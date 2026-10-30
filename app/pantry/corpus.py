"""
The recipe library, loaded once per process from data/recipes.json.

A recipe is addressed by its key: "<recipe_id>@<version>", e.g.
"shortbread@reformulated-2025". That key is the citation format, the chunk
prefix in the index, and the card filename. A citation that does not name the
version does not count (brief, requirement 1).

Recipes the user uploaded (data/user_recipes.json, written by uploads.py) are
merged in as "u_<slug>@upload". They carry declared=False: there is no
allergen declaration behind them, and safety.py treats them that way. The
merge is keyed on that file's mtime, so the MCP server process picks up an
upload made by the API process without a restart.
"""
import json
import threading

from . import config

_cache = {}
_cache_lock = threading.Lock()


def key(recipe_id, version):
    return f"{recipe_id}@{version}"


def split_key(k):
    recipe_id, _, version = k.partition("@")
    return recipe_id, version


def user_stamp():
    """mtime of the uploads file, or None. Changes on every upload/delete."""
    if not config.UPLOADS_ENABLED:
        return None
    try:
        return config.USER_RECIPES_FILE.stat().st_mtime_ns
    except FileNotFoundError:
        return None


def read_user_file():
    if user_stamp() is None:
        return {"files": [], "recipes": []}
    with open(config.USER_RECIPES_FILE, encoding="utf-8") as f:
        return json.load(f)


def _load():
    stamp = (str(config.RECIPES_FILE), str(config.USER_RECIPES_FILE), user_stamp())
    with _cache_lock:
        if _cache.get("stamp") == stamp:
            return _cache["value"]
        with open(config.RECIPES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        by_key = {key(r["recipe_id"], r["version"]): r for r in data["recipes"]}
        for r in read_user_file()["recipes"]:
            by_key.setdefault(key(r["recipe_id"], r["version"]), r)   # never shadow the library
        _cache.update(stamp=stamp, value=(data["allergen_codes"], by_key))
        return _cache["value"]


def is_upload(r):
    return (r.get("source") or {}).get("kind") == "upload"


def allergen_codes():
    return _load()[0]


def all_recipes():
    return list(_load()[1].values())


def get(recipe_id, version):
    return _load()[1].get(key(recipe_id, version))


def get_by_key(k):
    return _load()[1].get(k)


def versions_of(recipe_id):
    return [r for r in all_recipes() if r["recipe_id"] == recipe_id]


def current_version(recipe_id):
    for r in versions_of(recipe_id):
        if r["status"] == "current":
            return r
    return None


def card_path(k):
    if k.startswith("u_"):   # uploads stay out of the committed cards dir
        return config.UPLOADS_DIR / "cards" / f"{k}.md"
    return config.CARDS_DIR / f"{k}.md"


def render_card(r):
    """Markdown card for one recipe-version. Citations link here."""
    k = key(r["recipe_id"], r["version"])
    lines = [f"# {r['title']}", "", f"`{k}` | status: **{r['status']}**"]
    if r.get("superseded_by"):
        lines.append(f"\n> SUPERSEDED by `{r['superseded_by']}`. Do not cook from this version.")
    if r.get("reformulation_note"):
        lines.append(f"\n> {r['reformulation_note']}")
    if r.get("declared") is False:
        lines.append(f"\n> Your upload ({r['source']['filename']}). Allergens NOT declared: "
                     f"check every ingredient label yourself.")
    lines += [
        "",
        f"**Contains:** {', '.join(r['allergens']) or 'none declared'}  ",
        f"**May contain:** {', '.join(r['may_contain']) or 'none declared'}  ",
        f"**Yield:** {r['yield']['amount']} {r['yield']['unit']}  ",
        f"**Times:** prep {r.get('prep_minutes', '?')} min, cook {r.get('cook_minutes', '?')} min"
        + (f", rest/soak {r['rest_minutes']} min" if r.get("rest_minutes") else ""),
        "",
        "## Ingredients",
    ]
    for i in r["ingredients"]:
        qty = "" if i["qty"] is None else f"{i['qty']} "
        lines.append(f"- {qty}{i['unit']} {i['item']}" if i["qty"] is not None else f"- {i['item']} ({i['unit']})")
    lines += ["", "## Method"]
    lines += [f"{n}. {s}" for n, s in enumerate(r["method"], 1)]
    if r.get("notes"):
        lines += ["", "## Notes", r["notes"]]
    lines += ["", f"_Declaration source: {r.get('declaration_source', '')}_", ""]
    return "\n".join(lines)


def write_cards(recipes=None):
    recipes = all_recipes() if recipes is None else recipes
    for r in recipes:
        path = card_path(key(r["recipe_id"], r["version"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_card(r), encoding="utf-8")
    return len(recipes)
