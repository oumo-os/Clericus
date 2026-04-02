"""
utils/vector_store.py
---------------------
Lightweight FAISS + SentenceTransformer vector store that replaces the
langchain_community.vectorstores.FAISS dependency throughout Clericus.

Drop-in compatible: exposes similarity_search(), add_texts(), save_local(),
load_local(), and from_texts() so existing call sites need minimal changes.

Returns SearchResult objects with .page_content and .metadata attributes
to match the LangChain Document interface all callers already expect.
"""

from __future__ import annotations

import os
import pickle
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from utils.config import LOCAL_EMBEDDING_MODEL
from utils.logging import log_info, log_error


@dataclass
class SearchResult:
    """Mirrors LangChain's Document: .page_content + .metadata."""
    page_content: str
    metadata: Dict[str, Any]


class SimpleVectorStore:
    """
    In-memory FAISS index backed by a SentenceTransformer encoder.

    Persistence layout (save_local / load_local):
        <dir>/index.faiss   — raw FAISS index binary
        <dir>/store.pkl     — {"texts": [...], "metadatas": [...]}
    """

    _INDEX_FILE = "index.faiss"
    _STORE_FILE = "store.pkl"

    def __init__(self, model_name: str = LOCAL_EMBEDDING_MODEL):
        self._model_name = model_name
        self._model: Optional[SentenceTransformer] = None   # lazy init
        self._index: Optional[faiss.Index] = None
        self._texts: List[str] = []
        self._metadatas: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            log_info(f"Loading embedding model: {self._model_name}")
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def _embed(self, texts: List[str]) -> np.ndarray:
        vecs = self._get_model().encode(
            texts, convert_to_numpy=True, show_progress_bar=False
        )
        return vecs.astype("float32")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Embed and index a batch of texts."""
        if not texts:
            return
        metadatas = metadatas or [{} for _ in texts]
        vecs = self._embed(texts)
        if self._index is None:
            dim = vecs.shape[1]
            self._index = faiss.IndexFlatL2(dim)
        self._index.add(vecs)
        self._texts.extend(texts)
        self._metadatas.extend(metadatas)

    def similarity_search(
        self, query: str, k: int = 5
    ) -> List[SearchResult]:
        """Return up to k nearest neighbours for *query*."""
        if self._index is None or not self._texts:
            return []
        k = min(k, len(self._texts))
        vec = self._embed([query])
        _, indices = self._index.search(vec, k)
        results: List[SearchResult] = []
        for idx in indices[0]:
            if 0 <= idx < len(self._texts):
                results.append(
                    SearchResult(
                        page_content=self._texts[idx],
                        metadata=self._metadatas[idx],
                    )
                )
        return results

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_local(self, path: str) -> None:
        os.makedirs(path, exist_ok=True)
        if self._index is not None:
            faiss.write_index(
                self._index, os.path.join(path, self._INDEX_FILE)
            )
        with open(os.path.join(path, self._STORE_FILE), "wb") as fh:
            pickle.dump(
                {"texts": self._texts, "metadatas": self._metadatas}, fh
            )
        log_info(f"Vector store saved to {path} ({len(self._texts)} vectors)")

    @classmethod
    def load_local(
        cls,
        path: str,
        model_name: str = LOCAL_EMBEDDING_MODEL,
        # kept for compat with old call sites that pass allow_dangerous_deserialization
        **_kwargs: Any,
    ) -> "SimpleVectorStore":
        store = cls(model_name=model_name)
        index_path = os.path.join(path, cls._INDEX_FILE)
        store_path = os.path.join(path, cls._STORE_FILE)
        if os.path.exists(index_path):
            store._index = faiss.read_index(index_path)
        if os.path.exists(store_path):
            with open(store_path, "rb") as fh:
                data = pickle.load(fh)
            store._texts = data.get("texts", [])
            store._metadatas = data.get("metadatas", [])
        log_info(
            f"Vector store loaded from {path} ({len(store._texts)} vectors)"
        )
        return store

    @classmethod
    def from_texts(
        cls,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        model_name: str = LOCAL_EMBEDDING_MODEL,
        # compat shim — LangChain callers pass `embedding=` kwarg
        embedding: Any = None,
        **_kwargs: Any,
    ) -> "SimpleVectorStore":
        store = cls(model_name=model_name)
        store.add_texts(texts, metadatas)
        return store
