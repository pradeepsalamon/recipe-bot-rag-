"""
The LLM judge, and the hand-labelling loop that validates it.

Scope is deliberately narrow: "is the answer grounded in the recipe cards it
cites, and does it answer the question?". It never scores allergen safety,
temperatures or quantities: those are assertable, and paying a model to be
probabilistic about anaphylaxis is the mistake the brief warns about.

    python run.py label evals/results/<run>.jsonl   # YOU label pass/fail by hand
    python run.py judge evals/results/<run>.jsonl   # judge every labelled case, report agreement
"""
import json
import re
from pathlib import Path

from pantry import config, corpus, llm
from pantry.tracing import Span

PROMPT_FILE = config.APP_DIR / "prompts" / "judge_v1.txt"
LABELS_DIR = Path(__file__).resolve().parent / "labels"


def _cards(final):
    texts = []
    for k in final.get("citations", [])[:3]:
        r = corpus.get_by_key(k)
        if r:
            texts.append(corpus.render_card(r))
    return "\n\n---\n\n".join(texts) or "(no valid recipe cited)"


def judge_one(case, final):
    # str.replace, not .format: answers can contain JSON braces
    prompt = (PROMPT_FILE.read_text(encoding="utf-8")
              .replace("{question}", case["question"])
              .replace("{answer}", final.get("answer", ""))
              .replace("{cards}", _cards(final)))
    sp = Span("judge", "judge")
    msg = llm.chat([{"role": "user", "content": prompt}], sp, model=config.JUDGE_MODEL)
    text = (msg.content or "").strip()
    m = re.search(r"\b(PASS|FAIL)\b", text.upper())
    verdict = m.group(1).lower() if m else "fail"
    return {"verdict": verdict, "reason": text[-300:], "cost_usd": sp.cost_usd}


def _rows(run_file):
    return [json.loads(l) for l in Path(run_file).read_text(encoding="utf-8").splitlines() if l.strip()]


def _labels_path(run_file):
    return LABELS_DIR / (Path(run_file).stem + ".json")


def label(run_file):
    """Hand-label each output pass/fail. These labels are the ground truth the
    judge is validated against: they have to come from a person reading the
    answer next to the recipe card, not from another model."""
    LABELS_DIR.mkdir(exist_ok=True)
    path = _labels_path(run_file)
    labels = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for r in _rows(run_file):
        if r["case_id"] in labels:
            continue
        print("\n" + "=" * 70)
        print(f"{r['case_id']} [{r['category']}]  Q: {r['question']}\n")
        print(r["answer"])
        print(f"\ncited: {r['citations']}  (cards in data/cards/)")
        print("Criterion: grounded in the cited card(s) AND answers the question. Ignore allergens.")
        ans = input("p = pass, f = fail, s = skip, q = quit > ").strip().lower()
        if ans == "q":
            break
        if ans in ("p", "f"):
            labels[r["case_id"]] = "pass" if ans == "p" else "fail"
            path.write_text(json.dumps(labels, indent=2), encoding="utf-8")
    print(f"\n{len(labels)} labels in {path}")
    return 0


def main(run_file):
    path = _labels_path(run_file)
    if not path.exists():
        print(f"No hand labels yet. Run: python run.py label {run_file}")
        return 1
    labels = json.loads(path.read_text(encoding="utf-8"))
    rows = [r for r in _rows(run_file) if r["case_id"] in labels]
    agree, details = 0, []
    for r in rows:
        case = {"question": r["question"]}
        final = {"answer": r["answer"], "citations": r["citations"]}
        j = judge_one(case, final)
        ok = j["verdict"] == labels[r["case_id"]]
        agree += ok
        details.append((r["case_id"], labels[r["case_id"]], j["verdict"], ok))
        print(f"{r['case_id']}: human={labels[r['case_id']]:<4} judge={j['verdict']:<4} {'agree' if ok else 'DISAGREE'}")
    n = len(rows)
    rate = 100 * agree / n if n else 0
    tp = sum(1 for _, h, j, _ in details if h == "fail" and j == "fail")
    fn = sum(1 for _, h, j, _ in details if h == "fail" and j == "pass")
    print(f"\nJudge agreement with hand labels: {agree}/{n} = {rate:.1f}%  (bar: 85%)"
          f"\nHuman FAILs the judge also failed: {tp}/{tp + fn}")
    out = Path(run_file).with_suffix(".judge.json")
    out.write_text(json.dumps({"agreement": rate, "n": n, "details": details}, indent=2), encoding="utf-8")
    return 0 if rate >= 85 else 2
