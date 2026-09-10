"""
Week 7 Task Set B — Race Evaluation Runner

Runs the same 10 requests through both Agent and Fixed Workflow.
Measures pass rate, p50 latency, total tokens, cost/request.
Generates race.csv and a summary comparison.
"""

import os, sys, json, csv, time, statistics

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent import run_agent
from workflow import run_workflow
from evaluator import evaluate_response


def load_requests():
    """Load the 10 evaluation requests."""
    requests_path = os.path.join(os.path.dirname(__file__), "recipe_requests.json")
    with open(requests_path, "r") as f:
        return json.load(f)


def run_race():
    """Run the full race evaluation."""
    requests = load_requests()
    print(f"Loaded {len(requests)} evaluation requests.\n")

    results = []
    agent_latencies = []
    workflow_latencies = []
    agent_passed = 0
    workflow_passed = 0
    agent_total_tokens = 0
    workflow_total_tokens = 0
    agent_total_cost = 0.0
    workflow_total_cost = 0.0

    # Collect logs
    agent_logs = {}
    workflow_logs = {}

    for req in requests:
        req_id = req["id"]
        request_text = req["request"]
        expected = req["expected"]
        category = req["category"]

        print(f"\n{'='*70}")
        print(f"REQUEST {req_id} [{category}]: {request_text}")
        print(f"{'='*70}")

        # --- Run Agent ---
        print(f"\n--- AGENT ---")
        log_lines = []
        def agent_logger(msg):
            log_lines.append(msg)
            print(msg)

        try:
            agent_result = run_agent(
                request_text,
                request_id=f"agent_{req_id}",
                log_callback=agent_logger,
                max_iters=10,
                max_tokens=30000,
                max_cost=0.10,
                max_wall_clock=120,
            )
            agent_response = agent_result["response"]
            agent_metrics = agent_result["metrics"]
            agent_error = None
            agent_terminated = agent_result.get("terminated_by")
        except Exception as e:
            agent_response = None
            agent_metrics = {"iterations": 0, "total_input_tokens": 0, "total_output_tokens": 0,
                             "total_tokens": 0, "cost": 0, "latency_ms": 0}
            agent_error = str(e)
            agent_terminated = "error"
            print(f"  AGENT ERROR: {e}")

        agent_logs[req_id] = "\n".join(log_lines)

        # --- Run Workflow ---
        print(f"\n--- WORKFLOW ---")
        log_lines = []
        def workflow_logger(msg):
            log_lines.append(msg)
            print(msg)

        try:
            workflow_result = run_workflow(
                request_text,
                request_id=f"workflow_{req_id}",
                log_callback=workflow_logger,
            )
            workflow_response = workflow_result["response"]
            workflow_metrics = workflow_result["metrics"]
            workflow_error = None
        except Exception as e:
            workflow_response = None
            workflow_metrics = {"iterations": 0, "total_input_tokens": 0, "total_output_tokens": 0,
                                "total_tokens": 0, "cost": 0, "latency_ms": 0}
            workflow_error = str(e)
            print(f"  WORKFLOW ERROR: {e}")

        workflow_logs[req_id] = "\n".join(log_lines)

        # --- Evaluate Both ---
        agent_eval = evaluate_response(agent_response, expected)
        workflow_eval = evaluate_response(workflow_response, expected)

        a_passed = agent_eval["passed"]
        w_passed = workflow_eval["passed"]

        if a_passed:
            agent_passed += 1
        if w_passed:
            workflow_passed += 1

        agent_latencies.append(agent_metrics["latency_ms"])
        workflow_latencies.append(workflow_metrics["latency_ms"])
        agent_total_tokens += agent_metrics["total_tokens"]
        workflow_total_tokens += workflow_metrics["total_tokens"]
        agent_total_cost += agent_metrics["cost"]
        workflow_total_cost += workflow_metrics["cost"]

        print(f"\n  AGENT:    {'PASS' if a_passed else 'FAIL'} (score={agent_eval['score']}) | {agent_metrics['latency_ms']}ms | {agent_metrics['total_tokens']} tokens | ${agent_metrics['cost']}")
        if not a_passed:
            failed = [k for k, v in agent_eval["checks"].items() if not v["passed"]]
            print(f"    Failed checks: {failed}")
        if agent_terminated:
            print(f"    Terminated by: {agent_terminated}")

        print(f"  WORKFLOW: {'PASS' if w_passed else 'FAIL'} (score={workflow_eval['score']}) | {workflow_metrics['latency_ms']}ms | {workflow_metrics['total_tokens']} tokens | ${workflow_metrics['cost']}")
        if not w_passed:
            failed = [k for k, v in workflow_eval["checks"].items() if not v["passed"]]
            print(f"    Failed checks: {failed}")

        results.append({
            "request_id": req_id,
            "category": category,
            "request": request_text,
            # Agent
            "agent_passed": a_passed,
            "agent_score": agent_eval["score"],
            "agent_latency_ms": agent_metrics["latency_ms"],
            "agent_input_tokens": agent_metrics["total_input_tokens"],
            "agent_output_tokens": agent_metrics["total_output_tokens"],
            "agent_total_tokens": agent_metrics["total_tokens"],
            "agent_cost": agent_metrics["cost"],
            "agent_error": agent_error,
            "agent_terminated": agent_terminated,
            "agent_eval_checks": agent_eval["checks"],
            # Workflow
            "workflow_passed": w_passed,
            "workflow_score": workflow_eval["score"],
            "workflow_latency_ms": workflow_metrics["latency_ms"],
            "workflow_input_tokens": workflow_metrics["total_input_tokens"],
            "workflow_output_tokens": workflow_metrics["total_output_tokens"],
            "workflow_total_tokens": workflow_metrics["total_tokens"],
            "workflow_cost": workflow_metrics["cost"],
            "workflow_error": workflow_error,
            "workflow_eval_checks": workflow_eval["checks"],
        })

    # --- Calculate aggregate metrics ---
    n = len(requests)
    agent_p50 = round(statistics.median(agent_latencies), 1) if agent_latencies else 0
    workflow_p50 = round(statistics.median(workflow_latencies), 1) if workflow_latencies else 0
    agent_cost_per_req = round(agent_total_cost / n, 6) if n > 0 else 0
    workflow_cost_per_req = round(workflow_total_cost / n, 6) if n > 0 else 0

    summary = {
        "agent": {
            "pass_rate": f"{agent_passed}/{n} = {agent_passed/n*100:.0f}%",
            "p50_latency_ms": agent_p50,
            "total_tokens": agent_total_tokens,
            "cost_per_request": agent_cost_per_req,
            "total_cost": round(agent_total_cost, 6),
        },
        "workflow": {
            "pass_rate": f"{workflow_passed}/{n} = {workflow_passed/n*100:.0f}%",
            "p50_latency_ms": workflow_p50,
            "total_tokens": workflow_total_tokens,
            "cost_per_request": workflow_cost_per_req,
            "total_cost": round(workflow_total_cost, 6),
        },
    }

    # --- Write race.csv ---
    csv_path = os.path.join(os.path.dirname(__file__), "race.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "system", "request_id", "category", "passed", "latency_ms",
            "input_tokens", "output_tokens", "total_tokens", "cost", "error"
        ])
        for r in results:
            writer.writerow([
                "agent", r["request_id"], r["category"], r["agent_passed"],
                r["agent_latency_ms"], r["agent_input_tokens"], r["agent_output_tokens"],
                r["agent_total_tokens"], r["agent_cost"], r["agent_error"] or ""
            ])
            writer.writerow([
                "workflow", r["request_id"], r["category"], r["workflow_passed"],
                r["workflow_latency_ms"], r["workflow_input_tokens"], r["workflow_output_tokens"],
                r["workflow_total_tokens"], r["workflow_cost"], r["workflow_error"] or ""
            ])

    # --- Write detailed results JSON ---
    details_path = os.path.join(os.path.dirname(__file__), "race_details.json")
    with open(details_path, "w") as f:
        json.dump({"summary": summary, "results": results}, f, indent=2, default=str)

    # --- Write agent/workflow logs ---
    logs_path = os.path.join(os.path.dirname(__file__), "race_logs.txt")
    with open(logs_path, "w") as f:
        for req_id in agent_logs:
            f.write(f"\n{'='*70}\n")
            f.write(f"AGENT — {req_id}\n")
            f.write(f"{'='*70}\n")
            f.write(agent_logs[req_id])
            f.write(f"\n\n{'='*70}\n")
            f.write(f"WORKFLOW — {req_id}\n")
            f.write(f"{'='*70}\n")
            f.write(workflow_logs.get(req_id, ""))
            f.write("\n")

    # --- Print summary ---
    print(f"\n\n{'='*70}")
    print("RACE SUMMARY")
    print(f"{'='*70}")
    print(f"\n{'Metric':<20} | {'Agent':>15} | {'Fixed Workflow':>15}")
    print(f"{'-'*20}-+-{'-'*15}-+-{'-'*15}")
    print(f"{'Pass rate':<20} | {summary['agent']['pass_rate']:>15} | {summary['workflow']['pass_rate']:>15}")
    print(f"{'p50 latency (ms)':<20} | {summary['agent']['p50_latency_ms']:>15} | {summary['workflow']['p50_latency_ms']:>15}")
    print(f"{'Total tokens':<20} | {summary['agent']['total_tokens']:>15} | {summary['workflow']['total_tokens']:>15}")
    print(f"{'Cost/request ($)':<20} | {summary['agent']['cost_per_request']:>15} | {summary['workflow']['cost_per_request']:>15}")

    print(f"\nResults written to:")
    print(f"  {csv_path}")
    print(f"  {details_path}")
    print(f"  {logs_path}")

    return summary, results


if __name__ == "__main__":
    run_race()
