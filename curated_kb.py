"""
curated_kb.py
-------------
Manages one or more pre-built curated vector indexes (e.g. domain-specific
law, finance, or general knowledge bases).

Each domain is a directory containing a SimpleVectorStore (index.faiss +
store.pkl).  Domains are lazy-loaded on first query.
"""

import os
import json
from typing import Any, Dict, List, Optional

from utils.vector_store import SimpleVectorStore
from utils.config import CURATED_KB_DIR
from utils.logging import log_info, log_error


class CuratedKB:
    """
    Multi-domain curated knowledge base.

    domains: list of domain keys to load (e.g. ["law", "general"]).
             If None, all sub-directories under CURATED_KB_DIR are treated
             as domains.
    config_path: optional JSON file that maps domain keys to directory paths
                 and descriptions.
    """

    def __init__(
        self,
        domains: Optional[List[str]] = None,
        config_path: Optional[str] = None,
    ):
        self._stores: Dict[str, Optional[SimpleVectorStore]] = {}
        self._domain_paths: Dict[str, str] = {}

        # Resolve domain → path mapping
        if config_path and os.path.exists(config_path):
            try:
                cfg = json.loads(open(config_path).read())
                for key, info in cfg.items():
                    self._domain_paths[key] = info.get("path", "")
            except Exception as e:
                log_error("Failed to load curated KB config", e)
        else:
            if os.path.isdir(CURATED_KB_DIR):
                for entry in os.listdir(CURATED_KB_DIR):
                    path = os.path.join(CURATED_KB_DIR, entry)
                    if os.path.isdir(path):
                        self._domain_paths[entry] = path
            else:
                log_info(
                    f"Curated KB directory '{CURATED_KB_DIR}' not found; "
                    "no curated domains available."
                )

        # Register requested domains (lazy-load on first query)
        targets = domains if domains is not None else list(self._domain_paths.keys())
        for d in targets:
            if d in self._domain_paths:
                self._stores[d] = None  # will be loaded on demand
            else:
                log_info(f"Curated KB domain '{d}' not found; skipping.")

    # ------------------------------------------------------------------

    def _load_domain(self, domain: str) -> Optional[SimpleVectorStore]:
        if self._stores.get(domain) is None:
            path = self._domain_paths.get(domain, "")
            if path and os.path.isdir(path):
                try:
                    self._stores[domain] = SimpleVectorStore.load_local(path)
                    log_info(f"Loaded curated KB domain '{domain}' from {path}")
                except Exception as e:
                    log_error(f"Failed to load curated KB domain '{domain}'", e)
                    self._stores[domain] = None
        return self._stores.get(domain)

    def query(
        self,
        query: str,
        domain: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Query one specific domain or all loaded domains.
        Returns a list of dicts with keys: text, metadata, domain.
        """
        results: List[Dict[str, Any]] = []
        targets = [domain] if domain else list(self._stores.keys())
        for d in targets:
            store = self._load_domain(d)
            if store is None:
                continue
            try:
                hits = store.similarity_search(query, k=top_k)
                for h in hits:
                    results.append(
                        {
                            "text": h.page_content,
                            "metadata": h.metadata,
                            "domain": d,
                        }
                    )
            except Exception as e:
                log_error(f"Curated KB query failed for domain '{d}'", e)
        return results
