import sys
from rag_pipeline import search

def main():
    q = "What is the yield for the Rasam recipe?"
    print(f"Query: {q}")
    results = search(q, collection_name="recipes_structure", top_k=5)
    for i, (doc, score) in enumerate(results):
        print(f"Rank {i+1} | Score {score:.3f} | Chunk {doc.metadata.get('chunk_id')}")
        print(doc.page_content)
        print("-" * 40)

if __name__ == '__main__':
    main()
