"""
logq - search the request log. This is the tool the support drill is run with.

Slices (combine as many as you like):
    --since 7d / --until 2026-10-05     time
    --user u1234                        user
    --prompt-version v1                 prompt version
    --input-type dietary_swap           input type (see diet_rules.classify_input)
    --cost-top 10 / --latency-top 10    cost / latency outliers
    --text dairy --in answer            free text, in the query, the answer, or both
    --flag dairy_violation              answer-side index (log schema 2 only)

Examples:
    python logq.py find --since 7d --input-type dietary_swap --text dairy
    python logq.py find --cost-top 5
    python logq.py show 3f2a91 --out trace.json
    python logq.py stats
    python logq.py reindex          # backfill output_tags into old records

Every `find` is appended to logs/search_history.jsonl so drill.py can tell
which slice actually surfaced the planted answer.
"""
import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import config
import diet_rules
from tracing import read_logs, write_logs

IST = timezone(timedelta(hours=5, minutes=30))


def parse_when(value):
    """'7d', '36h', '2026-10-01' or a full ISO timestamp -> aware datetime."""
    now = datetime.now(timezone.utc)
    m = re.fullmatch(r"(\d+)([dh])", value)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return now - (timedelta(days=n) if unit == "d" else timedelta(hours=n))
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=IST)


def slices_used(args):
    used = []
    if args.since or args.until:
        used.append("time")
    if args.user:
        used.append("user")
    if args.prompt_version:
        used.append("prompt_version")
    if args.input_type:
        used.append("input_type")
    if args.cost_top or args.latency_top:
        used.append("cost_outlier")
    if args.text:
        used.append(f"text({args.where})")
    if args.flag:
        used.append(f"output_index({args.flag})")
    return used


def find(records, args):
    hits = records
    if args.since:
        since = parse_when(args.since)
        hits = [r for r in hits if datetime.fromisoformat(r["ts"]) >= since]
    if args.until:
        until = parse_when(args.until)
        hits = [r for r in hits if datetime.fromisoformat(r["ts"]) <= until]
    if args.user:
        hits = [r for r in hits if r["user_id"] == args.user]
    if args.prompt_version:
        hits = [r for r in hits if r["prompt_version"] == args.prompt_version]
    if args.input_type:
        wanted = set(args.input_type.split(","))
        hits = [r for r in hits if r["input_type"] in wanted]
    if args.text:
        needle = diet_rules.normalize(args.text)
        fields = {"query": ["query"], "answer": ["answer"], "both": ["query", "answer"]}[args.where]
        hits = [r for r in hits
                if any(needle in diet_rules.normalize(r.get(f) or "") for f in fields)]
    if args.flag:
        missing = [r for r in hits if "output_tags" not in r]
        if missing:
            sys.exit(f"{len(missing)} records have no output_tags (log schema 1). "
                     f"Run `python logq.py reindex` first.")
        hits = [r for r in hits if r["output_tags"].get(args.flag)]
    if args.cost_top:
        hits = sorted(hits, key=lambda r: r["totals"]["cost_usd"], reverse=True)[:args.cost_top]
    if args.latency_top:
        hits = sorted(hits, key=lambda r: r["totals"]["latency_ms"], reverse=True)[:args.latency_top]
    return hits


def print_rows(hits, full=False):
    for r in hits:
        ts = datetime.fromisoformat(r["ts"]).astimezone(IST).strftime("%a %d %b %H:%M")
        answer = (r.get("answer") or f"[{r['status']}] {r.get('error')}").replace("\n", " ")
        if not full:
            answer = answer[:110]
        print(f"{ts}  {r['trace_id'][:8]}  {r['user_id']:<6} {r['input_type']:<13} "
              f"{r['prompt_version']}  ${r['totals']['cost_usd']:.6f} {r['totals']['latency_ms']:>7.0f}ms")
        print(f"    Q: {r['query']}")
        print(f"    A: {answer}")


def cmd_find(args):
    records = read_logs()
    hits = find(records, args)
    print_rows(hits[: args.limit], full=args.full)
    print(f"\n{len(hits)} of {len(records)} requests matched"
          + (f" (showing {args.limit})" if len(hits) > args.limit else ""))

    config.SEARCH_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.SEARCH_HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "command": "python logq.py " + " ".join(sys.argv[1:]),
            "slices": slices_used(args),
            "matched": len(hits),
            "trace_ids": [r["trace_id"] for r in hits],
        }) + "\n")


def lookup(trace_prefix, records=None):
    records = records if records is not None else read_logs()
    matches = [r for r in records if r["trace_id"].startswith(trace_prefix)]
    if not matches:
        sys.exit(f"no trace starts with {trace_prefix}")
    if len(matches) > 1:
        sys.exit(f"{trace_prefix} is ambiguous ({len(matches)} traces), give more characters")
    return matches[0]


def cmd_show(args):
    rec = lookup(args.trace_id)
    text = json.dumps(rec, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"wrote {args.out}")
    else:
        print(text)


def cmd_stats(args):
    records = read_logs()
    if not records:
        sys.exit("log is empty")
    days = Counter(datetime.fromisoformat(r["ts"]).astimezone(IST).strftime("%a %d %b") for r in records)
    print(f"{len(records)} requests, {len({r['user_id'] for r in records})} users\n")
    print("per day:     ", dict(sorted(days.items(), key=lambda kv: kv[0][4:])))
    print("input_type:  ", dict(Counter(r["input_type"] for r in records).most_common()))
    print("prompt:      ", dict(Counter(r["prompt_version"] for r in records)))
    print("status:      ", dict(Counter(r["status"] for r in records)))
    print("fallbacks:   ", sum(r["fallback_used"] for r in records))
    costs = sorted(r["totals"]["cost_usd"] for r in records)
    lat = sorted(r["totals"]["latency_ms"] for r in records)
    pct = lambda xs, p: xs[min(len(xs) - 1, int(p * len(xs)))]
    print(f"cost/request: mean ${sum(costs)/len(costs):.6f}  p50 ${pct(costs, .5):.6f}  "
          f"p95 ${pct(costs, .95):.6f}  max ${costs[-1]:.6f}")
    print(f"latency:      p50 {pct(lat, .5):.0f}ms  p95 {pct(lat, .95):.0f}ms  max {lat[-1]:.0f}ms")


def cmd_reindex(args):
    """Backfill output_tags into every record (log schema 1 -> 2).

    This is the bonus fix: index what the app SAID, not just what the user
    asked. New requests get the field at write time once LOG_SCHEMA = 2.
    """
    records = read_logs()
    for r in records:
        r["output_tags"] = diet_rules.output_tags(r["query"], r.get("answer") or "")
        r["log_schema"] = max(r.get("log_schema", 1), 2)
    write_logs(records)
    flagged = sum(r["output_tags"]["dairy_violation"] for r in records)
    print(f"reindexed {len(records)} records, {flagged} flagged dairy_violation")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("find")
    f.add_argument("--since")
    f.add_argument("--until")
    f.add_argument("--user")
    f.add_argument("--prompt-version")
    f.add_argument("--input-type", help="comma-separated, e.g. swap,dietary_swap")
    f.add_argument("--text")
    f.add_argument("--in", dest="where", choices=["query", "answer", "both"], default="both")
    f.add_argument("--flag", help="output_tags key, e.g. dairy_violation (schema 2)")
    f.add_argument("--cost-top", type=int)
    f.add_argument("--latency-top", type=int)
    f.add_argument("--limit", type=int, default=40)
    f.add_argument("--full", action="store_true", help="print whole answers")
    f.set_defaults(func=cmd_find)

    s = sub.add_parser("show")
    s.add_argument("trace_id", help="full id or a unique prefix")
    s.add_argument("--out")
    s.set_defaults(func=cmd_show)

    sub.add_parser("stats").set_defaults(func=cmd_stats)
    sub.add_parser("reindex").set_defaults(func=cmd_reindex)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
