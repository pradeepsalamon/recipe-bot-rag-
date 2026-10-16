"""
One question in, one answer out: the path every entry point uses (CLI, chat,
evals).

    validate -> [semantic cache lookup] -> agent -> [cache store] -> log -> [LangSmith mirror]

The bracketed steps are opt-in (PANTRY_CACHE=1, PANTRY_LANGSMITH=1). The
eval suite always bypasses the cache: it must measure the system, not
yesterday's answers.
"""
from . import agent, config, observability
from .cache import SemanticCache, skip_reason, store_reason
from .tracing import Trace, append_jsonl


class InvalidQuestion(ValueError):
    pass


_cache = None


def get_cache():
    global _cache
    if _cache is None:
        _cache = SemanticCache()
    return _cache


def validate(question):
    q = (question or "").strip()
    if not q:
        raise InvalidQuestion("The question is empty.")
    if len(q) > config.MAX_QUESTION_CHARS:
        raise InvalidQuestion(f"The question is too long ({len(q)} characters, limit "
                              f"{config.MAX_QUESTION_CHARS}). Please shorten it.")
    return q


async def answer(question, registry, *, source="cli", session_id=None, log_path=None,
                 on_event=None, use_cache=None, budgets=None):
    q = validate(question)
    trace = Trace(q, session_id=session_id, source=source)
    cache_on = config.CACHE["enabled"] if use_cache is None else use_cache
    cache_info = {"enabled": cache_on}

    if cache_on:
        reason = skip_reason(q)
        if reason:
            cache_info["skipped"] = reason
        else:
            with trace.span("cache.lookup", "cache") as sp:
                hit, sim = get_cache().lookup(q)
                sp.attrs.update({"hit": bool(hit), "best_similarity": sim,
                                 "entries": len(get_cache().entries)})
            cache_info["best_similarity"] = sim
            if hit:
                cache_info.update(hit=True, source_trace_id=hit["source_trace_id"])
                final = dict(hit["final"], refused=False, substitutions=[], invalid_citations=[], cached=True)
                record = agent.build_record(trace, q, final, [], None, 0, 0, 0.0, cache=cache_info)
                _finish(record, log_path)
                return {"trace_id": trace.trace_id, "final": final, "steps": [], "record": record}

    res = await agent.run(q, registry, trace=trace, on_event=on_event, budgets=budgets)

    if cache_on and "skipped" not in cache_info:
        why_not = store_reason(res["final"])
        if why_not is None:
            get_cache().store(q, res["final"], res["trace_id"],
                              res["record"]["cost_usd"], res["record"]["latency_ms"])
            cache_info["stored"] = True
        else:
            cache_info["not_stored"] = why_not
    res["record"]["cache"] = cache_info
    _finish(res["record"], log_path)
    return res


def _finish(record, log_path):
    default = config.EVAL_LOG if record["source"] == "eval" else config.REQUEST_LOG
    append_jsonl(log_path or default, record)
    observability.mirror(record)
