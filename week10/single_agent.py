"""
single_agent.py — Single-agent pipeline for recipe substitution evaluation.

This agent handles the ENTIRE cooking question in one LLM call:
  - substitution viability check
  - allergen/nutrition assessment
  - synthesis of a final answer

It mirrors the existing Week-6 RAG single-agent approach but adds
token counting and latency tracking for the race comparison.
"""

import json
import time
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

load_dotenv(override=True)

# ─── System prompt: the single agent does everything ───
SINGLE_AGENT_SYSTEM_PROMPT = """You are a strict recipe-substitution evaluator.

Given an input recipe, a requested substitution, and the generated (substituted) recipe,
you must evaluate:

1. SUBSTITUTION VIABILITY:
   - Is the substitution culinarily viable and palatable?
   - Does the generated recipe correctly apply the requested substitution?

2. ALLERGEN & NUTRITION ASSESSMENT:
   - Are all allergen warnings correct and complete?
   - If the recipe contains common allergens (gluten, peanuts, tree nuts, dairy, eggs, soy, shellfish),
     is there a warning present?
   - Are any allergen claims fabricated (claiming allergens not actually present)?

3. RECIPE INTEGRITY:
   - Does every ingredient mentioned in the method also appear in the ingredient list?
   - Are servings and quantities properly formatted?

Respond in the following JSON format:
{
  "substitution_viable": true/false,
  "allergen_check_passed": true/false,
  "recipe_integrity_passed": true/false,
  "overall_verdict": "Pass" or "Fail",
  "reasoning": "brief explanation"
}
"""


def run_single_agent(case: dict) -> dict:
    """
    Run a single-agent evaluation on one case.
    Returns a dict with: verdict, tokens, latency_ms, raw_response.
    """
    llm = ChatGroq(
        model="openai/gpt-oss-20b",
        temperature=0,
        max_retries=5,
    )

    gen = case["generated_recipe"]
    ingredients = "\n".join(gen.get("ingredients", []))
    method = "\n".join(gen.get("method", []))

    human_msg = f"""Evaluate this recipe substitution:

Input Recipe: {case["input_recipe"]}
Requested Substitution: {case["requested_substitution"]}

Generated Recipe Title: {gen.get("title", "N/A")}
Servings: {gen.get("servings", "N/A")}

Ingredients:
{ingredients}

Method:
{method}

Allergen Warning: {gen.get("allergen_warning", "None")}

Provide your evaluation as JSON."""

    messages = [
        SystemMessage(content=SINGLE_AGENT_SYSTEM_PROMPT.strip()),
        HumanMessage(content=human_msg),
    ]

    start = time.time()
    # Retry loop for rate limiting
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = llm.invoke(messages)
            break
        except Exception as e:
            if '429' in str(e) or 'RESOURCE_EXHAUSTED' in str(e):
                wait = 60 * (attempt + 1)
                print(f"    Rate limited on {case['id']}, waiting {wait}s (attempt {attempt+1})...", flush=True)
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

    # Extract token usage from response metadata
    usage = getattr(response, "usage_metadata", None)
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    if usage and isinstance(usage, dict):
        prompt_tokens = usage.get("input_tokens", 0) or 0
        completion_tokens = usage.get("output_tokens", 0) or 0
        total_tokens = prompt_tokens + completion_tokens

    # Parse verdict from response
    verdict = "Fail"
    try:
        # Try to parse JSON from response
        json_str = content
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]
        parsed = json.loads(json_str.strip())
        verdict = parsed.get("overall_verdict", "Fail")
    except (json.JSONDecodeError, IndexError):
        if "pass" in content.lower():
            verdict = "Pass"

    return {
        "case_id": case["id"],
        "verdict": verdict,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "latency_ms": round(latency_ms, 2),
        "raw_response": content,
    }


def run_all_single_agent(cases: list) -> list:
    """Run single agent on all cases and return list of results."""
    results = []
    for case in cases:
        # Boundary refusal cases are always Pass
        if case.get("mode") == "Correct boundary refusal":
            results.append({
                "case_id": case["id"],
                "verdict": "Pass",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "latency_ms": 0,
                "raw_response": "Boundary refusal — auto-pass.",
            })
            continue
        result = run_single_agent(case)
        results.append(result)
        # Pause to avoid rate limiting (free tier is very restrictive)
        time.sleep(4)
    return results


if __name__ == "__main__":
    with open("eval_cases_10.json") as f:
        cases = json.load(f)

    print("Running single agent on 10 eval cases...")
    results = run_all_single_agent(cases)
    for r in results:
        print(f"  {r['case_id']}: {r['verdict']} | tokens={r['total_tokens']} | latency={r['latency_ms']}ms")

    with open("single_agent_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nResults saved to single_agent_results.json")
