# Verdict — Keep or Kill the Multi-Agent Orchestrator

**KILL the multi-agent orchestrator. Keep the single agent.**

The multi-agent arm used 14,988 tokens vs the single agent's 7,109 — a 2.1x cost multiplier — while achieving 10% (1/10) pass rate vs the single agent's 30% (3/10).
The p50 latency grew from 1153.0ms to 2309.7ms, and p99 from 1761.1ms to 3585.2ms.

**Sunk-cost bias acknowledgement:** We spent time building the orchestrator, the two workers, the synthesis prompt, and the hand-off logging. The natural inclination is to justify keeping the multi-agent system because we invested effort in it. This is the sunk-cost fallacy — the effort already spent is irrelevant to whether the system is worth running going forward. The numbers show it is not.

The single agent handles the full task in one call, avoids context re-send overhead, and delivers equivalent or better quality at a fraction of the cost and latency.