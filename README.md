# sci-viz-mcp

MCP servers for scientific visualization — crystal structures, atomistic rendering, 3D rendering, and COMSOL field visualization — with APS, Nature, and Science journal figure styles.

## Architecture

```
Cursor IDE (any chat, any repo)
  │
  ├── crystal_mcp ──── ASE + pymatgen ──── lattice diagrams, TikZ, defects
  ├── ovito_mcp ────── OVITO Python API ── atomistic rendering (Tachyon)
  ├── blender ──────── official Blender ── stdio MCP ⇄ TCP :9876 ⇄ Blender
  │                    Foundation MCP        add-on (sciviz_blender_addon
  │                    server                registers bpy.ops.sciviz.*)
  ├── comsol_viz_mcp ─ matplotlib ──────── COMSOL field maps, line cuts
  │
  ├── styles.py ────── APS / Nature / Science rcParams, Okabe-Ito, column widths
  └── science-figure-style/ ── AAAS figure spec (SKILL.md) + example_figure.py
```

All servers are registered globally in `~/.cursor/mcp.json` and available in every Cursor chat regardless of workspace.

## Servers

### crystal_mcp (9 tools)
Replaces VESTA with a programmatic, reproducible workflow.

| Tool | Description |
|------|-------------|
| `crystal_import_structure` | Load CIF, POSCAR, XYZ |
| `crystal_build_supercell` | Build NxMxL supercell |
| `crystal_create_defect` | Vacancy, substitution, interstitial |
| `crystal_get_symmetry` | Space group, Wyckoff positions |
| `crystal_render_lattice` | 2D projection → PDF/PNG/SVG |
| `crystal_render_unit_cell` | Annotated unit cell with bond lengths |
| `crystal_compare_structures` | Side-by-side structural comparison |
| `crystal_export_tikz` | LaTeX-ready TikZ code |
| `crystal_list_structures` | Show loaded structures |

### ovito_mcp (9 tools)
Headless atomistic visualization via OVITO Python API.

| Tool | Description |
|------|-------------|
| `ovito_import_data` | Load CIF, LAMMPS, POSCAR, XYZ, GSD |
| `ovito_add_modifier` | Coordination, Voronoi, CNA, color coding, etc. |
| `ovito_set_visual_style` | Particle colors, radii, cell visibility |
| `ovito_set_camera` | Ortho/perspective, direction, FOV |
| `ovito_render_image` | Tachyon ray-traced PNG/TIFF |
| `ovito_render_animation` | Frame sequence for simulations |
| `ovito_compute_property` | Extract RDF, coordination, per-atom data |
| `ovito_pipeline_status` | Inspect pipeline state |
| `ovito_list_pipelines` | List active pipelines |

### blender (official Blender Foundation MCP server + SciViz add-on)
Photorealistic 3D rendering via Blender + Cycles. Refactored in May 2026 to
use the [official Blender Foundation MCP server](https://www.blender.org/lab/mcp-server/)
released by the Blender devs in partnership with Anthropic, instead of a
custom socket protocol.

```
Cursor ──MCP/stdio──▶ blender-mcp ──TCP :9876──▶ Blender (5.1+)
                                                  ├── Foundation MCP add-on (transport)
                                                  └── SciViz add-on (sciviz_blender_addon/)
                                                        registers bpy.ops.sciviz.*
```

Science vocabulary lives inside Blender as proper operators, so it persists
across sessions, shows up as buttons in the SciViz N-panel, and is callable
from any MCP client (Cursor, Claude Desktop, Claude Code, ...) by writing
one-line Python through the Foundation server's execute-Python surface.

**SciViz operators (registered by `sciviz_blender_addon/`):**

| Operator | Description |
|----------|-------------|
| `bpy.ops.sciviz.import_crystal(filepath=...)` | CIF / POSCAR / XYZ → ball-and-stick with CPK materials. Uses ASE if installed in Blender's Python, falls back to pymatgen. |
| `bpy.ops.sciviz.apply_preset(preset=...)` | `WHITE_CLEAN` / `SOFT_SHADOW` / `PERSPECTIVE_DEPTH` / `DARK_PRESENTATION` |
| `bpy.ops.sciviz.render_hq(filepath=..., width=..., height=..., samples=...)` | Cycles render with 16-bit PNG output and live-preview ping |
| `bpy.ops.sciviz.add_annotation_3d(text=..., location_x=..., ...)` | 3D text label, optionally parented to the Crystal collection |

**Setup (one-time):**

```bash
# 1. Install the Foundation MCP add-on inside Blender 5.1+.
#    Open https://www.blender.org/lab/mcp-server/ and drag the install
#    link into Blender twice: first adds the lab.blender.org repository,
#    second installs the add-on. Enable it in Edit > Preferences > Add-ons.

# 2. Install the Foundation MCP *server* (the stdio bridge between
#    Cursor and Blender). Clones the source repo and pip-installs into
#    ./blender_mcp_foundation/.venv .
cd /Users/ricfulop/voltivity/sci-viz-mcp
./install_blender_foundation_mcp.sh

# 3. Install the SciViz add-on into Blender's user extensions
./install_sciviz_addon.sh                 # symlink (live editing)
# or  ./install_sciviz_addon.sh --copy     # one-shot copy

# 4. ASE / numpy in Blender's bundled Python (one-time)
/Applications/Blender.app/Contents/Resources/5.1/python/bin/python3.* \
    -m pip install ase numpy

# 5. Drop the snippet from step 2 into ~/.cursor/mcp.json under the
#    `blender` key, then reload Cursor's MCP servers.

# 6. In Blender, the BlenderMCP sidebar tab (View3D > N) shows a
#    "Connect" / status indicator. Once connected, calls from Cursor
#    flow through the Foundation server into Blender's bpy.
```

The Cursor → Blender path is now:

```
Cursor ─stdio─▶ blender_mcp_foundation/.venv/bin/blender-mcp
                       │
                  TCP :9876
                       ▼
               Blender 5.1+ with
                  ├── Foundation MCP add-on (lab.blender.org repo)
                  └── SciViz add-on (sciviz_blender_addon/)
                        registers bpy.ops.sciviz.*
```

Both server and add-on come from the Blender Foundation, so the protocol
matches end-to-end. The community `uvx blender-mcp` (ahujasid) used to
work in earlier setups but its command vocabulary disagrees with the
Foundation add-on's, so don't mix them.

### comsol_mcp (11 tools, Flash-Physics-Twin)
Headless COMSOL control via `mph` (Java API). Registered in `~/.cursor/mcp.json` with cwd `Flash-Physics-Twin`.

| Tool | Description |
|------|-------------|
| `comsol_health` | mph install + template check (`start_client=true` launches COMSOL) |
| `comsol_open_or_create_model` | Open `.mph` or copy template into run dir |
| `comsol_apply_inputs` | Apply YAML inputs from run directory |
| `comsol_build_geometry` / `comsol_mesh` | Geometry and mesh |
| `comsol_run_pipeline` / `comsol_run_study` | Execute studies |
| `comsol_export_fields` / `comsol_export_kpis` | HDF5 + JSON outputs |
| `comsol_render_png` / `comsol_close_model` | Plot export and cleanup |

**Common failure:** `templates/pfr_coil_acdc_axisym.mph` in git is a **text spec placeholder**, not a binary model. Save a real `.mph` from COMSOL Desktop and pass `model_path`, or set `COMSOL_MCP_DEFAULT_TEMPLATE` in `mcp.json` to that file.

### comsol_viz_mcp (7 tools)
Publication-quality visualization of COMSOL field exports.

| Tool | Description |
|------|-------------|
| `comsol_viz_health` | Matplotlib/output-dir readiness check |
| `comsol_viz_load_field` | Load HDF5/CSV field data from COMSOL exports |
| `comsol_viz_render_field_map` | 2D field map (temperature, E-field, etc.) |
| `comsol_viz_render_line_cut` | 1D line cut through field data |
| `comsol_viz_render_mesh` | Mesh visualization |
| `comsol_viz_list_datasets` | List loaded field datasets |
| `comsol_viz_get_field_stats` | Min/max/mean of field data |

## Live Preview Dashboard

Every render from any MCP server (crystal, OVITO, Blender, COMSOL) appears in
a browser-based live preview dashboard in real time.

```
MCP servers ──POST /api/render──▶ preview server ──WebSocket──▶ browser dashboard
```

**Auto-launch:** The first time any MCP tool produces a render, the preview
server starts automatically and opens your browser. No manual setup needed.

**Manual launch:** Or start it yourself:

```bash
cd /Users/ricfulop/voltivity/sci-viz-mcp
source .venv/bin/activate
python -m preview.server
```

Dashboard → [http://localhost:8765](http://localhost:8765)

Features:
- Real-time image/PDF preview as renders complete
- History strip with thumbnails — click to revisit any render
- Metadata panel showing tool name, server, parameters, and file path
- Keyboard navigation: `←` / `→` to browse history, `Space` to jump to latest
- Auto-reconnecting WebSocket — survives network hiccups
- Dark theme optimized for extended use

## Figure Styles

```python
from styles import (
    apply_aps_style, apply_nature_style, apply_science_style,
    OKABE_ITO, aps_double, nature_single, science_double,
    label_science_panel, save_science_figure,
)

apply_aps_style()                    # PRL/PRX/PRB: serif, 10pt, inward ticks, 600 DPI
apply_nature_style()                 # Nature/NatComms: sans-serif, 7pt, outward ticks, 300 DPI
apply_science_style()                # Science/AAAS: sans-serif, 7pt, no minor ticks, 300 DPI
apply_aps_style(use_latex=True)      # LaTeX + Computer Modern
apply_aps_large_style()              # 22pt for 0.48\textwidth panels

fig, ax = plt.subplots(figsize=aps_double())       # 6.75 x 3.2 in
fig, ax = plt.subplots(figsize=nature_single())      # 3.5 x 2.625 in (89 mm)
fig, ax = plt.subplots(figsize=science_double())     # 4.76 x 3.0 in (12.1 cm)
```

Science figure guide: `science-figure-style/SKILL.md`. Example: `python science-figure-style/example_figure.py`.

## Full Pipeline (COMSOL → figure)

```
comsol_mcp                         sci-viz-mcp
──────────                         ───────────
comsol_open_or_create_model  ──┐
comsol_apply_inputs            │
comsol_run_study               │
comsol_export_fields ──────────┼──→ comsol_viz_load_field
                               │    comsol_viz_render_field_map (APS/Nature style)
comsol_export_kpis ────────────┘    comsol_viz_render_line_cut
```

**Troubleshooting**

| Symptom | Likely cause | Fix |
|---------|----------------|-----|
| MCP server red / JSON parse errors on `comsol_viz_mcp` | Matplotlib wrote warnings to stdout | Reload MCP after update; `MPLCONFIGDIR` is set in `mcp.json` |
| `model file is damaged or not valid` | Placeholder `.mph` in repo | Use `comsol_health` then pass `model_path` to a real binary `.mph` |
| `mph not installed` | Wrong Python venv | Use `Flash-Physics-Twin/.venv/bin/python` from `mcp.json` |
| Viz works, solve does not | COMSOL not licensed / not running | Call `comsol_health` with `start_client: true` |
| Tools filtered / naming warnings in Cursor | Dotted names (`comsol.mesh`) | Reload MCP — tools now use underscores (`comsol_mesh`) |

```bash
# Quick smoke tests
cd /Users/ricfulop/voltivity/sci-viz-mcp && .venv/bin/python tests/test_comsol_viz.py
```

## Benchmark: Highly-Cited Crystal Structure Figures

Design conventions extracted from the most-cited papers using lattice structure figures, identified via [scite.ai](https://scite.ai) Smart Citation analysis.

### Reference papers

| Citations | Paper | Journal | Figure techniques |
|-----------|-------|---------|-------------------|
| 23,838 | Momma & Izumi, [VESTA 3](https://doi.org/10.1107/s0021889811038970) (2011) | J. Appl. Crystallogr. | Polyhedral + ball-and-stick hybrid, thermal ellipsoids, isosurfaces — the standard |
| 2,663 | Saparov & Mitzi, [Organic-Inorganic Perovskites](https://doi.org/10.1021/acs.chemrev.5b00715) (2016) | Chem. Rev. | Skeletal + polyhedral combined views, dimensionality slicing schematics |
| 2,327 | Adler, [SOFC Cathodes](https://doi.org/10.1021/cr020724o) (2004) | Chem. Rev. | Polyhedral + vacancy hopping arrows overlaid on structure |
| 1,410 | Zheng et al., [Nanostructured WO₃](https://doi.org/10.1002/adfm.201002477) (2011) | Adv. Funct. Mater. | Polyhedral tilt representations for 6 crystal phases, phase transformation sequences |
| 1,077 | Tsunekawa et al., [CeO₂ nanocrystals](https://doi.org/10.1063/1.2061873) (2005) | Appl. Phys. Lett. | Fluorite lattice parameter vs. size with structural schematic |
| 1,044 | Volonakis et al., [Cs₂InAgCl₆](https://doi.org/10.1021/acs.jpclett.6b02682) (2017) | JPCL | Ball-and-stick Fm-3m with alternating octahedra, widely reproduced |
| 1,018 | Adachi & Imanaka, [Binary Rare Earth Oxides](https://doi.org/10.1021/cr940055h) (1998) | Chem. Rev. | Fluorite vacancy superstructure + diffraction evidence |
| 882 | Li et al., [Na₀.₅Bi₀.₅TiO₃](https://doi.org/10.1038/nmat3782) (2013) | Nature Mater. | Side-by-side parent/child phases, vacancy channels, + electron diffraction |
| 647 | Foster et al., [Vacancies in hafnia](https://doi.org/10.1103/physrevb.65.174117) (2002) | Phys. Rev. B | Defect site ball-and-stick with charge density overlay |

### Key conventions from highly-cited papers

| Convention | Description | Implemented? |
|------------|-------------|:---:|
| Polyhedral + ball hybrid | Show coordination polyhedra AND individual atoms | Planned |
| Phase transformation arrows | Side-by-side parent → child with bold arrow | Yes |
| Vacancy channels colored | Highlight vacancy-rich planes in a distinct color | Yes |
| Diffraction evidence inset | Small SAED/XRD pattern proving structural claim | Yes |
| Bond-length annotations | Explicit angstrom values on key bonds | Yes |
| Color-coded Wyckoff sites | Different colors per crystallographic site | Planned |
| 3D perspective with depth | Slight perspective or isometric view showing 3D character | Planned |
| Derivation box | Math box showing key calculation leading to prediction | Yes |

## Setup

```bash
cd /Users/ricfulop/voltivity/sci-viz-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install ase pymatgen matplotlib numpy spglib ovito phonopy h5py aiohttp
```

Servers are registered in `~/.cursor/mcp.json` — restart Cursor to activate.

## Sample Structures

- `tests/sample_structures/fluorite_ZrO2.cif` — Fm-3m (#225), a = 5.145 Å
- `tests/sample_structures/rocksalt_ZrO.cif` — Fm-3m (#225), a = 4.620 Å
