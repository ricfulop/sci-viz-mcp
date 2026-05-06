"""Fire-and-forget POST to the sci-viz-mcp live preview dashboard.

Mirrors `sci-viz-mcp/preview/notify.py` but uses only Blender's bundled
stdlib so it can run inside Blender without extra deps.

The dashboard is optional; if it is not running the post fails silently.

Headless safety: the thread is non-daemon and the operator joins it with
a short timeout so the POST always completes before Blender exits in
`--background` mode (where daemon threads are killed at sys.exit). The
1 s urlopen timeout caps total latency.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

PREVIEW_PORT = int(os.environ.get("SCIVIZ_PREVIEW_PORT", "8765"))
PREVIEW_URL = f"http://localhost:{PREVIEW_PORT}/api/render"
JOIN_TIMEOUT = float(os.environ.get("SCIVIZ_PREVIEW_JOIN_TIMEOUT", "2.0"))


def _safe_params(params: dict | None) -> dict:
    if not params:
        return {}
    out: dict = {}
    for k, v in params.items():
        try:
            json.dumps(v)
            out[k] = v
        except (TypeError, ValueError):
            out[k] = str(v)
    return out


def _post(payload: dict) -> None:
    data = json.dumps(payload).encode()
    try:
        req = urllib.request.Request(
            PREVIEW_URL,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=1.0)
    except (urllib.error.URLError, ConnectionRefusedError, OSError):
        pass
    except Exception:
        pass


def notify_preview(
    output_file: str,
    tool_name: str,
    params: dict | None = None,
    server_name: str = "sciviz_blender_addon",
    *,
    block: bool = True,
) -> None:
    payload = {
        "output_file": str(output_file),
        "tool": tool_name,
        "server": server_name,
        "params": _safe_params(params),
        "file_name": Path(str(output_file)).name,
    }
    t = threading.Thread(target=_post, args=(payload,), daemon=False)
    t.start()
    if block:
        t.join(timeout=JOIN_TIMEOUT)
