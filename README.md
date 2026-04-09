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
pip install ase pymatgen matplotlib numpy spglib ovito phonopy h5py
```

Servers are registered in `~/.cursor/mcp.json` — restart Cursor to activate.

## Sample Structures

- `tests/sample_structures/fluorite_ZrO2.cif` — Fm-3m (#225), a = 5.145 Å
- `tests/sample_structures/rocksalt_ZrO.cif` — Fm-3m (#225), a = 4.620 Å
