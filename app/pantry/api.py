"""
HTTP API for the web chat (frontend/). Same path as the CLI: service.answer.

    POST /api/chat           {question, session_id?} -> NDJSON stream of events
    GET  /api/recipes/{key}  one recipe-version, as stored in data/recipes.json
    GET  /api/health         tools discovered, release, cache flag, uploads flag
    POST /api/uploads        multipart file -> NDJSON progress, then the recipes found
    GET  /api/uploads        uploaded files and their recipes
    DELETE /api/uploads/{id} remove one file and its recipes

One MCP registry is opened at startup and shared by every request, so the
MCP server process is not respawned per question. Events on the stream:

    {"type": "tool", "name", "args", "summary"}   each tool call as it returns
    {"type": "validator", "summary"}             a repair turn (v2)
    {"type": "final", ...}                       the answer, citations, trace id, cost
    {"type": "error", "message"}                 invalid question or crash
"""
import asyncio
import json
import os
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import config, corpus, service, uploads
from .mcp_client import McpToolRegistry

_state = {}


@asynccontextmanager
async def lifespan(_app):
    # A failed MCP start must not take the whole app down: /api/health then
    # reports why instead of every route answering a bare 500.
    try:
        async with McpToolRegistry() as reg:
            _state["registry"] = reg
            yield
    except Exception as exc:
        if "registry" in _state:
            raise
        _state["startup_error"] = f"MCP server failed to start: {type(exc).__name__}: {exc}"[:500]
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
            "current_key": current and corpus.key(current["recipe_id"], current["version"]),
            "source": "upload" if corpus.is_upload(r) else "library"}


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
    if "registry" not in _state:
        raise HTTPException(status_code=503, detail=_state.get("startup_error", "API is starting"))

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
    # _citation's "source" ("upload"/"library") replaces the stored source; the
    # upload details (filename, page) stay available as "upload"
    return {**r, **_citation(key), "upload": r.get("source") if corpus.is_upload(r) else None}


@app.get("/api/health")
def health():
    reg = _state.get("registry")
    if not reg and "startup_error" in _state:
        return {"status": "error", "detail": _state["startup_error"], "release": config.RELEASE}
    return {"status": "ok" if reg else "starting", "release": config.RELEASE,
            "model": config.AGENT_MODEL, "cache": config.CACHE["enabled"],
            "uploads": config.UPLOADS_ENABLED, "tools": sorted(reg.tools) if reg else []}


def _uploads_enabled():
    if not config.UPLOADS_ENABLED:
        raise HTTPException(status_code=501, detail="Uploads are only available when running locally.")


@app.post("/api/uploads")
async def upload(file: UploadFile):
    """Streams {"type":"progress","done","total"} per extraction call, then
    {"type":"done", file_id, filename, recipes, skipped, warnings, duplicate}
    or {"type":"error","message"}. Bad type/size fails fast with 400."""
    _uploads_enabled()
    data = await file.read(config.UPLOAD_LIMITS["max_bytes"] + 1)
    try:
        ext = uploads.check_file(file.filename, len(data))
    except uploads.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    fd, tmp = tempfile.mkstemp(suffix=ext)
    with os.fdopen(fd, "wb") as f:
        f.write(data)

    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()

    def on_progress(done, total):
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "progress", "done": done, "total": total})

    async def work():
        try:
            res = await asyncio.to_thread(uploads.ingest_file, tmp, file.filename, on_progress)
            queue.put_nowait({"type": "done", **res})
        except uploads.UploadError as exc:
            queue.put_nowait({"type": "error", "message": str(exc)})
        except Exception as exc:
            queue.put_nowait({"type": "error", "message": f"{type(exc).__name__}: {exc}"[:300]})
        finally:
            os.unlink(tmp)
        queue.put_nowait(None)

    async def stream():
        task = asyncio.create_task(work())
        try:
            while (event := await queue.get()) is not None:
                yield _line(event)
        finally:
            await task

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.get("/api/uploads")
def list_uploads():
    _uploads_enabled()
    return {"files": uploads.list_uploads()}


@app.delete("/api/uploads/{file_id}")
def delete_upload(file_id: str):
    _uploads_enabled()
    try:
        return uploads.delete_upload(file_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No upload {file_id}")


def serve(port=8000):
    import uvicorn
    # no reload/workers: on Windows that switches uvicorn to a selector loop,
    # which cannot spawn the MCP server subprocess
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
