"""
Semantic cache: when a new question means the same as one we answered
recently, return that answer instead of calling the model again.

This is the risky kind of cache. If a wrong answer gets in, it is served
instantly to everyone who asks something similar. So the rules here are
strict, and each one comes from a measured case, not a guess:

  1. Similarity >= 0.88 (MiniLM cosine). Every real paraphrase we tried
     scored >= 0.898; different-recipe questions scored <= 0.79.
  2. The recipes named must be identical. "Salt in Idli" vs "salt in Dosa"
     only differ by one word.
  3. The numbers must be identical. "Sambar for 8 people" vs "for 12
     people" scored 0.952 - higher than most paraphrases - so similarity
     alone would have served the wrong quantities.
  4. Diet / allergen questions are never cached. The dairy failure this
     week is exactly what a cache would have spread.
  5. In-scope refusals are never stored ("salt amount not available" for
     Idli is a retrieval miss, not an answer worth repeating).
  6. Entries are keyed on a release fingerprint (prompt sha + retrieval
     settings + model + corpus). A version bump or re-ingest means a new
     fingerprint, so old answers can never leak into a new release.
  7. Entries expire after ttl_hours (staleness is accepted, but bounded).

Every hit is logged with the trace id of the request that produced the
answer, so a bad cached answer can still be traced back to its source.

    python semantic_cache.py stats
    python semantic_cache.py clear
"""
import argparse
import json
import math
import re
from datetime import datetime, timedelta, timezone

import config
import diet_rules

NUMBER = re.compile(r"\d+(?:\.\d+)?")


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def numbers_in(text):
    return sorted(NUMBER.findall(text))


def is_eligible(input_type):
    return input_type not in config.SEMANTIC_CACHE["skip_input_types"]


def worth_storing(input_type, answer):
    """Don't keep answers we wouldn't want repeated."""
    if not answer:
        return False
    refused = bool(diet_rules.REFUSAL.search(diet_rules.normalize(answer)))
    # Refusing an off-topic question ("chocolate cake?") is correct and safe
    # to repeat. Refusing an in-scope one is usually a retrieval miss.
    return input_type == "out_of_scope" or not refused


def match_reason(query, entry, similarity):
    """None if the entry can be served for this query, else why not.

    Kept separate from the lookup so the tests can check every guard
    one by one with real questions.
    """
    if diet_rules.recipes_in(query) != diet_rules.recipes_in(entry["query"]):
        return "different recipe"
    if numbers_in(query) != numbers_in(entry["query"]):
        return "different numbers"
    if similarity < config.SEMANTIC_CACHE["threshold"]:
        return f"similarity {similarity:.3f} below threshold"
    return None


class SemanticCache:
    def __init__(self, path=None):
        self.path = path or config.SEMANTIC_CACHE["path"]
        self.entries = []
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                self.entries = [json.loads(line) for line in f if line.strip()]

    def lookup(self, query, vector, fingerprint, now):
        """Best servable entry for this query, as (entry, similarity) or (None, best_similarity)."""
        ttl = timedelta(hours=config.SEMANTIC_CACHE["ttl_hours"])
        best, best_sim = None, 0.0
        for entry in self.entries:
            if entry["fingerprint"] != fingerprint:
                continue
            if now - datetime.fromisoformat(entry["created_at"]) > ttl:
                continue
            sim = cosine(vector, entry["vector"])
            if match_reason(query, entry, sim) is None and sim > best_sim:
                best, best_sim = entry, sim
            elif best is None:
                best_sim = max(best_sim, sim)
        return best, round(best_sim, 4)

    def store(self, record, vector, fingerprint, now):
        entry = {
            "created_at": now.isoformat(timespec="seconds"),
            "fingerprint": fingerprint,
            "query": record["query"],
            "input_type": record["input_type"],
            "answer": record["answer"],
            "source_trace_id": record["trace_id"],
            "context_ids": record["retrieved_context_ids"] + record["tool_context_ids"],
            "source_cost_usd": record["totals"]["cost_usd"],
            "source_latency_ms": record["totals"]["latency_ms"],
            "vector": [round(v, 6) for v in vector],
        }
        self.entries.append(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def clear(self):
        self.entries = []
        if self.path.exists():
            self.path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cmd", choices=["stats", "clear"])
    args = parser.parse_args()

    cache = SemanticCache()
    if args.cmd == "clear":
        n = len(cache.entries)
        cache.clear()
        print(f"cleared {n} entries")
        return

    print(f"{len(cache.entries)} entries in {cache.path.name}")
    by_fp = {}
    for e in cache.entries:
        by_fp[e["fingerprint"]] = by_fp.get(e["fingerprint"], 0) + 1
    for fp, n in by_fp.items():
        print(f"  fingerprint {fp}: {n}")


if __name__ == "__main__":
    main()
