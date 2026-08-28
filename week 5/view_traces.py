import json

def main():
    with open('sampled_traces.json') as f:
        traces = json.load(f)
        
    for i, t in enumerate(traces):
        print(f"--- Trace {i+1} | ID: {t['trace_id']} ---")
        print(f"Q: {t['query']}")
        print(f"A: {t['raw_output']}")
        print(f"Chunks:")
        for c in t['retrieved_chunks']:
            print(f"  - {c['chunk_id']} (score {c['score']:.3f})")
        print()

if __name__ == '__main__':
    main()
