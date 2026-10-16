"""
LangSmith mirror (week 11's langsmith_export.py, adapted to the agent).

OFF unless PANTRY_LANGSMITH=1 and LANGSMITH_API_KEY is set. Our JSONL log
stays the source of truth; LangSmith gets a copy of each request as a run
tree with the same ids, nesting, latencies, tokens and cost:

    pantry-agent (root, run id == our trace_id)
      agent
        llm#1        (usage + cost: our numbers, not LangSmith's price table)
        search_recipes  (tool, MCP hop)
        check_allergens (tool, MCP hop)
        llm#2 ...
      cache.lookup   (when the cache is on)

What leaves the machine is exactly the redacted log record: the question and
answer with health statements masked, allergen arguments as codes only, no
user id. Spans written by the MCP server process are not mirrored (they live
in logs/mcp_spans.jsonl); the client-side tool span already carries the hop.

Mirroring must never break or slow a request: the langsmith client batches
in a background thread, failures are counted and reported once on stderr,
and pending runs are flushed at exit.

Do NOT set LANGSMITH_TRACING=true: LangChain would then auto-trace the
Chroma / embedding calls as separate duplicate traces. The MCP server is
started with LANGSMITH_TRACING=false for the same reason.
"""
import atexit
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

from . import config

_RUN_TYPES = {"agent": "chain", "llm": "llm", "mcp": "tool", "tool": "tool", "cache": "chain",
              "retrieval": "retriever", "safety": "tool"}
_client = None
_failures = 0


def enabled():
    return config.LANGSMITH["enabled"] and bool(os.getenv("LANGSMITH_API_KEY"))


def client():
    global _client
    if _client is None:
        from langsmith import Client
        _client = Client()
        atexit.register(_flush)
    return _client


def _flush():
    try:
        if _client is not None:
            _client.flush()
    except Exception:
        pass


def project_for(record):
    return config.LANGSMITH["projects"].get(record.get("source"), config.LANGSMITH["projects"]["cli"])


def _ts(s):
    return datetime.fromisoformat(s)


def _usage(span):
    price = config.PRICES.get(span["model"] or "")
    if not price:
        return None
    cached = span.get("tokens_cached", 0)
    in_cost = ((span["tokens_in"] - cached) * price["input"] + cached * price["cached_input"]) / 1e6
    out_cost = span["tokens_out"] * price["output"] / 1e6
    return {
        "input_tokens": span["tokens_in"], "output_tokens": span["tokens_out"],
        "total_tokens": span["tokens_in"] + span["tokens_out"],
        "input_token_details": {"cache_read": cached},
        "output_token_details": {"reasoning": span["attrs"].get("reasoning_tokens") or 0},
        "input_cost": in_cost, "output_cost": out_cost, "total_cost": in_cost + out_cost,
    }


def build_tree(record, ls_client=None, now=None):
    """Our log record -> a LangSmith RunTree (not posted). Pure apart from
    the client handle, so tests can inspect exactly what would be sent."""
    from langsmith.run_trees import RunTree

    now = now or datetime.now(timezone.utc)
    req_ts = _ts(record["ts"])
    # LangSmith rejects runs starting more than ~24 h from now (week 11 hit a
    # 422 on back-dated traces). Old records are shifted; real time is kept.
    shift = (now - req_ts) if abs(now - req_ts) > timedelta(hours=23) else timedelta(0)
    cache = record.get("cache") or {}
    tags = [record["release"], record["prompt_version"], record["source"], f"date:{req_ts.date().isoformat()}"]
    if cache.get("hit"):
        tags.append("semantic-cache-hit")
    if record.get("refused"):
        tags.append("refused")
    if record.get("terminated_by"):
        tags.append(f"stopped:{record['terminated_by']}")

    root = RunTree(
        id=uuid.UUID(record["trace_id"]),
        name="pantry-agent",
        run_type="chain",
        inputs={"question": record["query"]},
        start_time=req_ts + shift,
        project_name=project_for(record),
        tags=tags,
        extra={"metadata": {
            "our_trace_id": record["trace_id"], "request_ts": record["ts"],
            "time_shifted_for_upload": bool(shift), "session_id": record["session_id"],
            "model": record["model"], "allergen_codes_checked": record["allergen_codes_checked"],
            "tools_called": record["tools_called"], "cost_usd": record["cost_usd"],
            "latency_ms": record["latency_ms"], "semantic_cache": cache,
            "invalid_citations": record.get("invalid_citations", []),
        }},
        ls_client=ls_client or client(),
    )

    # Parents before children, by structure: on Windows spans opened within
    # the same clock tick share a start_ts, so sorting by time alone can put
    # a child first and flatten the tree.
    ids = {s["span_id"] for s in record["spans"]}
    kids = {}
    for s in sorted(record["spans"], key=lambda s: s["start_ts"]):
        kids.setdefault(s["parent_id"] if s["parent_id"] in ids else None, []).append(s)
    ordered, stack = [], list(reversed(kids.get(None, [])))
    while stack:
        s = stack.pop()
        ordered.append(s)
        stack.extend(reversed(kids.get(s["span_id"], [])))

    runs = {}
    for span in ordered:
        parent = runs.get(span["parent_id"], root)
        start = _ts(span["start_ts"]) + shift
        inputs = {"args": span["attrs"]["args"]} if "args" in span["attrs"] else {}
        child = parent.create_child(
            name=span["name"], run_type=_RUN_TYPES.get(span["stage"], "chain"),
            inputs=inputs, start_time=start, tags=[span["stage"]],
            extra={"metadata": {"attrs": {k: v for k, v in span["attrs"].items() if k != "args"}}},
        )
        if span["stage"] == "llm" and span["model"] and not span["error"]:
            usage = _usage(span)
            if usage:
                child.set(usage_metadata=usage)
        runs[span["span_id"]] = child

    # end children after all are created (a parent's end time is its own latency)
    for span in record["spans"]:
        run = runs[span["span_id"]]
        outputs = {"result": span["attrs"]["result"]} if "result" in span["attrs"] else {}
        run.end(outputs=outputs, error=span["error"],
                end_time=_ts(span["start_ts"]) + shift + timedelta(milliseconds=span["latency_ms"]))
    root.end(outputs={"answer": record["answer"], "citations": record["citations"],
                      "refused": record["refused"]},
             end_time=req_ts + shift + timedelta(milliseconds=record["latency_ms"]))
    return root


def mirror(record):
    """Called once per request by service.py. Never raises."""
    global _failures
    if not enabled():
        return False
    try:
        build_tree(record).post(exclude_child_runs=False)
        return True
    except Exception as exc:
        _failures += 1
        if _failures == 1:
            print(f"[langsmith] mirror failed ({type(exc).__name__}: {str(exc)[:120]}); "
                  "requests are unaffected, further failures are silent", file=sys.stderr)
        return False


def check():
    if not os.getenv("LANGSMITH_API_KEY"):
        return "LANGSMITH_API_KEY is not set"
    out = []
    for name in sorted(set(config.LANGSMITH["projects"].values())):
        try:
            p = client().read_project(project_name=name, include_stats=True)
            out.append(f"{name}: {getattr(p, 'run_count', None) or 0} runs "
                       f"(last run {getattr(p, 'last_run_start_time', None) or '-'})")
        except Exception as exc:
            kind = "not created yet" if "NotFound" in type(exc).__name__ else "not reachable"
            out.append(f"{name}: {kind} ({type(exc).__name__})")
    return "\n".join(out)


def backfill(records):
    sent = 0
    for r in records:
        try:
            build_tree(r).post(exclude_child_runs=False)
            sent += 1
        except Exception as exc:
            print(f"[langsmith] {r['trace_id'][:12]}: {type(exc).__name__}: {str(exc)[:100]}", file=sys.stderr)
    _flush()
    return sent
