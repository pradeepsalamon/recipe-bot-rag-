"""
Settings for the Week 11 production build.

Anything that changes between releases (prompt version, retrieval switches,
models, prices, canary split) lives in this one file, so a release or a
rollback is a one-line diff that is easy to review.
"""
from pathlib import Path

WEEK_DIR = Path(__file__).resolve().parent
REPO_ROOT = WEEK_DIR.parent

# Same vector store the app has used since week 3.
CHROMA_DIR = REPO_ROOT / "chroma_db"
COLLECTION = "recipes_structure"
EMBED_MODEL = "all-MiniLM-L6-v2"  # runs locally on CPU, no API bill

PROMPT_DIR = WEEK_DIR / "prompts"
LOG_DIR = WEEK_DIR / "logs"
LOG_FILE = LOG_DIR / "requests.jsonl"          # production traffic
EVAL_LOG_FILE = LOG_DIR / "eval_runs.jsonl"    # eval traffic, kept apart so it never pollutes the drill
SEARCH_HISTORY_FILE = LOG_DIR / "search_history.jsonl"

# Generation runs on Groq. Gemini is only the fallback: gemini-3.5-flash
# (the week-3 model) was returning 503s, and 3.6-flash takes ~40 s per call
# because of thinking tokens, so it is too slow to be the main model.
PRIMARY_MODEL = "openai/gpt-oss-20b"
FALLBACK_MODEL = "gemini-3.6-flash"

# USD per 1M tokens, looked up on 2026-10-07 (Groq / Google list prices via
# cloudprice.net and pricepertoken.com). Gemini price is the intro rate that
# runs until 2026-12-31. If prices change, update here; every cost in the
# logs is computed from this table at request time.
PRICES = {
    "openai/gpt-oss-20b": {"input": 0.075, "output": 0.30},
    "gemini-3.6-flash": {"input": 0.75, "output": 3.75},
    EMBED_MODEL: {"input": 0.0, "output": 0.0},
}

# Groq free-tier limits for gpt-oss-20b, as returned in the
# x-ratelimit-limit-* response headers. We also log the live header values
# on every generation span, so these are only the fallback for reports.
GROQ_LIMITS = {"tokens_per_minute": 8000, "requests_per_day": 1000}

# A release is a prompt file plus the retrieval switches that go with it.
#   dietary_guard: for diet/allergen questions, call the recipe_facts tool and
#   add the recipe's allergen line + full ingredient list to the context.
#   reasoning_effort: gpt-oss "thinks" before answering and those hidden
#   tokens are billed as output (~50% of a v1 request's cost). None = Groq's
#   default (medium).
RELEASES = {
    "v1": {"prompt_file": "recipe_v1.txt", "top_k": 3, "dietary_guard": False},
    "v2": {"prompt_file": "recipe_v2.txt", "top_k": 3, "dietary_guard": True},
    # Cost experiment on top of v2: same prompt and retrieval, less thinking.
    "v2.1": {"prompt_file": "recipe_v2.txt", "top_k": 3, "dietary_guard": True,
             "reasoning_effort": "low"},
}

# Canary: STABLE serves everyone except the CANARY_PERCENT of users whose
# hashed user_id lands in the canary bucket. Rollback = CANARY_PERCENT = 0.
STABLE_RELEASE = "v1"
CANARY_RELEASE = "v2"
CANARY_PERCENT = 0

# Log schema version.
#   1 = what was live for the first support drill.
#   2 = adds output_tags (diet claims found in the ANSWER), see diet_rules.py.
#       This is the field that turns the drill into a one-line search.
LOG_SCHEMA = 1
