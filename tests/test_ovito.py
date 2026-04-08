#!/usr/bin/env python3
"""
test_ovito.py
Validation test for the ovito_mcp server.

Imports fluorite ZrO2, applies modifiers, and renders an image.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
SERVER = REPO / "ovito_mcp" / "ovito_mcp_server.py"
CIF = REPO / "tests" / "sample_structures" / "fluorite_ZrO2.cif"
OUTPUT = REPO / "output"


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


def test_ovito_pipeline():
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=str(REPO),
    )

    try:
        # Initialize
        r = send_and_parse(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert r["serverInfo"]["name"] == "ovito_mcp"
        print("  [1] Initialize: OK")

        # Import data
        r = send_and_parse(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "ovito.import_data",
            "arguments": {"file_path": str(CIF)},
        }})
        handle = r["handle"]
        assert r["num_particles"] > 0
        print(f"  [2] Import: {r['num_particles']} particles, types={r.get('particle_types', [])}")

        # Set visual style
        r = send_and_parse(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "ovito.set_visual_style",
            "arguments": {
                "handle": handle,
                "particle_colors": {"Zr": "#4a86c8", "O": "#e74c3c"},
                "particle_radii": {"Zr": 0.6, "O": 0.4},
            },
        }})
        print(f"  [3] Visual style: {r['applied']}")

        # Set camera
        r = send_and_parse(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "ovito.set_camera",
            "arguments": {"handle": handle, "type": "ORTHO", "direction": [0, 0, -1]},
        }})
        print(f"  [4] Camera: {r['camera_type']}, dir={r['direction']}")

        # Render image
        out_file = str(OUTPUT / "ovito_fluorite_test.png")
        r = send_and_parse(proc, {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
            "name": "ovito.render_image",
            "arguments": {
                "handle": handle,
                "output_file": out_file,
                "width": 800,
                "height": 600,
            },
        }})
        if "_error" in r:
            print(f"  [5] RENDER ERROR: {r['_error']}")
        assert "output_file" in r, f"Render failed: {r}"
        assert Path(r["output_file"]).exists()
        size_kb = Path(r["output_file"]).stat().st_size / 1024
        print(f"  [5] Render: {r['output_file']} ({size_kb:.0f} KB)")

        # Pipeline status
        r = send_and_parse(proc, {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
            "name": "ovito.pipeline_status",
            "arguments": {"handle": handle},
        }})
        print(f"  [6] Pipeline: {r['num_particles']} particles, {len(r['modifiers'])} modifiers")
        print(f"       Properties: {r['properties']}")

        # List pipelines
        r = send_and_parse(proc, {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
            "name": "ovito.list_pipelines",
            "arguments": {},
        }})
        assert len(r["pipelines"]) >= 1
        print(f"  [7] Pipelines: {len(r['pipelines'])}")

        print("\n  All assertions passed!")

    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


if __name__ == "__main__":
    print("=== OVITO MCP Validation Test ===\n")
    test_ovito_pipeline()
    print("\n=== DONE ===")
