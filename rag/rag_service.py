"""
RAG retrieval service – shared knowledge only.
Private user data stays in the app layer.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHROMA_DIR = PROJECT_ROOT / "data" / "chroma_db"
COLLECTION_NAME = "personal_finance_knowledge"
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class RAGService:
    def __init__(
        self,
        chroma_dir: Path = CHROMA_DIR,
        collection_name: str = COLLECTION_NAME,
        model_name: str = EMBEDDING_MODEL_NAME,
    ) -> None:
        self.chroma_dir = str(chroma_dir)
        self.collection_name = collection_name

        if not Path(self.chroma_dir).exists():
            raise FileNotFoundError(
                f"ChromaDB not found at {self.chroma_dir}. "
                "Run: python -m rag.ingest"
            )

        logger.info("Opening ChromaDB at %s", self.chroma_dir)
        self.client = chromadb.PersistentClient(path=self.chroma_dir)

        try:
            self.collection = self.client.get_collection(name=self.collection_name)
        except Exception as exc:
            raise RuntimeError(
                f"Collection '{self.collection_name}' missing. "
                "Run: python -m rag.ingest"
            ) from exc

        count = self.collection.count()
        if count == 0:
            raise RuntimeError(
                "Collection is empty. Run: python -m rag.ingest"
            )
        logger.info("Collection has %d chunks", count)

        logger.info("Loading embedding model: %s", model_name)
        self.embedding_model = SentenceTransformer(model_name)

    def retrieve_relevant_chunks(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if not query or not query.strip():
            return []

        top_k = max(1, min(int(top_k), 20))
        query_emb = self.embedding_model.encode(
            query.strip(), normalize_embeddings=True
        ).tolist()

        results = self.collection.query(
            query_embeddings=[query_emb],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        docs = (results.get("documents") or [[]])[0]
        metas = (results.get("metadatas") or [[]])[0]
        dists = (results.get("distances") or [[]])[0]

        chunks = []
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) and metas[i] else {}
            dist = dists[i] if i < len(dists) else None
            chunks.append({"content": doc, "metadata": meta, "distance": dist})
        return chunks

    def build_context(self, query: str, top_k: int = 5) -> str:
        chunks = self.retrieve_relevant_chunks(query, top_k)
        if not chunks:
            return "No relevant knowledge-base context was retrieved."

        parts = []
        for i, chunk in enumerate(chunks, 1):
            meta = chunk.get("metadata") or {}
            source = (
                meta.get("source_file")
                or meta.get("source")
                or meta.get("file_name")
                or meta.get("filename")
                or "Knowledge-base document"
            )
            parts.append(f"[Source {i}: {source}]\n{chunk['content']}")
        return "\n\n".join(parts)


_rag_service: Optional[RAGService] = None


def get_rag_service() -> RAGService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service


def retrieve_relevant_chunks(
    query: str, top_k: int = 5, user_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    # user_id kept only for call-site compatibility
    return get_rag_service().retrieve_relevant_chunks(query, top_k)


def build_rag_context(
    query: str, top_k: int = 5, user_id: Optional[int] = None
) -> str:
    # user_id kept only for call-site compatibility
    return get_rag_service().build_context(query, top_k)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    q = input("Test query: ").strip()
    if q:
        print("\n" + "=" * 60)
        print(build_rag_context(q, top_k=5))