import json
import random

def main():
    traces = []
    with open("traces.jsonl", "r") as f:
        for line in f:
            if line.strip():
                traces.append(json.loads(line))
                
    random.seed(42)
    
    if len(traces) < 20:
        sampled = traces
        print(f"Warning: only {len(traces)} traces available. Sampling all.")
    else:
        sampled = random.sample(traces, 20)
        
    print(f"Sampled {len(sampled)} traces (seed=42).")
    
    with open("sampled_traces.json", "w") as f:
        json.dump(sampled, f, indent=2)

if __name__ == "__main__":
    main()
