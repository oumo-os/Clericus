"""
tests/conftest.py
-----------------
Stub out heavy native dependencies (faiss, sentence_transformers) so
all tests run in any environment — including CI without GPU/native libs.

The stubs are pure-Python shims that satisfy every import and method
call the test suite makes.  Production code uses the real libraries.
"""

import sys
import types
import numpy as np
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# faiss stub
# ---------------------------------------------------------------------------

faiss_mod = types.ModuleType("faiss")

class _FlatL2:
    def __init__(self, dim):
        self.dim = dim
        self._vecs = []
    def add(self, vecs):
        self._vecs.extend(vecs.tolist())
    def search(self, query, k):
        n = min(k, len(self._vecs))
        return np.zeros((1, n)), np.array([list(range(n))])

faiss_mod.IndexFlatL2 = _FlatL2

def _write_index(index, path):
    import pickle, os
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(index, f)

def _read_index(path):
    import pickle
    with open(path, "rb") as f:
        return pickle.load(f)

faiss_mod.write_index = _write_index
faiss_mod.read_index  = _read_index
sys.modules["faiss"] = faiss_mod


# ---------------------------------------------------------------------------
# sentence_transformers stub
# ---------------------------------------------------------------------------

st_mod = types.ModuleType("sentence_transformers")

class _SentenceTransformer:
    def __init__(self, model_name=None):
        self._dim = 16
    def encode(self, texts, convert_to_numpy=True, show_progress_bar=False):
        arr = np.random.rand(len(texts), self._dim).astype("float32")
        return arr

st_mod.SentenceTransformer = _SentenceTransformer
sys.modules["sentence_transformers"] = st_mod
