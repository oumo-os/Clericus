import re
from typing import List, Dict, Union # Added Union

def dedupe_references(refs: List) -> List:
    """
    Deduplicate references.  Handles both string refs and dict refs gracefully.
    """
    seen = set()
    unique = []
    for ref in refs:
        if ref is None:
            continue
        if isinstance(ref, dict):
            key = tuple(sorted((k, str(v)) for k, v in ref.items()))
        else:
            key = str(ref)
        if key not in seen:
            seen.add(key)
            unique.append(ref)
    return unique

def format_references_md(refs: List[Dict]) -> str:
    """
    Formats a list of reference dicts into a Markdown bibliography.
    """
    lines = []
    for ref in refs:
        author = ref.get('author','Unknown')
        year = ref.get('year','n.d.')
        title = ref.get('title','Untitled')
        filename = ref.get('filename','')
        lines.append(f"- {author} ({year}). *{title}*. [{filename}]")
    return "\n".join(lines)

# Modified function signature and logic
def parse_citation_text_rule_based(citation_input: Union[str, Dict]) -> Dict[str, str]:
    """
    Parses a plain text citation into a dictionary using a regex-based approach,
    or returns the input if it's already a dictionary.
    This ensures compatibility with both old string citations and new structured dict citations.
    """
    # If the input is already a dictionary, assume it's pre-parsed and return it directly.
    if isinstance(citation_input, dict):
        return citation_input
    
    # Otherwise, assume it's a string (or convert it to string for parsing).
    citation_text = str(citation_input) 

    # Updated regex pattern (your existing, flexible one)
    pattern = re.compile(
        r"^(.*?)\s*\((\d{4}|n\.d\.)\)\s*[\-.]\s*(.*?)(?:,\s*p\.(\d+|\?)\s*)?\[?(.*?)\]?$",
        re.IGNORECASE
    )
    match = pattern.match(citation_text.strip())

    if match:
        author, year, title, page, filename = match.groups()
        return {
            "author": (author or "Unknown").strip(),
            "year": (year or "n.d.").strip(),
            "title": (title or citation_text).strip(),
            "page": (page or '?').strip(),
            "filename": (filename or '').strip()
        }
    else:
        # Fallback if pattern doesn't match for a string input
        print(f"Warning: Citation text '{citation_text}' did not match expected pattern. Returning basic info.")
        return {
            "source": citation_text,
            "author": "Unknown",
            "year": "n.d.",
            "title": citation_text,
            "page": "?",
            "filename": ""
        }
    
def format_chunks_for_prompt(chunks: List[Dict]) -> str:
    """
    Formats knowledge chunks into a prompt block with inline citations.
    """
    lines = []
    for i, item in enumerate(chunks, 1):
        text = item.get("chunk") or item.get("text", "")
        # This will now correctly handle both string and dict citations due to parse_citation_text_rule_based
        citation = parse_citation_text_rule_based(item.get("citation", {})) 
        
        # Extract citation fields
        author = citation.get('author', citation.get('source', 'Unknown'))
        year = citation.get('year', citation.get('date', 'n.d.'))
        title = citation.get('title', citation.get('source', ''))
        filename = citation.get('filename', '')
        page = citation.get('page', '?')
        meta = f"{author} ({year}) - {title}, p.{page} [{filename}]"
        lines.append(f"[Source {i}] {meta}\n{text}")
    return "\n\n".join(lines)