"""
The recipe RAG app from week 3, rebuilt so it watches itself.

Same retrieval (dense + BM25 fused with RRF) and same prompt as before, but
every request now produces one log record with:
  - who / when / which prompt version / what kind of question,
  - the question AND the answer (the drill needs both),
  - the chunk ids that went into the prompt,
  - a span per step with its own latency, tokens and cost.

Two caches sit around the model call:
  - semantic cache (ours, semantic_cache.py): checked right after the query
    is embedded; a hit skips retrieval and generation entirely.
  - prompt cache (Groq's): automatic on repeated prompt prefixes; we only
    log how many input tokens it reports as cached and bill them at the
    cached price.

Run one question by hand:
    python pipeline.py "Is Rasam dairy-free?" --user u_demo
    python pipeline.py "How much salt goes into idli?" --cache
"""
import argparse
import hashlib
import os
import time
import warnings
from datetime import datetime, timezone

from dotenv import load_dotenv

import config
import diet_rules
from semantic_cache import SemanticCache, is_eligible, worth_storing
from tracing import Trace, append_log, stage_totals

load_dotenv(config.REPO_ROOT / ".env", override=True)
warnings.filterwarnings("ignore")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")


# --------------------------------------------------------------------------
# Vector store + BM25, loaded once per process.
# The week-3 code rebuilt both on every question (~1-2 s each time). The
# corpus never changes at runtime, so we build them once and reuse them.
# --------------------------------------------------------------------------
_store = {}


def _load_store():
    if _store:
        return _store

    from langchain_chroma import Chroma
    from langchain_community.retrievers import BM25Retriever
    from langchain_core.documents import Document
    from langchain_huggingface import HuggingFaceEmbeddings

    embeddings = HuggingFaceEmbeddings(model_name=config.EMBED_MODEL)
    db = Chroma(
        collection_name=config.COLLECTION,
        embedding_function=embeddings,
        persist_directory=str(config.CHROMA_DIR),
    )
    raw = db.get()
    all_docs = [
        Document(page_content=text, metadata=meta)
        for text, meta in zip(raw["documents"], raw["metadatas"])
    ]

    # A fingerprint of the corpus text. If the recipes are re-ingested, the
    # semantic cache fingerprint changes and old cached answers stop matching.
    corpus = "".join(sorted(d.page_content for d in all_docs))

    _store.update(
        embeddings=embeddings,
        db=db,
        all_docs=all_docs,
        bm25_docs=BM25Retriever.from_documents(all_docs),
        corpus_sha=hashlib.sha256(corpus.encode()).hexdigest()[:10],
    )
    return _store


def _count_embed_tokens(text):
    # Only used for the retrieval line of the cost report. The embedder is
    # local so the price is 0, but the token count tells us what a hosted
    # embedding API would charge if we ever moved off CPU.
    try:
        tokenizer = _store["embeddings"]._client.tokenizer
        return len(tokenizer.encode(text))
    except Exception:
        return len(text.split())


# --------------------------------------------------------------------------
# Retrieval: one span per step so we can see which part is slow.
# The query is embedded once and the vector is shared by the semantic cache
# lookup and the dense search.
# --------------------------------------------------------------------------
def embed(trace, query):
    if not _store:
        # First request in a fresh process pays ~10 s to load MiniLM + Chroma.
        # Give it its own span; otherwise it hides as unexplained latency.
        with trace.span("retrieval.cold_start", "retrieval"):
            _load_store()

    with trace.span("retrieval.embed", "retrieval") as sp:
        vector = _store["embeddings"].embed_query(query)
        sp.set_usage(config.EMBED_MODEL, _count_embed_tokens(query), 0)
    return vector


def retrieve(trace, query, vector, top_k):
    store = _store
    pool_k = max(top_k * 4, 20)

    with trace.span("retrieval.dense", "retrieval") as sp:
        dense = store["db"].similarity_search_by_vector_with_relevance_scores(vector, k=pool_k)
        sp.attrs["pool_k"] = pool_k

    with trace.span("retrieval.bm25", "retrieval") as sp:
        bm25 = store["bm25_docs"]
        bm25.k = pool_k
        sparse = bm25.invoke(query)
        sp.attrs["pool_k"] = pool_k

    with trace.span("retrieval.rrf_fuse", "retrieval") as sp:
        # Reciprocal Rank Fusion, same constant (60) as the week-3 code.
        scores, by_id = {}, {}
        for ranked in ([d for d, _ in dense], sparse):
            for rank, doc in enumerate(ranked):
                cid = doc.metadata.get("chunk_id")
                by_id.setdefault(cid, doc)
                scores[cid] = scores.get(cid, 0) + 1 / (60 + rank + 1)
        best = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        docs = [by_id[cid] for cid, _ in best]
        sp.attrs["context_ids"] = [cid for cid, _ in best]
        sp.attrs["rrf_scores"] = [round(score, 5) for _, score in best]

    return docs


# --------------------------------------------------------------------------
# Tool: recipe_facts. Only used by releases with dietary_guard on (v2).
# --------------------------------------------------------------------------
def recipe_facts(recipe_id):
    """The recipe's header (dietary tags + allergens) and every ingredient row.

    The dairy-free failure happened because top-3 retrieval for "dairy-free"
    questions never pulled the chunk that says ghee. For diet questions we
    can't rely on similarity search to find the one row that matters, so we
    fetch the full ingredient list by recipe_id instead.
    """
    store = _load_store()
    return [
        d for d in store["all_docs"]
        if d.metadata.get("recipe_id") == recipe_id
        and ("Description:" in d.page_content or "Ingredients Table Row" in d.page_content)
    ]


def dietary_guard(trace, query, docs):
    recipe_ids = diet_rules.recipes_in(query)
    with trace.span("tool.recipe_facts", "tools") as sp:
        sp.attrs["recipe_ids"] = recipe_ids
        seen = {d.metadata.get("chunk_id") for d in docs}
        added = []
        for rid in recipe_ids:
            for doc in recipe_facts(rid):
                cid = doc.metadata.get("chunk_id")
                if cid not in seen:
                    seen.add(cid)
                    added.append(doc)
        sp.attrs["added_context_ids"] = [d.metadata.get("chunk_id") for d in added]
    return added


# --------------------------------------------------------------------------
# Generation: Groq first, Gemini if Groq is down or keeps rate-limiting us.
# --------------------------------------------------------------------------
def load_prompt(release):
    path = config.PROMPT_DIR / config.RELEASES[release]["prompt_file"]
    text = path.read_text(encoding="utf-8").strip()
    # The sha lets us spot a prompt that was edited without a version bump.
    return text, hashlib.sha256(text.encode()).hexdigest()[:10]


def build_context(docs):
    # Kept byte-for-byte the same as rag_pipeline.generate() so v1 here is
    # really the prompt that was live.
    context = ""
    for doc in docs:
        meta = doc.metadata
        context += "\n--- Context Block ---\n"
        context += f"chunk_id: {meta.get('chunk_id', 'unknown_chunk')}\n"
        context += f"recipe_id: {meta.get('recipe_id', 'unknown_recipe')}\n"
        context += f"source_file: {meta.get('source_file', 'unknown_source')}\n"
        context += f"content: {doc.page_content}\n"
    return context


def _call_groq(messages, sp, reasoning_effort=None):
    import groq

    client = groq.Groq(max_retries=0)  # we do our own retries so we can log them
    extra = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
    retries = 0
    while True:
        try:
            raw = client.chat.completions.with_raw_response.create(
                model=config.PRIMARY_MODEL, messages=messages, temperature=0, **extra,
            )
            break
        except groq.RateLimitError as exc:
            retries += 1
            sp.attrs["rate_limited"] = retries
            if retries > 3:
                raise
            wait = float(exc.response.headers.get("retry-after", 5))
            time.sleep(min(wait, 30))

    resp = raw.parse()
    headers = raw.headers
    usage = resp.usage
    details = getattr(usage, "completion_tokens_details", None)

    # Groq's prompt cache reports hits in usage.prompt_tokens_details.cached_tokens
    # (the object is simply missing when nothing was cached). In the cache
    # experiment 29% of v2 calls got one 256-token block cached - the start of
    # the system prompt. We also record whether the field was there at all,
    # so "0 hits" and "not reported" can be told apart.
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(prompt_details, "cached_tokens", 0) or 0

    sp.set_usage(config.PRIMARY_MODEL, usage.prompt_tokens, usage.completion_tokens, cached)
    sp.attrs.update({
        "provider": "groq",
        "prompt_cache_reported": prompt_details is not None,
        "reasoning_effort": reasoning_effort or "default",
        "reasoning_tokens": getattr(details, "reasoning_tokens", None),
        "queue_ms": round((usage.queue_time or 0) * 1000, 1),
        "ratelimit_limit_tokens_per_min": headers.get("x-ratelimit-limit-tokens"),
        "ratelimit_remaining_tokens": headers.get("x-ratelimit-remaining-tokens"),
        "ratelimit_limit_requests_per_day": headers.get("x-ratelimit-limit-requests"),
        "ratelimit_remaining_requests": headers.get("x-ratelimit-remaining-requests"),
    })
    return resp.choices[0].message.content or ""


def _call_gemini(messages, sp):
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_google_genai import ChatGoogleGenerativeAI

    llm = ChatGoogleGenerativeAI(model=config.FALLBACK_MODEL, temperature=0, max_retries=1)
    resp = llm.invoke([
        SystemMessage(content=messages[0]["content"]),
        HumanMessage(content=messages[1]["content"]),
    ])
    usage = resp.usage_metadata or {}
    # Gemini's implicit cache shows up as input_token_details.cache_read.
    cached = (usage.get("input_token_details") or {}).get("cache_read", 0) or 0
    sp.set_usage(config.FALLBACK_MODEL, usage.get("input_tokens", 0),
                 usage.get("output_tokens", 0), cached)
    sp.attrs["provider"] = "google"

    content = resp.content
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content


def generate(trace, query, docs, system_prompt, reasoning_effort=None):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Context:\n{build_context(docs)}\n\nQuestion: {query}"},
    ]

    try:
        with trace.span("generation.llm", "generation") as sp:
            return _call_groq(messages, sp, reasoning_effort), False
    except Exception:
        # The failed Groq span stays in the trace (with its error), and the
        # fallback gets its own span, so the log shows both attempts.
        with trace.span("generation.llm_fallback", "generation") as sp:
            return _call_gemini(messages, sp), True


# --------------------------------------------------------------------------
# Semantic cache plumbing.
# --------------------------------------------------------------------------
_caches = {}


def get_cache():
    # One instance per cache file (the cache experiment uses its own file).
    path = config.SEMANTIC_CACHE["path"]
    if path not in _caches:
        _caches[path] = SemanticCache(path)
    return _caches[path]


def release_fingerprint(prompt_sha, settings, use_guard):
    """Everything that changes what an answer would be. If any of it changes,
    old cache entries simply stop matching - that is our cache flush."""
    parts = {
        "prompt_sha": prompt_sha,
        "top_k": settings["top_k"],
        "dietary_guard": use_guard,
        "reasoning_effort": settings.get("reasoning_effort"),
        "model": config.PRIMARY_MODEL,
        "corpus_sha": _store["corpus_sha"],
    }
    return hashlib.sha256(repr(sorted(parts.items())).encode()).hexdigest()[:12]


# --------------------------------------------------------------------------
# Release routing (canary) and the main entry point.
# --------------------------------------------------------------------------
def pick_release(user_id):
    """Sticky canary: the same user always lands on the same release."""
    bucket = int(hashlib.md5(user_id.encode()).hexdigest(), 16) % 100
    return config.CANARY_RELEASE if bucket < config.CANARY_PERCENT else config.STABLE_RELEASE


def answer(query, user_id="anonymous", session_id=None, release=None, ts=None,
           source="live", log_path=None, dietary_guard_override=None, use_cache=None):
    """Answer one question and write one log record. Returns the record.

    use_cache: None follows config.SEMANTIC_CACHE["enabled"]. The eval suite
    passes False so it always tests the model, never yesterday's answer.
    """
    release = release or pick_release(user_id)
    settings = config.RELEASES[release]
    use_guard = settings["dietary_guard"] if dietary_guard_override is None else dietary_guard_override
    system_prompt, prompt_sha = load_prompt(release)
    input_type = diet_rules.classify_input(query)

    trace = Trace(query, user_id, session_id=session_id, release=release, ts=ts)
    answer_text, fallback_used, error = None, False, None
    retrieved, tool_docs = [], []
    cache_on = config.SEMANTIC_CACHE["enabled"] if use_cache is None else use_cache
    cache_info = {"enabled": cache_on, "hit": False}
    hit, vector, fingerprint = None, None, None

    try:
        vector = embed(trace, query)

        if cache_on:
            fingerprint = release_fingerprint(prompt_sha, settings, use_guard)
            cache_info["fingerprint"] = fingerprint
            if is_eligible(input_type):
                with trace.span("cache.semantic_lookup", "cache") as sp:
                    hit, similarity = get_cache().lookup(query, vector, fingerprint, trace.ts)
                    sp.attrs.update(hit=hit is not None, best_similarity=similarity,
                                    entries=len(get_cache().entries))
                cache_info["best_similarity"] = similarity
            else:
                cache_info["skipped"] = f"{input_type} questions are never cached"

        if hit:
            # Served from cache: no retrieval, no model call. Keep a pointer to
            # the request that really produced this answer, so a bad cached
            # answer can still be traced back to its source in a drill.
            answer_text = hit["answer"]
            cache_info.update(hit=True, source_trace_id=hit["source_trace_id"],
                              source_query=hit["query"], source_context_ids=hit["context_ids"],
                              saved_cost_usd=hit["source_cost_usd"])
        else:
            retrieved = retrieve(trace, query, vector, settings["top_k"])
            if use_guard and input_type in ("dietary", "dietary_swap"):
                tool_docs = dietary_guard(trace, query, retrieved)
            answer_text, fallback_used = generate(trace, query, retrieved + tool_docs, system_prompt,
                                                  settings.get("reasoning_effort"))
    except Exception as exc:
        # A failed request is still a request. Log it so it can be found.
        error = f"{type(exc).__name__}: {exc}"[:300]

    spans = [s.to_dict() for s in trace.spans]
    used = [s for s in spans if s["stage"] == "generation" and not s["error"]]
    record = {
        "trace_id": trace.trace_id,
        "ts": trace.ts.isoformat(timespec="seconds"),
        "logged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "log_schema": config.LOG_SCHEMA,
        "source": source,
        "user_id": user_id,
        "session_id": trace.session_id,
        "input_type": input_type,
        "prompt_version": release,
        "prompt_sha": prompt_sha,
        "dietary_guard": use_guard,
        "model": used[-1]["model"] if used else None,
        "fallback_used": fallback_used,
        "query": query,
        "answer": answer_text,
        "recipe_ids": diet_rules.recipes_in(query),
        "retrieved_context_ids": [d.metadata.get("chunk_id") for d in retrieved],
        "tool_context_ids": [d.metadata.get("chunk_id") for d in tool_docs],
        "spans": spans,
        "cost_by_stage": stage_totals(spans),
        "totals": {
            "latency_ms": round(trace.elapsed_ms(), 1),
            "tokens_in": sum(s["tokens_in"] for s in spans),
            "tokens_cached": sum(s["tokens_cached"] for s in spans),
            "tokens_out": sum(s["tokens_out"] for s in spans),
            "cost_usd": sum(s["cost_usd"] or 0 for s in spans),
        },
        "cache": cache_info,
        "status": "error" if error else "ok",
        "error": error,
    }
    if config.LOG_SCHEMA >= 2:
        record["output_tags"] = diet_rules.output_tags(query, answer_text or "")

    # Only fresh, successful answers from the primary model go into the cache.
    # Fallback answers come from a different model, so they don't belong
    # under this release's fingerprint.
    if (cache_on and not hit and not error and not fallback_used
            and is_eligible(input_type) and worth_storing(input_type, answer_text)):
        get_cache().store(record, vector, fingerprint, trace.ts)
        cache_info["stored"] = True

    if log_path is not False:
        append_log(record, log_path)
        # Mirror to LangSmith (no-op without LANGSMITH_API_KEY). Imported here
        # so the app runs fine without the langsmith package configured.
        import langsmith_export
        langsmith_export.export_safe(record)
    return record


def main():
    parser = argparse.ArgumentParser(description="Ask the recipe app one question (traced + logged).")
    parser.add_argument("question")
    parser.add_argument("--user", default="u_cli")
    parser.add_argument("--release", choices=sorted(config.RELEASES), default=None)
    parser.add_argument("--cache", action="store_true", help="turn the semantic cache on for this call")
    args = parser.parse_args()

    rec = answer(args.question, user_id=args.user, release=args.release,
                 use_cache=True if args.cache else None)
    print(rec["answer"] or f"[error] {rec['error']}")
    if rec["cache"]["hit"]:
        print(f"\n(served from semantic cache, similarity {rec['cache']['best_similarity']}, "
              f"original trace {rec['cache']['source_trace_id']})")
    print(f"\ntrace_id={rec['trace_id']}  release={rec['prompt_version']}  "
          f"latency={rec['totals']['latency_ms']:.0f}ms  cost=${rec['totals']['cost_usd']:.6f}")
    for s in rec["spans"]:
        print(f"  {s['name']:<24} {s['latency_ms']:>8.1f} ms  "
              f"in={s['tokens_in']:<5} out={s['tokens_out']:<5} ${s['cost_usd'] or 0:.6f}")


if __name__ == "__main__":
    main()
