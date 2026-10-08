# Prompt / release changelog

Every request logs `prompt_version` and `prompt_sha` (first 10 hex chars of the prompt's
sha256), so any answer in the log can be tied to the exact prompt text that produced it.

## v2.1 - 2026-10-08 (sha `b51172732b`, same prompt as v2) - cost experiment, not yet promoted

Same prompt and retrieval as v2; only `reasoning_effort="low"` on gpt-oss. The cost-by-stage
breakdown showed hidden reasoning tokens were ~50% of a request's cost, so that is what we cut.
Result over the same 13 eval questions: **cost/query -26%** ($0.0001135 -> $0.0000840),
reasoning tokens -83%, suite unchanged at 11/13 with Allergen safety 4/4
(`evals/results/suite_v2.1_cost_experiment.txt`, `cost_improvement.md`).
Ships behind v2 with the same canary rules once v2 is stable. One release at a time,
so if something moves we know which change moved it.

## v2 - 2026-10-08 (sha `b51172732b`)

**Why:** support drill, "recommended a dairy-free substitution that wasn't dairy-free".
v1 told a cook with a dairy-free guest: *"Use ghee to fry the cashews. [chunk_0df1a3f4]"*.

**What changed (two layers, measured separately):**

| Change | Layer | File |
|---|---|---|
| Dietary rules block added to the system prompt (ghee/butter/... are dairy; never offer dairy as dairy-free; don't infer "dairy-free" from missing context; ingredient rows beat header tags; recommend the recipe's own non-dairy option, e.g. "Ghee or oil") | prompt | `recipe_v2.txt` |
| `dietary_guard`: for `dietary` / `dietary_swap` questions, the `recipe_facts` tool adds the recipe's allergen line and full ingredient list to the context | retrieval | `config.py`, `pipeline.py` |

**Evidence** (`evals/results/`):

| Run | Suite | New cases | Allergen-safety mode |
|---|---|---|---|
| v1, suite only, before the case existed | 7/11 | - | 0/2 |
| v1 + new case file (**RED**) | **7/13** | 0/2 | 0/4 |
| v2 prompt only, guard off (ablation) | 7/13 | 0/2 | 0/4 |
| v2 prompt + guard (**GREEN** for the new cases) | **11/13** | **2/2** | **4/4** |

The prompt alone made the Pongal answer safe ("ghee is a dairy product") but couldn't make it
*right*: the allergen line and ingredient rows never reached the model. The retrieval guard
is what fixes it. Still failing in every run, before and after: `fact_idli_salt` and
`fact_vada_oil_heat`, both top-3 retrieval misses on non-diet questions (right chunk sits
at rank 5 and 7). They were failing before this change and are not caused by it.
They're left for a separate release so this one changes one thing.

**Canary:** set `CANARY_PERCENT = 10` (users sticky-hashed onto v2) for 48 h; promote v2 to `STABLE_RELEASE` only if `logq.py find --prompt-version v2 --flag dairy_violation` stays empty, the suite holds 11/13 with Allergen safety 4/4, and p95 latency stays within +20%.
**Rollback:** set `CANARY_PERCENT = 0` (one line in `config.py`, everyone is back on v1 on the next request) the moment a v2 trace is flagged `dairy_violation`, the suite drops below 11/13, or diet-question cost per query more than doubles.

Not done on purpose: semantic caching. Caching the v1 answer to "dairy-free fat for the
cashews?" would have served the ghee answer instantly to every near-identical question.
Any cache gets keyed on `prompt_version` and flushed on a version bump.

## v1 - week 3 (sha `f14872c545`)

Strict grounded recipe assistant, top-3 hybrid retrieval (dense + BM25, RRF). Copied
verbatim from `rag_pipeline.py` so the RED run tests what was actually live.
