#!/usr/bin/env python3
"""Smoke tests for comsol_viz_mcp JSON-RPC over stdio."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).parent.parent
SERVER = REPO / "comsol_viz_mcp" / "comsol_viz_mcp_server.py"
FIXTURE = REPO / "tests" / "fixtures" / "sample_axisym_field.h5"
OUTPUT = REPO / "output" / "test_comsol_viz"


def _write_fixture():
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    import h5py

    nr, nz = 40, 60
    r = np.linspace(0, 0.05, nr)
    z = np.linspace(0, 0.2, nz)
    rr, zz = np.meshgrid(r, z, indexing="ij")
    coords = np.column_stack([rr.ravel(), zz.ravel()])
    e_mag = 1e5 * (1.0 + 0.2 * np.sin(2 * np.pi * zz.ravel() / 0.2))
    with h5py.File(FIXTURE, "w") as f:
        f.create_dataset("coords", data=coords)
        f.create_dataset("em.E_mag", data=e_mag)


def send_and_parse(proc, command):
    proc.stdin.write(json.dumps(command) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line.strip():
        return None
    resp = json.loads(line)
    if "error" in resp:
        return {"_error": resp["error"]["message"]}
    result = resp.get("result", {})
    content = result.get("content", [])
    if content and "text" in content[0]:
        return json.loads(content[0]["text"])
    return result


def test_comsol_viz_pipeline():
    _write_fixture()
    OUTPUT.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(REPO),
        env={
            **dict(**{k: v for k, v in __import__("os").environ.items()}),
            "MPLCONFIGDIR": str(REPO / ".matplotlib_cache"),
            "COMSOL_VIZ_OUTPUT_DIR": str(OUTPUT),
        },
    )

    try:
        r = send_and_parse(
            proc,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert r["serverInfo"]["name"] == "comsol_viz_mcp"

        # First stdout line must be valid JSON (no matplotlib warnings)
        r = send_and_parse(
            proc,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "comsol_viz_health",
                "arguments": {},
            }},
        )
        assert r["status"] == "ok"

        r = send_and_parse(
            proc,
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "comsol_viz_load_field",
                "arguments": {"file_path": str(FIXTURE)},
            }},
        )
        handle = r["handle"]
        assert "em.E_mag" in r["fields"]

        out_png = str(OUTPUT / "e_mag_map.png")
        r = send_and_parse(
            proc,
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                "name": "comsol_viz_render_field_map",
                "arguments": {
                    "handle": handle,
                    "field": "em.E_mag",
                    "output_file": out_png,
                },
            }},
        )
        assert Path(r["output_file"]).exists()
        print("comsol_viz_mcp smoke test: OK")
    finally:
        proc.terminate()


if __name__ == "__main__":
    test_comsol_viz_pipeline()
