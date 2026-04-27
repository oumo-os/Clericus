"""
utils/project.py
----------------
Project management for Clericus.

Each project is self-contained under:
    ~/Documents/Clericus/projects/<project_id>/
        project.json        — metadata (name, instruction, backend, dates)
        sources/            — user-uploaded source documents
        vector_index/       — FAISS index of those sources
        state/              — section JSON cache (crash-resume)
        efb_index/          — established facts base for this document
        questions.json      — question tracker state
        output/             — final exports (docx, md, pdf, html, txt)
        document.json       — last polished document tree

Global (shared across all projects):
    ~/.clericus/
        settings.json       — API keys, model paths, UI preferences
        curated_kb/         — immutable domain knowledge bases

The curated KB is never owned by a project. It can be enriched with
build_kb.py but not modified by a run.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Base directory
# ---------------------------------------------------------------------------

def _base_dir() -> Path:
    """
    Cross-platform projects root:
        Windows : ~/Documents/Clericus/projects
        Mac/Linux: ~/Clericus/projects
    Falls back to ~/Clericus/projects everywhere if Documents doesn't exist.
    """
    docs = Path.home() / "Documents"
    root = (docs if docs.exists() else Path.home()) / "Clericus"
    return root / "projects"


BASE_DIR = _base_dir()


# ---------------------------------------------------------------------------
# Project data model
# ---------------------------------------------------------------------------

@dataclass
class Project:
    id: str
    name: str
    description: str = ""
    instruction: str = ""
    llm_backend: str = "ollama"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_run: Optional[str] = None
    last_status: str = "never_run"    # never_run | complete | error

    # ------------------------------------------------------------------
    # Path helpers — everything hangs off project_dir
    # ------------------------------------------------------------------

    @property
    def project_dir(self) -> Path:
        return BASE_DIR / self.id

    @property
    def sources_dir(self) -> Path:
        return self.project_dir / "sources"

    @property
    def vector_index_dir(self) -> Path:
        return self.project_dir / "vector_index"

    @property
    def state_dir(self) -> Path:
        return self.project_dir / "state"

    @property
    def efb_dir(self) -> Path:
        return self.project_dir / "efb_index"

    @property
    def questions_path(self) -> Path:
        return self.project_dir / "questions.json"

    @property
    def output_dir(self) -> Path:
        return self.project_dir / "output"

    @property
    def document_json_path(self) -> Path:
        return self.project_dir / "output" / "document.json"

    @property
    def internal_kb_dir(self) -> Path:
        return self.project_dir / "vector_index" / "internal_kb"

    # ------------------------------------------------------------------

    def ensure_dirs(self) -> None:
        """Create all project subdirectories."""
        for d in (self.sources_dir, self.vector_index_dir, self.state_dir,
                  self.efb_dir, self.output_dir, self.internal_kb_dir):
            d.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        self.ensure_dirs()
        meta_path = self.project_dir / "project.json"
        meta_path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, project_dir: Path) -> "Project":
        meta_path = project_dir / "project.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["source_count"] = len(list(self.sources_dir.glob("*"))) if self.sources_dir.exists() else 0
        d["has_draft"] = self.document_json_path.exists()
        return d

    def update_run_status(self, status: str) -> None:
        self.last_run = datetime.now(timezone.utc).isoformat()
        self.last_status = status
        self.save()


# ---------------------------------------------------------------------------
# Project manager
# ---------------------------------------------------------------------------

class ProjectManager:
    """Create, list, open and delete projects."""

    def __init__(self, base_dir: Path = BASE_DIR):
        self._base = base_dir
        self._base.mkdir(parents=True, exist_ok=True)
        self._active: Optional[Project] = None

    # ------------------------------------------------------------------

    def create(self, name: str, description: str = "", instruction: str = "") -> Project:
        """Create a new project and set it as active."""
        project_id = _slug(name) + "-" + uuid.uuid4().hex[:6]
        p = Project(
            id=project_id,
            name=name,
            description=description,
            instruction=instruction,
        )
        p.save()
        self._active = p
        return p

    def open(self, project_id: str) -> Project:
        """Open an existing project by ID and set it as active."""
        d = self._base / project_id
        if not d.exists():
            raise FileNotFoundError(f"Project not found: {project_id}")
        p = Project.load(d)
        self._active = p
        return p

    def list_projects(self) -> List[Dict[str, Any]]:
        """Return summary dicts for all projects, newest first."""
        projects = []
        for d in sorted(self._base.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if not d.is_dir():
                continue
            meta = d / "project.json"
            if not meta.exists():
                continue
            try:
                p = Project.load(d)
                projects.append(p.to_dict())
            except Exception:
                continue
        return projects

    def delete(self, project_id: str) -> None:
        """Permanently delete a project and all its files."""
        if self._active and self._active.id == project_id:
            self._active = None
        d = self._base / project_id
        if d.exists():
            shutil.rmtree(d)

    @property
    def active(self) -> Optional[Project]:
        return self._active

    @active.setter
    def active(self, p: Optional[Project]) -> None:
        self._active = p


# ---------------------------------------------------------------------------
# Model file validation
# ---------------------------------------------------------------------------

def validate_model_path(path: str) -> Dict[str, Any]:
    """
    Check whether a local model file path is usable.
    Returns {"ok": bool, "message": str, "size_gb": float|None}.
    """
    if not path or not path.strip():
        return {"ok": False, "message": "No model path configured.", "size_gb": None}
    p = Path(path)
    if not p.exists():
        return {"ok": False, "message": f"File not found: {path}", "size_gb": None}
    if not p.is_file():
        return {"ok": False, "message": f"Path is not a file: {path}", "size_gb": None}
    size_gb = round(p.stat().st_size / 1_073_741_824, 2)
    if not path.lower().endswith(".gguf"):
        return {"ok": True,
                "message": f"File exists ({size_gb} GB) but is not a .gguf — proceed with caution.",
                "size_gb": size_gb}
    return {"ok": True, "message": f"Ready ({size_gb} GB)", "size_gb": size_gb}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    """Convert a project name to a filesystem-safe slug."""
    import re
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:40].strip("-") or "project"


# Module-level singleton — import this in the server
project_manager = ProjectManager()
