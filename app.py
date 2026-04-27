"""
app.py — Clericus desktop entry point
--------------------------------------
Starts the FastAPI backend in a background thread, then opens a native
OS window via pywebview pointing at the local server.

When bundled with PyInstaller, this is the only file the user ever "runs"
(indirectly, via the installer-created shortcut/icon).

No terminal is shown.  The window title bar and icon are set here.
"""

import sys
import time
import socket
import threading
import logging
from pathlib import Path

# Ensure project root is importable when run from any directory
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Port selection
# ---------------------------------------------------------------------------

def _find_free_port(start: int = 8765) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start   # fallback — unlikely to collide


PORT = _find_free_port()


# ---------------------------------------------------------------------------
# Start FastAPI in background thread
# ---------------------------------------------------------------------------

def _start_server():
    import uvicorn
    # Silence uvicorn access log — we have our own log buffer in the GUI
    logging.getLogger("uvicorn.access").disabled = True
    uvicorn.run(
        "gui.api.server:app",
        host="127.0.0.1",
        port=PORT,
        log_level="warning",
    )


server_thread = threading.Thread(target=_start_server, daemon=True)
server_thread.start()


# ---------------------------------------------------------------------------
# Wait for server to be ready (max 10 s)
# ---------------------------------------------------------------------------

def _wait_for_server(port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


if not _wait_for_server(PORT):
    # Last resort — just try to open anyway
    pass


# ---------------------------------------------------------------------------
# Open the native window
# ---------------------------------------------------------------------------

import webview   # pywebview

ICON_PATH = str(ROOT / "gui" / "static" / "icon.png")

window = webview.create_window(
    title="Clericus",
    url=f"http://127.0.0.1:{PORT}",
    width=1280,
    height=820,
    min_size=(900, 600),
    # background_color="#0f1117",   # matches --bg; some platforms ignore this
)


def _on_closed():
    """Called when the user closes the window — clean shutdown."""
    sys.exit(0)


window.events.closed += _on_closed

# gui=True uses the OS native WebView (no Chromium shipped)
webview.start(
    gui="edgechromium" if sys.platform == "win32" else None,
    debug=False,
)
