import os
import sys
import json
import time
import asyncio
import uuid
from contextlib import AsyncExitStack

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from dotenv import load_dotenv
load_dotenv(override=True)

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class McpToolRegistry:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.sessions = {}
        self.exit_stack = AsyncExitStack()
        self.tools_map = {}

    async def initialize(self):
        with open(self.config_path, "r") as f:
            config = json.load(f)

        for name, server_cfg in config.get("mcpServers", {}).items():
            cmd = server_cfg["command"]
            args = server_cfg.get("args", [])
            env = server_cfg.get("env", None)
            
            server_params = StdioServerParameters(command=cmd, args=args, env=env)
            read_stream, write_stream = await self.exit_stack.enter_async_context(stdio_client(server_params))
            session = await self.exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()
            self.sessions[name] = session
            
            result = await session.list_tools()
            for t in result.tools:
                self.tools_map[t.name] = (name, t)

    def get_tool_schemas(self):
        schemas = []
        for name, (server_name, t) in self.tools_map.items():
            schemas.append({
                "name": t.name,
                "description": t.description or "",
                "parameters": getattr(t, 'input_schema', getattr(t, 'inputSchema', {}))
            })
        return schemas

    async def call_tool(self, tool_name: str, arguments: dict):
        if tool_name not in self.tools_map:
            return {"error": f"Tool '{tool_name}' not found."}
        server_name, _ = self.tools_map[tool_name]
        session = self.sessions[server_name]
        res = await session.call_tool(tool_name, arguments)
        out = []
        for c in res.content:
            if c.type == "text":
                out.append(c.text)
        try:
            return json.loads("\n".join(out))
        except:
            return "\n".join(out)

    async def close(self):
        await self.exit_stack.aclose()

def _build_tool_call_prompt(schemas):
    lines = ["Available tools (call ONE at a time by responding with a JSON object):"]
    for t in schemas:
        params_desc = []
        for pname, pinfo in t.get("parameters", {}).get("properties", {}).items():
            req = "(required)" if pname in t.get("parameters", {}).get("required", []) else "(optional)"
            lines.append(f"    - {pname}: {pinfo.get('description', '')}")
        lines.append(f"\n  {t['name']}: {t['description']}")
        lines.extend(params_desc)
    lines.append('\nTo call a tool, respond with EXACTLY this JSON format:')
    lines.append('{"tool": "<tool_name>", "arguments": {<param>: <value>, ...}}')
    return "\n".join(lines)

def _parse_tool_call(text: str) -> tuple:
    text = text.strip()
    json_text = text
    if "```json" in json_text:
        start = json_text.index("```json") + 7
        end = json_text.find("```", start)
        json_text = json_text[start:end] if end > 0 else json_text[start:]
    elif "```" in json_text:
        start = json_text.index("```") + 3
        end = json_text.find("```", start)
        json_text = json_text[start:end] if end > 0 else json_text[start:]
    
    json_text = json_text.strip()
    try:
        parsed = json.loads(json_text)
        if isinstance(parsed, dict) and "tool" in parsed:
            return parsed["tool"], parsed.get("arguments", {})
    except:
        pass
    return None, None

async def run_agent(user_request: str, registry: McpToolRegistry):
    llm = ChatGroq(model="qwen/qwen3.8-27b", temperature=0)
    schemas = registry.get_tool_schemas()
    
    SYSTEM_PROMPT = """You are a Tamil Nadu recipe assistant with access to tools. 
    Use the tools provided to answer the user request.
    Output a JSON tool call to use a tool. Once you have enough info, output the final answer as JSON without any tool call wrapper."""
    
    full_system = SYSTEM_PROMPT + "\n\n" + _build_tool_call_prompt(schemas)
    messages = [SystemMessage(content=full_system), HumanMessage(content=user_request)]
    
    print(f"\n[REQUEST] {user_request}")
    
    for i in range(10):
        try:
            print(f"[WAITING ON GROQ API...] (Attempt {i+1})")
            response = llm.invoke(messages)
            content = response.content
            tool_name, tool_args = _parse_tool_call(content)
            if tool_name:
                print(f"[MODEL CALLS TOOL] {tool_name} with {tool_args}")
                tool_res = await registry.call_tool(tool_name, tool_args)
                print(f"[TOOL RESULT] {tool_res}")
                messages.append(AIMessage(content=content))
                messages.append(HumanMessage(content=f"Tool result for {tool_name}:\n{json.dumps(tool_res)}"))
            else:
                print(f"[FINAL ANSWER] {content}")
                break
        except Exception as e:
            print(f"[ERROR] {e}")
            break

async def main():
    print("Starting main...")
    registry = McpToolRegistry("mcp_config.json")
    print("Initializing registry...")
    await registry.initialize()
    print(f"Found tools: {list(registry.tools_map.keys())}")
    
    query = sys.argv[1] if len(sys.argv) > 1 else "Find substitution for creme fraiche lite for a VEGAN diet."
    print("Calling run_agent...")
    await run_agent(query, registry)
    await registry.close()

if __name__ == "__main__":
    asyncio.run(main())
