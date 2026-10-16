"""
What the MODEL sees of a tool result.

Every tool result is re-sent to the model on every later loop iteration, so
its size is paid again per step. The MCP server still returns the full
result (external clients and our traces get everything); this module trims
it for the model's context only.

Never dropped, because the safety rules depend on them: recipe key, status,
superseded_by, allergen verdicts and the matched codes, declared
contains/may-contain, unknown allergen terms, substitute allergens, the
"times do not scale" rule and the doneness temperature.
"""
import json


def _qty(i):
    if i.get("qty") is None:
        return f"{i['item']} ({i['unit']})"
    return f"{i['qty']} {i['unit']} {i['item']}"


def _drop_empty(d):
    return {k: v for k, v in d.items() if v not in (None, [], "", {})}


def for_model(name, result):
    if not isinstance(result, dict) or "error" in result:
        return result
    try:
        fn = _COMPACTORS.get(name)
        return fn(result) if fn else result
    except (KeyError, TypeError):
        return result  # unexpected shape: send it whole rather than lose data


def _search(r):
    return _drop_empty({
        "results": [_drop_empty({"recipe": h["recipe"], "title": h["title"], "status": h["status"],
                                 "superseded_by": h.get("superseded_by"),
                                 "snippet": h["snippet"][:160]})
                    for h in r["results"]],
        "excluded_by_declaration": r.get("excluded_by_declaration"),
        "hidden_superseded": r.get("hidden_superseded"),
        "unknown_allergen_terms": r.get("unknown_allergen_terms"),
    }) or {"results": []}


def _recipe(r):
    return _drop_empty({
        "warning": r.get("warning"),
        "citation": r.get("citation"), "status": r["status"], "superseded_by": r.get("superseded_by"),
        "title": r["title"], "reformulation_note": r.get("reformulation_note"),
        "declared_contains": r["allergens"], "declared_may_contain": r["may_contain"],
        "yield": f"{r['yield']['amount']} {r['yield']['unit']}",
        "prep_minutes": r.get("prep_minutes"), "cook_minutes": r.get("cook_minutes"),
        "rest_minutes": r.get("rest_minutes"), "oven_c": r.get("oven_c"),
        "ingredients": [_qty(i) for i in r["ingredients"]],
        "method": r["method"], "notes": r.get("notes"),
    })


def _check(r):
    return _drop_empty({
        "recipe": r["recipe"], "status": r["status"], "superseded_by": r.get("superseded_by"),
        "verdict": r["verdict"],
        "contains_user_allergens": r["contains_user_allergens"],
        "may_contain_user_allergens": r["may_contain_user_allergens"],
        "declared_contains": r["declared_contains"], "declared_may_contain": r["declared_may_contain"],
        "unknown_allergen_terms": r.get("unknown_allergen_terms"),
        # v2: current-version guard and the as-substituted check
        "note": r.get("note"), "asked_about": r.get("asked_about"),
        "asked_version_verdict": r.get("asked_version_verdict"),
        "published_verdict": r.get("published_verdict"), "swaps": r.get("swaps"),
        "unknown_substitutes": r.get("unknown_substitutes"),
    }) | {"verdict": r["verdict"]}


def _subs(r):
    return _drop_empty({
        "ingredient": r["ingredient"], "avoid": r["avoid"],
        "options": [_drop_empty({"substitute": o["substitute"], "allergens": o["allergens"] or "none",
                                 "may_contain": o["may_contain"], "ratio": o.get("ratio"), "note": o.get("note")})
                    for o in r["options"]],
        "unknown_allergen_terms": r.get("unknown_allergen_terms"),
    }) | {"found": r["found"]}


def _scale(r):
    return _drop_empty({
        "recipe": r["recipe"], "status": r["status"], "factor": r["factor"],
        "target_yield": f"{r['target_yield']['amount']:g} {r['target_yield']['unit']}",
        "ingredients": [_qty(i) + (f" (was {i['original_qty']})" if "original_qty" in i else "")
                        for i in r["ingredients"]],
        "times_minutes_UNCHANGED": r["times_minutes_UNCHANGED"], "oven_c_UNCHANGED": r.get("oven_c_UNCHANGED"),
        "time_rule": r["time_rule"], "doneness_rule": r.get("doneness_rule"),
    })


def _pantry(r):
    return _drop_empty({
        "results": [_drop_empty({"recipe": h["recipe"], "title": h["title"], "status": h["status"],
                                 "superseded_by": h.get("superseded_by"), "coverage": h["coverage"],
                                 "missing": h["missing"][:6], "total_minutes": h["total_minutes"]})
                    for h in r["results"]],
        "unknown_allergen_terms": r.get("unknown_allergen_terms"),
    }) or {"results": []}


def _temp(r):
    if not r.get("found"):
        return r
    return {"food": r["food"], "category": r["category"], "safe_internal_c": r["safe_internal_c"],
            "rest_minutes": r["rest_minutes"], "note": r["note"]}


_COMPACTORS = {
    "search_recipes": _search, "get_recipe": _recipe, "check_allergens": _check,
    "find_substitution": _subs, "scale_recipe": _scale, "match_pantry": _pantry,
    "safe_temperature": _temp,
}


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
