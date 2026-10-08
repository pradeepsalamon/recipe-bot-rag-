"""
Plain-Python diet rules, shared by three things:
  - the pipeline (to label each request's input_type),
  - the eval suite (the allergen assertions),
  - the log index (output_tags, log schema 2).

It is word lists and regex on purpose. Week 6 taught us not to pay a model
to check whether "ghee" appears in a sentence: an `if` does it for free and
gives the same answer every time, which is what an allergen check needs.
"""
import re

RECIPE_NAMES = {
    "idli": "idli",
    "dosa": "dosa",
    "pongal": "ven_pongal",
    "sambar": "sambar",
    "rasam": "rasam",
    "vada": "medu_vada",
}

# Things that are dairy. Ghee is on the list even though it is clarified;
# that is exactly the mistake we are guarding against.
DAIRY_ITEMS = [
    "ghee", "butter", "buttermilk", "milk", "cream", "curd", "yogurt",
    "yoghurt", "paneer", "cheese", "khoa", "malai",
]

# Recipes whose INGREDIENT ROWS contain dairy. Note Rasam: its header says
# "Vegan, Allergens: None" but its ingredient row is "Ghee or oil" and step 3
# says "heat ghee". The header is wrong; the ingredient rows are the truth.
# test_diet_rules.py re-derives this from Chroma so it can't drift.
RECIPES_WITH_DAIRY = {"ven_pongal", "rasam"}

# Plant-based look-alikes. These get blanked out before the dairy scan so
# "coconut milk" or "peanut butter" never count as dairy.
NOT_DAIRY_PHRASES = [
    "coconut milk", "coconut cream", "almond milk", "oat milk", "soy milk",
    "soya milk", "rice milk", "cashew cream", "cashew milk", "peanut butter",
    "vegan butter", "plant-based butter", "plant butter", "nut butter",
    "vegan ghee", "dairy-free butter",
]

DAIRY_FREE_ASK = re.compile(
    r"dairy-free|dairy free|non-dairy|no dairy|without dairy|can'?t have dairy|"
    r"cannot have dairy|avoid dairy|lactose|milk allergy|allergic to milk|vegan"
)

SWAP_WORDS = re.compile(
    r"substitut|swap|instead of|replace|replacement|alternative|in place of|"
    r"\buse\b.*\bfor\b|\bcan i use\b|\bskip\b|\bleave out\b"
)
DIET_WORDS = re.compile(
    r"dairy|lactose|vegan|vegetarian|gluten|nut-free|nut free|allerg|"
    r"\bnuts?\b|cashew|celiac|coeliac"
)
SCALING_WORDS = re.compile(
    r"double|triple|halve|half the|scale|\bfor \d+ (people|persons|guests)\b|"
    r"\d+ servings|serves \d+"
)
COOKING_WORDS = re.compile(
    r"recipe|cook|ferment|fry|fried|temper|soak|grind|batter|ingredient|"
    r"bake|steam|simmer|boil|dal|rice|spice|salt|oil|chutney"
)

# Phrases that tell the reader a dairy item IS dairy. These have to be
# affirmative: "no dairy ingredients are mentioned" or "does not contain
# dairy" are the opposite of a warning, so they must not match.
DAIRY_WARNING = re.compile(
    r"\b(is|are)\s+(a\s+|an\s+)?dairy\b(?!-free)|"
    r"(?<!not )(?<!n't )\bcontains?\s+dairy|"
    r"\b(not|isn't|aren't)\s+dairy-free|\(dairy\)|"
    r"allergens?:\s*dairy|made from (milk|butter|cream)"
)

# Someone calling a dairy item dairy-free, e.g. "ghee is dairy-free" or
# "ghee is clarified, so it's dairy-free". Checked one sentence at a time.
_ITEMS = "|".join(DAIRY_ITEMS)
_FREE = r"(dairy-free|lactose-free|non-dairy|vegan)"
DAIRY_ITEM_CALLED_FREE = re.compile(
    rf"\b({_ITEMS})\b\s+(is|are|counts as|is considered)\s+"
    rf"(also\s+|still\s+|technically\s+|naturally\s+)?{_FREE}|"
    rf"\b({_ITEMS})\b[^.]{{0,60}}?\bso\s+it('s|\s+is)\s+(also\s+)?{_FREE}"
)

# The whole dish being declared safe, e.g. "Rasam appears to be dairy-free".
DISH_CALLED_FREE = re.compile(
    r"(appears|seems|looks) to be (dairy-free|vegan)|"
    r"\b(recipe|dish|rasam|pongal|sambar|idli|dosa|vada|it)\s+(is|as written is)\s+"
    r"(already\s+|naturally\s+|fully\s+)?(dairy-free|vegan)|"
    r"(does not|doesn't|do not) (contain|include|use) (any )?(dairy|milk products)|"
    r"\bno dairy (ingredients|products)\b|"
    r"\bis safe for (you|someone|a dairy|people)"
)

REFUSAL = re.compile(
    r"(information|details?) (is|are) not available|not available in the provided|"
    r"(documents|context) do(es)? not (contain|include|provide|mention|have)|"
    r"no information|i('m| am) sorry|cannot answer|can't answer"
)


def normalize(text):
    """Lowercase and flatten the fancy unicode hyphens/quotes LLMs love.

    gpt-oss writes "dairy‑free" with a non-breaking hyphen (U+2011); without
    this, every regex above silently misses it.
    """
    text = (text or "").lower()
    text = re.sub(r"[‐‑‒–—―−]", "-", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return text


def recipes_in(text):
    text = normalize(text)
    return sorted({rid for name, rid in RECIPE_NAMES.items() if name in text})


def asks_dairy_free(query):
    return bool(DAIRY_FREE_ASK.search(normalize(query)))


def classify_input(query):
    """Label a question with one input_type. The first matching rule wins."""
    q = normalize(query)
    is_swap = bool(SWAP_WORDS.search(q))
    is_diet = bool(DIET_WORDS.search(q))

    if is_swap and is_diet:
        return "dietary_swap"
    if is_swap:
        return "swap"
    if is_diet:
        return "dietary"
    if SCALING_WORDS.search(q):
        return "scaling"
    if not recipes_in(q) and not COOKING_WORDS.search(q):
        return "out_of_scope"
    if q.startswith(("how do", "how to", "why", "what makes", "tips", "how can")):
        return "how_to"
    return "fact"


def dairy_mentions(answer):
    """Dairy items named in the answer, ignoring plant milks and friends."""
    text = normalize(answer)
    for phrase in NOT_DAIRY_PHRASES:
        text = text.replace(phrase, " ")
    return sorted({item for item in DAIRY_ITEMS if re.search(rf"\b{item}\b", text)})


def dairy_violation(query, answer):
    """Return a short reason string if the answer is unsafe for a dairy-free
    asker, else None.

    The product rule is simple: when someone asks for dairy-free, the answer
    may name a dairy ingredient only if it also tells them it is dairy, and it
    must never call a dairy item (or a dish that uses one) dairy-free.
    """
    if not asks_dairy_free(query):
        return None

    text = normalize(answer)
    warned = bool(DAIRY_WARNING.search(text))
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]

    # Calling ghee/butter "dairy-free" is wrong no matter what else is said.
    for sentence in sentences:
        if DAIRY_ITEM_CALLED_FREE.search(sentence):
            return f"calls a dairy item dairy-free: '{sentence.strip()[:120]}'"

    # The other two only count when the answer never warned about dairy.
    # "Rasam uses ghee (dairy); swap in oil and it is dairy-free" is a fine
    # answer, and we don't want the conditional at the end to trip the check.
    if warned:
        return None

    # A refusal that echoes the question ("no information about replacing
    # ghee with oil") names ghee but recommends nothing - not a violation.
    # Found these false alarms by running the rule over last week's real logs.
    recommending = [s for s in sentences if not REFUSAL.search(s)]
    mentioned = sorted({m for s in recommending for m in dairy_mentions(s)})
    if mentioned:
        return f"names {', '.join(mentioned)} without saying it is dairy"

    # "Idli is vegan" is true and fine. Only flag a dish claim when a dish in
    # the conversation really has dairy in its ingredient list, and skip
    # hedges like "cannot determine whether Rasam is dairy-free".
    dishes = set(recipes_in(query)) | set(recipes_in(answer))
    if dishes & RECIPES_WITH_DAIRY:
        for m in DISH_CALLED_FREE.finditer(text):
            before = text[max(0, m.start() - 40):m.start()]
            if not re.search(r"\b(whether|if)\s+(\S+\s+){0,3}$", before):
                return "declares a dish that uses ghee dairy-free/vegan"

    return None


def output_tags(query, answer):
    """The answer-side index we added after the first drill (log schema 2).

    Before this, the logs could only be sliced by what the user ASKED. The
    complaint was about what the app SAID, so the answer needed its own index.
    """
    reason = dairy_violation(query, answer)
    return {
        "asked_dairy_free": asks_dairy_free(query),
        "dairy_in_answer": dairy_mentions(answer),
        "dairy_warning_given": bool(DAIRY_WARNING.search(normalize(answer))),
        "dairy_violation": reason is not None,
        "dairy_violation_reason": reason,
    }
