import re
from pathlib import Path
from typing import Dict

def extract_metadata(filepath: Path, text: str) -> Dict[str, str]:
    """
    Extracts basic metadata such as title, author, publication year, and inferred citation info.
    Falls back gracefully if not found.
    """
    # Use the filename (without extension) as fallback title
    title = filepath.stem

    # Try to extract publication year from filename or text
    year = extract_year_from_text_or_filename(text, title)

    # Attempt to find author in the text (look for patterns like "By John Doe" etc.)
    author = extract_author(text)

    # Assemble a structured citation dictionary directly
    citation_dict = {
        "author": author or "Unknown Author",
        "year": year or "n.d.",
        "title": title, # Use the extracted title
        "filename": filepath.name,
        # 'page' is not extracted at this level from the raw text, so it's omitted.
        # It will gracefully fall back to '?' in format_chunks_for_prompt.
    }

    return {
        "title": title,
        "author": author or "Unknown",
        "year": year or "n.d.",
        "citation": citation_dict, # Now 'citation' is a dictionary!
        "filename": filepath.name,
        "path": str(filepath),
    }

def extract_year_from_text_or_filename(text: str, fallback_title: str) -> str:
    # Look for year patterns (e.g., 1999, 2020) in filename or first part of the text
    year_pattern = re.compile(r"(19|20)\d{2}")
    match = year_pattern.search(fallback_title)
    if match:
        return match.group()

    match = year_pattern.search(text[:1000])  # Search only in the beginning
    if match:
        return match.group()

    return None

def extract_author(text: str) -> str:
    # Look for "By [Author]" or similar patterns
    patterns = [
        r"by\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)",  # e.g., "By John Smith"
        r"Author[s]?:\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None