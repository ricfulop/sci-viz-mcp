# FreeCAD MCP in Sci-Viz

Drive FreeCAD from Cursor for parametric CAD, STEP import/export, FEM, and
TechDraw manufacturing drawings. Built on
[`neka-nat/freecad-mcp`](https://github.com/neka-nat/freecad-mcp) (MIT) —
same transport pattern as the Blender path: stdio MCP bridge ↔ localhost
RPC ↔ GUI app.

```
Cursor ──MCP/stdio──▶ uvx freecad-mcp ──XML-RPC :9875──▶ FreeCAD (1.0+)
                                                            └── FreeCADMCP addon
                                                                  (freecad_mcp/addon/)
```

FreeCAD is free/open source (LGPL). No paid license.

## Setup (one-time)

```bash
# 1. Install FreeCAD (macOS)
brew install --cask freecad

# 2. Install the FreeCADMCP addon into FreeCAD's Mod directory
cd sci-viz-mcp
./install_freecad_mcp.sh

# 3. Register the MCP server (uvx must be on PATH — https://docs.astral.sh/uv/)
.venv/bin/python scripts/generate_mcp_config.py --servers freecad --write
# or paste the freecad block from:  .venv/bin/python scripts/generate_mcp_config.py

# 4. Restart FreeCAD, switch to the "MCP Addon" workbench, click
#    "Start RPC Server" (or enable Auto-Start Server in the MCP menu).

# 5. Reload MCP servers in Cursor.
```

Addon install locations (script picks the right one):

| FreeCAD | macOS Mod path |
|---------|----------------|
| 1.1.x | `~/Library/Application Support/FreeCAD/v1-1/Mod/FreeCADMCP` |
| 1.0.x | `~/Library/Application Support/FreeCAD/v1-0/Mod/FreeCADMCP` |

## Cursor MCP registration

```json
{
  "mcpServers": {
    "freecad": {
      "command": "uvx",
      "args": ["freecad-mcp"],
      "_comment": "neka-nat/freecad-mcp — requires FreeCAD running with FreeCADMCP RPC server started"
    }
  }
}
```

Optional: `--only-text-feedback` to skip screenshot payloads (saves tokens).

## Tools (upstream)

| Tool | Purpose |
|------|---------|
| `create_document` / `get_objects` / `get_object` | Document + object inspection |
| `create_object` / `edit_object` / `delete_object` | Part primitives and edits |
| `execute_code` | Arbitrary FreeCAD Python (`Part`, `TechDraw`, `Import`, …) |
| `get_view` | Active-viewport screenshot |
| `insert_part_from_library` / `get_parts_list` | FreeCAD parts library |
| `run_fem_analysis` | CalculiX FEM on an existing analysis |

Manufacturing drawings: import STEP, then drive TechDraw through
`execute_code` (page + orthographic views + export DXF/SVG/PDF).

## Updating the vendored addon

```bash
./install_freecad_mcp.sh --update-vendor   # re-fetch upstream addon into freecad_mcp/addon
./install_freecad_mcp.sh                   # re-install into FreeCAD Mod
```

Record the new commit hash in `THIRD_PARTY_NOTICE.md`.
