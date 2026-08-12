import sys
from rag_pipeline import search, generate

def main():
    print("====================================")
    print("  Welcome to the Ask My Recipes App ")
    print("====================================\n")
    print("Type 'quit' or 'exit' to close the app.\n")
    
    while True:
        try:
            query = input("\nAsk a recipe question: ").strip()
            
            if query.lower() in ['quit', 'exit']:
                print("Goodbye!")
                break
                
            if not query:
                continue
                
            print("Searching for recipes...")
            # Retrieve the top 3 most relevant chunks
            results = search(query, collection_name="recipes_structure", top_k=3)
            
            if not results:
                print("No relevant recipe information found.")
                continue
                
            # Extract just the documents to send to the LLM
            docs = [doc for doc, score in results]
            
            print("Generating answer...")
            answer = generate(query, docs)
            
            print("\n--------------------------------")
            print("ANSWER:")
            print("--------------------------------")
            print(answer)
            
            print("\n--------------------------------")
            print("SOURCES (Citations):")
            print("--------------------------------")
            for rank, doc in enumerate(docs):
                meta = doc.metadata
                chunk_id = meta.get("chunk_id", "Unknown")
                recipe = meta.get("recipe_id", "Unknown")
                print(f"[{chunk_id}] Recipe: {recipe}")
                
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nAn error occurred: {e}")

if __name__ == "__main__":
    main()
