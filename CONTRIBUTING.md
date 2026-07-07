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
| `crystal_mcp/`, `ovito_mcp/`, `comsol_mcp/`, `comsol_viz_mcp/`, `ray_optics_mcp/`, `pixinsight_mcp/` | One directory per MCP server |
| `mcp_runtime.py`, `attribution.py`, `styles.py` | Shared helpers (stdio hygiene, output stamping, journal figure styles) |
| `preview/` | Live render-preview dashboard |
| `sciviz_blender_addon/` | Blender add-on registering `bpy.ops.sciviz.*` |
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

## Testing

```bash
.venv/bin/python tests/test_comsol_viz.py
.venv/bin/python tests/test_crystal.py
cd ray_optics_mcp && python3 validate_designs.py && python3 test_e2e.py
```

Servers that drive commercial software (COMSOL, PixInsight) degrade
gracefully when it's absent — `comsol_health` etc. must still respond.
Please keep that property.

## Pull requests

- One logical change per PR.
- Update the relevant module README and the tool tables in the top-level
  README when adding/renaming tools.
- Note any new third-party dependency in `THIRD_PARTY_NOTICES.md`.
