"""
tests/test_mock_llm_pipeline.py
Integration-level tests using a mock LLM — no real API calls, no network.

Patches call_llm globally so the full recursive_draft_section / draft_section
flow can be exercised without any credentials.
"""

import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


# ── Mock LLM responses ────────────────────────────────────────────────────────

def _mock_call_llm(prompt: str, parse_json: bool = False, **kwargs):
    """
    Returns plausible-but-minimal JSON for any prompt Clericus sends.
    Detected by scanning the prompt for keywords.
    """
    p = prompt.lower()

    # plan_and_discover / initial_contemplation
    if "questions" in p and "knowledge goals" in p:
        r = {"questions": ["What is the scope?"], "knowledge_goals": ["Understand topic"], "outline": ["Introduction", "Analysis"]}
        return r if parse_json else json.dumps(r)

    # reflective_contemplation
    if "insights" in p and "suggested_structure" in p:
        r = {"insights": ["Key insight"], "new_questions": [], "suggested_structure": ["Introduction", "Analysis"]}
        return r if parse_json else json.dumps(r)

    # draft_section — initial draft
    if '"body"' in p or '"openning"' in p or "openning" in p:
        r = {"title": "Test Section", "openning": "This section opens.", "body": "Body content here. " * 20, "closing": "In summary.", "references": []}
        return r if parse_json else json.dumps(r)

    # follow-up questions (enrichment)
    if "gaps" in p and "questions" in p:
        r = {"questions": []}
        return r if parse_json else json.dumps(r)

    # review_section
    if "consistency" in p or "reviewing" in p:
        r = {"openning": "Opening.", "body": "Body content.", "closing": "Closing.", "new_questions": [], "new_references": []}
        return r if parse_json else json.dumps(r)

    # extract_facts_from_section
    if "extract key facts" in p:
        r = {"facts": [{"fact_type": "claim", "description": "A key fact."}]}
        return r if parse_json else json.dumps(r)

    # document_planner
    if "document goal" in p and "source excerpts" in p:
        r = {"document_questions": ["Q1?"], "key_themes": ["theme"], "recommended_sections": ["Intro", "Body", "Conclusion"], "doc_summary": "A document about the topic."}
        return r if parse_json else json.dumps(r)

    # structure generator
    if "recommended sections" in p or "section structure" in p or "document architect" in p:
        r = {"title": "Generated Doc", "working_summary": "About topic.", "word_budget": 3000, "children": [
            {"title": "Introduction",  "working_summary": "", "word_budget": 600, "children": []},
            {"title": "Main Body",     "working_summary": "", "word_budget": 900, "children": []},
            {"title": "Conclusion",    "working_summary": "", "word_budget": 600, "children": []},
        ]}
        return r if parse_json else json.dumps(r)

    # fallback
    r = {}
    return r if parse_json else "{}"


# ── Mock KB index ─────────────────────────────────────────────────────────────

def make_mock_kb():
    from utils.vector_store import SimpleVectorStore, SearchResult
    kb = MagicMock(spec=SimpleVectorStore)
    kb.similarity_search.return_value = [
        SearchResult(page_content="Source evidence chunk.", metadata={"citation": {"author": "Test", "year": "2024", "title": "Source"}, "filename": "test.pdf"})
    ]
    return kb


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestDraftSectionMock:
    @patch("llm_client.call_llm.call_llm", side_effect=_mock_call_llm)
    def test_returns_expected_keys(self, mock_llm, tmp_path):
        from drafting.draft_section import draft_section

        result = draft_section(
            doc_summary="A test document.",
            parent_summary="",
            section_title="Introduction",
            working_summary="Overview of topic.",
            knowledge_chunks=[],
            word_budget=500,
            allow_subsections=False,
            kb_index=make_mock_kb(),
        )

        assert "title" in result
        assert "openning" in result
        assert "body" in result
        assert "closing" in result
        assert "references" in result
        assert isinstance(result["body"], str)
        assert isinstance(result["references"], list)

    @patch("llm_client.call_llm.call_llm", side_effect=_mock_call_llm)
    def test_handles_llm_failure_gracefully(self, mock_llm, tmp_path):
        mock_llm.side_effect = Exception("LLM unavailable")
        from drafting.draft_section import draft_section

        result = draft_section(
            doc_summary="Doc.", parent_summary="", section_title="Test",
            working_summary="", knowledge_chunks=[], word_budget=300, kb_index=None,
        )
        # Should return a fallback dict, not raise
        assert "title" in result
        assert result["body"] == "" or isinstance(result["body"], str)


class TestRecursiveDrafterMock:
    @patch("llm_client.call_llm.call_llm", side_effect=_mock_call_llm)
    def test_single_node_produces_output(self, mock_llm, tmp_path):
        from drafting.recursive_drafter import recursive_draft_section

        node = {"title": "Test Section", "working_summary": "", "word_budget": 400, "children": []}
        result = recursive_draft_section(
            node=node,
            output_dir=str(tmp_path),
            kb_index=make_mock_kb(),
            doc_summary="Test document.",
            parent_summary="",
            section_path="1",
            level=0,
        )
        assert result["title"] is not None
        assert "section_path" in result
        assert result["section_path"] == "1"

    @patch("llm_client.call_llm.call_llm", side_effect=_mock_call_llm)
    def test_predefined_children_are_respected(self, mock_llm, tmp_path):
        """Pre-defined children must produce child results, not be ignored."""
        from drafting.recursive_drafter import recursive_draft_section

        node = {
            "title": "Parent",
            "working_summary": "",
            "word_budget": 2000,
            "children": [
                {"title": "Child A", "working_summary": "", "word_budget": 500, "children": []},
                {"title": "Child B", "working_summary": "", "word_budget": 500, "children": []},
            ],
        }
        result = recursive_draft_section(
            node=node,
            output_dir=str(tmp_path),
            kb_index=make_mock_kb(),
            doc_summary="Doc.",
            parent_summary="",
            section_path="1",
            level=2,
        )
        assert "children" in result
        # Both pre-defined children must have been drafted
        assert len(result["children"]) == 2, (
            f"Expected 2 children, got {len(result.get('children',[]))}"
        )

    @patch("llm_client.call_llm.call_llm", side_effect=_mock_call_llm)
    def test_resume_reuses_cache(self, mock_llm, tmp_path):
        """A second call with the same section_path should load from cache."""
        from drafting.recursive_drafter import recursive_draft_section, save_section_state

        cached = {"id": "1", "title": "Cached", "body_text": "From cache.", "children": [], "section_path": "1", "references": []}
        save_section_state("1", cached, str(tmp_path))

        node = {"title": "Should not be used", "working_summary": "", "word_budget": 400, "children": []}
        result = recursive_draft_section(
            node=node, output_dir=str(tmp_path), kb_index=make_mock_kb(),
            doc_summary="Doc.", parent_summary="", section_path="1", level=1,
            force_redraft=False,
        )
        assert result["title"] == "Cached"
        assert result["body_text"] == "From cache."

    @patch("llm_client.call_llm.call_llm", side_effect=_mock_call_llm)
    def test_force_redraft_ignores_cache(self, mock_llm, tmp_path):
        from drafting.recursive_drafter import recursive_draft_section, save_section_state

        cached = {"id": "1", "title": "Stale Cache", "body_text": "Old.", "children": [], "section_path": "1", "references": []}
        save_section_state("1", cached, str(tmp_path))

        node = {"title": "Fresh", "working_summary": "", "word_budget": 400, "children": []}
        result = recursive_draft_section(
            node=node, output_dir=str(tmp_path), kb_index=make_mock_kb(),
            doc_summary="Doc.", parent_summary="", section_path="1", level=0,
            force_redraft=True,
        )
        assert result["title"] != "Stale Cache"


class TestFullPipelineMock:
    @patch("llm_client.call_llm.call_llm", side_effect=_mock_call_llm)
    def test_traverse_and_review_on_drafted_tree(self, mock_llm, tmp_path):
        """traverse_and_review should not crash on the output of recursive_draft_section."""
        from drafting.recursive_drafter import recursive_draft_section
        from review.review_pipeline import traverse_and_review

        node = {
            "title": "Document",
            "working_summary": "",
            "word_budget": 2000,
            "children": [
                {"title": "Introduction", "working_summary": "", "word_budget": 400, "children": []},
                {"title": "Conclusion",   "working_summary": "", "word_budget": 400, "children": []},
            ],
        }
        drafted = recursive_draft_section(
            node=node, output_dir=str(tmp_path), kb_index=make_mock_kb(),
            doc_summary="A test doc.", parent_summary="", section_path="1", level=2,
        )
        polished = traverse_and_review(drafted)
        assert polished["title"] is not None
        # All children should still be there
        assert len(polished.get("children", [])) == 2

    @patch("llm_client.call_llm.call_llm", side_effect=_mock_call_llm)
    def test_export_md_after_full_pipeline(self, mock_llm, tmp_path):
        from drafting.recursive_drafter import recursive_draft_section
        from review.review_pipeline import traverse_and_review
        from export.exporters import export_to_md

        node = {
            "title": "Report",
            "working_summary": "A report.",
            "word_budget": 1500,
            "children": [
                {"title": "Findings",   "working_summary": "", "word_budget": 400, "children": []},
                {"title": "Conclusion", "working_summary": "", "word_budget": 400, "children": []},
            ],
        }
        drafted  = recursive_draft_section(node=node, output_dir=str(tmp_path), kb_index=make_mock_kb(), doc_summary="Report.", parent_summary="", section_path="1", level=2)
        polished = traverse_and_review(drafted)
        out = tmp_path / "report.md"
        export_to_md(polished, str(out))
        content = out.read_text()
        assert "Report" in content
        assert out.stat().st_size > 0
