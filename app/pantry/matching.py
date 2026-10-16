"""
"What can I make with what's in the fridge": rank recipe-versions by how
much of their ingredient list the user already has. Deterministic keyword
overlap; staples (salt, water, oil, pepper) are assumed to be in any kitchen.
"""
import re

from . import corpus, safety

_STAPLES = {"salt", "water", "oil", "black pepper", "pepper"}
_STOP = {"chopped", "sliced", "grated", "crushed", "cooked", "mashed", "split", "husked", "fresh",
         "optional", "for", "frying", "cooking", "or", "and", "the", "of", "a", "finely", "soaked",
         "pulp", "extracted", "softened", "melted", "ripe", "each", "g", "cut", "bone", "in", "slit"}


def _words(text):
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOP and len(w) > 2}


def _is_staple(item):
    low = item.lower()
    return any(low.startswith(s) for s in _STAPLES)


def match(have, exclude_allergens=None, max_minutes=None, top_k=5):
    have_words = set().union(*[_words(h) for h in have]) if have else set()
    codes, unknown = safety.normalise_allergies(exclude_allergens or [])
    rows = []
    for r in corpus.all_recipes():
        if codes and set(codes) & (set(r["allergens"]) | set(r["may_contain"])):
            continue
        total = (r.get("prep_minutes") or 0) + (r.get("cook_minutes") or 0) + (r.get("rest_minutes") or 0)
        if max_minutes and total > max_minutes:
            continue
        needed = [i["item"] for i in r["ingredients"] if not _is_staple(i["item"])]
        got = [i for i in needed if _words(i) & have_words]
        missing = [i for i in needed if i not in got]
        if not got:
            continue
        rows.append({"recipe": corpus.key(r["recipe_id"], r["version"]), "title": r["title"],
                     "status": r["status"], "superseded_by": r.get("superseded_by"),
                     "coverage": round(len(got) / max(1, len(needed)), 2),
                     "have": got, "missing": missing, "total_minutes": total})
    rows.sort(key=lambda x: (-x["coverage"], x["total_minutes"]))
    return {"have": have, "excluded_for": codes, "unknown_allergen_terms": unknown,
            "max_minutes": max_minutes, "results": rows[:top_k]}
