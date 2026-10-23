"""
MCP client side: week 9's McpToolRegistry, plus trace propagation.

Tools are discovered at runtime from whatever servers mcp_servers.json lists
(list_tools); nothing about them is hardcoded in the agent. Each call sends
the current trace id and the calling span id in the request `_meta`, so the
server's spans join the same trace.
"""
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from . import config

CONFIG_FILE = config.APP_DIR / "mcp_servers.json"


def _expand(value):
    """Config values may use {python} and {app_dir}, so the file works on any
    machine (week 9's config hardcoded d:/practice/week 3/...)."""
    return value.replace("{python}", sys.executable).replace("{app_dir}", str(config.APP_DIR))


class McpToolRegistry:
    def __init__(self, config_path=CONFIG_FILE):
        self.config_path = config_path
        self.sessions = {}
        self.tools = {}           # tool name -> (server name, Tool)
        self._stack = AsyncExitStack()

    async def __aenter__(self):
        with open(self.config_path, encoding="utf-8") as f:
            servers = json.load(f)["mcpServers"]
        for name, cfg in servers.items():
            env = dict(os.environ, **{k: _expand(v) for k, v in cfg.get("env", {}).items()})
            # no LangChain auto-tracing inside the server (duplicate traces);
            # the client-side mirror is the one LangSmith copy
            env["LANGSMITH_TRACING"] = "false"
            env["LANGCHAIN_TRACING_V2"] = "false"
            current_pythonpath = env.get("PYTHONPATH", "")
            sys_paths = os.pathsep.join(sys.path)
            env["PYTHONPATH"] = f"{sys_paths}{os.pathsep}{current_pythonpath}" if current_pythonpath else sys_paths
            if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
                env.setdefault("HF_HOME", "/tmp/huggingface")
                env.setdefault("PANTRY_LOG_DIR", "/tmp/logs")
            params = StdioServerParameters(command=_expand(cfg["command"]),
                                           args=[_expand(a) for a in cfg.get("args", [])],
                                           env=env, cwd=_expand(cfg.get("cwd", "{app_dir}")))
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.sessions[name] = session
            for t in (await session.list_tools()).tools:
                self.tools[t.name] = (name, t)
        return self

    async def __aexit__(self, *exc):
        await self._stack.aclose()

    def schemas(self):
        """OpenAI/Groq function schemas for every discovered tool."""
        out = []
        for name, (_server, t) in sorted(self.tools.items()):
            params = dict(getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {})
            params.pop("title", None)
            out.append({"type": "function", "function": {
                "name": name, "description": (t.description or "").strip(), "parameters": params}})
        return out

    def server_of(self, tool_name):
        return self.tools[tool_name][0] if tool_name in self.tools else None

    async def call(self, tool_name, arguments, trace_id=None, parent_span_id=None):
        """Call one MCP tool. Never raises: unknown tools, timeouts, server
        errors and a dead server all come back as {"error": ...} so the agent
        can tell the model instead of crashing the request."""
        if tool_name not in self.tools:
            return {"error": f"Tool '{tool_name}' not found. Available: {sorted(self.tools)}"}
        server, _ = self.tools[tool_name]
        meta = {"trace_id": trace_id, "parent_span_id": parent_span_id}
        try:
            res = await asyncio.wait_for(
                self.sessions[server].call_tool(tool_name, arguments, meta=meta),
                timeout=config.MCP_CALL_TIMEOUT_S)
        except asyncio.TimeoutError:
            return {"error": f"{tool_name} timed out after {config.MCP_CALL_TIMEOUT_S:.0f}s"}
        except Exception as exc:  # transport closed, server crashed, protocol error
            return {"error": f"{tool_name} failed: {type(exc).__name__}: {str(exc)[:200]}"}
        text = "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")
        if getattr(res, "is_error", False) or getattr(res, "isError", False):
            return {"error": text[:500]}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}
