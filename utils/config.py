# utils/config.py — Global configuration for Clericus

import os

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
# Default backend when LLM_BACKEND env var is not set.
# Supported: "openai" | "anthropic" | "gemini" | "ollama" | "local"
LLM_BACKEND = "ollama"
OLLAMA_MODEL = "llama3.2"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
INDEX_DIR    = "vector_index"
TEMPLATES_DIR = "templates"

# ---------------------------------------------------------------------------
# Web search
# ---------------------------------------------------------------------------
WEB_SEARCH_API_URL = "https://api.bing.microsoft.com/v7.0/search"
WEB_SEARCH_API_KEY = os.getenv("BING_API_KEY", "")

# ---------------------------------------------------------------------------
# Word budgets
# ---------------------------------------------------------------------------
DEFAULT_DOCUMENT_BUDGET = 3000   # total words for the whole document
DEFAULT_SECTION_BUDGET  = 600    # fallback per-section budget

# A section is subdivided only when its budget EXCEEDS this threshold.
# Must be comfortably above DEFAULT_SECTION_BUDGET so leaf nodes don't
# keep splitting.  Tune upward for longer documents.
SUBDIVISION_WORD_THRESHOLD = 900

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
DEFAULT_CHUNK_SIZE    = 800
DEFAULT_CHUNK_OVERLAP = 100

# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
LOCAL_EMBEDDING_MODEL = "all-MiniLM-L6-v2"   # sentence-transformers name
EMBEDDING_BACKEND     = "local"

# ---------------------------------------------------------------------------
# Internal KB
# ---------------------------------------------------------------------------
USE_INTERNAL_KB    = True
INTERNAL_KB_TOP_K  = 3

# ---------------------------------------------------------------------------
# Curated KB
# ---------------------------------------------------------------------------
USE_CURATED_KB    = False
CURATED_KB_TOP_K  = 5
CURATED_KB_DIR    = "curated_kb"

# ---------------------------------------------------------------------------
# Question tracking
# ---------------------------------------------------------------------------
MAX_QUESTION_ITER = 3

# ---------------------------------------------------------------------------
# Established Facts Base
# ---------------------------------------------------------------------------
EFB_KB_DIR = ".clericus/efb_index"
EFB_TOP_K  = 5

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = "INFO"
