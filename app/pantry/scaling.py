"""
Scaling calculator (week 7 scale_recipe, rebuilt on structured quantities).

Quantities scale. Times and oven temperatures do not: four trays of
shortbread bake for 20 minutes each, not 80, and a bigger chicken is done
when the probe says so, not after 4x the minutes. The tool says this in its
result so the model has no number to multiply.
"""
from . import corpus, safety


def _round(qty, unit):
    if unit in ("g", "ml") and qty >= 10:
        return int(round(qty))
    if unit in ("kg", "L"):
        return round(qty, 2)
    return round(qty, 1)


def scale(recipe, target_amount):
    base = recipe["yield"]["amount"]
    factor = target_amount / base
    rows = []
    for i in recipe["ingredients"]:
        if i["qty"] is None:
            rows.append({"item": i["item"], "qty": None, "unit": i["unit"]})
            continue
        q = _round(i["qty"] * factor, i["unit"])
        row = {"item": i["item"], "qty": q, "unit": i["unit"], "original_qty": i["qty"]}
        if i["unit"] in ("piece", "pieces") and q != int(q):
            row["note"] = "fractional count: round to the nearest whole and adjust by eye"
        rows.append(row)

    times = {k: recipe[k] for k in ("prep_minutes", "cook_minutes", "rest_minutes") if recipe.get(k) is not None}
    result = {
        "recipe": corpus.key(recipe["recipe_id"], recipe["version"]),
        "status": recipe["status"],
        "original_yield": recipe["yield"],
        "target_yield": {"amount": target_amount, "unit": recipe["yield"]["unit"]},
        "factor": round(factor, 3),
        "ingredients": rows,
        "times_minutes_UNCHANGED": times,
        "oven_c_UNCHANGED": recipe.get("oven_c"),
        "time_rule": ("Cook/bake times and oven temperature do NOT scale with quantity. "
                      "Cook in batches of the original size with the original time, "
                      "or check doneness; never multiply the time by the factor."),
    }
    temp = safety.safe_temperature_for_recipe(recipe)
    if temp:
        result["doneness_rule"] = (f"Larger quantities take longer to reach temperature: cook until the "
                                   f"thickest part reads {temp['safe_internal_c']}°C.")
    return result
