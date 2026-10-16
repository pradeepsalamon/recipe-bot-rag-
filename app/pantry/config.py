"""
Settings for the integrated Pantry-to-Plate app.

Same idea as week11/config.py: anything that changes between releases
(models, prices, budgets, retrieval switches) lives here, so a release or a
rollback is a one-line diff.
"""
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
RECIPES_FILE = DATA_DIR / "recipes.json"
SUBSTITUTIONS_FILE = DATA_DIR / "substitutions.json"
FOOD_SAFETY_FILE = DATA_DIR / "food_safety.json"
CARDS_DIR = DATA_DIR / "cards"            # one rendered .md per recipe-version: the citation target

INDEX_DIR = APP_DIR / ".index"            # Chroma store, rebuilt by `run.py ingest`
COLLECTION = "pantry_v1"
EMBED_MODEL = "all-MiniLM-L6-v2"          # week 3 model, local CPU, no API bill

LOG_DIR = Path(os.getenv("PANTRY_LOG_DIR", str(APP_DIR / "logs")))  # tests point this at a temp dir
REQUEST_LOG = LOG_DIR / "requests.jsonl"  # one record per question (client side)
MCP_SPAN_LOG = LOG_DIR / "mcp_spans.jsonl"  # spans written by the MCP server process, same trace_id
EVAL_LOG = LOG_DIR / "eval_requests.jsonl"  # eval traffic kept apart from "production"

# Agent model (Groq). gpt-oss-20b is what week 11 ran on; its prices and
# free-tier limits are already measured there.
AGENT_MODEL = os.getenv("PANTRY_MODEL", "openai/gpt-oss-20b")
JUDGE_MODEL = os.getenv("PANTRY_JUDGE_MODEL", "openai/gpt-oss-20b")
REASONING_EFFORT = os.getenv("PANTRY_REASONING_EFFORT", "low")  # week 11: -26% cost, suite unchanged

# USD per 1M tokens (carried from week11/config.py, looked up 2026-10-07).
PRICES = {
    "openai/gpt-oss-20b": {"input": 0.075, "cached_input": 0.0375, "output": 0.30},
    "openai/gpt-oss-120b": {"input": 0.15, "cached_input": 0.075, "output": 0.60},
    EMBED_MODEL: {"input": 0.0, "cached_input": 0.0, "output": 0.0},
}

# Groq free tier for gpt-oss-20b (week 11, from x-ratelimit-* headers).
GROQ_LIMITS = {"tokens_per_minute": 8000, "requests_per_day": 1000}

# Week 7 budgets, re-tuned for a 7-tool agent.
BUDGETS = {
    "max_iters": 8,
    "max_tokens": 40000,
    "max_cost_usd": 0.02,
    "max_wall_clock_s": 240,
}

RETRIEVAL = {
    "top_k": 5,
    "pool_k": 20,   # candidates per retriever before RRF (week 3: max(top_k*4, 20))
    "rrf_k": 60,
}

RELEASE = os.getenv("PANTRY_RELEASE", "v1")


def _flag(name, default="0"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


# Input limits: a question longer than this is rejected before any model call.
MAX_QUESTION_CHARS = 1000

# MCP: a tool call that takes longer than this is returned to the model as a
# tool error instead of hanging the agent.
MCP_CALL_TIMEOUT_S = float(os.getenv("PANTRY_MCP_TIMEOUT_S", "30"))

# LLM transient-error retries (5xx / connection), on top of 429 retry-after.
LLM_TRANSIENT_RETRIES = 2

# Logs rotate at this size: requests.jsonl -> requests.jsonl.1 (one backup).
LOG_MAX_BYTES = int(os.getenv("PANTRY_LOG_MAX_BYTES", str(50 * 1024 * 1024)))

# Semantic answer cache (week 11 design, stricter). OFF unless PANTRY_CACHE=1.
# Rules and the reasons for them live in pantry/cache.py.
CACHE = {
    "enabled": _flag("PANTRY_CACHE"),
    "threshold": 0.88,          # week 11: paraphrases >= 0.898, different recipes <= 0.79
    "ttl_hours": 24,
    "max_entries": 5000,
    "path": LOG_DIR / "semantic_cache.jsonl",
}

# LangSmith mirror. OFF unless PANTRY_LANGSMITH=1 AND LANGSMITH_API_KEY is
# set. Sends the same redacted record we log (no raw allergy words, no user id).
LANGSMITH = {
    "enabled": _flag("PANTRY_LANGSMITH"),
    "projects": {"cli": "pantry-prod", "eval": "pantry-evals"},
}

# PII: a user's stated allergies are health data. What we write down:
#   - never a user id; each CLI session gets a random session id
#   - the question text with health phrases masked (tracing.redact)
#   - the normalised allergen CODES the checker ran with, because without
#     them an allergen failure cannot be reproduced from the log
#   - the LangSmith mirror (opt-in) receives exactly this redacted record
LOG_RAW_QUERY = os.getenv("PANTRY_LOG_RAW_QUERY", "0") == "1"
