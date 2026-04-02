import os
from pathlib import Path
from typing import List, Dict, Any
from sourceprep.metadata import extract_metadata
from sourceprep.chunker import chunk_text
from utils.text_tools import clean_text

# Import PDF and DOCX libraries at the top for clarity and consistency
from PyPDF2 import PdfReader  # Moved import
from docx import Document  # Moved import

SUPPORTED_FORMATS = [".txt", ".md", ".pdf", ".docx"]  # Extendable if needed


def load_documents(source_dir: str) -> List[Dict[str, Any]]:
    """
    Loads all supported documents from the source directory, extracting metadata and chunking them.
    Returns a list of dicts: each containing content, metadata, and chunked text.
    """
    documents = []
    source_path = Path(source_dir)

    # Walk through all files in the directory and subdirectories
    for filepath in source_path.rglob("*"):
        ext = filepath.suffix.lower()
        if ext not in SUPPORTED_FORMATS:
            continue  # Skip unsupported formats

        # Extract raw text content based on filetype
        if ext == ".txt" or ext == ".md":
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read()
        elif ext == ".pdf":
            text = extract_text_from_pdf(filepath)
        elif ext == ".docx":
            text = extract_text_from_docx(filepath)

        # Clean the text for consistent processing
        cleaned = clean_text(text)

        # Extract document-level metadata (author, title, etc.)
        metadata = extract_metadata(filepath, cleaned)

        # Chunk the cleaned text into smaller RAG-optimized segments
        chunks = chunk_text(cleaned, metadata)

        # Save the full document entry
        documents.append(
            {
                "path": str(filepath),
                "metadata": metadata,
                "raw_text": cleaned,
                "chunks": chunks,
            }
        )

    return documents


def extract_text_from_pdf(filepath: Path) -> str:
    # PyPDF2 is now imported at the top
    reader = PdfReader(str(filepath))
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text



def extract_text_from_docx(filepath: Path) -> str:
    # docx is now imported at the top
    doc = Document(str(filepath))
    return "\n".join([para.text for para in doc.paragraphs])
