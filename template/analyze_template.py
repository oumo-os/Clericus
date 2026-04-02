"""
template/analyze_template.py
-----------------------------
Two public entry points:

  generate_structure_from_template(path, budget)
      → reads an existing file (txt/md/pdf/docx), extracts headings,
        optionally refines with LLM, returns a pipeline-ready dict tree.

  generate_structure_from_instruction(instruction, budget, llm_client)
      → NEW: when no template file is given, calls the LLM directly to
        propose a document structure from the user's plain-text instruction.
        Wires structure_generator.TemplateHandler into the no-template path
        that was previously just a single flat node.

Both return a dict compatible with recursive_draft_section:
    {
      "title": str,
      "working_summary": str,
      "word_budget": int,
      "children": [   # may be empty for flat single-node case
          { "title": ..., "working_summary": ..., "word_budget": ..., "children": [...] },
          ...
      ]
    }
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm_client.call_llm import call_llm
from utils.logging import log_info

HEADING_PATTERNS = [
    re.compile(r"^\s*\d+\.\s+(.+)$", re.MULTILINE),    # "1. Introduction"
    re.compile(r"^[A-Z ]{5,}$", re.MULTILINE),           # ALL-CAPS LINES
    re.compile(r"^#{1,6}\s*(.+)$", re.MULTILINE),        # ## Markdown headings
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_headings(text: str) -> List[str]:
    """Return a deduplicated ordered list of heading strings."""
    headings: List[str] = []
    for pattern in HEADING_PATTERNS:
        for match in pattern.findall(text):
            title = match.strip()
            if title and title not in headings:
                headings.append(title)
    return headings


def _headings_to_tree(headings: List[str], total_budget: int) -> Dict[str, Any]:
    """Turn a flat heading list into a pipeline-ready dict tree."""
    if not headings:
        return {
            "title": "Untitled Document",
            "working_summary": "",
            "word_budget": total_budget,
            "children": [],
        }
    doc_title = headings[0]
    children_headings = headings[1:]
    per_section = total_budget // max(len(children_headings), 1)
    children = [
        {
            "title": h,
            "working_summary": "",
            "word_budget": per_section,
            "children": [],
        }
        for h in children_headings
    ]
    return {
        "title": doc_title,
        "working_summary": "",
        "word_budget": total_budget,
        "children": children,
    }


def _template_node_to_dict(node: Any, total_budget: int) -> Dict[str, Any]:
    """
    Convert a template/structure_generator.TemplateNode into a pipeline dict.
    Handles both absolute-int and fractional-float word_budget values.
    """
    budget = node.word_budget
    if budget is None:
        budget = total_budget
    elif isinstance(budget, float):        # fraction of total
        budget = max(50, int(budget * total_budget))

    children = [
        _template_node_to_dict(c, budget) for c in getattr(node, "children", [])
    ]
    return {
        "title": node.title,
        "working_summary": getattr(node, "placeholder", ""),
        "word_budget": budget,
        "children": children,
    }


# ---------------------------------------------------------------------------
# Public: from template file
# ---------------------------------------------------------------------------

def generate_structure_from_template(
    template_path: str, default_budget: int = 2000
) -> Dict[str, Any]:
    """
    Build a pipeline-ready structure dict from an existing template document.

    Reads the file, extracts headings heuristically, then asks the LLM to
    refine the structure (section order, proportional budgets).
    """
    log_info(f"Analysing template: {template_path}")
    path = Path(template_path)
    text = ""

    if path.suffix.lower() in {".md", ".txt"}:
        text = path.read_text(encoding="utf-8")
    elif path.suffix.lower() == ".pdf":
        from sourceprep.ingest import extract_text_from_pdf
        text = extract_text_from_pdf(path)
    elif path.suffix.lower() == ".docx":
        from sourceprep.ingest import extract_text_from_docx
        text = extract_text_from_docx(path)

    # Heuristic baseline
    headings = _extract_headings(text)
    baseline = _headings_to_tree(headings, default_budget)

    # LLM refinement
    prompt = (
        f"Given these headings extracted from a template document:\n{headings}\n\n"
        f"Total word budget: {default_budget} words.\n"
        "Propose a JSON structure with:\n"
        '  "title": document title (string),\n'
        '  "working_summary": brief description (string),\n'
        f'  "word_budget": {default_budget},\n'
        '  "children": list of section objects, each with "title", '
        '"working_summary", "word_budget", "children" (may be []).\n'
        "Distribute word_budget proportionally across sections.\n"
        "Return the JSON only."
    )
    try:
        refined = call_llm(prompt, parse_json=True)
        if isinstance(refined, dict) and refined.get("title"):
            log_info("LLM-refined template structure accepted.")
            return refined
    except Exception as e:
        log_info(f"LLM template refinement failed ({e}); using heuristic baseline.")

    return baseline


# ---------------------------------------------------------------------------
# Public: from plain instruction (NEW — no template file needed)
# ---------------------------------------------------------------------------

def generate_structure_from_instruction(
    instruction: str,
    default_budget: int = 2000,
    use_template_handler: bool = True,
) -> Dict[str, Any]:
    """
    Generate a document skeleton from a plain-text instruction/goal.

    Strategy A (default, use_template_handler=True):
        Uses template/structure_generator.TemplateHandler with a thin LLM
        adapter so the full TemplateNode machinery (budget normalisation,
        validation, preset merging) is exercised.

    Strategy B (fallback / use_template_handler=False):
        Direct LLM call asking for a pipeline-ready JSON dict — simpler,
        no extra dependencies.

    Returns a pipeline-ready dict (same schema as generate_structure_from_template).
    """
    log_info(f"Generating structure from instruction: '{instruction[:80]}…'")

    if use_template_handler:
        try:
            return _structure_via_template_handler(instruction, default_budget)
        except Exception as e:
            log_info(f"TemplateHandler path failed ({e}); falling back to direct LLM.")

    return _structure_via_direct_llm(instruction, default_budget)


def _structure_via_template_handler(
    instruction: str, total_budget: int
) -> Dict[str, Any]:
    """
    Wire the existing TemplateHandler + LLMStructureGeneratorBase protocol.
    We implement a minimal ClericusLLMAdapter that delegates to call_llm.
    """
    from template.structure_generator import (
        TemplateHandler,
        TemplateNode,
        LLMStructureGeneratorBase,
    )

    class _ClericusLLMAdapter:
        """Bridges LLMStructureGeneratorBase protocol → call_llm."""

        def generate_structure(
            self,
            *,
            seed_template: Optional[Any] = None,
            document_kind: Optional[str] = None,
            user_instructions: Optional[str] = None,
            max_depth: Optional[int] = None,
        ) -> "TemplateNode":
            prompt = (
                "You are a document architect. Create a logical section structure "
                "for the following document goal.\n\n"
                f"GOAL: {user_instructions or instruction}\n\n"
                f"Total word budget: {total_budget} words.\n"
                f"Maximum depth: {max_depth or 3} levels.\n\n"
                "Return a JSON object with:\n"
                '  "id": unique root id,\n'
                '  "title": document title,\n'
                f'  "word_budget": {total_budget},\n'
                '  "children": list of section objects, each with '
                '"id", "title", "placeholder" (1-sentence purpose), '
                '"word_budget" (integer), "children" (may be []).\n'
                "Return the JSON only."
            )
            raw = call_llm(prompt, parse_json=True)
            # Recursively build TemplateNode tree from the JSON
            return _dict_to_template_node(raw)

    def _dict_to_template_node(d: Dict) -> "TemplateNode":
        children = [_dict_to_template_node(c) for c in d.get("children", [])]
        return TemplateNode(
            id=d.get("id", str(id(d))),
            title=d.get("title", "Section"),
            placeholder=d.get("placeholder", ""),
            word_budget=d.get("word_budget"),
            children=children,
        )

    handler = TemplateHandler(llm=_ClericusLLMAdapter(), max_depth=3)
    root_node = handler.generate_structure_with_llm(user_instructions=instruction)
    return _template_node_to_dict(root_node, total_budget)


def _structure_via_direct_llm(
    instruction: str, total_budget: int
) -> Dict[str, Any]:
    """Simple direct-LLM fallback: ask for a pipeline-ready JSON dict."""
    prompt = (
        "You are a document architect. Create a logical section structure "
        f"for: '{instruction}'.\n\n"
        f"Total word budget: {total_budget} words.\n"
        "Return a JSON object with exactly these keys:\n"
        '  "title": document title,\n'
        '  "working_summary": one-sentence document goal,\n'
        f'  "word_budget": {total_budget},\n'
        '  "children": list of section dicts, each with '
        '"title", "working_summary", "word_budget" (integer), "children" ([]).\n'
        "Distribute word_budget proportionally. Return the JSON only."
    )
    try:
        result = call_llm(prompt, parse_json=True)
        if isinstance(result, dict) and result.get("title"):
            return result
    except Exception as e:
        log_info(f"Direct LLM structure generation failed: {e}")

    # Last-resort flat single node
    return {
        "title": instruction or "Document",
        "working_summary": instruction,
        "word_budget": total_budget,
        "children": [],
    }
