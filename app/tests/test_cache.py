"""Semantic cache: every guard, one by one."""
from datetime import datetime, timedelta, timezone

import pytest

from pantry import cache as cache_mod
from pantry.cache import SemanticCache, skip_reason, store_reason

GOOD = {"answer": "Use 250 g urad dal [medu_vada@original].", "citations": ["medu_vada@original"],
        "recommended": [], "substitutions": [], "refused": False, "invalid_citations": []}


def fake_embed(text):
    """Bag-of-letters vector: paraphrases with the same words are ~identical, different words are not."""
    v = [0.0] * 26
    for ch in text.lower():
        if "a" <= ch <= "z":
            v[ord(ch) - 97] += 1
    return v


@pytest.fixture
def make(tmp_path):
    def _make(fp="fp1", now=None):
        return SemanticCache(path=tmp_path / "c.jsonl", embed=fake_embed, fp=fp, now=now)
    return _make


@pytest.mark.parametrize("q", [
    "Is the shortbread nut-free?", "my kid is allergic to nuts", "dairy-free pesto?",
    "Can I swap butter for oil?", "vegan banana bread", "Is the chicken safe at 70 degrees?",
    "how do I know the burgers are done", "I'm coeliac, which recipes work", "recipe without eggs",
    "anything with peanuts?",
])
def test_constraint_and_safety_questions_never_touch_the_cache(q):
    assert skip_reason(q) is not None


@pytest.mark.parametrize("q", ["How much urad dal goes into medu vada?", "How long do I ferment idli batter?"])
def test_plain_recipe_questions_are_eligible(q):
    assert skip_reason(q) is None


def test_hit_on_identical_question(make):
    c = make()
    assert c.store("How much urad dal goes into medu vada?", GOOD, "t1", 0.0004, 3000)
    hit, sim = c.lookup("How much urad dal goes into medu vada?")
    assert hit and hit["source_trace_id"] == "t1" and sim >= 0.99


def test_different_recipe_never_served(make):
    c = make()
    c.store("How much salt goes into idli?", GOOD | {"citations": ["idli@original"]}, "t1", 0, 0)
    hit, _ = c.lookup("How much salt goes into dosa?")
    assert hit is None


def test_different_numbers_never_served(make):
    c = make()
    c.store("Sambar quantities for 8 people", GOOD | {"citations": ["sambar@original"]}, "t1", 0, 0)
    assert c.lookup("Sambar quantities for 12 people")[0] is None
    assert c.lookup("Sambar quantities for 8 people")[0] is not None


def test_below_threshold_not_served(make):
    c = make()
    c.store("How much urad dal goes into medu vada?", GOOD, "t1", 0, 0)
    assert c.lookup("medu vada")[0] is None


def test_reformulation_changes_fingerprint_and_voids_entries(make, tmp_path):
    c = make(fp="before")
    c.store("How much urad dal goes into medu vada?", GOOD, "t1", 0, 0)
    after = make(fp="after")          # data/recipes.json edited -> new fingerprint
    assert after.entries == [] and after.lookup("How much urad dal goes into medu vada?")[0] is None


def test_fingerprint_depends_on_recipe_data(monkeypatch, tmp_path):
    from pantry import config
    fp1 = cache_mod.fingerprint()
    edited = tmp_path / "recipes.json"
    edited.write_bytes(config.RECIPES_FILE.read_bytes() + b"\n")
    monkeypatch.setattr(config, "RECIPES_FILE", edited)
    assert cache_mod.fingerprint() != fp1


def test_ttl_expiry(make):
    t0 = datetime(2026, 10, 16, tzinfo=timezone.utc)
    clock = {"now": t0}
    c = make(now=lambda: clock["now"])
    c.store("How much urad dal goes into medu vada?", GOOD, "t1", 0, 0)
    clock["now"] = t0 + timedelta(hours=25)
    assert c.lookup("How much urad dal goes into medu vada?")[0] is None


def test_persisted_and_reloaded(make):
    make().store("How much urad dal goes into medu vada?", GOOD, "t1", 0, 0)
    assert make().lookup("How much urad dal goes into medu vada?")[0] is not None


@pytest.mark.parametrize("bad, reason", [
    ({"refused": True}, "refused"),
    ({"terminated": True}, "refused"),
    ({"citations": []}, "no citation"),
    ({"citations": ["shortbread@original"]}, "superseded"),
    ({"invalid_citations": ["x@y"]}, "invalid"),
    ({"substitutions": [{"from": "a", "to": "b"}]}, "substitution"),
])
def test_bad_answers_are_never_stored(make, bad, reason):
    assert reason in store_reason(GOOD | bad)
    assert make().store("How much urad dal goes into medu vada?", GOOD | bad, "t1", 0, 0) is False


def test_constraint_question_is_never_stored_even_if_answer_is_good(make):
    assert make().store("Is medu vada nut-free?", GOOD, "t1", 0, 0) is False


def test_max_entries_cap(make, monkeypatch):
    from pantry import config
    monkeypatch.setitem(config.CACHE, "max_entries", 3)
    c = make()
    for i in range(5):
        c.store(f"How much urad dal goes into medu vada batch {i}?", GOOD, f"t{i}", 0, 0)
    assert len(c.entries) == 3 and c.entries[0]["source_trace_id"] == "t2"


def test_real_embedding_paraphrase_hits_and_other_recipe_misses(make):
    """One check with the real MiniLM model and the real 0.88 threshold."""
    c = SemanticCache(path=make().path, fp="real")
    c.store("How much urad dal goes into medu vada?", GOOD, "t1", 0, 0)
    assert c.lookup("How much urad dal do I need for medu vada?")[0] is not None
    assert c.lookup("How long do I ferment idli batter?")[0] is None
