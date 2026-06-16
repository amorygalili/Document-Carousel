"""
Retrieval server for document-carousel.

Exposes POST /retrieve — embeds a query and returns matching documents from Qdrant.

Run locally:
    uvicorn retrieval_server:app --host 0.0.0.0 --port 8000

Or via Docker Compose:
    docker compose up retrieval-server
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore

app = FastAPI(title="Document Carousel Retrieval Server")


class RetrieveRequest(BaseModel):
    search_query: str
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "documents"
    embeddings_base_url: str = "http://localhost:11434/v1"
    embeddings_api_key: str = "ollama"
    embeddings_model: str = "nomic-embed-text"
    top_k: int = Field(default=9, ge=1)


@app.post("/retrieve")
def retrieve(req: RetrieveRequest) -> list[dict]:
    try:
        embeddings = OpenAIEmbeddings(
            base_url=req.embeddings_base_url,
            api_key=req.embeddings_api_key,
            model=req.embeddings_model,
        )

        vector_store = QdrantVectorStore.from_existing_collection(
            embedding=embeddings,
            url=req.qdrant_url,
            collection_name=req.qdrant_collection,
        )

        results = vector_store.similarity_search(req.search_query, k=req.top_k)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    documents = []
    for i, doc in enumerate(results):
        meta = doc.metadata
        documents.append({
            "id": meta.get("id", str(i)),
            "name": meta.get("name", meta.get("title", f"Document {i + 1}")),
            "description": meta.get("description", (doc.page_content[:120] if doc.page_content else "")),
            "type": meta.get("type", meta.get("file_type", "")),
            "content": doc.page_content or "",
        })

    return documents
