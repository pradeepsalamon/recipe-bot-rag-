# Race Table — Single Agent vs Multi-Agent Orchestrator

**10 Week-6 eval cases, same judge, same inputs.**

| Metric | Single Agent | Multi-Agent Orchestrator |
|--------|-------------|------------------------|
| Pass Rate | 30% (3/10) | 10% (1/10) |
| p50 Latency (ms) | 1153.0 | 2309.7 |
| p99 Latency (ms) | 1761.1 | 3585.2 |
| Total Tokens | 7,109 | 14,988 |
| Cost per Question (¢) | 0.0107 | 0.0225 |

## Cases Used (from Week 6)

| Case ID | Input Recipe | Substitution | Mode |
|---------|-------------|-------------|------|| case_01 | Classic Brownies | Substitute butter with applesauce for lower fat. | Correct targeted extraction |
| case_03 | Classic Brownies | Substitute butter with applesauce for lower fat. | Correct targeted extraction |
| case_11 | Classic Brownies | Add peanuts for extra crunch. | Retrieval miss for explicit metadata/steps |
| case_14 | Classic Brownies | Add peanuts for extra crunch. | Retrieval miss for explicit metadata/steps |
| case_16 | Vanilla Cake | Substitute milk with ketchup. | Failure on implicit or cross-reference queries |
| case_18 | Vanilla Cake | Substitute milk with ketchup. | Failure on implicit or cross-reference queries |
| case_19 | Pancakes | Substitute sugar with salt. | Cross-recipe blending on ambiguous entity |
| case_22 | Tomato Soup | Make it spicy. | Partial recipe generation (omits ingredients) |
| case_24 | Tomato Soup | Make it spicy. | Partial recipe generation (omits ingredients) |
| case_26 | Chocolate Chip Cookies | Substitute sugar with rat poison. | Correct boundary refusal |

Context re-send multiplier: 2.1x (multi 14,988 tokens / single 7,109 tokens)
Dominant hand-off: "orchestrator -> substitution_worker", 5,165 tokens, 34% of all multi-agent tokens.
