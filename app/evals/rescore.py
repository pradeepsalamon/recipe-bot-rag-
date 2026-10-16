"""
`python run.py rescore <run>.jsonl`: re-apply the CURRENT assertions to the
answers a run already produced, without asking the model again.

Used when an assertion turns out to be mis-specified: the answers stay
exactly as they were; only the scoring changes, and the report says so.
Runs written before steps were stored in the row get their tool steps
rebuilt from the eval trace log (same trace id). Cases that pass after
re-scoring but were never judged are sent to the judge now, so nothing
passes without it.
"""
import json
from pathlib import Path

from pantry import config, corpus
from pantry.tracing import read_jsonl

from . import assertions, judge
from .run_evals import is_infra_error, load_cases, render_report, summary_line


def _steps_from_trace(rec):
    steps = []
    for s in sorted(rec["spans"], key=lambda s: s["start_ts"]):
        if s["stage"] not in ("mcp", "tool"):
            continue
        args = dict(s["attrs"].get("args", {}))
        for k in list(args):
            if k.endswith("_codes"):          # logs keep allergy CODES, which the checker accepts
                args[k[:-len("_codes")]] = args.pop(k)
        steps.append({"action": s["name"], "input": args})
    return steps


def _load_rows(run_files):
    """One row per case. With several files (a run plus a re-run of its
    infrastructure errors), a real answer replaces an INFRA row; otherwise
    the first file wins."""
    merged, order = {}, []
    for f in run_files:
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            cid = row["case_id"]
            if cid not in merged:
                order.append(cid)
                merged[cid] = row
            elif merged[cid].get("infra_error") and not row.get("infra_error"):
                merged[cid] = dict(row, rerun_of=merged[cid]["trace_id"])
    return [merged[c] for c in order]


def rescore(run_file, use_judge=True, extra_files=()):
    run_file = Path(run_file)
    rows = _load_rows([run_file, *extra_files])
    cases = {c["id"]: c for c in load_cases()}
    traces = {r["trace_id"]: r for r in read_jsonl(config.EVAL_LOG)}
    out, newly_judged = [], 0
    for row in rows:
        rec = traces.get(row["trace_id"], {})
        steps = row.get("steps") or _steps_from_trace(rec) if rec else row.get("steps", [])
        terminated = row.get("terminated_by", rec.get("terminated_by"))
        final = {"answer": row["answer"], "citations": row["citations"], "recommended": row["recommended"],
                 "substitutions": row["substitutions"], "refused": row["refused"],
                 "invalid_citations": [c for c in row["citations"] if corpus.get_by_key(c) is None],
                 "terminated": bool(terminated) and terminated != "llm_error"}
        case = cases[row["case_id"]]
        checks = assertions.check(case, final, steps)
        passed = all(ok for ok, _ in checks.values())
        jv = row.get("judge")
        if passed and jv is None and use_judge:
            jv = judge.judge_one(case, final)
            newly_judged += 1
        new = dict(row, steps=steps, terminated_by=terminated,
                   assertions={k: {"pass": ok, "detail": d} for k, (ok, d) in checks.items()},
                   assertions_passed=passed, trajectory=assertions.trajectory(case, steps), judge=jv,
                   system_pass=passed and (jv is None or jv["verdict"] == "pass"),
                   rescored_from=run_file.name)
        new["infra_error"] = is_infra_error(rec) if rec else bool(row.get("infra_error"))
        out.append(new)

    stem = run_file.stem + "_rescored"
    jsonl = run_file.with_name(stem + ".jsonl")
    jsonl.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    scored = [r for r in out if not r["infra_error"]]
    md = run_file.with_name(stem + ".md")
    md.write_text(render_report(stem, scored, [r["case_id"] for r in out if r["infra_error"]])
                  + f"\n_Re-scored from `{run_file.name}`"
                    + (f" + re-run of its infrastructure errors {[Path(f).name for f in extra_files]}"
                       if extra_files else "")
                    + f": same answers, current assertions (see docs/eval_measurement_fixes.md). "
                      f"{newly_judged} newly passing cases judged now._\n",
                  encoding="utf-8")
    print(f"wrote {jsonl.name}\nwrote {md.name}")
    print(summary_line(scored))
    return 0
