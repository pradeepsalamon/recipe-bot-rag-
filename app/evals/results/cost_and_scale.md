# Cost per query and what breaks first

From 9 logged requests (live + eval), model `openai/gpt-oss-20b`.

| Per query | Mean | p50 | p95 |
|---|---|---|---|
| Cost (USD) | 0.000370 | 0.000412 | 0.000685 |
| Tokens (in+out) | 4458 | 4892 | 8936 |
| LLM calls | 2.44 | 3 | 4 |
| MCP tool calls | 1.56 | 2 | 3 |
| End-to-end latency (s) | 12.9 | 9.9 | 35.7 |
| One LLM call (ms) | 3874 | 980 | 15345 |
| One MCP hop (ms) | 2229 | 22 | 10508 |

Rate-limit waits already seen: 5 LLM calls waited, 65 s total.
Semantic-cache hits: 1 of 9 requests (served at $0; they are included in the means above).

## At scale

Assumption: busiest minute = 3x the average minute. Limits: Groq free tier for this model, 8,000 tokens/min and 1,000 requests/day (from the response headers).

| Queries/day | Cost/day | Avg tokens/min | Peak tokens/min | vs TPM limit | LLM requests/day | vs RPD limit |
|---|---|---|---|---|---|---|
| 50,000 | $18.50 | 154,807 | 464,421 | 58x over | 122,222 | 122x over |
| 500,000 | $185.05 | 1,548,071 | 4,644,213 | 581x over | 1,222,222 | 1,222x over |

**Breaks first: the provider requests/day limit.** Today's limits carry about 409 queries/day (TPM allows ~861, RPD allows ~409); 50,000/day is 122x past that.
Money is not the constraint: 50,000 queries/day costs about $18.50/day.
Next in line after a paid tier: the MCP server is one stdio process per agent process and the embedding model runs on CPU inside it. Median MCP hop 22 ms; p95 10508 ms is dominated by the model cold start on a process's first search. It has to become a long-lived shared HTTP service before horizontal scaling.

Sample size: 9 requests. Re-run after `python run.py eval` for a number worth defending.
