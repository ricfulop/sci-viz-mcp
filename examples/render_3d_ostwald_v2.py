#!/usr/bin/env python3
"""
3D Ostwald ripening — v2: vacancy-only rendering.

Show ONLY the V_O sites as bright spheres inside a wireframe cell.
Everything else removed for maximum visual clarity.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import ase.io
from ase import Atoms

CIF_DIR = Path(__file__).parent.parent / "tests" / "sample_structures"
OUT_DIR = Path(__file__).parent

atoms = ase.io.read(CIF_DIR / "fluorite_ZrO2.cif")
sc = atoms.repeat([5, 5, 5])
positions = sc.get_positions()
symbols = np.array(sc.get_chemical_symbols())
cell = sc.cell

o_indices = np.where(symbols == "O")[0]
o_positions = positions[o_indices]
n_o = len(o_indices)
print(f"Supercell: {len(sc)} atoms, {n_o} O sites")

np.random.seed(42)

def save_vacancies_only(vacancy_positions, name):
    """Save only vacancy positions as atoms in a CIF with the original cell."""
    if len(vacancy_positions) == 0:
        return None
    vac_atoms = Atoms(
        symbols=["O"] * len(vacancy_positions),
        positions=vacancy_positions,
        cell=cell,
        pbc=True,
    )
    path = OUT_DIR / f"_tmp_{name}.xyz"
    ase.io.write(str(path), vac_atoms, format="xyz")
    return str(path)

# Stage 1: Random sparse vacancies (8%)
mask1 = np.zeros(n_o, dtype=bool)
mask1[np.random.choice(n_o, size=int(n_o * 0.08), replace=False)] = True
f1 = save_vacancies_only(o_positions[mask1], "vac_stage1")
print(f"  Stage 1: {mask1.sum()} vacancies ({mask1.sum()/n_o*100:.0f}%)")

# Stage 2: Clustered — pick 12 seeds and grow spherical clusters
mask2 = np.zeros(n_o, dtype=bool)
seeds = o_positions[np.random.choice(n_o, size=12, replace=False)]
for seed in seeds:
    dists = np.linalg.norm(o_positions - seed, axis=1)
    mask2[dists < 4.5] = True
f2 = save_vacancies_only(o_positions[mask2], "vac_stage2")
print(f"  Stage 2: {mask2.sum()} vacancies ({mask2.sum()/n_o*100:.0f}%)")

# Stage 3: Percolating channels along [110]-type directions
mask3 = np.zeros(n_o, dtype=bool)
directions = [
    np.array([1, 1, 0]) / np.sqrt(2),
    np.array([1, -1, 0]) / np.sqrt(2),
    np.array([1, 0, 1]) / np.sqrt(2),
    np.array([0, 1, 1]) / np.sqrt(2),
]
for _ in range(6):
    start = o_positions[np.random.randint(n_o)]
    d = directions[np.random.randint(len(directions))]
    for t in np.linspace(0, 30, 200):
        point = start + t * d
        dists = np.linalg.norm(o_positions - point, axis=1)
        mask3[dists < 2.5] = True
    # Branches
    branch_sites = np.where(mask3)[0]
    if len(branch_sites) > 10:
        for bi in branch_sites[::6]:
            bd = d + np.random.randn(3) * 0.4
            bd /= np.linalg.norm(bd)
            bp = o_positions[bi]
            for t in np.linspace(0, 12, 60):
                point = bp + t * bd
                dists = np.linalg.norm(o_positions - point, axis=1)
                mask3[dists < 2.2] = True

f3 = save_vacancies_only(o_positions[mask3], "vac_stage3")
print(f"  Stage 3: {mask3.sum()} vacancies ({mask3.sum()/n_o*100:.0f}%)")

# ═══════════════════════════════════════════════════════════════════════════════
# OVITO rendering — vacancy sites only, bright orange
# ═══════════════════════════════════════════════════════════════════════════════

from ovito.io import import_file
from ovito.vis import Viewport, TachyonRenderer
from ovito.data import SimulationCell

def style_vac(frame, data):
    import numpy as np
    n = data.particles.count
    data.particles_.create_property("Color", data=np.tile([0.91, 0.30, 0.24], (n, 1)))
    data.particles_.create_property("Radius", data=np.full(n, 0.7))

renderer = TachyonRenderer()
renderer.antialiasing_samples = 16
renderer.direct_light_intensity = 0.85
renderer.ambient_occlusion = True
renderer.ambient_occlusion_brightness = 0.65

# Cell dimensions for manual cell overlay
cx, cy, cz = cell[0, 0], cell[1, 1], cell[2, 2]

stages = [
    ("stage1_nucleation", f1),
    ("stage2_ripening", f2),
    ("stage3_condensation", f3),
]

for name, xyz_path in stages:
    pipeline = import_file(xyz_path)
    pipeline.modifiers.append(style_vac)
    
    # Set simulation cell on source data (XYZ doesn't carry cell info)
    src_data = pipeline.source.data
    if src_data.cell is None:
        from ovito.data import SimulationCell
        cell_obj = SimulationCell()
        cell_obj.matrix = np.array([
            [cx, 0, 0, 0],
            [0, cy, 0, 0],
            [0, 0, cz, 0],
        ], dtype=float)
        cell_obj.pbc = (True, True, True)
        cell_obj.vis.enabled = True
        cell_obj.vis.line_width = 0.5
        cell_obj.vis.rendering_color = (0.3, 0.3, 0.3)
        src_data.objects.append(cell_obj)
    else:
        src_data.cell_.vis.enabled = True
    pipeline.add_to_scene()
    
    # Orthographic from slight angle — clean, not confusing
    vp = Viewport(type=Viewport.Type.Ortho)
    vp.camera_dir = (2, 1.5, -1)
    vp.fov = max(cx, cy, cz) * 1.3
    vp.zoom_all()
    
    out = str(OUT_DIR / f"3d_ostwald_v2_{name}.png")
    vp.render_image(
        filename=out,
        size=(2000, 1500),
        renderer=renderer,
        background=(1.0, 1.0, 1.0),
    )
    print(f"Rendered: {out}")
    pipeline.remove_from_scene()

# Cleanup
for _, p in stages:
    Path(p).unlink(missing_ok=True)

print("Done")
