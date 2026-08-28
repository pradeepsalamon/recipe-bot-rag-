# Error Analysis Taxonomy

Based on the 20 sampled traces, here is the ranked taxonomy of observed behaviors and failure modes.

| Mode Name | Count | Frequency | Severity | Example Trace ID |
| :--- | :--- | :--- | :--- | :--- |
| **Correct targeted extraction** | 8 | 40% | None (Expected behavior) | `14d7af70-60d5-4b3c-a147-a25e4e2b6e4a` |
| **Correct boundary refusal** | 5 | 25% | None (Expected behavior) | `6b510388-6aab-4a70-a82d-5b2601617dc6` |
| **Cross-recipe blending on ambiguous entity** | 2 | 10% | Annoys the cook | `8a034050-0e36-466f-85c9-94f95801359c` |
| **Retrieval miss for explicit metadata/steps** | 2 | 10% | Annoys the cook | `445c6b20-8491-423c-9e0f-23768490aaa3` |
| **Failure on implicit or cross-reference queries** | 2 | 10% | Annoys the cook | `8648dd14-234c-418d-9039-97238dcd6597` |
| **Partial recipe generation (omits ingredients)** | 1 | 5% | Ruins the dish | `1925e6ac-0f84-46fb-85f3-c9d2636ab033` |
