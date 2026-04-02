"""
Template Handling Module for Clericus
====================================

This module implements a self-contained Template Handling system that:
- Generates a template from an example document (heuristic extractor)
- Loads preset templates by document kind
- Serializes/deserializes templates to YAML
- Interfaces with an LLM-based Structure Generator through an abstract client
- Supports adjustments after QA/Contemplation/Discovery (e.g., update budgets, citations)
- Validates and normalizes templates (percentage vs absolute budgets)

Dependencies:
- pyyaml

Usage:
- Use TemplateHandler.from_example_document(...) to produce a template
- Save/load via TemplateStore
- Plug in an LLM by implementing LLMStructureGeneratorBase and pass to TemplateHandler

"""

from __future__ import annotations
import re
import math
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Union, Dict, Any, Protocol
import yaml

# -----------------------------
# Data model
# -----------------------------

Budget = Union[int, float]  # int = absolute words, float = fraction (0<x<=1)


@dataclass
class TemplateNode:
    id: str
    title: str
    placeholder: str = ""
    word_budget: Optional[Budget] = None
    required: bool = False
    citations_required: int = 0
    templates: List[str] = field(default_factory=list)
    children: List["TemplateNode"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # recursion already handled by asdict
        return d

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "TemplateNode":
        children = [TemplateNode.from_dict(c) for c in data.get("children", [])]
        return TemplateNode(
            id=data["id"],
            title=data.get("title", ""),
            placeholder=data.get("placeholder", ""),
            word_budget=data.get("word_budget", None),
            required=data.get("required", False),
            citations_required=data.get("citations_required", 0),
            templates=data.get("templates", []),
            children=children,
        )


# -----------------------------
# LLM interface (abstract)
# -----------------------------


class LLMStructureGeneratorBase(Protocol):
    """Protocol for an LLM-backed structure generator. Implement this for your LLM client.
    The implementation should accept either a seed template, or user instructions, and return
    a TemplateNode (root).
    """

    def generate_structure(
        self,
        *,
        seed_template: Optional[TemplateNode] = None,
        document_kind: Optional[str] = None,
        user_instructions: Optional[str] = None,
        max_depth: Optional[int] = None,
    ) -> TemplateNode: ...


# -----------------------------
# Template extraction heuristics
# -----------------------------

HEADING_MD = re.compile(r"^(#{1,6})\s*(.+)$", flags=re.MULTILINE)
HEADING_UNDERLINE = re.compile(r"^(.+)\n[=-]{2,}$", flags=re.MULTILINE)
ALL_CAPS_LINE = re.compile(r"^[A-Z\d][A-Z\s\d]{3,}$")


def _count_words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not s:
        s = uuid.uuid4().hex[:8]
    return s


class TemplateExtractor:
    """Heuristic extractor: given document text, produce a TemplateNode tree.

    Strategy (simple, robust):
    1. Prefer Markdown headings. If present, split by top-level headings (H1/H2) into sections.
    2. Else, detect "underlined" headings or ALL CAPS headings.
    3. If none found, split into N equal-chunk sections by paragraphs.
    4. For each section, compute relative word count and emit a TemplateNode where
       word_budget is a fraction (percentage) of the total document unless `target_word_budget`
       is passed, in which case absolute budgets are emitted.
    """

    def __init__(self, min_sections: int = 3, max_sections: int = 15):
        self.min_sections = min_sections
        self.max_sections = max_sections

    def from_text(
        self,
        text: str,
        document_title: Optional[str] = None,
        target_word_budget: Optional[int] = None,
    ) -> TemplateNode:
        secs = self._split_sections(text)
        if not secs:
            secs = self._split_by_paragraphs(text)

        totals = [_count_words(s[1]) for s in secs]
        total_words = sum(totals) or 1
        # clamp number of sections
        if len(secs) < self.min_sections:
            secs = self._split_by_paragraphs(text, target_n=self.min_sections)
            totals = [_count_words(s[1]) for s in secs]
            total_words = sum(totals) or 1

        # Build root node
        root_budget: Optional[Budget]
        if target_word_budget is not None:
            root_budget = target_word_budget
        else:
            root_budget = 1.0  # 100% fractional representation

        root = TemplateNode(
            id=_slugify(document_title or "root"),
            title=document_title or "Document",
            placeholder=(text[:240].strip() + "...") if text else "",
            word_budget=root_budget,
            required=True,
            children=[],
        )

        for i, (heading, body) in enumerate(secs):
            weight = totals[i] / total_words
            if target_word_budget is not None:
                node_budget: Budget = max(50, int(round(weight * target_word_budget)))
            else:
                node_budget = round(weight, 4)  # fractional
            node = TemplateNode(
                id=_slugify(heading or f"section-{i+1}"),
                title=heading or f"Section {i+1}",
                placeholder=(body[:200].strip() + "...") if body else "",
                word_budget=node_budget,
                required=(i == 0),
            )
            root.children.append(node)

        return root

    def _split_sections(self, text: str) -> List[tuple]:
        # Markdown headings
        md_matches = list(HEADING_MD.finditer(text))
        if md_matches:
            # collect headers with their start indexes
            headers = [(m.start(), m.group(2).strip()) for m in md_matches]
            headers.append((len(text), None))
            secs = []
            for (start, title), (end, _) in zip(headers, headers[1:]):
                # find the body between this heading and the next
                # get heading line end
                m = HEADING_MD.search(text, pos=start)
                if not m:
                    continue
                body_start = m.end()
                body = text[body_start:end].strip()
                secs.append((title, body))
            return secs

        # underline style
        um = list(HEADING_UNDERLINE.finditer(text))
        if um:
            headers = [(m.start(1), m.group(1).strip()) for m in um]
            headers.append((len(text), None))
            secs = []
            for (start, title), (end, _) in zip(headers, headers[1:]):
                # find body after the underline (two-lines pattern)
                # approximate: body starts after the underline line
                # naive approach:
                body = text[end:].split("\n\n", 1)[0].strip()
                secs.append((title, body))
            return secs

        # ALL CAPS lines
        caps = []
        for i, line in enumerate(text.splitlines()):
            if ALL_CAPS_LINE.match(line.strip()):
                caps.append((i, line.strip()))
        if caps:
            lines = text.splitlines()
            secs = []
            for j, (lineno, title) in enumerate(caps):
                start = sum(len(L) + 1 for L in lines[: lineno + 1])
                # estimate end at next caps or end of text
                next_lineno = caps[j + 1][0] if j + 1 < len(caps) else None
                end_idx = (
                    sum(len(L) + 1 for L in lines[:next_lineno])
                    if next_lineno
                    else len(text)
                )
                body = text[start:end_idx].strip()
                secs.append((title, body))
            return secs

        return []

    def _split_by_paragraphs(
        self, text: str, target_n: Optional[int] = None
    ) -> List[tuple]:
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not paras:
            return [("Section 1", text[:400])] if text else []
        # If target_n given, merge or split accordingly
        n = target_n or min(len(paras), self.max_sections)
        if len(paras) <= n:
            return [(f"Paragraph {i+1}", paras[i]) for i in range(len(paras))]

        # otherwise distribute paragraphs into n buckets roughly evenly
        buckets = [[] for _ in range(n)]
        for i, p in enumerate(paras):
            buckets[i % n].append(p)
        return [(f"Section {i+1}", "\n\n".join(b)) for i, b in enumerate(buckets) if b]


# -----------------------------
# Template store (YAML)
# -----------------------------


class TemplateStore:
    @staticmethod
    def save_to_yaml(root: TemplateNode, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                {"root": root.to_dict()}, f, sort_keys=False, allow_unicode=True
            )

    @staticmethod
    def load_from_yaml(path: str) -> TemplateNode:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data or "root" not in data:
            raise ValueError("YAML file does not contain 'root' mapping")
        return TemplateNode.from_dict(data["root"])


# -----------------------------
# Template handler - glue
# -----------------------------


class TemplateHandler:
    def __init__(
        self,
        llm: Optional[LLMStructureGeneratorBase] = None,
        presets: Optional[Dict[str, TemplateNode]] = None,
        max_depth: int = 6,
    ):
        self.llm = llm
        self.presets = presets or {}
        self.max_depth = max_depth

    def register_preset(self, kind: str, template: TemplateNode) -> None:
        self.presets[kind] = template

    def from_example_document(
        self,
        text: str,
        document_title: Optional[str] = None,
        document_kind: Optional[str] = None,
        target_word_budget: Optional[int] = None,
    ) -> TemplateNode:
        extractor = TemplateExtractor()
        base_template = extractor.from_text(
            text, document_title=document_title, target_word_budget=target_word_budget
        )
        # If a preset exists for this kind, attempt a merge where preset keys override/explain
        if document_kind and document_kind in self.presets:
            merged = self._merge_with_preset(base_template, self.presets[document_kind])
            return self._normalize_and_validate(merged)
        return self._normalize_and_validate(base_template)

    def from_preset(self, kind: str) -> TemplateNode:
        if kind not in self.presets:
            raise KeyError(f"Preset {kind} not registered")
        return self._normalize_and_validate(self.presets[kind])

    def generate_structure_with_llm(
        self,
        seed_template: Optional[TemplateNode] = None,
        document_kind: Optional[str] = None,
        user_instructions: Optional[str] = None,
    ) -> TemplateNode:
        if not self.llm:
            raise RuntimeError(
                "No LLM available; inject an LLMStructureGeneratorBase implementation"
            )
        root = self.llm.generate_structure(
            seed_template=seed_template,
            document_kind=document_kind,
            user_instructions=user_instructions,
            max_depth=self.max_depth,
        )
        return self._normalize_and_validate(root)

    def adjust_after_contemplation(
        self, template: TemplateNode, contemplation_log: Dict[str, Any]
    ) -> TemplateNode:
        """Adjust a template based on outputs from the contemplation/discovery step.

        contemplation_log expected shape (example):
          {
            "sections": {
               "section-id": {"unresolved_questions": [...], "found_citations": 3, "important": True},
               ...
            }
          }
        """
        mapping = contemplation_log.get("sections", {})

        def _rec(node: TemplateNode):
            info = mapping.get(node.id, {})
            # bump citations_required to match discovered citations if needed
            found = info.get("found_citations")
            if isinstance(found, int) and found > node.citations_required:
                node.citations_required = found
            # if unresolved questions exist, mark required
            unresolved = info.get("unresolved_questions") or []
            if unresolved:
                node.required = True
            for c in node.children:
                _rec(c)

        _rec(template)
        return self._normalize_and_validate(template)

    def _merge_with_preset(
        self, base: TemplateNode, preset: TemplateNode
    ) -> TemplateNode:
        # Merge by node id where possible, else append preset children
        mapping = {n.id: n for n in base.children}
        merged_children = []
        for pchild in preset.children:
            if pchild.id in mapping:
                # merge field-wise (preset overrides when non-empty)
                bchild = mapping[pchild.id]
                merged = TemplateNode(
                    id=bchild.id,
                    title=pchild.title or bchild.title,
                    placeholder=pchild.placeholder or bchild.placeholder,
                    word_budget=(
                        pchild.word_budget
                        if pchild.word_budget is not None
                        else bchild.word_budget
                    ),
                    required=pchild.required or bchild.required,
                    citations_required=max(
                        pchild.citations_required, bchild.citations_required
                    ),
                    templates=(pchild.templates or bchild.templates),
                    children=pchild.children or bchild.children,
                )
                merged_children.append(merged)
            else:
                merged_children.append(pchild)
        # append unmatched base children
        for bchild in base.children:
            if bchild.id not in {c.id for c in merged_children}:
                merged_children.append(bchild)
        return TemplateNode(
            id=preset.id or base.id,
            title=preset.title or base.title,
            placeholder=preset.placeholder or base.placeholder,
            word_budget=preset.word_budget or base.word_budget,
            required=preset.required or base.required,
            citations_required=max(preset.citations_required, base.citations_required),
            templates=preset.templates or base.templates,
            children=merged_children,
        )

    def _normalize_and_validate(self, root: TemplateNode) -> TemplateNode:
        # Ensure depth is within bounds and budgets make sense.
        self._enforce_depth(root, 1)
        self._normalize_budgets(root)
        self._validate_budgets(root)
        return root

    def _enforce_depth(self, node: TemplateNode, depth: int) -> None:
        if depth > self.max_depth:
            # truncate
            node.children = []
            return
        for c in node.children:
            self._enforce_depth(c, depth + 1)

    def _normalize_budgets(self, root: TemplateNode) -> None:
        """If root.word_budget is absolute (int) and children use fractions, convert them to absolute.
        If root is fractional, ensure child fractions sum to <=1; if not, normalize proportionally.
        """
        # detect if root is absolute
        if isinstance(root.word_budget, int):
            total_word_budget = root.word_budget
            # if children budgets are fractions, convert
            for c in root.children:
                if c.word_budget is None:
                    c.word_budget = max(
                        50, int(total_word_budget / max(1, len(root.children)))
                    )
                elif isinstance(c.word_budget, float):
                    c.word_budget = max(
                        50, int(round(c.word_budget * total_word_budget))
                    )
        else:
            # root is fractional (or None) - ensure children sum <=1
            frac_children = [
                c for c in root.children if isinstance(c.word_budget, float)
            ]
            total_frac = (
                sum(c.word_budget for c in frac_children) if frac_children else 0.0
            )
            if total_frac > 1 and total_frac > 0:
                # normalize
                for c in frac_children:
                    c.word_budget = round(c.word_budget / total_frac, 4)

    def _validate_budgets(self, root: TemplateNode) -> None:
        # Basic checks: absolute budgets >= 50 words; fraction budgets between 0 and 1.
        def _rec(node: TemplateNode):
            if node.word_budget is None:
                return
            if isinstance(node.word_budget, int):
                if node.word_budget < 50:
                    # bump to minimum to avoid tiny sections
                    node.word_budget = 50
            elif isinstance(node.word_budget, float):
                if not (0 < node.word_budget <= 1):
                    raise ValueError(
                        f"Fractional word_budget for node {node.id} must be in (0,1], got {node.word_budget}"
                    )
            for c in node.children:
                _rec(c)

        _rec(root)


# -----------------------------
# Mock LLM for testing / example
# -----------------------------


class MockLLM(LLMStructureGeneratorBase):
    def generate_structure(
        self,
        *,
        seed_template: Optional[TemplateNode] = None,
        document_kind: Optional[str] = None,
        user_instructions: Optional[str] = None,
        max_depth: Optional[int] = None,
    ) -> TemplateNode:
        # Very simple mock: if seed_template provided, add a conclusion child
        root = seed_template or TemplateNode(
            id="mock-root", title="Mock Document", word_budget=1.0
        )
        if not any(c.id == "conclusion" for c in root.children):
            root.children.append(
                TemplateNode(
                    id="conclusion",
                    title="Conclusion",
                    placeholder="Summarize main findings",
                    word_budget=0.05,
                )
            )
        return root


# -----------------------------
# Example usage & quick test
# -----------------------------

if __name__ == "__main__":
    sample = """
# Title of the Document

This is an overview paragraph.

## Background

Background paragraph explaining context. More text here.

## Methods

Detailed method explanation.

## Results

Results summary and important data.

## Discussion

Implications and future work.

"""
    handler = TemplateHandler(llm=MockLLM())
    t = handler.from_example_document(sample, document_title="Sample Doc")
    print("Generated template (root):", t.title)
    for c in t.children:
        print(f" - {c.title}: budget={c.word_budget}, id={c.id}")

    # Save to YAML
    TemplateStore.save_to_yaml(t, "sample_template.yaml")
    print("Saved sample_template.yaml")

    # Generate a structure with the LLM (mock)
    structured = handler.generate_structure_with_llm(seed_template=t)
    print("After LLM generation, children:")
    for c in structured.children:
        print("  ", c.id, c.title, c.word_budget)

""
