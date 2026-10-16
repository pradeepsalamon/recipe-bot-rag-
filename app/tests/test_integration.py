"""
Real processes: the MCP server as a subprocess over stdio, the real
retriever and index. Slower (embedding model load), still offline (no Groq).
"""
import asyncio
import json

import pytest

from pantry import config, retriever, service
from pantry.mcp_client import McpToolRegistry
from pantry.tracing import full_trace, read_jsonl
from tests.conftest import final_turn, model_turn, tool_call


@pytest.fixture(scope="module", autouse=True)
def index():
    if not retriever.index_exists():
        retriever.build_index()


def test_retriever_keeps_both_versions_and_labels_them():
    res = retriever.search("shortbread", top_k=5)
    by_key = {h["recipe"]: h for h in res["results"]}
    assert by_key["shortbread@original"]["status"] == "superseded"
    assert by_key["shortbread@reformulated-2025"]["status"] == "current"
    assert all(c.startswith(h["recipe"] + "#") for h in res["results"] for c in h["chunks"])


def test_retriever_exclusion_is_exact_match_on_declarations():
    res = retriever.search("nut-free shortbread", exclude_allergens=["nuts"])
    keys = [h["recipe"] for h in res["results"]]
    assert "shortbread@reformulated-2025" not in keys
    assert "shortbread@reformulated-2025" in res["excluded_by_declaration"]
    # the brief's trap, reproduced: the superseded nut-free version survives the filter
    assert keys[0] == "shortbread@original"


def test_mcp_server_over_stdio():
    async def go():
        async with McpToolRegistry() as reg:
            assert sorted(reg.tools) == ["check_allergens", "find_substitution", "get_recipe",
                                         "match_pantry", "safe_temperature", "search_recipes"]
            ok = await reg.call("check_allergens", {"recipe_id": "shortbread", "version": "reformulated-2025",
                                                    "allergies": ["nuts"]}, trace_id="itest-1", parent_span_id="p1")
            missing = await reg.call("get_recipe", {"recipe_id": "shortbread", "version": "v9"})
            empty = await reg.call("check_allergens", {"recipe_id": "idli", "version": "original", "allergies": []})
            too_long = await reg.call("search_recipes", {"query": "x" * 600})
            unknown = await reg.call("no_such_tool", {})
            bad_type = await reg.call("check_allergens", {"recipe_id": "idli"})
            return ok, missing, empty, too_long, unknown, bad_type
    ok, missing, empty, too_long, unknown, bad_type = asyncio.run(go())
    assert ok["verdict"] == "UNSAFE"
    assert missing["known_versions"] == ["shortbread@original", "shortbread@reformulated-2025"]
    assert "empty" in empty["error"] and "longer than" in too_long["error"]
    assert "not found" in unknown["error"] and "error" in bad_type
    spans = [s for s in read_jsonl(config.MCP_SPAN_LOG) if s["trace_id"] == "itest-1"]
    assert spans and spans[0]["parent_id"] == "p1" and spans[0]["attrs"]["verdict"] == "UNSAFE"


def test_one_trace_id_across_agent_and_mcp_hop(fake_llm):
    fake_llm([
        model_turn(tool_call("search_recipes", {"query": "shortbread"})),
        model_turn(tool_call("check_allergens", {"recipe_id": "shortbread", "version": "reformulated-2025",
                                                 "allergies": ["nuts"]})),
        final_turn(answer="No [shortbread@reformulated-2025].", citations=["shortbread@reformulated-2025"]),
    ])

    async def go():
        async with McpToolRegistry() as reg:
            return await service.answer("Is the shortbread safe for a nut allergy?", reg)
    res = asyncio.run(go())
    rec = full_trace(res["trace_id"])
    server = {s["name"]: s for s in rec["server_spans"]}
    client = {s["name"]: s for s in rec["spans"]}
    assert set(server) == {"search_recipes", "check_allergens"}
    for name in server:   # each server span hangs under the client span that called it
        assert server[name]["parent_id"] == client[name]["span_id"]
    # the server logged allergen codes, never the user's words
    assert "nuts" not in json.dumps(server["check_allergens"]["attrs"])
