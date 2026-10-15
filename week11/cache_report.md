# Caching: measured on last week's traffic

Replay of 121 production questions through `v2.1`, original order, users and timestamps, semantic cache on (threshold 0.88, TTL 24 h). Every miss was a real Groq call, so the prompt-cache numbers come from the same run. Raw data: `logs/cache_experiment.jsonl`.

## 1. Semantic cache (ours)

| | Value |
|---|---|
| Requests replayed | 121 |
| Never cached (diet / allergen questions) | 31 |
| Not stored (in-scope refusals, usually retrieval misses) | 57 |
| Served from cache | **6** (5% of all, 7% of eligible) |
| Cost without the semantic cache | $0.008798 ($0.0000727/query) |
| Cost with it | $0.008407 ($0.0000695/query) |
| **Saved** | **$0.000390 (4.4%)** |
| p50 latency, hit vs miss | **10 ms vs 778 ms** |
| Hits that break a guard on re-check (different recipe / numbers) | 0 |

Every hit, for a human to audit:

| Asked | Served the answer to | Similarity |
|---|---|---|
| How much tamarind pulp goes in Rasam? | How much tamarind pulp goes in Rasam? | 1.0 |
| What vegetables go in Sambar? | What vegetables go in Sambar? | 1.0 |
| What vegetables go in Sambar? | What vegetables go in Sambar? | 1.0 |
| How many idlis does the recipe make? | How many idlis does the recipe make? | 1.0 |
| What's the weather like today? | What's the weather like today? | 1.0 |
| Can I skip the onion in medu vada? | Can I skip the onion in medu vada? | 1.0 |

### TTL what-if (offline, same requests, no extra model calls)

| TTL | Served from cache | Saved |
|---|---|---|
| 24 h | 6 (5%) | $0.000390 (4.4%) |
| 72 h | 12 (10%) | $0.000736 (8.4%) |
| 168 h | 16 (13%) | $0.000974 (11.1%) |

A longer TTL serves more, but the recipe corpus or prompt can change in between. The release fingerprint covers prompt / model / retrieval / corpus changes; the TTL is the limit on everything else. 24 h stays the default until a canary says otherwise.

### Probes

Expectations were written into `PROBES` before the run; the *why* column is worked out from the data afterwards.

| Question | Expected | Got | Why |
|---|---|---|---|
| How much salt goes into idli? | hit | miss | `How much salt is used in the Idli recipe?` was asked, but its answer was a refusal (retrieval miss), so it was never stored - the refusal rule working |
| How long do I ferment idli batter? | hit | hit | similarity 0.9564 to `How long should the Idli batter ferment?` |
| Tips for making dosa crispy? | hit | miss | `How do I make crispy Dosa?` was asked, but its answer was a refusal (retrieval miss), so it was never stored - the refusal rule working |
| Can I swap ghee for oil in rasam? | hit | miss | no matching question was asked last week (closest: `I'm lactose intolerant, can I replace the ghee in pongal with oil?`, 0.521, different recipe) |
| How much salt is used in the Dosa recipe? | miss | miss | correctly not served (best similarity 0.5605, guards) |
| Double the sambar for 12 people - how much toor dal? | miss | miss | correctly not served (best similarity 0.3141, guards) |
| Is Rasam vegan? | miss | miss | dietary questions are never cached |
| I'm cooking Ven Pongal for a dairy-free guest. What can I fry the cashews in instead of butter? | miss | miss | dietary_swap questions are never cached |

Safety rules (each one backed by a test in `evals/test_semantic_cache.py`):

- Diet / allergen questions are never cached - the dairy bug is exactly what a cache would spread.
- Recipes and numbers in the question must match exactly: "sambar for 8" vs "for 12" scores 0.952 on MiniLM, higher than most real paraphrases.
- In-scope refusals are not stored (they are usually retrieval misses).
- Keyed on a release fingerprint (prompt sha, retrieval settings, model, corpus): a version bump or re-ingest is an automatic flush. The TTL bounds staleness.
- Every cached answer in the log points to the trace that produced it (`cache.source_trace_id`, `logq.py find --cache-hit`).
- Off in production (`SEMANTIC_CACHE.enabled = False`) until it goes through a canary like a release.

## 2. Prompt caching (Groq's, automatic)

| | Value |
|---|---|
| Generation calls in this run | 122 |
| Calls with cached input tokens | **35** (29%) |
| Cached tokens per hit | 256 |
| Input tokens billed at the cached rate | 8,960 of 92,448 (9.7%) |
| **Saved** (50% off those tokens) | **$0.000336** (3.6% of spend) |

What the numbers say:
- Groq caches in 256-token blocks from the start of the prompt. Every hit was exactly one block: the first 256 tokens of the system prompt, which is identical on every call. Everything after it (retrieved context, question) changes per request.
- The v1 prompt (601 chars, ~140 tokens) is shorter than one block, so v1 could **never** get a prompt-cache hit. The v2 dairy fix made the prompt longer (1443 chars), and that is what made it cacheable at all.
- Only some calls hit, with no pattern by question type or timing - most likely requests land on different Groq servers that each keep their own cache. A first test of 4 byte-identical calls got 0 hits, so a small test can easily miss it; this run of 122 calls is the number to trust.
- The ceiling here is low: the stable prefix is one block. Getting more would mean a longer fixed part before the context (e.g. few-shot examples), which costs tokens of its own.

## 3. What each cache is worth for this app

- Semantic cache: 4.4% cost, and 778 ms -> 10 ms on a hit. Traffic is ~17 questions/day, so few repeats land inside 24 h. It pays off on latency and at higher volume - at 10x traffic the same questions repeat 10x as often.
- Prompt cache: 3.6% cost, free and risk-free (the answer is still generated fresh). Keep the system prompt first and stable.
- Neither is a fix for anything: the reasoning_effort change (-26%, `cost_improvement.md`) saved more than both caches together.

## 4. Side finding: the app refuses most real questions

Same 121 questions: v1 refused **76 (63%)**, v2.1 refused **65 (54%)**. So the cheaper release did not quietly get worse (the diet guard now answers diet questions v1 couldn't), but more than half of real traffic gets "not in the recipe documents" - many questions (brown rice for dosa, scaling, troubleshooting) aren't covered by the 6 recipe cards, and top-3 retrieval misses some that are. That, not cost, is the next thing to fix - and it's also why only 33 answers were worth caching.
