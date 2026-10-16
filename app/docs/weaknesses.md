# Top known weaknesses

Written **2026-10-16 (Friday)**, from the v1 baseline and the work around it. Unprompted, ranked by how much harm they could do.

## 1. The allergen filter can hand the user the old recipe (taxonomy M1, critical)

- **v1 measurement:** 2 of 7 version cases unsafe (B03, B07).
- **What happens:** when the agent passes an allergy to search, the exact-match filter correctly removes the *current* version. The superseded one survives, gets checked (SAFE for *that* version), and is served.
- **v2 changes:**
  - hides superseded versions from search;
  - makes `check_allergens` answer for the current version;
  - validates the answer before sending it.
- **Still open:**
  - the effect is **not yet measured**: the after-run was stopped by the provider's daily cap;
  - the deeper problem is design: an exclusion filter that silently hides the recipe the user *named* also causes the refusals in M2. A filter that *annotates* instead of removing would fix both, but isn't built.

## 2. Allergen safety rests entirely on the client's declarations (M4, M3, critical)

- The system never second-guesses a declaration.
  - **Rasam** declares "None" while its ingredient list says "ghee or oil", and v1 told a milk-allergic user it is safe (B13).
  - **Unknown allergens:** in B28 the checker correctly reported "kiwi" as unknown, and the model still said "safe".
- **v2 doesn't fix either:**
  - the validator has no rule for unknown allergen terms;
  - the conflict list (`run.py check-data`) goes to nobody.
- **Next:** a validator rule that blocks "safe" when `unknown_allergen_terms` is non-empty, and the conflict report sent to the client's test kitchen.

## 3. The free tier carries ~40 questions a day

- **Measured:** about 5,000 tokens per question against Groq's 200k tokens/day. One eval run used 182k, and the next was cut off.
- **Consequences:**
  - the "after" number couldn't be produced the same day;
  - v2 likely uses *more* tokens per question (repair turns), which lowers the ceiling further;
  - at 50,000 questions/day the cap is exceeded 1,246×.
- **The fix is not engineering:** a paid tier, about $19/day at 50k questions. Engineering can push it back: v2 already sends the model 41% smaller tool results.

## Also known, ranked lower

- **The judge is unvalidated on integrated outputs.** It failed 4 cases whose assertions all passed, and on reading, two of those look like judge errors (B23, B27). No hand labels exist yet, so its agreement is unknown.
- **22 recipe-versions, not 600:** retrieval numbers don't transfer.
- **Substitutions:** v1 called `find_substitution` in 0 of 5 substitution cases. It refused instead (M2).
