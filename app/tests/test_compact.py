"""The model-facing view of tool results: smaller, but never missing a safety field."""
import json

import pytest

from pantry import compact, corpus, matching, retriever, safety, scaling


@pytest.fixture(scope="module")
def samples():
    return {
        "search_recipes": retriever.search("nut-free shortbread"),
        "get_recipe": dict(corpus.get("shortbread", "original"), citation="shortbread@original"),
        "check_allergens": safety.check_declaration(corpus.get("shortbread", "original"), ["TREE_NUT"]),
        "find_substitution": safety.find_substitutions("plain flour", "GLUTEN"),
        "scale_recipe": scaling.scale(corpus.get("roast_chicken", "original"), 8),
        "match_pantry": matching.match(["rice", "lemons", "curry leaves"]),
        "safe_temperature": safety.safe_temperature("chicken"),
    }


def test_overall_reduction_at_least_30_percent(samples):
    before = sum(len(json.dumps(v, ensure_ascii=False)) for v in samples.values())
    after = sum(len(compact.dumps(compact.for_model(k, v))) for k, v in samples.items())
    assert after <= 0.7 * before, (before, after)


def test_version_status_survives_everywhere(samples):
    s = compact.for_model("search_recipes", samples["search_recipes"])
    old = next(h for h in s["results"] if h["recipe"] == "shortbread@original")
    assert old["status"] == "superseded" and old["superseded_by"] == "shortbread@reformulated-2025"
    r = compact.for_model("get_recipe", samples["get_recipe"])
    assert r["status"] == "superseded" and r["superseded_by"] == "shortbread@reformulated-2025"
    c = compact.for_model("check_allergens", samples["check_allergens"])
    assert c["status"] == "superseded" and c["superseded_by"] and c["verdict"] == "SAFE"


def test_substitute_allergens_survive(samples):
    s = compact.for_model("find_substitution", samples["find_substitution"])
    opts = {o["substitute"]: o["allergens"] for o in s["options"]}
    assert opts["almond flour"] == ["TREE_NUT"] and opts["rice flour"] == "none"


def test_scaling_rules_survive(samples):
    s = compact.for_model("scale_recipe", samples["scale_recipe"])
    assert "never multiply" in s["time_rule"] and "74°C" in s["doneness_rule"]
    assert s["times_minutes_UNCHANGED"]["cook_minutes"] == 80


def test_errors_and_unknown_tools_pass_through():
    assert compact.for_model("get_recipe", {"error": "x"}) == {"error": "x"}
    assert compact.for_model("new_tool", {"a": 1}) == {"a": 1}
    assert compact.for_model("check_allergens", {"weird": "shape"}) == {"weird": "shape"}
