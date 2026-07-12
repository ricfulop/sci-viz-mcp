#!/usr/bin/env python3
"""
Generate MCP server registration JSON for this checkout of sci-viz-mcp.

Prints a ready-to-paste "mcpServers" block with absolute paths for THIS
machine, so users never hand-edit paths. Optionally merges directly into
~/.cursor/mcp.json with --write.

Usage:
    .venv/bin/python scripts/generate_mcp_config.py            # print JSON
    .venv/bin/python scripts/generate_mcp_config.py --write    # merge into ~/.cursor/mcp.json
    .venv/bin/python scripts/generate_mcp_config.py --servers crystal_mcp,ovito_mcp
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv" / "bin" / "python"


def python_servers() -> dict:
    py = str(VENV_PY if VENV_PY.exists() else sys.executable)
    cwd = str(ROOT)
    servers = {
        "crystal_mcp": {
            "command": py,
            "args": [str(ROOT / "crystal_mcp" / "crystal_mcp_server.py")],
            "cwd": cwd,
            "env": {"MPLCONFIGDIR": str(ROOT / ".matplotlib_cache")},
            "transport": "stdio",
        },
        "ovito_mcp": {
            "command": py,
            "args": [str(ROOT / "ovito_mcp" / "ovito_mcp_server.py")],
            "cwd": cwd,
            "transport": "stdio",
        },
        "comsol_viz_mcp": {
            "command": py,
            "args": [str(ROOT / "comsol_viz_mcp" / "comsol_viz_mcp_server.py")],
            "cwd": cwd,
            "env": {
                "MPLCONFIGDIR": str(ROOT / ".matplotlib_cache"),
                "COMSOL_VIZ_OUTPUT_DIR": str(ROOT / "output"),
            },
            "transport": "stdio",
        },
        "comsol_mcp": {
            "command": py,
            "args": [str(ROOT / "comsol_mcp" / "comsol_mcp_server.py")],
            "cwd": cwd,
            "env": {
                # Optional: point at your own runs dir / default .mph template
                "COMSOL_MCP_RUNS_DIR": str(ROOT / "output" / "comsol_runs"),
            },
            "transport": "stdio",
        },
        "ray_optics_mcp": {
            "command": py,
            "args": [str(ROOT / "ray_optics_mcp" / "ray_optics_mcp_server.py")],
            "cwd": cwd,
            "transport": "stdio",
        },
        "physical_optics_mcp": {
            "command": py,
            "args": [
                str(
                    ROOT
                    / "physical_optics_mcp"
                    / "physical_optics_mcp_server.py"
                )
            ],
            "cwd": cwd,
            "env": {
                "MPLCONFIGDIR": str(ROOT / ".matplotlib_cache"),
                "PHYSICAL_OPTICS_OUTPUT_DIR": str(
                    ROOT / "output" / "physical_optics"
                ),
            },
            "transport": "stdio",
        },
        "optical_design_mcp": {
            "command": py,
            "args": [
                str(
                    ROOT
                    / "optical_design_mcp"
                    / "optical_design_mcp_server.py"
                )
            ],
            "cwd": cwd,
            "env": {
                "MPLCONFIGDIR": str(ROOT / ".matplotlib_cache"),
                "OPTICAL_DESIGN_OUTPUT_DIR": str(
                    ROOT / "output" / "optical_design"
                ),
            },
            "transport": "stdio",
        },
        "siril_mcp": {
            "command": py,
            "args": [str(ROOT / "siril_mcp" / "siril_mcp_server.py")],
            "cwd": cwd,
            "transport": "stdio",
        },
        "picogk_mcp": {
            "command": py,
            "args": [str(ROOT / "picogk_mcp" / "picogk_mcp_server.py")],
            "cwd": cwd,
            "env": {
                "PICOGK_MCP_OUTPUT_DIR": str(ROOT / "output" / "picogk"),
                "DOTNET_CLI_HOME": str(ROOT / "output" / "dotnet-home"),
                "NUGET_PACKAGES": str(ROOT / ".nuget" / "packages"),
                **(
                    {"PICOGK_MCP_DOTNET": str(ROOT / ".dotnet" / "dotnet")}
                    if (ROOT / ".dotnet" / "dotnet").exists()
                    else {}
                ),
            },
            "transport": "stdio",
        },
    }
    return servers


def node_servers() -> dict:
    node = shutil.which("node") or "node"
    servers = {}
    pix_build = ROOT / "pixinsight_mcp" / "build" / "index.js"
    servers["pixinsight"] = {
        "command": node,
        "args": [str(pix_build)],
        "cwd": str(ROOT / "pixinsight_mcp"),
        "transport": "stdio",
        "_note": "Requires npm run build first, plus a licensed PixInsight running the PJSR watcher.",
    }
    return servers


def external_servers() -> dict:
    """Servers launched via an external CLI (uvx, etc.), not a repo script."""
    uvx = shutil.which("uvx") or "uvx"
    addon = ROOT / "freecad_mcp" / "addon"
    return {
        "freecad": {
            "command": uvx,
            "args": ["freecad-mcp"],
            "transport": "stdio",
            "_comment": (
                "neka-nat/freecad-mcp — FreeCAD must be running with the "
                "FreeCADMCP RPC server started (see freecad_mcp/README_SCIVIZ.md)."
            ),
            # Presence gate: vendored FreeCAD workbench must exist.
            "_entry": str(addon / "InitGui.py"),
            "_note": (
                "Run ./install_freecad_mcp.sh and start FreeCAD → MCP Addon → "
                "Start RPC Server before using."
            ),
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="Merge into ~/.cursor/mcp.json (backs up existing file)")
    ap.add_argument("--servers", default="",
                    help="Comma-separated subset (default: all)")
    args = ap.parse_args()

    servers = {**python_servers(), **node_servers(), **external_servers()}

    # Drop servers whose entry point / vendored prerequisite is missing.
    ready, skipped = {}, []
    for name, cfg in servers.items():
        gate = cfg.get("_entry") or cfg["args"][0]
        if not Path(gate).exists():
            skipped.append((name, cfg.get("_note", f"missing {gate}")))
            continue
        cfg.pop("_note", None)
        cfg.pop("_entry", None)
        ready[name] = cfg

    if args.servers:
        wanted = {s.strip() for s in args.servers.split(",")}
        ready = {k: v for k, v in ready.items() if k in wanted}

    if skipped:
        for name, why in skipped:
            print(f"# skipped {name}: {why}", file=sys.stderr)

    if args.write:
        target = Path.home() / ".cursor" / "mcp.json"
        existing = {}
        if target.exists():
            existing = json.loads(target.read_text())
            backup = target.with_suffix(".json.bak")
            backup.write_text(target.read_text())
            print(f"# backed up existing config to {backup}", file=sys.stderr)
        existing.setdefault("mcpServers", {}).update(ready)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(existing, indent=2) + "\n")
        print(f"# wrote {len(ready)} server entries to {target}", file=sys.stderr)
    else:
        print(json.dumps({"mcpServers": ready}, indent=2))


if __name__ == "__main__":
    main()
