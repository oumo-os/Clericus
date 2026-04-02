from typing import List, Dict, Any, Optional
from retrieval.retriever import query_knowledge_base, web_search
from internal_kb import internal_kb
from utils.config import INTERNAL_KB_TOP_K, USE_CURATED_KB, CURATED_KB_TOP_K
from utils.logging import log_info
from curated_kb import CuratedKB

# Initialize curated KB instance if global usage desired; can also pass instance to functions
curated_kb_global = CuratedKB(domains=None) if USE_CURATED_KB else None


def discover_knowledge(
    questions: List[str],
    kb_index: Any,
    top_k: int = 5,
    web_fallback: bool = False,
    web_top_k: int = 3,
    internal_top_k: int = INTERNAL_KB_TOP_K,
    use_curated: bool = False,
    curated_kb: Optional[CuratedKB] = None,
    curated_top_k: int = CURATED_KB_TOP_K
) -> List[Dict]:
    """
    For each question:
      1. Query external/project KB (semantic search)
      2. Query internal KB (cross-references of drafted sections)
      3. Optionally perform web search fallback
      4. Optionally perform curated KB enrichment if enabled
    Returns unified list of dicts with keys:
      - question
      - chunk/snippet
      - citation (metadata)
      - source_type: 'external' | 'internal' | 'web' | 'curated'
      - section_path (for internal)
      - domain (for curated)
    """
    all_results: List[Dict] = []

    # Determine curated KB instance
    curated_instance = curated_kb if use_curated and curated_kb else (curated_kb_global if use_curated else None)

    for q in questions:
        log_info(f"Discovering knowledge for question: {q}")

        # 1. External KB retrieval
        kb_hits = query_knowledge_base(kb_index, q, k=top_k)
        for hit in kb_hits:
            all_results.append({
                "question": q,
                "chunk": hit.get("text", hit.get("page_content", "")),
                "citation": hit.get("metadata", {}).get("citation", hit.get("metadata", {})),
                "source_type": "external",
                "section_path": None,
                "domain": None
            })

        # 2. Internal KB retrieval
        try:
            internal_hits = internal_kb.query_internal(q, top_k=internal_top_k)
        except Exception as e:
            log_info(f"Internal KB query failed for '{q}': {e}")
            internal_hits = []
        for hit in internal_hits:
            all_results.append({
                "question": q,
                "chunk": hit.get("snippet", ""),
                "citation": {
                    "source": "internal",
                    "section_path": hit.get("section_path"),
                    "title": hit.get("title")
                },
                "source_type": "internal cross reference",
                "section_path": hit.get("section_path"),
                "domain": None
            })

        # 3. Optional web fallback
        if web_fallback and len(kb_hits) < top_k:
            log_info(f"KB sparse for '{q}', performing web search fallback...")
            try:
                web_hits = web_search(q, top_k=web_top_k)
            except Exception as e:
                log_info(f"Web search failed for '{q}': {e}")
                web_hits = []
            for item in web_hits:
                all_results.append({
                    "question": q,
                    "chunk": item.get("snippet", ""),
                    "citation": {
                        "source": item.get("url", ""),
                        "title": item.get("title", "Web Source"),
                        "author": item.get("source", "Web")
                    },
                    "source_type": "web",
                    "section_path": None,
                    "domain": None
                })

        # 4. Optional curated KB enrichment
        if use_curated and curated_instance:
            try:
                curated_hits = curated_instance.query(q, domain=None, top_k=curated_top_k)
            except Exception as e:
                log_info(f"Curated KB query failed for '{q}': {e}")
                curated_hits = []
            for hit in curated_hits:
                all_results.append({
                    "question": q,
                    "chunk": hit.get("text", ""),
                    "citation": hit.get("metadata", {}),
                    "source_type": "curated",
                    "section_path": None,
                    "domain": hit.get("domain")
                })

    return all_results
