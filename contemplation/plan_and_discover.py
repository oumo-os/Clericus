
from typing import Dict, List, Any
from llm_client.call_llm import call_llm
from discovery.discovery import discover_knowledge
from internal_kb import internal_kb
from established_facts import established_facts
from question_tracker import question_tracker
from utils.config import INTERNAL_KB_TOP_K, USE_CURATED_KB, CURATED_KB_TOP_K, MAX_QUESTION_ITER
from curated_kb import CuratedKB
from utils.logging import log_info

# Initialize curated KB if enabled
curated_kb = CuratedKB(domains=None) if USE_CURATED_KB else None


def initial_contemplation(
    section_title: str,
    doc_summary: str,
    parent_summary: str,
    working_summary: str,
    word_budget: int,
    level: int,
    section_path: str
) -> List[str]:
    """
    Stage 1: Generate initial questions for the section and register them.
    Returns list of question IDs.
    """
    prompt = f"""
You are planning a section titled '{section_title}' (level {level}, ~{word_budget} words).

Document summary:
{doc_summary}

Parent section summary:
{parent_summary or '[None]'}

Working summary / placeholder:
{working_summary or '[None]'}

Tasks:
1. List 3–5 QUESTIONS this section must answer.
2. List 3–5 KNOWLEDGE GOALS (core topics or insights).
3. Suggest a preliminary OUTLINE (bullet list of 3–5 subheadings).

Return JSON:
{{
  "questions": [...],
  "knowledge_goals": [...],
  "outline": [...]
}}
""".strip()
    result = call_llm(prompt, parse_json=True)
    questions = result.get("questions", [])
    # Register questions
    qids = []
    for q in questions:
        qid = question_tracker.add_question(q, level="section", section_path=section_path)
        qids.append(qid)
    # Return question texts and ids mapping if needed
    return qids, questions, result.get("knowledge_goals", []), result.get("outline", [])


def reflective_contemplation(
    question_texts: List[str],
    fact_snippets: List[str]
) -> Dict:
    """
    Stage 3: Reflect on retrieved facts, synthesize insights, identify gaps, propose refined structure.
    """
    prompt = f"""
You asked these QUESTIONS:
{question_texts}

You retrieved these FACT SNIPPETS:
{fact_snippets}

Tasks:
1. Synthesize 3–5 INSIGHTS or THEMES from the facts.
2. Identify any GAPS or follow-up QUESTIONS.
3. Propose a REFINED STRUCTURE (3–5 headings in logical order).

Return JSON:
{{
  "insights": [...],
  "new_questions": [...],
  "suggested_structure": [...]
}}
""".strip()
    return call_llm(prompt, parse_json=True)


def plan_and_discover(
    section_title: str,
    doc_summary: str,
    parent_summary: str,
    working_summary: str,
    word_budget: int,
    level: int,
    kb_index: Any,
    section_path: str = ""
) -> Dict:
    """
    Orchestrate iterative contemplation-discovery with question tracking, EFB, internal KB, and optional curated KB.
    Returns plan containing insights, suggested_structure, knowledge_chunks, knowledge_goals.
    """
    log_info(f"Planning and discovering for section {section_path} - {section_title}")
    # Stage 1: Initial Contemplation
    qids, question_texts, knowledge_goals, outline = initial_contemplation(
        section_title, doc_summary, parent_summary, working_summary, word_budget, level, section_path
    )
    # Iterative discovery loop
    all_chunks = []
    insights = []
    suggested_structure = outline
    for iteration in range(MAX_QUESTION_ITER):
        open_entries = [
            question_tracker.get_question(qid) for qid in qids
            if question_tracker.get_question(qid) is not None
            and question_tracker.get_question(qid)['status'] == 'open'
        ]
        if not open_entries:
            break
        new_questions = []
        for entry in open_entries:
            qtext = entry['question_text']
            log_info(f"Discovering for question: {qtext}")
            # Primary discovery: external KB, internal KB, web
            primary_hits = discover_knowledge([qtext], kb_index, top_k=INTERNAL_KB_TOP_K)
            # Record answers
            for hit in primary_hits:
                question_tracker.record_answer(entry['question_id'], hit['chunk'], hit['citation'], hit['source_type'])
            all_chunks.extend(primary_hits)
            # If still open or need deeper, use curated KB if available
            if USE_CURATED_KB and curated_kb:
                curated_hits = curated_kb.query(qtext, domain=None, top_k=CURATED_KB_TOP_K)
                for ch in curated_hits:
                    question_tracker.record_answer(entry['question_id'], ch['text'], ch['metadata'], 'curated')
                all_chunks.extend([{"question":qtext, "chunk":h['text'], "citation":h['metadata'],"source_type":"curated"} for h in curated_hits])
        # Reflective contemplation
        fact_snippets = [c['chunk'] for c in all_chunks]
        reflection = reflective_contemplation(question_texts, fact_snippets)
        # Process new questions
        for nq in reflection.get('new_questions', []):
            nqid = question_tracker.add_question(nq, level="section", section_path=section_path)
            qids.append(nqid)
            question_texts.append(nq)
            new_questions.append(nq)
        # Update insights and structure
        insights = reflection.get('insights', insights)
        suggested_structure = reflection.get('suggested_structure', suggested_structure)
        if not new_questions:
            break
    # After iterations, query established facts for continuity
    efb_hits = established_facts.query_facts(section_title + ' ' + working_summary)
    # Convert efb_hits to chunks format
    for fact in efb_hits:
        snippet = fact['description']
        all_chunks.append({
            "question": None,
            "chunk": snippet,
            "citation": {"source":"established_fact","fact_id":fact['fact_id']},
            "source_type": "efb",
            "section_path":None
        })
    # Return comprehensive plan
    return {
        "insights": insights,
        "suggested_structure": suggested_structure,
        "knowledge_chunks": all_chunks,
        "knowledge_goals": knowledge_goals
    }