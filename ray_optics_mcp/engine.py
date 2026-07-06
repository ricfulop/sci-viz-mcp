"""
Headless invocation of the Ray Optics Simulation engine (vendor/runner.js).

Shared by the MCP server and the telescope design builders (which need to
trace rays during design, e.g. for focus finding and meniscus auto-tuning).
"""

import glob
import json
import os
import shutil
import subprocess
from pathlib import Path

_THIS_DIR = Path(__file__).parent.resolve()
VENDOR_DIR = _THIS_DIR / "vendor"
RUNNER_JS = VENDOR_DIR / "runner.js"


def find_node() -> str:
    env_node = os.environ.get("RAY_OPTICS_NODE")
    if env_node and Path(env_node).exists():
        return env_node
    which = shutil.which("node")
    if which:
        return which
    # Cursor-launched MCP servers often lack the nvm PATH entries
    candidates = sorted(glob.glob(str(Path.home() / ".nvm/versions/node/*/bin/node")))
    if candidates:
        return candidates[-1]
    raise RuntimeError(
        "Node.js not found. Install Node or set RAY_OPTICS_NODE to the node binary path."
    )


def run_scene(scene: dict, timeout_s: int = 120) -> dict:
    """Run a scene through runner.js and return the parsed result JSON."""
    proc = subprocess.run(
        [find_node(), str(RUNNER_JS)],
        input=json.dumps(scene).encode(),
        capture_output=True,
        cwd=str(VENDOR_DIR),  # so require('canvas') resolves vendor/node_modules
        timeout=timeout_s,
    )
    if not proc.stdout.strip():
        raise RuntimeError(
            f"Engine produced no output (exit {proc.returncode}). "
            f"stderr: {proc.stderr.decode()[:2000]}"
        )
    return json.loads(proc.stdout)
