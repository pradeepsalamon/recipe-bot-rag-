<!-- Soft Suave · The AI Engineering League -->
# Week 12 Capstone — Variant B

## Pantry-to-Plate Assistant

| | |
|---|---|
| Domain | Recipes & food |
| Duration | Week 12 — Monday to Friday, 1 hr/day + the Friday demo |
| Marks | 100 |
| Gate | **M6 — end-to-end app + closed loop → AI Summit & certification** |

> **Nothing new to learn — deliberately.** This is an integration and defence of eleven weeks of artifacts you already have. If you find yourself building something new, that's anxiety, not engineering.


---

## 1. The brief

The client is a recipe publisher with a 600-recipe library, a test kitchen, and a legal team that has become nervous. Their app already lets people search recipes; what users actually want is to ask in plain language — "what can I make with what's in the fridge, my kid is allergic to nuts, and I have 25 minutes" — and the current keyword search cannot do it. Last quarter a supplier change forced them to reformulate 80 recipes, and for six weeks their own site served both the old and new versions, which is how a nut-free shortbread stopped being nut-free without anyone updating the page. They want a system that answers cooking questions from THEIR library with a citation to the recipe and its version, checks allergens against the declaration field rather than inferring them from the prose, scales quantities correctly, and refuses to guess about safety. The stakes here are not embarrassment. The thing they will ask you on Friday is which of your eval cases has an allergy in it, and what it scores.

### Corpus

The 600-recipe CMS export — ingredients with quantities and units, method steps, yield, prep and cook times — plus the structured allergen and "may contain" declarations attached to each recipe as fields, the test kitchen's substitutions table, the food-safety chart of safe internal temperatures (chicken 74°C, and the rest), and the 80 recipes that exist in BOTH an original and a reformulated-2025 version after the supplier change. The two versions are the point: the reformulated shortbread swapped butter for a nut-oil blend, so citing the superseded version tells a nut-allergic parent it is safe. The allergen declarations are structured fields on purpose — they are an exact-match problem wearing a semantic-search costume, and treating them as prose is this domain's defining mistake.


---

## 2. Requirements

1. Your Week 3–4 RAG pipeline, wired in behind the single entry point and answering a real cooking question with clickable citations to recipe id — the citation must name WHICH version (original or reformulated-2025) it used, or it does not count as a citation here
2. Your Week 7 hand-built agent loop, running against the integrated retriever with at least three tools — recipe search, allergen/substitution lookup, and a scaling calculator — of which the tools reachable over MCP are discovered at runtime, not hardcoded
3. One MCP server of your own exposing a genuine capability (your recipe + allergen search is the obvious one), called live by a client that isn't yours — Thursday's fresh-eyes reviewer from another squad is that client
4. Your Week 6 eval suite running against the INTEGRATED system in one command: 25–40 cases, assertions before judges, and your validated judge re-checked on integrated outputs — report its agreement against your hand labels as a number, and it must still clear 85%
5. Your Week 5 error taxonomy re-scored on the integrated system: 4–7 named modes with frequency %, severity, and one trace id each. At least one mode must be NEW — created by integration, not inherited from the parts
6. Your Week 8 trajectory eval over 10+ cases on the integrated agent, reporting tool-choice accuracy and your outcome-vs-trajectory gap as numbers — the gap is the honest one, so show it even when it embarrasses you
7. Week 11 per-request logging surviving both the agent hop and the MCP hop: one trace id from question in to answer out, cost and latency per span, and the PII line held — a user's stated allergies are health data, so decide deliberately what you write down
8. One closed failure→test loop demonstrated live on the integrated system, plus cost per query and a 10× plan naming what breaks first at 50,000 queries a day, with the number behind it


---

## 3. Expected output

One repo a stranger can clone and run — one command, one entry point — containing the integrated system, the eval suite that runs against it, Tuesday's unedited seam list, the one-page architecture sketch, the eval report with its stated non-coverage, the top-3 weaknesses you wrote down on Wednesday before anyone asked, and the 10-minute demo script. Plus the demo, delivered live to the clock.


---

## 4. Evaluation rubric

| Criterion | Points |
|---|---|
| Failure-finding & error analysis — the integrated system's taxonomy with frequencies and trace ids, the traces you actually read, and the top 3 weaknesses you wrote down before anyone asked. A demo where nothing failed scores zero here. | 30 |
| A number that moved — before → after on a named metric, with sample size, judge-agreement rate, and an explicit statement of what your suite does NOT cover. Adjectives score zero. | 25 |
| Integration completeness — RAG + agent + MCP consumed AND exposed + evals + logging behind one entry point, from one command, with one trace id surviving every hop. No points for UI. No points for polish. No points for "it works". | 20 |
| Application depth — does it behave like it has actually worked a kitchen: allergens checked against the declaration field rather than the prose, the reformulated version named in the citation, quantities scaled without silently scaling the cook time, and safe internal temperatures never quietly dropped. | 15 |
| Iteration thinking — what you'd do next, ranked and costed: the closed failure→test loop, the cost/query number, and the 10× plan naming what breaks first. | 10 |
| **Total** | **100** |


---

## 5. The 10-minute demo — the four-part standard

1. Part 1 — a real run: a live pantry-and-allergy question in, the allergen declaration checked via a visible tool call, the answer citing the recipe id AND its version, a correctly scaled quantity, and one question that gets an honest refusal rather than a guess.
2. Part 2 — the failures you found: the trace where it served the pre-reformulation shortbread to a nut-allergy query (or whatever your top mode turned out to be), its frequency in the re-scored taxonomy, the mode that integration created, and the two other weaknesses you wrote down on Wednesday before anyone asked.
3. Part 3 — a number that moved: allergen-unsafe answer rate before → after, with n, the judge's agreement rate on the integrated system's outputs, and one sentence on what your suite does not measure at all.
4. Part 4 — what's next: the eval case that now permanently guards that failure, cost per query, and what breaks first at 50,000 queries a day — named, with the number that proves it, not a shrug.

*A flawless demo is a red flag. Show the failure you found and how you know it's fixed.*


---

## 6. Hostile questions you will be asked

- A parent with a nut-allergic child asks about the shortbread and gets the pre-reformulation version. Which of your eval cases covers that, how many are there, and what do they score — not your average, those cases.
- "May contain traces" is a legal declaration on a field, not a sentence for a retriever to feel its way through. Does your system exact-match the allergen fields, or is it embedding a paragraph and hoping? Show me the assertion.
- It told someone to cook the chicken until "golden and cooked through" and never said 74°C. Is that a pass or a fail in your suite — and if it's a pass, who signed off on that being acceptable?
- You scaled the recipe 4×. Did the bake time scale 4× too? Show me the trace, and show me the eval case that would have caught it if it had.
- This is a consumer app at 50,000 queries a day, not a demo at fifty. What's the cost per query, and what breaks first when it's 500,000?


---

## 7. Bonus challenge

Allergen safety through the substitution chain. When the user asks "what can I make from my pantry", your system will suggest substitutions — and the allergen check must run over the recipe AS SUBSTITUTED, not the recipe as published. Build the eval case where a genuinely nut-free recipe becomes unsafe because of a swap your own system proposed, watch it go red, then close it. Report how many of your previously-passing pantry cases fail once the check moves downstream of your own suggestion.


---

## 8. Submission checklist

- [ ] One command that runs the integrated system end to end, plus the README a stranger actually used
- [ ] Tuesday's seam list, unedited, each seam marked fixed / accepted / ran-out-of-time
- [ ] The one-page architecture sketch: boxes, arrows, where the model calls happen, where the money goes
- [ ] Full eval-suite output on the integrated system: pass rate per taxonomy mode, n, and the judge-agreement number
- [ ] The re-scored error taxonomy, with the mode integration created called out
- [ ] Trajectory eval results + the outcome-vs-trajectory gap
- [ ] One end-to-end trace with cost and latency per span, trace id intact across the agent and MCP hops
- [ ] Your top 3 known weaknesses, dated Wednesday, unprompted
- [ ] Cost per query + the 10× plan naming the first thing that breaks
- [ ] The fresh-eyes note: who from which squad ran it, where they stumbled, what you changed


---

## 9. Common mistakes

- **Re-embedding all 600 recipes on Tuesday with a better model because the ingredient chunks bothered you — Week 12 is four hours and nothing new to learn. The Week-4 retriever with a measured hit-rate ships; the better one you cannot score by Friday does not.**
- **Demoing the risotto that works. A flawless demo is a red flag: the rubric pays 30 points for the allergen near-miss you caught and zero for the run that never breaks.**
- **Treating "may contain traces of nuts" as prose for the embedder to handle. It is a declaration on a structured field — an exact-match assertion, not a cosine similarity. If you can assert it, never judge it, and never leave it to a retriever's top-5.**
- **Letting the LLM judge score allergen safety. Allergen correctness is assertable and binary; you are paying a model to be probabilistic about the one thing in this domain that must never be probabilistic, and the judge's 87% agreement means 13% of the time it's wrong about anaphylaxis.**
- **Dropping the pre-reformulation recipe versions from the index so the superseded-citation mode vanishes from your taxonomy. The client's CMS still has both. You hid the evidence, not the bug.**
- **Presenting "the model suggested a clever substitution" as your result. The panel wants the trace where your own substitution reintroduced the allergen, and the eval case that now catches it.**


---

*Variant B of 6. All six are equivalent in difficulty and graded on the same rubric.*
