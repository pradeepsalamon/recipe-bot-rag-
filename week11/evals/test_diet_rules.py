"""
Tests for the checker itself. If the dairy rule is wrong, every RED/GREEN
result built on it is wrong too, so the rule gets its own tests.

    python -m pytest evals/test_diet_rules.py -q      (from week11/)
    python evals/test_diet_rules.py                  (no pytest needed)
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from diet_rules import RECIPES_WITH_DAIRY, classify_input, dairy_mentions, dairy_violation

PONGAL_Q = "I'm cooking Ven Pongal for a dairy-free guest. What can I fry the cashews in instead of butter?"
RASAM_Q = "I'm dairy-free. Is the Rasam recipe safe for me as written?"

# (question, answer, should_be_flagged). The first two answers are verbatim
# v1 outputs from this week's probes.
CASES = [
    (PONGAL_Q, "The recipe calls for frying the cashews in ghee. [chunk_0df1a3f4]", True),
    (RASAM_Q, "The Rasam recipe as provided contains only tamarind pulp... (usually oil or ghee, "
              "but the text does not specify any dairy). Since no dairy ingredients are mentioned, "
              "the recipe appears to be dairy‑free.", True),
    ("Is Rasam dairy-free?", "Rasam does not contain any dairy products. [chunk_f16abe83]", True),
    (PONGAL_Q, "Use ghee instead - ghee is clarified, so it’s dairy‑free.", True),
    (PONGAL_Q, "Ghee is dairy-free, use it.", True),
    # Good answers must pass.
    (PONGAL_Q, "Ghee is a dairy product, so it is not dairy-free. The documents do not list a "
               "dairy-free fat for Ven Pongal. [chunk_697e81e5]", False),
    (PONGAL_Q, "Use coconut milk or oil.", False),
    ("Is Rasam dairy-free?", "Not as written: step 3 heats ghee, which is dairy [chunk_e5d73d96]. "
                             "The ingredient row allows ghee or oil [chunk_ea5622de], so use oil "
                             "and it is dairy-free.", False),
    ("Is Idli vegan?", "Yes, Idli is vegan. [chunk_1b753c67]", False),
    # Real v1 outputs from last week's log that an earlier version of the rule
    # wrongly flagged: a refusal echoing the question, and two hedges.
    ("I'm lactose intolerant, can I replace the ghee in pongal with oil?",
     "I’m sorry, but the provided recipe documents do not contain any information about "
     "substituting ghee with oil for Ven Pongal. [chunk_0df1a3f4]", False),
    ("Is Rasam dairy-free?", "The provided recipe documents do not contain enough information "
                             "to determine whether Rasam is dairy‑free.", False),
    (RASAM_Q, "The provided recipe steps do not mention any dairy ingredients, but the information "
              "is incomplete enough that I cannot confirm whether the Rasam recipe is fully "
              "dairy‑free.", False),
    ("How much salt in idli?", "15 g of salt.", False),  # not a diet question at all
]


def test_dairy_violation_cases():
    for question, answer, flagged in CASES:
        got = dairy_violation(question, answer)
        assert (got is not None) == flagged, f"{answer[:60]!r} -> {got}"


def test_plant_milks_are_not_dairy():
    assert dairy_mentions("Use coconut milk, or peanut butter for richness") == []
    assert dairy_mentions("Fry in butter, then add milk") == ["butter", "milk"]


def test_input_types():
    assert classify_input(PONGAL_Q) == "dietary_swap"
    assert classify_input("Can I use oil instead of ghee in Rasam?") == "swap"
    assert classify_input("Is Idli vegan?") == "dietary"
    assert classify_input("Tell me a joke") == "out_of_scope"


def test_dairy_recipe_list_matches_corpus():
    """RECIPES_WITH_DAIRY is hardcoded for speed; check it against Chroma."""
    db = sqlite3.connect(config.CHROMA_DIR / "chroma.sqlite3")
    rows = db.execute("""
        select m.id, m.key, m.string_value
        from embedding_metadata m
        join embeddings e on e.id = m.id
        join segments s on s.id = e.segment_id
        join collections c on c.id = s.collection
        where c.name = ?""", (config.COLLECTION,)).fetchall()
    chunks = {}
    for cid, key, value in rows:
        chunks.setdefault(cid, {})[key] = value

    with_dairy = {
        c["recipe_id"] for c in chunks.values()
        if "Ingredients Table Row" in c["chroma:document"]
        and dairy_mentions(c["chroma:document"].split("Ingredient:")[1].split("\n")[0])
    }
    assert with_dairy == RECIPES_WITH_DAIRY, with_dairy


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
