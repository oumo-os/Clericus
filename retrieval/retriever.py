"""
retrieval/retriever.py
----------------------
Knowledge retrieval helpers:
  - query_knowledge_base(): semantic search over a SimpleVectorStore
  - web_search():           Bing-backed fallback (requires BING_API_KEY env var)
  - NeighborRetriever:      chunk-neighbourhood retrieval via LocalChunkIndex
"""

import os
import requests
from typing import Any, Dict, List, Optional, Set

from utils.logging import log_info

# Web search config
WEB_SEARCH_API_URL = "https://api.bing.microsoft.com/v7.0/search"
WEB_SEARCH_API_KEY = os.getenv("BING_API_KEY", "")


# ---------------------------------------------------------------------------
# Primary retrieval
# ---------------------------------------------------------------------------

def query_knowledge_base(
    kb_index: Any, query: str, k: int = 5
) -> List[Dict[str, Any]]:
    """
    Semantic search over a SimpleVectorStore (or any object that exposes
    .similarity_search(query, k)).

    Returns list of dicts: {"text": ..., "metadata": ...}
    """
    log_info(f"Querying KB for: {query}")
    docs = kb_index.similarity_search(query, k=k)
    hits = [{"text": doc.page_content, "metadata": doc.metadata} for doc in docs]
    log_info(f"  → Retrieved {len(hits)} KB hits")
    return hits


# ---------------------------------------------------------------------------
# Web search fallback
# ---------------------------------------------------------------------------

def web_search(query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """
    Bing web search fallback.  Returns [] if BING_API_KEY is not set.
    Each result: {"snippet": ..., "url": ..., "title": ..., "source": ...}
    """
    if not WEB_SEARCH_API_KEY:
        log_info("No BING_API_KEY set; skipping web search.")
        return []

    log_info(f"Performing web search for: {query}")
    headers = {"Ocp-Apim-Subscription-Key": WEB_SEARCH_API_KEY}
    params = {"q": query, "count": top_k}
    try:
        resp = requests.get(
            WEB_SEARCH_API_URL, headers=headers, params=params, timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("webPages", {}).get("value", []):
            results.append(
                {
                    "snippet": item.get("snippet", ""),
                    "url": item.get("url", ""),
                    "title": item.get("name", ""),
                    "source": item.get("displayUrl", ""),
                }
            )
        return results
    except Exception as e:
        log_info(f"Web search failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Neighbourhood retriever (uses LocalChunkIndex from chunker_embed)
# ---------------------------------------------------------------------------

class NeighborRetriever:
    """
    Retrieves the k nearest chunks plus their immediate neighbours for
    richer context windows.  Requires a LocalChunkIndex instance.
    """

    def __init__(self, chunk_index: Any, window: int = 1):
        """
        chunk_index: a chunker_embed.LocalChunkIndex instance.
        window: how many adjacent chunks to include on each side.
        """
        self._index = chunk_index
        self._window = window

    def retrieve(
        self, query: str, k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Returns up to k results, each padded with neighbouring chunks.
        """
        from sourceprep.chunker_embed import Chunk  # local import to avoid circular

        hits = self._index.search(query, k=k)   # returns List[Tuple[Chunk, float]]
        seen: Set[str] = set()
        results: List[Dict[str, Any]] = []

        for chunk, score in hits:
            neighbours = self._get_neighbours(chunk)
            for c in neighbours:
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    results.append(
                        {
                            "text": c.text,
                            "metadata": c.metadata or {},
                            "chunk_id": c.chunk_id,
                            "score": float(score),
                        }
                    )
        return results

    def _get_neighbours(self, chunk: Any) -> List[Any]:
        """Fetch chunks within ±window positions in the same document."""
        try:
            all_doc_chunks = [
                c
                for c in self._index._chunks   # internal list on LocalChunkIndex
                if c.doc_id == chunk.doc_id
            ]
            all_doc_chunks.sort(key=lambda c: c.chunk_index)
            idx = next(
                (i for i, c in enumerate(all_doc_chunks) if c.chunk_id == chunk.chunk_id),
                None,
            )
            if idx is None:
                return [chunk]
            lo = max(0, idx - self._window)
            hi = min(len(all_doc_chunks), idx + self._window + 1)
            return all_doc_chunks[lo:hi]
        except Exception:
            return [chunk]
