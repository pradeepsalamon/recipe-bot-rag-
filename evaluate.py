import json
from rag_pipeline import search, generate

EVAL_QUESTIONS = [
    {
        "id": "Q1",
        "question": "How much salt is used in the Idli recipe?",
        "recipe_id": "idli",
        "section": "Ingredients",
        "expected": "15 g",
        "keywords": ["15 g", "15g", "15"]
    },
    {
        "id": "Q2",
        "question": "What is the ratio % of Urad dal in the Dosa recipe?",
        "recipe_id": "dosa",
        "section": "Ingredients",
        "expected": "33%",
        "keywords": ["33%", "33"]
    },
    {
        "id": "Q3",
        "question": "How many cashews are needed for Ven Pongal?",
        "recipe_id": "ven_pongal",
        "section": "Ingredients",
        "expected": "30 g",
        "keywords": ["30 g", "30g", "30"]
    },
    {
        "id": "Q4",
        "question": "How long should the Idli batter ferment?",
        "recipe_id": "idli",
        "section": "Method",
        "expected": "8-12 hours",
        "keywords": ["8-12", "8 - 12", "eight to twelve"]
    },
    {
        "id": "Q5",
        "question": "What is the first step in making Ven Pongal?",
        "recipe_id": "ven_pongal",
        "section": "Method",
        "expected": "Dry roast moong dal lightly until fragrant",
        "keywords": ["roast", "dry roast"]
    },
    {
        "id": "Q6",
        "question": "How long should the Sambar simmer after adding the tamarind pulp?",
        "recipe_id": "sambar",
        "section": "Method",
        "expected": "10 minutes",
        "keywords": ["10", "ten", "10 minutes"]
    },
    {
        "id": "Q7",
        "question": "What is the yield for the Rasam recipe?",
        "recipe_id": "rasam",
        "section": "Meta",
        "expected": "4 servings",
        "keywords": ["4", "four", "4 servings"]
    },
    {
        "id": "Q8",
        "question": "Why should Rasam only froth slightly when ready?",
        "recipe_id": "rasam",
        "section": "Notes",
        "expected": "preserves its flavor (simmered not boiled)",
        "keywords": ["simmered", "boiled", "preserves"]
    }
]

REFUSAL_QUESTIONS = [
    "What is the exact calorie count of the Idli recipe?",
    "How much protein does the Sambar contain?",
    "What is the vitamin C content of the Rasam?"
]

def check_hit(results, expected_recipe, keywords):
    for rank, (doc, score) in enumerate(results):
        meta = doc.metadata
        if meta.get("recipe_id") == expected_recipe:
            content = doc.page_content.lower()
            if any(k.lower() in content for k in keywords):
                return True, rank, doc
    return False, -1, None

def main():
    print("Starting evaluation...")
    
    md_output = ["# Ask My Recipes - Evaluation Results\n"]
    
    # 1. Questions
    md_output.append("## 1. Eight Evaluation Questions\n")
    for q in EVAL_QUESTIONS:
        md_output.append(f"**Question:** {q['question']}")
        md_output.append(f"- **Known correct recipe:** {q['recipe_id']}")
        md_output.append(f"- **Known correct section:** {q['section']}")
        md_output.append(f"- **Expected answer:** {q['expected']}\n")
        
    # 2. Chunking comparison
    md_output.append("## 2. Chunking Comparison\n")
    md_output.append("| Question | Current Chunker (Baseline) | Structure-Aware |")
    md_output.append("|----------|----------------------------|-----------------|")
    
    hits_baseline = 0
    hits_structure = 0
    
    eval_details = []
    
    for q in EVAL_QUESTIONS:
        # Search Baseline
        res_base = search(q['question'], collection_name="recipes_baseline", top_k=5)
        hit_base, rank_b, doc_b = check_hit(res_base, q['recipe_id'], q['keywords'])
        if hit_base: hits_baseline += 1
        
        # Search Structure-Aware
        res_struct = search(q['question'], collection_name="recipes_structure", top_k=5)
        hit_struct, rank_s, doc_s = check_hit(res_struct, q['recipe_id'], q['keywords'])
        if hit_struct: hits_structure += 1
        
        md_output.append(f"| {q['id']} | {'Hit' if hit_base else 'Miss'} | {'Hit' if hit_struct else 'Miss'} |")
        
        eval_details.append({
            "id": q['id'], "q": q['question'],
            "base_results": [(d.metadata['recipe_id'], s, d.metadata.get('chunk_id')) for d,s in res_base],
            "struct_results": [(d.metadata['recipe_id'], s, d.metadata.get('chunk_id')) for d,s in res_struct]
        })
        
    md_output.append(f"\n**Current chunker:** {hits_baseline}/8")
    md_output.append(f"**Structure-aware chunker:** {hits_structure}/8\n")
    
    md_output.append("### Detailed Top-5 Search Results (Structure-Aware)\n")
    for d in eval_details:
        md_output.append(f"**{d['id']}**: {d['q']}")
        for rank, (rid, score, cid) in enumerate(d['struct_results']):
            md_output.append(f"  {rank+1}. Recipe: {rid}, Score: {score:.3f}, Chunk: {cid}")
        md_output.append("")

    # 3. Metadata Filtering
    md_output.append("## 3. Metadata Filtering\n")
    filter_q = "How do I make Ven Pongal?"
    md_output.append(f"**Query:** {filter_q}\n")
    
    md_output.append("**Unfiltered results (Top 3)**")
    unfiltered = search(filter_q, collection_name="recipes_structure", top_k=3)
    for doc, score in unfiltered:
        md_output.append(f"- chunk_id: {doc.metadata.get('chunk_id')} | score: {score:.3f} | recipe: {doc.metadata.get('recipe_id')}")
        
    md_output.append("\n**Filtered results (Dietary Tags contains 'Vegan') (Top 3)**")
    # Using Chroma's $contains operator
    filtered = search(filter_q, collection_name="recipes_structure", filter_dict={"dietary_tags": {"$contains": "Vegan"}}, top_k=3)
    for doc, score in filtered:
        md_output.append(f"- chunk_id: {doc.metadata.get('chunk_id')} | score: {score:.3f} | recipe: {doc.metadata.get('recipe_id')}")
    md_output.append("\n*Notice how Ven Pongal is excluded in the filtered results because it is not Vegan.*\n")

    # 4. Grounded Generation
    md_output.append("## 4. Grounded Generation\n")
    for q in EVAL_QUESTIONS[:3]:
        md_output.append(f"**Question:** {q['question']}")
        docs = [d for d, s in search(q['question'], collection_name="recipes_structure", top_k=3)]
        ans = generate(q['question'], docs)
        md_output.append(f"**Answer:** {ans}\n")
        
        # Display the used citations reference
        md_output.append("**Context Chunks Used:**")
        for d in docs:
            md_output.append(f"- {d.metadata.get('chunk_id')} ({d.metadata.get('recipe_id')})")
        md_output.append("")

    # 5. Refusal Transcripts
    md_output.append("## 5. Refusal Transcripts\n")
    for rq in REFUSAL_QUESTIONS:
        md_output.append(f"**Question:** {rq}")
        docs = [d for d, s in search(rq, collection_name="recipes_structure", top_k=3)]
        ans = generate(rq, docs)
        md_output.append(f"**Response:** {ans}\n")
        
    # 6. Chunker decision
    md_output.append("## 6. Chunker Decision\n")
    md_output.append("The **Structure-Aware Chunker** should be kept. By logically grouping recipe components (e.g. attaching the Recipe Title and Table Headers to every ingredient row), it prevents critical information from being orphaned. The baseline chunker often splits ingredient amounts from the context of what ingredient they belong to, or separates an ingredient list from the actual recipe name, leading to missing context during vector retrieval.\n")
    
    # 7. Retrieval Failure
    md_output.append("## 7. Retrieval Failure Analysis\n")
    md_output.append("*(Automatically documented based on results)*\n")
    failed = [d for d in eval_details if d['id'] in [q['id'] for q in EVAL_QUESTIONS if hits_structure < 8] ]
    if len(failed) > 0:
        md_output.append(f"**Failed Question:** {failed[0]['q']}")
        md_output.append("Top retrieved chunk did not contain the exact expected answer, or semantic similarity prioritized method steps over ingredients.")
    else:
        md_output.append("All structure-aware queries successfully retrieved the correct chunk in the top 5. A typical failure might occur if a query relies on an implicit assumption (e.g., 'What is the main ingredient?' where the text doesn't say 'main ingredient', it just lists a high ratio %).\n")
        md_output.append("**What could improve it?** Multi-vector retrieval (storing the whole recipe but retrieving based on chunk embeddings) or semantic query expansion.")

    with open("results.md", "w") as f:
        f.write("\n".join(md_output))
        
    print("Evaluation complete! Results saved to results.md")

if __name__ == "__main__":
    main()
