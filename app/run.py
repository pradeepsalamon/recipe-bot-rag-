"""
Pantry-to-Plate: the single entry point.

    python run.py ask "what can I make with rice and lemons? my kid is allergic to nuts"
    python run.py chat                       # interactive
    python run.py eval                       # full suite against the integrated system
    python run.py trace <trace_id>           # one request, every span, both processes
    python run.py report                     # cost per query + what breaks at 50k/day
    python run.py serve-mcp [--http 8799]    # the MCP server on its own, for any client
    python run.py ingest                     # rebuild cards + index (ask/eval do it if missing)
    python run.py check-data                 # declaration vs ingredient-list mismatches
    python run.py test                       # pytest suite, no API calls
    python run.py doctor [--online]          # is this machine set up correctly?
    python run.py cache stats|clear          # semantic cache (PANTRY_CACHE=1 turns it on)
    python run.py langsmith check|backfill   # LangSmith mirror (PANTRY_LANGSMITH=1 turns it on)
"""
import argparse
import asyncio
import json
import os
import sys
import warnings
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
os.chdir(APP_DIR)
warnings.filterwarnings("ignore")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _load_env():
    from dotenv import load_dotenv
    # app/.env first, then the repo-level .env the weekly folders used
    load_dotenv(APP_DIR / ".env", override=False)
    load_dotenv(APP_DIR.parent / ".env", override=False)


def _ensure_index(quiet=False):
    from pantry import corpus, retriever
    if not retriever.index_exists() or not any(corpus.card_path("idli@original").parent.glob("*.md")):
        if not quiet:
            print("First run: building recipe cards and the search index (about a minute)...")
        corpus.write_cards()
        n = retriever.build_index()
        if not quiet:
            print(f"Indexed {n} chunks from {len(corpus.all_recipes())} recipe-versions.\n")


def _print_event(kind, name, args, summary):
    shown = {k: v for k, v in args.items()}
    print(f"  -> {name}({json.dumps(shown, ensure_ascii=False)})")
    print(f"     = {summary}")


def _print_result(res):
    from pantry import corpus
    final, rec = res["final"], res["record"]
    print("\n" + "=" * 70)
    print(final["answer"])
    print("=" * 70)
    if final["citations"]:
        print("Sources:")
        for c in final["citations"]:
            r = corpus.get_by_key(c)
            if r is None:
                print(f"  [{c}]  !! not in the library (invalid citation)")
                continue
            flag = "  !! SUPERSEDED" if r["status"] == "superseded" else ""
            print(f"  [{c}] {r['title']}{flag}\n      {corpus.card_path(c).relative_to(APP_DIR.parent)}")
    if final.get("refused"):
        print("(refused)")
    print(f"\ntrace {rec['trace_id']}  |  {rec['latency_ms'] / 1000:.1f} s  |  "
          f"{rec['tokens_in']}+{rec['tokens_out']} tokens  |  ${rec['cost_usd']:.6f}"
          + (f"  |  stopped: {rec['terminated_by']}" if rec["terminated_by"] else ""))
    print(f"see every span: python run.py trace {rec['trace_id'][:12]}")


async def _ask(questions, interactive=False):
    import uuid

    from pantry import config, service
    from pantry.mcp_client import McpToolRegistry

    async with McpToolRegistry() as reg:
        print(f"MCP tools discovered at runtime: {', '.join(sorted(reg.tools))}  (+ local: scale_recipe)"
              f"{'  | semantic cache ON' if config.CACHE['enabled'] else ''}"
              f"{'  | LangSmith mirror ON' if config.LANGSMITH['enabled'] else ''}")
        session = f"s_{uuid.uuid4().hex[:8]}"
        pending = list(questions)
        while True:
            if pending:
                q = pending.pop(0)
            elif interactive:
                try:
                    q = input("\nYou: ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if q.lower() in ("", "quit", "exit"):
                    break
            else:
                break
            print(f"\nQ: {q}")
            try:
                res = await service.answer(q, reg, session_id=session, on_event=_print_event)
            except service.InvalidQuestion as exc:
                print(f"  {exc}")
                continue
            if res["final"].get("cached"):
                print(f"  (served from the semantic cache; produced by trace "
                      f"{res['record']['cache']['source_trace_id'][:12]})")
            _print_result(res)


def cmd_trace(trace_id, out=None):
    from pantry.tracing import full_trace
    rec = full_trace(trace_id)
    if rec is None:
        print(f"No trace starting with {trace_id}")
        return 1
    if out:
        Path(out).write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {out}")
    print(f"trace {rec['trace_id']}  {rec['ts']}  release={rec['release']}  prompt={rec['prompt_version']}")
    print(f"query (redacted): {rec['query']}")
    print(f"allergen codes checked: {rec['allergen_codes_checked'] or '-'}")
    spans = sorted(rec["spans"] + rec["server_spans"], key=lambda s: s["start_ts"])
    by_parent = {}
    for s in spans:
        by_parent.setdefault(s["parent_id"], []).append(s)
    print(f"\n{'span':<34}{'process':<12}{'ms':>9}{'tok in':>8}{'tok out':>8}{'cost $':>12}  detail")

    def show(s, depth):
        cost = "" if s["cost_usd"] in (None, 0) else f"{s['cost_usd']:.7f}"
        detail = s["attrs"].get("result") or s["attrs"].get("verdict") or s["attrs"].get("hits") or ""
        print(f"{'  ' * depth + s['name']:<34}{s['process']:<12}{s['latency_ms']:>9.1f}"
              f"{s['tokens_in'] or '':>8}{s['tokens_out'] or '':>8}{cost:>12}  {str(detail)[:60]}")
        for child in by_parent.get(s["span_id"], []):
            show(child, depth + 1)

    for s in by_parent.get(None, []):
        show(s, 0)
    orphans = [s for s in rec["server_spans"] if s["parent_id"] not in {x["span_id"] for x in spans}]
    for s in orphans:
        show(s, 0)
    print(f"\ntotal {rec['latency_ms']:.0f} ms, ${rec['cost_usd']:.7f}, "
          f"{len(rec['spans'])} client spans + {len(rec['server_spans'])} MCP-server spans, one trace id")
    return 0


def _run_tests(pytest_args):
    try:
        import pytest
    except ImportError:
        print("pytest is not installed: pip install -r requirements-dev.txt")
        return 1
    return pytest.main(["-q", str(APP_DIR / "tests"), *pytest_args])


def main():
    if sys.argv[1:2] == ["test"]:
        # before argparse: pytest flags like -k / -x must pass through untouched
        return _run_tests(sys.argv[2:])
    p = argparse.ArgumentParser(description="Pantry-to-Plate assistant")
    sub = p.add_subparsers(dest="cmd")
    a = sub.add_parser("ask")
    a.add_argument("question", nargs="+")
    sub.add_parser("chat")
    sub.add_parser("ingest")
    s = sub.add_parser("serve-mcp")
    s.add_argument("--http", type=int, default=None, help="serve streamable HTTP on this port")
    t = sub.add_parser("trace")
    t.add_argument("trace_id")
    t.add_argument("--out", default=None)
    e = sub.add_parser("eval")
    e.add_argument("--cases", default=None, help="comma-separated case ids")
    e.add_argument("--category", default=None)
    e.add_argument("--label", default="", help="name for this run, e.g. before_fix")
    e.add_argument("--no-judge", action="store_true", help="assertions + trajectory only")
    e.add_argument("--fail-on-unsafe", action="store_true",
                   help="exit 1 if any answer is allergen-unsafe (for CI)")
    j = sub.add_parser("judge")
    j.add_argument("run_file", help="evals/results/<run>.jsonl")
    sub.add_parser("label").add_argument("run_file")
    rs = sub.add_parser("rescore", help="re-apply current assertions to a run's stored answers")
    rs.add_argument("run_file")
    rs.add_argument("--merge", nargs="*", default=[],
                    help="re-run files whose answers replace this run's INFRA rows")
    rs.add_argument("--no-judge", action="store_true")
    sub.add_parser("report")
    sub.add_parser("check-data")
    sub.add_parser("test", help="pytest suite; extra args go to pytest, e.g. test -k cache")
    d = sub.add_parser("doctor")
    d.add_argument("--online", action="store_true", help="also make one tiny Groq call (~$0.00001)")
    c = sub.add_parser("cache")
    c.add_argument("action", choices=["stats", "clear"])
    ls = sub.add_parser("langsmith")
    ls.add_argument("action", choices=["check", "backfill"])
    ls.add_argument("--file", default="logs/requests.jsonl")
    args = p.parse_args()

    if args.cmd is None:
        p.print_help()
        return 0
    if args.cmd == "serve-mcp":
        # stdout belongs to the MCP protocol here: print nothing.
        from pantry.mcp_server import serve
        serve(args.http)
        return 0

    _load_env()
    if args.cmd == "ingest":
        from pantry import corpus, retriever
        print(f"cards: {corpus.write_cards()}  chunks: {retriever.build_index()}")
        return 0
    if args.cmd == "check-data":
        from pantry import safety
        rows = safety.integrity_report()
        print(json.dumps(rows, indent=2) if rows else "Declarations and ingredient tags agree.")
        return 0
    if args.cmd == "doctor":
        from pantry import doctor
        return doctor.main(online=args.online)
    if args.cmd == "cache":
        from pantry.cache import SemanticCache, fingerprint
        from pantry import config
        if args.action == "clear":
            # no embedder needed to clear
            print(f"cleared {SemanticCache(embed=lambda t: [0.0]).clear()} entries")
        else:
            st = SemanticCache(embed=lambda t: [0.0]).stats()
            print(f"enabled={config.CACHE['enabled']} (PANTRY_CACHE)  live entries={st['entries_live']}  "
                  f"fingerprint={st['fingerprint']}  file={st['path']}")
        return 0
    if args.cmd == "langsmith":
        from pantry import observability
        from pantry.tracing import read_jsonl
        if args.action == "check":
            print(observability.check())
            return 0
        if not os.getenv("LANGSMITH_API_KEY"):
            print("LANGSMITH_API_KEY is not set")
            return 1
        recs = read_jsonl(APP_DIR / args.file)
        print(f"sent {observability.backfill(recs)}/{len(recs)} records")
        return 0
    if args.cmd == "trace":
        return cmd_trace(args.trace_id, args.out)
    if args.cmd == "report":
        from evals import report
        return report.main()
    if args.cmd == "judge":
        from evals import judge
        return judge.main(args.run_file)
    if args.cmd == "label":
        from evals import judge
        return judge.label(args.run_file)
    if args.cmd == "rescore":
        from evals import rescore
        return rescore.rescore(args.run_file, use_judge=not args.no_judge, extra_files=args.merge)

    if not os.getenv("GROQ_API_KEY"):
        print("GROQ_API_KEY is not set. Put it in app/.env (see .env.example).")
        return 1
    _ensure_index()
    if args.cmd == "ask":
        asyncio.run(_ask([" ".join(args.question)]))
    elif args.cmd == "chat":
        asyncio.run(_ask([], interactive=True))
    elif args.cmd == "eval":
        from evals import run_evals
        return asyncio.run(run_evals.main(args.cases, args.category, args.label, not args.no_judge,
                                          args.fail_on_unsafe))
    else:
        p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
