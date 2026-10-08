"""
Tiny tracing layer: one Trace per request, one Span per step.

We looked at LangSmith / Phoenix / OpenTelemetry this week. They all boil
down to the same shape: a trace id, a list of timed spans, and attributes on
each span. For a single-process app that is ~100 lines, and writing it
ourselves means every field the support drill needs is a plain JSON key we
can grep. The record layout follows OTel naming loosely (trace_id, spans,
attributes) so moving to a real collector later is a mapping, not a rewrite.
"""
import json
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import config


def cost_usd(model, tokens_in, tokens_out):
    price = config.PRICES.get(model)
    if price is None:
        # Unknown model: log None rather than a fake 0, so it shows up as a
        # gap in the cost report instead of quietly looking free.
        return None
    return (tokens_in * price["input"] + tokens_out * price["output"]) / 1_000_000


class Span:
    def __init__(self, name, stage):
        self.name = name
        self.stage = stage          # retrieval | tools | generation
        self.latency_ms = 0.0
        self.model = None
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd = 0.0
        self.attrs = {}
        self.error = None

    def set_usage(self, model, tokens_in, tokens_out):
        self.model = model
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.cost_usd = cost_usd(model, tokens_in, tokens_out)

    def to_dict(self):
        return {
            "name": self.name,
            "stage": self.stage,
            "latency_ms": round(self.latency_ms, 1),
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "attrs": self.attrs,
            "error": self.error,
        }


class Trace:
    def __init__(self, query, user_id, session_id=None, release="v1", ts=None):
        self.trace_id = str(uuid.uuid4())
        self.ts = ts or datetime.now(timezone.utc)
        self.query = query
        self.user_id = user_id
        self.session_id = session_id or f"s_{uuid.uuid4().hex[:8]}"
        self.release = release
        self.spans = []
        self._t0 = time.perf_counter()

    @contextmanager
    def span(self, name, stage):
        sp = Span(name, stage)
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


def stage_totals(spans):
    """Roll span dicts up to the three stages the cost report uses."""
    totals = {}
    for stage in ("retrieval", "tools", "generation"):
        mine = [s for s in spans if s["stage"] == stage]
        totals[stage] = {
            "calls": len(mine),
            "latency_ms": round(sum(s["latency_ms"] for s in mine), 1),
            "tokens_in": sum(s["tokens_in"] for s in mine),
            "tokens_out": sum(s["tokens_out"] for s in mine),
            "cost_usd": sum(s["cost_usd"] or 0 for s in mine),
        }
    return totals


def append_log(record, path=None):
    path = path or config.LOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_logs(path=None):
    path = path or config.LOG_FILE
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_logs(records, path=None):
    """Rewrite the whole log, sorted by request time. Only drill.py (planting)
    and the reindex backfill use this; normal requests just append."""
    path = path or config.LOG_FILE
    records = sorted(records, key=lambda r: r["ts"])
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
