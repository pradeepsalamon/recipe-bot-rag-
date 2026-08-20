# Ask My Recipes - Evaluation Results

## 1. Eight Evaluation Questions

**Question:** How much salt is used in the Idli recipe?
- **Known correct recipe:** idli
- **Known correct section:** Ingredients
- **Expected answer:** 15 g

**Question:** What is the ratio % of Urad dal in the Dosa recipe?
- **Known correct recipe:** dosa
- **Known correct section:** Ingredients
- **Expected answer:** 33%

**Question:** How many cashews are needed for Ven Pongal?
- **Known correct recipe:** ven_pongal
- **Known correct section:** Ingredients
- **Expected answer:** 30 g

**Question:** How long should the Idli batter ferment?
- **Known correct recipe:** idli
- **Known correct section:** Method
- **Expected answer:** 8-12 hours

**Question:** What is the first step in making Ven Pongal?
- **Known correct recipe:** ven_pongal
- **Known correct section:** Method
- **Expected answer:** Dry roast moong dal lightly until fragrant

**Question:** How long should the Sambar simmer after adding the tamarind pulp?
- **Known correct recipe:** sambar
- **Known correct section:** Method
- **Expected answer:** 10 minutes

**Question:** What is the yield for the Rasam recipe?
- **Known correct recipe:** rasam
- **Known correct section:** Meta
- **Expected answer:** 4 servings

**Question:** Why should Rasam only froth slightly when ready?
- **Known correct recipe:** rasam
- **Known correct section:** Notes
- **Expected answer:** preserves its flavor (simmered not boiled)

## 2. Chunking Comparison

| Question | Current Chunker (Baseline) | Structure-Aware |
|----------|----------------------------|-----------------|
| Q1 | Hit | Hit |
| Q2 | Hit | Hit |
| Q3 | Miss | Hit |
| Q4 | Miss | Hit |
| Q5 | Miss | Miss |
| Q6 | Hit | Hit |
| Q7 | Hit | Hit |
| Q8 | Hit | Hit |

**Current chunker:** 5/8
**Structure-aware chunker:** 7/8

### Detailed Top-5 Search Results (Structure-Aware)

**Q1**: How much salt is used in the Idli recipe?
  1. Recipe: idli, Score: 0.033, Chunk: chunk_cf0e597b
  2. Recipe: idli, Score: 0.029, Chunk: chunk_5ac0b6a4
  3. Recipe: idli, Score: 0.029, Chunk: chunk_8a4b7501
  4. Recipe: dosa, Score: 0.028, Chunk: chunk_dd7ac2d9
  5. Recipe: idli, Score: 0.016, Chunk: chunk_cde47aaa

**Q2**: What is the ratio % of Urad dal in the Dosa recipe?
  1. Recipe: dosa, Score: 0.031, Chunk: chunk_3e14d0f5
  2. Recipe: dosa, Score: 0.031, Chunk: chunk_51a1c54b
  3. Recipe: medu_vada, Score: 0.031, Chunk: chunk_3ef6aa60
  4. Recipe: idli, Score: 0.030, Chunk: chunk_cf0e597b
  5. Recipe: idli, Score: 0.028, Chunk: chunk_694d9ca3

**Q3**: How many cashews are needed for Ven Pongal?
  1. Recipe: ven_pongal, Score: 0.032, Chunk: chunk_f97ed4c6
  2. Recipe: ven_pongal, Score: 0.032, Chunk: chunk_0df1a3f4
  3. Recipe: ven_pongal, Score: 0.029, Chunk: chunk_7b726153
  4. Recipe: idli, Score: 0.028, Chunk: chunk_a515bd88
  5. Recipe: ven_pongal, Score: 0.027, Chunk: chunk_9e8ccac0

**Q4**: How long should the Idli batter ferment?
  1. Recipe: idli, Score: 0.030, Chunk: chunk_9ea03312
  2. Recipe: idli, Score: 0.030, Chunk: chunk_cf0e597b
  3. Recipe: idli, Score: 0.029, Chunk: chunk_5ac0b6a4
  4. Recipe: idli, Score: 0.029, Chunk: chunk_836ac807
  5. Recipe: sambar, Score: 0.028, Chunk: chunk_0f691769

**Q5**: What is the first step in making Ven Pongal?
  1. Recipe: ven_pongal, Score: 0.031, Chunk: chunk_f97ed4c6
  2. Recipe: ven_pongal, Score: 0.031, Chunk: chunk_9f569565
  3. Recipe: ven_pongal, Score: 0.028, Chunk: chunk_82a9ddca
  4. Recipe: idli, Score: 0.026, Chunk: chunk_5ac0b6a4
  5. Recipe: ven_pongal, Score: 0.016, Chunk: chunk_8b5a14d9

**Q6**: How long should the Sambar simmer after adding the tamarind pulp?
  1. Recipe: sambar, Score: 0.033, Chunk: chunk_d6fbc2ec
  2. Recipe: sambar, Score: 0.032, Chunk: chunk_0f691769
  3. Recipe: sambar, Score: 0.031, Chunk: chunk_326038db
  4. Recipe: sambar, Score: 0.029, Chunk: chunk_ba8a9b32
  5. Recipe: rasam, Score: 0.029, Chunk: chunk_1fbe81fa

**Q7**: What is the yield for the Rasam recipe?
  1. Recipe: rasam, Score: 0.029, Chunk: chunk_1747994c
  2. Recipe: rasam, Score: 0.029, Chunk: chunk_217d25f9
  3. Recipe: rasam, Score: 0.029, Chunk: chunk_b9862ae4
  4. Recipe: rasam, Score: 0.028, Chunk: chunk_f16abe83
  5. Recipe: rasam, Score: 0.028, Chunk: chunk_1fbe81fa

**Q8**: Why should Rasam only froth slightly when ready?
  1. Recipe: rasam, Score: 0.033, Chunk: chunk_e5789868
  2. Recipe: rasam, Score: 0.031, Chunk: chunk_1747994c
  3. Recipe: rasam, Score: 0.029, Chunk: chunk_f16abe83
  4. Recipe: medu_vada, Score: 0.029, Chunk: chunk_fe17c5d7
  5. Recipe: rasam, Score: 0.029, Chunk: chunk_80b0320d

## 3. Metadata Filtering

**Query:** How do I make Ven Pongal?

**Unfiltered results (Top 3)**
- chunk_id: chunk_f97ed4c6 | score: 0.031 | recipe: ven_pongal
- chunk_id: chunk_9f569565 | score: 0.031 | recipe: ven_pongal
- chunk_id: chunk_f7716941 | score: 0.031 | recipe: ven_pongal

**Filtered results (Dietary Tags contains 'Vegan') (Top 3)**

*Notice how Ven Pongal is excluded in the filtered results because it is not Vegan.*

## 4. Grounded Generation

**Question:** How much salt is used in the Idli recipe?
**Answer:** The information is not available in the provided recipe documents.

**Context Chunks Used:**
- chunk_cf0e597b (idli)
- chunk_5ac0b6a4 (idli)
- chunk_8a4b7501 (idli)

**Question:** What is the ratio % of Urad dal in the Dosa recipe?
**Answer:** The ratio % of Urad dal in the Dosa recipe is 33%. [chunk_3e14d0f5]

**Context Chunks Used:**
- chunk_3e14d0f5 (dosa)
- chunk_51a1c54b (dosa)
- chunk_3ef6aa60 (medu_vada)

**Question:** How many cashews are needed for Ven Pongal?
**Answer:** For Ven Pongal, 30 g of cashews are needed. [chunk_7b726153]

**Context Chunks Used:**
- chunk_f97ed4c6 (ven_pongal)
- chunk_0df1a3f4 (ven_pongal)
- chunk_7b726153 (ven_pongal)

## 5. Refusal Transcripts

**Question:** What is the exact calorie count of the Idli recipe?
**Response:** The information regarding the exact calorie count of the Idli recipe is not available in the provided recipe documents.

**Question:** How much protein does the Sambar contain?
**Response:** The information is not available in the provided recipe documents.

**Question:** What is the vitamin C content of the Rasam?
**Response:** The information is not available in the provided recipe documents.

## 6. Chunker Decision

The **Structure-Aware Chunker** should be kept. By logically grouping recipe components (e.g. attaching the Recipe Title and Table Headers to every ingredient row), it prevents critical information from being orphaned. The baseline chunker often splits ingredient amounts from the context of what ingredient they belong to, or separates an ingredient list from the actual recipe name, leading to missing context during vector retrieval.

## 7. Retrieval Failure Analysis

*(Automatically documented based on results)*

**Failed Question:** How much salt is used in the Idli recipe?
Top retrieved chunk did not contain the exact expected answer, or semantic similarity prioritized method steps over ingredients.