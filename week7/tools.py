"""
Week 7 Task Set B — Recipe Agent Tools

Three tools with sharply defined single responsibilities:
1. search_recipe: Find a recipe by name or description from the vector DB.
2. scale_recipe:  Scale a recipe's ingredient quantities to a target serving count.
3. substitute_ingredient: Given an ingredient + dietary/allergen constraint, return an appropriate substitute.
"""

import os, sys, json, re

# Ensure root project is on the path so we can import rag_pipeline / ingest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional
from ingest import parse_recipes_from_docx
from rag_pipeline import search as rag_search

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AllergenType(str, Enum):
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    DAIRY = "DAIRY"
    EGG = "EGG"
    GLUTEN = "GLUTEN"
    SOY = "SOY"
    SESAME = "SESAME"

class DietType(str, Enum):
    NONE = "NONE"
    VEGAN = "VEGAN"
    VEGETARIAN = "VEGETARIAN"
    GLUTEN_FREE = "GLUTEN_FREE"
    DAIRY_FREE = "DAIRY_FREE"
    NUT_FREE = "NUT_FREE"

# ---------------------------------------------------------------------------
# Substitution Knowledge Base  (deterministic — no LLM needed)
# ---------------------------------------------------------------------------

SUBSTITUTION_DB = {
    # (ingredient_pattern, constraint) -> substitute
    # Dairy-related
    ("ghee", AllergenType.DAIRY): {"substitute": "coconut oil", "note": "Use equal amount of coconut oil for a vegan/dairy-free alternative."},
    ("ghee", DietType.VEGAN): {"substitute": "coconut oil", "note": "Use equal amount of coconut oil for a vegan alternative."},
    ("ghee", DietType.DAIRY_FREE): {"substitute": "coconut oil", "note": "Use equal amount of coconut oil for a dairy-free alternative."},
    ("butter", AllergenType.DAIRY): {"substitute": "coconut oil", "note": "Use equal amount of coconut oil."},
    ("butter", DietType.VEGAN): {"substitute": "coconut oil", "note": "Use equal amount of coconut oil."},
    ("butter", DietType.DAIRY_FREE): {"substitute": "coconut oil", "note": "Use equal amount of coconut oil."},
    ("milk", AllergenType.DAIRY): {"substitute": "coconut milk", "note": "Use coconut milk as a 1:1 replacement."},
    ("milk", DietType.VEGAN): {"substitute": "coconut milk", "note": "Use coconut milk as a 1:1 replacement."},
    ("milk", DietType.DAIRY_FREE): {"substitute": "coconut milk", "note": "Use coconut milk as a 1:1 replacement."},
    ("cream", AllergenType.DAIRY): {"substitute": "coconut cream", "note": "Use coconut cream as a 1:1 replacement."},
    ("cream", DietType.VEGAN): {"substitute": "coconut cream", "note": "Use coconut cream as a 1:1 replacement."},
    ("yogurt", AllergenType.DAIRY): {"substitute": "coconut yogurt", "note": "Use coconut yogurt as a 1:1 replacement."},
    ("yogurt", DietType.VEGAN): {"substitute": "coconut yogurt", "note": "Use coconut yogurt as a 1:1 replacement."},
    ("curd", AllergenType.DAIRY): {"substitute": "coconut yogurt", "note": "Use coconut yogurt as a 1:1 replacement."},
    ("curd", DietType.VEGAN): {"substitute": "coconut yogurt", "note": "Use coconut yogurt as a 1:1 replacement."},

    # Tree-nut related
    ("cashew", AllergenType.TREE_NUT): {"substitute": "roasted sunflower seeds", "note": "Use sunflower seeds for similar crunch without tree nuts."},
    ("cashew", DietType.NUT_FREE): {"substitute": "roasted sunflower seeds", "note": "Use sunflower seeds for similar crunch, nut-free."},
    ("cashew", AllergenType.PEANUT): {"substitute": "cashew", "note": "Cashews are tree nuts, not peanuts. No substitution needed for peanut allergy."},
    ("almond", AllergenType.TREE_NUT): {"substitute": "pumpkin seeds", "note": "Use pumpkin seeds as a nut-free alternative."},
    ("almond", DietType.NUT_FREE): {"substitute": "pumpkin seeds", "note": "Use pumpkin seeds as a nut-free alternative."},

    # Gluten-related
    ("wheat flour", AllergenType.GLUTEN): {"substitute": "rice flour", "note": "Use rice flour as a gluten-free alternative."},
    ("wheat flour", DietType.GLUTEN_FREE): {"substitute": "rice flour", "note": "Use rice flour as a gluten-free alternative."},
    ("flour", AllergenType.GLUTEN): {"substitute": "rice flour", "note": "Use rice flour as a gluten-free alternative."},
    ("flour", DietType.GLUTEN_FREE): {"substitute": "rice flour", "note": "Use rice flour as a gluten-free alternative."},
    ("asafoetida", AllergenType.GLUTEN): {"substitute": "gluten-free asafoetida", "note": "Use asafoetida certified gluten-free (some brands use wheat filler)."},
    ("asafoetida", DietType.GLUTEN_FREE): {"substitute": "gluten-free asafoetida", "note": "Use asafoetida certified gluten-free (some brands use wheat filler)."},

    # Egg-related
    ("egg", AllergenType.EGG): {"substitute": "flax egg (1 tbsp ground flax + 3 tbsp water per egg)", "note": "Let flax mixture sit 5 minutes before using."},
    ("egg", DietType.VEGAN): {"substitute": "flax egg (1 tbsp ground flax + 3 tbsp water per egg)", "note": "Let flax mixture sit 5 minutes before using."},

    # Peanut-related
    ("peanut", AllergenType.PEANUT): {"substitute": "roasted sunflower seeds", "note": "Sunflower seeds provide similar crunch, peanut-free."},
    ("peanut oil", AllergenType.PEANUT): {"substitute": "sunflower oil", "note": "Use sunflower oil as a peanut-free cooking oil."},
    ("groundnut", AllergenType.PEANUT): {"substitute": "sunflower seeds", "note": "Use sunflower seeds as a peanut-free alternative."},

    # Soy-related
    ("soy sauce", AllergenType.SOY): {"substitute": "coconut aminos", "note": "Use coconut aminos for a soy-free umami flavor."},

    # Oil fallback for vegan
    ("oil", DietType.VEGAN): {"substitute": "oil", "note": "Most cooking oils are already vegan. No substitution needed."},

    # Sesame
    ("sesame", AllergenType.SESAME): {"substitute": "poppy seeds", "note": "Use poppy seeds as a sesame-free alternative."},
}

# ---------------------------------------------------------------------------
# In-memory recipe cache (parsed from docx)
# ---------------------------------------------------------------------------

_RECIPE_CACHE = None

def _get_recipes():
    global _RECIPE_CACHE
    if _RECIPE_CACHE is None:
        docx_path = os.path.join(os.path.dirname(__file__), "..", "TamilNadu_Recipe_Cards.docx")
        _RECIPE_CACHE = parse_recipes_from_docx(docx_path)
    return _RECIPE_CACHE


# ===========================================================================
# TOOL 1 — search_recipe
# ===========================================================================

def search_recipe(query: str) -> dict:
    """
    Search for a recipe by name, description, or ingredient query.
    Returns the SINGLE best-matching recipe with its full details
    (title, ingredients, method, dietary info, allergens, yield).

    Use this tool when the user asks for a specific recipe or when you need
    to retrieve recipe details before scaling or substituting ingredients.
    Do NOT use this for scaling or substitution — use the dedicated tools instead.
    """
    # First try exact match from parsed recipes
    recipes = _get_recipes()
    query_lower = query.lower().strip()
    for r in recipes:
        if r["recipe_id"] == query_lower or r["title"].lower() == query_lower:
            return _format_recipe(r)

    # Fuzzy: check if query is a substring of title
    for r in recipes:
        if query_lower in r["title"].lower():
            return _format_recipe(r)

    # Fall back to RAG vector search
    try:
        results = rag_search(query, collection_name="recipes_structure", top_k=3)
        if results:
            best_recipe_id = results[0][0].metadata.get("recipe_id", "")
            for r in recipes:
                if r["recipe_id"] == best_recipe_id:
                    return _format_recipe(r)
            # If we can't match to a parsed recipe, return the chunk text
            return {
                "found": True,
                "recipe_id": best_recipe_id,
                "title": best_recipe_id.replace("_", " ").title(),
                "content": results[0][0].page_content,
                "score": float(results[0][1])
            }
    except Exception:
        pass

    return {"found": False, "error": f"No recipe found matching '{query}'."}


def _format_recipe(r: dict) -> dict:
    """Format a parsed recipe dict into a clean tool result."""
    ingredients = []
    headers = r.get("ingredients_headers", [])
    for row in r.get("ingredients_rows", []):
        ing_dict = {}
        for i, h in enumerate(headers):
            if i < len(row):
                ing_dict[h.lower()] = row[i]
        ingredients.append(ing_dict)

    return {
        "found": True,
        "recipe_id": r["recipe_id"],
        "title": r["title"],
        "description": r.get("description", ""),
        "cuisine": r.get("cuisine", ""),
        "dietary_tags": r.get("dietary_tags", ""),
        "allergens": r.get("allergens", ""),
        "yield": r.get("yield", ""),
        "ingredients": ingredients,
        "method": r.get("method_steps", []),
        "notes": r.get("notes", "").strip(),
    }


# ===========================================================================
# TOOL 2 — scale_recipe
# ===========================================================================

def scale_recipe(recipe_id: str, original_servings: int, target_servings: int) -> dict:
    """
    Scale a recipe's ingredient quantities from original_servings to target_servings.
    Returns the recipe with all ingredient amounts multiplied by (target_servings / original_servings).

    Use this tool ONLY when the user requests a different serving count.
    You must first use search_recipe to obtain the recipe details and original yield.
    Do NOT use this for finding recipes or substituting ingredients.
    """
    if original_servings <= 0 or target_servings <= 0:
        return {"error": "Both original_servings and target_servings must be positive integers."}

    recipes = _get_recipes()
    recipe = None
    for r in recipes:
        if r["recipe_id"] == recipe_id.lower().strip():
            recipe = r
            break

    if not recipe:
        return {"error": f"Recipe '{recipe_id}' not found. Use search_recipe first."}

    scale_factor = target_servings / original_servings

    scaled_ingredients = []
    headers = recipe.get("ingredients_headers", [])
    for row in recipe.get("ingredients_rows", []):
        ing_name = row[0] if len(row) > 0 else ""
        amount_str = row[1] if len(row) > 1 else ""
        ratio = row[2] if len(row) > 2 else ""

        scaled_amount = _scale_amount(amount_str, scale_factor)
        scaled_ingredients.append({
            "ingredient": ing_name,
            "original_amount": amount_str,
            "scaled_amount": scaled_amount,
            "ratio": ratio,
        })

    return {
        "recipe_id": recipe_id,
        "title": recipe["title"],
        "original_servings": original_servings,
        "target_servings": target_servings,
        "scale_factor": round(scale_factor, 2),
        "scaled_ingredients": scaled_ingredients,
        "method": recipe.get("method_steps", []),
        "notes": recipe.get("notes", "").strip(),
    }


def _scale_amount(amount_str: str, factor: float) -> str:
    """Try to scale a numeric amount string by a factor."""
    if not amount_str:
        return amount_str

    # Try to extract a number from the beginning
    match = re.match(r"([\d.]+)\s*(.*)", amount_str.strip())
    if match:
        try:
            num = float(match.group(1))
            unit = match.group(2)
            scaled = round(num * factor, 1)
            # Clean up .0
            if scaled == int(scaled):
                scaled = int(scaled)
            return f"{scaled} {unit}".strip()
        except ValueError:
            pass
    return amount_str  # Return unchanged if we can't parse


# ===========================================================================
# TOOL 3 — substitute_ingredient
# ===========================================================================

def substitute_ingredient(
    ingredient: str,
    reason_type: str,       # "ALLERGEN" or "DIET"
    allergen: str = "",     # AllergenType value, required if reason_type=ALLERGEN
    diet: str = "",         # DietType value, required if reason_type=DIET
) -> dict:
    """
    Given a specific ingredient and a dietary or allergen constraint,
    return an appropriate substitute ingredient.

    Parameters:
        ingredient: The ingredient to substitute (e.g., "ghee", "cashews", "wheat flour").
        reason_type: Either "ALLERGEN" (avoiding an allergen) or "DIET" (following a diet).
        allergen: Required if reason_type is "ALLERGEN". One of:
                  PEANUT, TREE_NUT, DAIRY, EGG, GLUTEN, SOY, SESAME.
        diet: Required if reason_type is "DIET". One of:
              NONE, VEGAN, VEGETARIAN, GLUTEN_FREE, DAIRY_FREE, NUT_FREE.

    Use this tool ONLY to find a replacement for a single ingredient
    that violates a dietary or allergen constraint.
    Do NOT use this to search for recipes or scale quantities.
    """
    ingredient_lower = ingredient.lower().strip()
    reason_type_upper = reason_type.upper().strip()

    if reason_type_upper == "ALLERGEN":
        if not allergen:
            return {"error": "allergen parameter is required when reason_type is ALLERGEN."}
        try:
            constraint = AllergenType(allergen.upper().strip())
        except ValueError:
            return {"error": f"Invalid allergen '{allergen}'. Must be one of: {[e.value for e in AllergenType]}"}
    elif reason_type_upper == "DIET":
        if not diet:
            return {"error": "diet parameter is required when reason_type is DIET."}
        try:
            constraint = DietType(diet.upper().strip())
        except ValueError:
            return {"error": f"Invalid diet '{diet}'. Must be one of: {[e.value for e in DietType]}"}
    else:
        return {"error": "reason_type must be 'ALLERGEN' or 'DIET'."}

    # Look up substitution — try exact match first, then substring match
    result = SUBSTITUTION_DB.get((ingredient_lower, constraint))
    if result:
        return {
            "ingredient": ingredient,
            "constraint_type": reason_type_upper,
            "constraint": constraint.value,
            "substitute": result["substitute"],
            "note": result["note"],
            "needs_further_check": False,
        }

    # Substring match (e.g., "Cashews" matches "cashew")
    for (pattern, c), sub in SUBSTITUTION_DB.items():
        if c == constraint and (pattern in ingredient_lower or ingredient_lower in pattern):
            return {
                "ingredient": ingredient,
                "constraint_type": reason_type_upper,
                "constraint": constraint.value,
                "substitute": sub["substitute"],
                "note": sub["note"],
                "needs_further_check": False,
            }

    # No match — check if the ingredient even violates the constraint
    return {
        "ingredient": ingredient,
        "constraint_type": reason_type_upper,
        "constraint": constraint.value,
        "substitute": None,
        "note": f"No known substitution for '{ingredient}' under constraint {constraint.value}. The ingredient may already be compatible, or manual review is needed.",
        "needs_further_check": True,
    }


# ===========================================================================
# Tool schemas for the LLM (function calling)
# ===========================================================================

TOOL_SCHEMAS = [
    {
        "name": "search_recipe",
        "description": (
            "Search for a recipe by name or description and retrieve its full details "
            "(title, ingredients with amounts, method steps, dietary tags, allergens, yield). "
            "Use this as the FIRST step when you need recipe information. "
            "Do NOT use this tool for scaling or ingredient substitution."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Recipe name or search query (e.g., 'Ven Pongal', 'sambar', 'dosa')."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "scale_recipe",
        "description": (
            "Scale a recipe's ingredient quantities to a different serving count. "
            "Requires the recipe_id (from search_recipe), original serving count, and target serving count. "
            "Returns all ingredients with both original and scaled amounts. "
            "Do NOT use this for finding recipes or substituting ingredients."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "recipe_id": {
                    "type": "string",
                    "description": "The recipe ID returned by search_recipe (e.g., 'ven_pongal', 'sambar')."
                },
                "original_servings": {
                    "type": "integer",
                    "description": "The original serving count from the recipe's yield."
                },
                "target_servings": {
                    "type": "integer",
                    "description": "The desired serving count."
                }
            },
            "required": ["recipe_id", "original_servings", "target_servings"]
        }
    },
    {
        "name": "substitute_ingredient",
        "description": (
            "Find a substitute for a specific ingredient that violates a dietary restriction or "
            "allergen constraint. Returns one substitute ingredient with usage notes. "
            "Use this when an ingredient in a recipe is incompatible with the user's dietary needs "
            "or allergies. Call once per ingredient that needs substitution. "
            "Do NOT use this for recipe search or scaling."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ingredient": {
                    "type": "string",
                    "description": "The ingredient to replace (e.g., 'ghee', 'cashews', 'wheat flour')."
                },
                "reason_type": {
                    "type": "string",
                    "enum": ["ALLERGEN", "DIET"],
                    "description": "Whether the constraint is an allergen avoidance or a dietary preference."
                },
                "allergen": {
                    "type": "string",
                    "enum": ["PEANUT", "TREE_NUT", "DAIRY", "EGG", "GLUTEN", "SOY", "SESAME"],
                    "description": "Required if reason_type is 'ALLERGEN'. The specific allergen to avoid."
                },
                "diet": {
                    "type": "string",
                    "enum": ["NONE", "VEGAN", "VEGETARIAN", "GLUTEN_FREE", "DAIRY_FREE", "NUT_FREE"],
                    "description": "Required if reason_type is 'DIET'. The specific diet to follow."
                }
            },
            "required": ["ingredient", "reason_type"]
        }
    }
]


# ===========================================================================
# Tool dispatcher (maps name → function)
# ===========================================================================

TOOL_FUNCTIONS = {
    "search_recipe": search_recipe,
    "scale_recipe": scale_recipe,
    "substitute_ingredient": substitute_ingredient,
}

def dispatch_tool(name: str, arguments: dict) -> dict:
    """Execute a tool by name with the given arguments. Returns the tool result as a dict."""
    fn = TOOL_FUNCTIONS.get(name)
    if not fn:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(**arguments)
    except Exception as e:
        return {"error": f"Tool '{name}' failed: {str(e)}"}
