"""
chunker_embed.py (extended)
- Chunk documents (paragraph/sentence)
- Extract first-pages metadata (LLM-assisted optional, or local regex fallback)
- Store doc-level metadata under chunk.metadata['doc_meta']
- Build local FAISS index using sentence-transformers
- Save / load chunks + index
Usage:
    inst = LocalChunkIndex()
    inst.add_documents_from_paths(["./docs/contract.pdf"], mode="paragraph", extract_meta_pages=2, llm_client=None)
    inst.build_faiss_index()
    inst.save("index_dir")
"""

from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Iterable, Tuple, Any
import os
import json
import pickle
import re
from pathlib import Path
from sentence_transformers import SentenceTransformer
import numpy as np
import faiss


# ----------------------- # Data structures # -----------------------
@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    chunk_index: int
    page_id: Optional[int]
    text: str
    char_start: int
    char_end: int
    source_path: Optional[str] = None
    metadata: Dict[str, Any] = None

    def to_dict(self):
        d = asdict(self)
        if self.metadata is None:
            d["metadata"] = {}
        return d


# ----------------------- # Utilities # -----------------------
def normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


##see ingest.py
def load_text_from_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    if p.suffix.lower() in {".txt", ".md"}:
        return p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".pdf":
        try:
            import PyPDF2

            text_parts = []
            with open(p, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text_parts.append(page.extract_text() or "")
            # keep page delimiter marker \f so we can detect pages
            return "\f".join(text_parts)
        except Exception:
            raise RuntimeError(
                "PDF support requires PyPDF2; install or pre-extract text."
            )
    raise RuntimeError(f"Unsupported file type: {p.suffix}")


# ----------------------- # Simple chunkers # -----------------------
def chunk_text_into_paragraphs(text: str) -> List[Tuple[str, int, int]]:
    text = text.replace("\r\n", "\n")
    paragraphs = []
    for match in re.finditer(
        r"(?:[^\n][\n]?)+?(?=(\n\s*\n)|\Z)", text, flags=re.MULTILINE
    ):
        para = match.group(0)
        start = match.start()
        end = match.end()
        cleaned = normalize_whitespace(para)
        if cleaned:
            paragraphs.append((cleaned, start, end))
    if not paragraphs and text.strip():
        cleaned = normalize_whitespace(text)
        paragraphs = [(cleaned, 0, len(text))]
    return paragraphs


def chunk_text_into_sentences(
    text: str, min_chars: int = 40
) -> List[Tuple[str, int, int]]:
    sentences = []
    # naive sentence pattern
    pattern = r"([A-Z0-9][^\.!?]*[\.!?])"
    for match in re.finditer(pattern, text, flags=re.M):
        s = match.group(0).strip()
        start = match.start()
        end = match.end()
        sentences.append((s, start, end))
    if not sentences:
        return [(normalize_whitespace(text), 0, len(text))]
    grouped = []
    buffer = ""
    bstart = sentences[0][1]
    bend = sentences[0][2]
    for sent, sstart, send in sentences:
        if not buffer:
            buffer = sent
            bstart = sstart
            bend = send
        else:
            if len(buffer) < min_chars:
                buffer = buffer + " " + sent
                bend = send
            else:
                grouped.append((normalize_whitespace(buffer), bstart, bend))
                buffer = sent
                bstart = sstart
                bend = send
    if buffer:
        grouped.append((normalize_whitespace(buffer), bstart, bend))
    return grouped


def chunk_document_text(
    text: str,
    doc_id: str,
    source_path: Optional[str] = None,
    mode: str = "paragraph",
    page_split_hint: bool = True,
) -> List[Chunk]:
    if mode not in {"paragraph", "sentence"}:
        raise ValueError("mode must be 'paragraph' or 'sentence'")
    base_chunks = (
        chunk_text_into_paragraphs(text)
        if mode == "paragraph"
        else chunk_text_into_sentences(text)
    )
    chunks: List[Chunk] = []
    # detect pages using form-feed marker if present (we create it when extracting PDFs)
    page_break_positions = []
    if "\f" in text:
        # build map of character positions for page starts
        pages = text.split("\f")
        pos = 0
        for p in pages:
            page_break_positions.append(pos)
            pos += len(p) + 1  # +1 for the \f
    for idx, (chunk_text, start, end) in enumerate(base_chunks):
        page_id = None
        if page_split_hint and page_break_positions:
            # find page id where chunk start falls
            page_id = max(
                i for i, ppos in enumerate(page_break_positions) if ppos <= start
            )
        c = Chunk(
            chunk_id=f"{doc_id}::{idx}",
            doc_id=doc_id,
            chunk_index=idx,
            page_id=page_id,
            text=chunk_text,
            char_start=start,
            char_end=end,
            source_path=source_path,
            metadata={},
        )
        chunks.append(c)
    return chunks


# ----------------------- # Metadata extraction (LLM optional, else heuristic -----------------------
def heuristic_metadata_extraction(first_text: str) -> Dict[str, Optional[str]]:
    """
    Try to extract title, date, author/jurisdiction using heuristics/regex from first pages text.
    Returns a dict with keys: title, author, date, jurisdiction, short_summary
    """
    meta = {
        "title": None,
        "author": None,
        "date": None,
        "jurisdiction": None,
        "short_summary": None,
    }
    lines = [ln.strip() for ln in first_text.splitlines() if ln.strip()]
    if not lines:
        return meta
    # Title heuristic: longest line among first 5 non-empty lines or first line if it is short.
    head_lines = lines[:8]
    # prefer lines in all-caps or title case
    candidates = sorted(head_lines, key=lambda s: (-len(s), s))
    # choose line with most words but not too long
    title = None
    for cand in candidates[:4]:
        if 2 <= len(cand.split()) <= 12:
            title = cand
            break
    if not title:
        title = head_lines[0]
    meta["title"] = normalize_whitespace(title)
    # date heuristic: look for common date patterns
    date_pattern = r"(\b(?:\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]* \d{2,4})\b|\b\d{4}-\d{2}-\d{2}\b|\b(?:\d{1,2}/\d{1,2}/\d{2,4})\b)"
    m = re.search(date_pattern, first_text, flags=re.I)
    if m:
        meta["date"] = m.group(0)
    # author/jurisdiction heuristic: lines that contain words like 'Department', 'Ministry', 'Court', 'Ltd', 'Inc', 'By'
    for ln in head_lines[1:6]:
        if re.search(
            r"\b(Department|Ministry|Court|Judge|Ltd|Inc|LLP|Company|By)\b",
            ln,
            flags=re.I,
        ):
            meta["author"] = ln
            break
    # short summary: first 2 sentences after title if present
    sents = re.split(r"(?<=[\.!?])\s+", first_text.strip())
    if sents:
        meta["short_summary"] = normalize_whitespace(" ".join(sents[:2]))[:400]
    return meta


def llm_metadata_extraction(
    first_text: str, llm_client: Any, pages: int = 2
) -> Dict[str, Optional[str]]:
    """
    Use an LLM client to extract structured metadata. llm_client must expose call_llm_sync(prompt:str, parse_json:bool=True) -> dict-like (or call_llm_async).
    The function asks for JSON with keys: title, author, date, jurisdiction, summary.
    """
    prompt = f"""
    You will be given the first {pages} page(s) of a document. Extract structured metadata and return valid JSON with keys:
    - title (string or null)
    - author_or_issuer (string or null)
    - date (string or null)
    - jurisdiction (string or null)
    - short_summary (one-sentence summary, or null)
    Text: {first_text[:8000]}
    Return only JSON.
    """
    # attempt to call sync API
    try:
        resp = llm_client.call_llm_sync(prompt, parse_json=True)
        if isinstance(resp, dict):
            # map returned keys to our canonical names if necessary
            out = {
                "title": resp.get("title")
                or resp.get("document_title")
                or resp.get("name"),
                "author": resp.get("author_or_issuer")
                or resp.get("author")
                or resp.get("issuer"),
                "date": resp.get("date"),
                "jurisdiction": resp.get("jurisdiction"),
                "short_summary": resp.get("short_summary") or resp.get("summary"),
            }
            return out
    except Exception:
        pass
    # fallback to heuristic if LLM fails
    return heuristic_metadata_extraction(first_text)


# ----------------------- # Embedder + Indexer # -----------------------
class LocalEmbedder:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self._model = SentenceTransformer(model_name, device=device)

    def embed_texts(self, texts: Iterable[str], batch_size: int = 64) -> np.ndarray:
        texts = list(texts)
        embs = self._model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return embs.astype("float32")


class FAISSIndexWrapper:
    def __init__(self, dim: int, index: Optional[faiss.Index] = None):
        self.dim = dim
        self.index = index or faiss.IndexFlatIP(dim)
        self.id_map: List[str] = []

    def add(self, vectors: np.ndarray, chunk_ids: List[str]):
        if vectors.dtype != np.float32:
            vectors = vectors.astype("float32")
        self.index.add(vectors)
        self.id_map.extend(chunk_ids)

    def search(self, query_vectors: np.ndarray, top_k: int = 5) -> List[List[tuple]]:
        if query_vectors.dtype != np.float32:
            query_vectors = query_vectors.astype("float32")
        D, I = self.index.search(query_vectors, top_k)
        results = []
        for row_idx in range(I.shape[0]):
            row = []
            for j, idx in enumerate(I[row_idx]):
                if idx < 0 or idx >= len(self.id_map):
                    continue
                chunk_id = self.id_map[idx]
                score = float(D[row_idx, j])
                row.append((chunk_id, score))
            results.append(row)
        return results

    def save(self, path_prefix: str):
        faiss.write_index(self.index, f"{path_prefix}.faiss")
        with open(f"{path_prefix}.idmap.pkl", "wb") as f:
            pickle.dump(self.id_map, f)

    @classmethod
    def load(cls, path_prefix: str, dim: int):
        index = faiss.read_index(f"{path_prefix}.faiss")
        with open(f"{path_prefix}.idmap.pkl", "rb") as f:
            id_map = pickle.load(f)
        wrapper = cls(dim, index=index)
        wrapper.id_map = id_map
        return wrapper


# ----------------------- # Top-level builder # -----------------------
class LocalChunkIndex:
    def __init__(self, embedder: Optional[LocalEmbedder] = None):
        self.embedder = embedder or LocalEmbedder()
        self.chunks: Dict[str, Chunk] = {}
        self.index: Optional[FAISSIndexWrapper] = None
        self.dim = None

    def add_document_from_text(
        self,
        text: str,
        doc_id: str,
        source_path: Optional[str] = None,
        mode: str = "paragraph",
        extract_meta_pages: int = 2,
        llm_client: Optional[Any] = None,
    ):
        """
        Adds a document's chunks and attaches doc-level metadata. If llm_client is provided, it will be asked to extract structured metadata from the first extract_meta_pages pages; otherwise a heuristic extractor runs.
        """
        # prepare first-pages text for metadata extraction
        first_text = text
        # If the PDF-style page separator \f used, get first N pages
        if "\f" in text:
            pages = text.split("\f")
            first_text = "\f".join(pages[:extract_meta_pages])
        else:
            # otherwise, use first ~3000 chars
            first_text = text[:8000]
        # attempt LLM extraction if provided, else heuristic
        if llm_client is not None:
            try:
                doc_meta = llm_metadata_extraction(
                    first_text, llm_client, pages=extract_meta_pages
                )
            except Exception:
                doc_meta = heuristic_metadata_extraction(first_text)
        else:
            doc_meta = heuristic_metadata_extraction(first_text)
        # create chunks and attach doc_meta into chunk.metadata['doc_meta']
        chunks = chunk_document_text(text, doc_id, source_path=source_path, mode=mode)
        for c in chunks:
            c.metadata = c.metadata or {}
            c.metadata["doc_meta"] = doc_meta
            # also include extraction hint showing which part used
            c.metadata["meta_extracted_from"] = (
                "first_pages" if extract_meta_pages else "full"
            )
            self.chunks[c.chunk_id] = c

    def add_documents_from_paths(
        self,
        paths: Iterable[str],
        mode: str = "paragraph",
        extract_meta_pages: int = 2,
        llm_client: Optional[Any] = None,
    ):
        for p in paths:
            text = load_text_from_file(p)
            doc_id = Path(p).stem
            self.add_document_from_text(
                text,
                doc_id=doc_id,
                source_path=str(p),
                mode=mode,
                extract_meta_pages=extract_meta_pages,
                llm_client=llm_client,
            )

    def build_faiss_index(self, batch_size: int = 128):
        if not self.chunks:
            raise ValueError("No chunks to index")
        # ensure deterministic order: by doc_id then chunk_index
        ordered = sorted(
            self.chunks.keys(),
            key=lambda x: (self.chunks[x].doc_id, self.chunks[x].chunk_index),
        )
        texts = [self.chunks[cid].text for cid in ordered]
        chunk_ids = ordered
        vectors = self.embedder.embed_texts(texts, batch_size=batch_size)
        self.dim = vectors.shape[1]
        self.index = FAISSIndexWrapper(dim=self.dim)
        self.index.add(vectors, chunk_ids)

    def save(self, path_dir: str):
        os.makedirs(path_dir, exist_ok=True)
        with open(os.path.join(path_dir, "chunks.jsonl"), "w", encoding="utf-8") as f:
            for cid in self.chunks:
                f.write(
                    json.dumps(self.chunks[cid].to_dict(), ensure_ascii=False) + "\n"
                )
        assert self.index is not None, "Index not built"
        self.index.save(os.path.join(path_dir, "faiss_index"))
        with open(os.path.join(path_dir, "meta.pkl"), "wb") as f:
            pickle.dump({"dim": self.dim, "embedder": self.embedder.model_name}, f)

    @classmethod
    def load(cls, path_dir: str):
        chunks = {}
        with open(os.path.join(path_dir, "chunks.jsonl"), "r", encoding="utf-8") as f:
            for line in f:
                obj = json.loads(line)
                c = Chunk(
                    chunk_id=obj["chunk_id"],
                    doc_id=obj["doc_id"],
                    chunk_index=obj["chunk_index"],
                    page_id=obj.get("page_id"),
                    text=obj["text"],
                    char_start=obj["char_start"],
                    char_end=obj["char_end"],
                    source_path=obj.get("source_path"),
                    metadata=obj.get("metadata", {}),
                )
                chunks[c.chunk_id] = c
        with open(os.path.join(path_dir, "meta.pkl"), "rb") as f:
            meta = pickle.load(f)
        dim = meta["dim"]
        embedder_name = meta.get("embedder", "all-MiniLM-L6-v2")
        inst = cls(LocalEmbedder(model_name=embedder_name))
        inst.chunks = chunks
        inst.dim = dim
        inst.index = FAISSIndexWrapper.load(
            os.path.join(path_dir, "faiss_index"), dim=dim
        )
        return inst

    def embed_query(self, query: str) -> np.ndarray:
        vec = self.embedder.embed_texts([query])
        return vec

    def lookup_chunk(self, chunk_id: str) -> Chunk:
        return self.chunks[chunk_id]

    def lookup_chunk_by_doc_and_index(self, doc_id: str, idx: int) -> Optional[Chunk]:
        cid = f"{doc_id}::{idx}"
        return self.chunks.get(cid)

    def all_chunks_for_doc(self, doc_id: str) -> List[Chunk]:
        lst = [c for c in self.chunks.values() if c.doc_id == doc_id]
        return sorted(lst, key=lambda x: x.chunk_index)


# ----------------------- # Helper: format citation for prompts # -----------------------
def format_chunk_citation(chunk: Chunk) -> Dict[str, Any]:
    """
    Return a normalized citation dict for discover/drafting prompts, e.g.:
    {
        "doc_id": "...",
        "title": "...",
        "author": "...",
        "date": "...",
        "page_id": 2,
        "chunk_index": 5,
        "source_path": "/path/to/file.pdf"
    }
    """
    doc_meta = (chunk.metadata or {}).get("doc_meta", {}) or {}
    return {
        "doc_id": chunk.doc_id,
        "title": doc_meta.get("title"),
        "author": doc_meta.get("author"),
        "date": doc_meta.get("date"),
        "jurisdiction": doc_meta.get("jurisdiction"),
        "page_id": chunk.page_id,
        "chunk_index": chunk.chunk_index,
        "source_path": chunk.source_path,
    }
