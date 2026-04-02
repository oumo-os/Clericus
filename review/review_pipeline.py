"""
review/review_pipeline.py
--------------------------
Final polish pass over the entire drafted document tree.

traverse_and_review() walks every node — parent and leaf — using the
canonical "children" key that recursive_drafter produces.

review_section() deduplicates references, normalises whitespace, then
runs a lightweight LLM consistency pass.  It is safe to call on parent
nodes (body_text may be None) because it only revises fields that are
non-empty strings.
"""

from typing import Any, Dict, List

from llm_client.call_llm import call_llm
from utils.references import dedupe_references
from utils.text_tools import normalize_whitespace


# ---------------------------------------------------------------------------
# Single-node review
# ---------------------------------------------------------------------------

def review_section(section: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clean up one section dict in-place and return it.

    Steps:
      1. Deduplicate references (handles both string and dict refs).
      2. Normalise whitespace in text fields.
      3. LLM consistency pass (only on nodes that have actual body text).
    """
    # 1. Deduplicate references
    section["references"] = dedupe_references(section.get("references") or [])

    # 2. Normalise whitespace — all string text fields
    for key in ("openning", "body_text", "body", "closing"):
        val = section.get(key)
        if isinstance(val, str) and val.strip():
            section[key] = normalize_whitespace(val)

    # 3. LLM consistency pass — skip parent nodes with no real body text
    body = section.get("body_text") or section.get("body") or ""
    if not body.strip():
        return section

    opening = section.get("openning", "")
    closing  = section.get("closing", "")
    title    = section.get("title", "")

    consistency_prompt = (
        "Review the following document section for consistent terminology and tone.\n"
        "Make only small adjustments — do not change meaning or add new content.\n\n"
        f"Title: {title}\n\n"
        f"Opening:\n{opening}\n\n"
        f"Body:\n{body}\n\n"
        f"Closing:\n{closing}\n\n"
        'Return JSON with keys "openning", "body", "closing" (only include a key if you changed it).'
    )

    try:
        revised = call_llm(consistency_prompt, parse_json=True)
        if not isinstance(revised, dict):
            revised = {}
    except Exception:
        revised = {}

    for src_key, dst_key in [("openning", "openning"), ("body", "body_text"), ("closing", "closing")]:
        new_val = revised.get(src_key)
        if new_val and isinstance(new_val, str) and new_val.strip():
            section[dst_key] = new_val

    return section


# ---------------------------------------------------------------------------
# Document-tree traversal
# ---------------------------------------------------------------------------

def traverse_and_review(document: Dict[str, Any]) -> Dict[str, Any]:
    """
    Walk the entire document tree depth-first, reviewing every node.

    The drafter stores nested sections under the "children" key.
    Leaf nodes have an empty "children" list and carry text in "body_text".
    """
    def _walk(node: Dict[str, Any]) -> None:
        # Recurse into children first (bottom-up review)
        for child in node.get("children") or []:
            _walk(child)
        # Then review this node
        review_section(node)

    _walk(document)
    return document
