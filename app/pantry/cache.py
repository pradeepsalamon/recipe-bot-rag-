"""
Semantic answer cache: serve a stored answer when a new question means the
same as one answered recently. OFF unless PANTRY_CACHE=1.

This is the dangerous kind of cache: a wrong answer that gets in is served
instantly to everyone who asks something similar. Week 11 measured 6/121
hits (-4.4% cost) with diet questions excluded. In this app most questions
carry an allergy, so expect a lower hit rate. The rules (week 11's, tightened
for allergens and reformulations):

  NEVER LOOKED UP OR STORED
  1. Any question that mentions an allergen, a diet ("dairy-free", "vegan"),
     a health condition, a substitution, or doneness/food safety. Those
     answers depend on checks that must run every time.
  SERVED ONLY IF
  2. Cosine similarity >= 0.88 (MiniLM; week 11: real paraphrases >= 0.898,
     different-recipe questions <= 0.79).
  3. The same recipes are named ("idli" vs "dosa" differ by one word).
  4. The same numbers appear ("for 8" vs "for 12" scored 0.952 in week 11).
  5. Same fingerprint: hash of the prompt, the model, the release AND the
     recipe/substitution/food-safety data. A reformulation edits
     data/recipes.json, which changes the fingerprint, so every answer
     written before it stops matching. This is the shortbread rule.
  6. Younger than ttl_hours.
  STORED ONLY IF
  7. The answer finished normally, is not a refusal, cites at least one
     valid recipe-version, cites no superseded version and proposes no
     substitution.

Every hit is logged with the trace id of the request that produced the
answer, so a bad cached answer can still be traced back to its source.
"""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from . import config, corpus, safety
from .tracing import _HEALTH

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_CONSTRAINT = re.compile(
    r"(?i)\b(allerg\w*|intoleran\w*|[\w-]+-free|free from|vegan|vegetarian|halal|kosher|diet\w*|"
    r"substitut\w*|swap\w*|replace\w*|instead of|without|"
    r"safe\w*|done(ness)?|undercook\w*|raw|pink|temperature|°|degrees|cooked through|food poisoning)\b")
_GENERIC = {"recipe", "classic", "with", "and", "the", "quick", "simple", "baked", "reformulated", "2025",
            "lemon", "thyme", "honey", "oat", "basil", "style", "elumichai", "sadam"}


def skip_reason(question):
    """Why this question must never touch the cache (None = eligible)."""
    if _CONSTRAINT.search(question):
        return "constraint, substitution or food-safety question"
    if _HEALTH.search(question):
        return "health statement"
    for pattern, _codes in safety._SYNONYMS:
        if re.search(pattern, question.lower()):
            return "mentions an allergen"
    return None


@lru_cache(maxsize=1)
def _recipe_keywords():
    kw = {}
    for r in corpus.all_recipes():
        words = set(re.findall(r"[a-z]+", (r["title"] + " " + r["recipe_id"].replace("_", " ")).lower()))
        kw.setdefault(r["recipe_id"], set()).update(w for w in words if len(w) > 3 and w not in _GENERIC)
    return kw


def recipes_in(text):
    words = set(re.findall(r"[a-z]+", text.lower()))
    return sorted(rid for rid, kws in _recipe_keywords().items() if kws & words)


def numbers_in(text):
    return sorted(_NUMBER.findall(text))


def store_reason(final):
    """Why this answer must not be stored (None = storable)."""
    if final.get("refused") or final.get("terminated") or final.get("parse_error"):
        return "refused, stopped or unparsed"
    if final.get("invalid_citations"):
        return "invalid citation"
    cites = final.get("citations") or []
    if not cites:
        return "no citation"
    if any((corpus.get_by_key(c) or {}).get("status") == "superseded" for c in cites):
        return "cites a superseded version"
    if final.get("substitutions"):
        return "proposes a substitution"
    return None


def fingerprint(model=None):
    """Changes whenever anything that shapes an answer changes."""
    h = hashlib.sha256()
    prompt = config.APP_DIR / "prompts" / config.release_settings()["prompt"]
    for path in (prompt, config.RECIPES_FILE, config.SUBSTITUTIONS_FILE, config.FOOD_SAFETY_FILE):
        h.update(path.read_bytes())
    h.update(f"{model or config.AGENT_MODEL}|{config.RELEASE}".encode())
    return h.hexdigest()[:16]


def _default_embed(text):
    from . import retriever
    emb = retriever.query_embedder()
    return emb(text)


def _unit(v):
    import math
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class SemanticCache:
    def __init__(self, path=None, embed=None, fp=None, now=None):
        self.path = path or config.CACHE["path"]
        self.embed = embed or _default_embed
        self.fp = fp or fingerprint()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.entries = self._load()

    def _fresh(self, e):
        age = self._now() - datetime.fromisoformat(e["created_at"])
        return e["fingerprint"] == self.fp and age <= timedelta(hours=config.CACHE["ttl_hours"])

    def _load(self):
        if not self.path.exists():
            return []
        entries = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if self._fresh(e):
                    entries.append(e)
        return entries[-config.CACHE["max_entries"]:]

    def lookup(self, question):
        """(entry, similarity) for the best servable entry, or (None, best_similarity)."""
        if not self.entries:
            return None, 0.0
        v = _unit(self.embed(question))
        recipes, numbers = recipes_in(question), numbers_in(question)
        best, best_sim, top_sim = None, 0.0, 0.0
        for e in self.entries:
            if not self._fresh(e):
                continue
            sim = sum(a * b for a, b in zip(v, e["vector"]))
            top_sim = max(top_sim, sim)
            if (sim >= config.CACHE["threshold"] and sim > best_sim
                    and e["recipes"] == recipes and e["numbers"] == numbers):
                best, best_sim = e, sim
        return (best, round(best_sim, 4)) if best else (None, round(top_sim, 4))

    def store(self, question, final, trace_id, cost_usd, latency_ms):
        if skip_reason(question) or store_reason(final):
            return False
        entry = {
            "created_at": self._now().isoformat(timespec="seconds"),
            "fingerprint": self.fp,
            "question": question,
            "recipes": recipes_in(question),
            "numbers": numbers_in(question),
            "final": {k: final[k] for k in ("answer", "citations", "recommended") if k in final},
            "source_trace_id": trace_id,
            "source_cost_usd": cost_usd,
            "source_latency_ms": latency_ms,
            "vector": [round(x, 6) for x in _unit(self.embed(question))],
        }
        self.entries.append(entry)
        self.entries = self.entries[-config.CACHE["max_entries"]:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True

    def clear(self):
        n = len(self.entries)
        self.entries = []
        if self.path.exists():
            self.path.unlink()
        return n

    def stats(self):
        return {"entries_live": len(self.entries), "fingerprint": self.fp, "path": str(self.path)}
