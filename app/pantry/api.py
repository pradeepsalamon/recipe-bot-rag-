"""
HTTP API for the web chat (frontend/). Same path as the CLI: service.answer.

    POST /api/chat           {question, session_id?} -> NDJSON stream of events
    GET  /api/recipes/{key}  one recipe-version, as stored in data/recipes.json
    GET  /api/health         tools discovered, release, cache flag

One MCP registry is opened at startup and shared by every request, so the
MCP server process is not respawned per question. Events on the stream:

    {"type": "tool", "name", "args", "summary"}   each tool call as it returns
    {"type": "validator", "summary"}             a repair turn (v2)
    {"type": "final", ...}                       the answer, citations, trace id, cost
    {"type": "error", "message"}                 invalid question or crash
"""
import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import config, corpus, service
from .mcp_client import McpToolRegistry

_state = {}


@asynccontextmanager
async def lifespan(_app):
    async with McpToolRegistry() as reg:
        _state["registry"] = reg
        yield
    _state.clear()


app = FastAPI(title="Pantry-to-Plate API", lifespan=lifespan)


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None


def _citation(key):
    r = corpus.get_by_key(key)
    if r is None:
        return {"key": key, "title": None, "status": "invalid"}
    current = corpus.current_version(r["recipe_id"])
    return {"key": key, "title": r["title"], "status": r["status"],
            "current_key": current and corpus.key(current["recipe_id"], current["version"])}


def _final_event(res):
    final, rec = res["final"], res["record"]
    return {
        "type": "final",
        "answer": final["answer"],
        "citations": [_citation(c) for c in final["citations"]],
        "refused": bool(final.get("refused")),
        "cached": bool(final.get("cached")),
        "trace_id": rec["trace_id"],
        "latency_ms": rec["latency_ms"],
        "tokens_in": rec["tokens_in"],
        "tokens_out": rec["tokens_out"],
        "cost_usd": rec["cost_usd"],
        "terminated_by": rec["terminated_by"],
    }


def _line(event):
    return json.dumps(event, ensure_ascii=False) + "\n"


@app.post("/api/chat")
async def chat(req: ChatRequest):
    try:
        service.validate(req.question)
    except service.InvalidQuestion as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    queue = asyncio.Queue()

    def on_event(kind, name, args, summary):
        if kind == "validator":
            queue.put_nowait({"type": "validator", "summary": summary})
        else:
            queue.put_nowait({"type": "tool", "name": name, "args": args, "summary": summary})

    async def work():
        try:
            res = await service.answer(req.question, _state["registry"], source="web",
                                       session_id=req.session_id, on_event=on_event)
            queue.put_nowait(_final_event(res))
        except Exception as exc:
            queue.put_nowait({"type": "error", "message": f"{type(exc).__name__}: {exc}"[:300]})
        queue.put_nowait(None)

    async def stream():
        task = asyncio.create_task(work())
        try:
            while (event := await queue.get()) is not None:
                yield _line(event)
        finally:
            await task

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.get("/api/recipes/{key}")
def recipe(key: str):
    r = corpus.get_by_key(key)
    if r is None:
        raise HTTPException(status_code=404, detail=f"No recipe {key}")
    return {**r, **_citation(key)}


@app.get("/api/health")
def health():
    reg = _state.get("registry")
    return {"status": "ok" if reg else "starting", "release": config.RELEASE,
            "model": config.AGENT_MODEL, "cache": config.CACHE["enabled"],
            "tools": sorted(reg.tools) if reg else []}


def serve(port=8000):
    import uvicorn
    # no reload/workers: on Windows that switches uvicorn to a selector loop,
    # which cannot spawn the MCP server subprocess
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
