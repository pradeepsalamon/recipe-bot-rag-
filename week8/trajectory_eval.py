"""
Week 8 Task Set B — Trajectory Evaluation
"""

import os
import sys
import json
import statistics
import time
from typing import List, Dict, Any

# Ensure imports work from week7/ since this script was moved to week8/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "week7")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent import run_agent, SYSTEM_PROMPT
from evaluator import evaluate_response

EVAL_CASES = {
    "REQ_01": {"valid_paths": [["search_recipe"]]},
    "REQ_02": {"valid_paths": [["search_recipe", "scale_recipe"]]},
    "REQ_03": {"valid_paths": [["search_recipe", "substitute_ingredient"]]},
    "REQ_04": {"valid_paths": [
        ["search_recipe", "scale_recipe", "substitute_ingredient"],
        ["search_recipe", "substitute_ingredient", "scale_recipe"]
    ]},
    "REQ_05": {"valid_paths": [["search_recipe"]]},
    "REQ_06": {"valid_paths": [["search_recipe", "scale_recipe"]]},
    "REQ_07": {"valid_paths": [["search_recipe", "substitute_ingredient", "substitute_ingredient"]]},
    "REQ_08": {"valid_paths": [
        ["search_recipe", "scale_recipe", "substitute_ingredient", "substitute_ingredient"],
        ["search_recipe", "substitute_ingredient", "scale_recipe", "substitute_ingredient"],
        ["search_recipe", "substitute_ingredient", "substitute_ingredient", "scale_recipe"]
    ]},
    "REQ_09": {"valid_paths": [
        ["search_recipe", "scale_recipe", "substitute_ingredient"],
        ["search_recipe", "substitute_ingredient", "scale_recipe"]
    ]},
    "REQ_10": {"valid_paths": [
        ["search_recipe", "scale_recipe"] # Sambar has no dairy, just scale
    ]},
}

def load_requests():
    requests_path = os.path.join(os.path.dirname(__file__), "..", "week7", "recipe_requests.json")
    with open(requests_path, "r") as f:
        return json.load(f)

def determine_failure_mode(actual_path: List[str], expected_paths: List[List[str]]) -> str:
    """Classify the trajectory failure mode."""
    if actual_path in expected_paths:
        return "none"
    
    # Check if they missed a tool
    for exp in expected_paths:
        missing = set(exp) - set(actual_path)
        if missing:
            return "missing_tool"
            
    # Check if they added extra tools
    for exp in expected_paths:
        extra = set(actual_path) - set(exp)
        if extra:
            return "extra_tool"
            
    # If sets are same but order differs, it's wrong order
    return "wrong_order"

def run_evaluation(system_prompt_override: str = None) -> Dict[str, Any]:
    requests = load_requests()
    
    results = []
    
    total_tool_calls = 0
    correct_tool_calls = 0  # tool choice accuracy
    valid_arguments = 0
    
    total_steps_taken = 0
    total_min_steps_needed = 0
    
    costs = []
    latencies = []
    tokens = []
    
    outcome_passes = 0
    trajectory_passes = 0
    
    modes_count = {
        "none": 0,
        "missing_tool": 0,
        "extra_tool": 0,
        "wrong_order": 0,
        "hallucinated_args": 0,
        "outcome_failed": 0
    }
    
    right_answer_wrong_path_case = None

    for req in requests:
        req_id = req["id"]
        req_text = req["request"]
        expected = req["expected"]
        valid_paths = EVAL_CASES[req_id]["valid_paths"]
        
        # Suppress stdout to avoid messy output
        def silent_log(msg): pass
        
        res = run_agent(
            user_request=req_text,
            request_id=req_id,
            log_callback=silent_log,
            system_prompt_override=system_prompt_override
        )
        
        eval_result = evaluate_response(res["response"], expected)
        outcome_pass = eval_result["passed"]
        if outcome_pass:
            outcome_passes += 1
            
        # Extract trajectory
        actual_path = []
        for step in res["steps"]:
            if step["action"] != "final_answer":
                actual_path.append(step["action"])
                total_tool_calls += 1
                
                # We count argument validity by checking if the tool didn't return an error
                result_data = step.get("result", {})
                if isinstance(result_data, dict) and "error" not in result_data:
                    valid_arguments += 1
                elif isinstance(result_data, dict) and "error" in result_data:
                    # Invalid arguments led to a tool error
                    modes_count["hallucinated_args"] += 1
                    
        # Check trajectory correctness
        trajectory_pass = actual_path in valid_paths
        if trajectory_pass:
            trajectory_passes += 1
            
        # Classify mode
        if not outcome_pass:
            mode = "outcome_failed"
        elif not trajectory_pass:
            mode = determine_failure_mode(actual_path, valid_paths)
            if right_answer_wrong_path_case is None:
                right_answer_wrong_path_case = {
                    "id": req_id,
                    "request": req_text,
                    "actual_path": actual_path,
                    "valid_paths": valid_paths,
                    "mode": mode
                }
        else:
            mode = "none"
            
        if mode != "hallucinated_args": # Don't double count if we already incremented
            modes_count[mode] += 1
            
        # Tool choice accuracy: did they call a tool that was expected in the path?
        valid_tool_set = set()
        for path in valid_paths:
            valid_tool_set.update(path)
            
        for action in actual_path:
            if action in valid_tool_set:
                correct_tool_calls += 1
                
        # Efficiency
        min_needed = min(len(p) for p in valid_paths)
        total_steps_taken += len(actual_path)
        total_min_steps_needed += min_needed
        
        # Financials
        costs.append(res["metrics"]["cost"])
        latencies.append(res["metrics"]["latency_ms"])
        tokens.append(res["metrics"]["total_tokens"])
        
        # Add a delay to avoid hitting Groq API rate limits (HTTP 429)
        time.sleep(30)
        
    # Compile metrics
    tool_choice_accuracy = (correct_tool_calls / max(1, total_tool_calls)) * 100
    arg_validity_rate = (valid_arguments / max(1, total_tool_calls)) * 100
    step_efficiency = total_steps_taken / max(1, total_min_steps_needed)
    
    cost_p50 = statistics.median(costs)
    cost_max = max(costs)
    
    latency_p50 = statistics.median(latencies)
    latency_max = max(latencies)
    
    token_mean = statistics.mean(tokens)
    
    gap = (outcome_passes / len(requests) * 100) - (trajectory_passes / len(requests) * 100)
    
    return {
        "tool_choice_accuracy": tool_choice_accuracy,
        "arg_validity_rate": arg_validity_rate,
        "step_efficiency": step_efficiency,
        "cost_p50": cost_p50,
        "cost_max": cost_max,
        "latency_p50": latency_p50,
        "latency_max": latency_max,
        "token_mean": token_mean,
        "outcome_pass_rate": (outcome_passes / len(requests)) * 100,
        "trajectory_pass_rate": (trajectory_passes / len(requests)) * 100,
        "gap": gap,
        "modes_count": modes_count,
        "right_answer_wrong_path_case": right_answer_wrong_path_case
    }

def print_results(label: str, results: Dict[str, Any]):
    print(f"\n{'='*60}")
    print(f"RESULTS: {label}")
    print(f"{'='*60}")
    print(f"Tool-Choice Accuracy: {results['tool_choice_accuracy']:.1f}%")
    print(f"Argument Validity Rate: {results['arg_validity_rate']:.1f}%")
    print(f"Step Efficiency: {results['step_efficiency']:.2f} (Steps Taken / Min Needed)")
    print(f"Cost per request: p50=${results['cost_p50']:.6f}, max=${results['cost_max']:.6f}")
    print(f"Latency: p50={results['latency_p50']:.1f}ms, max={results['latency_max']:.1f}ms")
    print(f"\nOutcome Pass Rate: {results['outcome_pass_rate']:.1f}%")
    print(f"Trajectory Pass Rate: {results['trajectory_pass_rate']:.1f}%")
    print(f"GAP (Outcome - Trajectory): {results['gap']:.1f}%")
    
    print("\nFailure Modes Count:")
    for k, v in results['modes_count'].items():
        print(f"  {k}: {v}")
        
    if results["right_answer_wrong_path_case"]:
        c = results["right_answer_wrong_path_case"]
        print(f"\nExample Right-Answer-Wrong-Path Case:")
        print(f"  Req ID: {c['id']}")
        print(f"  Request: {c['request']}")
        print(f"  Mode: {c['mode']}")
        print(f"  Actual Path: {c['actual_path']}")
        print(f"  Valid Paths: {c['valid_paths']}")


if __name__ == "__main__":
    print("Running Baseline Evaluation... This may take a couple of minutes.")
    baseline_results = run_evaluation()
    print_results("BASELINE", baseline_results)
    
    # Identify top mode
    top_mode = None
    top_count = -1
    for k, v in baseline_results["modes_count"].items():
        if k not in ["none", "outcome_failed"] and v > top_count:
            top_mode = k
            top_count = v
            
    print(f"\nTop Trajectory Failure Mode: {top_mode} ({top_count} occurrences)")
    
    if top_mode == "missing_tool":
        print("Mitigation strategy: Tighter Tool Description (Prompting to enforce tool usage)")
        mitigation_prompt = SYSTEM_PROMPT + "\n\nCRITICAL RULE: If a user specifies a dietary restriction (e.g. dairy-free, vegan) or an allergen (e.g. nut allergy), YOU ABSOLUTELY MUST call the `substitute_ingredient` tool for EVERY problematic ingredient before answering. Do not guess the substitute from your internal knowledge. Skipping this tool will cause a failure."
    elif top_mode == "extra_tool":
        print("Mitigation strategy: Tighter Tool Description (Stop hallucinating tool calls)")
        mitigation_prompt = SYSTEM_PROMPT + "\n\nCRITICAL RULE: Only call tools if specifically requested. For example, if a recipe does NOT contain an allergen, do NOT call `substitute_ingredient`. If no scaling is requested, do NOT call `scale_recipe`."
    elif top_mode == "wrong_order":
        print("Mitigation strategy: Tighter Tool Description (Prevent duplicate tool calls)")
        mitigation_prompt = SYSTEM_PROMPT + "\n\nCRITICAL RULE: Do NOT call the same tool multiple times consecutively unless explicitly replacing multiple distinct ingredients. If there is only one restricted ingredient (like Ghee), only call substitute_ingredient ONCE. Do not substitute the substitute."
    else:
        print("Mitigation strategy: Tighter Tool Description")
        mitigation_prompt = SYSTEM_PROMPT + "\n\nCRITICAL RULE: Follow the exact expected sequence of tools. Call search_recipe first, then scale_recipe if scaling, then substitute_ingredient for allergens."

    print("\nPausing for 15 seconds to let API rate limits reset...")
    time.sleep(15)

    print("\nRunning Mitigated Evaluation...")
    mitigated_results = run_evaluation(system_prompt_override=mitigation_prompt)
    print_results("MITIGATED", mitigated_results)
    
    # Price paid
    print(f"\n{'='*60}")
    print("MITIGATION PRICE PAID")
    print(f"{'='*60}")
    latency_diff = mitigated_results['latency_p50'] - baseline_results['latency_p50']
    cost_diff = mitigated_results['cost_p50'] - baseline_results['cost_p50']
    token_diff = mitigated_results['token_mean'] - baseline_results['token_mean']
    
    print(f"Added Latency (p50): +{latency_diff:.1f}ms")
    print(f"Added Cost (p50): +${cost_diff:.6f}")
    print(f"Added Tokens (mean): +{token_diff:.1f}")
    
    print(f"\n{'='*60}")
    print("REGRESSION CHECK")
    print(f"{'='*60}")
    
    worsened = []
    improved = []
    new_modes = []
    
    for k in baseline_results["modes_count"].keys():
        b_val = baseline_results["modes_count"][k]
        m_val = mitigated_results["modes_count"][k]
        print(f"  {k}: {b_val} -> {m_val}")
        
        if k not in ["none", "outcome_failed"]:
            if m_val > b_val:
                if b_val == 0:
                    new_modes.append(k)
                else:
                    worsened.append(k)
            elif m_val < b_val:
                improved.append(k)
                
    if not worsened and not new_modes:
        print("\nResult: Clean mitigation. No modes worsened, and no new modes appeared.")
        print(f"Modes checked: {[k for k in baseline_results['modes_count'].keys() if k not in ['none', 'outcome_failed']]}")
    else:
        if worsened:
            print(f"\nWarning: The following modes worsened: {worsened}")
        if new_modes:
            print(f"\nWarning: The following NEW modes appeared: {new_modes}")
