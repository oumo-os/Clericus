**Clericus** transforms raw source materials (PDFs, DOCXs, TXTs) into structured, high-quality documents through a modular, evidence-driven pipeline. It combines Retrieval-Augmented Generation (RAG) with multi-stage contemplation and recursive drafting to ensure coherent, context-aware, and fully referenced outputs.

---

## Key Features

- **RAG-Based Source Preparation**  
  • Ingests multiple file formats; extracts metadata (title, author, year).  
  • Splits text into overlapping chunks; indexes in FAISS for fast semantic retrieval.

- **Template & Instruction Integration**  
  • Infers desired structure from an existing template document.  
  • Accepts high-level instructions or topics to guide tone and focus.

- **Multi-Stage Contemplation & Discovery**  
  1. **Initial Contemplation**: Generates guiding questions, knowledge goals, and a micro-outline.  
  2. **First-Pass Discovery**: Retrieves targeted chunks from the KB (and optional web sources).  
  3. **Reflective Contemplation**: Synthesizes insights, identifies gaps, refines structure.  
  4. **Second-Pass Discovery** (optional): Fills remaining gaps with focused queries.

- **Recursive Drafting**  
  • Dynamically subdivides large sections based on word-budget thresholds.  
  • Each section node follows: contemplate → discover → draft or subdivide → recurse.

- **Review & Polishing**  
  • Deduplicates and formats citations.  
  • Normalizes style and tone via lightweight LLM-based consistency checks.

- **Multi-Format Export**  
  • Outputs to DOCX, PDF, Markdown, HTML, or plain text.  
  • Applies templates, styling, and bibliography formatting.

- **Extensible Architecture**  
  • Modular design: swap LLM backends, vector stores, or domain-specific plugins.  
  • Future GUI, multi-agent QA, and domain templates planned.

## Revised Pipeline Outline 13/06/25

In light of the above, the high-level pipeline becomes:

1. **Collect sources** (project KB)  
2. **Template / Instruction**  
3. **Document-level planning**  
   - initial document questions → track in question_tracker
   - iterative discovery → answers → reflection → new questions → repeat
4. **Generate skeleton structure** based on document-level insights
5. **For each top-level section node** (recursive):
   1. **Section Contemplation & Question Tracking**  
      - initial questions registered  
      - iterative discovery (primary → internal → optionally curated) with question tracking and EFB checks  
   2. **Fact Extraction into EFB** from previous sections/drifts  
   3. **Draft Section Opening** using doc_summary, parent_summary, EFB hits, knowledge_chunks  
   4. **Subdivision Decision** (word budget threshold)  
      - If subdividing, recurse into subsections, maintaining question tracking context  
      - Else: **Draft subsections (if any) & Section Closing**  
   5. **Review & Continuity Check**  
      - Check cross-references via internal KB  
      - Check EFB for continuity issues (e.g., missing or contradictory facts)  
      - If issues, trigger refinement: e.g., generate “fix-up” prompts to adjust content  
   6. **Finalize Section**: add to internal KB, extract facts to EFB  
   7. **Compile references** from knowledge_chunks (external/internal/curated)  
6. **Post-structure examination**  
   - Check if any document-level or section-level questions remain unanswered → alert or auto-insert new sections or revisions  
7. **Export**

---

## Project Structure

```
clericus/
├── cli/                   # Command-line interface entrypoint
│   └── cli.py
├── sourceprep/            # Source ingestion & vector index building
│   ├── ingest.py          # Load files, clean text, extract metadata, chunking
│   ├── metadata.py        # Extract title, author, year, citation strings
│   ├── chunker.py         # Overlapping text chunk logic
│   └── index.py           # Build/load FAISS index from chunks
├── template/              # Template-based structure inference
│   └── analyze_template.py
├── contemplation/         # Section-level planning: questions, goals, outline
│   └── plan_and_discover.py
├── discovery/             # Targeted KB & optional web retrieval
│   └── discovery.py
├── retrieval/             # Retrieval helper functions (vector & web search)
│   └── retriever.py
├── drafting/              # Core recursive drafting
│   ├── draft_section.py   # Leaf node drafting with context and RAG
│   └── recursive_drafter.py
├── review/                # Review pipeline: style, facts, consistency
│   └── review_pipeline.py
├── export/                # Multi-format export and post-processing
│   ├── exporters.py
│   └── templates/         # HTML/CSS templates for HTML/PDF
├── llm_client/            # LLM API wrapper (OpenAI/local)
│   └── call_llm.py
├── utils/                 # Helper modules (config, text, references)
│   ├── config.py
│   ├── references.py
│   └── text_tools.py
├── requirements.txt       # Python dependencies
└── README.md              # This overview
```

---

## Installation

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
   export LLM_BACKEND="openai"   # or "local"
   ```

---

## Usage

### Command-Line Interface

```bash
python cli/cli.py \\
  --source ./path/to/source_docs \\
  --output ./output/final_report.docx \\
  --format docx \\
  --max-depth 3 \\
  --templatefile ./path/to/template_or_example.pdf \\
  --instruction "Market analysis for this quarter with projections"\\
  --use-curated \\
  --curated-domains law,finance \\
  --reset-state
```

### Configuration

- Adjust thresholds and defaults in `utils/config.py` (e.g., `LLM_OUTPUT_THRESHOLD`).  
- Customize templates under `export/templates` for HTML/PDF styling.

---

## Future Directions

- **Interactive GUI**: Live drafting, preview, and parameter tuning.  
- **Domain-Specific Templates**: Plugins for legal, academic, or technical reports.  
- **Multi-Agent Enhancements**: Fact-checkers, style editors, and summarizers.  
- **Testing & CI**: Full test suite and Dockerized deployment.

---

*Clericus*: recursive, reflective, and reference-rich document generation.