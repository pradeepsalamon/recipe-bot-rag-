from mcp.server.mcpserver import MCPServer
import json
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'week7')))
from tools import search_recipe, scale_recipe, substitute_ingredient

mcp = MCPServer("recipe-server")

@mcp.tool()
def do_search_recipe(query: str) -> str:
    """
    Search for a recipe by name or description. Use this FIRST.
    """
    return json.dumps(search_recipe(query=query))

@mcp.tool()
def do_scale_recipe(recipe_id: str, original_servings: int, target_servings: int) -> str:
    """
    Scale a recipe's ingredients.
    """
    return json.dumps(scale_recipe(recipe_id=recipe_id, original_servings=original_servings, target_servings=target_servings))

@mcp.tool()
def do_substitute_ingredient(ingredient: str, reason_type: str, allergen: str = "", diet: str = "") -> str:
    """
    Replace an ingredient for allergy/diet reasons. If you get a 'No known substitution' error, try providing just the base ingredient name without modifiers (e.g., 'creme fraiche' instead of 'creme fraiche lite').
    """
    res = substitute_ingredient(ingredient=ingredient, reason_type=reason_type, allergen=allergen, diet=diet)
    # Make error recoverable
    if "No known substitution" in res.get("note", ""):
        res["note"] = f"No exact match for '{ingredient}'. Try a simpler term (e.g. 'flour' instead of 'wheat flour') or verify it needs substitution."
    return json.dumps(res)

if __name__ == "__main__":
    mcp.run()
