"""
Week 7 Task Set B — Fixed Workflow

A predetermined sequence with NO agent loop, NO dynamic tool selection.
Uses the SAME tools, model, recipe data, and output contract as the agent.

Sequence:
1. search_recipe(query)
2. scale_recipe(recipe_id, original, target) — if scaling requested
3. substitute_ingredient(ingredient, constraint) — for each problematic ingredient
4. generate_final_response(all_data) — single LLM call to assemble the final output
"""

import os, sys, json, time, re, uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(override=True)

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage

from tools import (
    search_recipe, scale_recipe, substitute_ingredient,
    AllergenType, DietType,
)
from agent import COST_PER_1M_INPUT, COST_PER_1M_OUTPUT, estimate_cost

# ---------------------------------------------------------------------------
# Parse user request to extract parameters deterministically
# ---------------------------------------------------------------------------

def _parse_request(user_request: str) -> dict:
    """
    Use a single LLM call to parse the user's natural-language request
    into structured parameters for the workflow.
    Returns dict with: recipe_query, target_servings, dietary_constraints, allergen_constraints
    """
    llm = ChatGoogleGenerativeAI(model="gemini-3.6-flash", temperature=0)

    parse_prompt = """Extract the following from the user's recipe request. Return ONLY a JSON object.

{
  "recipe_query": "<recipe name or search term>",
  "target_servings": <integer or null if not specified>,
  "dietary_constraints": ["<DIET enum values>"],
  "allergen_constraints": ["<ALLERGEN enum values>"]
}

Diet enum values: NONE, VEGAN, VEGETARIAN, GLUTEN_FREE, DAIRY_FREE, NUT_FREE
Allergen enum values: PEANUT, TREE_NUT, DAIRY, EGG, GLUTEN, SOY, SESAME

Rules:
- If "dairy-free" is mentioned, add DAIRY_FREE to dietary_constraints AND DAIRY to allergen_constraints.
- If "vegan" is mentioned, add VEGAN to dietary_constraints AND DAIRY and EGG to allergen_constraints.
- If "gluten-free" is mentioned, add GLUTEN_FREE to dietary_constraints AND GLUTEN to allergen_constraints.
- If "nut-free" is mentioned, add NUT_FREE to dietary_constraints AND TREE_NUT and PEANUT to allergen_constraints.
- If no dietary/allergen constraints, use empty arrays.
- If no target servings, use null.

User request: """

    response = llm.invoke([HumanMessage(content=parse_prompt + user_request)])
    content = response.content
    if isinstance(content, list) and len(content) > 0:
        if isinstance(content[0], dict) and "text" in content[0]:
            content = content[0]["text"]
        else:
            content = str(content)

    # Token accounting
    usage = getattr(response, "usage_metadata", None) or {}
    if isinstance(usage, dict):
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
    else:
        input_tokens = getattr(usage, "input_tokens", 0)
        output_tokens = getattr(usage, "output_tokens", 0)

    # Parse JSON from response
    json_text = content
    if "```json" in json_text:
        start = json_text.index("```json") + 7
        end = json_text.find("```", start)
        json_text = json_text[start:end] if end > 0 else json_text[start:]
    brace_start = json_text.find("{")
    brace_end = json_text.rfind("}") + 1
    if brace_start >= 0 and brace_end > brace_start:
        parsed = json.loads(json_text[brace_start:brace_end])
    else:
        parsed = {"recipe_query": user_request, "target_servings": None, "dietary_constraints": [], "allergen_constraints": []}

    return parsed, input_tokens, output_tokens


def _parse_servings_from_yield(yield_str: str) -> int:
    """Extract number from yield string like '4 servings' or '~24 idlis'."""
    match = re.search(r"(\d+)", yield_str)
    return int(match.group(1)) if match else 4


# Ingredient-to-allergen mapping for identifying problematic ingredients
INGREDIENT_ALLERGEN_MAP = {
    "ghee": ["DAIRY"],
    "butter": ["DAIRY"],
    "milk": ["DAIRY"],
    "cream": ["DAIRY"],
    "yogurt": ["DAIRY"],
    "curd": ["DAIRY"],
    "cheese": ["DAIRY"],
    "paneer": ["DAIRY"],
    "cashew": ["TREE_NUT"],
    "almond": ["TREE_NUT"],
    "walnut": ["TREE_NUT"],
    "pistachio": ["TREE_NUT"],
    "peanut": ["PEANUT"],
    "groundnut": ["PEANUT"],
    "egg": ["EGG"],
    "wheat": ["GLUTEN"],
    "flour": ["GLUTEN"],
    "asafoetida": ["GLUTEN"],  # some brands contain wheat
    "soy": ["SOY"],
    "sesame": ["SESAME"],
}

DIET_TO_ALLERGENS = {
    "VEGAN": ["DAIRY", "EGG"],
    "DAIRY_FREE": ["DAIRY"],
    "GLUTEN_FREE": ["GLUTEN"],
    "NUT_FREE": ["TREE_NUT", "PEANUT"],
    "VEGETARIAN": [],
}


def _identify_problematic_ingredients(ingredients: list, dietary_constraints: list, allergen_constraints: list) -> list:
    """
    Given recipe ingredients and constraints, identify which ingredients
    need substitution and why.
    Returns list of (ingredient_name, reason_type, constraint_value).
    """
    problems = []

    # Build the full set of allergens to avoid
    allergens_to_avoid = set(allergen_constraints)
    for diet in dietary_constraints:
        allergens_to_avoid.update(DIET_TO_ALLERGENS.get(diet, []))

    for ing in ingredients:
        # Get ingredient name (might be a dict or string)
        if isinstance(ing, dict):
            ing_name = ing.get("ingredient", "") or ing.get("name", "")
        else:
            ing_name = str(ing)

        ing_lower = ing_name.lower()

        for pattern, allergen_list in INGREDIENT_ALLERGEN_MAP.items():
            if pattern in ing_lower:
                for allergen in allergen_list:
                    if allergen in allergens_to_avoid:
                        problems.append((ing_name, "ALLERGEN", allergen))

    return problems


def run_workflow(
    user_request: str,
    request_id: str = None,
    temperature: float = 0,
    log_callback=None,
):
    """
    Run the fixed workflow.
    Returns same structure as agent: {response, steps, metrics, terminated_by}
    """
    if request_id is None:
        request_id = str(uuid.uuid4())[:8]

    steps = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    start_time = time.time()

    def _log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    _log(f"\n[WORKFLOW START] request_id={request_id}")
    _log(f"  request: {user_request}")

    # -----------------------------------------------------------------------
    # Step 0: Parse the request (LLM call)
    # -----------------------------------------------------------------------
    _log(f"\n[STEP 1] action=parse_request")
    parsed, parse_in, parse_out = _parse_request(user_request)
    parse_cost = estimate_cost(parse_in, parse_out)
    total_input_tokens += parse_in
    total_output_tokens += parse_out
    total_cost += parse_cost
    _log(f"  parsed: {json.dumps(parsed, default=str)}")
    _log(f"  tokens: input={parse_in}, output={parse_out}, cost=${parse_cost:.6f}")
    steps.append({"step": 1, "action": "parse_request", "input": user_request, "result": parsed,
                   "input_tokens": parse_in, "output_tokens": parse_out, "cost": parse_cost})

    # -----------------------------------------------------------------------
    # Step 1: Search recipe
    # -----------------------------------------------------------------------
    _log(f"\n[STEP 2] action=search_recipe")
    recipe_query = parsed.get("recipe_query", user_request)
    recipe_result = search_recipe(recipe_query)
    _log(f"  query: {recipe_query}")
    _log(f"  found: {recipe_result.get('found', False)}")
    if recipe_result.get("found"):
        _log(f"  recipe: {recipe_result.get('title')} ({recipe_result.get('recipe_id')})")
    steps.append({"step": 2, "action": "search_recipe", "input": {"query": recipe_query}, "result": recipe_result,
                   "input_tokens": 0, "output_tokens": 0, "cost": 0})

    if not recipe_result.get("found"):
        elapsed_ms = (time.time() - start_time) * 1000
        _log(f"\n[WORKFLOW END] recipe not found")
        return {
            "request_id": request_id,
            "response": {"error": f"Recipe not found: {recipe_query}"},
            "steps": steps,
            "metrics": {"iterations": len(steps), "total_input_tokens": total_input_tokens,
                        "total_output_tokens": total_output_tokens,
                        "total_tokens": total_input_tokens + total_output_tokens,
                        "cost": round(total_cost, 6), "latency_ms": round(elapsed_ms, 1)},
            "terminated_by": None,
        }

    # -----------------------------------------------------------------------
    # Step 2: Scale recipe (if target_servings specified)
    # -----------------------------------------------------------------------
    target_servings = parsed.get("target_servings")
    scale_result = None
    if target_servings:
        _log(f"\n[STEP 3] action=scale_recipe")
        recipe_id = recipe_result["recipe_id"]
        original_servings = _parse_servings_from_yield(recipe_result.get("yield", "4 servings"))
        scale_result = scale_recipe(recipe_id, original_servings, target_servings)
        _log(f"  recipe_id: {recipe_id}, original: {original_servings}, target: {target_servings}")
        _log(f"  scale_factor: {scale_result.get('scale_factor')}")
        steps.append({"step": len(steps) + 1, "action": "scale_recipe",
                       "input": {"recipe_id": recipe_id, "original_servings": original_servings, "target_servings": target_servings},
                       "result": scale_result, "input_tokens": 0, "output_tokens": 0, "cost": 0})

    # -----------------------------------------------------------------------
    # Step 3: Substitute ingredients (if dietary/allergen constraints)
    # -----------------------------------------------------------------------
    dietary_constraints = parsed.get("dietary_constraints", [])
    allergen_constraints = parsed.get("allergen_constraints", [])
    substitutions = []

    if dietary_constraints or allergen_constraints:
        # Get ingredient list
        ingredients = recipe_result.get("ingredients", [])
        if scale_result and scale_result.get("scaled_ingredients"):
            ingredients = scale_result["scaled_ingredients"]

        problems = _identify_problematic_ingredients(ingredients, dietary_constraints, allergen_constraints)

        # Deduplicate — same ingredient may appear with multiple constraints, handle each once
        seen = set()
        for ing_name, reason_type, constraint in problems:
            # Normalize the ingredient name for dedup
            ing_key = re.sub(r'[^a-z]', '', ing_name.lower())
            if ing_key in seen:
                continue
            seen.add(ing_key)

            step_num = len(steps) + 1
            _log(f"\n[STEP {step_num}] action=substitute_ingredient")
            _log(f"  ingredient: {ing_name}, reason: {reason_type}, constraint: {constraint}")

            sub_args = {"ingredient": ing_name, "reason_type": reason_type}
            if reason_type == "ALLERGEN":
                sub_args["allergen"] = constraint
            else:
                sub_args["diet"] = constraint

            sub_result = substitute_ingredient(**sub_args)
            _log(f"  substitute: {sub_result.get('substitute', 'N/A')}")
            substitutions.append(sub_result)

            steps.append({"step": step_num, "action": "substitute_ingredient",
                           "input": sub_args, "result": sub_result,
                           "input_tokens": 0, "output_tokens": 0, "cost": 0})

            # CASCADE CHECK: if the substitute itself is problematic, do another substitution
            if sub_result.get("substitute") and not sub_result.get("needs_further_check"):
                new_sub = sub_result["substitute"].lower()
                for pattern, allergen_list in INGREDIENT_ALLERGEN_MAP.items():
                    if pattern in new_sub:
                        for allergen in allergen_list:
                            if allergen in [c.upper() for c in allergen_constraints] or \
                               any(allergen in DIET_TO_ALLERGENS.get(d, []) for d in dietary_constraints):
                                cascade_step = len(steps) + 1
                                _log(f"\n[STEP {cascade_step}] action=substitute_ingredient (CASCADE)")
                                _log(f"  ingredient: {sub_result['substitute']}, reason: ALLERGEN, constraint: {allergen}")

                                cascade_args = {"ingredient": sub_result["substitute"], "reason_type": "ALLERGEN", "allergen": allergen}
                                cascade_result = substitute_ingredient(**cascade_args)
                                _log(f"  cascade substitute: {cascade_result.get('substitute', 'N/A')}")
                                substitutions.append(cascade_result)

                                steps.append({"step": cascade_step, "action": "substitute_ingredient",
                                               "input": cascade_args, "result": cascade_result,
                                               "input_tokens": 0, "output_tokens": 0, "cost": 0})
                                break

    # -----------------------------------------------------------------------
    # Step 4: Generate final response (LLM call)
    # -----------------------------------------------------------------------
    step_num = len(steps) + 1
    _log(f"\n[STEP {step_num}] action=generate_final_response")

    final_response = _generate_final_response(
        recipe_result, scale_result, substitutions,
        dietary_constraints, allergen_constraints,
        temperature=temperature,
    )

    # Token accounting for final LLM call
    gen_in = final_response.pop("_input_tokens", 0)
    gen_out = final_response.pop("_output_tokens", 0)
    gen_cost = estimate_cost(gen_in, gen_out)
    total_input_tokens += gen_in
    total_output_tokens += gen_out
    total_cost += gen_cost

    steps.append({"step": step_num, "action": "generate_final_response",
                   "input_tokens": gen_in, "output_tokens": gen_out, "cost": gen_cost})

    elapsed_ms = (time.time() - start_time) * 1000

    _log(f"\n[FINAL]")
    _log(f"  title: {final_response.get('title', 'N/A')}")
    _log(f"  servings: {final_response.get('servings', 'N/A')}")
    _log(f"  ingredients: {len(final_response.get('ingredients', []))} items")

    metrics = {
        "iterations": len(steps),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_tokens": total_input_tokens + total_output_tokens,
        "cost": round(total_cost, 6),
        "latency_ms": round(elapsed_ms, 1),
    }

    _log(f"\n[WORKFLOW END] request_id={request_id}")
    _log(f"  iterations={metrics['iterations']}, tokens={metrics['total_tokens']}, cost=${metrics['cost']}, latency={metrics['latency_ms']}ms")

    return {
        "request_id": request_id,
        "response": final_response,
        "steps": steps,
        "metrics": metrics,
        "terminated_by": None,
    }


def _generate_final_response(recipe, scale_result, substitutions, dietary_constraints, allergen_constraints, temperature=0):
    """Single LLM call to assemble the final adapted recipe."""
    llm = ChatGoogleGenerativeAI(model="gemini-3.6-flash", temperature=temperature)

    context = f"Original Recipe:\n{json.dumps(recipe, indent=2, default=str)}\n"
    if scale_result:
        context += f"\nScaled Recipe:\n{json.dumps(scale_result, indent=2, default=str)}\n"
    if substitutions:
        context += f"\nSubstitutions:\n{json.dumps(substitutions, indent=2, default=str)}\n"
    if dietary_constraints:
        context += f"\nDietary Constraints: {dietary_constraints}\n"
    if allergen_constraints:
        context += f"\nAllergen Constraints: {allergen_constraints}\n"

    prompt = f"""{context}

Using the above information, produce the final adapted recipe in this exact JSON format:
```json
{{
  "title": "Recipe Name (adapted if modified)",
  "servings": "Serves N",
  "ingredients": ["amount ingredient", ...],
  "method": ["step 1", "step 2", ...],
  "allergen_warning": "Warning: Contains X" or "None",
  "substitutions_made": ["original -> substitute (reason)", ...],
  "notes": "any relevant notes"
}}
```

Rules:
- Apply all substitutions to the ingredient list and method steps.
- If scaling was applied, use the scaled amounts.
- Update allergen_warning to reflect the FINAL recipe (after substitutions).
- List all substitutions made in substitutions_made.
- Return ONLY the JSON, no other text.
"""

    response = llm.invoke([HumanMessage(content=prompt)])
    content = response.content
    if isinstance(content, list) and len(content) > 0:
        if isinstance(content[0], dict) and "text" in content[0]:
            content = content[0]["text"]
        else:
            content = str(content)

    usage = getattr(response, "usage_metadata", None) or {}
    if isinstance(usage, dict):
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
    else:
        input_tokens = getattr(usage, "input_tokens", 0)
        output_tokens = getattr(usage, "output_tokens", 0)

    # Parse JSON
    json_text = content
    if "```json" in json_text:
        start = json_text.index("```json") + 7
        end = json_text.find("```", start)
        json_text = json_text[start:end] if end > 0 else json_text[start:]

    brace_start = json_text.find("{")
    brace_end = json_text.rfind("}") + 1
    try:
        result = json.loads(json_text[brace_start:brace_end])
    except (json.JSONDecodeError, ValueError):
        result = {"title": "Parse Error", "raw_response": content}

    result["_input_tokens"] = input_tokens
    result["_output_tokens"] = output_tokens
    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = "Find me the Ven Pongal recipe scaled to 8 servings, and make it dairy-free."

    result = run_workflow(query)
    print("\n" + "=" * 60)
    print("FINAL RESULT:")
    print(json.dumps(result["response"], indent=2, default=str))
    print(f"\nMetrics: {result['metrics']}")
