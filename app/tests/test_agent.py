"""
The agent + service end to end, offline: a scripted model, the real tool
code, the real logging. Covers the loop, budgets, failures and the cache path.
"""
import asyncio

import pytest

from pantry import config, llm, service
from pantry.tracing import read_jsonl
from tests.conftest import final_turn, model_turn, tool_call

SHORTBREAD_FINAL = dict(answer="No: the current shortbread contains tree nuts [shortbread@reformulated-2025].",
                        citations=["shortbread@reformulated-2025"])


def ask(question, registry, **kw):
    return asyncio.run(service.answer(question, registry, **kw))


def test_full_loop_tools_final_and_log(fake_llm, fake_registry, log_dir):
    llm_fake = fake_llm([
        model_turn(tool_call("search_recipes", {"query": "shortbread"})),
        model_turn(tool_call("check_allergens", {"recipe_id": "shortbread", "version": "reformulated-2025",
                                                 "allergies": ["nuts"]})),
        final_turn(**SHORTBREAD_FINAL),
    ])
    reg = fake_registry()
    events = []
    res = ask("Is the shortbread safe? My son has a nut allergy.", reg,
              on_event=lambda *a: events.append(a[1]))

    assert res["final"]["citations"] == ["shortbread@reformulated-2025"]
    assert [s["action"] for s in res["steps"]] == ["search_recipes", "check_allergens", "final_answer"]
    assert events == ["search_recipes", "check_allergens"]
    # trace id travels with every MCP call
    assert {c[2] for c in reg.calls} == {res["trace_id"]}
    # the model saw compact JSON, not the full server payload
    tool_msgs = [m for m in llm_fake.requests[-1]["messages"] if m["role"] == "tool"]
    assert '"verdict":"UNSAFE"' in tool_msgs[-1]["content"] and "method" not in tool_msgs[-1]["content"]
    # tools are offered in a stable, sorted order (prompt-cache friendly)
    names = [t["function"]["name"] for t in llm_fake.requests[0]["tools"]]
    assert names == sorted(names) and "scale_recipe" in names

    rec = read_jsonl(config.REQUEST_LOG)[-1]
    assert rec["trace_id"] == res["trace_id"]
    assert rec["allergen_codes_checked"] == ["PEANUT", "TREE_NUT"]
    assert "nut allergy" not in rec["query"] and "[HEALTH]" in rec["query"]
    assert rec["tokens_in"] == 3000 and rec["cost_usd"] > 0
    assert [s["stage"] for s in rec["spans"]].count("llm") == 3


def test_parallel_tool_calls_all_run(fake_llm, fake_registry):
    fake_llm([
        model_turn(tool_call("safe_temperature", {"food": "chicken"}, "a"),
                   tool_call("scale_recipe", {"recipe_id": "roast_chicken", "version": "original",
                                              "target_amount": 8}, "b")),
        final_turn(answer="Roast 3.2 kg to 74°C [roast_chicken@original].", citations=["roast_chicken@original"]),
    ])
    res = ask("Roast chicken for 8?", fake_registry())
    by_action = {s["action"]: s for s in res["steps"][:2]}
    assert set(by_action) == {"safe_temperature", "scale_recipe"}
    assert by_action["scale_recipe"]["result"]["factor"] == 2.0
    assert by_action["safe_temperature"]["result"]["safe_internal_c"] == 74
    llm_spans = [s for s in res["record"]["spans"] if s["stage"] == "llm"]
    assert len(llm_spans) == 2          # both tools ran inside ONE model turn


def test_tool_error_goes_back_to_the_model(fake_llm, fake_registry):
    llm_fake = fake_llm([
        model_turn(tool_call("search_recipes", {"query": "x"})),
        final_turn(answer="Search is unavailable, I can't answer.", refused=True),
    ])
    res = ask("anything", fake_registry(fail={"search_recipes": "search_recipes timed out after 30s"}))
    assert res["steps"][0]["result"] == {"error": "search_recipes timed out after 30s"}
    assert "timed out" in llm_fake.requests[1]["messages"][-1]["content"]
    assert res["final"]["refused"] is True


def test_malformed_tool_arguments_do_not_crash(fake_llm, fake_registry):
    from types import SimpleNamespace
    bad = SimpleNamespace(id="c1", type="function", function=SimpleNamespace(name="get_recipe", arguments="{not json"))
    fake_llm([model_turn(bad), final_turn(answer="Sorry.", refused=True)])
    res = ask("q", fake_registry())
    assert "not a valid JSON object" in res["steps"][0]["result"]["error"]


def test_bad_scale_input_is_a_tool_error(fake_llm, fake_registry):
    fake_llm([model_turn(tool_call("scale_recipe", {"recipe_id": "idli", "version": "original",
                                                    "target_amount": -4})),
              final_turn(answer="Sorry.", refused=True)])
    res = ask("q", fake_registry())
    assert "between 0 and 10000" in res["steps"][0]["result"]["error"]


def test_llm_outage_ends_cleanly(fake_llm, fake_registry):
    fake_llm([llm.LLMError("APIConnectionError after 3 attempts")])
    res = ask("Is idli vegan?", fake_registry())
    assert res["record"]["terminated_by"] == "llm_error"
    assert res["final"]["refused"] and "temporarily unavailable" in res["final"]["answer"]


def test_iteration_budget(fake_llm, fake_registry):
    fake_llm([model_turn(tool_call("safe_temperature", {"food": "chicken"}))] * 3)
    res = ask("loop forever", fake_registry(), budgets={"max_iters": 3})
    assert res["record"]["terminated_by"] == "max_iters" and res["final"]["refused"]


def test_cost_budget(fake_llm, fake_registry):
    fake_llm([model_turn(tool_call("safe_temperature", {"food": "chicken"}))] * 5, tokens=(200_000, 0))
    res = ask("expensive", fake_registry(), budgets={"max_cost_usd": 0.01, "max_tokens": 10**9})
    assert res["record"]["terminated_by"] == "max_cost"


def test_unparseable_final_is_kept_and_flagged(fake_llm, fake_registry):
    from types import SimpleNamespace
    fake_llm([SimpleNamespace(content="Just plain text, no JSON", tool_calls=None)])
    res = ask("q", fake_registry())
    assert res["final"]["parse_error"] and res["final"]["answer"] == "Just plain text, no JSON"


def test_invalid_citation_is_flagged(fake_llm, fake_registry):
    fake_llm([final_turn(answer="See [brownies@original].", citations=["brownies@original"])])
    res = ask("brownies?", fake_registry())
    assert res["final"]["invalid_citations"] == ["brownies@original"]


@pytest.mark.parametrize("q", ["", "   ", "x" * 1001])
def test_invalid_questions_rejected_before_any_model_call(fake_llm, fake_registry, q):
    llm_fake = fake_llm([])
    with pytest.raises(service.InvalidQuestion):
        ask(q, fake_registry())
    assert llm_fake.requests == []


def test_eval_traffic_goes_to_eval_log(fake_llm, fake_registry):
    fake_llm([final_turn(answer="Sorry.", refused=True)])
    res = ask("q", fake_registry(), source="eval")
    assert read_jsonl(config.EVAL_LOG)[-1]["trace_id"] == res["trace_id"]


def test_cache_hit_skips_the_model(fake_llm, fake_registry, monkeypatch, tmp_path):
    from pantry import cache as cache_mod
    from tests.test_cache import fake_embed
    monkeypatch.setattr(service, "_cache", cache_mod.SemanticCache(path=tmp_path / "c.jsonl", embed=fake_embed))
    good = dict(answer="250 g [medu_vada@original].", citations=["medu_vada@original"])
    llm_fake = fake_llm([final_turn(**good)])
    reg = fake_registry()
    q = "How much urad dal goes into medu vada?"
    first = ask(q, reg, use_cache=True)
    second = ask(q, reg, use_cache=True)
    assert len(llm_fake.requests) == 1                     # second answer cost no model call
    assert second["final"]["cached"] and second["record"]["cache"]["source_trace_id"] == first["trace_id"]
    assert second["record"]["cost_usd"] == 0


def test_allergy_question_bypasses_cache(fake_llm, fake_registry, monkeypatch, tmp_path):
    from pantry import cache as cache_mod
    from tests.test_cache import fake_embed
    monkeypatch.setattr(service, "_cache", cache_mod.SemanticCache(path=tmp_path / "c.jsonl", embed=fake_embed))
    fake_llm([final_turn(**SHORTBREAD_FINAL), final_turn(**SHORTBREAD_FINAL)])
    reg = fake_registry()
    q = "Is the shortbread ok for a nut allergy?"
    ask(q, reg, use_cache=True)
    res = ask(q, reg, use_cache=True)
    assert "skipped" in res["record"]["cache"] and not res["final"].get("cached")
    assert service.get_cache().entries == []
