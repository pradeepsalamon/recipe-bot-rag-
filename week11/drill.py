"""
The support drill, timed by the tooling instead of by memory.

Squadmate (on the finder's machine, finder looks away):
    python drill.py plant
        -> sends dairy-free swap questions through the LIVE v1 pipeline until
           one genuinely comes back with a non-dairy-free answer, back-dates
           it to a random moment last week, hides it in the log, and stores
           only a sha256 of its trace id. Nothing is hand-written: the bad
           answer is a real model output with real spans, tokens and cost.

Finder:
    python drill.py start --finder "Pradeep" --timer "<squadmate name>"
    python logq.py find ...            (as many searches as it takes)
    python drill.py found <trace_id>   -> stops the clock, checks the hash

Then:
    python drill.py report             -> writes drill.md from the results
    python drill.py reset              -> removes planted records (for a rehearsal)
"""
import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timedelta, timezone

import config
import diet_rules
from tracing import read_logs, write_logs

STATE_FILE = config.LOG_DIR / "drill_state.json"
RESULTS_FILE = config.LOG_DIR / "drill_results.jsonl"
DRILL_MD = config.WEEK_DIR / "drill.md"

COMPLAINT = ("Someone said it recommended a dairy-free substitution that "
             "wasn't dairy-free, sometime last week.")

# Phrasings that tend to trip the v1 pipeline. plant() keeps trying until the
# live answer really fails the dairy check, so the plant is never fake.
DAIRY_TRAPS = [
    "I'm cooking Ven Pongal for a dairy-free guest. What can I fry the cashews in instead of butter?",
    "Dairy-free friend coming over - what should I fry the cashews in for pongal instead of butter?",
    "Making pongal dairy-free: what fat for the cashews instead of butter?",
    "I'm dairy-free. Is the Rasam recipe safe for me as written?",
    "My daughter can't have dairy. What should I temper Ven Pongal in instead of butter?",
    "Lactose intolerant guest - which fat do I use for the pongal tempering instead of butter?",
]


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"planted": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def mmss(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def cmd_plant(args):
    import pipeline  # heavy import, only the planter needs it

    records = read_logs()
    if not records:
        sys.exit("log is empty, run simulate_traffic.py first")

    rng = random.Random()
    users = sorted({r["user_id"] for r in records})
    first = min(datetime.fromisoformat(r["ts"]) for r in records)
    last = max(datetime.fromisoformat(r["ts"]) for r in records)

    questions = [args.query] if args.query else rng.sample(DAIRY_TRAPS, len(DAIRY_TRAPS))
    for question in questions:
        ts = first + (last - first) * rng.random()
        rec = pipeline.answer(question, user_id=rng.choice(users), release="v1",
                              ts=ts.replace(microsecond=0), source="simulated_traffic",
                              log_path=False)
        reason = diet_rules.dairy_violation(question, rec["answer"] or "")
        if reason:
            break
        print(f"  v1 answered this one safely, trying another phrasing ({question[:50]}...)")
    else:
        sys.exit("v1 gave safe answers to every phrasing this time - nothing planted. Run again.")

    write_logs(records + [rec])
    state = load_state()
    state["planted"].append({
        "drill": len(state["planted"]) + 1,
        "trace_sha256": sha(rec["trace_id"]),
        "planted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "log_schema_at_plant": config.LOG_SCHEMA,
    })
    state.pop("started", None)
    save_state(state)

    print("\nPlanted. Hand the finder ONLY this complaint:\n")
    print(f'    "{COMPLAINT}"\n')
    print(f"(squadmate only - answer key: {rec['trace_id']}, why it is bad: {reason})")


def cmd_start(args):
    state = load_state()
    if not state["planted"]:
        sys.exit("nothing planted yet - squadmate runs `python drill.py plant` first")
    state["started"] = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "finder": args.finder,
        "timer": args.timer,
        "drill": state["planted"][-1]["drill"],
    }
    save_state(state)
    print(f"Clock running for drill {state['started']['drill']}. The complaint:\n\n    \"{COMPLAINT}\"")


def first_search_that_found(trace_id, since):
    """Walk the search history since the clock started; return the searches
    made and the first one whose results contained the trace."""
    if not config.SEARCH_HISTORY_FILE.exists():
        return [], None
    steps = []
    for line in config.SEARCH_HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry["at"] < since:
            continue
        steps.append(entry)
        if trace_id in entry["trace_ids"]:
            return steps, entry
    return steps, None


def cmd_found(args):
    state = load_state()
    started = state.get("started")
    if not started:
        sys.exit("clock isn't running - `python drill.py start` first")

    stopped = datetime.now(timezone.utc)
    elapsed = (stopped - datetime.fromisoformat(started["at"])).total_seconds()

    from logq import lookup
    rec = lookup(args.trace_id)
    planted = next(p for p in state["planted"] if p["drill"] == started["drill"])
    correct = sha(rec["trace_id"]) == planted["trace_sha256"]
    steps, hit = first_search_that_found(rec["trace_id"], started["at"])

    result = {
        "drill": started["drill"],
        "finder": started["finder"],
        "timer": started["timer"],
        "started_at": started["at"],
        "stopped_at": stopped.isoformat(timespec="seconds"),
        "seconds": round(elapsed),
        "mm_ss": mmss(elapsed),
        "trace_id": rec["trace_id"],
        "correct": correct,
        "log_schema": planted["log_schema_at_plant"],
        "found_by_slices": hit["slices"] if hit else None,
        "found_by_command": hit["command"] if hit else None,
        "searches": [{"command": s["command"], "slices": s["slices"], "matched": s["matched"]} for s in steps],
        "missing_field": args.missing_field,
    }
    with open(RESULTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(result) + "\n")
    state.pop("started")
    save_state(state)

    if correct:
        print(f"Correct - drill {result['drill']} found in {result['mm_ss']} "
              f"via {', '.join(result['found_by_slices'] or ['?'])}")
    else:
        reason = diet_rules.dairy_violation(rec["query"], rec.get("answer") or "")
        print(f"Not the planted trace (clock stopped at {result['mm_ss']}).")
        if reason:
            print(f"It IS a genuine dairy failure though ({reason}) - worth an eval case.")
    if elapsed > 300 and not args.missing_field:
        print("Over 5:00 - re-run `found` with --missing-field \"<log field whose absence cost the time>\"")
    cmd_report(args)


def cmd_report(args):
    if not RESULTS_FILE.exists():
        sys.exit("no drill results yet")
    results = [json.loads(l) for l in RESULTS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]

    out = ["# Support drill - \"the dairy-free swap that wasn't\"", "",
           f"Complaint given to the finder, word for word: *\"{COMPLAINT}\"*", "",
           "Times come from `drill.py` (clock starts on `start`, stops on `found`); the slice is",
           "read from `logs/search_history.jsonl`, i.e. the first `logq.py find` whose results",
           "contained the planted trace. Correctness is checked against a sha256 the squadmate's",
           "`plant` stored, so the finder never sees the answer key.", "",
           "| Drill | Finder | Timed by | Log schema | Time-to-find | Slice that found it | Correct |",
           "|---|---|---|---|---|---|---|"]
    for r in results:
        out.append(f"| {r['drill']} | {r['finder']} | {r['timer']} | v{r['log_schema']} | "
                   f"**{r['mm_ss']}** | {', '.join(r['found_by_slices'] or ['-'])} | "
                   f"{'yes' if r['correct'] else 'NO'} |")

    for r in results:
        out += ["", f"## Drill {r['drill']} - {r['mm_ss']}", "",
                f"- Found trace: `{r['trace_id']}`",
                f"- Winning search: `{r['found_by_command']}`",
                f"- Searches made: {len(r['searches'])}", ""]
        for i, s in enumerate(r["searches"], 1):
            out.append(f"  {i}. `{s['command']}` -> {s['matched']} matches")
        if r["seconds"] > 300:
            out += ["", f"**Over 5:00.** Missing log field that cost the time: "
                        f"{r['missing_field'] or '_(fill in with `drill.py found --missing-field`)_'}"]

    if len(results) >= 2:
        a, b = results[0], results[-1]
        out += ["", "## Bonus - beating our own time", "",
                f"Drill 1: **{a['mm_ss']}** (log schema v{a['log_schema']}) -> "
                f"Drill {b['drill']}: **{b['mm_ss']}** (log schema v{b['log_schema']}).", "",
                "The field that closed the gap: `output_tags.dairy_violation` - an index on what the",
                "app *said* (dairy item named without a dairy warning, or dairy called dairy-free),",
                "computed by `diet_rules.output_tags()` at write time and backfilled with",
                "`python logq.py reindex`. One search: `python logq.py find --since 7d --flag dairy_violation`."]

    DRILL_MD.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {DRILL_MD.name}")


def cmd_reset(args):
    """Remove every planted record and the drill results (for rehearsals)."""
    state = load_state()
    hashes = {p["trace_sha256"] for p in state["planted"]}
    records = read_logs()
    kept = [r for r in records if sha(r["trace_id"]) not in hashes]
    write_logs(kept)
    for path in (STATE_FILE, RESULTS_FILE, DRILL_MD):
        if path.exists():
            path.unlink()
    print(f"removed {len(records) - len(kept)} planted record(s) and the drill results")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plant")
    p.add_argument("--query", help="squadmate's own phrasing (must actually fail on v1)")
    p.set_defaults(func=cmd_plant)

    s = sub.add_parser("start")
    s.add_argument("--finder", required=True)
    s.add_argument("--timer", required=True, help="the squadmate who planted and is timing")
    s.set_defaults(func=cmd_start)

    f = sub.add_parser("found")
    f.add_argument("trace_id")
    f.add_argument("--missing-field", help="only needed if the find took over 5:00")
    f.set_defaults(func=cmd_found)

    sub.add_parser("report").set_defaults(func=cmd_report)
    sub.add_parser("reset").set_defaults(func=cmd_reset)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
