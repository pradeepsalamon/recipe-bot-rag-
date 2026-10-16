"""
Shared fixtures. Every test runs offline: no Groq, no LangSmith. Logs (ours
and the MCP server subprocess's, via PANTRY_LOG_DIR) go to a temp dir, so the
real logs/ never sees test traffic.
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

_TMP = Path(tempfile.mkdtemp(prefix="pantry-tests-"))
os.environ["PANTRY_LOG_DIR"] = str(_TMP)
os.environ["PANTRY_CACHE"] = "0"
os.environ["PANTRY_LANGSMITH"] = "0"
os.environ.pop("LANGSMITH_TRACING", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json  # noqa: E402

import pytest  # noqa: E402

from pantry import config  # noqa: E402


@pytest.fixture
def log_dir():
    return config.LOG_DIR


# --------------------------------------------------------------------------
# A scripted stand-in for the Groq model
# --------------------------------------------------------------------------
def tool_call(name, args, call_id=None):
    return SimpleNamespace(id=call_id or f"call_{name}", type="function",
                           function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def model_turn(*calls, content=""):
    return SimpleNamespace(content=content, tool_calls=list(calls) or None)


def final_turn(**final):
    base = {"answer": "", "citations": [], "recommended": [], "substitutions": [], "refused": False}
    base.update(final)
    return SimpleNamespace(content=json.dumps(base), tool_calls=None)


class FakeLLM:
    """Replays a script of model turns; records every request it was sent."""

    def __init__(self, turns, tokens=(1000, 50)):
        self.turns = list(turns)
        self.requests = []
        self.tokens = tokens

    def __call__(self, messages, sp, tools=None, model=None, reasoning_effort=None, max_retries=5):
        self.requests.append({"messages": [dict(m) for m in messages], "tools": tools})
        sp.set_usage(config.AGENT_MODEL, *self.tokens)
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn


@pytest.fixture
def fake_llm(monkeypatch):
    from pantry import llm

    def install(turns, **kw):
        fake = FakeLLM(turns, **kw)
        monkeypatch.setattr(llm, "chat", fake)
        return fake
    return install


class FakeRegistry:
    """MCP registry stand-in that calls the real tool functions in-process."""

    def __init__(self, fail=None):
        from pantry import mcp_server
        self.fail = fail or {}
        self.tools = {n: ("pantry-server", None) for n in
                      ("search_recipes", "get_recipe", "check_allergens", "find_substitution",
                       "safe_temperature", "match_pantry")}
        self._srv = mcp_server
        self.calls = []

    def schemas(self):
        return [{"type": "function", "function": {"name": n, "description": n, "parameters": {"type": "object"}}}
                for n in self.tools]

    def server_of(self, name):
        return "pantry-server"

    async def call(self, name, args, trace_id=None, parent_span_id=None):
        self.calls.append((name, args, trace_id))
        if name in self.fail:
            return {"error": self.fail[name]}
        ctx = SimpleNamespace(request_context=SimpleNamespace(meta={"trace_id": trace_id,
                                                                    "parent_span_id": parent_span_id}))
        return json.loads(getattr(self._srv, name)(**args, ctx=ctx))


@pytest.fixture
def fake_registry():
    return FakeRegistry
