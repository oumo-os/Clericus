"""
utils/app_config.py
-------------------
Persistent application settings stored at ~/.clericus/settings.json.

All LLM credentials, model selections, and app preferences live here so
users never have to touch a terminal, environment variable, or config file.

Priority order for LLM credentials:
  1. app_config  (set via Settings panel in the GUI)
  2. environment variable  (power users / CI / CLI)
  3. built-in default

Usage:
    from utils.app_config import config

    key  = config.get("anthropic_api_key")
    back = config.get("llm_backend", default="ollama")
    config.set("anthropic_api_key", "sk-ant-...")
    config.save()
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

# Config file location — respects XDG on Linux, uses home dir everywhere
_CONFIG_DIR  = Path.home() / ".clericus"
_CONFIG_FILE = _CONFIG_DIR / "settings.json"

# ── Defaults ──────────────────────────────────────────────────────────────

DEFAULTS: Dict[str, Any] = {
    # LLM
    "llm_backend":        "ollama",      # ollama | anthropic | openai | gemini | local
    "anthropic_api_key":  "",
    "openai_api_key":     "",
    "gemini_api_key":     "",
    "anthropic_model":    "claude-sonnet-4-6",
    "openai_model":       "gpt-4o",
    "gemini_model":       "gemini-2.0-flash",

    # Ollama
    "ollama_url":         "http://localhost:11434",
    "ollama_model":       "llama3.2",

    # Local llama-cpp
    "local_model_path":   "",            # path to .gguf file

    # Drafting
    "max_depth":          3,
    "default_budget":     3000,
    "subdivision_threshold": 900,

    # Misc
    "sources_dir":        "",            # empty = use ./sources relative to cwd
    "output_dir":         "",
    "check_updates":      True,
    "last_known_version": "",
    "theme":              "dark",        # reserved for future light mode
}


class AppConfig:
    """Thin key-value store backed by a JSON file in the user's home dir."""

    def __init__(self):
        self._data: Dict[str, Any] = dict(DEFAULTS)
        self._load()

    # ------------------------------------------------------------------

    def _load(self) -> None:
        if _CONFIG_FILE.exists():
            try:
                saved = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
                # Merge: saved values override defaults, unknown keys are kept
                self._data.update(saved)
            except Exception:
                pass  # corrupt file — use defaults silently

    def save(self) -> None:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(
            json.dumps(self._data, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """
        Return the setting value.  Resolution order:
          1. Saved/runtime value in self._data
          2. Matching environment variable (upper-case key)
          3. DEFAULTS dict
          4. caller-supplied default
        """
        val = self._data.get(key)
        if val is not None and val != "":
            return val
        # Env var fallback
        env_val = os.environ.get(key.upper(), "")
        if env_val:
            return env_val
        return DEFAULTS.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def update(self, patch: Dict[str, Any]) -> None:
        """Apply a dict of changes and save immediately."""
        self._data.update(patch)
        self.save()

    def all(self) -> Dict[str, Any]:
        """Return all settings (safe copy, no mutation)."""
        return dict(self._data)

    def safe_all(self) -> Dict[str, Any]:
        """Like all() but redacts API key values for sending to the frontend."""
        safe = dict(self._data)
        for key in ("anthropic_api_key", "openai_api_key", "gemini_api_key"):
            if safe.get(key):
                safe[key] = "••••••••" + safe[key][-4:]
        return safe


# Module-level singleton — import this everywhere
config = AppConfig()
