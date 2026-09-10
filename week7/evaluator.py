"""
Week 7 Task Set B — Evaluator

Deterministic pass/fail evaluation for both Agent and Workflow.
Validates actual task requirements, not just "did it return something."
"""

import json, re


def evaluate_response(response: dict, expected: dict) -> dict:
    """
    Evaluate a system response against expected criteria.

    Returns:
      {
        "passed": bool,
        "checks": {check_name: {"passed": bool, "detail": str}, ...},
        "score": float (0.0-1.0),
      }
    """
    checks = {}

    if response is None or (isinstance(response, dict) and "error" in response):
        return {
            "passed": False,
            "checks": {"response_exists": {"passed": False, "detail": "No valid response or error returned"}},
            "score": 0.0,
        }

    # Normalize response
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except json.JSONDecodeError:
            response = {"raw": response}

    # 1. Check recipe selected correctly
    recipe_id = expected.get("recipe_id", "")
    if recipe_id:
        title = str(response.get("title", "")).lower()
        recipe_name = recipe_id.replace("_", " ")
        # Check if the recipe name appears in the title
        found = recipe_name in title or recipe_id in title
        # Also check for partial matches
        if not found:
            parts = recipe_name.split()
            found = all(part in title for part in parts)
        checks["correct_recipe"] = {
            "passed": found,
            "detail": f"Expected '{recipe_name}' in title '{response.get('title', '')}'"
        }

    # 2. Check serving count
    target_servings = expected.get("target_servings")
    if target_servings:
        servings_str = str(response.get("servings", ""))
        has_target = str(target_servings) in servings_str
        checks["correct_servings"] = {
            "passed": has_target,
            "detail": f"Expected {target_servings} in '{servings_str}'"
        }

    # 3. Check ingredients present
    must_contain = expected.get("must_contain_ingredients", [])
    ingredients_text = " ".join(str(i) for i in response.get("ingredients", [])).lower()
    for ing in must_contain:
        key = f"has_ingredient_{ing.replace(' ', '_')}"
        found = ing.lower() in ingredients_text
        # Also try partial match
        if not found:
            parts = ing.lower().split()
            found = any(part in ingredients_text for part in parts)
        checks[key] = {
            "passed": found,
            "detail": f"Looking for '{ing}' in ingredients"
        }

    # 4. Check method keywords
    method_keywords = expected.get("must_contain_method_keywords", [])
    method_text = " ".join(str(s) for s in response.get("method", [])).lower()
    for kw in method_keywords:
        key = f"method_has_{kw}"
        checks[key] = {
            "passed": kw.lower() in method_text,
            "detail": f"Looking for '{kw}' in method"
        }

    # 5. Check prohibited allergens absent
    prohibited = expected.get("prohibited_allergens", [])
    if prohibited:
        allergen_warning = str(response.get("allergen_warning", "")).lower()
        # Also check ingredients for allergen indicators
        all_text = ingredients_text + " " + method_text

        allergen_ingredient_map = {
            "DAIRY": ["ghee", "butter", "milk", "cream", "yogurt", "curd", "paneer", "cheese"],
            "TREE_NUT": ["cashew", "almond", "walnut", "pistachio"],
            "PEANUT": ["peanut", "groundnut"],
            "GLUTEN": ["wheat flour"],  # Don't flag just "flour" since rice flour is fine
            "EGG": ["egg"],
        }

        for allergen in prohibited:
            # Check if problematic ingredients are still present WITHOUT substitution
            problematic_ings = allergen_ingredient_map.get(allergen, [])
            substitutions_made = str(response.get("substitutions_made", [])).lower()

            # If a substitution was made for this allergen, it's likely handled
            allergen_handled = False
            if substitutions_made and substitutions_made != "[]":
                for pi in problematic_ings:
                    if pi in substitutions_made:
                        allergen_handled = True
                        break

            # If the ingredient is in the ingredients but no substitution was made
            has_problematic = False
            for pi in problematic_ings:
                if pi in ingredients_text and not allergen_handled:
                    # Check if it's actually a substitute (like "coconut milk" matching "milk")
                    # Only flag if it's standalone, not part of a safe compound
                    safe_compounds = [
                        "coconut milk", "coconut oil", "coconut cream", "coconut yogurt",
                        "rice flour", "sunflower seeds", "gluten-free asafoetida",
                        "sunflower oil", "flax egg",
                    ]
                    is_safe = any(sc in ingredients_text for sc in safe_compounds if pi in sc)
                    if not is_safe:
                        has_problematic = True
                        break

            checks[f"allergen_{allergen}_absent"] = {
                "passed": allergen_handled or not has_problematic,
                "detail": f"Checking {allergen} is handled via substitution or absent from ingredients"
            }

    # 6. Check required substitutions performed
    required_subs = expected.get("required_substitutions", [])
    substitutions_text = str(response.get("substitutions_made", [])).lower()
    for sub in required_subs:
        key = f"substitution_{sub}"
        # Check if the substitution is mentioned
        found = sub.lower() in substitutions_text
        # Broader check: the ingredient should not appear unchanged in final ingredients
        checks[key] = {
            "passed": found,
            "detail": f"Checking substitution for '{sub}' was performed"
        }

    # 7. Check output structure
    required_fields = ["title", "ingredients", "method"]
    for field in required_fields:
        checks[f"has_{field}"] = {
            "passed": field in response and response[field],
            "detail": f"Response has non-empty '{field}' field"
        }

    # Calculate overall
    total_checks = len(checks)
    passed_checks = sum(1 for c in checks.values() if c["passed"])
    score = passed_checks / total_checks if total_checks > 0 else 0.0
    overall_passed = all(c["passed"] for c in checks.values())

    return {
        "passed": overall_passed,
        "checks": checks,
        "score": round(score, 3),
    }
