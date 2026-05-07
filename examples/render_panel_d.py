#!/usr/bin/env python3
"""
Panel D — Ostwald Ripening: stage-specific renders with explicit scale separation.

Stage 1 and Stage 2 are compact seed/coarsening views.
Stage 3 is rendered from a dedicated wide supercell so the dendritic network
reads as a larger-scale vein morphology instead of a blown-up crop.
"""

import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import ase.io
from ase import Atoms

ROOT = Path(__file__).parent.parent.resolve()
CIF_DIR = ROOT / "tests" / "sample_structures"
OUT_DIR = ROOT / "output"
OUT_DIR.mkdir(exist_ok=True)

CYAN = [0.0, 0.75, 0.90]
ZR_GHOST = [0.15, 0.40, 0.82]
O_GHOST = [0.88, 0.22, 0.18]

atoms = ase.io.read(str(CIF_DIR / "fluorite_ZrO2.cif"))
a_f = 5.145
wavelength = 0.96 * a_f

# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: Build supercell and save combined XYZ (full lattice + bright vacancies)
# ═══════════════════════════════════════════════════════════════════════════════

def build_stage(repeats, vacancy_mask_fn, name):
    """Build a supercell, mark vacancies, save as XYZ with type IDs.

    Returns path and cell dims. Atom types:
      type 1 = Zr (ghost)
      type 2 = O occupied (ghost)
      type 3 = O vacancy (bright cyan)
    """
    sc = atoms.repeat(repeats)
    pos = sc.get_positions()
    sym = np.array(sc.get_chemical_symbols())
    cell = sc.cell
    cx, cy, cz = float(cell[0, 0]), float(cell[1, 1]), float(cell[2, 2])

    o_mask = sym == "O"
    o_pos = pos[o_mask]
    vac_flags = vacancy_mask_fn(o_pos, cx, cy, cz)

    # Build combined position array with type labels
    all_pos = []
    all_types = []

    # Zr atoms (type 1)
    zr_pos = pos[sym == "Zr"]
    for p in zr_pos:
        all_pos.append(p)
        all_types.append(1)

    # O occupied (type 2) and O vacancy (type 3)
    for i, p in enumerate(o_pos):
        all_pos.append(p)
        all_types.append(3 if vac_flags[i] else 2)

    all_pos = np.array(all_pos)
    all_types = np.array(all_types)

    n_vac = np.sum(vac_flags)
    print(f"  {name}: {n_vac} vacancies / {len(o_pos)} O sites ({n_vac/len(o_pos)*100:.0f}%)")

    # Save as extended XYZ with type property
    path = str(OUT_DIR / f"_tmp_{name}.xyz")
    with open(path, "w") as f:
        n = len(all_pos)
        f.write(f"{n}\n")
        f.write(f'Lattice="{cx} 0 0 0 {cy} 0 0 0 {cz}" '
                f'Properties=species:S:1:pos:R:3:type:I:1\n')
        for p, t in zip(all_pos, all_types):
            f.write(f"X {p[0]:.4f} {p[1]:.4f} {p[2]:.4f} {t}\n")

    return path, cx, cy, cz, all_types


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════

np.random.seed(42)

def _z_slab(o_pos, cz, z_lo_frac, z_hi_frac):
    return ((o_pos[:, 2] > z_lo_frac * cz) &
            (o_pos[:, 2] < z_hi_frac * cz))


def _paint_segment_mask(mask, points, p0, p1, radius):
    """Fill points lying within `radius` of a line segment."""
    seg = p1 - p0
    seg_norm2 = float(np.dot(seg, seg))
    if seg_norm2 < 1e-10:
        return
    rel = points - p0
    t = np.clip((rel @ seg) / seg_norm2, 0.0, 1.0)
    closest = p0 + t[:, None] * seg
    d2 = np.sum((points - closest) ** 2, axis=1)
    mask[d2 <= radius ** 2] = True


def _paint_sphere_mask(mask, points, center, radius):
    d2 = np.sum((points - center) ** 2, axis=1)
    mask[d2 <= radius ** 2] = True


# Stage 1: discrete seed array at antinode intersections in a narrow
# bottom slab. This reads as the commensurate nucleation template rather
# than a continuous slab.
def vac_stage1(o_pos, cx, cy, cz):
    phase_x = np.abs(np.sin(2 * np.pi * o_pos[:, 0] / wavelength))
    phase_y = np.abs(np.sin(2 * np.pi * o_pos[:, 1] / wavelength))
    slab = _z_slab(o_pos, cz, 0.05, 0.22)
    return (phase_x > 0.92) & (phase_y > 0.45) & slab


f1, cx1, cy1, cz1, types1 = build_stage([5, 5, 3], vac_stage1, "d_s1")


# Stage 2: LSW coarsening of the commensurate seeds into thicker bottom
# clusters occupying the lower third of the cell.
def vac_stage2(o_pos, cx, cy, cz):
    slab = _z_slab(o_pos, cz, 0.04, 0.40)
    seed_mask = vac_stage1(o_pos, cx, cy, cz)
    mask = seed_mask.copy()
    seed_idx = np.where(seed_mask)[0]
    if len(seed_idx) > 0:
        seeds = seed_idx[np.random.choice(
            len(seed_idx),
            size=min(24, len(seed_idx)),
            replace=False)]
        for s in seeds:
            dists = np.linalg.norm(o_pos - o_pos[s], axis=1)
            mask[(dists < 4.8) & slab] = True
    return mask


f2, cx2, cy2, cz2, types2 = build_stage([7, 7, 4], vac_stage2, "d_s2")


# Stage 3: sparse interconnected dendritic channels spanning the volume.
# The morphology should read as ~200 nm veins rather than a uniform blob.
def vac_stage3(o_pos, cx, cy, cz):
    mask = np.zeros(len(o_pos), dtype=bool)
    directions = [
        np.array([1.0, 1.0, 0.3]),
        np.array([1.0, -1.0, 0.4]),
        np.array([0.7, 0.2, 1.0]),
        np.array([0.2, 0.8, 1.0]),
        np.array([1.0, 0.3, -0.5]),
        np.array([0.4, 1.0, -0.3]),
    ]
    directions = [d / np.linalg.norm(d) for d in directions]

    seed_region = _z_slab(o_pos, cz, 0.12, 0.42)
    phase_x = np.abs(np.sin(2 * np.pi * o_pos[:, 0] / wavelength))
    phase_y = np.abs(np.sin(2 * np.pi * o_pos[:, 1] / wavelength))
    seed_candidates = np.where(seed_region & (phase_x > 0.62) & (phase_y > 0.30))[0]
    if len(seed_candidates) == 0:
        seed_candidates = np.where(seed_region)[0]

    span = max(cx, cy, cz)
    trunk_len = 0.72 * span
    branch_len = 0.34 * span
    twig_len = 0.18 * span
    trunk_radius = 4.85
    branch_radius = 3.80
    twig_radius = 2.85
    node_radius = 4.70

    chosen = seed_candidates[np.linspace(
        0, len(seed_candidates) - 1,
        min(10, len(seed_candidates)), dtype=int)]

    for i, seed in enumerate(chosen):
        start = o_pos[seed]
        trunk_dir = directions[i % len(directions)]
        trunk_end = start + trunk_len * trunk_dir
        _paint_segment_mask(mask, o_pos, start, trunk_end, trunk_radius)
        _paint_sphere_mask(mask, o_pos, start, node_radius)

        # Branches at downstream junctions to create a vein-like network.
        for frac, j in [(0.18, 1), (0.34, 2), (0.50, 3), (0.66, 1), (0.82, 2)]:
            t0 = frac * trunk_len
            branch_origin = start + t0 * trunk_dir
            _paint_sphere_mask(mask, o_pos, branch_origin, node_radius)
            branch_dir = directions[(i + j) % len(directions)]
            branch_dir = branch_dir + np.random.randn(3) * 0.10
            branch_dir /= np.linalg.norm(branch_dir)
            branch_end = branch_origin + branch_len * branch_dir
            _paint_segment_mask(mask, o_pos, branch_origin, branch_end, branch_radius)

            twig_origin = branch_origin + 0.55 * branch_len * branch_dir
            twig_dir = directions[(i + j + 2) % len(directions)] + np.random.randn(3) * 0.12
            twig_dir /= np.linalg.norm(twig_dir)
            twig_end = twig_origin + twig_len * twig_dir
            _paint_segment_mask(mask, o_pos, twig_origin, twig_end, twig_radius)
    return mask


f3, cx3, cy3, cz3, types3 = build_stage([14, 10, 6], vac_stage3, "d_s3")


# ═══════════════════════════════════════════════════════════════════════════════
# OVITO RENDERING
# ═══════════════════════════════════════════════════════════════════════════════

from ovito.io import import_file
from ovito.vis import Viewport, TachyonRenderer
from ovito.data import SimulationCell

renderer = TachyonRenderer()
renderer.antialiasing_samples = 16
renderer.direct_light_intensity = 0.85
renderer.ambient_occlusion = True
renderer.ambient_occlusion_brightness = 0.65

WHITE_BG = (1.0, 1.0, 1.0)


def attach_cell(pipeline, cx, cy, cz):
    src = pipeline.source.data
    if src.cell is None:
        cell_obj = SimulationCell()
        cell_obj.matrix = np.array([
            [cx, 0, 0, 0],
            [0, cy, 0, 0],
            [0, 0, cz, 0],
        ], dtype=float)
        cell_obj.pbc = (True, True, True)
        cell_obj.vis.enabled = True
        cell_obj.vis.line_width = 0.6
        cell_obj.vis.rendering_color = (0.6, 0.6, 0.6)
        src.objects.append(cell_obj)


def style_with_ghosts(types_arr):
    """Color by type: Zr ghost (blue, tiny), O ghost (red, tiny), vacancy (cyan, bright).
    types_arr is passed in from the build step since XYZ doesn't preserve custom props.
    """
    types_copy = types_arr.copy()

    def _style(frame, data):
        n = data.particles.count
        if n != len(types_copy):
            return
        colors = np.zeros((n, 3))
        radii = np.zeros(n)
        transp = np.zeros(n)
        for i in range(n):
            t = types_copy[i]
            if t == 1:      # Zr — saturated blue
                colors[i] = ZR_GHOST
                radii[i] = 0.50
                transp[i] = 0.38
            elif t == 2:    # O — saturated red
                colors[i] = O_GHOST
                radii[i] = 0.34
                transp[i] = 0.42
            else:           # vacancy — bright cyan
                colors[i] = CYAN
                radii[i] = 0.76
                transp[i] = 0.0
        data.particles_.create_property("Color", data=colors)
        data.particles_.create_property("Radius", data=radii)
        data.particles_.create_property("Transparency", data=transp)
    return _style


def render_to(pipeline, out_path, cell_max, size=(2000, 2100), zoom_factor=0.78):
    vp = Viewport(type=Viewport.Type.Ortho)
    vp.camera_dir = (2, 1.5, -1)
    vp.fov = cell_max * 1.3
    pipeline.add_to_scene()
    vp.zoom_all()
    vp.fov *= zoom_factor
    vp.render_image(filename=out_path, size=size,
                    renderer=renderer, background=WHITE_BG)
    pipeline.remove_from_scene()
    print(f"  Rendered: {out_path}")


# ── Render all 3 stages ──────────────────────────────────────────────────────

for xyz, cx, cy, cz, types, name, size, zoom in [
    (f1, cx1, cy1, cz1, types1, "panel_d_stage1", (1500, 1450), 0.92),
    (f2, cx2, cy2, cz2, types2, "panel_d_stage2", (1650, 1450), 0.90),
    (f3, cx3, cy3, cz3, types3, "panel_d_stage3", (3000, 1650), 0.90),
]:
    p = import_file(xyz)
    attach_cell(p, cx, cy, cz)
    p.modifiers.append(style_with_ghosts(types))
    render_to(p, str(OUT_DIR / f"{name}.png"), max(cx, cy, cz),
              size=size, zoom_factor=zoom)


# ═══════════════════════════════════════════════════════════════════════════════
# COMPOSITE TRIPTYCH
# ═══════════════════════════════════════════════════════════════════════════════

from PIL import Image

paths = [OUT_DIR / f"panel_d_stage{i}.png" for i in [1, 2, 3]]
imgs = [Image.open(str(p)) for p in paths]

# Keep a simple horizontal strip for quick inspection; the final publication
# layout is assembled in compose_fig10_hybrid.py from the individual stage
# renders, which now carry distinct scales/aspect ratios.
pad = 30
total_w = sum(img.width for img in imgs) + pad * (len(imgs) - 1)
total_h = max(img.height for img in imgs)

composite = Image.new("RGB", (total_w, total_h), (255, 255, 255))
x_cursor = 0
for img in imgs:
    y = (total_h - img.height) // 2
    composite.paste(img, (x_cursor, y))
    x_cursor += img.width + pad

out_path = str(OUT_DIR / "panel_d_v3.png")
composite.save(out_path, quality=95)
print(f"\n  Panel D triptych saved (unlabelled): {out_path}")

for f in [f1, f2, f3]:
    try:
        Path(f).unlink(missing_ok=True)
    except Exception:
        pass

print("Done.")
