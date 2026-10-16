"""
`python run.py eval`: the week 6 suite, re-pointed at the INTEGRATED system.

Every case goes through the real path: agent -> MCP server -> retriever /
safety checks -> answer, with a trace id per case (logged to
logs/eval_requests.jsonl, kept apart from "production" logs). Then:

  1. deterministic assertions (evals/assertions.py) -- allergen safety is
     only ever decided here, never by a judge;
  2. the trajectory check (week 8): did it call the tools the case needs;
  3. the LLM judge, only on cases whose assertions all passed
     ("assertions before judges"), for the one thing assertions cannot
     see: is the answer grounded in the cited recipe and does it answer
     the question.

Writes evals/results/<stamp>_<label>.jsonl (one row per case) and .md (the
report). Groq's free tier allows ~8,000 tokens/minute, so a full run takes
roughly 20-30 minutes; rate-limit waits are logged on each span.
"""
import json
import statistics
import uuid
from datetime import datetime
from pathlib import Path

from pantry import agent, config, service
from pantry.mcp_client import McpToolRegistry

from . import assertions, judge

EVAL_DIR = Path(__file__).resolve().parent
CASES_FILE = EVAL_DIR / "cases.json"
RESULTS_DIR = EVAL_DIR / "results"

NOT_COVERED = [
    "Taste, texture or whether a substitution actually bakes well: the suite checks that a swap is allergen-safe, not that the shortbread still holds together.",
    "Multi-turn conversations: every case is a single question; allergies stated in turn 1 and forgotten by turn 3 are not tested.",
    "Allergens outside the 9 declared codes (kiwi, mustard, celery, lupin...) beyond one refusal case.",
    "Correctness of the client's declarations themselves: the suite trusts the CMS fields as ground truth (see `run.py check-data` for the one known conflict, rasam).",
    "Non-English questions, typos and units the user converts themselves (cups, °F).",
    "Load: every case runs alone; nothing here measures behaviour under concurrent traffic or rate-limit pressure.",
]


def is_infra_error(record):
    """No real answer because of the provider, not the system: the LLM gave
    up (outage / quota), or the wall-clock budget was eaten by rate-limit
    waits (>= half of it spent waiting)."""
    term = record.get("terminated_by")
    if term == "llm_error":
        return True
    if term == "max_wall_clock":
        waited = sum(s.get("attrs", {}).get("retry_wait_s", 0) or 0
                     for s in record.get("spans", []) if s.get("stage") == "llm")
        return waited >= config.BUDGETS["max_wall_clock_s"] / 2
    return False


def load_cases(ids=None, category=None):
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    if ids:
        wanted = {i.strip() for i in ids.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
    if category:
        cases = [c for c in cases if c["category"] == category]
    return cases


async def main(ids=None, category=None, label="", use_judge=True, fail_on_unsafe=False):
    cases = load_cases(ids, category)
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    name = f"{stamp}_{config.RELEASE}" + (f"_{label}" if label else "")
    jsonl = RESULTS_DIR / f"{name}.jsonl"
    rows = []

    async with McpToolRegistry() as reg:
        print(f"Running {len(cases)} cases against release {config.RELEASE} "
              f"(tools: {', '.join(sorted(reg.tools))} + scale_recipe)\n")
        for n, case in enumerate(cases, 1):
            try:
                # cache bypassed: the suite measures the system, not stored answers
                res = await service.answer(case["question"], reg, source="eval", use_cache=False)
            except Exception as exc:  # a crash is a result, not a reason to stop the suite
                res = {"trace_id": "crash-" + uuid.uuid4().hex, "steps": [],
                       "record": {"cost_usd": 0, "latency_ms": 0},
                       "final": {"answer": f"CRASH: {type(exc).__name__}: {exc}", "citations": [],
                                 "recommended": [], "substitutions": [], "refused": False,
                                 "terminated": True, "invalid_citations": []}}
            checks = assertions.check(case, res["final"], res["steps"])
            traj = assertions.trajectory(case, res["steps"])
            passed = all(ok for ok, _ in checks.values())
            jv = None
            if passed and use_judge:
                jv = judge.judge_one(case, res["final"])
            row = {
                "case_id": case["id"], "category": case["category"], "question": case["question"],
                "allergies": case.get("allergies", []), "trace_id": res["trace_id"],
                "answer": res["final"]["answer"], "citations": res["final"]["citations"],
                "recommended": res["final"]["recommended"], "substitutions": res["final"]["substitutions"],
                "refused": res["final"]["refused"],
                "assertions": {k: {"pass": ok, "detail": d} for k, (ok, d) in checks.items()},
                "assertions_passed": passed,
                "trajectory": traj,
                "judge": jv,
                "system_pass": passed and (jv is None or jv["verdict"] == "pass"),
                "cost_usd": res["record"]["cost_usd"], "latency_ms": res["record"]["latency_ms"],
                # provider outage / daily quota: not a system answer, excluded from every rate
                "infra_error": is_infra_error(res["record"]),
                "terminated_by": res["record"].get("terminated_by"),
                "validator_repairs": len(res["record"].get("validator_repairs", [])),
                # stored so a run can be re-scored exactly (evals/rescore.py)
                "steps": [{"action": s["action"], "input": s.get("input", {})}
                          for s in res["steps"] if s["action"] != "final_answer"],
            }
            rows.append(row)
            with open(jsonl, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            fails = [k for k, (ok, _) in checks.items() if not ok]
            verdict = "INFRA" if row["infra_error"] else ("PASS" if row["system_pass"] else "FAIL")
            print(f"[{n:>2}/{len(cases)}] {case['id']} {case['category']:<22} "
                  f"{verdict}  traj={'ok' if traj['passed'] else 'MISS'}"
                  f"  {('failed: ' + ', '.join(fails)) if fails else ''}"
                  f"{'  judge=' + jv['verdict'] if jv else ''}  trace={res['trace_id'][:12]}")

    infra = [r["case_id"] for r in rows if r["infra_error"]]
    scored = [r for r in rows if not r["infra_error"]]
    md = RESULTS_DIR / f"{name}.md"
    md.write_text(render_report(name, scored, infra), encoding="utf-8")
    print(f"\nwrote {jsonl.relative_to(EVAL_DIR.parent)}\nwrote {md.relative_to(EVAL_DIR.parent)}")
    print(summary_line(scored) + (f" | {len(infra)} infra errors excluded: {infra}" if infra else ""))
    unsafe = [r["case_id"] for r in scored
              if not r["assertions"].get("allergen_safe_published", {}).get("pass", True)
              or not r["assertions"].get("allergen_safe_as_substituted", {}).get("pass", True)]
    if fail_on_unsafe and unsafe:
        print(f"FAIL (--fail-on-unsafe): allergen-unsafe answers in {unsafe}")
        return 1
    return 0


def _rate(rows, key=lambda r: r["system_pass"]):
    n = len(rows)
    k = sum(1 for r in rows if key(r))
    return k, n, (100 * k / n if n else 0.0)


def _assert_rate(rows, name):
    have = [r for r in rows if name in r["assertions"]]
    return _rate(have, lambda r: r["assertions"][name]["pass"])


def summary_line(rows):
    k, n, p = _rate(rows)
    ua, ub, _ = _assert_rate(rows, "allergen_safe_published")
    sa, sb, _ = _assert_rate(rows, "allergen_safe_as_substituted")
    return (f"system pass {k}/{n} ({p:.0f}%) | allergen-unsafe (published) {ub - ua}/{ub} "
            f"| allergen-unsafe (as substituted) {sb - sa}/{sb}")


def render_report(name, rows, infra=()):
    k, n, p = _rate(rows)
    out = [f"# Eval report: {name}", "",
           f"Release `{config.RELEASE}`, model `{config.AGENT_MODEL}`, prompt `{agent.prompt_version()}`, "
           f"{n} cases scored, run {datetime.now().isoformat(timespec='minutes')}.", "",
           f"**System pass (all assertions, then judge): {k}/{n} = {p:.1f}%**", ""]
    if infra:
        out += [f"Excluded as infrastructure errors (provider outage / quota, no answer produced): "
                f"{', '.join(infra)}. They are not counted as passes or failures.", ""]

    out += ["## Safety numbers (deterministic, exact match on declarations)", "",
            "| Metric | Failing / n | Rate |", "|---|---|---|"]
    for label, a in [("Allergen-unsafe answer (as published)", "allergen_safe_published"),
                     ("Allergen-unsafe answer (as substituted by our own swaps)", "allergen_safe_as_substituted"),
                     ("Superseded version cited/recommended", "no_superseded_version"),
                     ("Recommended without a visible check_allergens call", "allergen_tool_called"),
                     ("Citation missing its version / invalid", "cites_with_version")]:
        ok, tot, _ = _assert_rate(rows, a)
        out.append(f"| {label} | {tot - ok} / {tot} | {(100 * (tot - ok) / tot) if tot else 0:.1f}% |")
    answered = [r for r in rows if not r["refused"]]
    inline = sum(1 for r in answered if assertions.inline_citations(r["answer"]))
    out.append(f"| Answer prose without an inline [recipe@version] (informational, not pass/fail) "
               f"| {len(answered) - inline} / {len(answered)} | "
               f"{(100 * (len(answered) - inline) / len(answered)) if answered else 0:.1f}% |")
    ok_p = {r["case_id"] for r in rows if r["assertions"].get("allergen_safe_published", {}).get("pass")}
    flipped = [r["case_id"] for r in rows if r["case_id"] in ok_p
               and not r["assertions"].get("allergen_safe_as_substituted", {}).get("pass", True)]
    out += ["", f"Cases that pass the published-recipe check but FAIL once the check runs on the recipe "
                f"as substituted: **{len(flipped)}** {flipped}", ""]

    out += ["## Pass rate by category", "", "| Category | Pass | n | Rate |", "|---|---|---|---|"]
    for cat in sorted({r["category"] for r in rows}):
        rs = [r for r in rows if r["category"] == cat]
        ck, cn, cp = _rate(rs)
        out.append(f"| {cat} | {ck} | {cn} | {cp:.0f}% |")

    out += ["", "## Allergy cases, one by one", "",
            "The hostile question is 'which cases have an allergy in them and what do they score', not the average.", "",
            "| Case | Allergies | Pass | Failed assertions | Trace |", "|---|---|---|---|---|"]
    for r in rows:
        if r["allergies"]:
            failed = [a for a, v in r["assertions"].items() if not v["pass"]]
            out.append(f"| {r['case_id']} | {', '.join(r['allergies'])} | {'PASS' if r['system_pass'] else 'FAIL'} "
                       f"| {', '.join(failed) or '-'} | `{r['trace_id'][:12]}` |")

    tk, tn, tp = _rate(rows, lambda r: r["trajectory"]["passed"])
    both = sum(1 for r in rows if r["system_pass"] and r["trajectory"]["passed"])
    out_only = sum(1 for r in rows if r["system_pass"] and not r["trajectory"]["passed"])
    traj_only = sum(1 for r in rows if not r["system_pass"] and r["trajectory"]["passed"])
    neither = n - both - out_only - traj_only
    out += ["", "## Trajectory (week 8 method on the integrated agent)", "",
            f"Tool-choice accuracy (all required tools called): **{tk}/{tn} = {tp:.1f}%**  ",
            f"Outcome pass rate {p:.1f}% vs trajectory pass rate {tp:.1f}%: **gap {p - tp:+.1f} points**", "",
            "| | trajectory ok | trajectory wrong |", "|---|---|---|",
            f"| outcome pass | {both} | {out_only} (right answer, wrong path) |",
            f"| outcome fail | {traj_only} (right path, wrong answer) | {neither} |", ""]
    missing = {}
    for r in rows:
        for m in r["trajectory"]["missing"]:
            missing[m] = missing.get(m, 0) + 1
    if missing:
        out.append("Most-skipped required tools: " + ", ".join(f"`{k}` x{v}" for k, v in
                                                              sorted(missing.items(), key=lambda x: -x[1])))

    judged = [r for r in rows if r["judge"]]
    jk = sum(1 for r in judged if r["judge"]["verdict"] == "pass")
    ak, an, ap = _rate(rows, lambda r: r["assertions_passed"])
    out += ["", "## Judge", "",
            f"Pass on deterministic assertions alone: **{ak}/{an} = {ap:.1f}%**. The headline system pass "
            "above also requires the judge, which is NOT yet validated against hand labels on these "
            "outputs, so read both numbers.", ""]
    out += [f"Judge (`{config.JUDGE_MODEL}`, grounding + answers-the-question only, never allergens) ran on "
            f"{len(judged)} cases that passed every assertion: {jk} pass.",
            "Judge agreement with hand labels is computed by `python run.py judge <this run>.jsonl` "
            "after `python run.py label <this run>.jsonl`.", ""]

    costs = [r["cost_usd"] for r in rows if r["cost_usd"]]
    lats = sorted(r["latency_ms"] for r in rows if r["latency_ms"])
    if costs and lats:
        out += ["## Cost and latency (eval traffic)", "",
                f"Mean cost/query ${statistics.mean(costs):.6f}, median ${statistics.median(costs):.6f}, "
                f"max ${max(costs):.6f}. Latency p50 {lats[len(lats) // 2] / 1000:.1f} s, "
                f"p95 {lats[min(len(lats) - 1, int(0.95 * len(lats)))] / 1000:.1f} s "
                "(includes Groq rate-limit waits).", ""]

    out += ["## What this suite does NOT cover", ""] + [f"- {x}" for x in NOT_COVERED] + [""]

    out += ["## Every case", "", "| Case | Category | Pass | Traj | Failed assertions |", "|---|---|---|---|---|"]
    for r in rows:
        failed = [f"{a} ({v['detail'][:60]})" for a, v in r["assertions"].items() if not v["pass"]]
        out.append(f"| {r['case_id']} | {r['category']} | {'PASS' if r['system_pass'] else 'FAIL'} | "
                   f"{'ok' if r['trajectory']['passed'] else 'missing ' + ','.join(r['trajectory']['missing'])} | "
                   f"{'; '.join(failed) or '-'} |")
    return "\n".join(out) + "\n"
