# utils/embeddings.py
"""
Thin helper retained for backward compatibility.
All vector indexing now goes through utils.vector_store.SimpleVectorStore,
which owns the SentenceTransformer model directly.
This module is kept so any external code that imports get_embedding_model()
doesn't break; it simply returns the configured model name string.
"""
from utils.config import LOCAL_EMBEDDING_MODEL


def get_embedding_model_name() -> str:
    """Returns the configured sentence-transformers model name."""
    return LOCAL_EMBEDDING_MODEL


# Legacy shim — previously returned a LangChain embeddings object.
# Returns the model name string so callers that only use it for
# SimpleVectorStore construction still work.
def get_embedding_model() -> str:
    return get_embedding_model_name()
