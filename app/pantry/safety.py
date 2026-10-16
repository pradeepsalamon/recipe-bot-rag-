"""
Allergen and food-safety rules. Plain Python, no model anywhere in here.

"May contain traces" is a legal declaration on a field, not a sentence for a
retriever to feel its way through. Every allergen verdict in this app comes
from exact set intersection against the `allergens` and `may_contain` fields
of data/recipes.json. The evals use these same functions as their ground
truth, so an allergen assertion can never be "probably" right.
"""
import json
import re
from functools import lru_cache

from . import config, corpus

# Words a user might type -> declaration codes. "nuts" on its own means BOTH
# peanuts and tree nuts: a parent saying "nut allergy" is not making a
# botanical distinction, and guessing the narrower one is the unsafe guess.
_SYNONYMS = [
    (r"\btree[- ]?nuts?\b|\balmonds?\b|\bcashews?\b|\bwalnuts?\b|\bhazelnuts?\b|\bpecans?\b"
     r"|\bpistachios?\b|\bpine ?nuts?\b|\bmacadamias?\b|\bbrazil nuts?\b", ["TREE_NUT"]),
    (r"\bpeanuts?\b|\bgroundnuts?\b|\barachis\b", ["PEANUT"]),
    (r"\bnuts?\b|\bnut[- ]free\b", ["PEANUT", "TREE_NUT"]),
    (r"\bdairy\b|\bmilk\b|\blactose\b|\bcasein\b|\bwhey\b|\bbutter\b|\bghee\b", ["DAIRY"]),
    (r"\beggs?\b", ["EGG"]),
    (r"\bgluten\b|\bwheat\b|\bco?eliac\b|\bceliac\b", ["GLUTEN"]),
    (r"\bsoy\b|\bsoya\b|\bsoybeans?\b", ["SOY"]),
    (r"\bsesame\b|\btahini\b", ["SESAME"]),
    (r"\bfish\b|\banchov(y|ies)\b|\bsalmon\b|\bcod\b|\btuna\b", ["FISH"]),
    (r"\bshellfish\b|\bprawns?\b|\bshrimps?\b|\bcrustaceans?\b|\bcrab\b|\blobster\b", ["SHELLFISH"]),
]


def normalise_allergies(terms):
    """['nuts', 'Dairy', 'kiwi'] -> (['DAIRY','PEANUT','TREE_NUT'], ['kiwi']).

    Anything we cannot map comes back in `unknown`; the caller must say it
    cannot check that allergen rather than quietly ignore it.
    """
    codes, unknown = set(), []
    valid = set(corpus.allergen_codes())
    for raw in terms or []:
        t = str(raw).strip()
        if not t:
            continue
        if t.upper() in valid:
            codes.add(t.upper())
            continue
        if t.upper().replace(" ", "_") in valid:
            codes.add(t.upper().replace(" ", "_"))
            continue
        hit = False
        low = t.lower()
        # Tree-nut / peanut patterns are checked before the generic "nut"
        # pattern, and a specific match stops the generic one firing.
        for pattern, mapped in _SYNONYMS:
            if re.search(pattern, low):
                codes.update(mapped)
                hit = True
                break
        if not hit:
            unknown.append(t)
    return sorted(codes), unknown


def check_declaration(recipe, codes):
    """Exact-match the user's allergen codes against ONE recipe-version's
    declaration fields. Verdict order: UNSAFE > MAY_CONTAIN > SAFE."""
    codes = set(codes)
    contains = sorted(codes & set(recipe["allergens"]))
    traces = sorted(codes & set(recipe["may_contain"]))
    if contains:
        verdict = "UNSAFE"
    elif traces:
        verdict = "MAY_CONTAIN"
    else:
        verdict = "SAFE"
    return {
        "recipe": corpus.key(recipe["recipe_id"], recipe["version"]),
        "status": recipe["status"],
        "superseded_by": recipe.get("superseded_by"),
        "verdict": verdict,
        "contains_user_allergens": contains,
        "may_contain_user_allergens": traces,
        "declared_contains": recipe["allergens"],
        "declared_may_contain": recipe["may_contain"],
        "checked_against": sorted(codes),
        "method": "exact match on declaration fields `allergens` and `may_contain`",
    }


# --------------------------------------------------------------------------
# Substitution table
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _substitutions():
    with open(config.SUBSTITUTIONS_FILE, encoding="utf-8") as f:
        return json.load(f)["substitutions"]


def _ingredient_matches(table_name, ingredient):
    a, b = table_name.lower(), ingredient.lower()
    return a in b or b in a or a.rstrip("s") in b


def find_substitutions(ingredient, avoid):
    """Test-kitchen options for replacing `ingredient` to avoid one allergen
    code. Each option carries its own declaration."""
    codes, unknown = normalise_allergies([avoid])
    rows = [s for s in _substitutions()
            if s["avoid"] in codes and _ingredient_matches(s["ingredient"], ingredient)]
    options = [dict(o, replaces=s["ingredient"], avoids=s["avoid"]) for s in rows for o in s["options"]]
    return {"ingredient": ingredient, "avoid": codes, "unknown_allergen_terms": unknown,
            "options": options, "found": bool(options)}


def lookup_substitute(name):
    """Declaration of a substitute by name, for checking a recipe AS SUBSTITUTED."""
    n = name.lower().strip()
    options = [o for s in _substitutions() for o in s["options"]]
    for o in options:
        if o["substitute"].lower() == n:
            return o
    # No exact name: take every option whose name overlaps and UNION their
    # declarations, so a vague "milk" can never resolve to a safe-looking
    # "oat milk" and hide DAIRY.
    near = [o for o in options if n and (n in o["substitute"].lower() or o["substitute"].lower() in n)]
    if not near:
        return None
    # ...and whatever the name itself says ("milk" is DAIRY even though every
    # table option containing "milk" is a dairy-free one).
    named = set(normalise_allergies([name])[0]) if "free" not in n else set()
    return {"substitute": name,
            "allergens": sorted(named.union(*[set(o["allergens"]) for o in near])),
            "may_contain": sorted(set().union(*[set(o["may_contain"]) for o in near])),
            "matched": [o["substitute"] for o in near]}


def check_substituted(recipe, swaps, codes):
    """Allergen check over the recipe AS SUBSTITUTED.

    swaps: [{"from": "<ingredient text>", "to": "<substitute name>"}].
    Conservative: declared allergens that no ingredient tag explains are
    always kept; a removed ingredient only takes an allergen away if no
    remaining ingredient carries it; an unknown substitute is UNKNOWN, never
    SAFE.
    """
    removed, added_c, added_m, unknown_subs = [], set(), set(), []
    for sw in swaps or []:
        frm, to = sw.get("from", ""), sw.get("to", "")
        removed += [i for i in recipe["ingredients"] if frm and _ingredient_matches(frm, i["item"])]
        decl = lookup_substitute(to)
        if decl is None:
            unknown_subs.append(to)
        else:
            added_c |= set(decl["allergens"])
            added_m |= set(decl["may_contain"])

    explained_c = set().union(*[set(i.get("allergens", [])) for i in recipe["ingredients"]])
    explained_m = set().union(*[set(i.get("may_contain", [])) for i in recipe["ingredients"]])
    remaining = [i for i in recipe["ingredients"] if i not in removed]
    keep_c = set().union(*[set(i.get("allergens", [])) for i in remaining]) if remaining else set()
    keep_m = set().union(*[set(i.get("may_contain", [])) for i in remaining]) if remaining else set()

    contains = (set(recipe["allergens"]) - explained_c) | keep_c | added_c
    may = ((set(recipe["may_contain"]) - explained_m) | keep_m | added_m) - contains

    as_sub = dict(recipe, allergens=sorted(contains), may_contain=sorted(may))
    out = check_declaration(as_sub, codes)
    out["method"] = "exact match on the recipe AS SUBSTITUTED (declaration + substitute declarations)"
    out["swaps"] = swaps
    if unknown_subs:
        out["verdict"] = "UNKNOWN"
        out["unknown_substitutes"] = unknown_subs
    return out


# --------------------------------------------------------------------------
# Safe internal temperatures
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _chart():
    with open(config.FOOD_SAFETY_FILE, encoding="utf-8") as f:
        return json.load(f)["categories"]


def safe_temperature(food):
    low = food.lower()
    for c in _chart():
        if c["category"] == low or any(m in low for m in c["matches"]):
            return {"found": True, "food": food, "category": c["category"],
                    "safe_internal_c": c["safe_internal_c"], "rest_minutes": c["rest_minutes"],
                    "note": c["note"], "source": "data/food_safety.json (USDA FSIS chart, °C)"}
    return {"found": False, "food": food,
            "note": "Not in the food-safety chart. Do not guess a temperature."}


def safe_temperature_for_recipe(recipe):
    cat = recipe.get("safety_category")
    return safe_temperature(cat) if cat else None


# --------------------------------------------------------------------------
# Data integrity: declaration vs ingredient tags
# --------------------------------------------------------------------------
def integrity_report():
    """Where the CMS declaration and the ingredient list disagree. The
    declaration stays the authority; this is a list for the client's
    test kitchen, not something the app silently 'fixes'."""
    rows = []
    for r in corpus.all_recipes():
        tags_c = set().union(*[set(i.get("allergens", [])) for i in r["ingredients"]])
        tags_m = set().union(*[set(i.get("may_contain", [])) for i in r["ingredients"]])
        undeclared = sorted(tags_c - set(r["allergens"]))
        undeclared_m = sorted(tags_m - set(r["may_contain"]) - set(r["allergens"]))
        unexplained = sorted(set(r["allergens"]) - tags_c)
        if undeclared or undeclared_m or unexplained:
            rows.append({"recipe": corpus.key(r["recipe_id"], r["version"]),
                         "in_ingredients_not_declared": undeclared,
                         "may_contain_in_ingredients_not_declared": undeclared_m,
                         "declared_but_no_ingredient_tag": unexplained})
    return rows
