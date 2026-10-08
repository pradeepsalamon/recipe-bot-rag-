"""
Cost reports, computed from the logs (never from estimates typed by hand).

    python cost_report.py stage <trace_id>   -> cost_by_stage.md
    python cost_report.py tenx               -> tenx.md

Stage = retrieval / tools / generation, the `stage` field on every span.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta

import config
from logq import lookup
from tracing import read_logs, stage_totals

STAGES = ("retrieval", "tools", "generation")


def usd(x):
    return f"${x:.7f}"


def production_records():
    # Everything in the main log is "production" (simulated users + live);
    # eval runs live in their own file and are left out on purpose.
    return [r for r in read_logs() if r["status"] == "ok"]


def gen_span(rec):
    spans = [s for s in rec["spans"] if s["stage"] == "generation" and not s["error"]]
    return spans[-1] if spans else None


def cmd_stage(args):
    rec = lookup(args.trace_id)
    totals = rec["cost_by_stage"]
    total_cost = sum(t["cost_usd"] for t in totals.values()) or 1e-12

    out = ["# Cost per query, by stage", "",
           f"Request: `{rec['trace_id']}` ({rec['ts']}, user `{rec['user_id']}`, "
           f"prompt `{rec['prompt_version']}`, model `{rec['model']}`)", "",
           f"> {rec['query']}", "",
           "| Stage | Calls | Latency | Tokens in | Tokens out | Cost (USD) | Share of cost |",
           "|---|---|---|---|---|---|---|"]
    for stage in STAGES:
        t = totals[stage]
        out.append(f"| {stage} | {t['calls']} | {t['latency_ms']:.1f} ms | {t['tokens_in']} | "
                   f"{t['tokens_out']} | {usd(t['cost_usd'])} | {100 * t['cost_usd'] / total_cost:.1f}% |")
    out.append(f"| **total** | | **{rec['totals']['latency_ms']:.1f} ms** | {rec['totals']['tokens_in']} | "
               f"{rec['totals']['tokens_out']} | **{usd(rec['totals']['cost_usd'])}** | 100% |")

    out += ["", "Per span:", "", "| Span | Stage | Latency | Model | In | Out | Cost |", "|---|---|---|---|---|---|---|"]
    for s in rec["spans"]:
        out.append(f"| {s['name']} | {s['stage']} | {s['latency_ms']:.1f} ms | {s['model'] or '-'} | "
                   f"{s['tokens_in']} | {s['tokens_out']} | {usd(s['cost_usd'] or 0)} |")

    g = gen_span(rec)
    if g:
        price = config.PRICES[g["model"]]
        reasoning = g["attrs"].get("reasoning_tokens") or 0
        out += ["", "How the generation number is made:", "",
                f"- {g['tokens_in']} input x ${price['input']}/1M + {g['tokens_out']} output x "
                f"${price['output']}/1M = {usd(g['cost_usd'])}",
                f"- {reasoning} of the {g['tokens_out']} output tokens are hidden reasoning tokens "
                f"(gpt-oss thinks before it answers). They are billed as output, so they are "
                f"{100 * reasoning * price['output'] / 1e6 / (g['cost_usd'] or 1e-12):.0f}% of this request's cost."]

    out += ["", "Why retrieval and tools show $0:", "",
            f"- Retrieval embeds the query locally with `{config.EMBED_MODEL}` and searches a local "
            "Chroma + in-memory BM25. No API is called, so there is no per-query bill; its cost is "
            "CPU time (the latency column). The embed span still records the token count "
            "so we know what a hosted embedding API would charge if we moved off CPU.",
            "- Tools: v1 makes no tool calls (0 calls). v2 adds `tool.recipe_facts`, a local "
            "Chroma metadata lookup, also $0 - but the chunks it adds go into the prompt, so "
            "its real cost shows up as extra *generation input tokens* (see the comparison below)."]

    # Same question through v2, if the eval suite has run it.
    evals = read_logs(config.EVAL_LOG_FILE)
    v2 = [r for r in evals if r["query"] == rec["query"] and r["prompt_version"] == "v2"
          and r["dietary_guard"] and r["status"] == "ok"]
    if v2 and rec["prompt_version"] == "v1":
        after = v2[-1]
        before_cost, after_cost = rec["totals"]["cost_usd"], after["totals"]["cost_usd"]
        out += ["", "## Same question after the fix (v2, from the eval run)", "",
                "| | v1 (this trace) | v2 (fixed) | change |", "|---|---|---|---|",
                f"| generation tokens in | {rec['cost_by_stage']['generation']['tokens_in']} | "
                f"{after['cost_by_stage']['generation']['tokens_in']} | "
                f"{after['cost_by_stage']['generation']['tokens_in'] - rec['cost_by_stage']['generation']['tokens_in']:+d} |",
                f"| tool calls | {rec['cost_by_stage']['tools']['calls']} | {after['cost_by_stage']['tools']['calls']} | |",
                f"| cost / query | {usd(before_cost)} | {usd(after_cost)} | "
                f"{100 * (after_cost - before_cost) / (before_cost or 1e-12):+.0f}% |",
                "", "The fix costs more per diet question because the whole ingredient list goes into "
                "the prompt (the tool itself is free; its chunks are not)."]
        out += fleet_projection()

    # Fleet averages, so one request isn't mistaken for the norm. The cold
    # start (first request of a process loads the embedder, ~13 s) is pulled
    # out, otherwise it alone triples the average retrieval latency.
    recs = production_records()
    if recs:
        n = len(recs)
        avg = {s: sum(r["cost_by_stage"][s]["cost_usd"] for r in recs) / n for s in STAGES}
        lat = {s: sum(sp["latency_ms"] for r in recs for sp in r["spans"]
                      if sp["stage"] == s and sp["name"] != "retrieval.cold_start") / n for s in STAGES}
        colds = [sp["latency_ms"] for r in recs for sp in r["spans"] if sp["name"] == "retrieval.cold_start"]
        out += ["", f"## Fleet average over {n} logged requests (v1)", "",
                "| Stage | Avg cost / query | Avg latency (warm) |", "|---|---|---|"]
        for s in STAGES:
            out.append(f"| {s} | {usd(avg[s])} | {lat[s]:.1f} ms |")
        out.append(f"| total | {usd(sum(avg.values()))} | {sum(lat.values()):.1f} ms |")
        if colds:
            out.append(f"\nPlus {len(colds)} cold start(s) of {max(colds) / 1000:.1f} s "
                       "(first request after a process start; fix = load the index at boot).")

    path = config.WEEK_DIR / "cost_by_stage.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
    print(f"\nwrote {path.name}")


DIET_TYPES = ("dietary", "dietary_swap")


def fleet_projection():
    """What v2 would do to the average cost per query across real traffic.

    Uses the eval runs (same 13 questions through v1 and through v2) to get a
    measured cost ratio for diet vs non-diet questions, then applies it to last
    week's traffic mix. Measured, not guessed.
    """
    evals = [r for r in read_logs(config.EVAL_LOG_FILE) if r["status"] == "ok"]
    v1 = [r for r in evals if r["prompt_version"] == "v1"]
    v2 = [r for r in evals if r["prompt_version"] == "v2" and r["dietary_guard"]]
    if not v1 or not v2:
        return []

    def mean_cost(rows, diet):
        rows = [r["totals"]["cost_usd"] for r in rows if (r["input_type"] in DIET_TYPES) == diet]
        return sum(rows) / len(rows) if rows else 0

    ratio_diet = mean_cost(v2, True) / mean_cost(v1, True)
    ratio_other = mean_cost(v2, False) / mean_cost(v1, False)

    recs = production_records()
    diet = [r["totals"]["cost_usd"] for r in recs if r["input_type"] in DIET_TYPES]
    other = [r["totals"]["cost_usd"] for r in recs if r["input_type"] not in DIET_TYPES]
    now = (sum(diet) + sum(other)) / len(recs)
    projected = (sum(diet) * ratio_diet + sum(other) * ratio_other) / len(recs)

    return ["", "Fleet impact, measured: across the eval runs, diet questions cost "
            f"{ratio_diet:.2f}x on v2 vs v1 and other questions {ratio_other:.2f}x. Applied to last "
            f"week's mix ({len(diet)}/{len(recs)} = {100 * len(diet) / len(recs):.0f}% diet questions), "
            f"the average cost per query goes {usd(now)} -> {usd(projected)} "
            f"(**{100 * (projected - now) / now:+.0f}%**). That is the price of the safety fix, and "
            "it's tiny in dollars. One leak to close next: the classifier calls \"How many cashews "
            "for Ven Pongal?\" `dietary` (because of *cashew*), so the guard fires on plain quantity "
            "questions too."]


def peak_window_tokens(recs, seconds=60):
    """Most generation tokens that landed inside any 60-second window."""
    points = sorted((datetime.fromisoformat(r["ts"]), r["totals"]["tokens_in"] + r["totals"]["tokens_out"]
                     - sum(s["tokens_in"] for s in r["spans"] if s["stage"] == "retrieval"))
                    for r in recs)
    best, start, running = 0, 0, 0
    for end in range(len(points)):
        running += points[end][1]
        while points[end][0] - points[start][0] >= timedelta(seconds=seconds):
            running -= points[start][1]
            start += 1
        best = max(best, running)
    return best


def v2_token_note(recs, peak_min, tpm):
    """The fix adds context tokens to diet questions, which eats TPM headroom."""
    evals = [r for r in read_logs(config.EVAL_LOG_FILE) if r["status"] == "ok"]
    v1 = [r for r in evals if r["prompt_version"] == "v1"]
    v2 = [r for r in evals if r["prompt_version"] == "v2" and r["dietary_guard"]]
    if not v1 or not v2:
        return []

    def mean_tokens(rows, diet):
        rows = [gen_span(r)["tokens_in"] + gen_span(r)["tokens_out"] for r in rows
                if (r["input_type"] in DIET_TYPES) == diet and gen_span(r)]
        return sum(rows) / len(rows)

    share = sum(r["input_type"] in DIET_TYPES for r in recs) / len(recs)
    ratio = (share * mean_tokens(v2, True) / mean_tokens(v1, True)
             + (1 - share) * mean_tokens(v2, False) / mean_tokens(v1, False))
    return [f"- After the v2 fix ships, an average request uses {ratio:.2f}x the generation tokens "
            f"(ingredient lists on diet questions), so the TPM cap is hit at "
            f"{tpm / (peak_min * ratio):.1f}x today's load instead of {tpm / peak_min:.1f}x. "
            "The fix makes this limit arrive sooner, not later."]


def live_limit(recs, key, default):
    for r in reversed(recs):
        g = gen_span(r)
        if g and g["attrs"].get(key):
            return int(g["attrs"][key])
    return default


def cmd_tenx(args):
    recs = production_records()
    if not recs:
        raise SystemExit("no production records")

    per_day = Counter(r["ts"][:10] for r in recs)
    days = len(per_day)
    avg_day = len(recs) / days
    peak_day = max(per_day.values())
    gen_tokens = [g["tokens_in"] + g["tokens_out"] for g in map(gen_span, recs) if g]
    avg_tokens = sum(gen_tokens) / len(gen_tokens)
    avg_cost = sum(r["totals"]["cost_usd"] for r in recs) / len(recs)
    lat = sorted(r["totals"]["latency_ms"] for r in recs
                 if not any(s["name"] == "retrieval.cold_start" for s in r["spans"]))
    p95 = lat[int(0.95 * (len(lat) - 1))]
    peak_min = peak_window_tokens(recs)

    tpm = live_limit(recs, "ratelimit_limit_tokens_per_min", config.GROQ_LIMITS["tokens_per_minute"])
    rpd = live_limit(recs, "ratelimit_limit_requests_per_day", config.GROQ_LIMITS["requests_per_day"])

    # How many times today's load each limit can take before it breaks.
    headroom = {
        "rate limit (tokens/min)": tpm / peak_min,
        "rate limit (requests/day)": rpd / peak_day,
    }
    first = min(headroom, key=headroom.get)

    line = (f"**At 10x, the Groq tokens-per-minute rate limit breaks first: our busiest minute goes from "
            f"{peak_min:,} to {10 * peak_min:,} tokens/min against an {tpm:,} TPM cap "
            f"({10 * peak_min / tpm:.1f}x over), while cost only rises to ${10 * avg_day * avg_cost:.4f}/day.**"
            if first == "rate limit (tokens/min)" else
            f"**At 10x, the Groq requests-per-day limit breaks first: our busiest day goes from {peak_day} "
            f"to {10 * peak_day} requests against a {rpd:,}/day cap.**")

    out = ["# What breaks first at 10x", "", line, "",
           "Numbers behind it (all from `logs/requests.jsonl`):", "",
           "| | Today | At 10x | Limit | Breaks at |", "|---|---|---|---|---|",
           f"| Busiest 60 s window (generation tokens) | {peak_min:,} | {10 * peak_min:,} | {tpm:,} TPM (Groq header) | "
           f"{headroom['rate limit (tokens/min)']:.1f}x |",
           f"| Busiest day (requests) | {peak_day} | {10 * peak_day} | {rpd:,} RPD (Groq header) | "
           f"{headroom['rate limit (requests/day)']:.1f}x |",
           f"| Cost per day (avg {avg_day:.1f} req/day x {usd(avg_cost)}) | ${avg_day * avg_cost:.4f} | "
           f"${10 * avg_day * avg_cost:.4f} | no budget cap set | never, at this scale |",
           f"| p95 latency (warm) | {p95:.0f} ms | {p95:.0f} ms until 429s start, then + retry-after waits | - | "
           "rides on the rate limit |",
           "",
           f"- Average generation call: {avg_tokens:.0f} tokens, so {tpm:,} TPM sustains about "
           f"{tpm / avg_tokens:.1f} requests/minute. The traffic simulator already had to pause "
           "7 s between calls to stay under it.",
           *v2_token_note(recs, peak_min, tpm),
           "- Latency doesn't grow with volume by itself (each request is independent); it breaks "
           "*because of* the rate limit, when 429s force `retry-after` waits or the slow Gemini fallback.",
           f"- Caveat: request timestamps in the log are simulated over {days} days, so the busiest-minute "
           "figure depends on that arrival pattern. The per-request token and cost numbers are real.",
           "", "Plan: move to Groq's paid Dev tier (higher TPM) before 10x, keep the 429 -> retry-after -> "
           "Gemini fallback path, and alert when `ratelimit_remaining_tokens` (already logged on every "
           "generation span) drops below 20%."]

    path = config.WEEK_DIR / "tenx.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
    print(f"\nwrote {path.name}")


def cmd_compare(args):
    """Cost per query of two releases over the same eval questions (latest run of each)."""
    evals = [r for r in read_logs(config.EVAL_LOG_FILE) if r["status"] == "ok"]

    def latest(release):
        rows = {}
        for r in evals:  # later runs overwrite earlier ones
            if r["prompt_version"] == release and r["dietary_guard"] == config.RELEASES[release]["dietary_guard"]:
                rows[r["query"]] = r
        return rows

    a, b = latest(args.before), latest(args.after)
    shared = sorted(set(a) & set(b))
    if not shared:
        raise SystemExit("no shared eval questions - run the suite on both releases first")

    def avg(rows, fn):
        return sum(fn(rows[q]) for q in shared) / len(shared)

    stats = {}
    for name, rows in ((args.before, a), (args.after, b)):
        stats[name] = {
            "cost": avg(rows, lambda r: r["totals"]["cost_usd"]),
            "in": avg(rows, lambda r: gen_span(r)["tokens_in"]),
            "out": avg(rows, lambda r: gen_span(r)["tokens_out"]),
            "reasoning": avg(rows, lambda r: gen_span(r)["attrs"].get("reasoning_tokens") or 0),
            "latency": avg(rows, lambda r: gen_span(r)["latency_ms"]),
        }
    x, y = stats[args.before], stats[args.after]
    pct = lambda new, old: f"{100 * (new - old) / old:+.0f}%"

    out = [f"# Cost improvement: {args.before} -> {args.after}", "",
           f"Same {len(shared)} eval questions through both releases (`logs/eval_runs.jsonl`). "
           "Attributed first, optimised second: `cost_by_stage.md` shows generation is 100% of "
           "the bill and hidden reasoning tokens are about half of it, so that is the one thing changed.", "",
           f"| Per query (avg) | {args.before} | {args.after} | change |", "|---|---|---|---|",
           f"| generation input tokens | {x['in']:.0f} | {y['in']:.0f} | {pct(y['in'], x['in'])} |",
           f"| generation output tokens | {x['out']:.0f} | {y['out']:.0f} | {pct(y['out'], x['out'])} |",
           f"| of which reasoning | {x['reasoning']:.0f} | {y['reasoning']:.0f} | {pct(y['reasoning'], x['reasoning'])} |",
           f"| generation latency | {x['latency']:.0f} ms | {y['latency']:.0f} ms | {pct(y['latency'], x['latency'])} |",
           f"| **cost / query** | **{usd(x['cost'])}** | **{usd(y['cost'])}** | **{pct(y['cost'], x['cost'])}** |",
           "", f"Quality gate: see `evals/results/` - the suite must score the same on {args.after} as on "
           f"{args.before} (same cases passing, Allergen safety 4/4) or the saving doesn't count."]
    path = config.WEEK_DIR / "cost_improvement.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
    print(f"\nwrote {path.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stage")
    s.add_argument("trace_id")
    s.set_defaults(func=cmd_stage)
    sub.add_parser("tenx").set_defaults(func=cmd_tenx)
    c = sub.add_parser("compare")
    c.add_argument("before")
    c.add_argument("after")
    c.set_defaults(func=cmd_compare)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
