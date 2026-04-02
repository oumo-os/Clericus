"""
drafting/recursive_drafter.py
------------------------------
Recursive, state-persistent document drafter.

Pipeline per node:
  1. Plan & Discover  — question generation, KB retrieval, reflection
  2. Subdivision decision — either use pre-defined children from the
     structure generator OR let plan_and_discover propose the split
  3. Draft or Assemble — leaf: full draft+review; parent: assemble from children
  4. Fact extraction into EFB
  5. State persistence — JSON cache for crash-resume

Key fixes vs original:
  - Bug 1: pre-defined children (node["children"]) are now respected;
    plan_and_discover's suggested_structure is only used when no children
    were pre-defined.
  - Bug 4: subdivision threshold uses SUBDIVISION_WORD_THRESHOLD from
    config instead of the semantically wrong INTERNAL_KB_TOP_K * 100.
  - extract_facts_from_section is defined locally (no circular import).
"""

import os
import json
import logging
from typing import Any, Dict, List, Optional

from contemplation.plan_and_discover import plan_and_discover
from drafting.draft_section import draft_section
from drafting.review_section import review_section
from internal_kb import internal_kb
from established_facts import established_facts
from question_tracker import question_tracker
from utils.common import ensure_dir
from utils.config import (
    INTERNAL_KB_TOP_K,
    EFB_TOP_K,
    USE_CURATED_KB,
    DEFAULT_SECTION_BUDGET,
    SUBDIVISION_WORD_THRESHOLD,
)
from curated_kb import CuratedKB
from llm_client.call_llm import call_llm

logger = logging.getLogger(__name__)
STATE_DIRNAME = "clericus_state"

curated_kb: Optional[CuratedKB] = None
if USE_CURATED_KB:
    try:
        curated_kb = CuratedKB(domains=None)
    except Exception:
        logger.warning("Failed to initialise CuratedKB; continuing without it.")


# ---------------------------------------------------------------------------
# Fact extraction
# ---------------------------------------------------------------------------

def extract_facts_from_section(text: str) -> List[Dict[str, Any]]:
    """
    Pull key facts from completed section text via LLM.
    Returns list of {"fact_type": ..., "description": ...}.
    Safe: always falls back to [] on any error.
    """
    if not text or not text.strip():
        return []
    prompt = (
        "Extract key facts from the following section text.\n"
        "Return a JSON object: {\"facts\": [{\"fact_type\": \"...\", \"description\": \"...\"}]}\n"
        "fact_type examples: definition, statistic, claim, date, name.\n"
        "Return the JSON only.\n\n"
        f"TEXT:\n{text[:3000]}"
    )
    try:
        result = call_llm(prompt, parse_json=True)
        facts = result.get("facts", []) if isinstance(result, dict) else result
        return facts if isinstance(facts, list) else []
    except Exception as e:
        logger.warning(f"extract_facts_from_section failed: {e}")
    return []


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _safe_filename(section_path: str) -> str:
    return section_path.replace(".", "_").replace("/", "_") + ".json"


def save_section_state(section_path: str, data: Dict[str, Any], output_dir: str) -> None:
    state_dir = os.path.join(output_dir, STATE_DIRNAME)
    ensure_dir(state_dir)
    path = os.path.join(state_dir, _safe_filename(section_path))
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        logger.info(f"[O] Saved state: {section_path}")
    except Exception as e:
        logger.error(f"[X] Failed to save state for {section_path}: {e}")


def load_section_state(section_path: str, output_dir: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(output_dir, STATE_DIRNAME, _safe_filename(section_path))
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as e:
            logger.error(f"[X] Failed to load state for {section_path}: {e}")
    return None


# ---------------------------------------------------------------------------
# Core recursive drafter
# ---------------------------------------------------------------------------

def recursive_draft_section(
    node: Dict[str, Any],
    output_dir: str,
    kb_index: Any,
    doc_summary: str,
    parent_summary: str,
    section_path: str,
    level: int,
    force_redraft: bool = False,
) -> Dict[str, Any]:
    """
    Draft one section node and all descendants.

    node schema:
        title           str
        working_summary str   optional seed / placeholder
        word_budget     int   falls back to DEFAULT_SECTION_BUDGET
        children        list  optional pre-defined child nodes from structure generator

    section_path: dot-notation, e.g. "1", "1.2", "1.2.1"
    """
    title           = node.get("title", "Untitled")
    working_summary = node.get("working_summary", "")
    word_budget     = node.get("word_budget") or DEFAULT_SECTION_BUDGET

    # --- Resume from cache ---
    state = load_section_state(section_path, output_dir)
    if state and not force_redraft:
        logger.info(f"Reusing cached draft for {section_path}: {title}")
        return state

    logger.info(f"Drafting {section_path}: '{title}'  level={level}  budget={word_budget}w")

    # -----------------------------------------------------------------------
    # Stage 1: Plan & Discover
    # Always run for knowledge retrieval; we may or may not use suggested_structure.
    # -----------------------------------------------------------------------
    plan = plan_and_discover(
        section_title=title,
        doc_summary=doc_summary,
        parent_summary=parent_summary,
        working_summary=working_summary,
        word_budget=word_budget,
        level=level,
        kb_index=kb_index,
        section_path=section_path,
    )
    insights: List[str]       = plan.get("insights", [])
    suggested_structure: List = plan.get("suggested_structure", [])
    knowledge_chunks: List    = plan.get("knowledge_chunks", [])

    # -----------------------------------------------------------------------
    # Stage 2: Determine children
    #
    # Priority:
    #   A. pre-defined children from the structure generator (node["children"])
    #   B. LLM-suggested headings from plan_and_discover (suggested_structure)
    #   C. no subdivision — draft as a leaf
    #
    # A takes priority so that the structure generator output isn't thrown away.
    # -----------------------------------------------------------------------
    predefined_children: List[Dict] = node.get("children") or []
    children_nodes: List[Dict] = []

    if predefined_children:
        # Use the pre-defined structure; distribute budget evenly if not set
        num = len(predefined_children)
        per_budget = max(100, word_budget // num)
        for child in predefined_children:
            if not child.get("word_budget"):
                child = dict(child)
                child["word_budget"] = per_budget
            children_nodes.append(child)
        logger.info(f"  Using {num} pre-defined children for {section_path}")

    elif (
        suggested_structure
        and word_budget > SUBDIVISION_WORD_THRESHOLD
        and level > 0
    ):
        # Fall back to LLM-suggested headings
        num = len(suggested_structure)
        per_budget = max(100, word_budget // num)
        for heading in suggested_structure:
            children_nodes.append({
                "title": heading,
                "working_summary": "",
                "word_budget": per_budget,
                "children": [],
            })
        logger.info(f"  Subdividing into {num} LLM-suggested sections for {section_path}")

    # -----------------------------------------------------------------------
    # Stage 3: Recurse into children OR draft as leaf
    # -----------------------------------------------------------------------
    children_results: List[Dict[str, Any]] = []

    if children_nodes:
        for idx, child_node in enumerate(children_nodes, start=1):
            child_path = f"{section_path}.{idx}"
            child_result = recursive_draft_section(
                node=child_node,
                output_dir=output_dir,
                kb_index=kb_index,
                doc_summary=doc_summary + "\n" + title,
                parent_summary="; ".join(insights),
                section_path=child_path,
                level=level - 1,
                force_redraft=force_redraft,
            )
            children_results.append(child_result)

    # -----------------------------------------------------------------------
    # Stage 3b: Assemble parent OR draft leaf
    # -----------------------------------------------------------------------
    if children_results:
        # Parent node: intro and closing come from plan insights;
        # child sections carry the actual body content.
        intro = insights[0] if insights else ""
        concl = insights[-1] if len(insights) > 1 else ""
        references = [c.get("citation") for c in knowledge_chunks if c.get("citation")]

        combined_text = (
            intro + "\n"
            + "\n".join(
                child.get("openning", "") + "\n"
                + (child.get("body_text") or child.get("body") or "")
                for child in children_results
            )
            + "\n" + concl
        )

        try:
            internal_kb.add_section(section_path=section_path, title=title, content=combined_text)
        except Exception:
            logger.warning(f"Internal KB addition failed for {section_path}")

        facts = extract_facts_from_section(combined_text)
        for fact in facts:
            try:
                established_facts.add_fact(fact.get("fact_type"), fact.get("description"), section_path)
            except Exception:
                pass

        result = {
            "id":           section_path,
            "title":        title,
            "openning":     intro,
            "children":     children_results,   # ← canonical key for sub-sections
            "closing":      concl,
            "references":   references,
            "body_text":    None,
            "section_path": section_path,
        }

    else:
        # Leaf node: full draft → enrich → review
        draft = draft_section(
            doc_summary=doc_summary,
            parent_summary=parent_summary,
            section_title=title,
            working_summary=working_summary,
            knowledge_chunks=knowledge_chunks,
            word_budget=word_budget,
            allow_subsections=False,
            kb_index=kb_index,
        )
        body  = draft.get("body", "")
        intro = draft.get("openning", "")
        concl = draft.get("closing", "")
        references = draft.get("references", [])

        full_text = intro + "\n" + body + "\n" + concl
        try:
            internal_kb.add_section(section_path=section_path, title=title, content=full_text)
        except Exception:
            logger.warning(f"Internal KB addition failed for leaf {section_path}")

        facts = extract_facts_from_section(full_text)
        for fact in facts:
            try:
                established_facts.add_fact(fact.get("fact_type"), fact.get("description"), section_path)
            except Exception:
                pass

        review = review_section(
            draft=draft,
            section_meta={"title": title, "section_path": section_path},
            kb_index=kb_index,
            efb=established_facts,
        )

        result = {
            "id":                   section_path,
            "title":                review.get("title", title),
            "openning":             review.get("openning", intro),
            "body_text":            review.get("body", body),
            "closing":              review.get("closing", concl),
            "references":           references + review.get("new_references", []),
            "discovery_hits":       review.get("discovery_hits", []),
            "efb_crossrefs":        review.get("efb_crossrefs", []),
            "unresolved_questions": review.get("unresolved_questions", []),
            "section_path":         section_path,
            "children":             [],   # leaf — no children
        }

    # -----------------------------------------------------------------------
    # Stage 4: Persist
    # -----------------------------------------------------------------------
    save_section_state(section_path, result, output_dir)
    return result
