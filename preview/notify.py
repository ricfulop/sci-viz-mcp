"""
notify.py
Fire-and-forget notification to the live preview server.

Uses only stdlib — no aiohttp dependency here — so every MCP server can
import this without adding heavy deps.  Notifications are sent in a
daemon thread to avoid blocking the render pipeline.

On first call, auto-launches the preview server if it is not already
running and opens the dashboard in the default browser.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

PREVIEW_PORT = int(os.environ.get("SCIVIZ_PREVIEW_PORT", "8765"))
PREVIEW_URL = f"http://localhost:{PREVIEW_PORT}/api/render"
HEALTH_URL = f"http://localhost:{PREVIEW_PORT}/health"

_server_proc = None
_launch_lock = threading.Lock()
_launched = False


def _is_server_alive() -> bool:
    try:
        urllib.request.urlopen(HEALTH_URL, timeout=0.5)
        return True
    except Exception:
        return False


def _try_launch_server():
    """Start the preview server subprocess if not already running."""
    global _server_proc, _launched
    with _launch_lock:
        if _launched:
            return
        _launched = True

        if _is_server_alive():
            return

        server_script = str(Path(__file__).parent / "server.py")
        python = sys.executable

        try:
            _server_proc = subprocess.Popen(
                [python, server_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            pass


def _post_notification(payload: dict, retries: int = 2):
    """POST JSON to the preview server, launching it if needed."""
    data = json.dumps(payload).encode()

    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                PREVIEW_URL,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=1.0)
            return
        except (urllib.error.URLError, ConnectionRefusedError, OSError):
            if attempt == 0:
                _try_launch_server()
                time.sleep(2.0)
        except Exception:
            return


def notify_preview(
    output_file: str,
    tool_name: str,
    params: dict | None = None,
    server_name: str = "unknown",
):
    """Notify the live preview dashboard of a new render.

    Non-blocking: runs entirely in a daemon thread.
    Silent if the preview server is unreachable after auto-launch attempt.
    """
    safe_params = {}
    if params:
        for k, v in params.items():
            try:
                json.dumps(v)
                safe_params[k] = v
            except (TypeError, ValueError):
                safe_params[k] = str(v)

    payload = {
        "output_file": str(output_file),
        "tool": tool_name,
        "server": server_name,
        "params": safe_params,
        "file_name": Path(output_file).name,
    }

    t = threading.Thread(target=_post_notification, args=(payload,), daemon=True)
    t.start()
