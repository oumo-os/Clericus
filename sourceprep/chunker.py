from typing import List, Dict

# import textwrap # Not used, can be removed
from sourceprep.chunker_embed import chunk_document_text
from utils.logging import log_info  # Assuming this is available

DEFAULT_CHUNK_SIZE = 800  # Number of words per chunk
DEFAULT_CHUNK_OVERLAP = 100  # Number of overlapping words between chunks


def chunk_text_old(
    text: str,
    metadata: Dict = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[Dict]:
    """
    Splits input text into overlapping chunks with optional metadata tagging.

    Returns list of dicts: [{text: "...", metadata: {...}}, ...]
    """
    words = text.split()
    chunks = []
    start = 0
    index = 0

    while start < len(words):
        end = start + chunk_size
        chunk_words = words[start:end]
        chunk_text = " ".join(chunk_words)

        chunk = {"text": chunk_text, "metadata": metadata or {}, "chunk_index": index}
        chunks.append(chunk)

        index += 1
        start += chunk_size - overlap  # Step forward with overlap

    log_info(f"[!] Digested Sources in {index} Portions.")  # Changed to log_info

    return chunks


def chunk_text(
    text: str,
    metadata: Dict = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[Dict]:
    """
    Wraps new chunker to produce old-style list[dict] interface
    """
    chunks = chunk_document_text(text, doc_id="doc_tmp", mode="paragraph")
    chunk_list = []
    for c in chunks:
        chunk_list.append(
            {
                "text": c.text,
                "metadata": metadata or c.metadata,
                "chunk_index": c.chunk_index,
            }
        )
    return chunk_list
