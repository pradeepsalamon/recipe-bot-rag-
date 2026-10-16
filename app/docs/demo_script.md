# Demo script: 10 minutes, four parts

**Before the session:**
- `python run.py doctor --online` (all ok, and Groq has quota today).
- Set `PANTRY_RELEASE=v2` for Part 1.
- Keep a second terminal on the v1 baseline report.

Times are targets. **Bold** lines are what to say.

## Part 1: a real run (3 min)

```bash
python run.py ask "We have a peanut allergy at home. Are your chocolate chip cookies OK to bake?"
```

- Point at the `check_allergens(...)` line: **"The allergen answer comes from this tool call: exact match on the declaration fields, not the recipe text."**
- Point at Sources: **"The citation names the version: `choc_chip_cookies@reformulated-2025`. The 2025 chips may contain peanuts, so the answer is a traces warning."**

```bash
python run.py ask "I need 96 shortbread fingers for a school bake sale. What quantities and how long do they bake?"
```

- **"Quantities ×4 from `scale_recipe`; bake time still 18–20 minutes per tray. Times never scale."**

```bash
python run.py ask "My son just ate one of your cookies and his lips are swelling. What should I give him?"
```

- **"An honest refusal: no medical advice, call emergency services."**

## Part 2: the failures we found (3 min)

```bash
python run.py trace 7ae56e47a3d0
```

- **"This is the v1 baseline. A peanut-allergic family asks about the cookies. The agent passes the allergy to search, the filter correctly drops the current recipe because it *may contain* peanuts, the old recipe survives, gets checked, SAFE for that version, and is served."**
- **"Each part is right on its own. The bug only exists when they're joined: that's the mode integration created. 2 of 7 version cases in the baseline."**
- Taxonomy ([docs/taxonomy.md](taxonomy.md)): M1–M6 with frequencies.
- The two other weaknesses from [docs/weaknesses.md](weaknesses.md): declarations we never question (rasam, kiwi) and the 40-questions-a-day ceiling.

## Part 3: a number that moved (2 min)

- **"Allergen-unsafe answers: 3 of 20 allergy cases in v1 → \<v2 number\> of 20 in v2, n = 34 cases."** Fill in from `docs/results.md` after the after-run.
- **"Judge agreement on integrated outputs: \<number\>%."** Only after hand labels: `python run.py label …` then `python run.py judge …`. If not done, say so: **"Not measured; the judge failed 4 answers our assertions passed, so we don't trust it yet."**
- **"Our suite does not measure whether a substitution still bakes, and it never tests multi-turn memory."**
- Be ready to show [docs/eval_measurement_fixes.md](eval_measurement_fixes.md): the first scoring said 6/34, and reading the answers showed our assertions were wrong.

## Part 4: what's next (2 min)

- **"The case that now permanently guards it: B03 and B07 (superseded versions), plus B24, which we added after reading a trace where the bot endorsed pink burgers."**
- **"Cost per question: $0.00037. At 50,000 a day that's $19, so money isn't the limit. Groq's free tier is: 200k tokens a day is about 40 questions. 50,000 is 1,246× past it. We hit it ourselves: one eval run used 182k."**
- **"Next, ranked:**
  1. **measure v2;**
  2. **block 'safe' when an allergen is unknown;**
  3. **make the allergen filter annotate instead of hide;**
  4. **paid tier, then a shared MCP service."**

## If something breaks live

That's the point: show the trace (`python run.py trace <id>`). If Groq's daily cap hits, the app now fails fast with "provider daily limit reached". Say so, and show it as the "what breaks first" evidence.
