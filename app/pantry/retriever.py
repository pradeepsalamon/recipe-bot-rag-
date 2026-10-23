"""
Hybrid retrieval: dense (Chroma + all-MiniLM-L6-v2) + BM25, fused with RRF.

This is the week 3/4 retriever (rag_pipeline.search) with three seams fixed
for integration:
  1. The store and the BM25 index are built once per process (week 11), not
     on every question.
  2. Chunk ids are deterministic ("shortbread@reformulated-2025#method")
     instead of random uuids, so a citation or a trace from Monday still
     points at the same chunk on Friday.
  3. Every chunk carries recipe_id, version and status, and results are
     grouped per recipe-version so the caller always sees WHICH version a
     hit came from.

Chunking is the week 3 structure-aware idea (overview / ingredients / method /
notes per recipe). Allergen declarations are deliberately NOT in the chunk
text: they are answered by exact match in safety.py, never by similarity.
Both versions of a reformulated recipe stay in the index: the client's CMS
still has both, and hiding one would hide the bug, not fix it.
"""
import logging
import os
import re
import shutil
import threading
import warnings

from . import config, corpus, safety

warnings.filterwarnings("ignore")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
for _name in ("httpx", "chromadb"):
    logging.getLogger(_name).setLevel(logging.WARNING)

_store = {}
_lock = threading.Lock()


def _version_label(r):
    if r["status"] == "superseded":
        return f"{r['version']} (SUPERSEDED by {r.get('superseded_by')})"
    return f"{r['version']} (current)"


def chunks_for(r):
    k = corpus.key(r["recipe_id"], r["version"])
    head = f"Recipe: {r['title']}\nRecipe key: {k}\nVersion: {_version_label(r)}\n"
    times = f"Prep {r.get('prep_minutes', '?')} min, cook {r.get('cook_minutes', '?')} min"
    if r.get("rest_minutes"):
        times += f", soak/ferment/rest {r['rest_minutes']} min"
    overview = (head + f"Description: {r['description']}\nCuisine: {r['cuisine']}\n"
                f"Dietary tags: {', '.join(r['dietary_tags']) or 'none'}\n"
                f"Yield: {r['yield']['amount']} {r['yield']['unit']}\nTimes: {times}\n")
    if r.get("reformulation_note"):
        overview += f"Reformulation: {r['reformulation_note']}\n"
    ingredients = head + "Ingredients:\n" + "\n".join(
        f"- {i['item']}: {i['qty'] if i['qty'] is not None else ''} {i['unit']}".replace(":  ", ": ")
        for i in r["ingredients"])
    method = head + "Method:\n" + "\n".join(f"{n}. {s}" for n, s in enumerate(r["method"], 1))
    out = [("overview", overview), ("ingredients", ingredients), ("method", method)]
    if r.get("notes"):
        out.append(("notes", head + "Cook's notes: " + r["notes"]))
    return [{"chunk_id": f"{k}#{part}", "text": text,
             "meta": {"chunk_id": f"{k}#{part}", "recipe_key": k, "recipe_id": r["recipe_id"],
                      "version": r["version"], "status": r["status"], "part": part}}
            for part, text in out]


_emb = None


def _embeddings():
    """One embedding model per process (index build, search, and the cache).

    all-MiniLM-L6-v2 as the ONNX build chromadb ships, not sentence-transformers:
    same vectors (cosine 1.0, max diff ~1e-7, checked 2026-10-23) without the
    ~900 MB of torch that put the Vercel bundle over its 500 MB limit."""
    global _emb
    if _emb is None:
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
        from langchain_core.embeddings import Embeddings

        class OnnxMiniLM(Embeddings):
            def __init__(self):
                if config.SERVERLESS:   # home is read-only there
                    ONNXMiniLM_L6_V2.DOWNLOAD_PATH = config.ONNX_MODEL_DIR
                self._fn = ONNXMiniLM_L6_V2()

            def embed_documents(self, texts):
                return [[float(x) for x in v] for v in self._fn(list(texts))]

            def embed_query(self, text):
                return self.embed_documents([text])[0]

        _emb = OnnxMiniLM()
    return _emb


def query_embedder():
    """Embedding function for the semantic cache (no Chroma load needed)."""
    return _embeddings().embed_query


def build_index():
    from langchain_chroma import Chroma
    from langchain_core.documents import Document

    docs = [Document(page_content=c["text"], metadata=c["meta"])
            for r in corpus.all_recipes() for c in chunks_for(r)]
    if config.INDEX_DIR.exists():
        shutil.rmtree(config.INDEX_DIR)
    Chroma.from_documents(docs, _embeddings(), collection_name=config.COLLECTION,
                          persist_directory=str(config.INDEX_DIR),
                          ids=[d.metadata["chunk_id"] for d in docs])
    _store.clear()
    return len(docs)


def index_exists():
    return config.INDEX_DIR.exists() and any(config.INDEX_DIR.iterdir())


def _tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def _load():
    with _lock:   # warm() runs in a background thread at server start
        if _store:
            return _store
        from langchain_chroma import Chroma
        from rank_bm25 import BM25Okapi

        if (not index_exists() and config.INDEX_DIR != config.BUNDLED_INDEX_DIR
                and config.BUNDLED_INDEX_DIR.exists()):
            shutil.copytree(config.BUNDLED_INDEX_DIR, config.INDEX_DIR)
        if not index_exists():
            build_index()
        db = Chroma(collection_name=config.COLLECTION, embedding_function=_embeddings(),
                    persist_directory=str(config.INDEX_DIR))
        data = db.get()
        _store["bm25"] = BM25Okapi([_tokens(t) for t in data["documents"]])
        _store["ids"] = data["ids"]
        _store["texts"] = data["documents"]
        _store["metas"] = data["metadatas"]
        _store["db"] = db
        return _store


def warm():
    _load()


def warm_in_background():
    threading.Thread(target=warm, daemon=True).start()


def search(query, top_k=None, exclude_allergens=None, include_superseded=True):
    """Return recipe-version hits, best first.

    exclude_allergens: allergen terms; recipe-versions whose DECLARATION
    (allergens or may_contain) intersects them are dropped by exact match
    before ranking is cut to top_k.
    include_superseded=False: superseded versions are left out of the results
    (still in the index) and listed under hidden_superseded.
    """
    s = _load()
    top_k = top_k or config.RETRIEVAL["top_k"]
    pool_k = config.RETRIEVAL["pool_k"]
    rrf_k = config.RETRIEVAL["rrf_k"]

    dense = s["db"].similarity_search_with_relevance_scores(query, k=pool_k)
    dense_ids = [d.metadata["chunk_id"] for d, _ in dense]

    scores = s["bm25"].get_scores(_tokens(query))
    sparse_ids = [s["ids"][i] for i in sorted(range(len(scores)), key=lambda i: -scores[i])[:pool_k]
                  if scores[i] > 0]

    fused = {}
    for ids in (dense_ids, sparse_ids):
        for rank, cid in enumerate(ids):
            fused[cid] = fused.get(cid, 0.0) + 1 / (rrf_k + rank + 1)

    codes, unknown = safety.normalise_allergies(exclude_allergens or [])
    meta_by_id = dict(zip(s["ids"], s["metas"]))
    text_by_id = dict(zip(s["ids"], s["texts"]))

    hits, dropped, hidden = {}, [], []
    for cid, score in sorted(fused.items(), key=lambda x: -x[1]):
        m = meta_by_id[cid]
        k = m["recipe_key"]
        r = corpus.get_by_key(k)
        if not include_superseded and r["status"] == "superseded":
            if k not in hidden:
                hidden.append(k)
            continue
        if codes and (set(codes) & (set(r["allergens"]) | set(r["may_contain"]))):
            if k not in dropped:
                dropped.append(k)
            continue
        if k not in hits:
            hits[k] = {"recipe": k, "title": r["title"], "version": r["version"], "status": r["status"],
                       "superseded_by": r.get("superseded_by"), "score": 0.0, "chunks": [],
                       "snippet": text_by_id[cid].split("\n", 3)[-1][:240]}
        hits[k]["score"] += score
        hits[k]["chunks"].append(cid)

    ranked = sorted(hits.values(), key=lambda h: -h["score"])[:top_k]
    for h in ranked:
        h["score"] = round(h["score"], 4)
    out = {"query": query, "results": ranked, "excluded_by_declaration": dropped,
           "excluded_for": codes, "unknown_allergen_terms": unknown}
    if not include_superseded:
        out["hidden_superseded"] = hidden
    return out
