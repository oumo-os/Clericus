"""
established_facts.py
--------------------
Tracks critical facts established in the document for continuity checking.

Persistence layout:
    <persist_dir>/facts.json        — fact metadata (id, type, description, …)
    <persist_dir>/index.faiss       — semantic index over fact descriptions
    <persist_dir>/store.pkl         — text/metadata arrays for SimpleVectorStore
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.vector_store import SimpleVectorStore
from utils.config import EFB_KB_DIR, EFB_TOP_K


class EstablishedFactsBase:
    """Tracks and semantically queries facts established in the document."""

    def __init__(self, persist_dir: Optional[str] = None):
        self.persist_dir = Path(persist_dir or EFB_KB_DIR)
        self.metadata_path = self.persist_dir / "facts.json"
        self.facts: Dict[str, Dict[str, Any]] = {}

        # Load existing fact metadata
        if self.metadata_path.exists():
            try:
                data = json.loads(self.metadata_path.read_text(encoding="utf-8"))
                for fid, entry in data.items():
                    entry["context_refs"] = entry.get("context_refs", [])
                    entry["created_at"] = datetime.fromisoformat(entry["created_at"])
                    entry["updated_at"] = datetime.fromisoformat(entry["updated_at"])
                    self.facts[fid] = entry
            except Exception:
                self.facts = {}

        # Load or create vector store for semantic search over fact descriptions
        index_file = self.persist_dir / "index.faiss"
        if self.persist_dir.exists() and index_file.exists():
            self._store = SimpleVectorStore.load_local(str(self.persist_dir))
        else:
            self._store = SimpleVectorStore()

    # ------------------------------------------------------------------

    def add_fact(
        self,
        fact_type: str,
        description: str,
        context_ref: Optional[str] = None,
    ) -> str:
        """Register a new fact and embed its description."""
        fact_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        entry: Dict[str, Any] = {
            "fact_id": fact_id,
            "fact_type": fact_type or "general",
            "description": description,
            "context_refs": [context_ref] if context_ref else [],
            "created_at": now,
            "updated_at": now,
        }
        self.facts[fact_id] = entry
        self._store.add_texts(
            [description], metadatas=[{"fact_id": fact_id, "fact_type": fact_type}]
        )
        self._persist()
        return fact_id

    def query_facts(
        self, query: str, top_k: int = EFB_TOP_K
    ) -> List[Dict[str, Any]]:
        """Semantically retrieve the most relevant established facts."""
        results = self._store.similarity_search(query, k=top_k)
        hits = []
        for doc in results:
            fid = doc.metadata.get("fact_id")
            if fid and fid in self.facts:
                hits.append(self.facts[fid])
        return hits

    # ------------------------------------------------------------------

    def _persist(self) -> None:
        os.makedirs(self.persist_dir, exist_ok=True)
        # Serialise facts with ISO timestamps
        serialisable = {}
        for fid, entry in self.facts.items():
            e = dict(entry)
            e["created_at"] = e["created_at"].isoformat()
            e["updated_at"] = e["updated_at"].isoformat()
            serialisable[fid] = e
        self.metadata_path.write_text(
            json.dumps(serialisable, indent=2), encoding="utf-8"
        )
        self._store.save_local(str(self.persist_dir))


# Module-level singleton
established_facts = EstablishedFactsBase()
