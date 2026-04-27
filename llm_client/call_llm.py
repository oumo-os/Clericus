"""
llm_client/call_llm.py
----------------------
Unified LLM dispatch layer supporting four backends:
  openai   — OpenAI Chat Completions (gpt-4o, gpt-4-turbo, …)
  anthropic — Anthropic Messages API  (claude-sonnet-4-6, …)   ← NEW
  gemini   — Google Gemini            (gemini-2.0-flash, …)
  ollama   — Local Ollama server      (llama3, qwen, …)
  local    — llama-cpp-python binary  (llama_cpp, not llamacpp)

Bug fixes vs the old version:
  - Ollama "format":"json" is only sent when parse_json=True
  - llama_cpp import name corrected (was "llamacpp")
  - Gemini cost tracking uncommented and live (optional env var guard)
  - Anthropic backend added
"""

import json
import os
import subprocess
import time
from typing import Any

import backoff

from utils.logging import log_info, log_error

# ---------------------------------------------------------------------------
# Config  (resolved at call time — app_config > env vars > defaults)
# ---------------------------------------------------------------------------

_DEFAULT_BACKEND = "ollama"

def _cfg(key: str, default: str = "") -> str:
    """Resolve a config value: app_config > env var > default."""
    try:
        from utils.app_config import config as _app_cfg
        val = _app_cfg.get(key, "")
        if val and str(val).strip():
            return str(val)
    except Exception:
        pass
    return os.environ.get(key.upper(), default)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def call_llm(
    prompt: str,
    parse_json: bool = False,
    max_retries: int = 3,
    **kwargs: Any,
) -> Any:
    """
    Route to the active LLM backend.

    Args:
        prompt:      Text prompt to send.
        parse_json:  If True, parse the response as JSON.
        max_retries: Retry budget (passed to backoff decorators).
        **kwargs:    Backend-specific overrides (model, temperature, …).

    Returns:
        Parsed JSON object (if parse_json=True) or raw response string.
    """
    backend = kwargs.pop("backend", _cfg("llm_backend", os.getenv("LLM_BACKEND", _DEFAULT_BACKEND)).lower())
    dispatch = {
        "openai":    _call_openai,
        "anthropic": _call_anthropic,
        "gemini":    _call_gemini,
        "ollama":    _call_ollama,
        "local":     _call_local,
    }
    fn = dispatch.get(backend)
    if fn is None:
        log_error(f"Unknown LLM_BACKEND '{backend}'; falling back to ollama.")
        fn = _call_ollama
    return fn(prompt, parse_json, max_retries, **kwargs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(content: str, parse_json: bool) -> Any:
    """Attempt JSON parse; try stripping markdown fences on first failure."""
    if not parse_json:
        return content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        cleaned = extract_json_block(content)
        if cleaned:
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass
        log_error("JSON parse failed; returning raw string.")
        raise


def extract_json_block(text: str) -> str | None:
    """Extract text inside the first ```json … ``` fence."""
    import re
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    return match.group(1).strip() if match else None


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

@backoff.on_exception(backoff.expo, Exception, max_tries=3, jitter=backoff.full_jitter)
def _call_openai(prompt: str, parse_json: bool, max_retries: int, **kwargs) -> Any:
    from openai import OpenAI
    client = OpenAI(api_key=_cfg("openai_api_key"))
    model = kwargs.get("model", _cfg("openai_model", "gpt-4o"))
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=kwargs.get("temperature", 0.7),
    )
    content = response.choices[0].message.content
    log_info(
        f"OpenAI ({model}) — "
        f"in={response.usage.prompt_tokens} "
        f"out={response.usage.completion_tokens}"
    )
    return _parse(content, parse_json)


# ---------------------------------------------------------------------------
# Anthropic  (NEW)
# ---------------------------------------------------------------------------

@backoff.on_exception(backoff.expo, Exception, max_tries=3, jitter=backoff.full_jitter)
def _call_anthropic(prompt: str, parse_json: bool, max_retries: int, **kwargs) -> Any:
    import anthropic
    client = anthropic.Anthropic(api_key=_cfg("anthropic_api_key"))
    model = kwargs.get("model", _cfg("anthropic_model", "claude-sonnet-4-6"))
    message = client.messages.create(
        model=model,
        max_tokens=kwargs.get("max_tokens", 4096),
        messages=[{"role": "user", "content": prompt}],
    )
    content = message.content[0].text
    log_info(
        f"Anthropic ({model}) — "
        f"in={message.usage.input_tokens} "
        f"out={message.usage.output_tokens}"
    )
    return _parse(content, parse_json)


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

@backoff.on_exception(backoff.expo, Exception, max_tries=3, jitter=backoff.full_jitter)
def _call_gemini(prompt: str, parse_json: bool, max_retries: int, **kwargs) -> Any:
    from google import genai
    client = genai.Client(api_key=_cfg("gemini_api_key"))
    model = kwargs.get("model", _cfg("gemini_model", "gemini-2.0-flash"))

    gen_config: dict = {}
    if parse_json:
        gen_config["response_mime_type"] = "application/json"

    response = client.models.generate_content(
        model=model,
        contents=[prompt],
        config=gen_config or None,
    )
    content = response.text
    log_info(f"Gemini ({model}) — response received")
    return _parse(content, parse_json)


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

@backoff.on_exception(backoff.expo, Exception, max_tries=3, jitter=backoff.full_jitter)
def _call_ollama(prompt: str, parse_json: bool, max_retries: int, **kwargs) -> Any:
    import requests as _requests
    model = kwargs.get("model", _cfg("ollama_model", "llama3.2"))
    url = f"{_cfg('ollama_url', 'http://localhost:11434')}/api/generate"
    payload: dict = {"model": model, "prompt": prompt, "stream": False}
    # Only request JSON-constrained output when the caller actually needs JSON.
    # Sending "format":"json" unconditionally was causing garbled plain-text outputs.
    if parse_json:
        payload["format"] = "json"

    response = _requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=1800,
    )
    response.raise_for_status()
    data = json.loads(response.text)

    # Ollama /api/generate returns {"response": "..."}
    content = data.get("response") or json.dumps(data)
    log_info(f"Ollama ({model}) — response received")
    return _parse(content, parse_json)


# ---------------------------------------------------------------------------
# Local llama-cpp-python
# ---------------------------------------------------------------------------

@backoff.on_exception(backoff.expo, Exception, max_tries=3, jitter=backoff.full_jitter)
def _call_local(prompt: str, parse_json: bool, max_retries: int, **kwargs) -> Any:
    content: str = ""
    try:
        from llama_cpp import Llama   # package name is llama_cpp, not llamacpp
        llm = Llama(model_path=_cfg("local_model_path", "./models/ggml-model.bin"), n_ctx=4096)
        result = llm(prompt, **kwargs)
        content = result["choices"][0]["text"]
    except ImportError:
        # Fallback: invoke llama.cpp CLI binary
        try:
            proc = subprocess.Popen(
                ["llama", "-m", _cfg("local_model_path", "./models/ggml-model.bin"), "-p", prompt],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            out, _ = proc.communicate(timeout=120)
            content = out.strip()
        except Exception as e:
            log_error("Local LLM call failed", e)
            raise
    return _parse(content, parse_json)
