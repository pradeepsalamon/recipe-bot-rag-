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

from . import config, corpus, matching, retriever, safety
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


# --------------------------------------------------------------------------
# Implementations (shared by every release)
# --------------------------------------------------------------------------
def _search(ctx, query, exclude_allergens, top_k, include_superseded):
    with server_span("search_recipes", _meta(ctx), stage="retrieval") as sp:
        def go():
            q, excl = _text(query, "query"), _list(exclude_allergens, "exclude_allergens")
            k = max(1, min(int(top_k or 5), 10))
            sp.attrs.update({"top_k": k, "exclude_allergen_codes": safety.normalise_allergies(excl)[0],
                             "include_superseded": include_superseded})
            res = retriever.search(q, top_k=k, exclude_allergens=excl, include_superseded=include_superseded)
            sp.attrs["hits"] = [h["recipe"] for h in res["results"]]
            sp.attrs["chunks"] = [c for h in res["results"] for c in h["chunks"]]
            return _out(sp, res)
        return _guard(sp, go)


def _get(ctx, recipe_id, version):
    with server_span("get_recipe", _meta(ctx), stage="tool") as sp:
        r = corpus.get(recipe_id, version)
        sp.attrs["recipe"] = corpus.key(recipe_id, version)
        if r is None:
            known = [corpus.key(x["recipe_id"], x["version"]) for x in corpus.versions_of(recipe_id)]
            return _out(sp, {"error": f"No recipe {recipe_id}@{version}.", "known_versions": known})
        out = dict(r, citation=corpus.key(recipe_id, version))
        if config.feature("current_version_guard") and r["status"] == "superseded":
            out["warning"] = (f"SUPERSEDED: do not cook from, recommend or check allergens on this version. "
                              f"The recipe people cook today is {r['superseded_by']}.")
        return _out(sp, out)


def _check(ctx, recipe_id, version, allergies, substitutions):
    with server_span("check_allergens", _meta(ctx), stage="safety") as sp:
        try:
            allergies = _list(allergies, "allergies")
            if substitutions is not None and (not isinstance(substitutions, list) or len(substitutions) > MAX_LIST):
                raise BadInput(f"substitutions must be a list of at most {MAX_LIST} from/to objects")
        except BadInput as exc:
            return _out(sp, {"error": str(exc)})
        if not allergies:
            return _out(sp, {"error": "allergies is empty: pass the user's allergy words, e.g. ['nuts']"})
        codes, unknown = safety.normalise_allergies(allergies)
        asked = corpus.key(recipe_id, version)
        sp.attrs.update({"recipe": asked, "allergen_codes": codes, "unknown_terms_count": len(unknown)})
        r = corpus.get(recipe_id, version)
        if r is None:
            return _out(sp, {"error": f"No recipe {asked}."})

        guard = config.feature("current_version_guard") and r["status"] == "superseded"
        target = corpus.get_by_key(r["superseded_by"]) if guard else r
        swaps = [s for s in (substitutions or []) if isinstance(s, dict)]
        if swaps:
            res = safety.check_substituted(target, swaps, codes)
            res["published_verdict"] = safety.check_declaration(target, codes)["verdict"]
            sp.attrs["swaps"] = len(swaps)
        else:
            res = safety.check_declaration(target, codes)
        if guard:
            res["asked_about"] = asked
            res["asked_version_verdict"] = safety.check_declaration(r, codes)["verdict"]
            res["note"] = (f"{asked} is SUPERSEDED. The verdict above is for the current version "
                           f"{res['recipe']}, which is what people buy and cook today. Cite that version.")
        res["unknown_allergen_terms"] = unknown
        sp.attrs["verdict"] = res["verdict"]
        return _out(sp, res)


def _pantry(ctx, have, exclude_allergens, max_minutes, include_superseded):
    with server_span("match_pantry", _meta(ctx), stage="tool") as sp:
        def go():
            items, excl = _list(have, "have"), _list(exclude_allergens, "exclude_allergens")
            if not items:
                raise BadInput("have is empty: list the ingredients the user has")
            res = matching.match(items, exclude_allergens=excl, max_minutes=max_minutes,
                                 include_superseded=include_superseded)
            sp.attrs.update({"have_count": len(items), "exclude_allergen_codes": res["excluded_for"],
                             "hits": [h["recipe"] for h in res["results"]]})
            return _out(sp, res)
        return _guard(sp, go)


# --------------------------------------------------------------------------
# Tools. The release decides the signatures, so v1 keeps exactly the schema
# its baseline was measured with.
# --------------------------------------------------------------------------
_SEARCH_DOC = ("Search the recipe library (hybrid dense + keyword search). Returns recipe-versions as "
               "recipe_id@version with status (current / superseded). exclude_allergens drops any "
               "recipe-version whose allergen DECLARATION (contains or may-contain) matches, by exact match.")
_CHECK_DOC = ("Check a recipe-version against the user's allergies using the DECLARATION fields "
              "(contains + may-contain) by exact match. allergies are plain words or codes, e.g. "
              "['nuts'], ['TREE_NUT','DAIRY']. 'nuts' means peanuts AND tree nuts. "
              "Verdict: SAFE / MAY_CONTAIN / UNSAFE. Terms it cannot map come back as unknown_allergen_terms.")
_PANTRY_DOC = ("Rank recipe-versions by how many of their ingredients the user already has. Optional "
               "exact-match allergen exclusion on the declaration fields and a total-time limit (minutes, "
               "prep + cook + rest).")

if config.feature("hide_superseded"):
    @mcp.tool(description=_SEARCH_DOC + " Superseded versions are left out (listed in hidden_superseded) "
              "unless include_superseded=true; set it only when the user asks about an old version or "
              "what changed.")
    def search_recipes(query: str, ctx: Context, exclude_allergens: list[str] | None = None, top_k: int = 5,
                       include_superseded: bool = False) -> str:
        return _search(ctx, query, exclude_allergens, top_k, include_superseded)

    @mcp.tool(description=_PANTRY_DOC + " Superseded versions are left out unless include_superseded=true.")
    def match_pantry(have: list[str], ctx: Context, exclude_allergens: list[str] | None = None,
                     max_minutes: int | None = None, include_superseded: bool = False) -> str:
        return _pantry(ctx, have, exclude_allergens, max_minutes, include_superseded)
else:
    @mcp.tool(description=_SEARCH_DOC)
    def search_recipes(query: str, ctx: Context, exclude_allergens: list[str] | None = None, top_k: int = 5) -> str:
        return _search(ctx, query, exclude_allergens, top_k, True)

    @mcp.tool(description=_PANTRY_DOC)
    def match_pantry(have: list[str], ctx: Context, exclude_allergens: list[str] | None = None,
                     max_minutes: int | None = None) -> str:
        return _pantry(ctx, have, exclude_allergens, max_minutes, True)

if config.feature("substitution_check"):
    @mcp.tool(description=_CHECK_DOC + ' If you are proposing substitutions, pass them as '
              'substitutions=[{"from": ingredient, "to": substitute}] and the check runs on the recipe '
              'AS SUBSTITUTED. On a superseded version the verdict is for the current version.')
    def check_allergens(recipe_id: str, version: str, allergies: list[str], ctx: Context,
                        substitutions: list[dict[str, str]] | None = None) -> str:
        return _check(ctx, recipe_id, version, allergies, substitutions)
else:
    @mcp.tool(description=_CHECK_DOC)
    def check_allergens(recipe_id: str, version: str, allergies: list[str], ctx: Context) -> str:
        return _check(ctx, recipe_id, version, allergies, None)


@mcp.tool(description="Full recipe-version: ingredients with quantities, method, yield, times, status and "
                      "allergen declaration. version is e.g. 'original' or 'reformulated-2025'.")
def get_recipe(recipe_id: str, version: str, ctx: Context) -> str:
    return _get(ctx, recipe_id, version)


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


def serve(http_port=None):
    retriever.warm_in_background()   # model load overlaps the client's initialize
    if http_port:
        mcp.run(transport="streamable-http", port=http_port)
    else:
        mcp.run()


if __name__ == "__main__":
    serve()
