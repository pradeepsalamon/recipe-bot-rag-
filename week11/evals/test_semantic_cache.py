"""
Tests for the semantic cache rules. A cache that serves the wrong answer is
worse than no cache, so every guard gets a test with a real question pair.

    python evals/test_semantic_cache.py        (from week11/)
"""
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from semantic_cache import SemanticCache, cosine, is_eligible, match_reason, worth_storing

# Paraphrases: same meaning, same answer -> the cache SHOULD serve them.
SHOULD_HIT = [
    ("How much salt is used in the Idli recipe?", "How much salt goes into idli?"),
    ("How long should the Idli batter ferment?", "How long do I ferment idli batter?"),
    ("How do I make crispy Dosa?", "Tips for making dosa crispy?"),
    ("Can I use oil instead of ghee in Rasam?", "Can I swap ghee for oil in rasam?"),
    ("How many cashews are needed for Ven Pongal?", "How many cashews for pongal?"),
]

# Look-alikes with a DIFFERENT answer -> the cache must NOT serve them.
# The sambar pair scores 0.952 on MiniLM, higher than most paraphrases above;
# only the numbers guard stops it.
MUST_MISS = [
    ("How much salt is used in the Idli recipe?", "How much salt is used in the Dosa recipe?"),
    ("How long should the Idli batter ferment?", "How long should the Dosa batter ferment?"),
    ("Double the sambar for 8 people - how much toor dal?",
     "Double the sambar for 12 people - how much toor dal?"),
    ("Can I use oil instead of ghee in Rasam?", "Can I use oil instead of ghee in Ven Pongal?"),
    ("How much water goes into Ven Pongal?", "How much salt goes into Ven Pongal?"),
    ("Is Idli vegan?", "Is Rasam vegan?"),
]


def _embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(config.EMBED_MODEL)


def test_calibration_pairs_with_real_embeddings():
    model = _embedder()
    for cached_q, new_q in SHOULD_HIT:
        sim = cosine(model.encode(cached_q).tolist(), model.encode(new_q).tolist())
        reason = match_reason(new_q, {"query": cached_q}, sim)
        assert reason is None, f"should hit: {new_q!r} ({sim:.3f}) -> {reason}"
    for cached_q, new_q in MUST_MISS:
        sim = cosine(model.encode(cached_q).tolist(), model.encode(new_q).tolist())
        reason = match_reason(new_q, {"query": cached_q}, sim)
        assert reason is not None, f"must miss: {new_q!r} ({sim:.3f}) was served"


def test_numbers_guard_beats_high_similarity():
    entry = {"query": "Double the sambar for 8 people - how much toor dal?"}
    assert match_reason("Double the sambar for 12 people - how much toor dal?", entry, 0.99) == "different numbers"


def test_diet_questions_never_cached():
    assert not is_eligible("dietary_swap")
    assert not is_eligible("dietary")
    assert is_eligible("fact")


def test_in_scope_refusals_not_stored():
    # "salt amount not available" for Idli is a retrieval miss - don't repeat it.
    assert not worth_storing("fact", "The provided recipe documents do not specify the amount of salt.")
    # Refusing an off-topic question is correct, safe to repeat.
    assert worth_storing("out_of_scope", "The information is not available in the provided recipe documents.")
    assert worth_storing("fact", "The recipe uses 15 g of salt. [chunk_cde47aaa]")


def _record(query, answer="15 g of salt. [chunk_cde47aaa]"):
    return {"query": query, "input_type": "fact", "answer": answer, "trace_id": "t-source",
            "retrieved_context_ids": ["chunk_cde47aaa"], "tool_context_ids": [],
            "totals": {"cost_usd": 0.00008, "latency_ms": 800.0}}


def test_fingerprint_and_ttl():
    now = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
    vec = [1.0, 0.0, 0.0]
    with tempfile.TemporaryDirectory() as tmp:
        cache = SemanticCache(Path(tmp) / "c.jsonl")
        cache.store(_record("How much salt is used in the Idli recipe?"), vec, "fp-v1", now)
        q = "How much salt is used in the Idli recipe?"

        hit, _ = cache.lookup(q, vec, "fp-v1", now + timedelta(hours=1))
        assert hit and hit["source_trace_id"] == "t-source"

        # A new prompt/release = new fingerprint: the old answer must not leak.
        assert cache.lookup(q, vec, "fp-v2", now)[0] is None

        # Older than ttl_hours: stale, not served.
        ttl = config.SEMANTIC_CACHE["ttl_hours"]
        assert cache.lookup(q, vec, "fp-v1", now + timedelta(hours=ttl + 1))[0] is None

        # Survives a restart (reloaded from disk).
        assert SemanticCache(Path(tmp) / "c.jsonl").lookup(q, vec, "fp-v1", now)[0] is not None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
