"""
internal_kb.py
--------------
Evolving in-document knowledge base: stores drafted section text so later
sections can cross-reference earlier ones semantically.

Replaces the previous LangChain-FAISS implementation and fixes the
"placeholder" poisoning bug (the old code seeded FAISS with a dummy
document which could surface as a false match).
"""

from pathlib import Path
from typing import List, Dict, Any

from utils.vector_store import SimpleVectorStore
from utils.config import INDEX_DIR, INTERNAL_KB_TOP_K


class InternalKB:
    """Semantic cross-reference store for already-drafted sections."""

    def __init__(self, persist_dir: str = INDEX_DIR + "/internal_kb"):
        self._persist_dir = Path(persist_dir)
        index_file = self._persist_dir / "index.faiss"

        if self._persist_dir.exists() and index_file.exists():
            self._store = SimpleVectorStore.load_local(str(self._persist_dir))
        else:
            # Start completely empty — no placeholder documents
            self._store = SimpleVectorStore()

    # ------------------------------------------------------------------

    def add_section(
        self,
        section_path: str,
        title: str,
        content: str,
        metadata: Dict[str, Any] = None,
    ) -> None:
        """Embed and index a completed section."""
        text = f"{section_path} - {title}\n{content}"
        md: Dict[str, Any] = dict(metadata) if metadata else {}
        md.update({"section_path": section_path, "title": title})
        self._store.add_texts([text], metadatas=[md])
        self._store.save_local(str(self._persist_dir))

    def query_internal(
        self, query: str, top_k: int = INTERNAL_KB_TOP_K
    ) -> List[Dict[str, Any]]:
        """Return the top-k most similar previously drafted sections."""
        results = self._store.similarity_search(query, k=top_k)
        hits = []
        for doc in results:
            hits.append(
                {
                    "section_path": doc.metadata.get("section_path"),
                    "title": doc.metadata.get("title"),
                    "snippet": doc.page_content,
                    "metadata": doc.metadata,
                }
            )
        return hits


# Module-level singleton
internal_kb = InternalKB()
