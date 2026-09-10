"""
Week 7 Task Set B — Recipe Agent

A genuine think → act → observe → repeat loop.
The LLM dynamically decides which tool to call next based on intermediate results.
Enforces four budgets: max iterations, max tokens, max cost, wall-clock time.
"""

import os, sys, json, time, uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(override=True)

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from tools import TOOL_SCHEMAS, dispatch_tool

# ---------------------------------------------------------------------------
# Budget defaults
# ---------------------------------------------------------------------------
DEFAULT_MAX_ITERS = 10
DEFAULT_MAX_TOKENS = 30000
DEFAULT_MAX_COST = 0.10       # USD
DEFAULT_MAX_WALL_CLOCK = 120  # seconds

# ---------------------------------------------------------------------------
# Cost model (Gemini 2.0 Flash pricing per 1M tokens, approximate)
# ---------------------------------------------------------------------------
COST_PER_1M_INPUT = 0.15    # USD per 1M input tokens (Gemini Flash pricing)
COST_PER_1M_OUTPUT = 0.60   # USD per 1M output tokens (Gemini Flash pricing)

def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a given token count."""
    return (input_tokens * COST_PER_1M_INPUT / 1_000_000) + \
           (output_tokens * COST_PER_1M_OUTPUT / 1_000_000)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a Tamil Nadu recipe assistant with access to three tools.

TOOLS AVAILABLE:
1. search_recipe — Retrieve a recipe's full details (ingredients, method, yield, dietary info, allergens) by name or query. Always call this first.
2. scale_recipe — Scale ingredient quantities to a target serving count. Requires recipe_id and serving counts from search_recipe.
3. substitute_ingredient — Find a substitute for ONE ingredient that violates a dietary/allergen constraint. Call once per problematic ingredient.

WORKFLOW RULES:
- Always start with search_recipe to get the recipe details.
- If the user requests a different serving count, call scale_recipe after getting the recipe.
- If the user has dietary restrictions or allergen constraints, inspect the recipe's ingredients and call substitute_ingredient for EACH problematic ingredient.
- If a substitute itself violates another constraint (e.g., the substitute contains another allergen), call substitute_ingredient again with the new problematic ingredient.
- Once all adjustments are done, provide the final adapted recipe.

RESPONSE FORMAT:
When you have all the information, produce a final answer in this exact JSON format:
```json
{
  "title": "Recipe Name (adapted)",
  "servings": "Serves N",
  "ingredients": ["amount ingredient", ...],
  "method": ["step 1", "step 2", ...],
  "allergen_warning": "Warning: Contains X" or "None",
  "substitutions_made": ["original -> substitute (reason)", ...],
  "notes": "any relevant notes"
}
```

IMPORTANT:
- Call ONE tool at a time.
- After each tool result, decide what to do next.
- Do not guess information — always use the tools.
- When done, output ONLY the final JSON response, no tool calls.
"""


def _build_tool_call_prompt():
    """Build a description of available tools for the prompt."""
    lines = ["Available tools (call ONE at a time by responding with a JSON object):"]
    for t in TOOL_SCHEMAS:
        params_desc = []
        for pname, pinfo in t["parameters"]["properties"].items():
            req = "(required)" if pname in t["parameters"].get("required", []) else "(optional)"
            enum_str = f" One of: {pinfo['enum']}" if "enum" in pinfo else ""
            params_desc.append(f"    - {pname} ({pinfo['type']}) {req}: {pinfo['description']}{enum_str}")
        lines.append(f"\n  {t['name']}: {t['description']}")
        lines.append("  Parameters:")
        lines.extend(params_desc)
    lines.append('\nTo call a tool, respond with EXACTLY this JSON format:')
    lines.append('{"tool": "<tool_name>", "arguments": {<param>: <value>, ...}}')
    lines.append('\nWhen you are done and ready to give the final answer, respond with the final JSON recipe (no tool call wrapper).')
    return "\n".join(lines)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


def _parse_tool_call(text: str) -> tuple:
    """
    Try to parse a tool call from the model's response.
    Returns (tool_name, arguments) or (None, None) if it's a final answer.
    """
    text = text.strip()

    # Try to find a JSON object with "tool" key
    # Handle cases where the model wraps in markdown code blocks
    json_text = text
    if "```json" in json_text:
        start = json_text.index("```json") + 7
        end = json_text.index("```", start) if "```" in json_text[start:] else len(json_text)
        json_text = json_text[start:start + json_text[start:].index("```")] if "```" in json_text[start:] else json_text[start:]
    elif "```" in json_text:
        start = json_text.index("```") + 3
        end_pos = json_text.find("```", start)
        if end_pos > 0:
            json_text = json_text[start:end_pos]

    json_text = json_text.strip()

    try:
        parsed = json.loads(json_text)
        if isinstance(parsed, dict) and "tool" in parsed:
            return parsed["tool"], parsed.get("arguments", {})
        # It's a JSON dict but not a tool call — likely the final answer
        return None, None
    except json.JSONDecodeError:
        pass

    # Try to find embedded JSON
    brace_start = text.find("{")
    brace_end = text.rfind("}") + 1
    if brace_start >= 0 and brace_end > brace_start:
        try:
            candidate = json.loads(text[brace_start:brace_end])
            if isinstance(candidate, dict) and "tool" in candidate:
                return candidate["tool"], candidate.get("arguments", {})
            return None, None
        except json.JSONDecodeError:
            pass

    return None, None


def run_agent(
    user_request: str,
    request_id: str = None,
    max_iters: int = DEFAULT_MAX_ITERS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_cost: float = DEFAULT_MAX_COST,
    max_wall_clock: float = DEFAULT_MAX_WALL_CLOCK,
    temperature: float = 0,
    log_callback=None,
):
    """
    Run the recipe agent loop.

    Returns a dict with:
      - response: the final answer (str or dict)
      - steps: list of step logs
      - metrics: {iterations, total_input_tokens, total_output_tokens, total_tokens, cost, latency_ms}
      - terminated_by: None or the budget that fired
    """
    if request_id is None:
        request_id = str(uuid.uuid4())[:8]

    llm = ChatGoogleGenerativeAI(model="gemini-3.6-flash", temperature=temperature)

    full_system = SYSTEM_PROMPT + "\n\n" + _build_tool_call_prompt()

    messages = [
        SystemMessage(content=full_system),
        HumanMessage(content=user_request),
    ]

    steps = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    terminated_by = None
    final_response = None

    start_time = time.time()

    def _log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    _log(f"\n[RUN START] request_id={request_id}")
    _log(f"  request: {user_request}")
    _log(f"  budgets: max_iters={max_iters}, max_tokens={max_tokens}, max_cost={max_cost}, max_wall_clock={max_wall_clock}")

    for iteration in range(1, max_iters + 1):
        elapsed = time.time() - start_time

        # --- Budget check: wall-clock ---
        if elapsed > max_wall_clock:
            terminated_by = "max_wall_clock"
            _log(f"\n[BUDGET] budget=max_wall_clock, limit={max_wall_clock}s, actual={elapsed:.1f}s")
            _log("[AGENT TERMINATED] reason=max_wall_clock")
            break

        # --- Budget check: tokens ---
        if total_input_tokens + total_output_tokens >= max_tokens:
            terminated_by = "max_tokens"
            _log(f"\n[BUDGET] budget=max_tokens, limit={max_tokens}, actual={total_input_tokens + total_output_tokens}")
            _log("[AGENT TERMINATED] reason=max_tokens")
            break

        # --- Budget check: cost ---
        if total_cost >= max_cost:
            terminated_by = "max_cost"
            _log(f"\n[BUDGET] budget=max_cost, limit=${max_cost}, actual=${total_cost:.6f}")
            _log("[AGENT TERMINATED] reason=max_cost")
            break

        _log(f"\n[STEP {iteration}]")

        # Call the LLM
        try:
            response = llm.invoke(messages)
        except Exception as e:
            _log(f"  LLM call failed: {e}")
            final_response = {"error": str(e)}
            terminated_by = "error"
            break

        content = response.content
        if isinstance(content, list):
            if len(content) > 0 and isinstance(content[0], dict) and "text" in content[0]:
                content = content[0]["text"]
            else:
                content = str(content)

        # Token accounting
        usage = getattr(response, "usage_metadata", None) or {}
        if isinstance(usage, dict):
            iter_input = usage.get("input_tokens", 0)
            iter_output = usage.get("output_tokens", 0)
        else:
            iter_input = getattr(usage, "input_tokens", 0)
            iter_output = getattr(usage, "output_tokens", 0)

        if iter_input == 0 and iter_output == 0:
            # Estimate from text length
            msg_text = "".join(m.content if isinstance(m.content, str) else str(m.content) for m in messages)
            iter_input = _estimate_tokens(msg_text)
            iter_output = _estimate_tokens(content)

        total_input_tokens += iter_input
        total_output_tokens += iter_output
        iter_cost = estimate_cost(iter_input, iter_output)
        total_cost += iter_cost

        _log(f"  tokens: input={iter_input}, output={iter_output}, cost=${iter_cost:.6f}")

        # Parse the response
        tool_name, tool_args = _parse_tool_call(content)

        if tool_name:
            _log(f"  action={tool_name}")
            _log(f"  input={json.dumps(tool_args, default=str)}")

            # Execute the tool
            tool_result = dispatch_tool(tool_name, tool_args)
            tool_result_str = json.dumps(tool_result, default=str, indent=2)

            _log(f"\n[TOOL RESULT]")
            _log(f"  {tool_result_str[:500]}{'...' if len(tool_result_str) > 500 else ''}")

            step = {
                "step": iteration,
                "action": tool_name,
                "input": tool_args,
                "result": tool_result,
                "input_tokens": iter_input,
                "output_tokens": iter_output,
                "cost": iter_cost,
            }
            steps.append(step)

            # Add the exchange to messages
            messages.append(AIMessage(content=content))
            messages.append(HumanMessage(content=f"Tool result for {tool_name}:\n{tool_result_str}"))

        else:
            # Final answer
            _log(f"  decision=final_answer")
            step = {
                "step": iteration,
                "action": "final_answer",
                "input_tokens": iter_input,
                "output_tokens": iter_output,
                "cost": iter_cost,
            }
            steps.append(step)

            # Try to parse as JSON
            try:
                # Extract JSON from the content
                json_text = content
                if "```json" in json_text:
                    start = json_text.index("```json") + 7
                    end = json_text.find("```", start)
                    json_text = json_text[start:end] if end > 0 else json_text[start:]
                elif "```" in json_text:
                    start = json_text.index("```") + 3
                    end = json_text.find("```", start)
                    json_text = json_text[start:end] if end > 0 else json_text[start:]

                brace_start = json_text.find("{")
                brace_end = json_text.rfind("}") + 1
                if brace_start >= 0 and brace_end > brace_start:
                    final_response = json.loads(json_text[brace_start:brace_end])
                else:
                    final_response = content
            except json.JSONDecodeError:
                final_response = content

            _log(f"\n[FINAL]")
            if isinstance(final_response, dict):
                _log(f"  title: {final_response.get('title', 'N/A')}")
                _log(f"  servings: {final_response.get('servings', 'N/A')}")
                _log(f"  ingredients: {len(final_response.get('ingredients', []))} items")
                _log(f"  substitutions: {final_response.get('substitutions_made', [])}")
            else:
                _log(f"  {str(final_response)[:300]}")
            break
    else:
        # Loop exhausted — max iterations reached
        terminated_by = "max_iterations"
        _log(f"\n[BUDGET] budget=max_iterations, limit={max_iters}, actual={max_iters}")
        _log("[AGENT TERMINATED] reason=max_iterations")

    elapsed_ms = (time.time() - start_time) * 1000

    metrics = {
        "iterations": len(steps),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_tokens": total_input_tokens + total_output_tokens,
        "cost": round(total_cost, 6),
        "latency_ms": round(elapsed_ms, 1),
    }

    _log(f"\n[RUN END] request_id={request_id}")
    _log(f"  iterations={metrics['iterations']}, tokens={metrics['total_tokens']}, cost=${metrics['cost']}, latency={metrics['latency_ms']}ms")
    if terminated_by:
        _log(f"  terminated_by={terminated_by}")

    return {
        "request_id": request_id,
        "response": final_response,
        "steps": steps,
        "metrics": metrics,
        "terminated_by": terminated_by,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = "Find me the Ven Pongal recipe scaled to 8 servings, and make it dairy-free."

    result = run_agent(query)
    print("\n" + "=" * 60)
    print("FINAL RESULT:")
    print(json.dumps(result["response"], indent=2, default=str))
    print(f"\nMetrics: {result['metrics']}")
    if result["terminated_by"]:
        print(f"Terminated by: {result['terminated_by']}")
