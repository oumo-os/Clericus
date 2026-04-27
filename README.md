# Clericus — Smart Drafting Assistant for Complex Documents

Clericus transforms a folder of source documents (PDFs, DOCXs, TXTs) and a
plain-English instruction into a structured, evidence-backed document — a
whitepaper, policy brief, legal memo, market analysis, or any research-heavy
report.

It works the way a careful human research team does: it reads your sources,
plans the document structure, asks itself questions, retrieves relevant
passages, drafts section by section with full cross-referencing, and reviews
for consistency before export.

---

## How it works

```
Sources (PDFs, DOCXs, TXTs)
        │
        ▼
  [1] Index — chunks & embeds into FAISS (no cloud, local SentenceTransformer)
        │
        ▼
  [2] Structure — LLM proposes document skeleton from your instruction
        │           (or reads headings from an existing template file)
        │
        ▼
  [3] For each section node (recursive):
        │
        ├─ Plan & Discover
        │    • LLM generates 3-5 guiding questions for this section
        │    • Questions are registered in the Question Tracker
        │    • KB is queried for each question (project KB + internal KB)
        │    • Reflective pass synthesises insights, spawns follow-up questions
        │    • Established Facts Base queried for continuity
        │
        ├─ Subdivision decision
        │    • If word budget > SUBDIVISION_WORD_THRESHOLD and level > 0:
        │        recurse into child sections (from structure or LLM-suggested)
        │    • Else: draft as a leaf
        │
        ├─ Draft (leaf only)
        │    • LLM writes opening / body / closing against all context
        │    • Post-draft enrichment: generates follow-up questions,
        │        queries KBs again, re-drafts if new material found
        │
        ├─ Review (leaf only)
        │    • Checks cross-refs via Internal KB
        │    • Checks EFB for continuity issues
        │    • LLM suggests final refinements
        │
        └─ Persist — section JSON cached; crash-resume safe
                │
                ▼
  [4] Traverse & polish — dedup references, normalise style, LLM consistency pass
        │
        ▼
  [5] Export — DOCX / PDF / Markdown / HTML / TXT
```

---

## Installation

```bash
git clone https://github.com/your-org/clericus.git
cd clericus
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Requirements

| Package | Purpose |
|---|---|
| `sentence-transformers` | Local embeddings (no API key needed) |
| `faiss-cpu` | Vector similarity search |
| `anthropic` | Anthropic Claude backend |
| `openai` | OpenAI backend |
| `google-genai` | Gemini backend |
| `PyPDF2` | PDF text extraction |
| `python-docx` | DOCX read & write |
| `weasyprint` | HTML → PDF export |
| `jinja2` | HTML templating |
| `backoff` | Retry logic for LLM calls |
| `pyyaml` | Template YAML serialisation |

---

## Quick start

```bash
# Minimal — structure is generated from the instruction
python cli.py \
  --source ./my_sources \
  --instruction "Whitepaper on renewable energy incentives in Sub-Saharan Africa"

# With a template file to mirror structure/style
python cli.py \
  --source ./my_sources \
  --templatefile ./my_template.md \
  --instruction "Quarterly market analysis" \
  --format md

# Anthropic Claude backend, markdown output, fresh state
python cli.py \
  --source ./sources \
  --instruction "Policy brief on data privacy regulation" \
  --llm-backend anthropic \
  --format md \
  --reset-state

# Resume a run that crashed mid-way (cached sections are reused)
python cli.py \
  --source ./sources \
  --instruction "..."
```

### All CLI flags

| Flag | Default | Description |
|---|---|---|
| `--source` | `./sources` | Directory of source documents |
| `--instruction` | *(generic)* | Plain-English document goal |
| `--templatefile` | *(none)* | Existing file to infer structure from |
| `--output` | `output/final_document.docx` | Output file path |
| `--format` | `docx` | `docx` / `pdf` / `md` / `html` / `txt` |
| `--max-depth` | `3` | Maximum recursion depth |
| `--llm-backend` | *(env var)* | `openai` / `anthropic` / `gemini` / `ollama` / `local` |
| `--offline` | `false` | Disable web search and curated KB |
| `--use-curated` | `false` | Enable curated knowledge base |
| `--curated-domains` | *(all)* | Comma-separated domains, e.g. `law,finance` |
| `--reset-state` | `false` | Clear cached drafts and facts before running |
| `--output-dir` | `OUTPUT` | Working directory for section state files |

---

## LLM backend setup

Set `LLM_BACKEND` as an env var or pass `--llm-backend`. The flag always wins.

```bash
# Anthropic (recommended — handles long structured prompts well)
export ANTHROPIC_API_KEY="sk-ant-..."
export LLM_BACKEND="anthropic"

# OpenAI
export OPENAI_API_KEY="sk-..."
export LLM_BACKEND="openai"

# Google Gemini
export GEMINI_API_KEY="..."
export LLM_BACKEND="gemini"

# Ollama (local, no key needed)
export OLLAMA_API_URL="http://localhost:11434"
export OLLAMA_MODEL="llama3.2"
export LLM_BACKEND="ollama"

# llama-cpp-python (local binary)
export LOCAL_LLM_PATH="./models/my-model.gguf"
export LLM_BACKEND="local"
```

---

## Project structure

```
clericus/
├── cli.py                     ← single entry point
│
├── sourceprep/
│   ├── ingest.py              PDF / DOCX / TXT text extraction
│   ├── metadata.py            Author, title, year extraction
│   ├── chunker.py             Overlapping-chunk wrapper
│   ├── chunker_embed.py       Full LocalChunkIndex (SentenceTransformer + FAISS)
│   └── index.py               Build/load project source vector index
│
├── template/
│   ├── analyze_template.py    generate_structure_from_template()
│   │                          generate_structure_from_instruction()  ← NEW
│   └── structure_generator.py TemplateNode data model & TemplateHandler
│
├── contemplation/
│   └── plan_and_discover.py   Initial & reflective contemplation, iterative discovery loop
│
├── discovery/
│   └── discovery.py           discover_knowledge() — project KB + internal KB + web + curated
│
├── retrieval/
│   └── retriever.py           query_knowledge_base(), web_search(), NeighborRetriever
│
├── drafting/
│   ├── recursive_drafter.py   recursive_draft_section() — the core pipeline loop
│   ├── draft_section.py       Leaf-node drafter (draft → enrich → return)
│   └── review_section.py      Per-leaf review against EFB + internal KB
│
├── review/
│   └── review_pipeline.py     traverse_and_review() — final polish pass on full tree
│
├── export/
│   ├── exporters.py           export_document() — txt / md / html / pdf / docx
│   └── templates/             Jinja2 HTML template (optional; inline fallback exists)
│
├── llm_client/
│   └── call_llm.py            Unified dispatch: openai / anthropic / gemini / ollama / local
│
├── internal_kb.py             InternalKB — semantic index of drafted sections
├── established_facts.py       EstablishedFactsBase — facts extracted from drafted text
├── question_tracker.py        QuestionTracker — per-section question lifecycle
├── curated_kb.py              CuratedKB — optional domain-specific vector stores
├── docling_adapter.py         Optional Docling integration for advanced parsing
│
└── utils/
    ├── config.py              All tuneable constants (see below)
    ├── vector_store.py        SimpleVectorStore — FAISS wrapper, no LangChain
    ├── embeddings.py          Shim (model name resolution)
    ├── references.py          Citation formatting, dedupe
    ├── text_tools.py          clean_text, normalize_whitespace, count_tokens
    ├── common.py              ensure_dir
    └── logging.py             log_info, log_error
```

---

## Configuration (`utils/config.py`)

All runtime behaviour is controlled from one place.

| Constant | Default | Effect |
|---|---|---|
| `LLM_BACKEND` | `"ollama"` | Default backend when env var not set |
| `OLLAMA_MODEL` | `"llama3.2"` | Model name for Ollama |
| `LOCAL_EMBEDDING_MODEL` | `"all-MiniLM-L6-v2"` | sentence-transformers model for all vector stores |
| `DEFAULT_DOCUMENT_BUDGET` | `3000` | Total word budget for the document |
| `DEFAULT_SECTION_BUDGET` | `600` | Fallback per-section budget |
| `SUBDIVISION_WORD_THRESHOLD` | `900` | A section subdivides only if its budget exceeds this |
| `MAX_QUESTION_ITER` | `3` | Discovery loop iterations per section |
| `INTERNAL_KB_TOP_K` | `3` | Cross-references pulled per query |
| `EFB_TOP_K` | `5` | Facts retrieved per continuity check |
| `USE_CURATED_KB` | `False` | Enable/disable curated domain KBs |
| `EFB_KB_DIR` | `".clericus/efb_index"` | Established Facts Base persistence |
| `INDEX_DIR` | `"vector_index"` | Project source index |

Tune `SUBDIVISION_WORD_THRESHOLD` and `DEFAULT_SECTION_BUDGET` together.
A section stays as a leaf when `word_budget ≤ SUBDIVISION_WORD_THRESHOLD`.

---

## State and persistence

Clericus writes intermediate state so a run can survive crashes or be
continued:

```
OUTPUT/
└── clericus_state/
    ├── 1.json          root section
    ├── 1_1.json        section 1.1
    ├── 1_2.json        section 1.2
    └── ...

.clericus/
    ├── questions.json  question tracker
    └── efb_index/      established facts vector store

vector_index/
    ├── sources/        project source index (FAISS)
    └── internal_kb/    in-document cross-reference index
```

`--reset-state` wipes the question tracker and EFB. The source index and
section state cache are cleared separately by deleting `vector_index/` or
`OUTPUT/clericus_state/`.

---

## Curated knowledge bases

A curated KB is a pre-built vector store for a domain (e.g. case law, market
data). Each domain lives in its own sub-directory:

```
curated_kb/
├── law/
│   ├── index.faiss
│   └── store.pkl
└── finance/
    ├── index.faiss
    └── store.pkl
```

Build a domain index with `SimpleVectorStore`:

```python
from utils.vector_store import SimpleVectorStore

texts     = [chunk.text for chunk in my_chunks]
metadatas = [chunk.metadata for chunk in my_chunks]
store     = SimpleVectorStore.from_texts(texts, metadatas=metadatas)
store.save_local("curated_kb/law")
```

Then enable it:

```bash
python cli.py --source ./sources --instruction "..." \
  --use-curated --curated-domains law
```

---

## Document tree schema

Every node in the document tree (whether parent or leaf) follows this shape:

```json
{
  "id":                 "1.2",
  "title":              "Market Landscape",
  "section_path":       "1.2",
  "openning":           "This section surveys...",
  "body_text":          "Full prose body (leaf nodes only).",
  "closing":            "In summary...",
  "references":         [{"author": "...", "year": "...", "title": "..."}],
  "children":           [...],
  "discovery_hits":     [...],
  "efb_crossrefs":      [...],
  "unresolved_questions": [...]
}
```

Parent nodes have `body_text: null` and a non-empty `children` list.
Leaf nodes have `children: []` and body text in `body_text`.

The tree is also saved as `output/document.json` after drafting completes,
before export.

---

## Extending Clericus

### Add a new LLM backend

Open `llm_client/call_llm.py`, add an `_call_mybackend()` function following
the same signature as `_call_openai()`, then add `"mybackend": _call_mybackend`
to the `dispatch` dict in `call_llm()`.

### Add a new export format

Open `export/exporters.py`, add `export_to_myformat()`, and add an entry to
the `dispatch` dict in `export_document()`.

### Plug in a custom fact extractor

`extract_facts_from_section()` in `drafting/recursive_drafter.py` calls the
LLM with a generic prompt. Replace the function body with domain-specific
extraction logic (e.g., regex for legal citations, NER for named entities).

---

## Known limitations

- **No web search by default.** Web fallback requires `BING_API_KEY`. Without
  it, all retrieval is from the local source index.
- **No Docling auto-activation.** `docling_adapter.py` exists but is not wired
  into the ingestion pipeline by default. See the adapter's docstring for usage.
- **HTML/PDF export needs a template.** If `export/templates/document.html`
  does not exist, a minimal inline HTML is generated instead. PDF quality
  depends on WeasyPrint's CSS support.
- **Curated KB must be pre-built.** Clericus does not populate curated domains
  automatically; see the section above.

---

## Roadmap

- Interactive web UI with per-section controls and live question/fact inspector
- Multi-agent QA layer: dedicated fact-checker and style editor agents
- Domain plugins for legal, academic, and technical report formats
- Dynamic context trimming for very large source corpora
- Docker image with bundled sentence-transformers model

---

*Clericus — recursive, reflective, reference-rich.*
