"""
gui/api/server.py — Clericus FastAPI backend (project-aware)

All pipeline paths come from the active project, not hardcoded dirs.

Endpoints:
  GET/POST /api/projects            list / create
  POST     /api/projects/{id}/open  set active
  DELETE   /api/projects/{id}       delete permanently
  PATCH    /api/projects/{id}       update name/description/instruction
  GET      /api/projects/active     current project + document

  POST /api/run/start   GET /api/run/status   GET /api/run/log
  POST /api/run/cancel  POST /api/state/reset

  POST /api/sources/upload   GET /api/sources   DELETE /api/sources/{name}

  GET /api/document          GET /api/export/{fmt}

  GET/POST /api/settings
  GET      /api/model/validate
  GET      /api/update-check

  WebSocket /ws/log
"""

import asyncio, json, logging, os, shutil, sys, threading, time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Clericus", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

from utils.project import project_manager, validate_model_path

def _active():
    p = project_manager.active
    if p is None:
        raise HTTPException(400, "No project open. Create or open a project first.")
    return p

# ---------------------------------------------------------------------------
# Log buffer + WebSocket broadcast
# ---------------------------------------------------------------------------

_log_buffer: deque = deque(maxlen=600)
_ws_clients: List[WebSocket] = []

class _BufHandler(logging.Handler):
    def emit(self, record):
        line = self.format(record)
        _log_buffer.append(line)
        for ws in list(_ws_clients):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        ws.send_text(json.dumps({"type": "log", "line": line})), loop)
            except Exception:
                pass

_h = _BufHandler()
_h.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S"))
for _n in ("clericus", "drafting", "contemplation", "sourceprep"):
    logging.getLogger(_n).addHandler(_h)

# ---------------------------------------------------------------------------
# Run state
# ---------------------------------------------------------------------------

_run_state: Dict[str, Any] = {
    "status": "idle", "project_id": None, "instruction": "",
    "started_at": None, "finished_at": None, "error": None,
    "sections_total": 0, "sections_done": 0, "current_section": "",
}
_cancel_flag = threading.Event()

class RunRequest(BaseModel):
    instruction: str = ""
    llm_backend: str = "ollama"
    max_depth: int = 3
    format: str = "md"
    reset_state: bool = False

def _do_reset(project):
    if project.efb_dir.exists():
        for f in project.efb_dir.glob("*"): f.unlink(missing_ok=True)
    if project.questions_path.exists(): project.questions_path.unlink()
    if project.state_dir.exists():
        shutil.rmtree(project.state_dir, ignore_errors=True)
        project.state_dir.mkdir(parents=True, exist_ok=True)

def _run_pipeline(req: RunRequest, project_id: str):
    log = logging.getLogger("clericus")
    try:
        project = project_manager.open(project_id)
    except Exception as e:
        _run_state.update({"status": "error", "error": str(e), "finished_at": time.time()})
        return

    _run_state.update({
        "status": "running", "project_id": project_id, "instruction": req.instruction,
        "started_at": time.time(), "finished_at": None, "error": None,
        "sections_done": 0, "current_section": "Initialising…",
    })
    _cancel_flag.clear()

    try:
        os.environ["LLM_BACKEND"] = req.llm_backend

        import utils.config as config
        from sourceprep.index import build_or_load_index
        from contemplation.document_planner import plan_document
        from template.analyze_template import (
            generate_structure_from_instruction, _headings_to_tree)
        from drafting.recursive_drafter import recursive_draft_section
        from review.review_pipeline import traverse_and_review
        from export.exporters import export_document
        from established_facts import EstablishedFactsBase
        from internal_kb import InternalKB
        from question_tracker import QuestionTracker
        import established_facts as _em, internal_kb as _im, question_tracker as _qm

        # Re-init singletons with project paths
        efb = EstablishedFactsBase(persist_dir=str(project.efb_dir))
        ikb = InternalKB(persist_dir=str(project.internal_kb_dir))
        qt  = QuestionTracker(persist_path=str(project.questions_path))
        _em.established_facts = efb
        _im.internal_kb = ikb
        _qm.question_tracker = qt

        if req.reset_state: _do_reset(project)

        _run_state["current_section"] = "Indexing sources…"
        kb_index = build_or_load_index(
            str(project.sources_dir),
            persist_dir=str(project.vector_index_dir / "sources"),
        )
        if _cancel_flag.is_set(): _run_state["status"] = "cancelled"; return

        _run_state["current_section"] = "Planning document…"
        instruction = req.instruction or project.instruction or "A report on the provided sources."
        doc_plan = plan_document(instruction, kb_index)
        enriched = doc_plan["doc_summary"]
        if _cancel_flag.is_set(): _run_state["status"] = "cancelled"; return

        _run_state["current_section"] = "Generating structure…"
        hint = doc_plan.get("recommended_sections")
        if hint:
            structure = _headings_to_tree([enriched] + hint, config.DEFAULT_DOCUMENT_BUDGET)
            structure["working_summary"] = enriched
        else:
            structure = generate_structure_from_instruction(enriched, config.DEFAULT_DOCUMENT_BUDGET)
        _run_state["sections_total"] = len(structure.get("children", [])) or 1
        if _cancel_flag.is_set(): _run_state["status"] = "cancelled"; return

        _run_state["current_section"] = "Drafting…"
        drafted = recursive_draft_section(
            node=structure, output_dir=str(project.state_dir),
            section_path="1", doc_summary=enriched, parent_summary="",
            kb_index=kb_index, level=req.max_depth, force_redraft=req.reset_state,
        )
        if _cancel_flag.is_set(): _run_state["status"] = "cancelled"; return

        _run_state["current_section"] = "Reviewing…"
        polished = traverse_and_review(drafted)

        project.output_dir.mkdir(parents=True, exist_ok=True)
        project.document_json_path.write_text(
            json.dumps(polished, indent=2, default=str), encoding="utf-8")

        _run_state["current_section"] = f"Exporting ({req.format})…"
        export_document(polished, req.format, str(project.output_dir / f"final_document.{req.format}"))

        project.update_run_status("complete")
        _run_state.update({"status": "complete", "finished_at": time.time(), "current_section": "Done"})
        log.info(f"Pipeline complete — '{project.name}'")

    except Exception as e:
        _run_state.update({"status": "error", "error": str(e), "finished_at": time.time()})
        log.error(f"Pipeline error: {e}", exc_info=True)
        try: project_manager.open(project_id).update_run_status("error")
        except Exception: pass

# ---------------------------------------------------------------------------
# Project endpoints
# ---------------------------------------------------------------------------

class NewProjectRequest(BaseModel):
    name: str
    description: str = ""
    instruction: str = ""

@app.get("/api/projects")
async def list_projects():
    return {"projects": project_manager.list_projects()}

@app.post("/api/projects")
async def create_project(req: NewProjectRequest):
    if not req.name.strip():
        raise HTTPException(400, "Project name cannot be empty.")
    p = project_manager.create(req.name.strip(), req.description, req.instruction)
    return p.to_dict()

@app.get("/api/projects/active")
async def active_project():
    p = project_manager.active
    if p is None: return {"active": None}
    d = p.to_dict()
    if p.document_json_path.exists():
        try: d["document"] = json.loads(p.document_json_path.read_text())
        except Exception: pass
    return {"active": d}

@app.post("/api/projects/{project_id}/open")
async def open_project(project_id: str):
    try:
        p = project_manager.open(project_id)
        d = p.to_dict()
        if p.document_json_path.exists():
            try: d["document"] = json.loads(p.document_json_path.read_text())
            except Exception: pass
        return d
    except FileNotFoundError:
        raise HTTPException(404, f"Project not found: {project_id}")

@app.patch("/api/projects/{project_id}")
async def update_project(project_id: str, body: dict):
    try: p = project_manager.open(project_id)
    except FileNotFoundError: raise HTTPException(404, f"Project not found: {project_id}")
    for k in ("name", "description", "instruction"):
        if k in body: setattr(p, k, body[k])
    p.save()
    if project_manager.active and project_manager.active.id == project_id:
        project_manager.active = p
    return p.to_dict()

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    if _run_state["status"] == "running" and _run_state.get("project_id") == project_id:
        raise HTTPException(400, "Cannot delete the active running project.")
    project_manager.delete(project_id)
    return {"deleted": project_id}

# ---------------------------------------------------------------------------
# Run endpoints
# ---------------------------------------------------------------------------

@app.post("/api/run/start")
async def run_start(req: RunRequest):
    if _run_state["status"] == "running":
        raise HTTPException(400, "A run is already in progress.")
    p = _active()
    if req.instruction: p.instruction = req.instruction; p.save()
    threading.Thread(target=_run_pipeline, args=(req, p.id), daemon=True).start()
    return {"status": "started", "project_id": p.id}

@app.get("/api/run/status")
async def run_status():
    state = dict(_run_state)
    p = project_manager.active
    if p and p.document_json_path.exists():
        try: state["document"] = json.loads(p.document_json_path.read_text())
        except Exception: state["document"] = None
    return JSONResponse(state)

@app.get("/api/run/log")
async def run_log(n: int = 100):
    return {"lines": list(_log_buffer)[-n:]}

@app.post("/api/run/cancel")
async def run_cancel():
    _cancel_flag.set(); return {"status": "cancel_requested"}

@app.post("/api/state/reset")
async def state_reset():
    if _run_state["status"] == "running":
        raise HTTPException(400, "Cannot reset while running.")
    p = _active(); _do_reset(p)
    _run_state.update({"status": "idle", "error": None, "sections_done": 0})
    return {"status": "reset", "project_id": p.id}

# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

@app.post("/api/sources/upload")
async def sources_upload(files: List[UploadFile] = File(...)):
    p = _active(); p.sources_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        (p.sources_dir / f.filename).write_bytes(await f.read())
        saved.append(f.filename)
    return {"uploaded": saved}

@app.get("/api/sources")
async def sources_list():
    p = _active()
    if not p.sources_dir.exists(): return {"files": []}
    return {"files": sorted([
        {"name": x.name, "size": x.stat().st_size, "ext": x.suffix.lower()}
        for x in p.sources_dir.iterdir() if x.is_file()
    ], key=lambda x: x["name"])}

@app.delete("/api/sources/{name}")
async def sources_delete(name: str):
    p = _active(); path = p.sources_dir / name
    if not path.exists(): raise HTTPException(404, f"File not found: {name}")
    path.unlink()
    # Bust vector index so it rebuilds on next run
    idx = p.vector_index_dir / "sources"
    if idx.exists(): shutil.rmtree(idx, ignore_errors=True)
    return {"deleted": name}

# ---------------------------------------------------------------------------
# Document & export
# ---------------------------------------------------------------------------

@app.get("/api/document")
async def get_document():
    p = _active()
    if not p.document_json_path.exists():
        raise HTTPException(404, "No document yet.")
    return JSONResponse(json.loads(p.document_json_path.read_text()))

@app.get("/api/export/{fmt}")
async def export_download(fmt: str):
    allowed = {"docx","md","pdf","txt","html"}
    if fmt not in allowed: raise HTTPException(400, f"Must be one of {allowed}")
    p = _active(); path = p.output_dir / f"final_document.{fmt}"
    if not path.exists(): raise HTTPException(404, f"No {fmt} export. Run the pipeline first.")
    media = {"docx":"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "pdf":"application/pdf","md":"text/markdown","txt":"text/plain","html":"text/html"}
    safe = p.name.replace(" ","_")[:40]
    return FileResponse(str(path), media_type=media[fmt], filename=f"{safe}.{fmt}")

# ---------------------------------------------------------------------------
# Settings / model / updates
# ---------------------------------------------------------------------------

@app.get("/api/settings")
async def settings_get():
    from utils.app_config import config as cfg; return JSONResponse(cfg.safe_all())

@app.post("/api/settings")
async def settings_save(body: dict):
    from utils.app_config import config as cfg
    clean = {k: v for k,v in body.items() if "••••" not in str(v)}
    cfg.update(clean); return {"saved": list(clean.keys())}

@app.get("/api/model/validate")
async def model_validate():
    from utils.app_config import config as cfg
    return validate_model_path(cfg.get("local_model_path",""))

@app.get("/api/update-check")
async def update_check():
    REPO, CURRENT = "your-org/clericus", "0.5.0"
    try:
        import urllib.request
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/releases/latest",
            headers={"User-Agent":"Clericus"})
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read())
        latest = data.get("tag_name","").lstrip("v")
        return {"current":CURRENT,"latest":latest,
                "update_available":bool(latest and latest!=CURRENT),
                "release_url":data.get("html_url","")}
    except Exception:
        return {"current":CURRENT,"latest":"","update_available":False,"release_url":""}

# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws/log")
async def ws_log(ws: WebSocket):
    await ws.accept(); _ws_clients.append(ws)
    for line in list(_log_buffer):
        await ws.send_text(json.dumps({"type":"log","line":line}))
    try:
        while True: await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        if ws in _ws_clients: _ws_clients.remove(ws)

# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent.parent / "static"
if STATIC_DIR.exists() and any(STATIC_DIR.iterdir()):
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
