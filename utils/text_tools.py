
import re

def clean_text(text: str) -> str:
    """
    Performs basic cleaning: normalise line endings and collapse runs of whitespace.
    """
    text = re.sub(r"\r\n", "\n", text)   # Windows CRLF → LF
    text = re.sub(r"\r", "\n", text)     # bare CR → LF
    text = re.sub(r"\s+", " ", text)     # collapse any whitespace run to single space
    return text.strip()


def normalize_whitespace(text: str) -> str:
    """
    Ensures consistent single newlines between paragraphs.
    """
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text.strip()


def count_tokens(text: str) -> int:
    """
    Rough estimate of tokens by splitting on whitespace.
    """
    return len(text.split())


def enforce_consistency(text: str) -> str:
    """
    Placeholder for a deeper consistency check or normalization.
    Could integrate a dictionary of preferred terms.
    """
    # Example: unify hyphens
    text = text.replace(' - ', ' – ')
    return text