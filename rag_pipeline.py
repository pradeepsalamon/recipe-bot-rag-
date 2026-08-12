from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage

load_dotenv(override=True)

def get_db(collection_name="recipes_structure"):
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    db = Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory="./chroma_db"
    )
    return db

def search(query, collection_name="recipes_structure", filter_dict=None, top_k=5):
    """
    Search-only retrieval. Returns a list of documents.
    """
    db = get_db(collection_name)
    # Chroma filter syntax: {"dietary_tags": {"$contains": "Vegan"}} or exact match
    # Since dietary tags can be comma separated, we use $contains if supported, else exact.
    # Actually, Chroma supports simple dict filters.
    # Let's format the filter to match exact strings, or pass it directly.
    kwargs = {"k": top_k}
    if filter_dict:
        kwargs["filter"] = filter_dict
        
    results = db.similarity_search_with_relevance_scores(query, **kwargs)
    return results

def generate(query, docs):
    """
    Grounded generation using LLM with strict prompting.
    """
    llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash", temperature=0)
    
    context = ""
    for idx, doc in enumerate(docs):
        meta = doc.metadata
        chunk_id = meta.get("chunk_id", "unknown_chunk")
        recipe_id = meta.get("recipe_id", "unknown_recipe")
        source = meta.get("source_file", "unknown_source")
        
        context += f"\n--- Context Block ---\n"
        context += f"chunk_id: {chunk_id}\n"
        context += f"recipe_id: {recipe_id}\n"
        context += f"source_file: {source}\n"
        context += f"content: {doc.page_content}\n"
        
    system_prompt = """
You are a strict recipe assistant. 

Answer only using the supplied retrieved context.
Do not use outside knowledge.
If the retrieved context does not contain enough information
to answer the question, say that the information is not available
in the provided recipe documents.

When making a factual claim based on the context, you MUST provide a citation at the end of the sentence or claim.
The citation MUST be in the exact format: [chunk_id]
Where chunk_id is the chunk_id provided in the context block that contains the fact.

Example format:
The recipe uses 20g of fine sea salt. [chunk_abc123]
"""

    human_prompt = f"Context:\n{context}\n\nQuestion: {query}"
    
    messages = [
        SystemMessage(content=system_prompt.strip()),
        HumanMessage(content=human_prompt)
    ]
    
    response = llm.invoke(messages)
    
    content = response.content
    if isinstance(content, list) and len(content) > 0:
        if isinstance(content[0], dict) and 'text' in content[0]:
            return content[0]['text']
    elif isinstance(content, str):
        return content
        
    return str(content)
