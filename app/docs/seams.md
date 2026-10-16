# Seam list

Compiled **2026-10-16 (Friday)** while integrating weeks 3–11 into `app/`. Each entry is a place where two pieces that worked alone broke when joined. The list is append-only; the status column is the only thing updated afterwards.

Status: **fixed** · **accepted** (known, deliberately left) · **ran-out-of-time**

| # | Seam | Between | What broke / would have broken | Status | Where |
|---|---|---|---|---|---|
| 1 | Chunk ids were random uuids | W3 ingest ↔ citations, traces | A citation or trace id from Monday pointed at nothing after a re-ingest | fixed: ids are `recipe@version#part` | `pantry/retriever.py` |
| 2 | Retriever rebuilt Chroma + BM25 on every question | W3 retriever ↔ W7 agent loop | 1–2 s per tool call, several calls per question | fixed: built once per process (W11 idea) | `pantry/retriever.py` |
| 3 | No version concept anywhere; allergens were a prose line | W3 corpus ↔ the brief | The superseded-shortbread failure could not even be expressed | fixed: structured corpus, `version`/`status`, `allergens[]`/`may_contain[]` | `data/recipes.json` |
| 4 | Agent tools read allergens from the docx prose | W7 tools ↔ declaration fields | "May contain" treated as text | fixed: exact set match on fields | `pantry/safety.py` |
| 5 | Agent parsed tool calls out of free-text JSON | W7 loop ↔ new model | The W7 parser was the most common failure | fixed: native function calling | `pantry/agent.py` |
| 6 | MCP config hard-coded `d:/practice/week 3/...` | W9 client ↔ a stranger's machine | Clone-and-run fails | fixed: `{python}` / `{app_dir}` placeholders | `mcp_servers.json` |
| 7 | Second MCP server (`ingredient-db`) was a 4-item mock | W9 ↔ "genuine capability" | Not a real capability | fixed: dropped; one real server with 6 tools | `pantry/mcp_server.py` |
| 8 | Trace id stopped at the process boundary | W11 tracing ↔ W9 MCP hop | No single trace from question to answer | fixed: trace id + parent span in MCP `_meta`; server writes its spans under it | `pantry/tracing.py`, `mcp_client.py` |
| 9 | Raw question text (with allergies) in the logs | W11 logging ↔ health data | PII line not held | fixed: health statements masked; allergen codes kept | `tracing.redact` |
| 10 | MCP server's first search took 11.7 s | W3 embeddings ↔ W9 stdio server | First question of every session slow | fixed: model warms in background at start; HF Hub offline when cached | `retriever.py` |
| 11 | Sync Groq call blocked the event loop that services the MCP stdio streams | W7 loop ↔ W9 async client | Stalls / timeouts under parallel tool calls | fixed: LLM call runs in a worker thread | `agent.py` |
| 12 | Evals scored pre-generated outputs, not the system | W6 suite ↔ integrated app | A passing suite said nothing about the app | fixed: every case runs the live path | `evals/run_evals.py` |
| 13 | Trajectory eval hard-coded W7 tool names and agent | W8 ↔ MCP-discovered tools | Could not run against the integrated agent | fixed: trajectory check per case on discovered names | `evals/assertions.py` |
| 14 | W6 judge was built for "is this substitution palatable" | W6 judge ↔ new outputs | Validated on a different task, so its 88.5% does not transfer | ran-out-of-time: new grounding judge written; agreement needs fresh hand labels | `prompts/judge_v1.txt` |
| 15 | Semantic cache would happily serve an allergy answer across a reformulation | W11 cache ↔ versioned corpus | Old "it's nut-free" served after the supplier change | fixed: never caches constraint questions; cache key includes a hash of the recipe data | `pantry/cache.py` |
| 16 | Port 8765 already taken on the dev machine | MCP HTTP mode ↔ local services | Server failed to bind, client talked to another program | fixed: documented port 8799 | README |
| 17 | Spans opened in the same Windows clock tick share a timestamp | W11 spans ↔ LangSmith tree | Children attached to the root, flattening the tree | fixed: tree built by parent id, not time | `observability.py` |
| 18 | Rasam: declaration says "None", ingredients say "Ghee or oil" | client CMS ↔ itself | Which is the truth for a dairy allergy? | accepted: declaration stays authoritative, conflict flagged by `run.py check-data`, eval case B13 | `data/recipes.json` |
| 19 | Groq free tier: 8k tokens/min, 1k requests/day | agent ↔ provider | Full eval takes ~30 min; ~400 questions/day max | accepted: logged per span; see cost report | `evals/results/cost_and_scale.md` |
| 20 | Corpus is 22 recipe-versions, not the client's 600 | brief ↔ what exists | Retrieval numbers do not transfer to 600 | accepted: stated in README and eval report | README |
