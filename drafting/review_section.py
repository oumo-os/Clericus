"""
Review a drafted section for continuity, consistency, and completeness.
Generates a review prompt using internal KB, established facts, and question tracker,
then applies suggested refinements from the LLM.
"""
from typing import Dict, Any, List
from llm_client.call_llm import call_llm
from internal_kb import internal_kb
from established_facts import established_facts
from question_tracker import question_tracker
from discovery.discovery import discover_knowledge
from utils.references import format_chunks_for_prompt
from utils.text_tools import count_tokens
from utils.config import INTERNAL_KB_TOP_K, EFB_TOP_K, USE_CURATED_KB, CURATED_KB_TOP_K
from curated_kb import CuratedKB
from utils.logging import log_info

# Initialize curated KB if needed
curated_kb = None
if USE_CURATED_KB:
    try:
        curated_kb = CuratedKB(domains=None)
    except Exception:
        log_info("Failed to initialize CuratedKB in review_section; continuing without curated enrichment.")

def review_section(
    draft: Dict[str, Any],
    section_meta: Dict[str, Any],
    kb_index: Any,
    efb: Any
) -> Dict[str, Any]:
    """
    Review the drafted section:
    - Check against internal KB cross-references
    - Check against established facts for continuity
    - Identify unresolved questions
    - Suggest refinements
    Returns a dict with keys:
      - title, openning, body, closing (possibly revised)
      - new_references: list of added citations
      - discovery_hits: any new knowledge hits (optional)
      - efb_crossrefs: list of relevant established facts
      - unresolved_questions: list of open questions still unresolved
    """
    title = section_meta.get("title", "")
    section_path = section_meta.get("section_path", "")
    intro = draft.get("openning", "")
    body = draft.get("body", draft.get("body_text", ""))
    concl = draft.get("closing", "")

    # Prepare context blocks
    # Internal KB context
    internal_block = ''
    try:
        internal_hits = internal_kb.query_internal(title + ' ' + body, top_k=INTERNAL_KB_TOP_K)
    except Exception as e:
        log_info(f"Internal KB query failed in review_section: {e}")
        internal_hits = []
    if internal_hits:
        lines = ['Previously in this document:']
        for hit in internal_hits:
            snippet = hit.get('snippet', '')[:200].replace('\n', ' ')
            lines.append(f"- Section {hit.get('section_path')}: {hit.get('title')}\n  '{snippet}...'" )
        internal_block = '\n'.join(lines)

    # Established Facts context
    efb_block = ''
    try:
        efb_hits = efb.query_facts(title + ' ' + body, top_k=EFB_TOP_K)
    except Exception as e:
        log_info(f"EFB query failed in review_section: {e}")
        efb_hits = []
    efb_crossrefs = []
    if efb_hits:
        lines = ['Relevant established facts:']
        for fact in efb_hits:
            desc = fact.get('description', '')
            refs = ', '.join(fact.get('context_refs', []))
            lines.append(f"- {desc} (introduced in sections: {refs})")
            efb_crossrefs.append(fact)
        efb_block = '\n'.join(lines)

    # Open questions for this section
    open_qs = question_tracker.get_open_questions(level="section")
    relevant_open = []
    for q in open_qs:
        if q.get('section_path') == section_path:
            relevant_open.append(q.get('question_text'))
    open_block = ''
    if relevant_open:
        open_block = 'Open questions for this section:\n' + '\n'.join(f"- {q}" for q in relevant_open)

    # Build review prompt
    prompt_parts: List[str] = [
        "You are reviewing a drafted section for consistency and completeness.",
        "",
        f"SECTION TITLE: {title}",
        "",
        "OPENNING:", intro,
        "",
        "BODY:", body,
        "",
        "CLOSING:", concl,
    ]
    if internal_block:
        prompt_parts.extend(["", internal_block])
    if efb_block:
        prompt_parts.extend(["", efb_block])
    if open_block:
        prompt_parts.extend(["", open_block])
    prompt_parts.extend([
        "", "Tasks:",
        "1. Confirm the section addresses all important questions or flag any remaining gaps.",
        "2. Detect contradictions or continuity issues with established facts or earlier sections.",
        "3. Suggest refinements or additional details to improve coherence and completeness.",
        "Return a JSON with keys: 'title', 'openning', 'body', 'closing', 'new_questions' (list), 'new_references' (list)."
    ])
    review_prompt = '\n'.join(prompt_parts)

    # Token check
    token_estimate = count_tokens(review_prompt)
    if token_estimate > 3000:
        log_info(f"Review prompt token estimate {token_estimate} high for section {section_path}")

    # Call LLM for review
    try:
        review_resp = call_llm(review_prompt, parse_json=True)
    except Exception as e:
        log_info(f"LLM call failed in review_section: {e}")
        review_resp = {}

    # Extract revisions
    revised = {}
    revised['title'] = review_resp.get('title', title)
    revised['openning'] = review_resp.get('openning', intro).strip()
    revised['body'] = review_resp.get('body', body).strip()
    revised['closing'] = review_resp.get('closing', concl).strip()
    new_questions = review_resp.get('new_questions', []) or []
    new_references = review_resp.get('new_references', []) or []
    # Register new questions
    for qtext in new_questions:
        question_tracker.add_question(qtext, level="section", section_path=section_path)

    return {
        'title': revised['title'],
        'openning': revised['openning'],
        'body': revised['body'],
        'closing': revised['closing'],
        'new_questions': new_questions,
        'new_references': new_references,
        'discovery_hits': [],  # could be populated if review triggers new discovery
        'efb_crossrefs': efb_crossrefs,
        'unresolved_questions': relevant_open
    }
