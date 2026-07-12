# Contributing to sci-viz-mcp

Thanks for your interest! This repo is a collection of MCP servers for
scientific visualization and simulation. Contributions of new tools, new
telescope/crystal presets, bug fixes, and docs are all welcome.

## Getting set up

```bash
git clone https://github.com/<org>/sci-viz-mcp && cd sci-viz-mcp
./install.sh                 # or ./install.sh --minimal for Python-only
.venv/bin/python scripts/generate_mcp_config.py   # MCP registration JSON
```

## Repo layout

| Path | What it is |
|------|------------|
| `picogk_mcp/`, `crystal_mcp/`, `ovito_mcp/`, `comsol_mcp/`, `comsol_viz_mcp/`, `ray_optics_mcp/`, `physical_optics_mcp/`, `optical_design_mcp/`, `pixinsight_mcp/`, `freecad_mcp/` | One directory per MCP server (or CAD bridge) |
| `mcp_runtime.py`, `attribution.py`, `styles.py` | Shared helpers (stdio hygiene, output stamping, journal figure styles) |
| `preview/` | Live render-preview dashboard |
| `sciviz_blender_addon/` | Blender add-on registering `bpy.ops.sciviz.*` |
| `freecad_mcp/addon/` | Vendored FreeCADMCP workbench (neka-nat); install via `./install_freecad_mcp.sh` |
| `tests/`, `examples/`, `docs/` | Tests, example figure scripts, reference figures |

## Conventions

- **MCP servers** are plain-stdlib JSON-RPC over stdio (see any
  `*_mcp_server.py` for the pattern). Keep stdout JSON-only; log to stderr
  via `mcp_runtime.configure_stdio_logging()`.
- **Tool names** use underscores only (`crystal_render_lattice`), never dots.
- **Figures** must go through `styles.py` (`apply_aps_style()` etc.), colors
  from `OKABE_ITO`, sizes from the column-width helpers.
- **No absolute personal paths** in code or docs — use env vars or paths
  relative to the repo root.
- **Vendored code** goes in a subdirectory with its upstream LICENSE and an
  entry in `THIRD_PARTY_NOTICES.md`.
- **PicoGK source modules** are never copied into git. Update
  `picogk_mcp/stack.lock.json`, verify the upstream license, and test the
  exact commit through `scripts/sync_picogk_stack.py`.
- **Raw C# tools** must remain clearly marked as trusted-local execution.
  Keep each job in a child process and preserve cancellation/timeouts.

## Testing

```bash
.venv/bin/python tests/test_comsol_viz.py
.venv/bin/python tests/test_crystal.py
.venv/bin/python tests/test_picogk_mcp.py
MPLBACKEND=Agg .venv/bin/python -m pytest -q tests/test_physical_optics_mcp.py
MPLBACKEND=Agg .venv/bin/python -m pytest -q tests/test_optical_design_mcp.py
cd ray_optics_mcp && python3 validate_designs.py && python3 test_e2e.py
```

Native PicoGK tests require .NET 9 plus macOS ARM64 or Windows x64:

```bash
./install.sh --with-picogk
PICOGK_NATIVE_TESTS=1 .venv/bin/python tests/test_picogk_mcp.py
```

Servers that drive commercial software (COMSOL, PixInsight) degrade
gracefully when it's absent — `comsol_health` etc. must still respond.
Please keep that property.

## Pull requests

- One logical change per PR.
- Update the relevant module README and the tool tables in the top-level
  README when adding/renaming tools.
- Note any new third-party dependency in `THIRD_PARTY_NOTICES.md`.
