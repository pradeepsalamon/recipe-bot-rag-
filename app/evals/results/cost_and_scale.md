# Cost per query and what breaks first

From 46 logged requests (live + eval), model `openai/gpt-oss-20b`.

| Per query | Mean | p50 | p95 |
|---|---|---|---|
| Cost (USD) | 0.000374 | 0.000392 | 0.000685 |
| Tokens (in+out) | 4985 | 4892 | 9324 |
| LLM calls | 2.93 | 3 | 5 |
| MCP tool calls | 1.91 | 2 | 3 |
| End-to-end latency (s) | 34.0 | 25.2 | 49.1 |
| One LLM call (ms) | 11272 | 6924 | 15345 |
| One MCP hop (ms) | 476 | 14 | 5606 |

Rate-limit waits already seen: 110 LLM calls waited, 1420 s total.
Semantic-cache hits: 1 of 46 requests (served at $0; they are included in the means above).
Requests the provider refused (rate limit / quota, no answer): 14, excluded from the means.

## At scale

Assumption: busiest minute = 3x the average minute. Limits: Groq free tier for this model: 8,000 tokens/min and 1,000 requests/day (response headers), 200,000 tokens/day (from the 429 message; this one is not in the headers).

| Queries/day | Cost/day | Tokens/day | vs TPD | Peak tokens/min | vs TPM | LLM requests/day | vs RPD |
|---|---|---|---|---|---|---|---|
| 50,000 | $18.68 | 249M | 1,246x over | 519,293 | 65x over | 146,739 | 147x over |
| 500,000 | $186.82 | 2,493M | 12,463x over | 5,192,935 | 649x over | 1,467,391 | 1,467x over |

**Breaks first: the provider tokens/day limit, at about 40 questions/day** (tokens/day allows ~40, tokens/minute allows ~770, requests/day allows ~341). 50,000/day is 1,246x past that. Measured, not projected: on 2026-10-16 one 34-case eval run used 182k of the 200k daily tokens and the next run hit the cap.
Money is not the constraint: 50,000 queries/day costs about $18.68/day.
Next in line after a paid tier: the MCP server is one stdio process per agent process and the embedding model runs on CPU inside it. Median MCP hop 14 ms; p95 5606 ms is dominated by the model cold start on a process's first search. It has to become a long-lived shared HTTP service before horizontal scaling.

Sample size: 46 requests. Re-run after `python run.py eval` for a number worth defending.
