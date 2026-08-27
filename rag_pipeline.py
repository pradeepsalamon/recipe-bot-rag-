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
    Hybrid search (Dense + BM25 with RRF). Returns a list of (document, score) tuples.
    """
    db = get_db(collection_name)
    kwargs = {"k": top_k}
    if filter_dict:
        kwargs["filter"] = filter_dict
        
    # 1. Dense Search (fetch a larger pool for RRF)
    pool_k = max(top_k * 4, 20)
    dense_kwargs = kwargs.copy()
    dense_kwargs["k"] = pool_k
    dense_results = db.similarity_search_with_relevance_scores(query, **dense_kwargs)
    
    # If there is a filter_dict, applying BM25 in-memory is complex without manual filtering,
    # so we'll just fall back to dense for filtered queries (for simplicity).
    if filter_dict:
        return dense_results[:top_k]
        
    # 2. Sparse Search (BM25)
    # Fetch all docs to create BM25 index
    from langchain_community.retrievers import BM25Retriever
    from langchain_core.documents import Document
    all_data = db.get()
    all_docs = [Document(page_content=c, metadata=m) for c, m in zip(all_data['documents'], all_data['metadatas'])]
    bm25 = BM25Retriever.from_documents(all_docs)
    bm25.k = pool_k
    sparse_docs = bm25.invoke(query)
    
    # 3. RRF (Reciprocal Rank Fusion)
    # RRF Score = 1 / (60 + rank)
    fused_scores = {}
    doc_map = {}
    
    # Add dense scores
    for rank, (doc, _score) in enumerate(dense_results):
        chunk_id = doc.metadata.get('chunk_id')
        if chunk_id not in fused_scores:
            fused_scores[chunk_id] = 0
            doc_map[chunk_id] = doc
        fused_scores[chunk_id] += 1 / (60 + rank + 1)
        
    # Add sparse scores
    for rank, doc in enumerate(sparse_docs):
        chunk_id = doc.metadata.get('chunk_id')
        if chunk_id not in fused_scores:
            fused_scores[chunk_id] = 0
            doc_map[chunk_id] = doc
        fused_scores[chunk_id] += 1 / (60 + rank + 1)
        
    # Sort and return top_k
    sorted_fused = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
    results = [(doc_map[chunk_id], score) for chunk_id, score in sorted_fused[:top_k]]
    
    return results

def generate(query, docs, return_trace=False):
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
    answer = str(content)
    if isinstance(content, list) and len(content) > 0:
        if isinstance(content[0], dict) and 'text' in content[0]:
            answer = content[0]['text']
    elif isinstance(content, str):
        answer = content
        
    if return_trace:
        return answer, {
            "system_prompt": system_prompt.strip(),
            "human_prompt": human_prompt,
            "model_params": {"model": "gemini-3.5-flash", "temperature": 0}
        }
    return answer
