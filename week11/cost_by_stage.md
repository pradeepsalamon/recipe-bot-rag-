# Cost per query, by stage

Request: `d125333e-1309-4adf-a43c-5eea52988a25` (2026-10-01T02:39:01+00:00, user `u4111`, prompt `v1`, model `openai/gpt-oss-20b`)

> I'm cooking Ven Pongal for a dairy-free guest. What can I fry the cashews in instead of butter?

| Stage | Calls | Latency | Tokens in | Tokens out | Cost (USD) | Share of cost |
|---|---|---|---|---|---|---|
| retrieval | 4 | 13.6 ms | 31 | 0 | $0.0000000 | 0.0% |
| tools | 0 | 0.0 ms | 0 | 0 | $0.0000000 | 0.0% |
| generation | 1 | 817.4 ms | 430 | 166 | $0.0000821 | 100.0% |
| **total** | | **831.2 ms** | 461 | 166 | **$0.0000821** | 100% |

Per span:

| Span | Stage | Latency | Model | In | Out | Cost |
|---|---|---|---|---|---|---|
| retrieval.embed | retrieval | 10.8 ms | all-MiniLM-L6-v2 | 31 | 0 | $0.0000000 |
| retrieval.dense | retrieval | 2.4 ms | - | 0 | 0 | $0.0000000 |
| retrieval.bm25 | retrieval | 0.4 ms | - | 0 | 0 | $0.0000000 |
| retrieval.rrf_fuse | retrieval | 0.0 ms | - | 0 | 0 | $0.0000000 |
| generation.llm | generation | 817.4 ms | openai/gpt-oss-20b | 430 | 166 | $0.0000821 |

How the generation number is made:

- 430 input x $0.075/1M + 166 output x $0.3/1M = $0.0000821
- 137 of the 166 output tokens are hidden reasoning tokens (gpt-oss thinks before it answers). They are billed as output, so they are 50% of this request's cost.

Why retrieval and tools show $0:

- Retrieval embeds the query locally with `all-MiniLM-L6-v2` and searches a local Chroma + in-memory BM25. No API is called, so there is no per-query bill; its cost is CPU time (the latency column). The embed span still records the token count so we know what a hosted embedding API would charge if we moved off CPU.
- Tools: v1 makes no tool calls (0 calls). v2 adds `tool.recipe_facts`, a local Chroma metadata lookup, also $0 - but the chunks it adds go into the prompt, so its real cost shows up as extra *generation input tokens* (see the comparison below).

## Same question after the fix (v2, from the eval run)

| | v1 (this trace) | v2 (fixed) | change |
|---|---|---|---|
| generation tokens in | 430 | 1392 | +962 |
| tool calls | 0 | 1 | |
| cost / query | $0.0000821 | $0.0002142 | +161% |

The fix costs more per diet question because the whole ingredient list goes into the prompt (the tool itself is free; its chunks are not).

Fleet impact, measured: across the eval runs, diet questions cost 2.45x on v2 vs v1 and other questions 1.13x. Applied to last week's mix (31/121 = 26% diet questions), the average cost per query goes $0.0000698 -> $0.0001015 (**+46%**). That is the price of the safety fix, and it's tiny in dollars. One leak to close next: the classifier calls "How many cashews for Ven Pongal?" `dietary` (because of *cashew*), so the guard fires on plain quantity questions too.

## Fleet average over 121 logged requests (v1)

| Stage | Avg cost / query | Avg latency (warm) |
|---|---|---|
| retrieval | $0.0000000 | 14.0 ms |
| tools | $0.0000000 | 0.0 ms |
| generation | $0.0000698 | 853.4 ms |
| total | $0.0000698 | 867.4 ms |

Plus 1 cold start(s) of 12.7 s (first request after a process start; fix = load the index at boot).
