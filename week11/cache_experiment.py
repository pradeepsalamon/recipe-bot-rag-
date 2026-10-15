"""
Measure both caches on real traffic before anyone turns them on.

    python cache_experiment.py run       # replay + probes (real Groq calls on misses)
    python cache_experiment.py report    # rebuild cache_report.md from the experiment log

What `run` does:
  1. Replays last week's production questions (logs/requests.jsonl), in time
     order, with their original users and timestamps, through release v2.1
     with the semantic cache ON. Uses its own cache file and its own log, so
     production data is untouched.
  2. Sends probe questions: paraphrases of cached questions (should hit) and
     look-alikes with different answers (must miss).
Every miss is a real model call, so the provider's prompt-cache counter
(cached_tokens) is measured on the same run.
"""
import argparse
import time
from datetime import datetime, timedelta

import config
import diet_rules
from semantic_cache import cosine, is_eligible, match_reason, numbers_in, worth_storing
from tracing import read_logs

RELEASE = "v2.1"  # current best: v2 safety fix + low reasoning
EXP_LOG = config.LOG_DIR / "cache_experiment.jsonl"
EXP_CACHE = config.WEEK_DIR / "cache" / "experiment_semantic_cache.jsonl"
REPORT = config.WEEK_DIR / "cache_report.md"

# Asked after the replay, one hour after the last replayed request so the
# cached entries from that day are still inside the TTL. The expectations
# were written before the run and are left exactly as they were.
PROBES = [
    # (question, expected) - expected True = should be served from cache
    ("How much salt goes into idli?", True),
    ("How long do I ferment idli batter?", True),
    ("Tips for making dosa crispy?", True),
    ("Can I swap ghee for oil in rasam?", True),
    ("How much salt is used in the Dosa recipe?", False),     # other recipe
    ("Double the sambar for 12 people - how much toor dal?", False),  # other number
    ("Is Rasam vegan?", False),                                # diet: never cached
    ("I'm cooking Ven Pongal for a dairy-free guest. What can I fry the cashews in instead of butter?", False),
]


def run(args):
    import pipeline

    config.SEMANTIC_CACHE["path"] = EXP_CACHE
    pipeline.get_cache().clear()
    if EXP_LOG.exists():
        EXP_LOG.unlink()

    traffic = sorted(read_logs(), key=lambda r: r["ts"])
    last_ts = None
    for i, src in enumerate(traffic, 1):
        ts = datetime.fromisoformat(src["ts"])
        rec = pipeline.answer(src["query"], user_id=src["user_id"], session_id=src["session_id"],
                              release=RELEASE, ts=ts, source="cache_experiment",
                              log_path=EXP_LOG, use_cache=True)
        last_ts = ts
        tag = "HIT " if rec["cache"]["hit"] else ("skip" if rec["cache"].get("skipped") else "miss")
        print(f"[{i:>3}/{len(traffic)}] {tag} {rec['input_type']:<13} {src['query'][:60]}", flush=True)
        if not rec["cache"]["hit"]:
            time.sleep(args.pause)  # only real model calls count against Groq's TPM

    probe_ts = last_ts + timedelta(hours=1)
    for question, expected in PROBES:
        rec = pipeline.answer(question, user_id="probe", release=RELEASE, ts=probe_ts,
                              source="cache_probe", log_path=EXP_LOG, use_cache=True)
        rec_hit = rec["cache"]["hit"]
        print(f"probe {'HIT ' if rec_hit else 'miss'} (expected {'hit' if expected else 'miss'}) {question[:60]}")
        if not rec_hit:
            time.sleep(args.pause)
    report(args)


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else 0


def _embed_all(texts):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(config.EMBED_MODEL)
    return {t: v.tolist() for t, v in zip(texts, model.encode(texts))}


def explain_miss(probe, probe_ts, replay, vecs):
    """Why a probe we expected to hit did not - worked out from the data."""
    ttl = timedelta(hours=config.SEMANTIC_CACHE["ttl_hours"])
    matches = [r for r in replay
               if match_reason(probe, r, cosine(vecs[probe], vecs[r["query"]])) is None]
    if not matches:
        best = max(replay, key=lambda r: cosine(vecs[probe], vecs[r["query"]]))
        sim = cosine(vecs[probe], vecs[best["query"]])
        return (f"no matching question was asked last week (closest: `{best['query']}`, "
                f"{sim:.3f}, {match_reason(probe, best, sim)})")
    stored = [r for r in matches if r["cache"].get("stored")]
    if not stored:
        return (f"`{matches[0]['query']}` was asked, but its answer was a refusal "
                f"(retrieval miss), so it was never stored - the refusal rule working")
    newest = max(datetime.fromisoformat(r["ts"]) for r in stored)
    if probe_ts - newest > ttl:
        return f"matching entry expired ({(probe_ts - newest).total_seconds() / 3600:.0f} h old > TTL)"
    return "unexplained - check the lookup"


def simulate_ttl(replay, vecs, ttl_hours):
    """Offline re-run of the cache decisions over the same requests with another TTL.

    No model calls: we already know every answer and whether it was safe to
    store, so only the hit/miss decisions change.
    """
    ttl = timedelta(hours=ttl_hours)
    entries, hits, saved = [], 0, 0.0
    for r in replay:
        if not is_eligible(r["input_type"]):
            continue
        ts = datetime.fromisoformat(r["ts"])
        cost = r["cache"].get("saved_cost_usd") if r["cache"]["hit"] else r["totals"]["cost_usd"]
        match = next((e for e in entries if ts - e["ts"] <= ttl
                      and match_reason(r["query"], e, cosine(vecs[r["query"]], vecs[e["query"]])) is None),
                     None)
        if match:
            hits += 1
            saved += match["cost"]
        elif worth_storing(r["input_type"], r["answer"]):
            entries.append({"query": r["query"], "ts": ts, "cost": cost})
    return hits, saved


def report(args):
    recs = read_logs(EXP_LOG)
    replay = [r for r in recs if r["source"] == "cache_experiment" and r["status"] == "ok"]
    probes = [r for r in recs if r["source"] == "cache_probe"]
    if not replay:
        raise SystemExit("no experiment log - run `python cache_experiment.py run` first")

    hits = [r for r in replay if r["cache"]["hit"]]
    skipped = [r for r in replay if r["cache"].get("skipped")]
    eligible = [r for r in replay if not r["cache"].get("skipped")]
    misses = [r for r in replay if not r["cache"]["hit"]]
    not_stored = [r for r in eligible if not r["cache"]["hit"] and not r["cache"].get("stored")]
    saved = sum(r["cache"]["saved_cost_usd"] for r in hits)
    spent = sum(r["totals"]["cost_usd"] for r in replay)
    no_cache_total = spent + saved
    n = len(replay)

    # Re-check every hit with the guards, independently of the lookup code.
    bad_hits = [r for r in hits
                if diet_rules.recipes_in(r["query"]) != diet_rules.recipes_in(r["cache"]["source_query"])
                or numbers_in(r["query"]) != numbers_in(r["cache"]["source_query"])]

    hit_lat = [r["totals"]["latency_ms"] for r in hits]
    miss_lat = [r["totals"]["latency_ms"] for r in misses
                if not any(s["name"] == "retrieval.cold_start" for s in r["spans"])]

    vecs = _embed_all(sorted({r["query"] for r in recs}))

    out = ["# Caching: measured on last week's traffic", "",
           f"Replay of {n} production questions through `{RELEASE}`, original order, users and "
           f"timestamps, semantic cache on (threshold {config.SEMANTIC_CACHE['threshold']}, "
           f"TTL {config.SEMANTIC_CACHE['ttl_hours']} h). Every miss was a real Groq call, so the "
           "prompt-cache numbers come from the same run. Raw data: `logs/cache_experiment.jsonl`.", "",
           "## 1. Semantic cache (ours)", "",
           "| | Value |", "|---|---|",
           f"| Requests replayed | {n} |",
           f"| Never cached (diet / allergen questions) | {len(skipped)} |",
           f"| Not stored (in-scope refusals, usually retrieval misses) | {len(not_stored)} |",
           f"| Served from cache | **{len(hits)}** ({100 * len(hits) / n:.0f}% of all, "
           f"{100 * len(hits) / max(1, len(eligible)):.0f}% of eligible) |",
           f"| Cost without the semantic cache | ${no_cache_total:.6f} (${no_cache_total / n:.7f}/query) |",
           f"| Cost with it | ${spent:.6f} (${spent / n:.7f}/query) |",
           f"| **Saved** | **${saved:.6f} ({100 * saved / max(1e-12, no_cache_total):.1f}%)** |",
           f"| p50 latency, hit vs miss | **{pct(hit_lat, .5):.0f} ms vs {pct(miss_lat, .5):.0f} ms** |",
           f"| Hits that break a guard on re-check (different recipe / numbers) | {len(bad_hits)} |",
           "", "Every hit, for a human to audit:", "",
           "| Asked | Served the answer to | Similarity |", "|---|---|---|"]
    for r in hits:
        out.append(f"| {r['query']} | {r['cache']['source_query']} | {r['cache']['best_similarity']} |")

    out += ["", "### TTL what-if (offline, same requests, no extra model calls)", "",
            "| TTL | Served from cache | Saved |", "|---|---|---|"]
    for ttl in (24, 72, 168):
        h, sv = simulate_ttl(replay, vecs, ttl)
        out.append(f"| {ttl} h | {h} ({100 * h / n:.0f}%) | ${sv:.6f} ({100 * sv / no_cache_total:.1f}%) |")
    out += ["", "A longer TTL serves more, but the recipe corpus or prompt can change in between. "
            "The release fingerprint covers prompt / model / retrieval / corpus changes; the TTL is "
            "the limit on everything else. 24 h stays the default until a canary says otherwise."]

    probe_ts = datetime.fromisoformat(replay[-1]["ts"]) + timedelta(hours=1)
    expected = dict(PROBES)
    out += ["", "### Probes", "",
            "Expectations were written into `PROBES` before the run; the *why* column is worked "
            "out from the data afterwards.", "",
            "| Question | Expected | Got | Why |", "|---|---|---|---|"]
    for r in probes:
        cache = r["cache"]
        if cache["hit"]:
            why = f"similarity {cache['best_similarity']} to `{cache['source_query']}`"
        elif cache.get("skipped"):
            why = cache["skipped"]
        elif expected.get(r["query"]):
            why = explain_miss(r["query"], probe_ts, replay, vecs)
        else:
            why = f"correctly not served (best similarity {cache.get('best_similarity')}, guards)"
        out.append(f"| {r['query']} | {'hit' if expected.get(r['query']) else 'miss'} | "
                   f"{'hit' if cache['hit'] else 'miss'} | {why} |")

    out += ["", "Safety rules (each one backed by a test in `evals/test_semantic_cache.py`):", "",
            "- Diet / allergen questions are never cached - the dairy bug is exactly what a cache would spread.",
            '- Recipes and numbers in the question must match exactly: "sambar for 8" vs "for 12" '
            "scores 0.952 on MiniLM, higher than most real paraphrases.",
            "- In-scope refusals are not stored (they are usually retrieval misses).",
            "- Keyed on a release fingerprint (prompt sha, retrieval settings, model, corpus): a version "
            "bump or re-ingest is an automatic flush. The TTL bounds staleness.",
            "- Every cached answer in the log points to the trace that produced it "
            "(`cache.source_trace_id`, `logq.py find --cache-hit`).",
            "- Off in production (`SEMANTIC_CACHE.enabled = False`) until it goes through a canary like a release."]

    # ---- prompt caching (Groq) ----
    gens = [s for r in recs for s in r["spans"] if s["stage"] == "generation" and not s["error"]]
    with_hits = [s for s in gens if s.get("tokens_cached", 0) > 0]
    cached_tokens = sum(s.get("tokens_cached", 0) for s in gens)
    input_tokens = sum(s["tokens_in"] for s in gens)
    pc_saved = sum(s.get("tokens_cached", 0) * (config.PRICES[s["model"]]["input"]
                                                - config.PRICES[s["model"]]["cached_input"]) / 1e6
                   for s in gens)
    block_sizes = sorted({s["tokens_cached"] for s in with_hits})
    total_spend = sum(r["totals"]["cost_usd"] for r in recs)

    import pipeline
    v1_len = len(pipeline.load_prompt("v1")[0])
    v2_len = len(pipeline.load_prompt("v2")[0])

    out += ["", "## 2. Prompt caching (Groq's, automatic)", "",
            "| | Value |", "|---|---|",
            f"| Generation calls in this run | {len(gens)} |",
            f"| Calls with cached input tokens | **{len(with_hits)}** ({100 * len(with_hits) / len(gens):.0f}%) |",
            f"| Cached tokens per hit | {', '.join(map(str, block_sizes)) or '-'} |",
            f"| Input tokens billed at the cached rate | {cached_tokens:,} of {input_tokens:,} "
            f"({100 * cached_tokens / input_tokens:.1f}%) |",
            f"| **Saved** (50% off those tokens) | **${pc_saved:.6f}** "
            f"({100 * pc_saved / (total_spend + pc_saved):.1f}% of spend) |",
            "",
            "What the numbers say:",
            "- Groq caches in 256-token blocks from the start of the prompt. Every hit was exactly one "
            "block: the first 256 tokens of the system prompt, which is identical on every call. "
            "Everything after it (retrieved context, question) changes per request.",
            f"- The v1 prompt ({v1_len} chars, ~140 tokens) is shorter than one block, so v1 could "
            f"**never** get a prompt-cache hit. The v2 dairy fix made the prompt longer ({v2_len} chars), "
            "and that is what made it cacheable at all.",
            "- Only some calls hit, with no pattern by question type or timing - most likely requests "
            "land on different Groq servers that each keep their own cache. A first test of 4 "
            "byte-identical calls got 0 hits, so a small test can easily miss it; this run of "
            f"{len(gens)} calls is the number to trust.",
            "- The ceiling here is low: the stable prefix is one block. Getting more would mean a longer "
            "fixed part before the context (e.g. few-shot examples), which costs tokens of its own.",
            "", "## 3. What each cache is worth for this app", "",
            f"- Semantic cache: {100 * saved / max(1e-12, no_cache_total):.1f}% cost, and "
            f"{pct(miss_lat, .5):.0f} ms -> {pct(hit_lat, .5):.0f} ms on a hit. Traffic is ~17 "
            "questions/day, so few repeats land inside 24 h. It pays off on latency and at higher "
            "volume - at 10x traffic the same questions repeat 10x as often.",
            f"- Prompt cache: {100 * pc_saved / (total_spend + pc_saved):.1f}% cost, free and risk-free "
            "(the answer is still generated fresh). Keep the system prompt first and stable.",
            "- Neither is a fix for anything: the reasoning_effort change (-26%, `cost_improvement.md`) "
            "saved more than both caches together."]

    # The replay asked exactly last week's questions, so refusal rates can be
    # compared one-to-one with what v1 said at the time.
    refused = lambda a: bool(diet_rules.REFUSAL.search(diet_rules.normalize(a or "")))
    v1_week = sorted(read_logs(), key=lambda r: r["ts"])
    if [r["query"] for r in v1_week] == [r["query"] for r in replay]:
        v1_ref = sum(refused(r["answer"]) for r in v1_week)
        v21_ref = sum(refused(r["answer"]) for r in replay)
        out += ["", "## 4. Side finding: the app refuses most real questions", "",
                f"Same {n} questions: v1 refused **{v1_ref} ({100 * v1_ref / n:.0f}%)**, {RELEASE} refused "
                f"**{v21_ref} ({100 * v21_ref / n:.0f}%)**. So the cheaper release did not quietly get "
                "worse (the diet guard now answers diet questions v1 couldn't), but more than half of "
                "real traffic gets \"not in the recipe documents\" - many questions (brown rice for dosa, "
                "scaling, troubleshooting) aren't covered by the 6 recipe cards, and top-3 retrieval misses "
                "some that are. That, not cost, is the next thing to fix - and it's also why only "
                f"{len(eligible) - len(not_stored)} answers were worth caching."]

    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
    print(f"\nwrote {REPORT.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cmd", choices=["run", "report"])
    parser.add_argument("--pause", type=float, default=6.0, help="seconds after each real model call")
    args = parser.parse_args()
    run(args) if args.cmd == "run" else report(args)


if __name__ == "__main__":
    main()
