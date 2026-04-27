#!/usr/bin/env python3
"""
build_kb.py — Build or rebuild a Clericus vector index from source documents.

Usage:
    # Build / rebuild the main project source index
    python build_kb.py --source ./my_sources

    # Build a named curated KB domain
    python build_kb.py --source ./legal_docs --domain law
    python build_kb.py --source ./finance_data --domain finance

    # Force a rebuild even if an index already exists
    python build_kb.py --source ./my_sources --rebuild

    # Inspect an existing index (show chunk count and sample hits)
    python build_kb.py --source ./my_sources --inspect
    python build_kb.py --domain law --inspect

Each domain is stored under curated_kb/<domain>/  as a SimpleVectorStore
(index.faiss + store.pkl).  The main project index lives at vector_index/sources/.
"""

import argparse
import os
import sys
from pathlib import Path

# Ensure project root is on the path when called from any directory
sys.path.insert(0, str(Path(__file__).parent))

from sourceprep.ingest import load_documents
from utils.vector_store import SimpleVectorStore
from utils.config import CURATED_KB_DIR, INDEX_DIR
from utils.logging import log_info, log_error


MAIN_INDEX_PATH = str(Path(INDEX_DIR) / "sources")


def _extract_chunks(docs):
    texts, metas = [], []
    for doc in docs:
        for chunk in doc["chunks"]:
            texts.append(chunk["text"])
            md = doc["metadata"].copy()
            md["chunk_index"] = chunk["chunk_index"]
            metas.append(md)
    return texts, metas


def build_index(source_dir: str, persist_dir: str, rebuild: bool = False) -> SimpleVectorStore:
    """Ingest source_dir and save a SimpleVectorStore to persist_dir."""
    persist_path = Path(persist_dir)
    index_file   = persist_path / "index.faiss"

    if index_file.exists() and not rebuild:
        log_info(f"Index already exists at {persist_dir}. Use --rebuild to overwrite.")
        return SimpleVectorStore.load_local(persist_dir)

    log_info(f"Loading documents from {source_dir} …")
    docs = load_documents(source_dir)

    if not docs:
        log_error(f"No supported documents found in {source_dir}.")
        sys.exit(1)

    texts, metas = _extract_chunks(docs)
    log_info(f"Embedding {len(texts)} chunks from {len(docs)} document(s) …")

    store = SimpleVectorStore.from_texts(texts, metadatas=metas)
    store.save_local(persist_dir)

    log_info(f"Index saved → {persist_dir}  ({len(texts)} chunks)")
    return store


def inspect_index(persist_dir: str, sample_query: str = "overview summary introduction") -> None:
    """Print stats and a few sample hits for an existing index."""
    index_file = Path(persist_dir) / "index.faiss"
    if not index_file.exists():
        print(f"[X] No index found at {persist_dir}")
        return

    store = SimpleVectorStore.load_local(persist_dir)
    total = len(store._texts)
    print(f"\nIndex: {persist_dir}")
    print(f"  Chunks : {total}")
    if total == 0:
        return

    print(f"\nSample hits for query: '{sample_query}'")
    hits = store.similarity_search(sample_query, k=min(3, total))
    for i, h in enumerate(hits, 1):
        snippet = h.page_content[:120].replace("\n", " ")
        source  = h.metadata.get("filename", h.metadata.get("path", "?"))
        print(f"  [{i}] {source}\n      {snippet}…\n")


def main():
    p = argparse.ArgumentParser(description="Build or inspect Clericus vector indexes.")
    p.add_argument("--source",  default="", help="Directory of source documents to ingest.")
    p.add_argument("--domain",  default="", help="Curated KB domain name (e.g. 'law').")
    p.add_argument("--rebuild", action="store_true", help="Overwrite existing index.")
    p.add_argument("--inspect", action="store_true", help="Show index stats and sample hits.")
    p.add_argument("--query",   default="overview summary introduction",
                   help="Sample query to use with --inspect.")
    args = p.parse_args()

    if args.domain:
        persist_dir = str(Path(CURATED_KB_DIR) / args.domain)
    else:
        persist_dir = MAIN_INDEX_PATH

    if args.inspect:
        inspect_index(persist_dir, sample_query=args.query)
        return

    if not args.source:
        p.error("--source is required unless using --inspect.")

    if not os.path.isdir(args.source):
        p.error(f"Source directory not found: {args.source}")

    build_index(args.source, persist_dir, rebuild=args.rebuild)

    # Quick sanity check
    print()
    inspect_index(persist_dir, sample_query=args.query)


if __name__ == "__main__":
    main()
