"""
One-time / re-run ingestion for the personal-finance knowledge base.

From project root:
    python -m rag.ingest
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Dict, List

import chromadb
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# Always resolve relative to this file → project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "knowledge_base"
CHROMA_DIR = PROJECT_ROOT / "data" / "chroma_db"
COLLECTION_NAME = "personal_finance_knowledge"
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

CHUNK_SIZE = 900
CHUNK_OVERLAP = 150


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_into_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    text = clean_text(text)
    if not text:
        return []

    paragraphs = re.split(r"\n\s*\n", text)
    chunks: List[str] = []
    current = ""

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        if len(paragraph) > chunk_size:
            if current:
                chunks.append(current.strip())
                current = ""
            words = paragraph.split()
            piece = ""
            for word in words:
                candidate = f"{piece} {word}".strip()
                if len(candidate) <= chunk_size:
                    piece = candidate
                else:
                    if piece:
                        chunks.append(piece.strip())
                    tail = piece[-overlap:] if piece else ""
                    piece = f"{tail} {word}".strip()
            if piece:
                current = piece
            continue

        candidate = f"{current}\n\n{paragraph}".strip()
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current.strip())
            previous_tail = current[-overlap:] if current else ""
            current = f"{previous_tail}\n\n{paragraph}".strip()
            if len(current) > chunk_size:
                current = paragraph

    if current:
        chunks.append(current.strip())

    return [c for c in chunks if len(c.strip()) >= 40]


def load_manifest() -> Dict:
    path = KNOWLEDGE_BASE_DIR / "manifest.json"
    if not path.exists():
        logger.warning("manifest.json not found")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("manifest.json invalid")
        return {}


def metadata_for_file(file_path: Path, manifest: Dict) -> Dict:
    meta = {
        "source_file": file_path.name,
        "source_path": str(file_path.relative_to(PROJECT_ROOT)),
        "topic": file_path.stem,
        "jurisdiction": manifest.get("jurisdiction", "India"),
        "document_version": str(manifest.get("version", "unknown")),
        "freshness_class": "unknown",
    }
    for doc in manifest.get("documents", []) or []:
        if not isinstance(doc, dict):
            continue
        name = doc.get("file") or doc.get("filename") or doc.get("source_file")
        if name == file_path.name:
            for key in (
                "topic", "issuing_authority", "publication_date",
                "effective_date", "last_verified_date", "freshness_class", "jurisdiction",
            ):
                if doc.get(key) is not None:
                    meta[key] = str(doc[key])
    return meta


def make_chunk_id(source_file: str, idx: int, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"{source_file}:{idx}:{digest}"


def read_documents() -> List[Dict]:
    if not KNOWLEDGE_BASE_DIR.exists():
        raise FileNotFoundError(f"Knowledge base missing: {KNOWLEDGE_BASE_DIR}")

    files = sorted(KNOWLEDGE_BASE_DIR.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"No .md files in {KNOWLEDGE_BASE_DIR}")

    manifest = load_manifest()
    records: List[Dict] = []

    for fp in files:
        text = fp.read_text(encoding="utf-8")
        chunks = split_into_chunks(text)
        base = metadata_for_file(fp, manifest)
        for i, chunk in enumerate(chunks):
            meta = {**base, "chunk_index": i, "total_chunks_in_file": len(chunks)}
            records.append({
                "id": make_chunk_id(fp.name, i, chunk),
                "text": chunk,
                "metadata": meta,
            })
        logger.info("%s → %d chunks", fp.name, len(chunks))

    return records


def build_vector_database(records: List[Dict]) -> None:
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Loading embedding model: %s", EMBEDDING_MODEL_NAME)
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    # Drop & recreate so re-ingest is always clean
    try:
        client.delete_collection(COLLECTION_NAME)
        logger.info("Deleted existing collection")
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"description": "Personal finance knowledge base"},
    )

    if not records:
        logger.warning("Nothing to insert")
        return

    docs = [r["text"] for r in records]
    ids = [r["id"] for r in records]
    metas = [r["metadata"] for r in records]

    logger.info("Embedding %d chunks…", len(docs))
    embeddings = model.encode(
        docs, batch_size=32, show_progress_bar=True, normalize_embeddings=True
    ).tolist()

    collection.add(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)
    logger.info("Stored %d chunks in '%s'", len(docs), COLLECTION_NAME)


def main() -> None:
    logger.info("Starting ingestion…")
    records = read_documents()
    logger.info("Total chunks: %d", len(records))
    build_vector_database(records)
    logger.info("Done.")


if __name__ == "__main__":
    main()