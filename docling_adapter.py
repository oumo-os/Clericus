# docling_adapter.py
"""
Adapter module to integrate Docling parsing and post-processing into Clericus.
This module assumes the Docling CLI or Python API is installed and available.
It provides functions to parse diverse document formats into a standardized intermediate
representation (e.g., Markdown or JSON) that Clericus can ingest uniformly.
It also provides post-processing hooks using Docling on Clericus-generated outputs.
"""
import os
import subprocess
import json
from pathlib import Path
from utils.logging import log_info, log_error

# Configuration: path to Docling CLI executable or Python import
DOCLING_CLI_CMD = os.getenv("DOCLING_CLI_CMD", "docling")  # assume 'docling' is in PATH
# If Docling Python API exists, we can try import; otherwise use CLI
USE_DOCLING_PYTHON_API = False
try:
    # Try import a hypothetical Docling Python package
    import docling  # replace with actual package name if available
    USE_DOCLING_PYTHON_API = True
    log_info("Docling Python API detected; will use direct import.")
except ImportError:
    log_info("Docling Python API not found; will use CLI via subprocess.")


def parse_to_markdown(input_path: str, output_path: str) -> bool:
    """
    Parse the given document using Docling and output Markdown text.
    Returns True on success, False otherwise.
    """
    input_path = str(input_path)
    output_path = str(output_path)
    # Try Python API first
    try:
        from docling.document_converter import DocumentConverter
        converter = DocumentConverter()
        # converter.convert accepts URL or file path
        result = converter.convert(input_path)
        # Export to markdown
        markdown_text = result.document.export_to_markdown()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown_text)
        log_info(f"Docling Python API parse_to_markdown success for {input_path}")
        return True
    except ImportError:
        log_info("Docling Python API not available; falling back to CLI.")
    except Exception as e:
        log_error(f"Docling Python API parse_to_markdown failed for {input_path}", e)
        # fallback to CLI

    # Fallback to CLI
    cmd = [DOCLING_CLI_CMD, "parse", "--input", input_path, "--format", "markdown", "--output", output_path]
    try:
        log_info(f"Running Docling CLI: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        log_info(f"Docling CLI parse_to_markdown success for {input_path}")
        return True
    except subprocess.CalledProcessError as e:
        log_error(f"Docling CLI parse_to_markdown failed for {input_path}: {e.stderr}", e)
        return False


def parse_to_json(input_path: str, output_path: str) -> bool:
    """
    Parse the given document using Docling and output a JSON representation.
    Returns True on success, False otherwise.
    """
    input_path = str(input_path)
    output_path = str(output_path)
    try:
        from docling.document_converter import DocumentConverter
        converter = DocumentConverter()
        result = converter.convert(input_path)
        # Export to dict/JSON
        # Assume export_to_dict or export_to_json available
        if hasattr(result.document, 'export_to_dict'):
            json_obj = result.document.export_to_dict()
            json_text = json.dumps(json_obj, indent=2)
        elif hasattr(result.document, 'export_to_json'):
            json_text = result.document.export_to_json()
        else:
            # Fallback: attempt to serialize attributes
            json_obj = result.document.__dict__
            json_text = json.dumps(json_obj, default=str, indent=2)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(json_text)
        log_info(f"Docling Python API parse_to_json success for {input_path}")
        return True
    except ImportError:
        log_info("Docling Python API not available; falling back to CLI.")
    except Exception as e:
        log_error(f"Docling Python API parse_to_json failed for {input_path}", e)
        # fallback to CLI
    cmd = [DOCLING_CLI_CMD, "parse", "--input", input_path, "--format", "json", "--output", output_path]
    try:
        log_info(f"Running Docling CLI: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        log_info(f"Docling CLI parse_to_json success for {input_path}")
        return True
    except subprocess.CalledProcessError as e:
        log_error(f"Docling CLI parse_to_json failed for {input_path}: {e.stderr}", e)
        return False

def ingest_with_docling(source_dir: str, working_dir: str) -> str:
    """
    Given a directory of source files, run Docling parsing on each and store the outputs
    in a standardized subdirectory (e.g., 'docling_parsed'), returning the path to that dir.
    working_dir: base working directory for storing parsed outputs

    Returns the path to the directory containing parsed markdown files (to feed Clericus's sourceprep).
    """
    source_path = Path(source_dir)
    parsed_dir = Path(working_dir) / "docling_parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)

    for filepath in source_path.rglob("*"):
        if filepath.is_file():
            rel = filepath.relative_to(source_path)
            out_subdir = parsed_dir / rel.parent
            out_subdir.mkdir(parents=True, exist_ok=True)
            # Decide output file extension: Markdown (.md)
            out_file = out_subdir / (filepath.stem + ".md")
            success = parse_to_markdown(str(filepath), str(out_file))
            if not success:
                log_info(f"Falling back to raw text extraction for {filepath}")
                # Optionally fallback: extract text via existing ingest.extract_text_from_* functions
                # from sourceprep.ingest import extract_text_from_pdf, extract_text_from_docx, clean_text
                try:
                    from sourceprep.ingest import extract_text_from_pdf, extract_text_from_docx
                    from utils.text_tools import clean_text
                    ext = filepath.suffix.lower()
                    if ext == ".pdf":
                        text = extract_text_from_pdf(filepath)
                    elif ext == ".docx":
                        text = extract_text_from_docx(filepath)
                    else:
                        text = filepath.read_text(encoding='utf-8', errors='ignore')
                    cleaned = clean_text(text)
                    out_file.write_text(cleaned, encoding='utf-8')
                except Exception as e:
                    log_error(f"Fallback extraction failed for {filepath}", e)
    return str(parsed_dir)


def postprocess_with_docling(input_path: str, output_path: str, format: str = "html") -> bool:
    """
    Post-process a Clericus-generated document (e.g., Markdown or JSON) through Docling to produce
    enhanced output (e.g., styled HTML, enriched JSON). Returns True on success.
    format: desired Docling output format ("html", "json", etc.)
    """
    input_path = str(input_path)
    output_path = str(output_path)
    if USE_DOCLING_PYTHON_API:
        try:
            # Hypothetical API usage:
            # doc = docling.load_document(input_path)
            # processed = doc.postprocess()
            # if format == "html": html = processed.to_html(); write to output_path
            raise NotImplementedError("Docling Python API postprocess integration needs actual API calls.")
        except Exception as e:
            log_error(f"Docling Python API postprocess failed for {input_path}", e)
            return False
    else:
        # Use CLI: docling postprocess --input <input_path> --format <format> --output <output_path>
        cmd = [DOCLING_CLI_CMD, "postprocess", "--input", input_path, "--format", format, "--output", output_path]
        try:
            log_info(f"Running Docling CLI postprocess: {' '.join(cmd)}")
            result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            log_info(f"Docling postprocess success for {input_path}")
            return True
        except subprocess.CalledProcessError as e:
            log_error(f"Docling CLI postprocess failed for {input_path}: {e.stderr}", e)
            return False
