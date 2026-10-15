# Custom JSONL logs vs LangSmith

Same requests, two tools. Every record in `logs/requests.jsonl` is mirrored into the
LangSmith project **`recipe-rag-prod`** by `langsmith_export.py`, and the LangSmith run id
is our `trace_id`, so `d125333e-...` is the same request in both.

## What was checked (2026-10-15)

| Check | Result |
|---|---|
| Traces in each tool | 121 in `requests.jsonl`, 121 root runs in `recipe-rag-prod` |
| Planted trace `d125333e`, numbers in LangSmith | 5 child runs, LLM 817.4 ms, 430 in / 166 out tokens, $0.0000821. Identical to `trace.json` (we pass our own token/cost numbers in `usage_metadata`) |
| Exact prompt in LangSmith's LLM view | Rebuilt from `prompt_version` + chunk ids; sha matched (`prompt_rebuilt_exactly: true`) |
| Back-dated runs (30 Sep - 6 Oct) | **Rejected by LangSmith**: 422, "start_time must be within ±24 hours of current time". Uploaded at upload time instead; real time kept in metadata `request_ts` and tags `date:YYYY-MM-DD`, `week:YYYY-Www` |

## The drill in each tool

The complaint: *"it recommended a dairy-free substitution that wasn't dairy-free, sometime last week."*

**Custom logs** (`logq.py`, see `README.md`):

```bash
python logq.py find --since 14d --input-type dietary_swap,swap,dietary --text dairy   # -> 4 requests
python logq.py show <trace_id>
```

**LangSmith** (project `recipe-rag-prod`, Runs tab, filter bar). These filters were tested
through the API with the results shown:

| Filter | Runs | Planted one included? |
|---|---|---|
| tag `week:2026-W40` | 83 | yes |
| full-text search `dairy` | 4 | yes |
| full-text search `ghee` | 9 | yes |
| metadata `input_type` = `dietary_swap` | 9 | yes |
| metadata `input_type` = `dietary_swap` AND search `dairy` | **1** | yes |
| latency > 1.2 s | 8 | - |
| LLM runs with total_cost > $0.0001 | 10 | - |

Things that did **not** work in LangSmith's filter language (API errors / empty results):
- OR across tags, e.g. `dietary_swap` OR `swap` OR `dietary` -> 400 "OR operator cannot be
  used across different tables". Filter one input type at a time instead.
- cost / token filters on the root run (`gt(total_cost, ...)` -> 0 runs, even though the root
  shows its cost). They work on the LLM child runs (run type = llm).

## Side by side (fill in the last rows yourself)

| | Custom JSONL + `logq.py` | LangSmith |
|---|---|---|
| Per-step latency / tokens / cost | yes (spans) | yes (child runs), same numbers |
| Sees the full prompt and documents | no - stores ids only, rebuilt on demand | yes - LLM and retriever views |
| Request time for old / imported data | any timestamp | only within ±24 h of upload; older times live in metadata |
| Slice by time / user / prompt version / input type | yes, any combination incl. several input types at once | yes, but no OR across tags |
| Search question AND answer text | yes (`--text`, `--in answer`) | yes (full-text search) |
| Cost-outlier slice | `--cost-top N` on the whole request | cost filter only on LLM child runs |
| Answer-side flag (`dairy_violation`) | `--flag dairy_violation` (schema 2) | exported as metadata `output_dairy_violation` (schema 2) |
| Works offline / no account | yes | no (cloud account + API key) |
| Data leaves the machine | no | yes - questions, answers and prompts go to LangSmith |
| Visual trace tree, sharing a link with a teammate | no (terminal) | yes |
| Who maintains it | us (648 lines: tracing.py, logq.py, drill.py) | LangChain |
| **Your time-to-find, drill 1** | __:__ | __:__ |
| **Which slice / filter found it** | | |
| **What slowed you down** | | |
| **Verdict** | | |

## How to run the drill in both tools fairly

1. `python drill.py reset` and `python langsmith_export.py rebuild` (both tools now hold
   the same 120 clean requests).
2. Squadmate: `python drill.py plant` - the bad answer goes into **both** tools.
3. Find it in one tool with `drill.py start` / `found` (the tool times you), note the time.
4. Squadmate plants again; find the second one in the other tool, timing yourself.
   Alternate which tool goes first, otherwise the second tool benefits from practice.
