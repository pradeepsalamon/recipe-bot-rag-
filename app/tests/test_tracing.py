"""Logs: rotation, torn lines, redaction, cross-process trace merge."""
import json

from pantry import config, tracing


def test_rotation_keeps_one_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_MAX_BYTES", 200)
    p = tmp_path / "r.jsonl"
    for i in range(10):
        tracing.append_jsonl(p, {"i": i, "pad": "x" * 40})
    assert p.exists() and (tmp_path / "r.jsonl.1").exists()
    assert p.stat().st_size <= 200
    assert tracing.read_jsonl(p)[-1]["i"] == 9          # newest record is in the live file
    assert tracing.read_jsonl(tmp_path / "r.jsonl.1")    # the previous chunk is kept once


def test_torn_last_line_is_skipped(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text('{"a": 1}\n{"a": 2', encoding="utf-8")
    assert tracing.read_jsonl(p) == [{"a": 1}]


def test_redaction_masks_health_statements_not_recipe_words():
    q = tracing.redact("my kid is allergic to nuts and I have a peanut allergy, I'm coeliac")
    for raw in ("my kid", "allergic to nuts", "peanut allergy", "coeliac"):
        assert raw not in q, q
    assert tracing.redact("Contains allergens: GLUTEN, TREE_NUT") == "Contains allergens: GLUTEN, TREE_NUT"


def test_span_records_error_and_latency():
    t = tracing.Trace("q")
    try:
        with t.span("boom", "tool"):
            raise RuntimeError("x")
    except RuntimeError:
        pass
    sp = t.spans[0].to_dict()
    assert sp["error"].startswith("RuntimeError") and sp["latency_ms"] >= 0 and sp["trace_id"] == t.trace_id


def test_full_trace_merges_server_spans(tmp_path, monkeypatch):
    req, srv = tmp_path / "req.jsonl", tmp_path / "srv.jsonl"
    monkeypatch.setattr(config, "MCP_SPAN_LOG", srv)
    tracing.append_jsonl(req, {"trace_id": "abc123", "spans": []})
    tracing.append_jsonl(srv, {"trace_id": "abc123", "name": "check_allergens"})
    tracing.append_jsonl(srv, {"trace_id": "other", "name": "x"})
    rec = tracing.full_trace("abc", log_path=req)
    assert [s["name"] for s in rec["server_spans"]] == ["check_allergens"]


def test_server_span_writes_under_callers_trace_id(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MCP_SPAN_LOG", tmp_path / "srv.jsonl")
    with tracing.server_span("get_recipe", {"trace_id": "T1", "parent_span_id": "P1"}):
        pass
    s = json.loads((tmp_path / "srv.jsonl").read_text(encoding="utf-8"))
    assert (s["trace_id"], s["parent_id"], s["process"]) == ("T1", "P1", "mcp-server")
