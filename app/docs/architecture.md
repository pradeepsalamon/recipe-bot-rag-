# Architecture (one page)

```
                         python run.py ask | chat | eval
                                      │
                                      ▼
 ┌────────────────────────── CLIENT PROCESS ───────────────────────────────┐
 │                                                                          │
 │  SERVICE (pantry/service.py): validate (empty / >1000 chars rejected)    │
 │    └► [semantic cache, PANTRY_CACHE=1] never for allergy/diet/safety Qs; │
 │        hit = same recipes + same numbers + sim ≥ 0.88 + same data hash   │
 │        → answer served at $0, logged with its source trace id           │
 │                                                                          │
 │  Trace(trace_id) ── one per question ──────────────────────────────┐     │
 │                                                                    │     │
 │  AGENT LOOP (week 7, pantry/agent.py)                              │     │
 │   budgets: 8 iters · 40k tokens · $0.02 · 240 s                    │     │
 │                                                                    │     │
 │   ┌─► LLM call ($)  Groq gpt-oss-20b, native tool calling ─────────┤     │
 │   │      │ tool_calls                                              │     │
 │   │      ▼                                                         │     │
 │   │   local tool: scale_recipe  (no hop, pure Python) ─────────────┤     │
 │   │   MCP tools (discovered at runtime from mcp_servers.json) ─────┤     │
 │   │      │  call_tool(name, args, _meta={trace_id, parent_span})   │     │
 │   └──────┘ observe result, loop                                    │     │
 │                                                                    ▼     │
 │  final JSON {answer, citations[id@version], recommended,  ──► logs/requests.jsonl
 │              substitutions, refused}                         (redacted query,
 │                                                               spans, tokens, $)
 │    └► [cache store if storable]  └► [LangSmith mirror, PANTRY_LANGSMITH=1:
 │                                      same redacted record, background post]
 └───────────────────────────────┬──────────────────────────────────────────┘
                                 │ stdio (or HTTP :8799/mcp for outside clients)
                                 ▼
 ┌──────────────────────── MCP SERVER PROCESS (pantry-server) ─────────────┐
 │  search_recipes ──► RETRIEVER (week 3/4): Chroma dense (MiniLM, CPU,    │
 │                     free) + BM25 → RRF → group by recipe@version        │
 │                     + exact-match allergen exclusion on declarations    │
 │  get_recipe     ──► data/recipes.json                                   │
 │  check_allergens──► safety.py: set ∩ on `allergens` / `may_contain`     │
 │  find_substitution► data/substitutions.json (each option has allergens) │
 │  safe_temperature─► data/food_safety.json                               │
 │  match_pantry   ──► matching.py (ingredient overlap, time limit)        │
 │                                                                         │
 │  every tool call ──► logs/mcp_spans.jsonl  (same trace_id, parent span) │
 └─────────────────────────────────────────────────────────────────────────┘

 EVALS (python run.py eval): same client path per case → logs/eval_requests.jsonl
   1. assertions (no model): version cited, no superseded version, allergen-safe
      as published AND as substituted (safety.py is ground truth), temps, quantities,
      refusals
   2. trajectory: required tools called
   3. judge ($, LLM) only where 1 passed: grounded + answers the question
```

## Where the model calls happen

1. **Agent LLM calls**: one per loop iteration, typically 2–4 per question. This is the only per-question model cost.
2. **Judge LLM call**: eval runs only, one per case that passed its assertions.
3. **Embeddings**: local CPU (all-MiniLM-L6-v2), $0. The model warms in the background when the server starts, so the server is ready in about 1 s, then about 15–25 ms per search. With the cache on, the client process also embeds each eligible question for the cache lookup.

## Where the money goes

All of it goes to agent LLM tokens.
- Every iteration re-sends the system prompt, 7 tool schemas (~1.2k tokens) and all previous tool results. So input tokens grow with each tool call, and cost per question rises roughly with the square of the number of steps.
- Retrieval, the safety checks and the MCP hop cost nothing per call.

Live numbers: `python run.py report` (writes `evals/results/cost_and_scale.md`).

## Trace id across hops

- `Trace.trace_id` is created when the question arrives.
- Each MCP request carries `{trace_id, parent_span_id}` in its `_meta`. The model never sees it, because it isn't a tool argument.
- The server writes its own spans under that id.
- `python run.py trace <id>` merges `requests.jsonl` and `mcp_spans.jsonl` into one tree.
