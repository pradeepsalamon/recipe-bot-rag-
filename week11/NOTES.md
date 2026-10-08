# Week 11 study notes: what we did and why

Plain-language notes for revising before the Monday evaluation. Part 1 covers the ideas,
Part 2 covers what we actually built and the numbers, and Part 3 lists questions you are
likely to be asked.

---

## Part 1 - Theory

### 1. Observability: the app has to watch itself
In a demo, you are watching every answer. In production nobody is. So when a user says
"it gave a wrong answer last week", the **log is the only witness**. If a request wasn't
logged with enough detail, you can't find it, can't replay it, and can't prove it's fixed.

### 2. What to log for every request
The minimum, and why each field earns its place:

| Field | Why |
|---|---|
| `trace_id` | one id to quote in a bug report and replay the request |
| `ts` | the "time" slice ("sometime last week") |
| `user_id`, `session_id` | the "user" slice, and seeing a whole conversation |
| `input_type` | the "input type" slice (fact / swap / dietary_swap / ...) |
| `prompt_version` + `prompt_sha` | which prompt produced this answer; the sha catches edits made without a version bump |
| `query` **and** `answer` | complaints describe the *output* ("it said ghee"), so the answer must be searchable, not just the question |
| `retrieved_context_ids` | what the model was shown: tells you if it was a retrieval bug or a generation bug |
| spans with latency / tokens / cost | where the time and money went, per step |
| `model`, `fallback_used`, `status`, `error` | failed requests are requests too |

### 3. Traces and spans
A **trace** is one request. A **span** is one step inside it (embed, vector search, BM25,
fusion, tool call, LLM call). Each span has its own latency, tokens and cost. One total
number tells you *that* a request was slow or expensive; spans tell you *which step* to fix.

### 4. LangSmith / Phoenix / OpenTelemetry
These are ready-made tracing tools. **OpenTelemetry (OTel)** is the open standard (trace id,
spans, attributes). **LangSmith** (LangChain) and **Phoenix** (Arize) are LLM-focused UIs on
top of the same idea. We wrote a tiny tracer (`tracing.py`, about 100 lines) with the same
shape. That keeps every field a plain JSON key we can search, and moving to OTel later is
just a mapping.

### 5. The support drill
Practice for the real thing: a teammate hides one bad answer in the logs and gives you only
a vague complaint. You find it **from the logs alone**, against a clock. You narrow the
search using **slices**: time, user, prompt version, input type, cost outlier. The lesson from
the brief: index both inputs *and* outputs, because the complaint describes the output.
Finding it because you *remember* the demo doesn't count; that is memory, not tooling.

### 6. Cost per query
Cost = tokens x price. Measure it **per stage** (retrieval / tools / generation) *before*
optimising. Otherwise when the number moves you can't say what moved it. Watch out for
hidden **reasoning tokens**: models like gpt-oss "think" before answering, and those
tokens are billed as output.

### 7. Prompt caching vs semantic caching
- **Prompt caching** (provider side): a repeated prompt *prefix* (like a long system prompt)
  is billed cheaper. It's safe because the answer is still generated fresh.
- **Semantic caching** (your side): if a new question is *similar* to an old one, return the
  old answer without calling the model. It's fast and cheap, but **risky**: if the old answer
  was wrong, you now serve the wrong answer instantly to everyone. You must also accept that
  cached answers go stale. Never use it as a "fix". Key the cache on prompt version and
  flush it on a version bump.

### 8. Model routing (LiteLLM)
Send easy questions to a cheap or fast model and hard ones to a strong model. LiteLLM is a
library that gives one API over many providers and handles routing and fallbacks.

### 9. Fallbacks and rate limits
Providers limit you: requests per day (RPD) and tokens per minute (TPM). When you hit one you
get HTTP 429 with a `retry-after` header. A **fallback** is a second model or provider used
when the first one fails. Log both attempts so you can see when fallbacks happen.

### 10. The failure -> test loop (and the data flywheel)
Every real failure becomes a permanent eval case:
1. Write the case and run the suite **before** fixing. Watch it go **RED**. A test you never
   saw fail is a test you haven't tested.
2. Fix it. Re-run the **whole** suite and see it **GREEN**, with pass counts both times, so a
   regression somewhere else can't hide.
3. Keep the case forever.

The **data flywheel** is that loop running continuously: logs -> failures -> eval cases ->
better app -> better logs.

### 11. Canary and rollback
Don't ship a fix to everyone at once. Send it to a small share of users first (the
**canary**, e.g. 10%), watch a few numbers, then promote it. **Rollback** must be one quick,
boring step, like setting a config value to 0.

### 12. The 10x plan
Ask: if traffic were 10 times bigger, which ceiling do we hit first: cost, latency, or a
rate limit? Answer with a number from your own logs, then plan for that limit.

### 13. Fine-tuning: last resort
Fix with prompt, retrieval, tools and evals first. Fine-tuning is slow and costly, hard to
undo, and needs lots of good data. Use it only when cheaper fixes have clearly run out.

---

## Part 2 - Practical: what we built

**The app.** It is the same recipe RAG app as before (6 Tamil Nadu recipes, hybrid
dense + BM25 retrieval with RRF, strict cite-your-chunk prompt). The v1 prompt is copied
word for word from `rag_pipeline.py`. We changed generation to Groq `gpt-oss-20b`, because the
old Gemini 3.5 model was returning 503 errors. Gemini 3.6 is now the fallback.

**Step 1 - Make it observable** (`pipeline.py`, `tracing.py`). Every request writes one JSON
line with all the fields in Part 1, plus spans: `retrieval.embed`, `retrieval.dense`,
`retrieval.bm25`, `retrieval.rrf_fuse`, `tool.recipe_facts` (v2 only), and
`generation.llm`. The first request in a process also gets a `retrieval.cold_start` span
(~13 s to load the embedder); otherwise it would hide as unexplained latency.

**Step 2 - Traffic** (`simulate_traffic.py`). We sent 120 real questions through the app
(23 users, all question types). Only the timestamps are simulated, spread over last week,
because we can't wait a week. Each record is labelled `simulated_traffic`.

**Step 3 - Reproduce the bug for real.** We didn't invent the bad answer. We asked v1:
*"I'm cooking Ven Pongal for a dairy-free guest. What can I fry the cashews in instead of
butter?"* and it said *"Use ghee to fry the cashews."* Ghee is dairy.
Root cause, read from the trace's `retrieved_context_ids`: top-3 retrieval returned three
method steps and never the line *"Allergens: Dairy (ghee)"*. The v1 prompt also had no
rule that ghee is dairy.
We also found a **data bug** in the corpus: Rasam's header says *"Vegan, Allergens: None"*,
but its ingredient row is *"Ghee or oil"* and step 3 says *"heat ghee"*.

**Step 4 - Checks without an LLM judge** (`diet_rules.py`). Following the week 6 lesson,
allergen checks use plain regex and word lists, not a model. The rule is: for a dairy-free
question, the answer may only name ghee/butter/milk if it also says it's dairy, and it must
never call a dairy item (or a dish containing one) dairy-free. We **tested the checker
itself** (`evals/test_diet_rules.py`). Running it over last week's real logs first gave
false alarms: refusals that just repeat the word "ghee", and hedges like "cannot determine
*whether* Rasam is dairy-free". We fixed those and added them as tests.

**Step 5 - The drill tooling** (`logq.py`, `drill.py`). `logq.py find` slices the log. Every
search is recorded, so `drill.py found` can report the exact slice that found the trace.
The squadmate's `plant` sends real questions through v1 until one genuinely fails, then
back-dates and hides it. Only a hash of the answer key is stored. The clock is the tool's,
not a stopwatch.

**Step 6 - The failure -> test loop** (`evals/`). The suite has 11 live cases tagged with the
week 6 taxonomy modes, plus the new case file with 2 cases:

| Run | Suite | New cases | Allergen safety |
|---|---|---|---|
| v1, before the case | 7/11 | - | 0/2 |
| v1 + case (RED) | 7/13 | 0/2 | 0/4 |
| v2 prompt only (ablation) | 7/13 | 0/2 | 0/4 |
| v2 prompt + retrieval guard (GREEN) | 11/13 | 2/2 | 4/4 |

The **ablation** shows *which layer* did the work. The prompt alone made the answer safe
("ghee is a dairy product") but not useful. The retrieval guard (the `recipe_facts` tool
adds the allergen line and ingredient list for diet questions) is what made it correct.
The two cases still failing were failing before too: plain top-3 retrieval misses, left
for a separate release.
Includes guard cases (taste swap, "Is Medu Vada vegan?") so the dairy fix can't
over-correct into refusing everything.

**Step 7 - Cost** (`cost_report.py`).
- One query costs $0.0000821. 100% of that is generation; retrieval runs locally ($0).
- 137 of its 166 output tokens are hidden reasoning, which is **50% of the cost**.
- The v2 fix costs +46% per query fleet-wide, because diet questions now carry the ingredient list.
- Improvement v2 -> v2.1: `reasoning_effort=low` cuts cost **-26%** with the suite unchanged.
  This is attribution first, optimisation second.

**Step 8 - 10x.** Groq's 8,000 tokens/minute limit breaks first. Our busiest minute is 1,178
tokens and becomes 11,780 at 10x. Requests per day still have 43x headroom, and cost is about
one cent per day. After v2 ships, the tokens-per-minute limit arrives at 4.0x instead of 6.8x.

---

## Part 3 - Likely evaluation questions

- **"Why didn't you search only the questions?"** The complaint describes the *answer*. Both
  are indexed, and the bonus `output_tags.dairy_violation` indexes the answer directly.
- **"How do you know the test works?"** It failed on v1 (RED file, timestamp before
  `recipe_v2.txt` was created), and the checker has its own tests.
- **"Could your fix have broken something else?"** The whole suite re-ran with pass counts.
  The same 2 old failures, no new ones, and the taste-swap and vegan cases still pass.
- **"Which change fixed it?"** The ablation run: prompt alone 0/2, prompt + retrieval guard 2/2.
- **"Why not semantic caching?"** It would cache the ghee answer and serve it instantly to
  everyone asking something similar.
- **"Why not fine-tune?"** A prompt rule plus one retrieval tool fixed it in an afternoon,
  and it is measurable and reversible.
