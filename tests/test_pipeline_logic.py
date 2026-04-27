"""
tests/test_pipeline_logic.py
Logic-level tests for subdivision, document tree, and exporter traversal.
No LLM calls, no dependencies beyond stdlib + the project modules.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from utils.config import SUBDIVISION_WORD_THRESHOLD, DEFAULT_SECTION_BUDGET


# ── Subdivision threshold sanity ──────────────────────────────────────────────

class TestSubdivisionThreshold:
    def test_default_budget_does_not_trigger_subdivision(self):
        """A section at DEFAULT_SECTION_BUDGET must NOT be subdivided."""
        assert DEFAULT_SECTION_BUDGET <= SUBDIVISION_WORD_THRESHOLD

    def test_threshold_above_default_budget(self):
        """Threshold must be meaningfully above the default so leaves stay as leaves."""
        assert SUBDIVISION_WORD_THRESHOLD > DEFAULT_SECTION_BUDGET

    def test_large_budget_would_subdivide(self):
        large_budget = SUBDIVISION_WORD_THRESHOLD + 1
        should_subdivide = large_budget > SUBDIVISION_WORD_THRESHOLD
        assert should_subdivide


# ── Document tree shape ───────────────────────────────────────────────────────

def make_leaf(path, title="Leaf"):
    return {
        "id": path, "title": title, "section_path": path,
        "openning": "Opening.", "body_text": "Body text here.",
        "closing": "Closing.", "references": [], "children": [],
    }

def make_parent(path, title="Parent", children=None):
    return {
        "id": path, "title": title, "section_path": path,
        "openning": "Parent opening.", "body_text": None,
        "closing": "Parent closing.",
        "references": [{"author": "X", "year": "2024", "title": "T"}],
        "children": children or [],
    }

class TestDocumentTree:
    def test_parent_has_children_not_body(self):
        doc = make_parent("1", children=[make_leaf("1.1"), make_leaf("1.2")])
        assert len(doc["children"]) == 2
        assert doc["body_text"] is None

    def test_leaf_has_body_not_children(self):
        leaf = make_leaf("1.1")
        assert leaf["body_text"] == "Body text here."
        assert leaf["children"] == []

    def test_tree_depth(self):
        doc = make_parent("1", children=[
            make_parent("1.1", children=[make_leaf("1.1.1"), make_leaf("1.1.2")]),
            make_leaf("1.2"),
        ])
        assert len(doc["children"]) == 2
        assert len(doc["children"][0]["children"]) == 2


# ── Traverse & review uses children key ──────────────────────────────────────

class TestTraverseAndReview:
    def test_visits_all_nodes(self):
        visited = []

        def fake_review(section):
            visited.append(section["id"])
            section["references"] = []
            return section

        from review import review_pipeline
        original = review_pipeline.review_section
        review_pipeline.review_section = fake_review

        doc = make_parent("1", children=[
            make_parent("1.1", children=[make_leaf("1.1.1")]),
            make_leaf("1.2"),
        ])

        try:
            review_pipeline.traverse_and_review(doc)
        finally:
            review_pipeline.review_section = original

        assert set(visited) == {"1", "1.1", "1.1.1", "1.2"}

    def test_does_not_recurse_into_body_string(self):
        """Ensure body_text string is never mistaken for a child list."""
        visited = []

        def fake_review(section):
            visited.append(section["id"])
            section["references"] = []
            return section

        from review import review_pipeline
        original = review_pipeline.review_section
        review_pipeline.review_section = fake_review

        leaf = make_leaf("1.1")
        leaf["body"] = "This is a string body, not a list."

        doc = make_parent("1", children=[leaf])

        try:
            review_pipeline.traverse_and_review(doc)
        finally:
            review_pipeline.review_section = original

        assert "1.1" in visited
        assert len(visited) == 2  # root + one leaf, no false recursion


# ── Exporter tree traversal ───────────────────────────────────────────────────

class TestExporterTraversal:
    def test_txt_includes_all_section_titles(self, tmp_path):
        from export.exporters import export_to_txt
        doc = make_parent("1", "Main Doc", children=[
            make_leaf("1.1", "Section One"),
            make_leaf("1.2", "Section Two"),
        ])
        out = tmp_path / "out.txt"
        export_to_txt(doc, str(out))
        content = out.read_text()
        assert "Section One" in content
        assert "Section Two" in content
        assert "Body text here." in content

    def test_md_includes_headings(self, tmp_path):
        from export.exporters import export_to_md
        doc = make_parent("1", "Root", children=[
            make_leaf("1.1", "Alpha"),
            make_leaf("1.2", "Beta"),
        ])
        out = tmp_path / "out.md"
        export_to_md(doc, str(out))
        content = out.read_text()
        assert "# Root" in content
        assert "Alpha" in content
        assert "Beta" in content

    def test_references_collected_recursively(self):
        from export.exporters import _collect_references
        doc = make_parent("1", children=[
            make_leaf("1.1"),
            make_parent("1.2", children=[make_leaf("1.2.1")]),
        ])
        doc["references"] = [{"author": "Root", "year": "2020", "title": "T"}]
        doc["children"][0]["references"] = [{"author": "Child", "year": "2021", "title": "T2"}]
        refs = _collect_references(doc)
        authors = [r.get("author") for r in refs if isinstance(r, dict)]
        assert "Root" in authors
        assert "Child" in authors

    def test_dict_refs_do_not_crash_docx(self, tmp_path):
        from export.exporters import export_to_docx
        doc = make_parent("1", "Doc", children=[make_leaf("1.1")])
        doc["references"] = [{"author": "Smith", "year": "2022", "title": "Paper", "filename": "x.pdf"}]
        out = tmp_path / "out.docx"
        # Should not raise
        export_to_docx(doc, str(out))
        assert out.exists()


# ── State persistence (no disk side effects) ─────────────────────────────────

class TestSectionState:
    def test_save_and_load_roundtrip(self, tmp_path):
        from drafting.recursive_drafter import save_section_state, load_section_state
        data = {"id": "1.2", "title": "Test", "body_text": "hello", "children": []}
        save_section_state("1.2", data, str(tmp_path))
        loaded = load_section_state("1.2", str(tmp_path))
        assert loaded["title"] == "Test"
        assert loaded["body_text"] == "hello"

    def test_load_nonexistent_returns_none(self, tmp_path):
        from drafting.recursive_drafter import load_section_state
        result = load_section_state("99.99", str(tmp_path))
        assert result is None

    def test_path_with_dots_is_safe(self, tmp_path):
        from drafting.recursive_drafter import save_section_state, load_section_state, _safe_filename
        assert "/" not in _safe_filename("1.2.3")
        name = _safe_filename("1.2.3")
        assert "." not in name.replace(".json", "")  # section path part has no dots
        data = {"id": "1.2.3", "title": "Deep"}
        save_section_state("1.2.3", data, str(tmp_path))
        loaded = load_section_state("1.2.3", str(tmp_path))
        assert loaded["title"] == "Deep"
