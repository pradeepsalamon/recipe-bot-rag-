"""
Run the whole live suite (suite.json + every evals/cases/*.json) against one
release and print pass counts, overall and by mode.

    python evals/run_suite.py --release v1 --out evals/results/suite_v1_RED.txt
    python evals/run_suite.py --release v2 --out evals/results/suite_v2_GREEN.txt

    # ablation: v2 prompt with v1 retrieval, to see which layer did the work
    python evals/run_suite.py --release v2 --no-guard --out evals/results/ablation_v2_prompt_only.txt

Exit code is 1 if anything failed, so it can gate a deploy.
Eval requests are logged to logs/eval_runs.jsonl, never the production log.
"""
import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import diet_rules
import pipeline

EVAL_DIR = Path(__file__).resolve().parent
CITATION = re.compile(r"\[(chunk_[0-9a-f]{8})\]")


def load_cases(suite_only=False):
    suite = json.loads((EVAL_DIR / "suite.json").read_text(encoding="utf-8"))
    cases = [dict(c, origin="suite.json") for c in suite["cases"]]
    if suite_only:
        return cases
    for path in sorted((EVAL_DIR / "cases").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cases += [dict(c, origin=path.name) for c in data["cases"]]
    return cases


def check(case, rec):
    """Return a list of failure reasons (empty list = pass)."""
    checks = case["checks"]
    answer = diet_rules.normalize(rec["answer"] or "")
    context = set(rec["retrieved_context_ids"]) | set(rec["tool_context_ids"])
    fails = []

    if rec["status"] != "ok":
        return [f"request errored: {rec['error']}"]

    for pattern in checks.get("answer_matches_all", []):
        if not re.search(pattern, answer):
            fails.append(f"missing /{pattern}/")
    if "answer_matches_any" in checks and not any(re.search(p, answer) for p in checks["answer_matches_any"]):
        fails.append(f"none of {checks['answer_matches_any']}")
    for pattern in checks.get("answer_not_matches", []):
        if re.search(pattern, answer):
            fails.append(f"forbidden /{pattern}/")

    if "refusal" in checks:
        refused = bool(diet_rules.REFUSAL.search(answer))
        if refused != checks["refusal"]:
            fails.append("refused" if refused else "should have refused")

    if checks.get("cites_context"):
        cited = set(CITATION.findall(rec["answer"] or ""))
        if not cited:
            fails.append("no [chunk_id] citation")
        elif cited - context:
            fails.append(f"cites chunks it was never given: {sorted(cited - context)}")

    if "context_includes_any" in checks and not context & set(checks["context_includes_any"]):
        fails.append(f"none of {checks['context_includes_any']} reached the prompt")

    if checks.get("dairy_safe"):
        reason = diet_rules.dairy_violation(case["query"], rec["answer"] or "")
        if reason:
            fails.append(f"dairy: {reason}")

    return fails


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", choices=sorted(config.RELEASES), required=True)
    parser.add_argument("--no-guard", action="store_true", help="force dietary_guard off (ablation)")
    parser.add_argument("--suite-only", action="store_true",
                        help="skip evals/cases/ (shows the suite as it was before the new case)")
    parser.add_argument("--out", help="also write the report to this file")
    parser.add_argument("--pause", type=float, default=4.0, help="seconds between calls (Groq TPM)")
    args = parser.parse_args()

    cases = load_cases(args.suite_only)
    _, prompt_sha = pipeline.load_prompt(args.release)
    guard = False if args.no_guard else config.RELEASES[args.release]["dietary_guard"]

    lines = [
        f"run at     : {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"release    : {args.release} (prompt sha {prompt_sha}, dietary_guard={guard})",
        f"model      : {config.PRIMARY_MODEL}",
        f"cases      : {len(cases)} ({sum(c['origin'] == 'suite.json' for c in cases)} suite + "
        f"{sum(c['origin'] != 'suite.json' for c in cases)} from evals/cases/)",
        "",
    ]
    print("\n".join(lines), flush=True)

    by_mode = defaultdict(lambda: [0, 0])
    passed = 0
    for case in cases:
        rec = pipeline.answer(case["query"], user_id="eval", release=args.release,
                              source="eval", log_path=config.EVAL_LOG_FILE,
                              dietary_guard_override=False if args.no_guard else None)
        fails = check(case, rec)
        ok = not fails
        passed += ok
        by_mode[case["mode"]][0] += ok
        by_mode[case["mode"]][1] += 1

        line = f"{'PASS' if ok else 'FAIL'}  {case['id']:<34} [{case['mode']}]"
        if fails:
            line += "\n      " + "; ".join(fails)
            line += f"\n      answer: {(rec['answer'] or '').strip()[:220]!r}"
            line += f"\n      context: {rec['retrieved_context_ids'] + rec['tool_context_ids']}  trace: {rec['trace_id']}"
        print(line, flush=True)
        lines.append(line)
        time.sleep(args.pause)

    summary = ["", "pass rate by mode:"]
    for mode, (ok, total) in sorted(by_mode.items()):
        summary.append(f"  {mode:<45} {ok}/{total}")
    summary += ["", f"SUITE: {passed}/{len(cases)} passed  ({'GREEN' if passed == len(cases) else 'RED'})"]
    print("\n".join(summary))
    lines += summary

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    sys.exit(0 if passed == len(cases) else 1)


if __name__ == "__main__":
    main()
