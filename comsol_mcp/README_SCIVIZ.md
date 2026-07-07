# comsol_mcp — headless COMSOL execution

Ported from the Flash-Physics-Twin project's `mcp/comsol_mcp` (the
comprehensive COMSOL execution server) into sci-viz-mcp, so that model
execution and figure production live in one repo. The visualization-only
companion is `../comsol_viz_mcp/`.

```
comsol_mcp  (this module)          comsol_viz_mcp
──────────────────────────         ─────────────────────────────
drives COMSOL via mph (Java API)   reads the HDF5/CSV exports
opens models, applies params,      renders APS/Nature-styled field
runs studies, exports fields/KPIs  maps, line cuts, mesh overlays
```

## What changed vs. the Flash-Physics-Twin original

- Runs directory comes from `COMSOL_MCP_RUNS_DIR` (default:
  `sci-viz-mcp/output/comsol_runs/`) instead of a hardcoded
  `results/runs` path inside Flash-Physics-Twin.
- Four previously unexposed backend capabilities are now MCP tools:
  `comsol_export_em_coil_fields`, `comsol_export_em_coil_kpis`,
  `comsol_export_coupled_fields`, `comsol_export_coupled_kpis`.
- Rendered PNGs get the Sci-Viz attribution footer
  (disable with `SCIVIZ_ATTRIBUTION=0`).

## Requirements

- COMSOL Multiphysics installed and licensed (tested with 6.4). Without a
  COMSOL license the server still starts, and `comsol_health` reports
  `degraded`; only the solver-side tools fail.
- `pip install mph h5py pyyaml` in the sci-viz-mcp venv.

## Tools (15)

| Tool | Description |
|------|-------------|
| `comsol_health` | mph install + template check; `start_client=true` launches COMSOL |
| `comsol_open_or_create_model` | Open `.mph` or copy a template into the run dir |
| `comsol_apply_inputs` | Apply YAML parameters (`geometry/ops/materials/chemistry.yaml`) |
| `comsol_build_geometry` / `comsol_mesh` | Geometry and mesh |
| `comsol_run_pipeline` / `comsol_run_study` | Execute studies (A→B→C→D or by id) |
| `comsol_export_fields` / `comsol_export_kpis` | HDF5 fields + JSON KPIs (incl. Flash ΔB/χ) |
| `comsol_export_em_coil_fields` / `comsol_export_em_coil_kpis` | AC/DC coil EM surrogate (B, E, Q_RF) |
| `comsol_export_coupled_fields` / `comsol_export_coupled_kpis` | Coupled EM + thermal + Flash physics |
| `comsol_render_png` | Export a COMSOL plot group to PNG (attribution-stamped) |
| `comsol_close_model` | Release model resources |

## Cursor MCP registration

```json
{
  "mcpServers": {
    "comsol_mcp": {
      "command": "<repo>/.venv/bin/python",
      "args": ["<repo>/comsol_mcp/comsol_mcp_server.py"],
      "cwd": "<repo>",
      "env": {
        "COMSOL_MCP_RUNS_DIR": "/path/to/your/runs",
        "COMSOL_MCP_DEFAULT_TEMPLATE": "/path/to/template.mph"
      },
      "transport": "stdio"
    }
  }
}
```

Both env vars are optional. `.mph` templates are NOT bundled here —
COMSOL models are binary and project-specific; save one from COMSOL
Desktop and pass `model_path`/`template_path`, or set
`COMSOL_MCP_DEFAULT_TEMPLATE`.

## Common failure

A `.mph` file that is actually a text placeholder (from a repo that
stores specs as text) will fail with *"model file is damaged or not
valid"*. `comsol_health` and `comsol_open_or_create_model` detect this
and tell you to save a real binary model from COMSOL Desktop.

## Design notes

The original design spec is kept as `comsol_mcp_design.md`. The Flash
physics closure (ΔB = k_soft·ΔG₀ − (nF·E_eff·r_act + W_ph + Δμ_chem),
χ = 1/(1+exp(ΔB/B_s))) and the PFR field schema in the export tools come
from the Flash-Physics-Twin project.
