#!/usr/bin/env python3
"""
Panel D — Ostwald Ripening: 3-stage triptych.

All stages show the FULL fluorite lattice as a faded transparent backdrop
(Zr=blue ghost, O=red ghost) so you see what's NOT there.
Vacancy channels rendered as bright cyan spheres on top.

Stage 1: Thin cyan vacancy sheets at acoustic antinodes
Stage 2: LSW coarsening — sheets thicken into cyan clusters
Stage 3: Dense interconnected dendritic cyan channels (200 nm scale)
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

CYAN = [0.0, 0.75, 0.85]
ZR_GHOST = [0.29, 0.53, 0.78]
O_GHOST = [0.91, 0.30, 0.24]

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
    vac_flags = vacancy_mask_fn(o_pos)

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

# Stage 1: Thin vacancy sheets at acoustic antinodes
def vac_stage1(o_pos):
    phases = np.sin(2 * np.pi * o_pos[:, 0] / wavelength)
    return phases > 0.85

f1, cx1, cy1, cz1, types1 = build_stage([8, 8, 2], vac_stage1, "d_s1")

# Stage 2: LSW coarsening — wider antinodes + spherical cluster growth
def vac_stage2(o_pos):
    phases = np.sin(2 * np.pi * o_pos[:, 0] / wavelength)
    mask = phases > 0.8
    # Grow clusters from seeds within antinode regions
    antinode_idx = np.where(phases > 0.6)[0]
    if len(antinode_idx) > 0:
        seeds = antinode_idx[np.random.choice(len(antinode_idx),
                             size=min(20, len(antinode_idx)), replace=False)]
        for s in seeds:
            dists = np.linalg.norm(o_pos - o_pos[s], axis=1)
            mask[dists < 4.5] = True
    return mask

f2, cx2, cy2, cz2, types2 = build_stage([8, 8, 3], vac_stage2, "d_s2")

# Stage 3: Dense interconnected dendritic channels
def vac_stage3(o_pos):
    n = len(o_pos)
    mask = np.zeros(n, dtype=bool)
    directions = [
        np.array([1, 1, 0]) / np.sqrt(2),
        np.array([1, -1, 0]) / np.sqrt(2),
        np.array([1, 0, 1]) / np.sqrt(2),
        np.array([0, 1, 1]) / np.sqrt(2),
        np.array([1, 0, -1]) / np.sqrt(2),
        np.array([0, 1, -1]) / np.sqrt(2),
    ]
    # Interconnected trunks along [110] with controlled branching
    for _ in range(6):
        start = o_pos[np.random.randint(n)]
        d = directions[np.random.randint(len(directions))]
        for t in np.linspace(0, 30, 200):
            point = start + t * d
            dists = np.linalg.norm(o_pos - point, axis=1)
            mask[dists < 2.0] = True
        branch_sites = np.where(mask)[0]
        if len(branch_sites) > 8:
            for bi in branch_sites[::8]:
                bd = directions[np.random.randint(len(directions))]
                bd = bd + np.random.randn(3) * 0.3
                bd /= np.linalg.norm(bd)
                bp = o_pos[bi]
                for t in np.linspace(0, 12, 60):
                    point = bp + t * bd
                    dists = np.linalg.norm(o_pos - point, axis=1)
                    mask[dists < 1.8] = True
    return mask

f3, cx3, cy3, cz3, types3 = build_stage([8, 8, 8], vac_stage3, "d_s3")


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
            if t == 1:      # Zr ghost
                colors[i] = ZR_GHOST
                radii[i] = 0.18
                transp[i] = 0.82
            elif t == 2:    # O occupied ghost
                colors[i] = O_GHOST
                radii[i] = 0.12
                transp[i] = 0.82
            else:           # vacancy — bright cyan
                colors[i] = CYAN
                radii[i] = 0.45
                transp[i] = 0.0
        data.particles_.create_property("Color", data=colors)
        data.particles_.create_property("Radius", data=radii)
        data.particles_.create_property("Transparency", data=transp)
    return _style


def render_to(pipeline, out_path, cell_max):
    vp = Viewport(type=Viewport.Type.Ortho)
    vp.camera_dir = (2, 1.5, -1)
    vp.fov = cell_max * 1.3
    pipeline.add_to_scene()
    vp.zoom_all()
    vp.render_image(filename=out_path, size=(2000, 1500),
                    renderer=renderer, background=WHITE_BG)
    pipeline.remove_from_scene()
    print(f"  Rendered: {out_path}")


# ── Render all 3 stages ──────────────────────────────────────────────────────

for xyz, cx, cy, cz, types, name in [
    (f1, cx1, cy1, cz1, types1, "panel_d_stage1"),
    (f2, cx2, cy2, cz2, types2, "panel_d_stage2"),
    (f3, cx3, cy3, cz3, types3, "panel_d_stage3"),
]:
    p = import_file(xyz)
    attach_cell(p, cx, cy, cz)
    p.modifiers.append(style_with_ghosts(types))
    render_to(p, str(OUT_DIR / f"{name}.png"), max(cx, cy, cz))


# ═══════════════════════════════════════════════════════════════════════════════
# COMPOSITE TRIPTYCH
# ═══════════════════════════════════════════════════════════════════════════════

from PIL import Image, ImageDraw, ImageFont

paths = [OUT_DIR / f"panel_d_stage{i}.png" for i in [1, 2, 3]]
imgs = [Image.open(str(p)) for p in paths]
w, h = imgs[0].size

pad = 20
title_h = 55
callout_h = 55
total_w = w * 3 + pad * 2
total_h = title_h + h + callout_h

composite = Image.new("RGB", (total_w, total_h), (255, 255, 255))
draw = ImageDraw.Draw(composite)

try:
    font_title = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
    font_callout = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 30)
    font_sub = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
except Exception:
    font_title = font_callout = font_sub = ImageFont.load_default()

labels = [
    ("Stage 1", "Acoustic Template"),
    ("Stage 2", "LSW Coarsening"),
    ("Stage 3", "Condensation"),
]
subs = ["seeds ~0.5 nm", "LSW dynamics", "~200 nm colonies"]

for i, (img, (main, sub), bot) in enumerate(zip(imgs, labels, subs)):
    x_off = i * (w + pad)
    composite.paste(img, (x_off, title_h))
    cx_t = x_off + w // 2
    draw.text((cx_t, 5), f"{main}: {sub}", fill=(50, 50, 50),
              anchor="mt", font=font_title)
    draw.text((cx_t, title_h + h + 5), bot, fill=(120, 120, 120),
              anchor="mt", font=font_sub)

for i in range(2):
    ax = (i + 1) * (w + pad) - pad // 2
    ay = title_h + h // 2
    draw.text((ax, ay), "\u2192", fill=(100, 100, 100), anchor="mm", font=font_title)

callout = "Parallel Transport: M = 1000\u00d7  |  Channel Cond. = 10\u2075\u00d7 Bulk"
draw.text((total_w // 2, total_h - 5), callout, fill=(0, 0, 0),
          anchor="mb", font=font_callout)

out_path = str(OUT_DIR / "panel_d_v3.png")
composite.save(out_path, quality=95)
print(f"\n  Panel D triptych saved: {out_path}")

for f in [f1, f2, f3]:
    try:
        Path(f).unlink(missing_ok=True)
    except Exception:
        pass

print("Done.")
