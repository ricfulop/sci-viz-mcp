# sci-viz-mcp

MCP servers for scientific visualization — crystal structures, atomistic rendering, 3D rendering, and COMSOL field visualization — with APS and Nature journal figure styles.

## Architecture

```
Cursor IDE (any chat, any repo)
  │
  ├── crystal_mcp ──── ASE + pymatgen ──── lattice diagrams, TikZ, defects
  ├── ovito_mcp ────── OVITO Python API ── atomistic rendering (Tachyon)
  ├── blender_mcp ──── Blender 4.x ────── photorealistic 3D (Cycles)
  ├── comsol_viz_mcp ─ matplotlib ──────── COMSOL field maps, line cuts
  │
  └── styles.py ────── APS / Nature rcParams, Okabe-Ito palette, column widths
```

All servers are registered globally in `~/.cursor/mcp.json` and available in every Cursor chat regardless of workspace.

## Servers

### crystal_mcp (9 tools)
Replaces VESTA with a programmatic, reproducible workflow.

| Tool | Description |
|------|-------------|
| `crystal.import_structure` | Load CIF, POSCAR, XYZ |
| `crystal.build_supercell` | Build NxMxL supercell |
| `crystal.create_defect` | Vacancy, substitution, interstitial |
| `crystal.get_symmetry` | Space group, Wyckoff positions |
| `crystal.render_lattice` | 2D projection → PDF/PNG/SVG |
| `crystal.render_unit_cell` | Annotated unit cell with bond lengths |
| `crystal.compare_structures` | Side-by-side structural comparison |
| `crystal.export_tikz` | LaTeX-ready TikZ code |
| `crystal.list_structures` | Show loaded structures |

### ovito_mcp (9 tools)
Headless atomistic visualization via OVITO Python API.

| Tool | Description |
|------|-------------|
| `ovito.import_data` | Load CIF, LAMMPS, POSCAR, XYZ, GSD |
| `ovito.add_modifier` | Coordination, Voronoi, CNA, color coding, etc. |
| `ovito.set_visual_style` | Particle colors, radii, cell visibility |
| `ovito.set_camera` | Ortho/perspective, direction, FOV |
| `ovito.render_image` | Tachyon ray-traced PNG/TIFF |
| `ovito.render_animation` | Frame sequence for simulations |
| `ovito.compute_property` | Extract RDF, coordination, per-atom data |
| `ovito.pipeline_status` | Inspect pipeline state |
| `ovito.list_pipelines` | List active pipelines |

### blender_mcp (7 tools)
Photorealistic 3D rendering via Blender + Cycles.

| Tool | Description |
|------|-------------|
| `blender.ping` | Check Blender connectivity |
| `blender.import_crystal` | CIF → ball-and-stick with CPK materials |
| `blender.set_science_preset` | white_clean, soft_shadow, perspective_depth, dark_presentation |
| `blender.render_hq` | Cycles render at specified resolution |
| `blender.add_annotation_3d` | 3D text labels |
| `blender.execute_code` | Arbitrary Blender Python |
| `blender.get_scene_info` | Scene inspection |

### comsol_viz_mcp (6 tools)
Publication-quality visualization of COMSOL field exports.

| Tool | Description |
|------|-------------|
| `comsol_viz.load_field` | Load HDF5/CSV field data from COMSOL exports |
| `comsol_viz.render_field_map` | 2D field map (temperature, E-field, etc.) |
| `comsol_viz.render_line_cut` | 1D line cut through field data |
| `comsol_viz.render_mesh` | Mesh visualization |
| `comsol_viz.list_datasets` | List loaded field datasets |
| `comsol_viz.get_field_stats` | Min/max/mean of field data |

## Figure Styles

```python
from styles import apply_aps_style, apply_nature_style, OKABE_ITO, aps_double, nature_single

apply_aps_style()                    # PRL/PRX/PRB: serif, 10pt, inward ticks, 600 DPI
apply_nature_style()                 # Nature/NatComms: sans-serif, 7pt, outward ticks, 300 DPI
apply_aps_style(use_latex=True)      # LaTeX + Computer Modern
apply_aps_large_style()              # 22pt for 0.48\textwidth panels

fig, ax = plt.subplots(figsize=aps_double())      # 6.75 x 3.2 in
fig, ax = plt.subplots(figsize=nature_single())    # 3.5 x 2.625 in (89 mm)
```

## Full Pipeline (COMSOL → figure)

```
comsol_mcp                         sci-viz-mcp
──────────                         ───────────
comsol.open_or_create_model  ──┐
comsol.apply_inputs            │
comsol.run_study               │
comsol.export_fields ──────────┼──→ comsol_viz.load_field
                               │    comsol_viz.render_field_map (APS/Nature style)
comsol.export_kpis ────────────┘    comsol_viz.render_line_cut
```

## Setup

```bash
cd /Users/ricfulop/voltivity/sci-viz-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install ase pymatgen matplotlib numpy spglib ovito phonopy h5py
```

Servers are registered in `~/.cursor/mcp.json` — restart Cursor to activate.

## Sample Structures

- `tests/sample_structures/fluorite_ZrO2.cif` — Fm-3m (#225), a = 5.145 Å
- `tests/sample_structures/rocksalt_ZrO.cif` — Fm-3m (#225), a = 4.620 Å
