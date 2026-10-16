# Pantry-to-Plate Assistant (Week 12 capstone, Variant B)

Ask cooking questions in plain language ("what can I make with what's in the fridge, my kid is allergic to nuts, I have 25 minutes"). It answers from the publisher's recipe library only. Every answer:

- cites the recipe **and its version** (`[shortbread@reformulated-2025]`);
- checks allergens against the declaration **fields** by exact match, never from the prose;
- scales quantities without scaling cook times;
- states safe internal temperatures;
- refuses rather than guesses.

Weeks 3–11 are wired together behind one entry point:

| Piece | From | Here |
|---|---|---|
| Hybrid RAG (dense + BM25 + RRF) | week 3/4 | [pantry/retriever.py](pantry/retriever.py) |
| Agent loop with 4 budgets | week 7 | [pantry/agent.py](pantry/agent.py) |
| MCP tools discovered at runtime | week 9 | [pantry/mcp_client.py](pantry/mcp_client.py), [mcp_servers.json](mcp_servers.json) |
| Our own MCP server | week 9 | [pantry/mcp_server.py](pantry/mcp_server.py) |
| Eval suite: assertions before judge | week 6 | [evals/](evals/) |
| Trajectory eval | week 8 | [evals/assertions.py](evals/assertions.py) `trajectory()` + report |
| Per-request trace, cost per span | week 11 | [pantry/tracing.py](pantry/tracing.py), [pantry/llm.py](pantry/llm.py) |

## Run it (from zero)

You need Python 3.12 and a free Groq API key (https://console.groq.com/keys).

```bash
cd app
pip install -r requirements-dev.txt   # pinned runtime deps + pytest
cp .env.example .env                  # paste your GROQ_API_KEY into .env
python run.py doctor                  # checks everything below the line works on this machine
python run.py ask "Is the shortbread safe for my son? He has a nut allergy."
```

The first run builds the recipe cards and the search index. That takes about a minute, and downloads a ~90 MB embedding model once. After that a question takes 4–25 s depending on Groq rate limits.

Every answer prints:
- each tool call as it happens (the allergen check is visible);
- the answer, then its sources as file paths to the cited recipe card (click them in VS Code);
- a trace id, cost and latency.

## Commands

| Command | What it does |
|---|---|
| `python run.py ask "<question>"` | One question, end to end |
| `python run.py chat` | Interactive session |
| `python run.py trace <trace_id>` | Every span of one request across both processes (agent + MCP server), with latency, tokens and cost |
| `python run.py eval` | Full suite (34 cases) against the integrated system: assertions, then trajectory, then judge. Writes `evals/results/<run>.md` + `.jsonl`. **Takes 20–30 min on the Groq free tier.** `--cases B01,B19` or `--category scaling` runs a subset. `--no-judge` skips the judge. `--fail-on-unsafe` exits 1 if any answer is allergen-unsafe (for CI). The cache is always bypassed. |
| `python run.py label <run>.jsonl` | Hand-label outputs pass/fail; this is the ground truth for the judge |
| `python run.py judge <run>.jsonl` | Re-run the judge on labelled outputs and report agreement (bar: 85%) |
| `python run.py report` | Cost per query and what breaks first at 50,000 / 500,000 queries a day, from the logs |
| `python run.py test [-k ...]` | pytest suite, 111 tests, about 25 s, fully offline (details below) |
| `python run.py doctor [--online]` | Setup check: Python, dependencies, key, data, index, MCP server. `--online` adds one tiny Groq call |
| `python run.py check-data` | Where a recipe's allergen declaration and its ingredient list disagree |
| `python run.py serve-mcp [--http 8799]` | The MCP server on its own, for any MCP client |
| `python run.py ingest` | Rebuild cards and index after editing `data/` |
| `python run.py cache stats\|clear` | Semantic cache status, or empty it |
| `python run.py langsmith check\|backfill` | Is the LangSmith mirror receiving? Re-send a log file |

## Optional features (off by default)

**Semantic cache (`PANTRY_CACHE=1`).** Serves a stored answer to a paraphrased question.
- Measured live: "How much urad dal do I need for medu vada?" was served from the answer to "How much urad dal goes into medu vada?" in under 0.1 s for $0. The first answer took 9.4 s and cost $0.0004.
- Rules, taken from Week 11 and tightened ([pantry/cache.py](pantry/cache.py)):
  - **never** used for any question mentioning an allergen, a diet, a health condition, a substitution or doneness;
  - a hit needs similarity ≥ 0.88, the same recipes named and the same numbers;
  - the cache key includes a hash of the prompt, the model **and the recipe data**, so editing `data/recipes.json` (a reformulation) voids every stored answer;
  - refusals, superseded-version citations and substitution answers are never stored;
  - entries expire after 24 h;
  - every hit records the trace that produced the answer.
- Expect a low hit rate: Week 11 measured 6/121 with diet questions excluded, and most questions here carry an allergy.

**LangSmith mirror (`PANTRY_LANGSMITH=1` + `LANGSMITH_API_KEY`).** Each request becomes a LangSmith run tree:
- the run id is our trace id;
- agent → each LLM call (with our token and cost numbers) → each tool call;
- `semantic-cache-hit`, `refused` and `stopped:*` tags.

It sends **exactly the redacted log record**: masked health statements, allergen codes only, no user id. It posts in the background, so a LangSmith outage never fails or slows a request. Projects: `pantry-prod` (CLI) and `pantry-evals` (evals). Verified live: both test traces arrived with full trees (8 runs and 2 runs). MCP-server-side spans stay in `logs/mcp_spans.jsonl`; `run.py trace` shows them merged.

## Production behaviour

| Concern | What happens |
|---|---|
| MCP tool slow or hung | Each call has a timeout (30 s, `PANTRY_MCP_TIMEOUT_S`) and comes back to the model as a tool error |
| MCP server crashed / bad tool name / bad args | Returned as a tool error. The server bounds its inputs (lengths, list sizes, `top_k`), because outside clients call it too |
| Groq 429 | Waits `retry-after` (capped at 60 s), up to 5 times, logged on the span |
| Groq 5xx / connection / timeout | Exponential backoff, 2 retries, then a clean "temporarily unavailable" answer (`terminated_by: llm_error`). It never crashes, and no advice is given |
| Model emits broken tool JSON | That call returns a tool error and the loop continues |
| Runaway loop | Week 7 budgets: 8 iterations, 40k tokens, $0.02, 240 s |
| Empty or >1000-char question | Rejected before any model call |
| Logs | JSONL, rotated at 50 MB (one backup). A torn last line is skipped on read |
| LangSmith down | Requests unaffected; first failure reported once on stderr |

## Optimizations (measured)

| Change | Effect |
|---|---|
| The model sees a compact view of tool results ([pantry/compact.py](pantry/compact.py)). Safety fields always kept, enforced by tests | **−41%** characters across one call of each tool (7,568 → 4,490) |
| Same shortbread question, same tool path, before → after | input tokens **5,535 → 4,690 (−15%)**, cost **$0.000468 → $0.000412 (−12%)**, 13.4 s → 9.9 s. One pair of runs; latency is noisy on Groq |
| One Groq client per process | No new TLS handshake per LLM call (Week 7/11 created a client each time) |
| Several tool calls in one model turn run concurrently | Saves one MCP round trip per extra call |
| Tools sorted by name | Byte-identical prompt prefix between requests, so Groq's prompt cache can hit (`tokens_cached` is logged per span) |
| Embedding model warms in the background at MCP server start; HF Hub goes offline once cached | Server ready in about 1 s instead of a 10 s first search |
| `reasoning_effort=low` | Kept from Week 11 (−26% cost there, suite unchanged) |

## Tests

`python run.py test`: 111 tests in about 25 s. No Groq or LangSmith calls, and logs go to a temp dir.

| File | Covers |
|---|---|
| `test_safety.py` | Allergen normalisation ("nuts" = both), exact-match verdicts, may-contain, the declaration-not-prose case (Worcestershire contains fish), substitution chains, unknown substitutes, temperatures, the rasam data conflict |
| `test_corpus_scaling.py` | Version links, one current version per recipe, scaling never touching times, fractional eggs, poultry probe temperature |
| `test_assertions.py` | The eval assertions catch: superseded shortbread, the system's own unsafe swap, unwarned may-contain, a missing allergen tool call, citations without a version, a scaled bake time |
| `test_compact.py` | ≥30% smaller, and status / superseded_by / verdicts / substitute allergens / time rule survive |
| `test_cache.py` | Every guard: constraint questions, other recipe, other numbers, threshold, recipe-data fingerprint, TTL, never-store rules, cap, reload, plus one real-MiniLM paraphrase check |
| `test_tracing.py` | Rotation, torn lines, redaction, server spans under the caller's trace id |
| `test_observability.py` | LangSmith tree shape, ids, usage; nothing un-redacted leaves; disabled without key; a failure never raises |
| `test_agent.py` | Offline end to end with a scripted model: tool loop, compact payloads, sorted tools, parallel calls, tool errors, malformed args, LLM outage, iteration and cost budgets, unparseable final, invalid citation, input validation, eval log routing, cache hit skips the model, allergy questions bypass the cache |
| `test_integration.py` | Real MCP server subprocess over stdio and the real index: tool discovery, bad input, unknown tool, **one trace id across the agent and MCP hop with correct parent spans**, codes-not-words in server logs, and the superseded shortbread surviving the nut filter (the brief's trap) |

## Connect your own MCP client to our server

stdio, e.g. Claude Desktop / Claude Code / MCP Inspector config (use absolute paths on your machine):

```json
{ "mcpServers": { "pantry-server": {
    "command": "python",
    "args": ["<path-to-repo>/app/run.py", "serve-mcp"] } } }
```

Or HTTP: `python run.py serve-mcp --http 8799`, then connect to `http://127.0.0.1:8799/mcp`.

Tools:

| Tool | What it does |
|---|---|
| `search_recipes` | Version-aware hybrid search, with optional exact-match allergen exclusion |
| `get_recipe` | One full recipe-version |
| `check_allergens` | Exact match on the `allergens` / `may_contain` fields: SAFE / MAY_CONTAIN / UNSAFE |
| `find_substitution` | Test-kitchen options; each carries its own allergens |
| `safe_temperature` | Safe internal temperature (°C) |
| `match_pantry` | Which recipes your ingredients cover |

Calls from your client are logged in `logs/mcp_spans.jsonl`. Calls from our agent carry the trace id in the MCP `_meta`, so they join the same trace.

## The data (read this before trusting any number)

[data/recipes.json](data/recipes.json) holds **17 recipes / 22 recipe-versions, not the client's 600.**

- The 6 Tamil Nadu cards from weeks 3–11 are carried over verbatim. Their prose "Allergens:" line became structured `allergens` / `may_contain` fields.
- 11 recipes were written for the capstone to cover the brief:
  - **5 recipes exist as both `original` (superseded) and `reformulated-2025` (current)**: shortbread, chocolate chip cookies, pesto pasta, granola bars and banana bread. Their allergens differ between versions in both directions.
  - Poultry, mince and fish dishes, for the safe-temperature chart.
  - Quick pantry dishes.
- Both versions stay in the index on purpose. The client's CMS still has both, and dropping the old ones would hide the superseded-citation bug, not fix it.

Two more data files:
- [data/substitutions.json](data/substitutions.json) is the test-kitchen table. Every substitute has its own declaration, because some swaps add an allergen (almond flour for gluten, peanuts for cashews).
- [data/food_safety.json](data/food_safety.json) is the USDA FSIS safe-minimum-temperature chart in °C. Poultry is 74°C, mince 71°C, fish and whole cuts 63°C.

One known conflict in the client's own data: **rasam declares "Allergens: None" but its ingredients say "Ghee or oil".** It's left as exported and flagged by `run.py check-data`.

## Design decisions worth defending

- **Allergen verdicts are code, not judgment.**
  - [pantry/safety.py](pantry/safety.py) intersects the user's allergen codes with the declaration fields.
  - "nuts" maps to PEANUT **and** TREE_NUT.
  - An unknown allergen ("kiwi") is reported as unknown, never treated as absent.
  - The evals use the same functions as their ground truth. The LLM judge never scores allergen safety.
- **The allergen eval metric counts what the user will actually cook.** Recommending `shortbread@original` (genuinely nut-free) to a nut-allergic parent counts as **unsafe**, because the current version contains tree nuts.
- **Allergen safety is measured twice:** on the recipe as published, and on the recipe *as substituted by the system's own swaps*. The report shows how many cases pass the first and fail the second (the bonus challenge).
- **Scaling never scales time.** `scale_recipe` returns quantities scaled and times/oven temperature explicitly UNCHANGED. For poultry it adds the probe temperature.
- **Chunk ids are deterministic** (`shortbread@reformulated-2025#method`), so a citation or trace from Monday still resolves on Friday.
- **PII line:** a user's stated allergies are health data.
  - Logged questions and answers have health statements masked (`my kid is allergic to nuts` becomes `[PERSON] is [HEALTH]`).
  - The normalised allergen *codes* the checker used are kept, because without them an allergen failure can't be reproduced.
  - No user id is logged. The opt-in LangSmith mirror receives exactly this redacted record and nothing else.
  - `PANTRY_LOG_RAW_QUERY=1` turns masking off for local debugging only.

## Repo map

```
run.py                 single entry point
mcp_servers.json       MCP servers the agent discovers tools from (portable: {python}, {app_dir})
prompts/               agent_v1.txt, judge_v1.txt (versioned, logged on every trace)
data/                  recipes, substitutions, food-safety chart; cards/ = rendered citation targets
pantry/                service (the one request path), agent, mcp_client, mcp_server, retriever,
                       safety, scaling, matching, corpus, compact, cache, observability (LangSmith),
                       tracing, llm, doctor, config
evals/                 cases.json (34), assertions.py, run_evals.py, judge.py, report.py,
                       results/ (reports), labels/ (hand labels)
tests/                 pytest suite (111 tests, offline)
docs/architecture.md   one-page sketch: boxes, arrows, model calls, where the money goes
logs/                  requests.jsonl, eval_requests.jsonl, mcp_spans.jsonl (git-ignored)
```
