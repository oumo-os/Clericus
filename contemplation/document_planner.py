"""
contemplation/document_planner.py
-----------------------------------
Document-level planning pass — runs BEFORE structure generation.

Purpose: before the LLM proposes a document skeleton, give it a chance to
think about the sources and form an informed view of what the document needs
to cover.  This produces:

  - document_questions  : top-level questions the document must answer
  - key_themes          : recurring themes / concepts found in the sources
  - recommended_sections: a prioritised section list with rationale
  - doc_summary         : a concise paragraph summarising what will be written

The output feeds directly into generate_structure_from_instruction() as a
richer prompt seed, replacing the bare instruction string.

Usage (called from cli.py before structure generation):

    from contemplation.document_planner import plan_document
    plan = plan_document(instruction, kb_index)
    structure = generate_structure_from_instruction(
        instruction=plan["doc_summary"],
        default_budget=config.DEFAULT_DOCUMENT_BUDGET,
    )
"""

from typing import Any, Dict, List

from llm_client.call_llm import call_llm
from retrieval.retriever import query_knowledge_base
from established_facts import established_facts
from question_tracker import question_tracker
from utils.config import INTERNAL_KB_TOP_K, MAX_QUESTION_ITER
from utils.logging import log_info


def plan_document(
    instruction: str,
    kb_index: Any,
    max_sample_chunks: int = 12,
) -> Dict:
    """
    Run the document-level planning pass.

    Steps:
      1. Sample a broad set of chunks from the KB to understand source coverage.
      2. Ask the LLM to generate document-level questions and key themes.
      3. Register questions in the question tracker.
      4. Run up to MAX_QUESTION_ITER discovery rounds: retrieve, reflect, refine.
      5. Produce a concise doc_summary and recommended section list.

    Returns a dict:
        {
          "doc_summary":            str,   # enriched instruction for structure generator
          "document_questions":     [...], # question strings
          "key_themes":             [...], # theme strings
          "recommended_sections":   [...], # section title strings in order
          "knowledge_chunks":       [...], # raw KB hits (passed to first-section context)
        }
    """
    log_info("=== Document-level planning pass ===")

    # ------------------------------------------------------------------
    # 1. Sample source KB broadly — use the instruction as the seed query
    # ------------------------------------------------------------------
    sample_hits = query_knowledge_base(kb_index, instruction, k=max_sample_chunks)
    source_snippets = [h["text"][:300] for h in sample_hits]
    source_block = "\n\n".join(
        f"[Source {i+1}] {snip}" for i, snip in enumerate(source_snippets)
    )
    log_info(f"Sampled {len(source_snippets)} source chunks for document planning.")

    # ------------------------------------------------------------------
    # 2. Initial document contemplation
    # ------------------------------------------------------------------
    contemplation_prompt = (
        "You are planning a complex document. Read the following source excerpts "
        "and the document goal, then produce a thorough planning response.\n\n"
        f"DOCUMENT GOAL:\n{instruction}\n\n"
        f"SOURCE EXCERPTS:\n{source_block}\n\n"
        "Tasks:\n"
        "1. List 4-6 QUESTIONS this document must definitively answer.\n"
        "2. List 4-6 KEY THEMES or concepts that appear in the sources.\n"
        "3. Suggest 4-8 RECOMMENDED SECTIONS in logical reading order.\n"
        "4. Write a concise DOCUMENT SUMMARY (2-3 sentences) describing "
        "what this document will cover and for whom.\n\n"
        "Return JSON:\n"
        "{\n"
        '  "document_questions": [...],\n'
        '  "key_themes": [...],\n'
        '  "recommended_sections": [...],\n'
        '  "doc_summary": "..."\n'
        "}"
    )

    try:
        plan = call_llm(contemplation_prompt, parse_json=True)
    except Exception as e:
        log_info(f"Document contemplation LLM call failed: {e}. Using bare instruction.")
        return _fallback(instruction, sample_hits)

    document_questions: List[str] = plan.get("document_questions", [])
    key_themes: List[str]         = plan.get("key_themes", [])
    recommended_sections: List[str] = plan.get("recommended_sections", [])
    doc_summary: str              = plan.get("doc_summary", instruction)

    # ------------------------------------------------------------------
    # 3. Register document-level questions
    # ------------------------------------------------------------------
    qids = []
    for q in document_questions:
        qid = question_tracker.add_question(q, level="document", section_path=None)
        qids.append(qid)
    log_info(f"Registered {len(qids)} document-level questions.")

    # ------------------------------------------------------------------
    # 4. Iterative discovery: retrieve, reflect, refine
    # ------------------------------------------------------------------
    all_chunks = list(sample_hits)

    for iteration in range(MAX_QUESTION_ITER):
        open_qs = [
            question_tracker.get_question(qid)
            for qid in qids
            if question_tracker.get_question(qid) is not None
            and question_tracker.get_question(qid)["status"] == "open"
        ]
        if not open_qs:
            break

        new_questions_this_round = []
        for entry in open_qs:
            qtext = entry["question_text"]
            hits = query_knowledge_base(kb_index, qtext, k=INTERNAL_KB_TOP_K)
            for hit in hits:
                question_tracker.record_answer(
                    entry["question_id"],
                    hit.get("text", ""),
                    hit.get("metadata", {}),
                    "external",
                )
            all_chunks.extend(hits)

        # Reflect on what we've found
        fact_snippets = [c.get("text", c.get("chunk", ""))[:200] for c in all_chunks[-20:]]
        reflection_prompt = (
            f"You are refining a document plan for: '{instruction}'.\n\n"
            f"Questions asked:\n" + "\n".join(f"- {q['question_text']}" for q in open_qs) + "\n\n"
            f"Evidence retrieved:\n" + "\n".join(f"- {s}" for s in fact_snippets) + "\n\n"
            "Tasks:\n"
            "1. List any NEW questions that the evidence raises (or [] if none).\n"
            "2. Update the RECOMMENDED SECTIONS list if the evidence changes priorities.\n"
            "3. Refine the DOCUMENT SUMMARY to be more specific.\n\n"
            "Return JSON:\n"
            '{"new_questions": [...], "recommended_sections": [...], "doc_summary": "..."}'
        )
        try:
            reflection = call_llm(reflection_prompt, parse_json=True)
        except Exception:
            break

        for nq in reflection.get("new_questions", []):
            nqid = question_tracker.add_question(nq, level="document", section_path=None)
            qids.append(nqid)
            new_questions_this_round.append(nq)

        if reflection.get("recommended_sections"):
            recommended_sections = reflection["recommended_sections"]
        if reflection.get("doc_summary"):
            doc_summary = reflection["doc_summary"]

        log_info(
            f"Planning iteration {iteration+1}: "
            f"{len(new_questions_this_round)} new questions, "
            f"{len(recommended_sections)} sections."
        )
        if not new_questions_this_round:
            break

    log_info(
        f"Document plan complete: {len(recommended_sections)} sections, "
        f"summary='{doc_summary[:80]}…'"
    )

    return {
        "doc_summary":           doc_summary,
        "document_questions":    document_questions,
        "key_themes":            key_themes,
        "recommended_sections":  recommended_sections,
        "knowledge_chunks":      all_chunks,
    }


def _fallback(instruction: str, sample_hits: List[Dict]) -> Dict:
    """Minimal fallback when LLM is unavailable."""
    return {
        "doc_summary":           instruction,
        "document_questions":    [],
        "key_themes":            [],
        "recommended_sections":  [],
        "knowledge_chunks":      sample_hits,
    }
