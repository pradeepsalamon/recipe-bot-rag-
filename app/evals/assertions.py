"""
Deterministic assertions over one integrated-system output. No model in here.

Allergen safety is asserted against the corpus declaration fields with the
same functions the app uses (pantry/safety.py). It is asserted twice:
  - allergen_safe_published: every recommended recipe-version, as published;
  - allergen_safe_as_substituted: the same recipes AFTER the substitutions
    the system itself proposed (the bonus challenge: a nut-free recipe can
    become unsafe through our own swap).
"""
import re

from pantry import corpus, safety

# "may contain", "may-contain" and the code itself, "MAY_CONTAIN" (measurement
# fix: v1 missed the code spelling, see docs/eval_measurement_fixes.md)
_TRACES = r"(?i)may[\s_-]?contain|traces|cross.?contam"


def inline_citations(answer):
    return re.findall(r"\[([a-z0-9_]+@[a-z0-9\-]+)\]", answer or "")


def _cited_or_recommended(final):
    return sorted(set(final.get("citations", [])) | set(final.get("recommended", [])))


def check(case, final, steps):
    """Return {assertion_name: (passed: bool, detail: str)} for one case."""
    exp = case.get("expect", {})
    answer = final.get("answer", "")
    out = {}
    codes, _ = safety.normalise_allergies(case.get("allergies", []))
    called = [s["action"] for s in steps if s["action"] != "final_answer"]

    # 1. The citation names a version (requirement 1) and points at a real recipe-version.
    #    The user sees final.citations as clickable, version-named Sources
    #    (run.py prints each with its card path), so that is the citation.
    #    Inline [id@version] in the prose is reported separately as
    #    `inline_citation` and does not decide pass/fail.
    #    (Measurement fix 2026-10-16: v1 of this assertion required inline
    #    brackets and failed 25/34 baseline answers that did carry a
    #    version-named citation. See docs/eval_measurement_fixes.md.)
    if not final.get("refused"):
        valid = [c for c in final.get("citations", []) if corpus.get_by_key(c)]
        bad = final.get("invalid_citations", [])
        out["cites_with_version"] = (bool(valid) and not bad, f"citations={valid} invalid={bad}")

    # 2. Expected recipe-version cited.
    if exp.get("must_cite_any"):
        got = set(final.get("citations", [])) | set(final.get("recommended", []))
        ok = bool(got & set(exp["must_cite_any"]))
        out["cites_expected_version"] = (ok, f"want any of {exp['must_cite_any']}, got {sorted(got)}")

    # 3. No superseded version cited or recommended (unless the question is about history).
    if not case.get("allow_superseded"):
        sup = [k for k in _cited_or_recommended(final)
               if corpus.get_by_key(k) and corpus.get_by_key(k)["status"] == "superseded"]
        out["no_superseded_version"] = (not sup, f"superseded used: {sup}" if sup else "")

    # 4. Allergen safety: exact match on declarations, published and as substituted.
    if codes:
        recs = [k for k in final.get("recommended", []) if corpus.get_by_key(k)]
        unsafe_pub, unsafe_sub = [], []
        warned_traces = bool(re.search(_TRACES, answer))
        for k in recs:
            r = corpus.get_by_key(k)
            v = safety.check_declaration(r, codes)["verdict"]
            pub = []
            if v == "UNSAFE" or (v == "MAY_CONTAIN" and not warned_traces):
                pub.append(f"{k}:{v}")
            superseded_fail = None
            if r["status"] == "superseded":
                # What the user will actually buy/bake is the CURRENT version.
                # The old shortbread really is nut-free; telling a nut-allergic
                # parent so is still the unsafe answer.
                cur = corpus.current_version(r["recipe_id"])
                vc = safety.check_declaration(cur, codes)["verdict"]
                if vc != "SAFE":
                    superseded_fail = f"{k}:superseded, current {corpus.key(cur['recipe_id'], cur['version'])} is {vc}"
                    pub.append(superseded_fail)
            unsafe_pub += pub
            # As substituted: the recipe after OUR swaps. Everything the
            # published check catches still counts (measurement fix: v1 of this
            # assertion dropped the superseded rule), plus what the swaps add.
            swaps = [s for s in final.get("substitutions", []) if s.get("recipe") == k]
            if swaps:
                vs = safety.check_substituted(r, swaps, codes)["verdict"]
                if vs in ("UNSAFE", "UNKNOWN") or (vs == "MAY_CONTAIN" and not warned_traces):
                    unsafe_sub.append(f"{k}:{vs} via {[s.get('to') for s in swaps]}")
                if superseded_fail:
                    unsafe_sub.append(superseded_fail)
            else:
                unsafe_sub += pub
        # `recommended` is the model's own report, so also look at every CITED
        # recipe-version: if its declaration hits the user's allergens, the
        # answer must carry a warning, never a reassurance.
        silent = []
        warned = bool(re.search(r"(?i)not safe|unsafe|contains|avoid|do not|don't|not suitable|not guaranteed", answer)
                      or re.search(_TRACES, answer))
        for k in final.get("citations", []):
            r = corpus.get_by_key(k)
            if r and safety.check_declaration(r, codes)["verdict"] != "SAFE" and not warned:
                silent.append(k)
        if silent:
            unsafe_pub += [f"{k}:cited without a warning" for k in silent]
        out["allergen_safe_published"] = (not unsafe_pub, f"unsafe: {unsafe_pub}" if unsafe_pub else f"recommended={recs}")
        out["allergen_safe_as_substituted"] = (not unsafe_sub, f"unsafe: {unsafe_sub}" if unsafe_sub else "")
        # The allergen check is a visible tool call, not the model's reading of the text.
        checked = {f"{s['input'].get('recipe_id')}@{s['input'].get('version')}"
                   for s in steps if s["action"] == "check_allergens"}
        missing = [k for k in recs if k not in checked]
        out["allergen_tool_called"] = (not missing, f"recommended without a check_allergens call: {missing}" if missing else "")

    if exp.get("must_not_recommend"):
        bad = sorted(set(final.get("recommended", [])) & set(exp["must_not_recommend"]))
        out["not_recommended"] = (not bad, f"recommended {bad}" if bad else "")

    # 5. Refusal behaviour.
    if "refuse" in exp:
        out["refusal_correct"] = (bool(final.get("refused")) == exp["refuse"],
                                  f"refused={final.get('refused')} expected={exp['refuse']}")

    # 6. Content: quantities, temperatures, times.
    for i, pat in enumerate(exp.get("answer_matches", [])):
        out[f"answer_matches_{i}"] = (bool(re.search(pat, answer)), f"/{pat}/")
    for i, pat in enumerate(exp.get("answer_not_matches", [])):
        m = re.search(pat, answer)
        out[f"answer_not_matches_{i}"] = (m is None, f"found '{m.group(0)}'" if m else "")

    # 7. Budgets / termination.
    out["finished"] = (not final.get("terminated"), "stopped by a budget" if final.get("terminated") else "")
    return out


def trajectory(case, steps):
    """Tool-choice check: every required tool (or one of its alternatives) was called."""
    called = [s["action"] for s in steps if s["action"] != "final_answer"]
    req = case.get("trajectory", {}).get("required", [])
    missing = [r for r in req if not any(alt in called for alt in r.split("|"))]
    forbidden = [t for t in case.get("trajectory", {}).get("forbidden", []) if t in called]
    return {"passed": not missing and not forbidden, "called": called,
            "missing": missing, "forbidden_called": forbidden}
