"""
One trace id from question in to answer out, across the agent hop and the
MCP hop. Week 11's Trace/Span, plus:

  - span ids + parent ids, so the MCP server's spans hang under the client
    span that called them;
  - the trace id crosses the process boundary in the MCP request's `_meta`
    (never as a tool argument, so the model never sees or invents it); the
    server writes its spans to logs/mcp_spans.jsonl under the same trace id;
  - redact(): the PII line. Stated allergies are health data.
"""
import json
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config


def cost_usd(model, tokens_in, tokens_out, tokens_cached=0):
    price = config.PRICES.get(model)
    if price is None:
        return None  # unknown model: a visible gap in the report, not a fake $0
    fresh = tokens_in - tokens_cached
    return (fresh * price["input"] + tokens_cached * price["cached_input"]
            + tokens_out * price["output"]) / 1_000_000


def new_id():
    return uuid.uuid4().hex[:16]


class Span:
    def __init__(self, name, stage, parent_id=None, trace_id=None, process="client"):
        self.span_id = new_id()
        self.parent_id = parent_id
        self.trace_id = trace_id
        self.process = process
        self.name = name
        self.stage = stage          # agent | llm | tool | mcp | retrieval | safety
        self.start_ts = datetime.now(timezone.utc).isoformat()
        self.latency_ms = 0.0
        self.model = None
        self.tokens_in = 0
        self.tokens_cached = 0
        self.tokens_out = 0
        self.cost_usd = 0.0
        self.attrs = {}
        self.error = None

    def set_usage(self, model, tokens_in, tokens_out, tokens_cached=0):
        self.model = model
        self.tokens_in = tokens_in
        self.tokens_cached = tokens_cached
        self.tokens_out = tokens_out
        self.cost_usd = cost_usd(model, tokens_in, tokens_out, tokens_cached)

    def to_dict(self):
        return {k: getattr(self, k) for k in (
            "trace_id", "span_id", "parent_id", "process", "name", "stage", "start_ts",
            "model", "tokens_in", "tokens_cached", "tokens_out", "cost_usd", "attrs", "error")} | {
            "latency_ms": round(self.latency_ms, 1)}


class Trace:
    def __init__(self, query, session_id=None, source="cli"):
        self.trace_id = uuid.uuid4().hex
        self.ts = datetime.now(timezone.utc)
        self.query = query
        self.session_id = session_id or f"s_{uuid.uuid4().hex[:8]}"
        self.source = source
        self.spans = []
        self._t0 = time.perf_counter()

    @contextmanager
    def span(self, name, stage, parent_id=None):
        sp = Span(name, stage, parent_id=parent_id, trace_id=self.trace_id)
        start = time.perf_counter()
        try:
            yield sp
        except Exception as exc:
            sp.error = f"{type(exc).__name__}: {exc}"[:300]
            raise
        finally:
            sp.latency_ms = (time.perf_counter() - start) * 1000
            self.spans.append(sp)

    def elapsed_ms(self):
        return (time.perf_counter() - self._t0) * 1000


# --------------------------------------------------------------------------
# Server side of the MCP hop
# --------------------------------------------------------------------------
@contextmanager
def server_span(name, meta, stage="mcp"):
    """Used inside the MCP server process. `meta` is the request's _meta
    dict; a call from a client that sends no trace id (e.g. a reviewer's
    MCP Inspector) still gets logged, under trace_id None."""
    meta = meta or {}
    sp = Span(name, stage, parent_id=meta.get("parent_span_id"), trace_id=meta.get("trace_id"),
              process="mcp-server")
    start = time.perf_counter()
    try:
        yield sp
    except Exception as exc:
        sp.error = f"{type(exc).__name__}: {exc}"[:300]
        raise
    finally:
        sp.latency_ms = (time.perf_counter() - start) * 1000
        append_jsonl(config.MCP_SPAN_LOG, sp.to_dict())


# --------------------------------------------------------------------------
# PII
# --------------------------------------------------------------------------
# Statements ABOUT a person's health are masked; words like "allergen" in a
# recipe answer are not (masking those would make every trace unreadable).
_HEALTH = re.compile(
    r"(\ballergic to [^,.;?!\n]*"
    r"|\ballergy to [^,.;?!\n]*"
    r"|\b[\w-]+ allerg(?:y|ies)\b"
    r"|\bintoleran(?:t|ce) to [^,.;?!\n]*"
    r"|\b[\w-]+ intolerance\b"
    r"|\banaphyla\w*|\bepi-?pens?\b|\bco?eliac\b|\bceliac\b|\bdiabet\w*|\bpregnan\w*)",
    re.IGNORECASE)
_PERSON = re.compile(r"\bmy (?:son|daughter|kid|child|baby|toddler|wife|husband|partner|mum|mom|dad|guest)s?\b",
                     re.IGNORECASE)


def redact(text):
    """Mask health statements in free text before it is written down. The
    allergen CODES the checker used are logged separately (see config)."""
    if config.LOG_RAW_QUERY or not text:
        return text
    return _PERSON.sub("[PERSON]", _HEALTH.sub("[HEALTH]", text))


# --------------------------------------------------------------------------
# JSONL
# --------------------------------------------------------------------------
_write_lock = threading.Lock()


def append_jsonl(path, record):
    """One JSON line per record. Lines are written in a single call so two
    processes appending to the same file cannot interleave inside a line;
    the file rotates to <name>.1 at LOG_MAX_BYTES (one backup kept)."""
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.stat().st_size + len(line) > config.LOG_MAX_BYTES:
                backup = path.with_name(path.name + ".1")
                if backup.exists():
                    backup.unlink()
                path.rename(backup)
        except FileNotFoundError:
            pass
        except OSError:
            pass  # another process holds the file (Windows): skip rotation this time
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)


def read_jsonl(path):
    """Read a JSONL log, skipping a torn last line (e.g. a crash mid-write)."""
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def full_trace(trace_id, log_path=None):
    """Client record + the MCP server's spans for the same trace id."""
    paths = [log_path] if log_path else [config.REQUEST_LOG, config.EVAL_LOG]
    record = None
    for p in paths:
        for r in read_jsonl(p):
            if r["trace_id"].startswith(trace_id):
                record = r
    if record is None:
        return None
    server = [s for s in read_jsonl(config.MCP_SPAN_LOG) if s.get("trace_id") == record["trace_id"]]
    record = dict(record, server_spans=server)
    return record
