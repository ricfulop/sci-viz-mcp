#!/usr/bin/env python3
"""
Vacancy-migration panels via OVITO Tachyon ray-tracer + matplotlib annotations.

Panel (a): ZrO₂ fluorite — O vacancy + O–O migration path + Zr–Zr saddle
Panel (b): BCC W — triple vacancy cluster + ADP strain halos + [110] saddle inset
Panel (c): WC hexagonal — V_C + C_i Frenkel pair + zigzag displacement vector

Uses the OVITO Python API (same engine as ovito_mcp) for 3D rendering,
then overlays publication-quality annotations with matplotlib.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import ase.io
import ase.build
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import (
    FancyArrowPatch,
    Circle,
    Ellipse,
    Arc,
)
from matplotlib.lines import Line2D
import matplotlib.patheffects as pe
from PIL import Image

from ovito.io import import_file
from ovito.vis import Viewport, TachyonRenderer
from ovito.modifiers import ExpressionSelectionModifier, DeleteSelectedModifier

from styles import apply_aps_style, MATERIALS, APS_DOUBLE

CIF_DIR = Path(__file__).parent.parent / "tests" / "sample_structures"
OUT_DIR = Path(__file__).parent.parent / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BLUE = MATERIALS["blue"]
ORANGE = MATERIALS["vermillion"]
GREEN = MATERIALS["green"]
GOLD = MATERIALS["gold"]
GRAY = "#999999"
DARK_GRAY = "#555555"
WHITE = "#FFFFFF"

IMG_W, IMG_H = 2400, 1800


def _tachyon():
    r = TachyonRenderer()
    r.antialiasing_samples = 12
    r.direct_light_intensity = 0.9
    r.ambient_occlusion = True
    r.ambient_occlusion_brightness = 0.8
    return r


def _project_ortho(pos_3d, cam_dir, cam_up, cell, img_size, padding=0.12):
    """Project 3D positions to 2D pixel coords for orthographic camera."""
    cam_dir = np.array(cam_dir, dtype=float)
    cam_dir /= np.linalg.norm(cam_dir)
    cam_up = np.array(cam_up, dtype=float)

    x_axis = np.cross(cam_up, cam_dir)
    x_axis /= np.linalg.norm(x_axis)
    y_axis = np.cross(cam_dir, x_axis)
    y_axis /= np.linalg.norm(y_axis)

    pts = np.atleast_2d(pos_3d)
    x2d = pts @ x_axis
    y2d = pts @ y_axis

    xmin, xmax = x2d.min(), x2d.max()
    ymin, ymax = y2d.min(), y2d.max()
    dx = xmax - xmin
    dy = ymax - ymin
    pad_x = dx * padding
    pad_y = dy * padding

    w, h = img_size
    px = (x2d - xmin + pad_x) / (dx + 2 * pad_x) * w
    py = h - (y2d - ymin + pad_y) / (dy + 2 * pad_y) * h

    return px, py


# ═══════════════════════════════════════════════════════════════════════════════
# Panel (a): ZrO₂ fluorite — O vacancy migration
# ═══════════════════════════════════════════════════════════════════════════════

def panel_a():
    atoms = ase.io.read(str(CIF_DIR / "fluorite_ZrO2.cif"))
    sc = atoms.repeat([2, 2, 1])
    symbols = sc.get_chemical_symbols()
    positions = sc.positions.copy()
    cell = sc.cell[:]

    o_indices = [i for i, s in enumerate(symbols) if s == "O"]
    zr_indices = [i for i, s in enumerate(symbols) if s == "Zr"]

    vac_idx = o_indices[4]
    vac_pos = positions[vac_idx].copy()

    dists = np.linalg.norm(positions[o_indices] - vac_pos, axis=1)
    sorted_o = np.argsort(dists)
    adj_o_local = sorted_o[1]
    adj_o_idx = o_indices[adj_o_local]
    adj_pos = positions[adj_o_idx].copy()

    zr_pos_all = positions[zr_indices]
    mid_migration = (vac_pos + adj_pos) / 2.0
    zr_dists = np.linalg.norm(zr_pos_all - mid_migration, axis=1)
    nearest_zr = np.argsort(zr_dists)[:2]
    saddle_pos = (zr_pos_all[nearest_zr[0]] + zr_pos_all[nearest_zr[1]]) / 2.0

    del sc[vac_idx]
    tmp_cif = OUT_DIR / "_tmp_panel_a.cif"
    ase.io.write(str(tmp_cif), sc, format="cif")

    color_map = {"Zr": (0.6, 0.6, 0.6), "O": (1.0, 1.0, 1.0)}
    radii_map = {"Zr": 0.9, "O": 0.5}

    def style_fn(frame, data):
        ptypes = data.particles.particle_types
        if ptypes is None:
            return
        tmap = {t.id: t.name for t in ptypes.types}
        ids = np.array(ptypes)
        colors = np.ones((data.particles.count, 3)) * 0.5
        radii = np.ones(data.particles.count) * 0.5
        for tid, tname in tmap.items():
            mask = ids == tid
            if tname in color_map:
                colors[mask] = color_map[tname]
            if tname in radii_map:
                radii[mask] = radii_map[tname]
        data.particles_.create_property("Color", data=colors)
        data.particles_.create_property("Radius", data=radii)

    pipeline = import_file(str(tmp_cif))
    pipeline.modifiers.append(style_fn)
    pipeline.add_to_scene()

    vp = Viewport(type=Viewport.Type.Ortho)
    vp.camera_dir = (0, 0, -1)
    vp.fov = max(cell[0, 0], cell[1, 1]) * 1.3
    vp.zoom_all()

    base_png = str(OUT_DIR / "panel_a_ovito_base.png")
    vp.render_image(
        filename=base_png,
        size=(IMG_W, IMG_H),
        renderer=_tachyon(),
        background=(1.0, 1.0, 1.0),
    )
    pipeline.remove_from_scene()
    tmp_cif.unlink(missing_ok=True)

    all_pos = positions
    all_pos_for_proj = np.vstack([all_pos, [vac_pos], [adj_pos], [saddle_pos]])
    px, py = _project_ortho(
        all_pos_for_proj, [0, 0, -1], [0, 1, 0], cell, (IMG_W, IMG_H)
    )

    n = len(positions)
    vac_px, vac_py = px[n], py[n]
    adj_px, adj_py = px[n + 1], py[n + 1]
    sad_px, sad_py = px[n + 2], py[n + 2]

    img = Image.open(base_png)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.imshow(img, extent=[0, IMG_W, IMG_H, 0])
    ax.set_xlim(0, IMG_W)
    ax.set_ylim(IMG_H, 0)
    ax.set_aspect("equal")
    ax.axis("off")

    vac_r = 55
    circle = plt.Circle(
        (vac_px, vac_py),
        vac_r,
        fill=False,
        edgecolor=BLUE,
        linewidth=2.5,
        linestyle="--",
    )
    ax.add_patch(circle)
    ax.annotate(
        r"$V_{\mathrm{O}}$",
        (vac_px, vac_py),
        fontsize=14,
        fontweight="bold",
        color=BLUE,
        ha="center",
        va="center",
    )

    arrow = FancyArrowPatch(
        (vac_px, vac_py),
        (adj_px, adj_py),
        arrowstyle="->,head_length=12,head_width=6",
        color=BLUE,
        linewidth=2.5,
        linestyle="--",
        mutation_scale=1,
    )
    ax.add_patch(arrow)

    ax.plot(
        sad_px,
        sad_py,
        marker="x",
        color=GOLD,
        markersize=18,
        markeredgewidth=3.5,
        zorder=10,
    )
    ax.annotate(
        "saddle",
        (sad_px, sad_py + 40),
        fontsize=10,
        color=GOLD,
        ha="center",
        fontweight="bold",
    )

    ax.text(
        60,
        80,
        "(a)  ZrO₂ fluorite  [001]",
        fontsize=14,
        fontweight="bold",
        color="black",
    )

    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=GRAY, markersize=12, label="Zr"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=WHITE, markeredgecolor=BLUE, markersize=8, markeredgewidth=1.5, label="O"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", fontsize=10, framealpha=0.85)

    out_path = str(OUT_DIR / "panel_a_ovito.png")
    fig.savefig(out_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Panel (a) OVITO: {out_path}")
    return out_path


# ═══════════════════════════════════════════════════════════════════════════════
# Panel (b): BCC W — triple vacancy cluster + ADP halos + [110] saddle inset
# ═══════════════════════════════════════════════════════════════════════════════

def panel_b():
    atoms = ase.io.read(str(CIF_DIR / "bcc_W.cif"))
    sc = atoms.repeat([3, 3, 1])
    symbols = sc.get_chemical_symbols()
    positions = sc.positions.copy()
    cell = sc.cell[:]

    n_atoms = len(sc)
    dists_from_center = np.linalg.norm(
        positions - positions.mean(axis=0), axis=1
    )

    w_indices = list(range(n_atoms))
    sorted_by_dist = np.argsort(dists_from_center)
    vac_candidates = []
    for idx in sorted_by_dist:
        if len(vac_candidates) == 0:
            vac_candidates.append(idx)
        else:
            pos_i = positions[idx]
            too_close = False
            for vc in vac_candidates:
                if np.linalg.norm(pos_i - positions[vc]) < 3.5:
                    too_close = True
                    break
            if not too_close:
                vac_candidates.append(idx)
        if len(vac_candidates) == 3:
            break

    vac_positions = positions[vac_candidates].copy()

    mask = np.ones(n_atoms, dtype=bool)
    mask[vac_candidates] = False
    sc_defect = sc[mask]
    positions_kept = positions[mask]

    tmp_cif = OUT_DIR / "_tmp_panel_b.cif"
    ase.io.write(str(tmp_cif), sc_defect, format="cif")

    def style_fn(frame, data):
        ptypes = data.particles.particle_types
        if ptypes is None:
            return
        colors = np.ones((data.particles.count, 3)) * 0.6
        radii = np.ones(data.particles.count) * 0.75
        data.particles_.create_property("Color", data=colors)
        data.particles_.create_property("Radius", data=radii)

    pipeline = import_file(str(tmp_cif))
    pipeline.modifiers.append(style_fn)
    pipeline.add_to_scene()

    vp = Viewport(type=Viewport.Type.Ortho)
    vp.camera_dir = (0, 0, -1)
    vp.fov = max(cell[0, 0], cell[1, 1]) * 1.4
    vp.zoom_all()

    base_png = str(OUT_DIR / "panel_b_ovito_base.png")
    vp.render_image(
        filename=base_png,
        size=(IMG_W, IMG_H),
        renderer=_tachyon(),
        background=(1.0, 1.0, 1.0),
    )
    pipeline.remove_from_scene()
    tmp_cif.unlink(missing_ok=True)

    all_proj = np.vstack([positions_kept, vac_positions])
    px, py = _project_ortho(
        all_proj, [0, 0, -1], [0, 1, 0], cell, (IMG_W, IMG_H)
    )
    n_kept = len(positions_kept)
    vac_px = px[n_kept:]
    vac_py = py[n_kept:]

    img = Image.open(base_png)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.imshow(img, extent=[0, IMG_W, IMG_H, 0])
    ax.set_xlim(0, IMG_W)
    ax.set_ylim(IMG_H, 0)
    ax.set_aspect("equal")
    ax.axis("off")

    for i in range(len(vac_positions)):
        ell = Ellipse(
            (vac_px[i], vac_py[i]),
            width=180,
            height=160,
            angle=np.random.uniform(0, 30),
            fill=True,
            facecolor=ORANGE,
            alpha=0.20,
            edgecolor=ORANGE,
            linewidth=2.0,
            linestyle="-",
        )
        ax.add_patch(ell)
        ax.annotate(
            r"$V_{\mathrm{W}}$",
            (vac_px[i], vac_py[i]),
            fontsize=12,
            fontweight="bold",
            color=ORANGE,
            ha="center",
            va="center",
        )

    ax.text(
        60,
        80,
        "(b)  BCC W  [001]",
        fontsize=14,
        fontweight="bold",
        color="black",
    )

    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=GRAY, markeredgecolor=ORANGE, markersize=10, markeredgewidth=1.5, label="W"),
        Ellipse((0, 0), 0.1, 0.1, facecolor=ORANGE, alpha=0.3),
    ]
    ax.legend(
        handles=[
            Line2D([0], [0], marker="o", color="w", markerfacecolor=GRAY, markeredgecolor=ORANGE, markersize=10, markeredgewidth=1.5, label="W"),
            Line2D([0], [0], marker="s", color="w", markerfacecolor=ORANGE, alpha=0.3, markersize=12, label="ADP halo"),
        ],
        loc="lower right",
        fontsize=10,
        framealpha=0.85,
    )

    # ── Saddle-point inset: [110] view with migrating atom ──
    atoms_110 = ase.io.read(str(CIF_DIR / "bcc_W.cif"))
    sc_110 = atoms_110.repeat([3, 3, 2])
    pos_110 = sc_110.positions.copy()
    cell_110 = sc_110.cell[:]

    center = pos_110.mean(axis=0)
    dists_c = np.linalg.norm(pos_110 - center, axis=1)
    sorted_c = np.argsort(dists_c)
    mid_hop_idx = sorted_c[0]
    hop_pos = pos_110[mid_hop_idx].copy()

    nbrs = sorted_c[1:5]
    rhombus_pos = pos_110[nbrs]

    cam_110 = np.array([1, 1, 0], dtype=float)
    cam_110 /= np.linalg.norm(cam_110)
    up_110 = np.array([0, 0, 1], dtype=float)
    x110 = np.cross(up_110, cam_110)
    x110 /= np.linalg.norm(x110)
    y110 = np.cross(cam_110, x110)

    def proj_110(pts):
        pts = np.atleast_2d(pts)
        return pts @ x110, pts @ y110

    inset_ax = fig.add_axes([0.62, 0.58, 0.32, 0.35])
    inset_ax.set_facecolor("#F8F8F8")
    inset_ax.set_aspect("equal")

    all_x, all_y = proj_110(pos_110)
    hop_x, hop_y = proj_110(hop_pos)
    rh_x, rh_y = proj_110(rhombus_pos)

    near_mask = np.linalg.norm(pos_110 - hop_pos, axis=1) < 5.0
    near_x, near_y = all_x[near_mask], all_y[near_mask]

    inset_ax.scatter(near_x, near_y, s=250, c=GRAY, edgecolors="black", linewidths=0.8, zorder=3)

    inset_ax.scatter(
        hop_x,
        hop_y,
        s=350,
        c=ORANGE,
        alpha=0.5,
        edgecolors=ORANGE,
        linewidths=2.0,
        zorder=5,
    )

    for i in range(len(rh_x)):
        for j in range(i + 1, len(rh_x)):
            inset_ax.plot(
                [rh_x[i], rh_x[j]],
                [rh_y[i], rh_y[j]],
                color="#AAAAAA",
                linewidth=0.8,
                linestyle="--",
                alpha=0.5,
            )

    inset_ax.set_title("[110] saddle", fontsize=9, fontweight="bold")
    inset_ax.set_xticks([])
    inset_ax.set_yticks([])
    for spine in inset_ax.spines.values():
        spine.set_edgecolor("#888888")
        spine.set_linewidth(1.0)

    out_path = str(OUT_DIR / "panel_b_ovito.png")
    fig.savefig(out_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Panel (b) OVITO: {out_path}")
    return out_path


# ═══════════════════════════════════════════════════════════════════════════════
# Panel (c): WC hexagonal — V_C + C_i Frenkel pair
# ═══════════════════════════════════════════════════════════════════════════════

def panel_c():
    atoms = ase.io.read(str(CIF_DIR / "hexagonal_WC.cif"))
    sc = atoms.repeat([2, 2, 1])
    symbols = sc.get_chemical_symbols()
    positions = sc.positions.copy()
    cell = sc.cell[:]

    c_indices = [i for i, s in enumerate(symbols) if s == "C"]
    w_indices = [i for i, s in enumerate(symbols) if s == "W"]

    vac_c_idx = c_indices[0]
    vac_c_pos = positions[vac_c_idx].copy()

    interstitial_pos = vac_c_pos + np.array([0.3, 0.25, 0.5])

    c_dists = np.linalg.norm(positions[c_indices] - vac_c_pos, axis=1)
    sorted_c = np.argsort(c_dists)
    adj_c_idx = c_indices[sorted_c[1]]
    saddle_pos = (vac_c_pos + positions[adj_c_idx]) / 2.0

    del sc[vac_c_idx]
    tmp_cif = OUT_DIR / "_tmp_panel_c.cif"
    ase.io.write(str(tmp_cif), sc, format="cif")

    color_map = {"W": (0.35, 0.35, 0.35), "C": (1.0, 1.0, 1.0)}
    radii_map = {"W": 0.85, "C": 0.45}

    def style_fn(frame, data):
        ptypes = data.particles.particle_types
        if ptypes is None:
            return
        tmap = {t.id: t.name for t in ptypes.types}
        ids = np.array(ptypes)
        colors = np.ones((data.particles.count, 3)) * 0.5
        radii = np.ones(data.particles.count) * 0.5
        for tid, tname in tmap.items():
            mask = ids == tid
            if tname in color_map:
                colors[mask] = color_map[tname]
            if tname in radii_map:
                radii[mask] = radii_map[tname]
        data.particles_.create_property("Color", data=colors)
        data.particles_.create_property("Radius", data=radii)

    pipeline = import_file(str(tmp_cif))
    pipeline.modifiers.append(style_fn)
    pipeline.add_to_scene()

    vp = Viewport(type=Viewport.Type.Ortho)
    vp.camera_dir = (0, 0, -1)
    vp.fov = max(cell[0, 0], cell[1, 1]) * 1.5
    vp.zoom_all()

    base_png = str(OUT_DIR / "panel_c_ovito_base.png")
    vp.render_image(
        filename=base_png,
        size=(IMG_W, IMG_H),
        renderer=_tachyon(),
        background=(1.0, 1.0, 1.0),
    )
    pipeline.remove_from_scene()
    tmp_cif.unlink(missing_ok=True)

    anno_pts = np.vstack(
        [positions, [vac_c_pos], [interstitial_pos], [saddle_pos]]
    )
    px, py = _project_ortho(
        anno_pts, [0, 0, -1], [0, 1, 0], cell, (IMG_W, IMG_H)
    )
    n = len(positions)
    vc_px, vc_py = px[n], py[n]
    ci_px, ci_py = px[n + 1], py[n + 1]
    sad_px, sad_py = px[n + 2], py[n + 2]

    img = Image.open(base_png)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.imshow(img, extent=[0, IMG_W, IMG_H, 0])
    ax.set_xlim(0, IMG_W)
    ax.set_ylim(IMG_H, 0)
    ax.set_aspect("equal")
    ax.axis("off")

    vac_circle = plt.Circle(
        (vc_px, vc_py),
        50,
        fill=False,
        edgecolor=GREEN,
        linewidth=2.5,
        linestyle="--",
    )
    ax.add_patch(vac_circle)
    ax.annotate(
        r"$V_{\mathrm{C}}$",
        (vc_px, vc_py),
        fontsize=13,
        fontweight="bold",
        color=GREEN,
        ha="center",
        va="center",
    )

    ci_circle = plt.Circle(
        (ci_px, ci_py),
        40,
        fill=False,
        edgecolor=GREEN,
        linewidth=2.5,
        linestyle="--",
    )
    ax.add_patch(ci_circle)
    ax.annotate(
        r"$C_{\mathrm{i}}$",
        (ci_px, ci_py),
        fontsize=12,
        fontweight="bold",
        color=GREEN,
        ha="center",
        va="center",
    )

    mid_x = (vc_px + ci_px) / 2
    mid_y = (vc_py + ci_py) / 2
    dx = ci_px - vc_px
    dy = ci_py - vc_py
    perp_x = -dy * 0.15
    perp_y = dx * 0.15

    zigzag_x = [
        vc_px,
        vc_px + dx * 0.33 + perp_x,
        vc_px + dx * 0.66 - perp_x,
        ci_px,
    ]
    zigzag_y = [
        vc_py,
        vc_py + dy * 0.33 + perp_y,
        vc_py + dy * 0.66 - perp_y,
        ci_py,
    ]
    ax.annotate(
        "",
        xy=(zigzag_x[-1], zigzag_y[-1]),
        xytext=(zigzag_x[-2], zigzag_y[-2]),
        arrowprops=dict(arrowstyle="->", color=GREEN, lw=2.5),
    )
    ax.plot(
        zigzag_x[:-1],
        zigzag_y[:-1],
        color=GREEN,
        linewidth=2.5,
        linestyle="-",
        solid_capstyle="round",
    )

    saddle_circle = plt.Circle(
        (sad_px, sad_py),
        35,
        fill=True,
        facecolor=GREEN,
        alpha=0.35,
        edgecolor=GREEN,
        linewidth=2.0,
    )
    ax.add_patch(saddle_circle)
    ax.annotate(
        "TS",
        (sad_px, sad_py + 50),
        fontsize=9,
        fontweight="bold",
        color=GREEN,
        ha="center",
    )

    ax.text(
        60,
        80,
        "(c)  WC hexagonal  [001]",
        fontsize=14,
        fontweight="bold",
        color="black",
    )

    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=DARK_GRAY, markersize=12, label="W"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=WHITE, markeredgecolor=GREEN, markersize=8, markeredgewidth=1.5, label="C"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", fontsize=10, framealpha=0.85)

    out_path = str(OUT_DIR / "panel_c_ovito.png")
    fig.savefig(out_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Panel (c) OVITO: {out_path}")
    return out_path


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    apply_aps_style()
    print("=" * 60)
    print("Generating vacancy-migration panels via OVITO Tachyon")
    print("=" * 60)

    a = panel_a()
    b = panel_b()
    c = panel_c()

    print("\n── All OVITO panels complete ──")
    print(f"  (a) {a}")
    print(f"  (b) {b}")
    print(f"  (c) {c}")
