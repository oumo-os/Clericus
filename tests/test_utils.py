"""
tests/test_utils.py — Unit tests for utility modules.
Run with: python -m pytest tests/ -v
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from utils.text_tools import clean_text, normalize_whitespace, count_tokens
from utils.references import dedupe_references, format_chunks_for_prompt


# ── clean_text ────────────────────────────────────────────────────────────────

class TestCleanText:
    def test_crlf_normalised(self):
        # clean_text normalises CRLF then collapses all whitespace (by design for embedding)
        # The result should have no CR and no raw CRLF sequence
        result = clean_text("hello\r\nworld")
        assert "\r" not in result          # CR must be gone
        assert "\r\n" not in result        # CRLF sequence must be gone
        assert "hello" in result and "world" in result  # content preserved

    def test_whitespace_collapsed(self):
        result = clean_text("too   many    spaces")
        assert "  " not in result
        assert "too many spaces" == result

    def test_strips_edges(self):
        assert clean_text("  hello  ") == "hello"

    def test_empty_string(self):
        assert clean_text("") == ""

    def test_does_not_match_literal_backslash_s(self):
        # The old bug: r"\\s+" matched the literal characters \s+
        text = r"hello\s+world"
        result = clean_text(text)
        # Backslash-s should survive (it's not whitespace)
        assert "\\s" in result or "s" in result


# ── normalize_whitespace ──────────────────────────────────────────────────────

class TestNormalizeWhitespace:
    def test_collapses_blank_lines(self):
        result = normalize_whitespace("para1\n\n\n\npara2")
        assert result == "para1\n\npara2"

    def test_strips(self):
        assert normalize_whitespace("  text  ") == "text"


# ── count_tokens ─────────────────────────────────────────────────────────────

class TestCountTokens:
    def test_simple(self):
        assert count_tokens("hello world foo") == 3

    def test_empty(self):
        assert count_tokens("") == 0


# ── dedupe_references ─────────────────────────────────────────────────────────

class TestDedupeReferences:
    def test_dedupes_identical_dicts(self):
        refs = [
            {"author": "Smith", "year": "2023", "title": "Report"},
            {"author": "Smith", "year": "2023", "title": "Report"},
        ]
        result = dedupe_references(refs)
        assert len(result) == 1

    def test_handles_strings(self):
        refs = ["Smith (2023)", "Smith (2023)", "Jones (2022)"]
        result = dedupe_references(refs)
        assert len(result) == 2

    def test_handles_mixed_types(self):
        refs = [
            {"author": "Smith", "year": "2023"},
            "Jones (2022)",
            None,
            {"author": "Smith", "year": "2023"},
        ]
        result = dedupe_references(refs)
        assert len(result) == 2   # None dropped, dict deduped

    def test_empty_list(self):
        assert dedupe_references([]) == []

    def test_preserves_order(self):
        refs = ["A", "B", "C", "A"]
        result = dedupe_references(refs)
        assert result == ["A", "B", "C"]


# ── format_chunks_for_prompt ──────────────────────────────────────────────────

class TestFormatChunksForPrompt:
    def test_dict_citation(self):
        chunks = [{
            "chunk": "Some evidence text.",
            "citation": {"author": "Doe", "year": "2021", "title": "Study", "filename": "doc.pdf"},
            "source_type": "external",
        }]
        result = format_chunks_for_prompt(chunks)
        assert "Doe" in result
        assert "Some evidence text." in result

    def test_string_citation(self):
        chunks = [{"chunk": "Text.", "citation": "Smith (2020) — Paper [file.pdf]"}]
        result = format_chunks_for_prompt(chunks)
        assert "Text." in result

    def test_empty(self):
        assert format_chunks_for_prompt([]) == ""
