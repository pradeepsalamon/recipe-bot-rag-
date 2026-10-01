"""
multi_agent.py — Multi-agent orchestrator with substitution worker + allergen worker.

Architecture:
  Orchestrator (manager)
    ├── Substitution Worker — evaluates substitution viability only
    └── Allergen Worker     — evaluates allergen/nutrition correctness only

The orchestrator:
  1. Decomposes the cooking question into two sub-tasks
  2. Delegates to each specialist worker with a NARROW prompt + MINIMAL context
  3. Collects responses (with retry on failure)
  4. Synthesises a final verdict

Every hand-off logs token counts so we can compute the context re-send multiplier.
"""

import json
import time
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

load_dotenv(override=True)

# ─── Global hand-off log ───
handoff_log = []

# ─── Flag: inject failure on a specific case ───
INJECT_FAILURE_CASE = "case_22"  # Allergen worker returns 500 on this case


# ═══════════════════════════════════════════════════════════
# SUBSTITUTION WORKER
# ═══════════════════════════════════════════════════════════

SUBSTITUTION_WORKER_PROMPT = """You are a specialist substitution evaluator.
Your ONLY job is to assess whether a recipe substitution is culinarily viable and palatable.

You do NOT assess allergens, nutrition, or recipe formatting — another specialist handles that.

Evaluate:
- Is the substitution reasonable in a culinary context?
- Would the resulting dish be palatable?
- Does the recipe correctly apply the substitution?

Respond in JSON:
{
  "substitution_viable": true/false,
  "reasoning": "brief explanation"
}
"""


def call_substitution_worker(case: dict) -> dict:
    """
    Call the substitution worker with only substitution-relevant context.
    Returns: dict with verdict, tokens, latency_ms, raw_response.
    """
    llm = ChatGroq(
        model="openai/gpt-oss-20b",
        temperature=0,
        max_retries=5,
    )

    gen = case["generated_recipe"]
    ingredients = "\n".join(gen.get("ingredients", []))
    method = "\n".join(gen.get("method", []))

    # NARROW context: only what the substitution worker needs
    human_msg = f"""Evaluate this substitution:

Input Recipe: {case["input_recipe"]}
Requested Substitution: {case["requested_substitution"]}

Generated Title: {gen.get("title", "N/A")}
Ingredients:
{ingredients}

Method:
{method}

Is this substitution culinarily viable? Respond as JSON."""

    messages = [
        SystemMessage(content=SUBSTITUTION_WORKER_PROMPT.strip()),
        HumanMessage(content=human_msg),
    ]

    start = time.time()
    for attempt in range(5):
        try:
            response = llm.invoke(messages)
            break
        except Exception as e:
            if '429' in str(e) or 'RESOURCE_EXHAUSTED' in str(e):
                wait = 60 * (attempt + 1)
                print(f"    Rate limited (sub worker, {case['id']}), waiting {wait}s...", flush=True)
                time.sleep(wait)
            else:
                raise
    latency_ms = (time.time() - start) * 1000

    content = response.content
    if isinstance(content, list) and len(content) > 0:
        if isinstance(content[0], dict) and "text" in content[0]:
            content = content[0]["text"]
        else:
            content = str(content[0])

    usage = getattr(response, "usage_metadata", None)
    prompt_tokens = 0
    completion_tokens = 0
    if usage and isinstance(usage, dict):
        prompt_tokens = usage.get("input_tokens", 0) or 0
        completion_tokens = usage.get("output_tokens", 0) or 0

    total_tokens = prompt_tokens + completion_tokens

    # Log this hand-off
    handoff_entry = {
        "handoff": "orchestrator -> substitution_worker",
        "case_id": case["id"],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "latency_ms": round(latency_ms, 2),
    }
    handoff_log.append(handoff_entry)

    # Parse result
    viable = False
    try:
        json_str = content
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]
        parsed = json.loads(json_str.strip())
        viable = parsed.get("substitution_viable", False)
    except (json.JSONDecodeError, IndexError):
        viable = "true" in content.lower()

    return {
        "substitution_viable": viable,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "latency_ms": round(latency_ms, 2),
        "raw_response": content,
    }


# ═══════════════════════════════════════════════════════════
# ALLERGEN WORKER
# ═══════════════════════════════════════════════════════════

ALLERGEN_WORKER_PROMPT = """You are a specialist allergen and nutrition evaluator.
Your ONLY job is to check allergen warnings and ingredient-method consistency.

You do NOT judge whether the substitution is palatable — another specialist handles that.

Evaluate:
1. If ingredients contain common allergens (gluten/wheat, peanuts, tree nuts, dairy/milk,
   eggs, soy, shellfish), is there a correct allergen warning?
2. Are any allergen claims fabricated (claiming allergens not in the ingredients)?
3. Does every ingredient mentioned in the method also appear in the ingredient list?

Respond in JSON:
{
  "allergen_check_passed": true/false,
  "recipe_integrity_passed": true/false,
  "allergen_issues": "brief explanation or 'none'"
}
"""


def call_allergen_worker(case: dict, inject_failure: bool = False) -> dict:
    """
    Call the allergen worker. If inject_failure is True, simulate a 500 error.
    Returns: dict with allergen_check_passed, recipe_integrity_passed, tokens, etc.
    """
    if inject_failure:
        # Simulate HTTP 500 — worker is down
        raise ConnectionError(
            f"HTTP 500 Internal Server Error: Allergen worker crashed on {case['id']}"
        )

    llm = ChatGroq(
        model="openai/gpt-oss-20b",
        temperature=0,
        max_retries=5,
    )

    gen = case["generated_recipe"]
    ingredients = "\n".join(gen.get("ingredients", []))
    method = "\n".join(gen.get("method", []))

    # NARROW context: only allergen-relevant fields
    human_msg = f"""Check allergens and recipe integrity:

Ingredients:
{ingredients}

Method:
{method}

Allergen Warning: {gen.get("allergen_warning", "None")}

Are allergen warnings correct and complete? Does every method ingredient appear in the list?
Respond as JSON."""

    messages = [
        SystemMessage(content=ALLERGEN_WORKER_PROMPT.strip()),
        HumanMessage(content=human_msg),
    ]

    start = time.time()
    for attempt in range(5):
        try:
            response = llm.invoke(messages)
            break
        except Exception as e:
            if '429' in str(e) or 'RESOURCE_EXHAUSTED' in str(e):
                wait = 60 * (attempt + 1)
                print(f"    Rate limited (allergen worker, {case['id']}), waiting {wait}s...", flush=True)
                time.sleep(wait)
            else:
                raise
    latency_ms = (time.time() - start) * 1000

    content = response.content
    if isinstance(content, list) and len(content) > 0:
        if isinstance(content[0], dict) and "text" in content[0]:
            content = content[0]["text"]
        else:
            content = str(content[0])

    usage = getattr(response, "usage_metadata", None)
    prompt_tokens = 0
    completion_tokens = 0
    if usage and isinstance(usage, dict):
        prompt_tokens = usage.get("input_tokens", 0) or 0
        completion_tokens = usage.get("output_tokens", 0) or 0

    total_tokens = prompt_tokens + completion_tokens

    # Log this hand-off
    handoff_entry = {
        "handoff": "orchestrator -> allergen_worker",
        "case_id": case["id"],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "latency_ms": round(latency_ms, 2),
    }
    handoff_log.append(handoff_entry)

    # Parse result
    allergen_ok = True
    integrity_ok = True
    allergen_issues = "none"
    try:
        json_str = content
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]
        parsed = json.loads(json_str.strip())
        allergen_ok = parsed.get("allergen_check_passed", True)
        integrity_ok = parsed.get("recipe_integrity_passed", True)
        allergen_issues = parsed.get("allergen_issues", "none")
    except (json.JSONDecodeError, IndexError):
        pass

    return {
        "allergen_check_passed": allergen_ok,
        "recipe_integrity_passed": integrity_ok,
        "allergen_issues": allergen_issues,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "latency_ms": round(latency_ms, 2),
        "raw_response": content,
    }


# ═══════════════════════════════════════════════════════════
# ORCHESTRATOR (SYNTHESIS)
# ═══════════════════════════════════════════════════════════

SYNTHESIS_PROMPT = """You are the orchestrator synthesising a final verdict from two specialist reports.

Substitution Worker Report:
{substitution_report}

Allergen Worker Report:
{allergen_report}

Rules:
- If EITHER specialist flagged a problem, the overall verdict is Fail.
- Do NOT drop caveats from the allergen worker to keep the answer tidy.
- Do NOT fabricate allergen claims that the allergen worker did not make.

Respond in JSON:
{{
  "overall_verdict": "Pass" or "Fail",
  "reasoning": "one-line explanation combining both reports"
}}
"""


def synthesise_verdict(sub_result: dict, allergen_result: dict, case: dict) -> dict:
    """
    Orchestrator synthesis step: combine worker reports into a final verdict.
    This step re-sends a summary of both worker outputs, which is the key
    source of context re-send overhead in multi-agent patterns.
    """
    llm = ChatGroq(
        model="openai/gpt-oss-20b",
        temperature=0,
        max_retries=5,
    )

    sub_report = json.dumps({
        "substitution_viable": sub_result["substitution_viable"],
        "raw_reasoning": sub_result["raw_response"][:300],
    })
    allergen_report = json.dumps({
        "allergen_check_passed": allergen_result["allergen_check_passed"],
        "recipe_integrity_passed": allergen_result["recipe_integrity_passed"],
        "allergen_issues": allergen_result.get("allergen_issues", "none"),
        "raw_reasoning": allergen_result["raw_response"][:300],
    })

    human_msg = SYNTHESIS_PROMPT.format(
        substitution_report=sub_report,
        allergen_report=allergen_report,
    )

    messages = [
        SystemMessage(content="You are a fair recipe evaluation orchestrator."),
        HumanMessage(content=human_msg),
    ]

    start = time.time()
    for attempt in range(5):
        try:
            response = llm.invoke(messages)
            break
        except Exception as e:
            if '429' in str(e) or 'RESOURCE_EXHAUSTED' in str(e):
                wait = 60 * (attempt + 1)
                print(f"    Rate limited (synthesis, {case['id']}), waiting {wait}s...", flush=True)
                time.sleep(wait)
            else:
                raise
    latency_ms = (time.time() - start) * 1000

    content = response.content
    if isinstance(content, list) and len(content) > 0:
        if isinstance(content[0], dict) and "text" in content[0]:
            content = content[0]["text"]
        else:
            content = str(content[0])

    usage = getattr(response, "usage_metadata", None)
    prompt_tokens = 0
    completion_tokens = 0
    if usage and isinstance(usage, dict):
        prompt_tokens = usage.get("input_tokens", 0) or 0
        completion_tokens = usage.get("output_tokens", 0) or 0

    total_tokens = prompt_tokens + completion_tokens

    # Log synthesis hand-off
    handoff_entry = {
        "handoff": "workers -> orchestrator_synthesis",
        "case_id": case["id"],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "latency_ms": round(latency_ms, 2),
    }
    handoff_log.append(handoff_entry)

    # Parse verdict
    verdict = "Fail"
    try:
        json_str = content
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]
        parsed = json.loads(json_str.strip())
        verdict = parsed.get("overall_verdict", "Fail")
    except (json.JSONDecodeError, IndexError):
        if "pass" in content.lower() and "fail" not in content.lower():
            verdict = "Pass"

    return {
        "case_id": case["id"],
        "verdict": verdict,
        "synthesis_tokens": total_tokens,
        "synthesis_latency_ms": round(latency_ms, 2),
        "raw_response": content,
    }


# ═══════════════════════════════════════════════════════════
# RUN ORCHESTRATOR ON ONE CASE
# ═══════════════════════════════════════════════════════════

def run_multi_agent(case: dict, inject_failure_on: str = None) -> dict:
    """
    Run the multi-agent orchestrator on a single case.
    If inject_failure_on matches the case id, the allergen worker returns a 500.
    """
    should_inject = (inject_failure_on and case["id"] == inject_failure_on)

    failure_record = None

    # Step 1: Call substitution worker
    sub_result = call_substitution_worker(case)
    time.sleep(4)

    # Step 2: Call allergen worker (with possible failure injection)
    allergen_result = None
    orchestrator_behaviour = None

    if should_inject:
        # First attempt — will fail with 500
        try:
            allergen_result = call_allergen_worker(case, inject_failure=True)
        except ConnectionError as e:
            failure_record = str(e)
            # Orchestrator RETRIES once
            print(f"    [FAILURE INJECTED] Allergen worker returned 500 on {case['id']}. Retrying...", flush=True)

            # Log the failed attempt
            handoff_log.append({
                "handoff": "orchestrator -> allergen_worker (FAILED — 500)",
                "case_id": case["id"],
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "latency_ms": 0,
                "error": "HTTP 500 Internal Server Error",
            })

            time.sleep(4)

            # Retry — this time allow it to succeed
            try:
                allergen_result = call_allergen_worker(case, inject_failure=False)
                orchestrator_behaviour = "retried"
                print(f"    [RETRY SUCCESS] Allergen worker succeeded on retry for {case['id']}.")
            except Exception:
                # If retry also fails, degrade to partial answer
                orchestrator_behaviour = "degraded"
                allergen_result = {
                    "allergen_check_passed": False,
                    "recipe_integrity_passed": False,
                    "allergen_issues": "UNAVAILABLE — allergen worker failed after retry",
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "latency_ms": 0,
                    "raw_response": "Worker unavailable",
                }
                handoff_log.append({
                    "handoff": "orchestrator -> allergen_worker (RETRY ALSO FAILED)",
                    "case_id": case["id"],
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "latency_ms": 0,
                    "error": "Retry failed — degraded to partial answer",
                })
    else:
        allergen_result = call_allergen_worker(case, inject_failure=False)

    time.sleep(4)

    # Step 3: Synthesis
    synthesis = synthesise_verdict(sub_result, allergen_result, case)

    # Aggregate tokens
    total_tokens = (
        sub_result["total_tokens"]
        + allergen_result["total_tokens"]
        + synthesis.get("synthesis_tokens", 0)
    )

    total_latency = (
        sub_result["latency_ms"]
        + allergen_result["latency_ms"]
        + synthesis.get("synthesis_latency_ms", 0)
    )

    return {
        "case_id": case["id"],
        "verdict": synthesis["verdict"],
        "total_tokens": total_tokens,
        "latency_ms": round(total_latency, 2),
        "sub_tokens": sub_result["total_tokens"],
        "allergen_tokens": allergen_result["total_tokens"],
        "synthesis_tokens": synthesis.get("synthesis_tokens", 0),
        "sub_result": sub_result,
        "allergen_result": allergen_result,
        "synthesis_result": synthesis,
        "failure_injected": should_inject,
        "orchestrator_behaviour": orchestrator_behaviour,
        "failure_record": failure_record,
    }


def run_all_multi_agent(cases: list, inject_failure_on: str = INJECT_FAILURE_CASE) -> list:
    """Run multi-agent orchestrator on all cases and return list of results."""
    results = []
    for case in cases:
        # Boundary refusal cases are always Pass
        if case.get("mode") == "Correct boundary refusal":
            results.append({
                "case_id": case["id"],
                "verdict": "Pass",
                "total_tokens": 0,
                "latency_ms": 0,
                "sub_tokens": 0,
                "allergen_tokens": 0,
                "synthesis_tokens": 0,
                "sub_result": {},
                "allergen_result": {},
                "synthesis_result": {},
                "failure_injected": False,
                "orchestrator_behaviour": None,
                "failure_record": None,
            })
            continue
        result = run_multi_agent(case, inject_failure_on=inject_failure_on)
        results.append(result)
        time.sleep(4)
    return results


if __name__ == "__main__":
    with open("eval_cases_10.json") as f:
        cases = json.load(f)

    print("Running multi-agent orchestrator on 10 eval cases...")
    results = run_all_multi_agent(cases)
    for r in results:
        inj = " [FAILURE INJECTED]" if r.get("failure_injected") else ""
        bhv = f" → {r['orchestrator_behaviour']}" if r.get("orchestrator_behaviour") else ""
        print(f"  {r['case_id']}: {r['verdict']} | tokens={r['total_tokens']} | latency={r['latency_ms']}ms{inj}{bhv}")

    with open("multi_agent_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to multi_agent_results.json")
    print(f"Hand-off log entries: {len(handoff_log)}")

    with open("handoff_log_raw.json", "w") as f:
        json.dump(handoff_log, f, indent=2)
    print("Hand-off log saved to handoff_log_raw.json")
