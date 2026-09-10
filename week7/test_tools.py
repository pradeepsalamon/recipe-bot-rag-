"""
Week 7 Task Set B — Unit Tests for Tools, Evaluator, and Workflow
"""

import os, sys, json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_search_recipe():
    """Test search_recipe tool."""
    from tools import search_recipe

    print("test_search_recipe...")

    # Exact match
    r = search_recipe("Idli")
    assert r["found"], f"Idli not found: {r}"
    assert r["recipe_id"] == "idli"
    assert len(r["ingredients"]) > 0
    print(f"  ✓ Exact match: {r['title']}")

    # Case-insensitive
    r = search_recipe("ven pongal")
    assert r["found"], f"Ven Pongal not found: {r}"
    assert r["recipe_id"] == "ven_pongal"
    print(f"  ✓ Case-insensitive: {r['title']}")

    # RAG search for non-existent recipe returns nearest neighbor (expected)
    r = search_recipe("pizza")
    # Vector search always returns something; verify it's not actually pizza
    if r.get("found"):
        assert "pizza" not in r.get("recipe_id", "").lower(), "Should not find 'pizza' recipe"
        print(f"  [ok] 'pizza' query returned nearest match: {r.get('recipe_id', r.get('title', 'unknown'))}")
    else:
        print(f"  [ok] 'pizza' query: not found (as expected)")

    print("  PASSED\n")


def test_scale_recipe():
    """Test scale_recipe tool."""
    from tools import scale_recipe

    print("test_scale_recipe...")

    # Scale Rasam from 4 to 8 servings
    r = scale_recipe("rasam", 4, 8)
    assert "error" not in r, f"Error scaling: {r}"
    assert r["scale_factor"] == 2.0
    assert r["target_servings"] == 8
    print(f"  ✓ Scale 4->8: factor={r['scale_factor']}")

    # Check amounts are doubled
    for ing in r["scaled_ingredients"]:
        if ing["original_amount"] and ing["original_amount"][0].isdigit():
            orig = float(ing["original_amount"].split()[0])
            scaled = float(ing["scaled_amount"].split()[0])
            assert abs(scaled - orig * 2) < 0.1, f"Scaling error: {ing}"
    print(f"  ✓ Amounts correctly doubled")

    # Invalid recipe
    r = scale_recipe("nonexistent", 4, 8)
    assert "error" in r
    print(f"  ✓ Invalid recipe handled")

    # Invalid servings
    r = scale_recipe("rasam", 0, 8)
    assert "error" in r
    print(f"  ✓ Zero servings handled")

    print("  PASSED\n")


def test_substitute_ingredient():
    """Test substitute_ingredient tool."""
    from tools import substitute_ingredient

    print("test_substitute_ingredient...")

    # Ghee -> dairy-free
    r = substitute_ingredient("ghee", "ALLERGEN", allergen="DAIRY")
    assert r["substitute"] == "coconut oil", f"Expected coconut oil, got {r}"
    assert not r["needs_further_check"]
    print(f"  ✓ Ghee DAIRY: {r['substitute']}")

    # Cashew -> tree nut-free
    r = substitute_ingredient("cashews", "ALLERGEN", allergen="TREE_NUT")
    assert "sunflower" in r["substitute"].lower()
    print(f"  ✓ Cashews TREE_NUT: {r['substitute']}")

    # Ghee -> vegan
    r = substitute_ingredient("ghee", "DIET", diet="VEGAN")
    assert r["substitute"] == "coconut oil"
    print(f"  ✓ Ghee VEGAN: {r['substitute']}")

    # Asafoetida -> gluten-free
    r = substitute_ingredient("asafoetida", "ALLERGEN", allergen="GLUTEN")
    assert "gluten-free" in r["substitute"].lower()
    print(f"  ✓ Asafoetida GLUTEN: {r['substitute']}")

    # No substitution needed
    r = substitute_ingredient("salt", "ALLERGEN", allergen="DAIRY")
    assert r["needs_further_check"] or r["substitute"] is None
    print(f"  ✓ Salt DAIRY: no sub needed")

    # Invalid allergen
    r = substitute_ingredient("ghee", "ALLERGEN", allergen="INVALID")
    assert "error" in r
    print(f"  ✓ Invalid allergen handled")

    # Missing allergen param
    r = substitute_ingredient("ghee", "ALLERGEN")
    assert "error" in r
    print(f"  ✓ Missing param handled")

    print("  PASSED\n")


def test_dispatch_tool():
    """Test tool dispatcher."""
    from tools import dispatch_tool

    print("test_dispatch_tool...")

    r = dispatch_tool("search_recipe", {"query": "Sambar"})
    assert r["found"]
    print(f"  ✓ Dispatch search_recipe")

    r = dispatch_tool("unknown_tool", {})
    assert "error" in r
    print(f"  ✓ Unknown tool handled")

    print("  PASSED\n")


def test_evaluator():
    """Test the evaluator."""
    from evaluator import evaluate_response

    print("test_evaluator...")

    # Perfect response
    response = {
        "title": "Idli",
        "servings": "Serves 24",
        "ingredients": ["800g Idli rice", "200g Urad dal"],
        "method": ["Soak rice", "Grind", "Ferment for 8 hours"],
        "allergen_warning": "None",
        "substitutions_made": [],
    }
    expected = {
        "recipe_id": "idli",
        "must_contain_ingredients": ["idli rice", "urad dal"],
        "must_contain_method_keywords": ["soak", "grind", "ferment"],
        "target_servings": None,
        "prohibited_allergens": [],
        "required_substitutions": [],
    }
    result = evaluate_response(response, expected)
    assert result["passed"], f"Should pass: {result}"
    print(f"  ✓ Perfect response: passed={result['passed']}, score={result['score']}")

    # Missing ingredient
    response2 = {
        "title": "Idli",
        "ingredients": ["800g rice"],
        "method": ["Cook"],
    }
    result2 = evaluate_response(response2, expected)
    print(f"  ✓ Missing data: passed={result2['passed']}, score={result2['score']}")

    # None response
    result3 = evaluate_response(None, expected)
    assert not result3["passed"]
    print(f"  ✓ None response: passed={result3['passed']}")

    print("  PASSED\n")


def test_tool_schemas():
    """Verify tool schemas are well-formed."""
    from tools import TOOL_SCHEMAS

    print("test_tool_schemas...")

    assert len(TOOL_SCHEMAS) == 3
    names = [t["name"] for t in TOOL_SCHEMAS]
    assert "search_recipe" in names
    assert "scale_recipe" in names
    assert "substitute_ingredient" in names

    # Check substitute_ingredient has enum params
    sub_schema = next(t for t in TOOL_SCHEMAS if t["name"] == "substitute_ingredient")
    props = sub_schema["parameters"]["properties"]
    assert "enum" in props["reason_type"]
    assert "enum" in props["allergen"]
    assert "enum" in props["diet"]
    print(f"  ✓ All 3 tool schemas present with correct enums")

    print("  PASSED\n")


def run_all_tests():
    """Run all unit tests."""
    print("=" * 60)
    print("RUNNING UNIT TESTS")
    print("=" * 60 + "\n")

    tests = [
        test_search_recipe,
        test_scale_recipe,
        test_substitute_ingredient,
        test_dispatch_tool,
        test_evaluator,
        test_tool_schemas,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ✗ FAILED: {e}\n")
            failed += 1

    print(f"{'='*60}")
    print(f"UNIT TESTS: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
