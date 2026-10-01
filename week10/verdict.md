# Verdict — Keep or Kill the Multi-Agent Orchestrator

**KILL the multi-agent orchestrator. Keep the single agent.**

The multi-agent arm used 14,052 tokens vs the single agent's 6,857 — a 2.0x cost multiplier — while achieving 10% (1/10) pass rate vs the single agent's 30% (3/10).
The p50 latency grew from 850.3ms to 2050.6ms, and p99 from 953.1ms to 2551.0ms.

**Sunk-cost bias acknowledgement:** We spent time building the orchestrator, the two workers, the synthesis prompt, and the hand-off logging. The natural inclination is to justify keeping the multi-agent system because we invested effort in it. This is the sunk-cost fallacy — the effort already spent is irrelevant to whether the system is worth running going forward. The numbers show it is not.

The single agent handles the full task in one call, avoids context re-send overhead, and delivers equivalent or better quality at a fraction of the cost and latency.