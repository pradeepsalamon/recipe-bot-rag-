# Cost improvement: v2 -> v2.1

Same 13 eval questions through both releases (`logs/eval_runs.jsonl`). Attributed first, optimised second: `cost_by_stage.md` shows generation is 100% of the bill and hidden reasoning tokens are about half of it, so that is the one thing changed.

| Per query (avg) | v2 | v2.1 | change |
|---|---|---|---|
| generation input tokens | 876 | 876 | +0% |
| generation output tokens | 160 | 61 | -62% |
| of which reasoning | 113 | 19 | -83% |
| generation latency | 822 ms | 760 ms | -8% |
| **cost / query** | **$0.0001135** | **$0.0000840** | **-26%** |

Quality gate: see `evals/results/` - the suite must score the same on v2.1 as on v2 (same cases passing, Allergen safety 4/4) or the saving doesn't count.
