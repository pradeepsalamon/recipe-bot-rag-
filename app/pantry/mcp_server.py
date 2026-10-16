"""
pantry-server: the recipe library + allergen declarations over MCP.

The genuine capability a client gets here is the thing the publisher's
keyword search could not do: version-aware recipe search, and allergen
answers that come from the declaration fields by exact match.

Run it on its own (any MCP client can connect):
    python run.py serve-mcp                 # stdio
    python run.py serve-mcp --http 8799     # streamable HTTP on localhost

Every tool call is logged as a span in logs/mcp_spans.jsonl. If the caller
sends {"trace_id", "parent_span_id"} in the request _meta (our agent does),
the span joins that trace; otherwise it is logged under trace_id null.
"""
import json

from mcp.server.mcpserver import Context, MCPServer

from . import corpus, matching, retriever, safety
from .tracing import server_span

mcp = MCPServer(
    "pantry-server",
    log_level="WARNING",
    instructions=(
        "Recipe library of a recipe publisher. Recipes exist in versions; cite as recipe_id@version. "
        "Some recipes have an 'original' (superseded) and a 'reformulated-2025' (current) version with "
        "DIFFERENT allergens. Allergen answers must come from check_allergens, never from recipe text."
    ),
)


def _meta(ctx):
    try:
        m = ctx.request_context.meta
    except Exception:
        return {}
    if m is None:
        return {}
    return m if isinstance(m, dict) else m.model_dump()


def _out(sp, result):
    text = json.dumps(result, ensure_ascii=False)
    sp.attrs["result_chars"] = len(text)
    return text


# Inputs from clients we don't control: bound everything.
MAX_TEXT = 500
MAX_LIST = 20


class BadInput(ValueError):
    pass


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise BadInput(f"{field} must be a non-empty string")
    if len(value) > MAX_TEXT:
        raise BadInput(f"{field} is longer than {MAX_TEXT} characters")
    return value.strip()


def _list(value, field):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_LIST:
        raise BadInput(f"{field} must be a list of at most {MAX_LIST} strings")
    return [_text(v, field) for v in value]


def _guard(sp, fn):
    try:
        return fn()
    except BadInput as exc:
        sp.attrs["bad_input"] = True
        return _out(sp, {"error": str(exc)})


@mcp.tool()
def search_recipes(query: str, ctx: Context, exclude_allergens: list[str] | None = None, top_k: int = 5) -> str:
    """Search the recipe library (hybrid dense + keyword search). Returns recipe-versions as
    recipe_id@version with status (current / superseded). exclude_allergens drops any
    recipe-version whose allergen DECLARATION (contains or may-contain) matches, by exact match."""
    with server_span("search_recipes", _meta(ctx), stage="retrieval") as sp:
        def go():
            q, excl = _text(query, "query"), _list(exclude_allergens, "exclude_allergens")
            k = max(1, min(int(top_k or 5), 10))
            sp.attrs.update({"top_k": k, "exclude_allergen_codes": safety.normalise_allergies(excl)[0]})
            res = retriever.search(q, top_k=k, exclude_allergens=excl)
            sp.attrs["hits"] = [h["recipe"] for h in res["results"]]
            sp.attrs["chunks"] = [c for h in res["results"] for c in h["chunks"]]
            return _out(sp, res)
        return _guard(sp, go)


@mcp.tool()
def get_recipe(recipe_id: str, version: str, ctx: Context) -> str:
    """Full recipe-version: ingredients with quantities, method, yield, times, status and
    allergen declaration. version is e.g. 'original' or 'reformulated-2025'."""
    with server_span("get_recipe", _meta(ctx), stage="tool") as sp:
        r = corpus.get(recipe_id, version)
        sp.attrs["recipe"] = corpus.key(recipe_id, version)
        if r is None:
            known = [corpus.key(x["recipe_id"], x["version"]) for x in corpus.versions_of(recipe_id)]
            return _out(sp, {"error": f"No recipe {recipe_id}@{version}.", "known_versions": known})
        return _out(sp, dict(r, citation=corpus.key(recipe_id, version)))


@mcp.tool()
def check_allergens(recipe_id: str, version: str, allergies: list[str], ctx: Context) -> str:
    """Check a recipe-version against the user's allergies using the DECLARATION fields
    (contains + may-contain) by exact match. allergies are plain words or codes, e.g.
    ['nuts'], ['TREE_NUT','DAIRY']. 'nuts' means peanuts AND tree nuts.
    Verdict: SAFE / MAY_CONTAIN / UNSAFE. Terms it cannot map come back as unknown_allergen_terms."""
    with server_span("check_allergens", _meta(ctx), stage="safety") as sp:
        try:
            allergies = _list(allergies, "allergies")
        except BadInput as exc:
            return _out(sp, {"error": str(exc)})
        if not allergies:
            return _out(sp, {"error": "allergies is empty: pass the user's allergy words, e.g. ['nuts']"})
        codes, unknown = safety.normalise_allergies(allergies)
        sp.attrs.update({"recipe": corpus.key(recipe_id, version), "allergen_codes": codes,
                         "unknown_terms_count": len(unknown)})
        r = corpus.get(recipe_id, version)
        if r is None:
            return _out(sp, {"error": f"No recipe {recipe_id}@{version}."})
        res = safety.check_declaration(r, codes)
        res["unknown_allergen_terms"] = unknown
        sp.attrs["verdict"] = res["verdict"]
        return _out(sp, res)


@mcp.tool()
def find_substitution(ingredient: str, avoid: str, ctx: Context) -> str:
    """Test-kitchen substitutes for ONE ingredient to avoid ONE allergen (e.g. ingredient='butter',
    avoid='DAIRY'). Each option lists the substitute's own allergens and may-contain."""
    with server_span("find_substitution", _meta(ctx), stage="tool") as sp:
        res = safety.find_substitutions(ingredient, avoid)
        sp.attrs.update({"ingredient": ingredient, "avoid": res["avoid"], "options": len(res["options"])})
        return _out(sp, res)


@mcp.tool()
def safe_temperature(food: str, ctx: Context) -> str:
    """Minimum safe internal temperature (°C) from the food-safety chart for a food or
    category, e.g. 'chicken', 'minced beef', 'salmon'."""
    with server_span("safe_temperature", _meta(ctx), stage="safety") as sp:
        res = safety.safe_temperature(food)
        sp.attrs.update({"food": food, "found": res["found"]})
        return _out(sp, res)


@mcp.tool()
def match_pantry(have: list[str], ctx: Context, exclude_allergens: list[str] | None = None,
                 max_minutes: int | None = None) -> str:
    """Rank recipe-versions by how many of their ingredients the user already has. Optional
    exact-match allergen exclusion on the declaration fields and a total-time limit (minutes,
    prep + cook + rest)."""
    with server_span("match_pantry", _meta(ctx), stage="tool") as sp:
        def go():
            items, excl = _list(have, "have"), _list(exclude_allergens, "exclude_allergens")
            if not items:
                raise BadInput("have is empty: list the ingredients the user has")
            res = matching.match(items, exclude_allergens=excl, max_minutes=max_minutes)
            sp.attrs.update({"have_count": len(items), "exclude_allergen_codes": res["excluded_for"],
                             "hits": [h["recipe"] for h in res["results"]]})
            return _out(sp, res)
        return _guard(sp, go)


def serve(http_port=None):
    retriever.warm_in_background()   # model load overlaps the client's initialize
    if http_port:
        mcp.run(transport="streamable-http", port=http_port)
    else:
        mcp.run()


if __name__ == "__main__":
    serve()
