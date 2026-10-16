# Fresh-eyes test

To be filled in **during** the session with a reviewer from another squad. Don't help them; write down where they stop.

- **Reviewer (name, squad):**
- **Date / time:**
- **Their machine (OS, Python version):**
- **Started from:** a fresh clone, README only

## What they did, in order

| Time | Step (README section / command) | What happened | Stumbled? |
|---|---|---|---|
| | `pip install -r requirements-dev.txt` | | |
| | `.env` from `.env.example` | | |
| | `python run.py doctor` | | |
| | `python run.py ask "..."` (their own question) | | |
| | connected their own MCP client to `serve-mcp` (stdio or `--http 8799`) | | |
| | `python run.py trace <id>` | | |

## Their MCP client call (requirement 3)

- Client used (Claude Desktop / MCP Inspector / their own):
- Tool(s) called and arguments:
- Result:
- Did it show up in `logs/mcp_spans.jsonl`? (`trace_id` is null for outside clients; that's expected)

## Where they stumbled

1.
2.

## What I changed because of it

| Stumble | Change | Commit |
|---|---|---|
| | | |
