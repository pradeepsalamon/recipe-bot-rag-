"""Corpus integrity and the scaling calculator."""
from pantry import corpus, scaling


def test_every_superseded_version_points_at_a_current_one():
    for r in corpus.all_recipes():
        if r["status"] == "superseded":
            assert corpus.get_by_key(r["superseded_by"])["status"] == "current", r["recipe_id"]


def test_exactly_one_current_version_per_recipe():
    for rid in {r["recipe_id"] for r in corpus.all_recipes()}:
        assert sum(v["status"] == "current" for v in corpus.versions_of(rid)) == 1, rid


def test_declarations_only_use_known_codes():
    codes = set(corpus.allergen_codes())
    for r in corpus.all_recipes():
        assert set(r["allergens"]) <= codes and set(r["may_contain"]) <= codes, r["recipe_id"]


def test_five_reformulated_pairs():
    pairs = {r["recipe_id"] for r in corpus.all_recipes() if r["version"] == "reformulated-2025"}
    assert pairs == {"shortbread", "choc_chip_cookies", "pesto_pasta", "granola_bars", "banana_bread"}


def test_card_marks_superseded_versions():
    card = corpus.render_card(corpus.get("shortbread", "original"))
    assert "SUPERSEDED by `shortbread@reformulated-2025`" in card


def test_scaling_quantities_but_never_times():
    s = scaling.scale(corpus.get("shortbread", "reformulated-2025"), 96)
    assert s["factor"] == 4.0
    flour = next(i for i in s["ingredients"] if i["item"] == "Plain flour")
    assert flour["qty"] == 1200 and flour["original_qty"] == 300
    assert s["times_minutes_UNCHANGED"] == {"prep_minutes": 15, "cook_minutes": 20}
    assert s["oven_c_UNCHANGED"] == 160
    assert "never multiply" in s["time_rule"]


def test_scaling_as_needed_stays_as_needed():
    s = scaling.scale(corpus.get("idli", "original"), 48)
    water = next(i for i in s["ingredients"] if i["item"] == "Water")
    assert water["qty"] is None and water["unit"] == "as needed"


def test_scaling_fractional_pieces_are_flagged():
    s = scaling.scale(corpus.get("beef_burgers", "original"), 6)
    egg = next(i for i in s["ingredients"] if i["item"] == "Egg")
    assert egg["qty"] == 1.5 and "fractional" in egg["note"]


def test_poultry_scaling_carries_probe_temperature():
    s = scaling.scale(corpus.get("roast_chicken", "original"), 8)
    assert "74°C" in s["doneness_rule"]
    assert next(i for i in s["ingredients"] if i["item"] == "Whole chicken")["qty"] == 3.2
