"""
`python run.py doctor`: everything a stranger needs to know before the first
question, checked in order, each with the fix when it fails.
"""
import asyncio
import importlib
import json
import os
import sys
import time

from . import config

OK, WARN, FAIL = "ok  ", "warn", "FAIL"


def _line(status, what, detail=""):
    print(f"[{status}] {what}" + (f"  - {detail}" if detail else ""))
    return status


def main(online=False):
    results = []
    v = sys.version_info
    results.append(_line(OK if v >= (3, 11) else FAIL, f"Python {v.major}.{v.minor}",
                         "" if v >= (3, 11) else "needs 3.11+ (built on 3.12)"))

    for mod in ("dotenv", "groq", "mcp", "chromadb", "langchain_chroma", "onnxruntime", "rank_bm25"):
        try:
            importlib.import_module(mod)
            results.append(_line(OK, f"import {mod}"))
        except Exception as exc:
            results.append(_line(FAIL, f"import {mod}", f"{type(exc).__name__}; run pip install -r requirements.txt"))
    try:
        from mcp.server.mcpserver import MCPServer  # noqa: F401
        results.append(_line(OK, "mcp 2.x API (MCPServer)"))
    except Exception:
        results.append(_line(FAIL, "mcp 2.x API (MCPServer)", "pip install 'mcp>=2.2'"))

    results.append(_line(OK if os.getenv("GROQ_API_KEY") else FAIL, "GROQ_API_KEY",
                         "" if os.getenv("GROQ_API_KEY") else "copy .env.example to .env and paste your key"))

    try:
        from . import corpus, safety
        n = len(corpus.all_recipes())
        for p in (config.SUBSTITUTIONS_FILE, config.FOOD_SAFETY_FILE):
            json.loads(p.read_text(encoding="utf-8"))
        conflicts = safety.integrity_report()
        results.append(_line(OK, f"data: {n} recipe-versions, substitutions, food-safety chart"))
        if conflicts:
            results.append(_line(WARN, f"{len(conflicts)} declaration/ingredient conflict(s)",
                                 "see python run.py check-data (known: rasam)"))
    except Exception as exc:
        results.append(_line(FAIL, "data files", f"{type(exc).__name__}: {exc}"))

    from . import retriever
    results.append(_line(OK if retriever.index_exists() else WARN, "search index",
                         "" if retriever.index_exists() else "will be built on the first ask (about a minute)"))

    try:
        from .mcp_client import McpToolRegistry

        async def probe():
            t0 = time.perf_counter()
            async with McpToolRegistry() as reg:
                tools = sorted(reg.tools)
                r = await reg.call("check_allergens", {"recipe_id": "shortbread", "version": "reformulated-2025",
                                                       "allergies": ["nuts"]})
            return tools, r, time.perf_counter() - t0

        tools, r, secs = asyncio.run(probe())
        good = len(tools) >= 6 and r.get("verdict") == "UNSAFE"
        results.append(_line(OK if good else FAIL, f"MCP server: {len(tools)} tools discovered, "
                             f"allergen check answers, {secs:.1f}s", "" if good else f"got {r}"))
    except Exception as exc:
        results.append(_line(FAIL, "MCP server", f"{type(exc).__name__}: {str(exc)[:150]}"))

    if online and os.getenv("GROQ_API_KEY"):
        try:
            from . import llm
            from .tracing import Span
            sp = Span("doctor", "llm")
            llm.chat([{"role": "user", "content": "Reply with the single word: ok"}], sp)
            results.append(_line(OK, f"Groq {config.AGENT_MODEL} reachable",
                                 f"{sp.attrs.get('ratelimit_remaining_requests')} requests left today"))
        except Exception as exc:
            results.append(_line(FAIL, "Groq call", f"{type(exc).__name__}: {str(exc)[:150]}"))

    results.append(_line(OK, f"semantic cache {'ON' if config.CACHE['enabled'] else 'off'} (PANTRY_CACHE)"))
    if config.LANGSMITH["enabled"]:
        has_key = bool(os.getenv("LANGSMITH_API_KEY"))
        results.append(_line(OK if has_key else WARN, "LangSmith mirror ON",
                             "" if has_key else "PANTRY_LANGSMITH=1 but LANGSMITH_API_KEY is missing: mirror inactive"))
    else:
        results.append(_line(OK, "LangSmith mirror off (PANTRY_LANGSMITH)"))

    failed = results.count(FAIL)
    print(f"\n{'All good.' if not failed else f'{failed} problem(s) to fix.'}")
    return 1 if failed else 0
