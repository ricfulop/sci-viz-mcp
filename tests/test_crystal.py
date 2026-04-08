#!/usr/bin/env python3
"""
test_crystal.py
Validation test: reproduce fig10 panel (a) style lattice using crystal_mcp.

Imports fluorite ZrO2, builds a 3x3x1 supercell, creates oxygen vacancies,
and renders a publication-quality [001] projection matching the acoustic
blueprint diagram.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
SERVER = REPO / "crystal_mcp" / "crystal_mcp_server.py"
CIF = REPO / "tests" / "sample_structures" / "fluorite_ZrO2.cif"
OUTPUT = REPO / "output"


def send_and_parse(proc, command):
    """Send one command and read one response line."""
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


def test_full_pipeline():
    """Test: import -> symmetry -> supercell -> render -> tikz -> unit_cell"""
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=str(REPO),
    )

    try:
        # Initialize
        r = send_and_parse(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert r["serverInfo"]["name"] == "crystal_mcp"
        print("  [1] Initialize: OK")

        # Import structure
        r = send_and_parse(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "crystal.import_structure",
            "arguments": {"file_path": str(CIF)},
        }})
        handle = r["handle"]
        assert r["cell_params"]["a"] == 5.145
        assert "Zr" in r["species"] and "O" in r["species"]
        print(f"  [2] Import: {r['formula']}, handle={handle}, a={r['cell_params']['a']} A")

        # Get symmetry
        r = send_and_parse(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "crystal.get_symmetry",
            "arguments": {"handle": handle},
        }})
        assert r["space_group_symbol"] == "Fm-3m"
        assert r["space_group_number"] == 225
        assert r["crystal_system"] == "cubic"
        print(f"  [3] Symmetry: {r['space_group_symbol']} (#{r['space_group_number']}), {r['crystal_system']}")

        # Build supercell
        r = send_and_parse(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "crystal.build_supercell",
            "arguments": {"handle": handle, "repeats": [3, 3, 1]},
        }})
        sc_handle = r["handle"]
        assert r["n_atoms"] == 108  # 12 * 9
        print(f"  [4] Supercell: {r['formula']}, {r['n_atoms']} atoms, handle={sc_handle}")

        # Render lattice projection
        out_render = str(OUTPUT / "fig10a_validation.png")
        r = send_and_parse(proc, {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
            "name": "crystal.render_lattice",
            "arguments": {
                "handle": sc_handle,
                "output_file": out_render,
                "title": "Fluorite ZrO2 — Acoustic Blueprint [001]",
                "projection": "001",
                "atom_colors": {"Zr": "#4a86c8", "O": "#e74c3c"},
                "dpi": 300,
                "show_labels": True,
            },
        }})
        assert Path(r["output_file"]).exists()
        size_kb = Path(r["output_file"]).stat().st_size / 1024
        print(f"  [5] Render: {r['output_file']} ({size_kb:.0f} KB)")

        # Export TikZ
        out_tikz = str(OUTPUT / "fig10a_validation.tex")
        r = send_and_parse(proc, {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
            "name": "crystal.export_tikz",
            "arguments": {"handle": sc_handle, "output_file": out_tikz},
        }})
        assert Path(r["output_file"]).exists()
        print(f"  [6] TikZ: {r['output_file']}")

        # Render unit cell
        out_uc = str(OUTPUT / "fig10a_unit_cell.png")
        r = send_and_parse(proc, {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
            "name": "crystal.render_unit_cell",
            "arguments": {
                "handle": handle,
                "output_file": out_uc,
                "title": "Fluorite ZrO2 Unit Cell",
                "dpi": 300,
            },
        }})
        assert Path(r["output_file"]).exists()
        print(f"  [7] Unit cell: {r['output_file']}")

        # Create vacancy
        r = send_and_parse(proc, {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {
            "name": "crystal.create_defect",
            "arguments": {"handle": handle, "defect_type": "vacancy", "site_index": 4},
        }})
        assert r["defect_type"] == "vacancy"
        assert r["removed_species"] == "O"
        print(f"  [8] Vacancy: removed {r['removed_species']} at index {r['removed_index']}")

        # List all structures
        r = send_and_parse(proc, {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {
            "name": "crystal.list_structures",
            "arguments": {},
        }})
        assert len(r["structures"]) >= 3
        print(f"  [9] Loaded structures: {len(r['structures'])}")
        for s in r["structures"]:
            print(f"      - {s['handle']}: {s['formula']} ({s['n_atoms']} atoms)")

        print("\n  All 9 assertions passed!")

    finally:
        proc.stdin.close()
        proc.wait(timeout=5)


if __name__ == "__main__":
    print("=== Fig10 Panel (a) Validation Test ===\n")
    test_full_pipeline()
    print("\n=== DONE ===")
