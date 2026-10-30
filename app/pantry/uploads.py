"""
User uploads: a recipe doc, PDF or cookbook in, structured recipes out.

    file -> text (pypdf / python-docx / plain) -> overlapping windows
         -> LLM extraction into the recipes.json schema (prompts/extract_v1.txt)
         -> data/user_recipes.json + the user Chroma collection + cards

Uploaded recipes become ordinary corpus entries ("u_<slug>@upload"), so
search, get_recipe, scale_recipe, citations and the recipe drawer all work
on them unchanged. What they do NOT get is an allergen declaration: the
model reads a cookbook, it does not certify one. They are stored with
declared=False and safety.check_declaration answers UNDECLARED for them.

Local dev only (config.UPLOADS_ENABLED): on serverless the files would land
in a per-instance /tmp and vanish on the next cold start.

Write order matters: the index is changed BEFORE user_recipes.json, because
the file's mtime is what tells the MCP server process to reload its store.
"""
import hashlib
import json
import os
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from . import config, corpus, llm, retriever
from .tracing import Trace, append_jsonl

_PROMPT = config.APP_DIR / "prompts" / "extract_v1.txt"
_MIN_CHARS_PER_PAGE = 50    # below this a PDF page is an image, not text
_write_lock = threading.Lock()


class UploadError(ValueError):
    """Something the user can fix: wrong type, scanned PDF, no recipes."""


# --------------------------------------------------------------------------
# File -> text
# --------------------------------------------------------------------------
def extract_text(path, ext=None):
    """[(page_number, text), ...]. DOCX and plain text are one 'page'."""
    path = Path(path)
    ext = (ext or path.suffix).lower()
    if ext == ".doc":
        raise UploadError("Old .doc files are not supported: open it in Word and save as .docx.")
    if ext not in config.UPLOAD_LIMITS["extensions"]:
        raise UploadError(f"Unsupported file type {ext or '(none)'}: use PDF, DOCX, TXT or MD.")
    if ext == ".pdf":
        return _pdf_text(path)
    if ext == ".docx":
        return [(1, _docx_text(path))]
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    return [(1, text.replace("\r\n", "\n"))]


def _pdf_text(path):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise UploadError("This PDF is password-protected: remove the password and upload it again.")
        pages = [(n, page.extract_text() or "") for n, page in enumerate(reader.pages, 1)]
    except PdfReadError as exc:
        raise UploadError(f"Could not read this PDF: {exc}") from exc
    total = sum(len(t.strip()) for _, t in pages)
    if not pages or total < _MIN_CHARS_PER_PAGE * len(pages):
        raise UploadError("This PDF has (almost) no text layer; it looks scanned. Scanned PDFs need OCR, "
                          "which is not supported: upload a text PDF, DOCX or TXT instead.")
    return pages


def _docx_text(path):
    import docx
    from docx.table import Table
    blocks = []
    for item in docx.Document(path).iter_inner_content():   # paragraphs and tables, in order
        if isinstance(item, Table):
            for row in item.rows:
                cells = [c.text.strip() for c in row.cells]
                blocks.append(" | ".join(c for c in dict.fromkeys(cells) if c))   # merged cells repeat
        else:
            blocks.append(item.text)
    return "\n".join(blocks)


def windows(pages, size=None, overlap=None):
    """Paragraph-aligned windows of about `size` chars; each repeats the last
    `overlap` chars of the one before, so a recipe cut by a window edge is
    seen whole once. [{"page": first page, "text": ...}]"""
    size = size or config.UPLOAD_LIMITS["window_chars"]
    overlap = overlap if overlap is not None else config.UPLOAD_LIMITS["overlap_chars"]
    units = []
    for page, text in pages:
        for para in re.split(r"\n\s*\n", text):
            para = para.strip()
            while len(para) > size:   # a PDF page with no blank lines is one huge "paragraph"
                cut = para.rfind("\n", 0, size)
                cut = cut if cut > 0 else size
                units.append((page, para[:cut].strip()))
                para = para[cut:].strip()
            if para:
                units.append((page, para))

    out, cur, length, fresh = [], [], 0, 0
    for unit in units:
        if fresh and length + len(unit[1]) > size:
            out.append(cur)
            tail, n = [], 0
            for u in reversed(cur):
                if n + len(u[1]) > overlap:
                    break
                tail.insert(0, u)
                n += len(u[1])
            cur, length, fresh = tail, n, 0
        cur.append(unit)
        length += len(unit[1])
        fresh += 1
    if fresh:
        out.append(cur)
    return [{"page": w[0][0], "text": "\n\n".join(u[1] for u in w)} for w in out]


# --------------------------------------------------------------------------
# Text -> recipes
# --------------------------------------------------------------------------
class _Ingredient(BaseModel):
    item: str = Field(min_length=1)
    qty: float | None = None
    unit: str = ""


class _Yield(BaseModel):
    amount: float | None = None
    unit: str | None = None


class _Recipe(BaseModel):
    title: str = Field(min_length=1)
    description: str | None = ""
    cuisine: str | None = ""
    dietary_tags: list[str] = []
    yield_: _Yield = Field(default_factory=_Yield, alias="yield")
    prep_minutes: int | None = None
    cook_minutes: int | None = None
    rest_minutes: int | None = None
    oven_c: int | None = None
    ingredients: list[_Ingredient] = Field(min_length=1)
    method: list[str] = Field(min_length=1)
    notes: str | None = ""
    safety_category: str | None = None


def _parse_json(content):
    text = (content or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply")
    return json.loads(text[start:end + 1])


def extract_recipes(text, trace):
    """One LLM call over one window. Returns (valid recipes, skipped reasons)."""
    messages = [{"role": "system", "content": _PROMPT.read_text(encoding="utf-8")},
                {"role": "user", "content": text}]
    with trace.span("extract_recipes", "llm") as sp:
        reply = llm.chat(messages, sp)
        try:
            items = _parse_json(reply.content).get("recipes") or []
        except (ValueError, AttributeError) as exc:
            sp.attrs["parse_error"] = str(exc)[:200]
            return [], [f"unreadable model reply: {str(exc)[:120]}"]
        good, skipped = [], []
        for item in items if isinstance(items, list) else []:
            try:
                good.append(_Recipe.model_validate(item))
            except ValidationError as exc:
                title = item.get("title") if isinstance(item, dict) else None
                skipped.append(f"{title or 'untitled'}: {exc.error_count()} invalid field(s)")
        sp.attrs.update({"recipes": len(good), "skipped": len(skipped)})
        return good, skipped


def _slug(title):
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40].strip("_") or "recipe"


def _richness(rec):
    return len(rec.ingredients) + len(rec.method)


def _to_corpus(rec, recipe_id, source):
    """An extracted recipe in the recipes.json schema, flagged as undeclared."""
    y = rec.yield_
    yield_ = ({"amount": y.amount, "unit": y.unit or "servings"} if y.amount and y.amount > 0
              else {"amount": 1, "unit": "batch (yield not stated)"})
    return {
        "recipe_id": recipe_id,
        "version": "upload",
        "status": "current",
        "superseded_by": None,
        "title": rec.title.strip(),
        "description": rec.description or "",
        "cuisine": rec.cuisine or "",
        "dietary_tags": rec.dietary_tags,
        "allergens": [],
        "may_contain": [],
        "declared": False,
        "declaration_source": "undeclared (user upload)",
        "yield": yield_,
        "prep_minutes": rec.prep_minutes,
        "cook_minutes": rec.cook_minutes,
        "rest_minutes": rec.rest_minutes,
        "oven_c": rec.oven_c,
        "ingredients": [i.model_dump() for i in rec.ingredients],
        "method": rec.method,
        "notes": rec.notes or "",
        "safety_category": rec.safety_category if rec.safety_category in
        ("poultry", "ground_meat", "whole_cuts", "fish", "egg_dishes") else None,
        "source": source,
    }


# --------------------------------------------------------------------------
# Upload, list, delete
# --------------------------------------------------------------------------
def _write(store):
    config.USER_RECIPES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.USER_RECIPES_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, config.USER_RECIPES_FILE)


def _summary(f):
    return {k: f[k] for k in ("file_id", "filename", "uploaded_at", "bytes")} | {
        "recipes": [{"key": k, "title": (corpus.get_by_key(k) or {}).get("title")} for k in f["recipes"]]}


def check_file(filename, size):
    ext = Path(filename or "").suffix.lower()
    if ext == ".doc":
        raise UploadError("Old .doc files are not supported: open it in Word and save as .docx.")
    if ext not in config.UPLOAD_LIMITS["extensions"]:
        raise UploadError(f"Unsupported file type {ext or '(none)'}: use PDF, DOCX, TXT or MD.")
    if size > config.UPLOAD_LIMITS["max_bytes"]:
        raise UploadError(f"File is over {config.UPLOAD_LIMITS['max_bytes'] // (1024 * 1024)} MB.")
    if size == 0:
        raise UploadError("File is empty.")
    return ext


def ingest_file(path, filename, on_progress=None):
    """Extract, store and index the recipes in one uploaded file.

    on_progress(done, total) is called after each window. Re-uploading the
    same bytes returns the earlier result (duplicate=True) without LLM calls.
    """
    path = Path(path)
    ext = check_file(filename, path.stat().st_size)
    file_id = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    for f in corpus.read_user_file()["files"]:
        if f["file_id"] == file_id:
            return _summary(f) | {"duplicate": True, "skipped": [], "warnings": []}

    wins = windows(extract_text(path, ext))
    if not wins:
        raise UploadError("No text found in this file.")
    warnings = []
    limit = config.UPLOAD_LIMITS["max_windows"]
    if len(wins) > limit:
        warnings.append(f"Long file: only the first {limit} of {len(wins)} sections (up to page "
                        f"{wins[limit]['page']}) were read.")
        wins = wins[:limit]

    trace = Trace(f"upload {filename}", source="upload")
    found, skipped = {}, []
    for n, w in enumerate(wins, 1):
        try:
            recs, bad = extract_recipes(w["text"], trace)
        except llm.LLMError as exc:
            recs, bad = [], []
            warnings.append(f"section {n} (page {w['page']}) could not be read: {str(exc)[:120]}")
        skipped += bad
        for rec in recs:   # the same recipe seen twice across an overlap: keep the fuller copy
            s = _slug(rec.title)
            if s not in found or _richness(rec) > _richness(found[s][0]):
                found[s] = (rec, w["page"])
        if on_progress:
            on_progress(n, len(wins))

    record = {"ts": trace.ts.isoformat(), "trace_id": trace.trace_id, "file_id": file_id, "ext": ext,
              "windows": len(wins), "recipes": len(found), "skipped": len(skipped),
              "tokens_in": sum(s.tokens_in for s in trace.spans),
              "tokens_out": sum(s.tokens_out for s in trace.spans),
              "cost_usd": sum(s.cost_usd or 0 for s in trace.spans),
              "latency_ms": round(trace.elapsed_ms(), 1)}
    append_jsonl(config.LOG_DIR / "uploads.jsonl", record)   # cost per upload
    if not found:
        raise UploadError("No complete recipes (title, ingredients and method) were found in this file.")

    with _write_lock:
        store = corpus.read_user_file()
        taken = {corpus.key(r["recipe_id"], r["version"]) for r in corpus.all_recipes()}
        new = []
        for s, (rec, page) in found.items():
            rid, i = f"u_{s}", 2
            while corpus.key(rid, "upload") in taken:
                rid, i = f"u_{s}_{i}", i + 1
            taken.add(corpus.key(rid, "upload"))
            new.append(_to_corpus(rec, rid, {"kind": "upload", "file_id": file_id,
                                             "filename": filename, "page": page}))
        keys = [corpus.key(r["recipe_id"], r["version"]) for r in new]
        retriever.add_recipes(new)
        config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, config.UPLOADS_DIR / f"{file_id}{ext}")
        entry = {"file_id": file_id, "filename": filename, "ext": ext, "bytes": path.stat().st_size,
                 "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "trace_id": trace.trace_id, "recipes": keys}
        store["files"].append(entry)
        store["recipes"] += new
        _write(store)
        corpus.write_cards(new)
    return _summary(entry) | {"duplicate": False, "skipped": skipped, "warnings": warnings,
                              "cost_usd": record["cost_usd"]}


def list_uploads():
    return [_summary(f) for f in corpus.read_user_file()["files"]]


def delete_upload(file_id):
    """Remove one uploaded file and every recipe that came from it."""
    with _write_lock:
        store = corpus.read_user_file()
        entry = next((f for f in store["files"] if f["file_id"] == file_id), None)
        if entry is None:
            raise KeyError(file_id)
        keys = set(entry["recipes"])
        retriever.remove_recipes(keys)
        store["files"] = [f for f in store["files"] if f["file_id"] != file_id]
        store["recipes"] = [r for r in store["recipes"]
                            if corpus.key(r["recipe_id"], r["version"]) not in keys]
        _write(store)
    for k in keys:
        corpus.card_path(k).unlink(missing_ok=True)
    (config.UPLOADS_DIR / f"{file_id}{entry['ext']}").unlink(missing_ok=True)
    return {"file_id": file_id, "removed": sorted(keys)}
