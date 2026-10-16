"""Eval plumbing: infrastructure errors are excluded, never scored; re-runs merge correctly."""
import json

from evals.rescore import _load_rows
from evals.run_evals import is_infra_error


def _rec(term, waits=()):
    return {"terminated_by": term,
            "spans": [{"stage": "llm", "attrs": {"retry_wait_s": w}} for w in waits]}


def test_llm_error_is_infra():
    assert is_infra_error(_rec("llm_error"))


def test_wall_clock_eaten_by_rate_limits_is_infra():
    assert is_infra_error(_rec("max_wall_clock", [100, 40]))


def test_wall_clock_from_slow_reasoning_is_a_real_failure():
    assert not is_infra_error(_rec("max_wall_clock", [3]))


def test_normal_answers_are_not_infra():
    assert not is_infra_error(_rec(None)) and not is_infra_error(_rec("max_iters"))


def test_rerun_replaces_only_infra_rows(tmp_path):
    a, b = tmp_path / "run.jsonl", tmp_path / "rerun.jsonl"
    a.write_text("".join(json.dumps(r) + "\n" for r in [
        {"case_id": "B01", "trace_id": "t1", "infra_error": True},
        {"case_id": "B02", "trace_id": "t2", "infra_error": False, "answer": "first"},
    ]), encoding="utf-8")
    b.write_text("".join(json.dumps(r) + "\n" for r in [
        {"case_id": "B01", "trace_id": "t3", "infra_error": False},
        {"case_id": "B02", "trace_id": "t4", "infra_error": False, "answer": "second"},
    ]), encoding="utf-8")
    rows = {r["case_id"]: r for r in _load_rows([a, b])}
    assert rows["B01"]["trace_id"] == "t3" and rows["B01"]["rerun_of"] == "t1"
    assert rows["B02"]["answer"] == "first"          # a real answer is never replaced
