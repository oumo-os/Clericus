"""
drafting/draft_section.py
--------------------------
Draft a single leaf section using:
  1. Initial LLM pass with all available context (KB chunks, internal cross-refs, EFB facts).
  2. Post-draft enrichment: generate follow-up questions, query KBs for new chunks,
     re-draft if new material was found.

Note: the post-enrichment *review* pass that used to be steps 7-8 here has been
removed.  recursive_drafter.py calls drafting.review_section separately after
draft_section returns, so reviewing inside draft_section was a redundant double-pass
that could produce contradictory revisions.
"""

from typing import List, Dict, Any
from llm_client.call_llm import call_llm
from utils.references import format_chunks_for_prompt
from utils.text_tools import count_tokens
from internal_kb import internal_kb
from established_facts import established_facts
from question_tracker import question_tracker
from discovery.discovery import discover_knowledge
from utils.config import INTERNAL_KB_TOP_K, EFB_TOP_K, USE_CURATED_KB, CURATED_KB_TOP_K
from curated_kb import CuratedKB
from utils.logging import log_info

curated_kb = CuratedKB(domains=None) if USE_CURATED_KB else None


def draft_section(
    doc_summary: str,
    parent_summary: str,
    section_title: str,
    working_summary: str,
    knowledge_chunks: List[Dict[str, Any]],
    word_budget: int,
    allow_subsections: bool = True,
    kb_index: Any = None,
) -> Dict[str, Any]:
    """
    Draft one leaf section.  Returns a dict with keys:
        title, openning, body, closing, references
    and optionally `subdivisions` when allow_subsections=True.
    """

    # ------------------------------------------------------------------
    # Context builder helpers
    # ------------------------------------------------------------------

    def _sources_block(chunks: List[Dict[str, Any]]) -> str:
        external = [c for c in chunks if c.get("source_type") in ("external", "web", "curated")]
        return format_chunks_for_prompt(external) if external else ""

    def _internal_block() -> str:
        try:
            hits = internal_kb.query_internal(
                section_title + " " + working_summary, top_k=INTERNAL_KB_TOP_K
            )
        except Exception as e:
            log_info(f"Internal KB query failed: {e}")
            hits = []
        if not hits:
            return ""
        lines = ["Previously in this document:"]
        for h in hits:
            snippet = h.get("snippet", "")[:200].replace("\n", " ")
            lines.append(f"- Section {h['section_path']}: {h['title']}\n  '{snippet}…'")
        return "\n".join(lines)

    def _efb_block(query: str) -> str:
        try:
            facts = established_facts.query_facts(query, top_k=EFB_TOP_K)
        except Exception as e:
            log_info(f"EFB query failed: {e}")
            facts = []
        if not facts:
            return ""
        lines = ["Relevant established facts:"]
        for f in facts:
            desc = f.get("description", "")
            refs = ", ".join(f.get("context_refs", []))
            lines.append(f"- {desc} (introduced in: {refs})")
        return "\n".join(lines)

    def build_context(chunks: List[Dict[str, Any]], query: str) -> str:
        parts = []
        src = _sources_block(chunks)
        if src:
            parts += ["FACTUAL MATERIALS (source text + citations):", src]
        iblock = _internal_block()
        if iblock:
            parts.append(iblock)
        efb = _efb_block(query)
        if efb:
            parts.append(efb)
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # 1. Build initial context
    # ------------------------------------------------------------------
    context_block = build_context(knowledge_chunks, section_title + " " + working_summary)

    # ------------------------------------------------------------------
    # 2. Initial draft prompt
    # ------------------------------------------------------------------
    prompt_parts = [
        "You are writing a structured document section.",
        "",
        "DOCUMENT SUMMARY:", doc_summary,
        "",
        "PARENT SECTION SUMMARY:", parent_summary or "[None]",
        "",
        "SECTION TITLE:", section_title,
        "",
        "WORKING SUMMARY:", working_summary or "[None]",
    ]
    if context_block:
        prompt_parts += ["", context_block]
    prompt_parts += [
        "",
        "Produce a JSON object with exactly these keys:",
        '  "title": section title (string),',
        '  "openning": 1-2 sentence overview (string),',
        f'  "body": detailed prose up to {word_budget} words (string),',
        '  "closing": 1 paragraph wrap-up (string),',
        '  "references": list of citation dicts (array).',
    ]
    if allow_subsections:
        prompt_parts += [
            '  "subdivisions" (optional): array of {"heading","summary","word_budget"}'
            " if the section is too large for a single pass.",
        ]
    prompt_parts.append(f"Stay within {word_budget} words for the body.")

    initial_prompt = "\n".join(prompt_parts)
    if count_tokens(initial_prompt) > 3000:
        log_info(f"Initial prompt is large ({count_tokens(initial_prompt)} tokens) for '{section_title}'")

    # ------------------------------------------------------------------
    # 3. Call LLM for initial draft
    # ------------------------------------------------------------------
    try:
        response = call_llm(initial_prompt, parse_json=True)
    except Exception as e:
        log_info(f"LLM call failed for initial draft of '{section_title}': {e}")
        return {
            "title": section_title, "openning": "", "body": "",
            "closing": "", "references": [], "word_budget": word_budget,
        }

    section: Dict[str, Any] = {
        "title":      response.get("title", section_title),
        "openning":   (response.get("openning", "") or "").strip(),
        "body":       (response.get("body", "") or "").strip(),
        "closing":    (response.get("closing", "") or "").strip(),
        "references": response.get("references", []) or [],
        "word_budget": word_budget,
    }
    if allow_subsections and response.get("subdivisions"):
        section["subdivisions"] = response["subdivisions"]

    # ------------------------------------------------------------------
    # 4. Post-draft enrichment: discover follow-up knowledge
    # ------------------------------------------------------------------
    # Ask for follow-up questions as a JSON object (not bare array) so
    # JSON-constrained backends (Ollama, Gemini) return a parseable object.
    follow_prompt = (
        f"The following section draft was just written:\n\n"
        f"Title: {section['title']}\n"
        f"Body excerpt: {section['body'][:500]}\n\n"
        "Identify up to 5 important questions or gaps that need further evidence.\n"
        'Return JSON: {"questions": ["...", ...]}'
    )
    try:
        fq_resp = call_llm(follow_prompt, parse_json=True)
        follow_qs = fq_resp.get("questions", []) if isinstance(fq_resp, dict) else []
        if not isinstance(follow_qs, list):
            follow_qs = []
    except Exception:
        follow_qs = []

    # ------------------------------------------------------------------
    # 5. Query KBs for follow-up knowledge
    # ------------------------------------------------------------------
    new_chunks: List[Dict] = []
    if follow_qs and kb_index:
        for q in follow_qs:
            log_info(f"Enrichment discovery for: {q}")
            hits = discover_knowledge(
                [q], kb_index,
                top_k=INTERNAL_KB_TOP_K,
                use_curated=USE_CURATED_KB,
                curated_kb=curated_kb,
            )
            for hit in hits:
                if hit not in knowledge_chunks and hit not in new_chunks:
                    new_chunks.append(hit)
    # Also pull EFB facts related to follow-up questions
    if follow_qs:
        for q in follow_qs:
            try:
                efb_hits = established_facts.query_facts(q, top_k=EFB_TOP_K)
            except Exception:
                efb_hits = []
            for fact in efb_hits:
                chunk = {
                    "question": q,
                    "chunk": fact.get("description", ""),
                    "citation": {"source": "established_fact", "fact_id": fact["fact_id"]},
                    "source_type": "efb",
                    "section_path": None,
                }
                if chunk not in knowledge_chunks and chunk not in new_chunks:
                    new_chunks.append(chunk)

    # ------------------------------------------------------------------
    # 6. Re-draft if new material found
    # ------------------------------------------------------------------
    if new_chunks:
        knowledge_chunks = list(knowledge_chunks) + new_chunks
        context_block2 = build_context(knowledge_chunks, section.get("body", ""))
        refined_parts = [
            "Revise the following document section using new information.",
            "",
            "PREVIOUS DRAFT BODY:", section.get("body", ""),
            "",
            "NEW CONTEXT:", context_block2,
            "",
            "Produce a revised JSON object with the same keys as before:",
            '  "title", "openning", "body", "closing", "references".',
            f"Integrate the new information. Stay within {word_budget} words for body.",
        ]
        if allow_subsections:
            refined_parts.append('  "subdivisions" (optional): suggest splits if needed.')
        try:
            refined = call_llm("\n".join(refined_parts), parse_json=True)
            section["openning"]   = (refined.get("openning",   section["openning"]) or "").strip()
            section["body"]       = (refined.get("body",       section["body"]) or "").strip()
            section["closing"]    = (refined.get("closing",    section["closing"]) or "").strip()
            old_refs = section.get("references", [])
            new_refs = refined.get("references", []) or []
            section["references"] = old_refs + [r for r in new_refs if r not in old_refs]
            if allow_subsections and refined.get("subdivisions"):
                section["subdivisions"] = refined["subdivisions"]
        except Exception as e:
            log_info(f"Refined draft LLM call failed for '{section_title}': {e}")

    # Register any new follow-up questions in the tracker (for reporting, not blocking)
    for q in follow_qs:
        question_tracker.add_question(q, level="section", section_path=None)

    return section
