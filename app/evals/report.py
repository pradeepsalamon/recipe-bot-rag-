"""
`python run.py report`: cost per query and what breaks first at 50,000
queries/day (and at 500,000), computed from the logged traces, not guessed.

Every number comes from logs/requests.jsonl + logs/eval_requests.jsonl except
two stated assumptions: the peak-minute multiplier and the provider limits
(Groq free tier, read from the x-ratelimit-* headers we log on every LLM span).
"""
import statistics

from pantry import config
from pantry.tracing import read_jsonl

PEAK_FACTOR = 3.0   # ASSUMPTION: busiest minute (dinner-time) = 3x the day's average minute
OUT = config.APP_DIR / "evals" / "results" / "cost_and_scale.md"


def _pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else 0


def main():
    recs = [r for r in read_jsonl(config.REQUEST_LOG) + read_jsonl(config.EVAL_LOG) if r.get("cost_usd") is not None]
    if not recs:
        print("No logged requests yet. Run `python run.py ask ...` or `python run.py eval` first.")
        return 1
    n = len(recs)
    cost = [r["cost_usd"] for r in recs]
    toks = [r["tokens_in"] + r["tokens_out"] for r in recs]
    llm_calls = [sum(1 for s in r["spans"] if s["stage"] == "llm") for r in recs]
    mcp_calls = [sum(1 for s in r["spans"] if s["stage"] == "mcp") for r in recs]
    lat = [r["latency_ms"] for r in recs]
    llm_ms = [s["latency_ms"] for r in recs for s in r["spans"] if s["stage"] == "llm"]
    mcp_ms = [s["latency_ms"] for r in recs for s in r["spans"] if s["stage"] == "mcp"]
    waits = [s["attrs"].get("retry_wait_s", s["attrs"].get("rate_limit_wait_s", 0))
             for r in recs for s in r["spans"] if s["stage"] == "llm"]
    tpm_hdr = next((s["attrs"].get("ratelimit_limit_tokens_per_min") for r in reversed(recs)
                    for s in r["spans"] if s["stage"] == "llm" and s["attrs"].get("ratelimit_limit_tokens_per_min")), None)
    rpd_hdr = next((s["attrs"].get("ratelimit_limit_requests_per_day") for r in reversed(recs)
                    for s in r["spans"] if s["stage"] == "llm" and s["attrs"].get("ratelimit_limit_requests_per_day")), None)
    tpm = int(tpm_hdr) if tpm_hdr else config.GROQ_LIMITS["tokens_per_minute"]
    rpd = int(rpd_hdr) if rpd_hdr else config.GROQ_LIMITS["requests_per_day"]

    mean_cost, mean_tok, mean_llm = statistics.mean(cost), statistics.mean(toks), statistics.mean(llm_calls)
    lines = ["# Cost per query and what breaks first", "",
             f"From {n} logged requests (live + eval), model `{config.AGENT_MODEL}`.", "",
             "| Per query | Mean | p50 | p95 |", "|---|---|---|---|",
             f"| Cost (USD) | {mean_cost:.6f} | {_pct(cost, .5):.6f} | {_pct(cost, .95):.6f} |",
             f"| Tokens (in+out) | {mean_tok:.0f} | {_pct(toks, .5)} | {_pct(toks, .95)} |",
             f"| LLM calls | {mean_llm:.2f} | {_pct(llm_calls, .5)} | {_pct(llm_calls, .95)} |",
             f"| MCP tool calls | {statistics.mean(mcp_calls):.2f} | {_pct(mcp_calls, .5)} | {_pct(mcp_calls, .95)} |",
             f"| End-to-end latency (s) | {statistics.mean(lat) / 1000:.1f} | {_pct(lat, .5) / 1000:.1f} | {_pct(lat, .95) / 1000:.1f} |",
             f"| One LLM call (ms) | {statistics.mean(llm_ms):.0f} | {_pct(llm_ms, .5):.0f} | {_pct(llm_ms, .95):.0f} |",
             f"| One MCP hop (ms) | {statistics.mean(mcp_ms) if mcp_ms else 0:.0f} | {_pct(mcp_ms, .5):.0f} | {_pct(mcp_ms, .95):.0f} |",
             "", f"Rate-limit waits already seen: {sum(1 for w in waits if w)} LLM calls waited, {sum(waits):.0f} s total.",
             f"Semantic-cache hits: {sum(1 for r in recs if (r.get('cache') or {}).get('hit'))} of {n} "
             "requests (served at $0; they are included in the means above).", ""]

    lines += ["## At scale", "",
              f"Assumption: busiest minute = {PEAK_FACTOR:.0f}x the average minute. Limits: Groq free tier for "
              f"this model, {tpm:,} tokens/min and {rpd:,} requests/day (from the response headers).", "",
              "| Queries/day | Cost/day | Avg tokens/min | Peak tokens/min | vs TPM limit | LLM requests/day | vs RPD limit |",
              "|---|---|---|---|---|---|---|"]
    for q in (50_000, 500_000):
        avg_tpm = q * mean_tok / 1440
        peak = avg_tpm * PEAK_FACTOR
        reqs = q * mean_llm
        lines.append(f"| {q:,} | ${q * mean_cost:,.2f} | {avg_tpm:,.0f} | {peak:,.0f} | {peak / tpm:,.0f}x over "
                     f"| {reqs:,.0f} | {reqs / rpd:,.0f}x over |")
    max_q_tpm = tpm / mean_tok * 1440 / PEAK_FACTOR
    max_q_rpd = rpd / mean_llm
    first = "requests/day" if max_q_rpd < max_q_tpm else "tokens/minute"
    lines += ["",
              f"**Breaks first: the provider {first} limit.** Today's limits carry about "
              f"{min(max_q_tpm, max_q_rpd):,.0f} queries/day (TPM allows ~{max_q_tpm:,.0f}, RPD allows ~{max_q_rpd:,.0f}); "
              f"50,000/day is {50_000 / min(max_q_tpm, max_q_rpd):,.0f}x past that.",
              f"Money is not the constraint: 50,000 queries/day costs about ${50_000 * mean_cost:,.2f}/day.",
              "Next in line after a paid tier: the MCP server is one stdio process per agent process and the "
              f"embedding model runs on CPU inside it. Median MCP hop {_pct(mcp_ms, .5):.0f} ms; p95 "
              f"{_pct(mcp_ms, .95):.0f} ms is dominated by the model cold start on a process's first search. "
              "It has to become a long-lived shared HTTP service before horizontal scaling.",
              "", f"Sample size: {n} requests. Re-run after `python run.py eval` for a number worth defending.", ""]
    text = "\n".join(lines)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    print(f"(written to {OUT.relative_to(config.APP_DIR)})")
    return 0
