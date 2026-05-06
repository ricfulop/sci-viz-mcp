# sci-viz-mcp

MCP servers for scientific visualization — crystal structures, atomistic rendering, 3D rendering, and COMSOL field visualization — with APS and Nature journal figure styles.

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
# 1. Install the Foundation MCP server + add-on
#    https://www.blender.org/lab/mcp-server/  (requires Blender 5.1+)
#    - drag the install link into Blender twice (adds repo, installs add-on)
#    - then enable the add-on and start the server inside Blender

# 2. Install the SciViz add-on into Blender 5.1 user extensions
cd /Users/ricfulop/voltivity/sci-viz-mcp
./install_sciviz_addon.sh                 # symlink (live editing)
# or  ./install_sciviz_addon.sh --copy     # one-shot copy

# 3. ASE / numpy in Blender's bundled Python (one-time)
/Applications/Blender.app/Contents/Resources/5.1/python/bin/python3.* \
    -m pip install ase numpy

# 4. In Blender, enable both add-ons and connect the MCP server.
```

The `~/.cursor/mcp.json` `blender` entry currently launches the community
`uvx blender-mcp` package because Cursor doesn't yet natively load `.mcpb`
bundles; it speaks the same TCP/9876 protocol the Foundation server uses,
so the SciViz add-on works through either transport. Migrate to the
Foundation server's stdio entry-point as soon as Cursor supports it
(no changes needed on the add-on side).

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
