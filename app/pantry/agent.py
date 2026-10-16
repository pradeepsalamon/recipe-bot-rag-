"""
The agent: week 7's hand-built think -> act -> observe loop with its four
budgets (iterations, tokens, cost, wall-clock), running against the
integrated system:

  - tools come from the MCP server(s) in mcp_servers.json, discovered at
    runtime (week 9), plus one local tool, the scaling calculator;
  - Groq native function calling (week 7's "reply with a JSON blob" parser
    was its most common failure);
  - every LLM call and tool call is a span on one Trace (week 11); MCP calls
    carry the trace id across the process boundary.

Production behaviour:
  - several tool calls in one model turn run concurrently;
  - a failing or timed-out tool comes back to the model as a tool error, it
    never crashes the request;
  - an LLM outage ends the run with a clean "unavailable" answer
    (terminated_by="llm_error");
  - tool schemas are sorted by name so the prompt prefix is byte-identical
    between requests (Groq's prompt cache only hits on identical prefixes);
  - the model sees compact tool results (pantry/compact.py, ~41% fewer
    characters); traces keep the one-line summary.

Logging, caching and the LangSmith mirror live in pantry/service.py.
"""
import asyncio
import json
import re
import time

from . import compact, config, corpus, llm, safety, scaling
from .tracing import Trace, redact

PROMPT_FILE = config.APP_DIR / "prompts" / "agent_v1.txt"
PROMPT_VERSION = "agent_v1"

LOCAL_TOOLS = [{
    "type": "function",
    "function": {
        "name": "scale_recipe",
        "description": ("Scale a recipe-version's ingredient quantities to a target yield (same unit as "
                        "the recipe's yield, e.g. 48 for 48 fingers, 8 for 8 servings). Returns scaled "
                        "quantities; times and oven temperature are returned UNCHANGED."),
        "parameters": {
            "type": "object",
            "properties": {
                "recipe_id": {"type": "string"},
                "version": {"type": "string", "description": "e.g. original or reformulated-2025"},
                "target_amount": {"type": "number", "description": "target yield amount"},
            },
            "required": ["recipe_id", "version", "target_amount"],
        },
    },
}]
_LOCAL_NAMES = {t["function"]["name"] for t in LOCAL_TOOLS}

_ALLERGY_ARGS = ("allergies", "exclude_allergens", "avoid")
_CITATION = re.compile(r"\[([a-z0-9_]+@[a-z0-9\-]+)\]")
_UNAVAILABLE = ("Sorry, I can't answer right now: the assistant is temporarily unavailable. "
                "Please try again in a minute. (No recipe or allergen advice was given.)")


def _prompt():
    return PROMPT_FILE.read_text(encoding="utf-8")


def _local_call(name, args):
    if name == "scale_recipe":
        r = corpus.get(str(args.get("recipe_id", "")), str(args.get("version", "")))
        if r is None:
            return {"error": f"No recipe {args.get('recipe_id')}@{args.get('version')}."}
        try:
            target = float(args["target_amount"])
        except (KeyError, TypeError, ValueError):
            return {"error": "target_amount must be a number."}
        if not 0 < target <= 10_000:
            return {"error": "target_amount must be between 0 and 10000."}
        return scaling.scale(r, target)
    return {"error": f"Unknown local tool {name}."}


def _loggable_args(args):
    """Allergy words are health data: log the normalised codes, not the words."""
    out = {}
    for k, v in args.items():
        if k in _ALLERGY_ARGS:
            codes, unknown = safety.normalise_allergies(v if isinstance(v, list) else [v])
            out[k + "_codes"] = codes
            if unknown:
                out[k + "_unknown_count"] = len(unknown)
        else:
            out[k] = v
    return out


def summary(name, result):
    """One line per tool result, for the live CLI view and the trace."""
    if not isinstance(result, dict):
        return str(result)[:120]
    if "error" in result:
        return f"ERROR {str(result['error'])[:100]}"
    try:
        if name == "check_allergens":
            s = f"{result['recipe']} [{result['status']}] -> {result['verdict']}"
            if result["contains_user_allergens"]:
                s += f" (contains {', '.join(result['contains_user_allergens'])})"
            if result["may_contain_user_allergens"]:
                s += f" (may contain {', '.join(result['may_contain_user_allergens'])})"
            return s
        if name in ("search_recipes", "match_pantry"):
            hits = [f"{h['recipe']}{'*' if h['status'] == 'superseded' else ''}" for h in result["results"]]
            s = ", ".join(hits) or "no results"
            if result.get("excluded_by_declaration"):
                s += f" | excluded: {', '.join(result['excluded_by_declaration'])}"
            return s + ("   (* = superseded)" if "*" in s else "")
        if name == "get_recipe":
            return f"{result.get('citation')} [{result.get('status')}]"
        if name == "scale_recipe":
            return f"{result['recipe']} x{result['factor']} (times unchanged)"
        if name == "find_substitution":
            return "; ".join(f"{o['substitute']} {o['allergens'] or ''}" for o in result["options"]) or "no options"
        if name == "safe_temperature":
            return f"{result.get('category')} {result.get('safe_internal_c')}°C" if result["found"] else "not in chart"
    except (KeyError, TypeError):
        pass
    return json.dumps(result, ensure_ascii=False)[:120]


def parse_final(text):
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    final = None
    if m:
        try:
            final = json.loads(m.group(0))
        except json.JSONDecodeError:
            final = None
    if not isinstance(final, dict) or not isinstance(final.get("answer"), str):
        final = {"answer": text, "citations": [], "recommended": [], "substitutions": [],
                 "refused": False, "parse_error": True}
    for k, default in (("citations", []), ("recommended", []), ("substitutions", []), ("refused", False)):
        if not isinstance(final.get(k), type(default)):
            final[k] = default
    final["citations"] = [c for c in final["citations"] if isinstance(c, str)]
    final["recommended"] = [c for c in final["recommended"] if isinstance(c, str)]
    final["substitutions"] = [s for s in final["substitutions"] if isinstance(s, dict)]
    inline = _CITATION.findall(final["answer"])
    final["citations"] = sorted(set(final["citations"]) | set(inline))
    final["invalid_citations"] = [c for c in final["citations"] if corpus.get_by_key(c) is None]
    return final


async def _call_tool(registry, trace, root, c):
    """Run one tool call inside its own span. Never raises."""
    name = c.function.name
    try:
        args = json.loads(c.function.arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError
        result = None
    except (json.JSONDecodeError, ValueError):
        args, result = {}, {"error": "arguments were not a valid JSON object"}
    local = name in _LOCAL_NAMES
    with trace.span(name, "tool" if local else "mcp", parent_id=root.span_id) as tsp:
        tsp.attrs["args"] = _loggable_args(args)
        tsp.attrs["server"] = "local" if local else registry.server_of(name)
        if result is None:
            if local:
                result = _local_call(name, args)
            else:
                result = await registry.call(name, args, trace.trace_id, tsp.span_id)
        tsp.attrs["result"] = summary(name, result)
        if isinstance(result, dict) and "error" in result:
            tsp.attrs["tool_error"] = True
    return name, args, result


async def run(question, registry, trace=None, on_event=None, budgets=None):
    """Answer one question. Returns {trace_id, final, steps, record}; does not log."""
    budgets = dict(config.BUDGETS, **(budgets or {}))
    trace = trace or Trace(question)
    emit = on_event or (lambda *a: None)
    tools = sorted(registry.schemas() + LOCAL_TOOLS, key=lambda t: t["function"]["name"])
    messages = [{"role": "system", "content": _prompt()}, {"role": "user", "content": question}]

    steps, final, terminated_by = [], None, None
    tok_in = tok_out = 0
    cost = 0.0
    t0 = time.time()

    with trace.span("agent", "agent") as root:
        root.attrs.update({"prompt_version": PROMPT_VERSION, "release": config.RELEASE,
                           "tools_discovered": sorted(registry.tools), "tools_local": sorted(_LOCAL_NAMES)})
        for it in range(1, budgets["max_iters"] + 1):
            if time.time() - t0 > budgets["max_wall_clock_s"]:
                terminated_by = "max_wall_clock"
                break
            if tok_in + tok_out >= budgets["max_tokens"]:
                terminated_by = "max_tokens"
                break
            if cost >= budgets["max_cost_usd"]:
                terminated_by = "max_cost"
                break

            try:
                with trace.span(f"llm#{it}", "llm", parent_id=root.span_id) as sp:
                    # the sync HTTP call runs in a thread so the MCP session's
                    # event loop keeps servicing its stdio streams meanwhile
                    msg = await asyncio.to_thread(llm.chat, messages, sp, tools)
            except llm.LLMError as exc:
                terminated_by = "llm_error"
                root.attrs["llm_error"] = str(exc)[:200]
                break
            tok_in += sp.tokens_in
            tok_out += sp.tokens_out
            cost += sp.cost_usd or 0

            calls = msg.tool_calls or []
            if not calls:
                final = parse_final(msg.content)
                steps.append({"step": it, "action": "final_answer"})
                break

            messages.append({"role": "assistant", "content": msg.content or "",
                             "tool_calls": [{"id": c.id, "type": "function",
                                             "function": {"name": c.function.name,
                                                          "arguments": c.function.arguments or "{}"}}
                                            for c in calls]})
            results = await asyncio.gather(*(_call_tool(registry, trace, root, c) for c in calls))
            for c, (name, args, result) in zip(calls, results):
                steps.append({"step": it, "action": name, "input": args, "result": result})
                emit("tool", name, args, summary(name, result))
                messages.append({"role": "tool", "tool_call_id": c.id,
                                 "content": compact.dumps(compact.for_model(name, result))[:8000]})
        else:
            terminated_by = "max_iters"

        if final is None:
            text = (_UNAVAILABLE if terminated_by == "llm_error"
                    else f"I could not finish this request (stopped by {terminated_by}). "
                         "No recipe or allergen advice was given.")
            final = {"answer": text, "citations": [], "recommended": [], "substitutions": [],
                     "refused": True, "invalid_citations": [], "terminated": True}
        root.attrs["terminated_by"] = terminated_by

    return {"trace_id": trace.trace_id, "final": final, "steps": steps,
            "record": build_record(trace, question, final, steps, terminated_by, tok_in, tok_out, cost)}


def build_record(trace, question, final, steps, terminated_by, tok_in, tok_out, cost, cache=None):
    tools_called = [s["action"] for s in steps if s["action"] != "final_answer"]
    checked_codes = sorted({c for s in steps if s["action"] == "check_allergens"
                            for c in safety.normalise_allergies(s["input"].get("allergies", []) or [])[0]})
    return {
        "trace_id": trace.trace_id,
        "ts": trace.ts.isoformat(),
        "session_id": trace.session_id,
        "source": trace.source,
        "release": config.RELEASE,
        "prompt_version": PROMPT_VERSION,
        "model": config.AGENT_MODEL,
        "query": redact(question),
        "allergen_codes_checked": checked_codes,
        "tools_called": tools_called,
        "answer": redact(final["answer"]),
        "citations": final["citations"],
        "recommended": final["recommended"],
        "substitutions": final["substitutions"],
        "refused": final["refused"],
        "invalid_citations": final.get("invalid_citations", []),
        "terminated_by": terminated_by,
        "cache": cache or {"enabled": False},
        "latency_ms": round(trace.elapsed_ms(), 1),
        "tokens_in": tok_in,
        "tokens_out": tok_out,
        "cost_usd": round(cost, 8),
        "spans": [s.to_dict() for s in trace.spans],
    }
