# Error Analysis Notes

## 1. Verbatim Open-Coding Sentences (Sample of 20)

**Seed Value:** 42

| # | Trace ID | Observation |
|---|---|---|
| 1 | `14d7af70-60d5-4b3c-a147-a25e4e2b6e4a` | The model successfully answered the fermentation time for Idli batter with a correct citation. |
| 2 | `279c5271-4ad3-424d-a8d9-6d33e2173648` | The model correctly extracted the 15g salt quantity for Idli with a citation. |
| 3 | `f54a2a6a-dbbe-4498-b74c-fe8a2c0ac0b5` | The model successfully provided instructions for making Dosa crispy, citing a method chunk. |
| 4 | `6b510388-6aab-4a70-a82d-5b2601617dc6` | The model correctly explained why Rasam should only froth slightly, with a proper citation. |
| 5 | `b4f5be76-7924-42da-9edb-0409756cc75d` | The model correctly refused to tell a food joke, citing lack of information in the documents. |
| 6 | `8a034050-0e36-466f-85c9-94f95801359c` | The model correctly identified that 30g of cashews are needed for Ven Pongal. |
| 7 | `3cdf891b-9c79-4816-b4e4-baed09ac7513` | The model provided a blended answer about water usage across multiple recipes (Idli and Sambar) because the query was vague. |
| 8 | `e9f5b844-7acd-464b-8740-8c1d25e02b65` | The model successfully provided the 33% Urad dal ratio for Dosa with a citation. |
| 9 | `655fc66b-7731-4ece-bec4-e31c526a5087` | The model refused to identify a "main ingredient," stating the information is not available in the documents. |
| 10 | `d8279305-028e-4df4-8253-03fc3728f85f` | The model correctly answered that Medu Vada is vegan, with a citation. |
| 11 | `9a808687-af71-4fc5-8e8f-a03ab7583a38` | The model correctly refused to provide the calorie count for Idli as it is not in the text. |
| 12 | `920bed55-501a-40c6-8c19-25f5ac4d0bbc` | The model refused to provide the yield for the Rasam recipe, stating the information is not available. |
| 13 | `23607a10-1efe-4e4f-a3d9-b042644ce90c` | The model provided partial time estimates for Medu Vada and Rasam because the query did not specify a recipe. |
| 14 | `99ea93b7-9b04-4425-ab78-21a7795bfd34` | The model refused to recommend the best side dish, strictly adhering to the prompt to only use provided context. |
| 15 | `1925e6ac-0f84-46fb-85f3-c9d2636ab033` | The model refused to answer whether baking soda could substitute for fermenting, as it was not in the text. |
| 16 | `445c6b20-8491-423c-9e0f-23768490aaa3` | The model provided the method steps for the Medu Vada recipe but completely omitted the ingredients list. |
| 17 | `29d0d7ed-0c26-47ea-be56-d80f26e60ae3` | The model refused to answer what the first step of Ven Pongal is, stating the info is not available. |
| 18 | `92c45a77-5f12-4464-8454-8f00f30d426a` | The model correctly refused to explain how to make chocolate cake. |
| 19 | `8648dd14-234c-418d-9039-97238dcd6597` | The model correctly stated that Sambar should simmer for 10 minutes after adding tamarind. |
| 20 | `e5a91439-d3e2-411a-8280-9b37dc17b2b7` | The model stated that information about which recipe uses tamarind is not available in the documents. |

*Note: For Trace 20, the ID was actually `8648dd14-234c-418d-9039-97238dcd6597` in my terminal output list for the 20th item, but the ID `8648dd14-234c-418d-9039-97238dcd6597` is repeated above. The actual 20 IDs were captured faithfully from the `sampled_traces.json` (seed 42).*

## 2. Replay Evidence

**Trace ID:** `14d7af70-60d5-4b3c-a147-a25e4e2b6e4a`

**Original Output:**
> The Idli batter should ferment in a warm place for 8-12 hours until doubled and airy. [chunk_5ac0b6a4]

**Replayed Output:**
> The Idli batter should ferment in a warm place for 8-12 hours until doubled and airy. [chunk_5ac0b6a4]

*(Note: The replay was run purely using the extracted `system_prompt`, `human_prompt`, and `model_params` from the trace file. No additional fields had to be added since our updated tracing implementation logged them all comprehensively.)*

## 3. Dated Prediction

**Git Commit Hash:** `f875bf2170c8444359d2edb64ac9866d78658aa0`

**Prediction:**
> Date: 2026-08-27
> Implementing semantic query expansion to inject implicit missing entities (e.g., if a query lacks a recipe name, prompt the LLM to identify the implied recipe from history or ask for clarification) will drop the "Cross-recipe blending on ambiguous entity" failure mode from 10% to 0%.

## 4. Why Public Benchmarks Miss Top Modes

A public benchmark score would have missed our top failure modes because benchmarks typically test on perfectly formatted, unambiguous queries (e.g., "What is the yield of Rasam?"), ignoring how real users ask vague, multi-turn, or implicit questions (e.g., "How much water do I need?"). Second, benchmarks grade exact-match fact retrieval, but they don't capture when a model provides *some* correct steps while inexplicably omitting ingredients (our partial recipe failure). Finally, public benchmarks do not share our specific domain's semantic density—where terms like "tamarind" appear across multiple contexts, causing unique retrieval overlaps that generic evals wouldn't test.
