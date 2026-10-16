"""
Release v2: deterministic checks on the model's final answer, before it is
sent. A failed check does not rewrite the answer; the model gets one repair
turn with the exact problems listed (config: max_repairs).

Each rule exists because of a failure in the v1 baseline (see
docs/taxonomy.md). The checks read the corpus and safety tables, never the
model's opinion.

Caveat for the eval numbers: these invariants overlap with some eval
assertions (versions, citations). The judge and the trajectory check are
independent of it, and the allergen assertions are recomputed from the
corpus, not taken from anything the validator says.
"""
import re

from . import corpus, safety

_HISTORY = re.compile(r"(?i)\b(chang\w*|history|original|old|older|previous|before|reformulat\w*|2025|used to)\b")
_QTY = re.compile(r"(?i)\b\d+(?:\.\d+)?\s?(?:g|kg|ml|l)\b")
_TEMP = re.compile(r"(?i)\d+\s?°\s?C\b|\d+\s?degrees? (?:C|celsius)")
_INLINE = re.compile(r"\[([a-z0-9_]+@[a-z0-9\-]+)\]")
_ALLERGY_WORDS = re.compile(r"(?i)allerg|intoleran|co?eliac|celiac|anaphyla")
_RECIPE_TOOLS = {"search_recipes", "get_recipe", "match_pantry", "check_allergens", "scale_recipe"}


def user_states_allergy(question):
    low = question.lower()
    return bool(_ALLERGY_WORDS.search(low)) or any(re.search(p, low) for p, _ in safety._SYNONYMS)


def _checked_keys(steps):
    """Recipe-versions a check_allergens call actually covered (incl. the
    current version the v2 guard switched to)."""
    keys = set()
    for s in steps:
        if s["action"] != "check_allergens":
            continue
        keys.add(f"{s['input'].get('recipe_id')}@{s['input'].get('version')}")
        res = s.get("result") or {}
        if isinstance(res, dict) and res.get("recipe"):
            keys.add(res["recipe"])
    return keys


def problems(question, final, steps):
    """List of plain-English problems with this answer; empty = ship it."""
    out = []
    answer = final.get("answer", "")
    valid = [k for k in sorted(set(final.get("citations", [])) | set(final.get("recommended", [])))
             if corpus.get_by_key(k)]
    used_recipe_tools = any(s["action"] in _RECIPE_TOOLS for s in steps)

    if not _HISTORY.search(question):
        sup = [k for k in valid if corpus.get_by_key(k)["status"] == "superseded"]
        if sup:
            cur = [corpus.get_by_key(k)["superseded_by"] for k in sup]
            out.append(f"You used superseded version(s) {sup}. People cook the current version(s) {cur} today: "
                       f"answer from those instead (get_recipe, and check_allergens if the user has allergies), "
                       f"and cite them.")

    if final.get("invalid_citations"):
        out.append(f"These citations are not in the library: {final['invalid_citations']}. "
                   f"Only cite recipe_id@version keys a tool returned.")

    if used_recipe_tools and not _INLINE.search(answer) and (not final.get("refused") or valid):
        out.append("Cite every recipe you mention inline in the answer text as [recipe_id@version], "
                   "including when you are warning the user off a recipe.")

    if _QTY.search(answer):
        fetched = {f"{s['input'].get('recipe_id')}@{s['input'].get('version')}"
                   for s in steps if s["action"] in ("get_recipe", "scale_recipe")}
        unfetched = [k for k in valid if k not in fetched]
        if unfetched:
            out.append(f"You gave quantities without reading {unfetched}. Call get_recipe (or scale_recipe for "
                       f"a different yield) and use only its numbers.")

    if user_states_allergy(question):
        unchecked = [k for k in final.get("recommended", []) if corpus.get_by_key(k) and k not in _checked_keys(steps)]
        if unchecked:
            out.append(f"The user stated an allergy but you recommend {unchecked} without check_allergens on "
                       f"that exact version. Check it and report the verdict.")
        if final.get("substitutions"):
            swapped_check = any(s["action"] == "check_allergens" and s["input"].get("substitutions") for s in steps)
            if not swapped_check:
                out.append("You propose substitutions for a user with allergies: call check_allergens with "
                           "substitutions=[{\"from\": ..., \"to\": ...}] so the recipe AS SUBSTITUTED is checked, "
                           "and drop any swap that makes it UNSAFE or MAY_CONTAIN.")

    if not final.get("refused"):
        cats = sorted({corpus.get_by_key(k).get("safety_category") for k in valid
                       if corpus.get_by_key(k).get("safety_category")})
        if cats and not _TEMP.search(answer):
            out.append(f"This dish needs a doneness temperature ({', '.join(cats)}): call safe_temperature and "
                       f"state the minimum internal temperature in °C.")
    return out
