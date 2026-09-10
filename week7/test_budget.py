"""
Week 7 Task Set B — Budget Termination Test

Demonstrates that budget enforcement works by using a deliberately low
max_iterations limit (2) to trigger clean budget termination.
"""

import os, sys, json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent import run_agent


def test_budget_termination():
    """Test that max_iterations budget fires and terminates the agent cleanly."""
    print("=" * 60)
    print("BUDGET TERMINATION TEST")
    print("=" * 60)
    print("Setting max_iters=2 to force budget termination.")
    print("The agent needs 3+ steps for complex requests, so it will be cut short.\n")

    log_lines = []
    def logger(msg):
        log_lines.append(msg)
        print(msg)

    # Complex request that requires search + scale + substitute = 3+ steps
    result = run_agent(
        "Make the Ven Pongal recipe for 8 servings, dairy-free and nut-free.",
        request_id="budget_test",
        max_iters=2,       # Deliberately low
        max_tokens=30000,
        max_cost=0.10,
        max_wall_clock=120,
        log_callback=logger,
    )

    print(f"\n{'='*60}")
    print("BUDGET TEST RESULT")
    print(f"{'='*60}")
    print(f"  terminated_by: {result['terminated_by']}")
    print(f"  iterations: {result['metrics']['iterations']}")
    print(f"  total_tokens: {result['metrics']['total_tokens']}")
    print(f"  cost: ${result['metrics']['cost']}")
    print(f"  latency: {result['metrics']['latency_ms']}ms")

    # Assertions
    assert result["terminated_by"] == "max_iterations", \
        f"Expected termination by max_iterations, got {result['terminated_by']}"
    assert result["metrics"]["iterations"] <= 2, \
        f"Expected <= 2 iterations, got {result['metrics']['iterations']}"

    print(f"\n✓ Budget termination test PASSED")
    print(f"  Agent was correctly terminated after {result['metrics']['iterations']} iterations")
    print(f"  Budget: max_iterations=2, actual={result['metrics']['iterations']}")

    # Save log
    log_path = os.path.join(os.path.dirname(__file__), "budget_termination_log.txt")
    with open(log_path, "w") as f:
        f.write("\n".join(log_lines))
        f.write(f"\n\n[BUDGET TEST RESULT]\n")
        f.write(f"terminated_by={result['terminated_by']}\n")
        f.write(f"iterations={result['metrics']['iterations']}\n")
        f.write(f"total_tokens={result['metrics']['total_tokens']}\n")
        f.write(f"cost=${result['metrics']['cost']}\n")
    print(f"\n  Log saved to: {log_path}")

    return result


if __name__ == "__main__":
    test_budget_termination()
