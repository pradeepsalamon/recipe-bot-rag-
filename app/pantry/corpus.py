"""
The recipe library, loaded once per process from data/recipes.json.

A recipe is addressed by its key: "<recipe_id>@<version>", e.g.
"shortbread@reformulated-2025". That key is the citation format, the chunk
prefix in the index, and the card filename. A citation that does not name the
version does not count (brief, requirement 1).
"""
import json
from functools import lru_cache

from . import config


def key(recipe_id, version):
    return f"{recipe_id}@{version}"


def split_key(k):
    recipe_id, _, version = k.partition("@")
    return recipe_id, version


@lru_cache(maxsize=1)
def _load():
    with open(config.RECIPES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    by_key = {key(r["recipe_id"], r["version"]): r for r in data["recipes"]}
    return data["allergen_codes"], by_key


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
    return config.CARDS_DIR / f"{k}.md"


def render_card(r):
    """Markdown card for one recipe-version. Citations link here."""
    k = key(r["recipe_id"], r["version"])
    lines = [f"# {r['title']}", "", f"`{k}` | status: **{r['status']}**"]
    if r.get("superseded_by"):
        lines.append(f"\n> SUPERSEDED by `{r['superseded_by']}`. Do not cook from this version.")
    if r.get("reformulation_note"):
        lines.append(f"\n> {r['reformulation_note']}")
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


def write_cards():
    config.CARDS_DIR.mkdir(parents=True, exist_ok=True)
    for r in all_recipes():
        k = key(r["recipe_id"], r["version"])
        card_path(k).write_text(render_card(r), encoding="utf-8")
    return len(all_recipes())
