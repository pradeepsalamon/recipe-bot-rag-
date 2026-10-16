"""The allergen and food-safety rules. These are the evals' ground truth."""
import pytest

from pantry import corpus, safety


@pytest.mark.parametrize("words, codes", [
    (["nuts"], ["PEANUT", "TREE_NUT"]),
    (["my son's nut allergy"], ["PEANUT", "TREE_NUT"]),
    (["peanut"], ["PEANUT"]),
    (["tree nuts"], ["TREE_NUT"]),
    (["cashews"], ["TREE_NUT"]),
    (["Dairy", "egg"], ["DAIRY", "EGG"]),
    (["coeliac"], ["GLUTEN"]),
    (["TREE_NUT"], ["TREE_NUT"]),
    (["shellfish"], ["SHELLFISH"]),
])
def test_normalise(words, codes):
    assert safety.normalise_allergies(words)[0] == codes


def test_unknown_allergen_is_reported_not_dropped():
    codes, unknown = safety.normalise_allergies(["kiwi", "nuts"])
    assert unknown == ["kiwi"] and codes == ["PEANUT", "TREE_NUT"]


def test_shortbread_versions_differ():
    nuts = safety.normalise_allergies(["nuts"])[0]
    old = safety.check_declaration(corpus.get("shortbread", "original"), nuts)
    new = safety.check_declaration(corpus.get("shortbread", "reformulated-2025"), nuts)
    assert (old["verdict"], old["status"]) == ("SAFE", "superseded")
    assert old["superseded_by"] == "shortbread@reformulated-2025"
    assert new["verdict"] == "UNSAFE"
    assert new["contains_user_allergens"] == ["TREE_NUT"]
    assert new["may_contain_user_allergens"] == ["PEANUT"]


def test_may_contain_is_its_own_verdict():
    r = corpus.get("choc_chip_cookies", "reformulated-2025")
    assert safety.check_declaration(r, ["PEANUT"])["verdict"] == "MAY_CONTAIN"


def test_unsafe_beats_may_contain():
    r = corpus.get("shortbread", "reformulated-2025")
    assert safety.check_declaration(r, ["TREE_NUT", "PEANUT"])["verdict"] == "UNSAFE"


def test_declaration_not_prose_worcestershire_is_fish():
    # nothing in the burger's title or method says "fish"; the declaration does
    assert safety.check_declaration(corpus.get("beef_burgers", "original"), ["FISH"])["verdict"] == "UNSAFE"


def test_own_swap_can_reintroduce_allergen():
    r = corpus.get("ven_pongal", "original")
    nuts = safety.normalise_allergies(["nuts"])[0]
    assert safety.check_substituted(r, [{"from": "cashews", "to": "roasted peanuts"}], nuts)["verdict"] == "UNSAFE"
    assert safety.check_substituted(r, [{"from": "cashews", "to": "roasted sunflower seeds"}], nuts)["verdict"] == "SAFE"


def test_swap_removes_allergen_only_if_no_other_ingredient_has_it():
    r = corpus.get("banana_bread", "reformulated-2025")
    out = safety.check_substituted(r, [{"from": "plain flour", "to": "rice flour"}], ["GLUTEN", "SOY"])
    assert out["verdict"] == "SAFE"           # flour was the only GLUTEN and the only SOY trace
    out = safety.check_substituted(r, [{"from": "plain flour", "to": "almond flour"}], ["TREE_NUT"])
    assert out["verdict"] == "UNSAFE"


def test_unknown_substitute_is_unknown_not_safe():
    r = corpus.get("banana_bread", "reformulated-2025")
    out = safety.check_substituted(r, [{"from": "plain flour", "to": "magic flour"}], ["GLUTEN"])
    assert out["verdict"] == "UNKNOWN"


def test_vague_substitute_name_keeps_its_own_allergen():
    d = safety.lookup_substitute("milk")
    assert "DAIRY" in d["allergens"]


def test_find_substitutions_lists_each_option_allergens():
    res = safety.find_substitutions("plain flour", "gluten")
    names = {o["substitute"]: o["allergens"] for o in res["options"]}
    assert names["almond flour"] == ["TREE_NUT"] and names["rice flour"] == []


@pytest.mark.parametrize("food, temp", [("chicken thighs", 74), ("whole chicken", 74), ("minced beef", 71),
                                        ("salmon", 63), ("pork chop", 63), ("leftover curry", 74)])
def test_safe_temperatures(food, temp):
    assert safety.safe_temperature(food)["safe_internal_c"] == temp


def test_unknown_food_has_no_temperature():
    assert safety.safe_temperature("tofu")["found"] is False


def test_integrity_report_finds_only_the_known_rasam_conflict():
    rows = safety.integrity_report()
    assert [r["recipe"] for r in rows] == ["rasam@original"]
    assert rows[0]["in_ingredients_not_declared"] == ["DAIRY"]
