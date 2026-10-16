"""LangSmith mirror: what would be sent, and that it can never hurt a request."""
import uuid
from datetime import datetime, timezone

from pantry import config, observability
from pantry.tracing import Trace, redact


class FakeLSClient:
    """Accepts anything; build_tree never posts on its own."""

    def __getattr__(self, name):
        return lambda *a, **k: None


def _record():
    t = Trace("my kid is allergic to nuts, is the shortbread ok?")
    with t.span("agent", "agent") as root:
        with t.span("llm#1", "llm", parent_id=root.span_id) as sp:
            sp.set_usage(config.AGENT_MODEL, 1200, 40, tokens_cached=256)
        with t.span("check_allergens", "mcp", parent_id=root.span_id) as tsp:
            tsp.attrs.update({"args": {"recipe_id": "shortbread", "allergies_codes": ["PEANUT", "TREE_NUT"]},
                              "result": "shortbread@reformulated-2025 [current] -> UNSAFE"})
    return {"trace_id": t.trace_id, "ts": t.ts.isoformat(), "session_id": t.session_id, "source": "cli",
            "release": "v1", "prompt_version": "agent_v1", "model": config.AGENT_MODEL,
            "query": redact(t.query), "allergen_codes_checked": ["PEANUT", "TREE_NUT"],
            "tools_called": ["check_allergens"], "answer": "No [shortbread@reformulated-2025].",
            "citations": ["shortbread@reformulated-2025"], "recommended": [], "substitutions": [],
            "refused": False, "invalid_citations": [], "terminated_by": None, "cache": {"enabled": False},
            "latency_ms": 50.0, "tokens_in": 1200, "tokens_out": 40, "cost_usd": 0.0001,
            "spans": [s.to_dict() for s in t.spans]}


def _walk(run):
    yield run
    for c in run.child_runs:
        yield from _walk(c)


def test_tree_shape_ids_and_usage():
    rec = _record()
    root = observability.build_tree(rec, ls_client=FakeLSClient())
    assert root.id == uuid.UUID(rec["trace_id"])
    (agent,) = root.child_runs
    assert agent.name == "agent"
    names = {c.name: c for c in agent.child_runs}
    assert set(names) == {"llm#1", "check_allergens"}
    assert names["llm#1"].run_type == "llm" and names["check_allergens"].run_type == "tool"
    usage = names["llm#1"].extra["metadata"]["usage_metadata"]
    assert usage["input_tokens"] == 1200 and usage["input_token_details"]["cache_read"] == 256


def test_no_raw_health_text_leaves_the_machine():
    root = observability.build_tree(_record(), ls_client=FakeLSClient())
    blob = " ".join(str(r.inputs) + str(r.outputs) + str(r.extra) for r in _walk(root))
    assert "allergic to nuts" not in blob and "my kid" not in blob
    assert "[HEALTH]" in str(root.inputs)
    assert "TREE_NUT" in blob     # codes are what we chose to keep


def test_old_records_are_time_shifted_for_upload():
    rec = _record()
    rec["ts"] = "2026-01-01T00:00:00+00:00"
    root = observability.build_tree(rec, ls_client=FakeLSClient(),
                                    now=datetime(2026, 10, 16, tzinfo=timezone.utc))
    assert root.extra["metadata"]["time_shifted_for_upload"] is True


def test_disabled_by_default_and_without_key(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setitem(config.LANGSMITH, "enabled", True)
    assert observability.mirror(_record()) is False


def test_mirror_failure_never_raises(monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "x")
    monkeypatch.setitem(config.LANGSMITH, "enabled", True)

    def boom(*a, **k):
        raise ConnectionError("network down")
    monkeypatch.setattr(observability, "build_tree", boom)
    assert observability.mirror(_record()) is False
