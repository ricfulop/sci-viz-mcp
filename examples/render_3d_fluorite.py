#!/usr/bin/env python3
"""
High-quality 3D render of fluorite ZrO2 using OVITO Tachyon ray-tracer.

Builds a 3x3x3 supercell from CIF, applies CPK coloring and proper radii,
renders from multiple angles with ambient occlusion and anti-aliasing.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import ase.io
import ase.build

CIF_DIR = Path(__file__).parent.parent / "tests" / "sample_structures"
OUT_DIR = Path(__file__).parent
TMP_CIF = OUT_DIR / "_tmp_supercell.cif"

# Build supercell from CIF
atoms = ase.io.read(CIF_DIR / "fluorite_ZrO2.cif")
sc = atoms.repeat([3, 3, 3])
ase.io.write(str(TMP_CIF), sc, format="cif")
print(f"Supercell: {sc.get_chemical_formula()}, {len(sc)} atoms")

# OVITO rendering
from ovito.io import import_file
from ovito.vis import Viewport, TachyonRenderer
from ovito.modifiers import ExpressionSelectionModifier

pipeline = import_file(str(TMP_CIF))
data = pipeline.compute()

# Apply colors and radii via modifier (avoids shared-data mutability issue)
color_map = {"Zr": (0.29, 0.53, 0.78), "O": (0.91, 0.30, 0.24)}
radii_map = {"Zr": 0.9, "O": 0.55}

def apply_style(frame, data):
    import numpy as np
    ptypes = data.particles.particle_types
    if ptypes is None:
        return
    type_name = {t.id: t.name for t in ptypes.types}
    ids = np.array(ptypes)
    colors = np.ones((data.particles.count, 3)) * 0.5
    radii = np.ones(data.particles.count) * 0.5
    for tid, tname in type_name.items():
        mask = ids == tid
        if tname in color_map:
            colors[mask] = color_map[tname]
        if tname in radii_map:
            radii[mask] = radii_map[tname]
    data.particles_.create_property("Color", data=colors)
    data.particles_.create_property("Radius", data=radii)

pipeline.modifiers.append(apply_style)

pipeline.add_to_scene()

renderer = TachyonRenderer()
renderer.antialiasing_samples = 12
renderer.direct_light_intensity = 0.9
renderer.ambient_occlusion = True
renderer.ambient_occlusion_brightness = 0.8

views = [
    ("perspective_001", (0, 0, -1), Viewport.Type.Perspective, 45),
    ("perspective_110", (1, 1, -0.7), Viewport.Type.Perspective, 45),
    ("perspective_111", (1, 1, -1), Viewport.Type.Perspective, 45),
    ("ortho_001", (0, 0, -1), Viewport.Type.Ortho, 25),
    ("isometric", (1, 0.7, -0.5), Viewport.Type.Perspective, 40),
]

for name, direction, vtype, fov in views:
    vp = Viewport(type=vtype)
    vp.camera_dir = direction
    vp.fov = fov
    vp.zoom_all()

    out_path = str(OUT_DIR / f"3d_fluorite_{name}.png")
    vp.render_image(
        filename=out_path,
        size=(2400, 1800),
        renderer=renderer,
        background=(1.0, 1.0, 1.0),
    )
    print(f"Rendered: {out_path}")

pipeline.remove_from_scene()
TMP_CIF.unlink(missing_ok=True)
print("Done — 5 renders complete")
