import os
from pathlib import Path
from typing import List, Dict, Tuple

from sourceprep.ingest import load_documents
from utils.vector_store import SimpleVectorStore
from utils.logging import log_info

INDEX_DIR = "vector_index/sources"


def build_or_load_index(source_dir: str, persist_dir: str = INDEX_DIR) -> SimpleVectorStore:
    """
    Build or load the project-source vector index.

    If a persisted index already exists at *persist_dir* it is loaded; otherwise
    all documents in *source_dir* are ingested, chunked, embedded, and saved.

    Returns a SimpleVectorStore instance.
    """
    persist_path = Path(persist_dir)
    if persist_path.exists() and (persist_path / "index.faiss").exists():
        log_info(f"Loading existing index from {persist_dir}…")
        return SimpleVectorStore.load_local(str(persist_path))

    log_info("Index not found — building new vector index.")

    docs = load_documents(source_dir)
    chunk_texts, chunk_metadatas = _extract_chunks(docs)

    if not chunk_texts:
        log_info("Warning: no chunks extracted from source directory.")
        # Return an empty store so the pipeline can still run
        return SimpleVectorStore()

    store = SimpleVectorStore.from_texts(chunk_texts, metadatas=chunk_metadatas)
    os.makedirs(persist_path, exist_ok=True)
    store.save_local(str(persist_path))
    log_info(f"Built and saved index with {len(chunk_texts)} chunks.")
    return store


def _extract_chunks(docs: List[Dict]) -> Tuple[List[str], List[Dict]]:
    """Flatten per-document chunk lists into two parallel lists."""
    texts: List[str] = []
    metadatas: List[Dict] = []
    for doc in docs:
        for chunk in doc["chunks"]:
            texts.append(chunk["text"])
            md = doc["metadata"].copy()
            md["chunk_index"] = chunk["chunk_index"]
            metadatas.append(md)
    return texts, metadatas
