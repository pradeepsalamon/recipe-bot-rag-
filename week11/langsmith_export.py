"""
Mirror our request logs into LangSmith, so the same requests can be searched
in both tools and compared side by side.

Our JSONL record stays the source of truth. Each record becomes one LangSmith
trace:
  - root run (chain)    question -> answer, with our fields as metadata/tags
  - one child per span  same names, same latencies, same tokens and cost
The LangSmith run id IS our trace_id, so an id found in one tool opens the
same request in the other.

The LLM run gets the exact messages that were sent, and the retriever run
gets the actual documents. Neither is stored in our log - both are rebuilt
from prompt_version + chunk ids. If that rebuild works, the log really does
hold everything needed to replay a request.

Setup: put LANGSMITH_API_KEY=... in the repo's .env. Do NOT set
LANGSMITH_TRACING=true: that would make LangChain auto-trace the Chroma /
BM25 / Gemini calls a second time, as separate, duplicate traces.

    python langsmith_export.py check                   # key works? runs in project?
    python langsmith_export.py backfill                # last week's production log
    python langsmith_export.py backfill --file logs/eval_runs.jsonl
    python langsmith_export.py rebuild                 # after drill.py reset: re-sync prod
"""
import argparse
import atexit
import os
import uuid
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

import config
from tracing import read_logs

load_dotenv(config.REPO_ROOT / ".env", override=True)

# Our span names -> LangSmith run types (decides the icon and the viewer).
RUN_TYPES = {
    "retrieval.cold_start": "chain",
    "retrieval.embed": "embedding",
    "retrieval.dense": "retriever",
    "retrieval.bm25": "retriever",
    "retrieval.rrf_fuse": "retriever",
    "tool.recipe_facts": "tool",
    "cache.semantic_lookup": "chain",
    "generation.llm": "llm",
    "generation.llm_fallback": "llm",
}

_client = None


def enabled():
    return config.LANGSMITH["enabled"] and bool(os.getenv("LANGSMITH_API_KEY"))


def client():
    global _client
    if _client is None:
        from langsmith import Client
        _client = Client()
        # Runs are sent in the background; make sure nothing is lost on exit.
        atexit.register(_client.flush)
    return _client


def project_for(record):
    return config.LANGSMITH["projects"].get(record["source"], config.LANGSMITH["projects"]["default"])


def _docs(chunk_ids):
    """Chunk ids -> the documents, as LangSmith's retriever viewer expects."""
    import pipeline
    by_id = {d.metadata.get("chunk_id"): d for d in pipeline._load_store()["all_docs"]}
    return [by_id[c] for c in chunk_ids if c in by_id]


def _as_ls_docs(docs):
    return [{"page_content": d.page_content, "metadata": dict(d.metadata), "type": "Document"} for d in docs]


def _messages(record):
    """Rebuild the exact messages sent to the model from the log record."""
    import pipeline
    system_prompt, sha = pipeline.load_prompt(record["prompt_version"])
    docs = _docs(record["retrieved_context_ids"] + record["tool_context_ids"])
    user = f"Context:\n{pipeline.build_context(docs)}\n\nQuestion: {record['query']}"
    exact = sha == record["prompt_sha"]  # prompt file edited since? then say so
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user}], exact


def _span_io(record, span):
    """Inputs / outputs for one child run."""
    name = span["name"]
    if name == "retrieval.embed":
        return {"text": record["query"]}, {"tokens": span["tokens_in"]}
    if name in ("retrieval.dense", "retrieval.bm25"):
        return {"query": record["query"], "pool_k": span["attrs"].get("pool_k")}, {}
    if name == "retrieval.rrf_fuse":
        return {"query": record["query"]}, {"documents": _as_ls_docs(_docs(record["retrieved_context_ids"]))}
    if name == "tool.recipe_facts":
        return ({"recipe_ids": span["attrs"].get("recipe_ids")},
                {"documents": _as_ls_docs(_docs(record["tool_context_ids"]))})
    if name == "cache.semantic_lookup":
        cache = record.get("cache") or {}
        return {"query": record["query"]}, {"hit": cache.get("hit"),
                                            "best_similarity": cache.get("best_similarity"),
                                            "source_trace_id": cache.get("source_trace_id")}
    if name.startswith("generation"):
        messages, exact = _messages(record)
        return ({"messages": messages, "prompt_rebuilt_exactly": exact},
                {"choices": [{"message": {"role": "assistant", "content": record["answer"] or ""}}]})
    return {}, {}


def export(record):
    """Send one log record to LangSmith as a run tree."""
    from langsmith.run_trees import RunTree

    request_ts = datetime.fromisoformat(record["ts"])
    # LangSmith only accepts runs that start within +-24 h of "now" (it
    # rejected our 1 Oct traces with a 422). Live requests are always inside
    # that window. Older ones (the back-dated simulated week) go in at upload
    # time, and the real request time is kept in metadata + date/week tags,
    # which is what you filter on for "sometime last week" in LangSmith.
    now = datetime.now(timezone.utc)
    shifted = abs(now - request_ts) > timedelta(hours=23)
    start = now if shifted else request_ts
    iso_year, iso_week, _ = request_ts.isocalendar()

    cache = record.get("cache") or {}
    metadata = {
        "request_ts": record["ts"],
        "time_shifted_for_upload": shifted,
        "our_trace_id": record["trace_id"],
        "user_id": record["user_id"],
        "session_id": record["session_id"],
        "input_type": record["input_type"],
        "prompt_version": record["prompt_version"],
        "prompt_sha": record["prompt_sha"],
        "model": record["model"],
        "fallback_used": record["fallback_used"],
        "source": record["source"],
        "retrieved_context_ids": record["retrieved_context_ids"],
        "tool_context_ids": record["tool_context_ids"],
        "cost_usd": record["totals"]["cost_usd"],
        "latency_ms": record["totals"]["latency_ms"],
        "semantic_cache_hit": bool(cache.get("hit")),
    }
    if "output_tags" in record:
        metadata.update({f"output_{k}": v for k, v in record["output_tags"].items()})

    tags = [record["prompt_version"], record["input_type"], record["source"],
            f"date:{request_ts.date().isoformat()}", f"week:{iso_year}-W{iso_week:02d}"]
    if cache.get("hit"):
        tags.append("semantic-cache-hit")

    root = RunTree(
        id=uuid.UUID(record["trace_id"]),
        name="recipe-rag",
        run_type="chain",
        inputs={"question": record["query"]},
        start_time=start,
        project_name=project_for(record),
        extra={"metadata": metadata},
        tags=tags,
        ls_client=client(),
    )

    # Our spans run one after another, so each child starts where the
    # previous one ended. (Tiny gaps between spans are not recorded.)
    offset = 0.0
    for span in record["spans"]:
        inputs, outputs = _span_io(record, span)
        child_meta = {"attrs": span["attrs"]}
        if span["stage"] == "generation" and span["model"]:
            child_meta.update(ls_provider=span["attrs"].get("provider"), ls_model_name=span["model"])
        child = root.create_child(
            name=span["name"],
            run_type=RUN_TYPES.get(span["name"], "chain"),
            inputs=inputs,
            start_time=start + timedelta(milliseconds=offset),
            extra={"metadata": child_meta},
            tags=[span["stage"]],
        )
        if span["stage"] == "generation" and not span["error"]:
            # Hand LangSmith our own token + cost numbers, so both tools show
            # identical figures instead of two different price tables.
            price = config.PRICES[span["model"]]
            fresh_in = span["tokens_in"] - span.get("tokens_cached", 0)
            in_cost = (fresh_in * price["input"] + span.get("tokens_cached", 0) * price["cached_input"]) / 1e6
            out_cost = span["tokens_out"] * price["output"] / 1e6
            child.set(usage_metadata={
                "input_tokens": span["tokens_in"],
                "output_tokens": span["tokens_out"],
                "total_tokens": span["tokens_in"] + span["tokens_out"],
                "input_token_details": {"cache_read": span.get("tokens_cached", 0)},
                "output_token_details": {"reasoning": span["attrs"].get("reasoning_tokens") or 0},
                "input_cost": in_cost,
                "output_cost": out_cost,
                "total_cost": in_cost + out_cost,
            })
        offset += span["latency_ms"]
        child.end(outputs=outputs, error=span["error"],
                  end_time=start + timedelta(milliseconds=offset))

    root.end(outputs={"answer": record["answer"]}, error=record["error"],
             end_time=start + timedelta(milliseconds=record["totals"]["latency_ms"]))
    root.post(exclude_child_runs=False)


def export_safe(record):
    """Called from pipeline.answer(). Tracing must never break a request."""
    if not enabled():
        return
    try:
        export(record)
    except Exception as exc:
        print(f"[langsmith] export failed for {record['trace_id'][:8]}: {type(exc).__name__}: {exc}")


def cmd_check(args):
    if not os.getenv("LANGSMITH_API_KEY"):
        raise SystemExit("LANGSMITH_API_KEY is not set - add it to the repo's .env")
    projects = sorted(set(config.LANGSMITH["projects"].values()))
    for name in projects:
        try:
            n = sum(1 for _ in client().list_runs(project_name=name, is_root=True))
            print(f"{name}: {n} root runs")
        except Exception as exc:
            print(f"{name}: not found yet ({type(exc).__name__})")


def cmd_backfill(args):
    if not os.getenv("LANGSMITH_API_KEY"):
        raise SystemExit("LANGSMITH_API_KEY is not set - add it to the repo's .env")
    records = read_logs(config.WEEK_DIR / args.file)
    if args.limit:
        records = records[: args.limit]

    # Run ids are our trace ids, so anything already uploaded can be skipped
    # (re-posting the same id is rejected by LangSmith anyway).
    existing = set()
    for name in {project_for(r) for r in records}:
        try:
            existing |= {str(run.id) for run in client().list_runs(project_name=name, is_root=True)}
        except Exception:
            pass  # project doesn't exist yet
    records = [r for r in records if r["trace_id"] not in existing]
    print(f"{len(existing)} already in LangSmith, exporting {len(records)}")

    for i, rec in enumerate(records, 1):
        export(rec)
        if i % 20 == 0:
            print(f"  {i}/{len(records)}")
    client().flush()
    print(f"exported {len(records)} traces to {sorted({project_for(r) for r in records})}")


def cmd_rebuild(args):
    """Delete the prod project and re-upload it from our log.

    Our JSONL is the source of truth. After `drill.py reset` removes a
    planted record, LangSmith still has it; rebuilding keeps both tools
    holding exactly the same requests, so a drill comparison is fair.
    """
    name = config.LANGSMITH["projects"]["simulated_traffic"]
    try:
        client().delete_project(project_name=name)
        print(f"deleted LangSmith project {name}")
    except Exception as exc:
        print(f"nothing to delete ({type(exc).__name__})")
    args.file, args.limit = "logs/requests.jsonl", None
    cmd_backfill(args)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").set_defaults(func=cmd_check)
    sub.add_parser("rebuild").set_defaults(func=cmd_rebuild)
    b = sub.add_parser("backfill")
    b.add_argument("--file", default="logs/requests.jsonl", help="relative to week11/")
    b.add_argument("--limit", type=int)
    b.set_defaults(func=cmd_backfill)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
