"""Release v2: hidden superseded versions, current-version guard, as-substituted
check, and the answer validator with its repair turn."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from pantry import config, mcp_server, retriever, service, validator
from tests.conftest import final_turn, model_turn, tool_call


@pytest.fixture
def v2(monkeypatch):
    monkeypatch.setattr(config, "RELEASE", "v2")


def _ctx():
    return SimpleNamespace(request_context=SimpleNamespace(meta={}))


def _final(answer, citations=(), recommended=(), substitutions=(), refused=False):
    return {"answer": answer, "citations": list(citations), "recommended": list(recommended),
            "substitutions": list(substitutions), "refused": refused, "invalid_citations": []}


# --- tools -----------------------------------------------------------------
def test_search_hides_superseded_but_lists_them():
    res = retriever.search("shortbread", include_superseded=False)
    assert "shortbread@original" not in [h["recipe"] for h in res["results"]]
    assert "shortbread@original" in res["hidden_superseded"]


def test_v1_search_still_returns_superseded():
    res = retriever.search("shortbread")
    assert "shortbread@original" in [h["recipe"] for h in res["results"]] and "hidden_superseded" not in res


def test_guard_checks_the_current_version(v2):
    res = json.loads(mcp_server._check(_ctx(), "shortbread", "original", ["nuts"], None))
    assert res["recipe"] == "shortbread@reformulated-2025" and res["verdict"] == "UNSAFE"
    assert res["asked_about"] == "shortbread@original" and res["asked_version_verdict"] == "SAFE"


def test_no_guard_in_v1():
    res = json.loads(mcp_server._check(_ctx(), "shortbread", "original", ["nuts"], None))
    assert res["recipe"] == "shortbread@original" and res["verdict"] == "SAFE"


def test_as_substituted_check(v2):
    res = json.loads(mcp_server._check(_ctx(), "ven_pongal", "original", ["peanut"],
                                       [{"from": "cashews", "to": "roasted peanuts"}]))
    assert res["published_verdict"] == "SAFE" and res["verdict"] == "UNSAFE"


def test_get_recipe_warns_on_superseded(v2):
    res = json.loads(mcp_server._get(_ctx(), "shortbread", "original"))
    assert res["warning"].startswith("SUPERSEDED")


def test_bad_substitutions_shape_rejected(v2):
    res = json.loads(mcp_server._check(_ctx(), "idli", "original", ["egg"], "not a list"))
    assert "substitutions must be a list" in res["error"]


# --- validator -------------------------------------------------------------
def test_superseded_citation_flagged_unless_history_question():
    f = _final("Nut-free [shortbread@original].", ["shortbread@original"])
    assert any("superseded" in p for p in validator.problems("Is the shortbread nut-free?", f, []))
    assert not any("superseded" in p for p in validator.problems("What changed in the shortbread?", f, []))


def test_missing_inline_citation_flagged_even_on_a_warning():
    steps = [{"action": "check_allergens", "input": {"recipe_id": "shortbread", "version": "reformulated-2025"},
              "result": {"recipe": "shortbread@reformulated-2025"}}]
    f = _final("It contains tree nuts, avoid it.", refused=True, citations=["shortbread@reformulated-2025"])
    assert any("inline" in p for p in validator.problems("nut allergy shortbread?", f, steps))


def test_refusal_with_nothing_to_cite_is_fine():
    f = _final("I don't have a beef wellington recipe.", refused=True)
    assert validator.problems("beef wellington?", f, [{"action": "search_recipes", "input": {}}]) == []


def test_quantities_need_a_get_recipe():
    f = _final("Use 800 g flour [shortbread@reformulated-2025].", ["shortbread@reformulated-2025"])
    assert any("get_recipe" in p for p in validator.problems("96 fingers?", f, []))
    steps = [{"action": "scale_recipe", "input": {"recipe_id": "shortbread", "version": "reformulated-2025"}}]
    assert not any("get_recipe" in p for p in validator.problems("96 fingers?", f, steps))


def test_allergy_recommendation_needs_its_own_check():
    f = _final("Make idli [idli@original].", ["idli@original"], ["idli@original"])
    assert any("check_allergens" in p for p in validator.problems("egg allergy, idli ok?", f, []))


def test_substitutions_for_allergic_user_need_as_substituted_check():
    f = _final("Swap cashews for sunflower seeds [ven_pongal@original].", ["ven_pongal@original"],
               substitutions=[{"recipe": "ven_pongal@original", "from": "cashews", "to": "roasted sunflower seeds"}])
    steps = [{"action": "check_allergens", "input": {"recipe_id": "ven_pongal", "version": "original"},
              "result": {"recipe": "ven_pongal@original"}}]
    assert any("AS SUBSTITUTED" in p for p in validator.problems("pongal, nut allergy", f, steps))


def test_poultry_answer_needs_a_temperature():
    f = _final("Simmer until cooked through [chicken_chettinad@original].", ["chicken_chettinad@original"])
    assert any("°C" in p for p in validator.problems("when is it done?", f, []))
    f["answer"] += " Cook to 74°C."
    assert validator.problems("when is it done?", f, []) == []


def test_clean_answer_has_no_problems():
    steps = [{"action": "get_recipe", "input": {"recipe_id": "medu_vada", "version": "original"}}]
    f = _final("250 g urad dal [medu_vada@original].", ["medu_vada@original"])
    assert validator.problems("urad dal in medu vada?", f, steps) == []


# --- repair loop ------------------------------------------------------------
def test_repair_turn_fixes_a_superseded_answer(v2, fake_llm, fake_registry):
    llm_fake = fake_llm([
        final_turn(answer="Yes, nut-free [shortbread@original].", citations=["shortbread@original"],
                   recommended=["shortbread@original"]),
        model_turn(tool_call("check_allergens", {"recipe_id": "shortbread", "version": "reformulated-2025",
                                                 "allergies": ["nuts"]})),
        final_turn(answer="No: it contains tree nuts [shortbread@reformulated-2025].",
                   citations=["shortbread@reformulated-2025"]),
    ])
    res = asyncio.run(service.answer("Is the shortbread OK for a nut allergy?", fake_registry()))
    assert res["final"]["citations"] == ["shortbread@reformulated-2025"]
    assert len(res["record"]["validator_repairs"]) == 1 and res["record"]["validator_unresolved"] == []
    assert "NOT sent" in llm_fake.requests[1]["messages"][-1]["content"]


def test_unfixed_answer_ships_flagged_after_max_repairs(v2, fake_llm, fake_registry):
    bad = final_turn(answer="Yes [shortbread@original].", citations=["shortbread@original"])
    fake_llm([bad, bad])
    res = asyncio.run(service.answer("Is the shortbread OK for a nut allergy?", fake_registry()))
    assert res["record"]["validator_unresolved"] and len(res["record"]["validator_repairs"]) == 1


def test_v1_has_no_validator(fake_llm, fake_registry):
    fake_llm([final_turn(answer="Yes [shortbread@original].", citations=["shortbread@original"])])
    res = asyncio.run(service.answer("Is the shortbread OK for a nut allergy?", fake_registry()))
    assert res["record"]["validator_repairs"] == []


def test_v2_mcp_schema_over_stdio(monkeypatch):
    from pantry.mcp_client import McpToolRegistry
    monkeypatch.setenv("PANTRY_RELEASE", "v2")

    async def go():
        async with McpToolRegistry() as reg:
            props = {t["function"]["name"]: t["function"]["parameters"]["properties"] for t in reg.schemas()}
            r = await reg.call("check_allergens", {"recipe_id": "shortbread", "version": "original",
                                                   "allergies": ["nuts"]})
            return props, r
    props, r = asyncio.run(go())
    assert "include_superseded" in props["search_recipes"] and "substitutions" in props["check_allergens"]
    assert r["verdict"] == "UNSAFE" and r["asked_about"] == "shortbread@original"
