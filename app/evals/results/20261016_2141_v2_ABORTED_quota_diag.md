# Eval report: 20261016_2141_v2_diag

Release `v2`, model `openai/gpt-oss-20b`, prompt `agent_v2`, 0 cases scored, run 2026-10-16T21:49.

**System pass (all assertions, then judge): 0/0 = 0.0%**

Excluded as infrastructure errors (provider outage / quota, no answer produced): B03. They are not counted as passes or failures.

## Safety numbers (deterministic, exact match on declarations)

| Metric | Failing / n | Rate |
|---|---|---|
| Allergen-unsafe answer (as published) | 0 / 0 | 0.0% |
| Allergen-unsafe answer (as substituted by our own swaps) | 0 / 0 | 0.0% |
| Superseded version cited/recommended | 0 / 0 | 0.0% |
| Recommended without a visible check_allergens call | 0 / 0 | 0.0% |
| Citation missing its version / invalid | 0 / 0 | 0.0% |
| Answer prose without an inline [recipe@version] (informational, not pass/fail) | 0 / 0 | 0.0% |

Cases that pass the published-recipe check but FAIL once the check runs on the recipe as substituted: **0** []

## Pass rate by category

| Category | Pass | n | Rate |
|---|---|---|---|

## Allergy cases, one by one

The hostile question is 'which cases have an allergy in them and what do they score', not the average.

| Case | Allergies | Pass | Failed assertions | Trace |
|---|---|---|---|---|

## Trajectory (week 8 method on the integrated agent)

Tool-choice accuracy (all required tools called): **0/0 = 0.0%**  
Outcome pass rate 0.0% vs trajectory pass rate 0.0%: **gap +0.0 points**

| | trajectory ok | trajectory wrong |
|---|---|---|
| outcome pass | 0 | 0 (right answer, wrong path) |
| outcome fail | 0 (right path, wrong answer) | 0 |


## Judge

Pass on deterministic assertions alone: **0/0 = 0.0%**. The headline system pass above also requires the judge, which is NOT yet validated against hand labels on these outputs, so read both numbers.

Judge (`openai/gpt-oss-20b`, grounding + answers-the-question only, never allergens) ran on 0 cases that passed every assertion: 0 pass.
Judge agreement with hand labels is computed by `python run.py judge <this run>.jsonl` after `python run.py label <this run>.jsonl`.

## What this suite does NOT cover

- Taste, texture or whether a substitution actually bakes well: the suite checks that a swap is allergen-safe, not that the shortbread still holds together.
- Multi-turn conversations: every case is a single question; allergies stated in turn 1 and forgotten by turn 3 are not tested.
- Allergens outside the 9 declared codes (kiwi, mustard, celery, lupin...) beyond one refusal case.
- Correctness of the client's declarations themselves: the suite trusts the CMS fields as ground truth (see `run.py check-data` for the one known conflict, rasam).
- Non-English questions, typos and units the user converts themselves (cups, °F).
- Load: every case runs alone; nothing here measures behaviour under concurrent traffic or rate-limit pressure.

## Every case

| Case | Category | Pass | Traj | Failed assertions |
|---|---|---|---|---|
