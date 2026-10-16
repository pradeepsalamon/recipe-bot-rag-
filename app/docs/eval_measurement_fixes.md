# Eval measurement fixes

On 2026-10-16, reading the v1 baseline answers showed that some failures came from the **assertions**, not the system. The answers were never re-generated: `python run.py rescore <run>.jsonl` re-applies the corrected assertions to the stored answers. **Both v1 and v2 are scored with the same, final assertions.**

| # | Assertion | Problem found by reading | Example | Fix |
|---|---|---|---|---|
| 1 | `cites_with_version` | Required inline `[recipe@version]` in the prose. The user actually sees `final.citations` as clickable, version-named Sources (`run.py` prints each with its card path), which is what requirement 1 asks for | B30: "250 g of urad dal" + Sources `[medu_vada@original]` was failed | Pass = at least one valid version-named citation shown, and no invalid ones. Inline brackets are reported separately as an informational rate |
| 2 | may-contain warning | Regex `may contain` missed the code spelling `MAY_CONTAIN` | B10: "marked as MAY_CONTAIN gluten, so it is not guaranteed to be gluten-free" was scored allergen-unsafe | `may[\s_-]?contain`; "not guaranteed" counts as a warning |
| 3 | `allergen_safe_as_substituted` | Dropped the superseded-version rule, so it could report *fewer* unsafe answers than the published check | B03 was unsafe as published but "safe" as substituted | As-substituted now includes every published failure, plus what the swaps add |
| 4 | quantity regexes (B19–B21) | Missed thousands separators | B20: "1,600 g of Idli rice" was failed | `1,?600`, `1,?200`, `3,?200` |
| 5 | B24 (new check, not a fix) | No assertion caught an answer endorsing pink minced beef next to "71°C"; only the judge noticed | trace `36ca9def8a49`: "grill each side for about 5 minutes… a medium-rare (pink in the middle) result" | `answer_not_matches` for endorsing medium-rare. This is the failure→test loop: found in a trace, now a permanent check |

## Effect on the v1 baseline (same 34 answers)

| Scoring | System pass | Allergen-unsafe (published) | Allergen-unsafe (as substituted) |
|---|---|---|---|
| Original assertions (`20261016_2004_v1_baseline.md`) | 6/34 (18%) | 4/20 | 1/20 |
| Final assertions (`20261016_2004_v1_baseline_rescored.md`) | **18/34 (53%)** | **3/20** | **3/20** |

The original "6/34" mostly measured whether the model wrote brackets in its prose. Reporting it as the baseline would have made any fix look better than it is.
