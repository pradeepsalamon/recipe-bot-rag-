# What breaks first at 10x

**At 10x, the Groq tokens-per-minute rate limit breaks first: our busiest minute goes from 1,178 to 11,780 tokens/min against an 8,000 TPM cap (1.5x over), while cost only rises to $0.0121/day.**

Numbers behind it (all from `logs/requests.jsonl`):

| | Today | At 10x | Limit | Breaks at |
|---|---|---|---|---|
| Busiest 60 s window (generation tokens) | 1,178 | 11,780 | 8,000 TPM (Groq header) | 6.8x |
| Busiest day (requests) | 23 | 230 | 1,000 RPD (Groq header) | 43.5x |
| Cost per day (avg 17.3 req/day x $0.0000698) | $0.0012 | $0.0121 | no budget cap set | never, at this scale |
| p95 latency (warm) | 1216 ms | 1216 ms until 429s start, then + retry-after waits | - | rides on the rate limit |

- Average generation call: 547 tokens, so 8,000 TPM sustains about 14.6 requests/minute. The traffic simulator already had to pause 7 s between calls to stay under it.
- After the v2 fix ships, an average request uses 1.71x the generation tokens (ingredient lists on diet questions), so the TPM cap is hit at 4.0x today's load instead of 6.8x. The fix makes this limit arrive sooner, not later.
- Latency doesn't grow with volume by itself (each request is independent); it breaks *because of* the rate limit, when 429s force `retry-after` waits or the slow Gemini fallback.
- Caveat: request timestamps in the log are simulated over 7 days, so the busiest-minute figure depends on that arrival pattern. The per-request token and cost numbers are real.

Plan: move to Groq's paid Dev tier (higher TPM) before 10x, keep the 429 -> retry-after -> Gemini fallback path, and alert when `ratelimit_remaining_tokens` (already logged on every generation span) drops below 20%.
