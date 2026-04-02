#!/usr/bin/env python3
"""
cli.py — Clericus command-line entry point
------------------------------------------
Usage examples:

  # Minimal — let Clericus plan the structure from your instruction:
  python cli.py --source ./sources --instruction "Whitepaper on renewable energy in Sub-Saharan Africa"

  # With a template file to infer structure from:
  python cli.py --source ./sources --templatefile ./my_template.md --instruction "..."

  # Anthropic backend, markdown output, fresh run:
  python cli.py --source ./sources --instruction "..." --llm-backend anthropic --format md --reset-state

  # Resume a previous run (skips already-drafted sections):
  python cli.py --source ./sources --instruction "..." --resume
"""

import argparse
import json
import logging
import os
from pathlib import Path

import utils.config as config
from export.exporters import export_document
from review.review_pipeline import traverse_and_review
from sourceprep.index import build_or_load_index
from template.analyze_template import (
    generate_structure_from_instruction,
    generate_structure_from_template,
)
from drafting.recursive_drafter import recursive_draft_section
from utils.logging import log_info, log_error

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_sources(source_dir: str) -> None:
    if not os.path.exists(source_dir):
        print(f"[X] Source directory not found: {source_dir}")
        return
    files = os.listdir(source_dir)
    if not files:
        print("[!] Source directory is empty — no source documents to index.")
    else:
        print(f"[O] Found {len(files)} file(s) in {source_dir}:")
        for f in files:
            print(f"    └── {f}")


def _reset_state() -> None:
    """Clear question tracker, established facts, and any cached section states."""
    from question_tracker import question_tracker
    from established_facts import established_facts

    question_tracker.questions.clear()
    if question_tracker.persist_path and question_tracker.persist_path.exists():
        question_tracker.persist_path.unlink(missing_ok=True)

    established_facts.facts.clear()
    try:
        if established_facts.metadata_path.exists():
            established_facts.metadata_path.unlink()
        for f in established_facts.persist_dir.glob("*"):
            f.unlink(missing_ok=True)
    except Exception:
        pass

    log_info("State reset: question tracker and established facts cleared.")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clericus",
        description="Clericus: Smart Drafting Assistant for Complex Documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--source", default="./sources",
        help="Directory of source documents (PDFs, DOCXs, TXTs). Default: ./sources",
    )
    p.add_argument(
        "--instruction", default="A report on the entities in the provided sources.",
        help="High-level document goal / topic.",
    )
    p.add_argument(
        "--templatefile", default="",
        help="Optional existing document to infer structure/style from.",
    )
    p.add_argument(
        "--output", default="output/final_document.docx",
        help="Output file path.",
    )
    p.add_argument(
        "--format", default="docx",
        choices=["docx", "pdf", "md", "html", "txt"],
        help="Export format. Default: docx",
    )
    p.add_argument(
        "--max-depth", type=int, default=3,
        help="Maximum recursion depth for section subdivision. Default: 3",
    )
    p.add_argument(
        "--llm-backend", choices=["openai", "anthropic", "gemini", "ollama", "local"],
        help="LLM backend to use (overrides LLM_BACKEND env var).",
    )
    p.add_argument(
        "--offline", action="store_true", default=False,
        help="Disable web search and curated KB (local sources only).",
    )
    p.add_argument(
        "--use-curated", action="store_true", default=False,
        help="Enable curated knowledge base enrichment.",
    )
    p.add_argument(
        "--curated-domains", type=str, default="",
        help="Comma-separated curated KB domains (e.g. 'law,general').",
    )
    p.add_argument(
        "--reset-state", action="store_true", default=False,
        help="Clear all cached drafts and facts before running.",
    )
    p.add_argument(
        "--resume", action="store_true", default=False,
        help="Resume a previous run: reuse cached section drafts (default behaviour).",
    )
    p.add_argument(
        "--output-dir", default="OUTPUT",
        help="Working directory for section state files. Default: OUTPUT",
    )
    return p


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    args = _build_parser().parse_args()
    log_info("=" * 60)
    log_info("Clericus pipeline starting")
    log_info("=" * 60)

    # --- Apply overrides ---
    if args.llm_backend:
        os.environ["LLM_BACKEND"] = args.llm_backend
        log_info(f"LLM backend: {args.llm_backend}")

    if args.offline:
        config.WEB_SEARCH_API_KEY = None
        config.USE_CURATED_KB = False
        log_info("Offline mode: web search and curated KB disabled.")

    if args.use_curated:
        config.USE_CURATED_KB = True
        if args.curated_domains:
            domains = [d.strip() for d in args.curated_domains.split(",") if d.strip()]
            os.environ["CURATED_DOMAINS"] = ",".join(domains)
            log_info(f"Curated KB domains: {domains}")

    # --- Reset state ---
    if args.reset_state:
        _reset_state()

    _verify_sources(args.source)

    try:
        # 1. Build / load source vector index
        log_info(f"Building/loading index from '{args.source}'…")
        kb_index = build_or_load_index(args.source)

        # 2. Generate document skeleton
        if args.templatefile and os.path.exists(args.templatefile):
            log_info(f"Deriving structure from template: {args.templatefile}")
            structure = generate_structure_from_template(
                args.templatefile,
                default_budget=config.DEFAULT_DOCUMENT_BUDGET,
            )
        else:
            # NEW: use LLM structure generator instead of a bare single-node dict
            log_info("Generating document structure from instruction…")
            structure = generate_structure_from_instruction(
                instruction=args.instruction,
                default_budget=config.DEFAULT_DOCUMENT_BUDGET,
            )

        log_info(
            f"Structure: '{structure.get('title')}' "
            f"({len(structure.get('children', []))} top-level sections, "
            f"budget={structure.get('word_budget')}w)"
        )

        # 3. Recursive drafting
        log_info("Recursively drafting document…")
        force_redraft = args.reset_state  # if we cleared state, don't load stale cache
        drafted = recursive_draft_section(
            node=structure,
            output_dir=args.output_dir,
            section_path="1",
            doc_summary=args.instruction,
            parent_summary="",
            kb_index=kb_index,
            level=args.max_depth,
            force_redraft=force_redraft,
        )

        # 4. Review / polish
        log_info("Reviewing and polishing document…")
        polished = traverse_and_review(drafted)

        # 5. Save intermediate JSON
        Path("output").mkdir(parents=True, exist_ok=True)
        with open("output/document.json", "w", encoding="utf-8") as fh:
            json.dump(polished, fh, indent=2, ensure_ascii=False)
        log_info("Intermediate JSON saved to output/document.json")

        # 6. Export
        log_info(f"Exporting to {args.format}: {args.output}")
        export_document(polished, args.format, args.output)

        log_info("=" * 60)
        log_info(f"Done. Output: {args.output}")
        log_info("=" * 60)

    except Exception as e:
        log_error("Pipeline encountered an error", e)
        raise


if __name__ == "__main__":
    main()
