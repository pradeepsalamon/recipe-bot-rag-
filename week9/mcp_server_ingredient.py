from mcp.server.mcpserver import MCPServer
import json

mcp = MCPServer("ingredient-db")

@mcp.tool()
def lookup_ingredient_nutrition(ingredient_name: str) -> str:
    """
    Lookup an ingredient by name to get its allergen flags and per-100g nutrition.
    """
    db = {
        "milk": {"allergens": ["DAIRY"], "nutrition_per_100g": {"calories": 42, "protein": 3.4, "fat": 1.0}},
        "peanuts": {"allergens": ["PEANUT"], "nutrition_per_100g": {"calories": 567, "protein": 25.8, "fat": 49.2}},
        "wheat flour": {"allergens": ["GLUTEN"], "nutrition_per_100g": {"calories": 339, "protein": 13.7, "fat": 1.9}},
        "ghee": {"allergens": ["DAIRY"], "nutrition_per_100g": {"calories": 900, "protein": 0, "fat": 100}}
    }
    name = ingredient_name.lower().strip()
    if name in db:
        return json.dumps(db[name])
    return json.dumps({"error": f"Ingredient '{ingredient_name}' not found in database."})

if __name__ == "__main__":
    mcp.run()
