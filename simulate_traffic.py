import json
import uuid
import time
from datetime import datetime
from rag_pipeline import search, generate

QUERIES = [
    # Normal / expected
    "How much salt is used in the Idli recipe?",
    "What is the ratio % of Urad dal in the Dosa recipe?",
    "How many cashews are needed for Ven Pongal?",
    "How long should the Idli batter ferment?",
    "What is the first step in making Ven Pongal?",
    "How long should the Sambar simmer after adding the tamarind pulp?",
    "What is the yield for the Rasam recipe?",
    "Why should Rasam only froth slightly when ready?",
    "How do I make crispy Dosa?",
    "Can you give me the full recipe for Medu Vada?",
    # Edge cases / ambiguous / missing info
    "What is the main ingredient?",
    "How much water do I need?",
    "How many calories are in Idli?",
    "Can I use baking soda instead of fermenting?",
    "How do I make chocolate cake?",
    "What's the best side dish?",
    "Tell me a joke about food.",
    "Is this vegan?",
    "How long does it take?",
    "Which recipe uses tamarind?",
    "Give me a recipe with urad dal.",
    "How much does it cost to make?",
    "How long can I store the batter?",
    "What temperature should the oil be for Medu Vada?",
    "Do I need to soak the dal overnight?",
    "Can I use brown rice for dosa?",
    "Is Sambar healthy?",
    "Who invented Idli?",
    "How much protein is in it?",
    "How many servings does this make?"
]

def main():
    print("Simulating traffic...")
    
    traces = []
    for q in QUERIES:
        print(f"Processing: {q}")
        try:
            results = search(q, collection_name="recipes_structure", top_k=5)
            docs = [doc for doc, score in results]
            answer, trace_info = generate(q, docs, return_trace=True)
            
            trace_id = str(uuid.uuid4())
            
            retrieved_chunks = []
            for doc, score in results:
                retrieved_chunks.append({
                    "chunk_id": doc.metadata.get("chunk_id"),
                    "recipe_id": doc.metadata.get("recipe_id"),
                    "score": score,
                    "content": doc.page_content
                })
                
            trace = {
                "trace_id": trace_id,
                "timestamp": datetime.utcnow().isoformat(),
                "query": q,
                "retrieved_chunks": retrieved_chunks,
                "prompt_version": "v1_strict_recipe_assistant",
                "system_prompt": trace_info["system_prompt"],
                "human_prompt": trace_info["human_prompt"],
                "model_params": trace_info["model_params"],
                "raw_output": answer
            }
            traces.append(trace)
        except Exception as e:
            print(f"Error on '{q}': {e}")
            
        # tiny delay just in case of rate limits
        time.sleep(1)
            
    with open("traces.jsonl", "w") as f:
        for t in traces:
            f.write(json.dumps(t) + "\n")
            
    print(f"Saved {len(traces)} traces to traces.jsonl")

if __name__ == '__main__':
    main()
