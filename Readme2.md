# Clericus: A Recursive, Reflective RAG-Powered Document Drafter

**Clericus** is a modular, extensible system that transforms diverse source materials into richly structured, coherent, evidence-driven documents. It combines Retrieval-Augmented Generation (RAG) with multi-stage contemplation, iterative question tracking, an internal knowledge base, an established-facts base, and optional curated knowledge for authoritative enrichment. Designed for forward-thinking users, Clericus mimics a collaborative authorial process—thinking deeply, discovering relevant information, drafting with context awareness, and refining for consistency and continuity.

---

## Key Concepts & Innovations

- **Waterfall Flow with Evolving Memory**  
  Clericus maintains document- and section-level summaries, insights, and a semantic internal KB of drafted content, ensuring each part builds on previous ones.

- **Multi-Stage Contemplation & Iterative Discovery**  
  1. **Initial Contemplation**: Generate guiding questions, knowledge goals, and an outline for sections.  
  2. **Iterative Discovery**: Query primary KBs (project sources, internal KB, optional live/web) and record answers; reflect to synthesize insights and spawn new questions; optionally enrich via curated KB.  
  3. **Reflective Contemplation**: Integrate retrieved facts, identify gaps, refine structure repeatedly until questions are addressed or iteration limit reached.

- **Internal Knowledge Base (IKB)**  
  As sections are drafted, their content and metadata are embedded into an evolving internal KB (vectorstore). This enables semantic cross-referencing: prompts can include “Previously in Section X.Y…”, reducing redundancy and enhancing cohesion.

- **Established Facts Base (EFB)**  
  Critical facts (e.g., narrative continuity, product specifications, character details) are extracted from drafted text via specialized LLM prompts and tracked separately. EFB supports semantic querying of facts to maintain consistency across distant sections.

- **Staged Curated KB Enrichment**  
  Optionally integrate authoritative, pre-curated knowledge bases (e.g., legal corpora, encyclopedic repositories). Clericus can first draft from primary sources and internal context, then enrich or fact-check sections with curated KB hits via targeted “enrichment prompts.”

- **Recursive Drafting & Subdivision**  
  Sections exceeding an LLM-friendly word threshold auto-split into subsections based on insights. Each node undergoes planning, discovery, and drafting, recursing until leaf sections are generated.

- **Persistent Question Tracking**  
  All document- and section-level questions are logged, their answers recorded, and open questions highlighted. Unanswered critical questions trigger additional retrieval or user alerts to ensure completeness.

- **Review & Polishing**  
  After drafting, Clericus runs consistency and style checks (via LLM), deduplicates references, and performs continuity validation (cross-ref and EFB-based checks).

- **Multi-Format Export**  
  Outputs to Markdown, HTML, PDF, DOCX, or plain text. Optional Docling integration can further post-process or style outputs.

- **Optional Docling Integration**  
  For advanced parsing of varied document formats (PDF, DOCX, HTML, images) and post-processing, Clericus can invoke Docling (via Python API or CLI) to normalize inputs to Markdown/JSON and to enhance exported documents.

---

## Project Structure

```
clericus/
├── cli/                   # Command-line interface entrypoint
│   └── cli.py
├── sourceprep/            # Source ingestion & vector index building
│   ├── ingest.py          # Raw parsing fallback, but often replaced by Docling adapter
│   ├── metadata.py        # Extract basic metadata
│   ├── chunker.py         # Split text into overlapping chunks
│   └── index.py           # Build/load FAISS index from chunks
├── docling_adapter.py     # Optional: integrate Docling parsing and postprocessing
├── template/              # Template-based structure inference
│   └── analyze_template.py
├── contemplation/         # Section-level planning & iterative discovery
│   └── plan_and_discover.py
├── discovery/             # Knowledge retrieval combining external, internal, curated, web
│   └── discovery.py
├── retrieval/             # Retrieval helpers (vector & web search)
│   └── retriever.py
├── drafting/              # Core recursive drafting logic
│   ├── draft_section.py   # Leaf section drafting with enriched context
│   └── recursive_drafter.py
├── internal_kb.py         # Evolving internal knowledge base for cross-references
├── established_facts.py   # Tracks critical facts for continuity and checks
├── question_tracker.py    # Persistent tracking of questions and answers
├── curated_kb.py          # Optional: manage and query curated knowledge domains
├── review/                # Review pipeline: style, consistency, continuity checks
│   └── review_pipeline.py
├── export/                # Multi-format export
│   ├── exporters.py       # Export to DOCX, PDF, HTML, MD, TXT
│   └── templates/         # HTML/CSS for export styling
├── llm_client/            # LLM API wrapper (OpenAI, local, Ollama)
│   └── call_llm.py
├── utils/                 # Helper modules
│   ├── config.py          # Global settings (thresholds, paths, toggles)
│   ├── logging.py         # Central logging functions
│   ├── references.py      # Citation formatting, deduplication
│   └── text_tools.py      # Cleaning, token counting, normalization
├── requirements.txt       # Python dependencies
└── README.md              # This overview
```

---

## Installation & Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/your-org/clericus.git
   cd clericus
   ```
2. **Set up a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate      # Windows: venv\\Scripts\\activate
   pip install -r requirements.txt
   ```
3. **Configure environment variables**
   ```bash
   export OPENAI_API_KEY="your-openai-key"
   export BING_API_KEY="your-bing-key"
   export LLM_BACKEND="openai"    # or "ollama" or "local"
   export OLLAMA_API_URL="http://localhost:11434"  # if using Ollama
   export OLLAMA_MODEL="llama2"
   ```
4. **(Optional) Docling**  
   - Install Docling CLI or Python package as per Docling docs.  
   - Ensure `docling` command is in PATH or Python API is importable.

---

## Usage Examples

### Basic CLI Run
```bash
python cli/cli.py \
  --source ./source_docs \
  --output ./output/final_report.docx \
  --format docx \
  --max-depth 3 \
  --instruction "Market analysis for this quarter with projections"
```

### Using Docling for Parsing
```bash
# Prior to running Clericus, convert diverse sources to Markdown via Docling
python -c "from docling_adapter import ingest_with_docling; ingest_with_docling('raw_sources', working_dir='.')"
# Then feed parsed_dir to Clericus
python cli/cli.py --source ./docling_parsed --output ./out.docx --instruction "..."
```

### Enabling Curated KB Enrichment
```bash
python cli/cli.py --source ./src --output out.pdf --format pdf \
  --use-curated --curated-domains "law,finance" --reset-state
```

### Iterative Workflows (GUI or API)
- In a GUI environment, sessions can persist `question_tracker` and `established_facts` between edits, allowing users to refine drafts over multiple runs.
- API endpoints can trigger runs, reset state, or fetch question logs and facts for interactive dashboards.

---

## Pipeline Overview

1. **Source Preparation**  
   - (Optional) **Docling** parses diverse formats into Markdown/JSON.  
   - **Ingest** clean text, extract metadata, chunk, and index into FAISS (project KB).

2. **Template & Instruction**  
   - Load a template file to infer skeleton, or use high-level instruction to name the document.

3. **Document-Level Contemplation & Discovery**  
   - Generate document-level questions; track them.  
   - Iteratively retrieve from project KB, internal KB (initially empty), web (optional), and curated KB (optional) until insights mature and questions answered.  
   - Derive a weighted hierarchical skeleton based on insights.

4. **Recursive Section Drafting**  
   For each section node:  
   a. **Initial Contemplation**: register section-level questions, goals, outline.  
   b. **Iterative Discovery**: retrieve answers from project KB, internal KB, web/live, and optionally curated KB; reflect to refine questions and structure.  
   c. **Established Facts Query**: fetch facts relevant to continuity.  
   d. **Draft Section**: prompt LLM with doc_summary, parent_summary, internal cross-ref snippets, established facts, and factual materials.  
   e. **Subdivision**: if budget exceeds threshold, split into subsections and recurse.  
   f. **Review & Continuity Check**: check EFB contradictions, unanswered questions; revise if needed.  
   g. **Register**: add drafted content to internal KB and extract new facts into EFB.

5. **Final Review**  
   - Traverse entire document tree: dedupe references, normalize style, harmonize tone, ensure all tracked questions answered or flagged.

6. **Export**  
   - Render to desired format (MD, HTML, PDF, DOCX, TXT).  
   - (Optional) Post-process via Docling for advanced styling, layout fixes, enriched metadata.

---

## Configuration & Customization

- **`utils/config.py`** holds thresholds (e.g., `LLM_OUTPUT_THRESHOLD`), KB settings, and toggles for internal KB, curated KB, EFB, question iterations.
- **LLM Backend**: Switch between OpenAI, local LLMs, or Ollama by setting `LLM_BACKEND` and relevant env vars.
- **Curated KB Management**: Populate `curated_kb/` directories via separate build scripts; configure domains in CLI or config.
- **Docling Adapter**: Enable or disable via CLI or environment; fallback to basic parsing if unavailable.
- **Persistence**: By default, question logs and EFB metadata are stored under `.clericus/`; can be reset or persisted for iterative editing.

---

## Future Directions

- **Interactive GUI**: Web-based dashboard for section-level control, real-time logs, question/fact inspection, manual overrides.  
- **Multi-Agent QA**: Dedicated agents for fact-checking, style adaptation, conflict resolution among unanswered questions.  
- **Domain Plugins**: Tailored templates, question heuristics, or fact-extraction routines for specific domains (legal, academic, narrative writing).  
- **Advanced Token Management**: Dynamic context trimming, prioritized snippet selection, streaming LLM responses for large sections.  
- **Collaboration & Versioning**: Shared projects, role-based access, version history of drafts, issue tracking for open questions.

---

*Clericus* empowers deep, reflective, and coherent document creation—blurring the line between AI-driven generation and human-like editorial workflows.