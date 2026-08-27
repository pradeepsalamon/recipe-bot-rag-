import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from rag_pipeline import search, generate

app = FastAPI(title="Ask My Recipes API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str


class Source(BaseModel):
    chunk_id: str
    recipe_id: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    results = search(req.question, collection_name="recipes_structure", top_k=5)
    docs = [doc for doc, _score in results]
    answer = generate(req.question, docs)
    sources = [
        Source(
            chunk_id=doc.metadata.get("chunk_id", "unknown"),
            recipe_id=doc.metadata.get("recipe_id", "unknown"),
        )
        for doc in docs
    ]
    return ChatResponse(answer=answer, sources=sources)
