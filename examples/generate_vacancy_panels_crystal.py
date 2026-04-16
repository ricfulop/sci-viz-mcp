#!/usr/bin/env python3
"""
Vacancy-migration panels via Crystal MCP approach (ASE + matplotlib 2D projection).

Panel (a): ZrO₂ fluorite — O vacancy + O–O migration path + Zr–Zr saddle
Panel (b): BCC W — triple vacancy cluster + ADP strain halos + [110] saddle inset
Panel (c): WC hexagonal — V_C + C_i Frenkel pair + zigzag displacement vector

Uses ASE for structure building and matplotlib for publication-quality 2D
projected diagrams — the same rendering engine as crystal_mcp_server.py.
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
    Circle,
    FancyArrowPatch,
    Ellipse,
    FancyBboxPatch,
    Rectangle,
)
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
import matplotlib.patheffects as pe

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
LIGHT_GRAY = "#C8C8C8"


def _project_2d(positions, projection="001"):
    """Project 3D positions to 2D using Miller-index direction."""
    digits = [int(c) for c in projection]
    normal = np.array(digits, dtype=float)
    normal /= np.linalg.norm(normal)

    if abs(normal[2]) < 0.99:
        up = np.array([0, 0, 1.0])
    else:
        up = np.array([1, 0, 0.0])

    x_axis = np.cross(up, normal)
    x_axis /= np.linalg.norm(x_axis)
    y_axis = np.cross(normal, x_axis)
    y_axis /= np.linalg.norm(y_axis)

    pts = np.atleast_2d(positions)
    depth = pts @ normal
    x2d = pts @ x_axis
    y2d = pts @ y_axis
    return x2d, y2d, depth


def _draw_cell_box(ax, cell, projection="001", **kwargs):
    """Draw the projected unit cell outline."""
    corners_frac = np.array([
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
    ], dtype=float)
    corners = corners_frac @ cell
    x, y, _ = _project_2d(corners, projection)

    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    default_kw = dict(color="#AAAAAA", linewidth=0.8, linestyle="-", alpha=0.6)
    default_kw.update(kwargs)
    for i, j in edges:
        ax.plot([x[i], x[j]], [y[i], y[j]], **default_kw)


def _draw_atoms(ax, x2d, y2d, depth, symbols, colors, radii, rim_colors=None):
    """Draw atoms as circles sorted by depth (back-to-front)."""
    order = np.argsort(depth)
    for idx in order:
        s = symbols[idx]
        r = radii.get(s, 0.2)
        fc = colors.get(s, GRAY)
        rc = rim_colors.get(s, None) if rim_colors else None

        shade = 0.85 + 0.15 * (depth[idx] - depth.min()) / max(depth.max() - depth.min(), 0.01)
        circle = Circle(
            (x2d[idx], y2d[idx]),
            r,
            facecolor=fc,
            edgecolor=rc if rc else "black",
            linewidth=1.8 if rc else 0.6,
            zorder=depth[idx] + 100,
            alpha=min(1.0, shade),
        )
        ax.add_patch(circle)


def _draw_bonds(ax, positions, symbols, x2d, y2d, depth, cutoff=3.2, color="#888888"):
    """Draw bonds between atoms within cutoff distance."""
    n = len(positions)
    segments = []
    for i in range(n):
        for j in range(i + 1, n):
            d = np.linalg.norm(positions[i] - positions[j])
            if d < cutoff:
                avg_depth = (depth[i] + depth[j]) / 2
                segments.append(((x2d[i], y2d[i]), (x2d[j], y2d[j]), avg_depth))

    segments.sort(key=lambda s: s[2])
    for (x1, y1), (x2, y2), d in segments:
        shade = 0.5 + 0.3 * (d - depth.min()) / max(depth.max() - depth.min(), 0.01)
        ax.plot(
            [x1, x2], [y1, y2],
            color=color, linewidth=0.6, alpha=min(0.7, shade), zorder=d + 50,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Panel (a): ZrO₂ fluorite — O vacancy migration
# ═══════════════════════════════════════════════════════════════════════════════

def panel_a():
    atoms = ase.io.read(str(CIF_DIR / "fluorite_ZrO2.cif"))
    sc = atoms.repeat([2, 2, 1])
    symbols = list(sc.get_chemical_symbols())
    positions = sc.positions.copy()
    cell = sc.cell[:]

    o_indices = [i for i, s in enumerate(symbols) if s == "O"]
    zr_indices = [i for i, s in enumerate(symbols) if s == "Zr"]

    vac_idx = o_indices[4]
    vac_pos = positions[vac_idx].copy()

    dists = np.linalg.norm(positions[o_indices] - vac_pos, axis=1)
    sorted_o = np.argsort(dists)
    adj_o_idx = o_indices[sorted_o[1]]
    adj_pos = positions[adj_o_idx].copy()

    zr_pos_all = positions[zr_indices]
    mid_migration = (vac_pos + adj_pos) / 2.0
    zr_dists = np.linalg.norm(zr_pos_all - mid_migration, axis=1)
    nearest_zr = np.argsort(zr_dists)[:2]
    saddle_pos = (zr_pos_all[nearest_zr[0]] + zr_pos_all[nearest_zr[1]]) / 2.0

    mask = np.ones(len(symbols), dtype=bool)
    mask[vac_idx] = False
    kept_symbols = [s for i, s in enumerate(symbols) if mask[i]]
    kept_positions = positions[mask]

    x2d, y2d, depth = _project_2d(kept_positions, "001")

    colors = {"Zr": GRAY, "O": WHITE}
    radii = {"Zr": 0.50, "O": 0.30}
    rim_colors = {"Zr": None, "O": BLUE}

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_facecolor("white")

    _draw_cell_box(ax, cell, "001")
    _draw_bonds(ax, kept_positions, kept_symbols, x2d, y2d, depth, cutoff=2.8)
    _draw_atoms(ax, x2d, y2d, depth, kept_symbols, colors, radii, rim_colors)

    vx, vy, _ = _project_2d(vac_pos.reshape(1, -1), "001")
    adj_x, adj_y, _ = _project_2d(adj_pos.reshape(1, -1), "001")
    sx, sy, _ = _project_2d(saddle_pos.reshape(1, -1), "001")

    vac_circle = Circle(
        (vx[0], vy[0]),
        radii["O"],
        fill=False,
        edgecolor=BLUE,
        linewidth=2.0,
        linestyle="--",
        zorder=200,
    )
    ax.add_patch(vac_circle)
    ax.annotate(
        r"$V_{\mathrm{O}}$",
        (vx[0], vy[0]),
        fontsize=11,
        fontweight="bold",
        color=BLUE,
        ha="center",
        va="center",
        zorder=201,
    )

    arrow = FancyArrowPatch(
        (vx[0], vy[0]),
        (adj_x[0], adj_y[0]),
        arrowstyle="->,head_length=6,head_width=3",
        color=BLUE,
        linewidth=2.0,
        linestyle="--",
        zorder=190,
    )
    ax.add_patch(arrow)

    ax.plot(
        sx[0], sy[0],
        marker="x",
        color=GOLD,
        markersize=16,
        markeredgewidth=3.0,
        zorder=210,
    )
    ax.annotate(
        "saddle",
        (sx[0], sy[0] + 0.35),
        fontsize=8,
        color=GOLD,
        ha="center",
        fontweight="bold",
        zorder=211,
    )

    pad = 0.8
    ax.set_xlim(x2d.min() - pad, x2d.max() + pad)
    ax.set_ylim(y2d.min() - pad, y2d.max() + pad)

    ax.text(
        x2d.min() - pad + 0.15,
        y2d.max() + pad - 0.15,
        "(a)  ZrO₂ fluorite  [001]",
        fontsize=11,
        fontweight="bold",
    )

    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=GRAY, markersize=12, label="Zr"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=WHITE, markeredgecolor=BLUE, markeredgewidth=1.5, markersize=8, label="O"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", fontsize=9, framealpha=0.85)

    out_path = str(OUT_DIR / "panel_a_crystal.png")
    fig.savefig(out_path, dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Panel (a) Crystal: {out_path}")
    return out_path


# ═══════════════════════════════════════════════════════════════════════════════
# Panel (b): BCC W — triple vacancy cluster + ADP halos + [110] saddle inset
# ═══════════════════════════════════════════════════════════════════════════════

def panel_b():
    atoms = ase.io.read(str(CIF_DIR / "bcc_W.cif"))
    sc = atoms.repeat([3, 3, 1])
    symbols = list(sc.get_chemical_symbols())
    positions = sc.positions.copy()
    cell = sc.cell[:]
    n_atoms = len(sc)

    dists_from_center = np.linalg.norm(
        positions - positions.mean(axis=0), axis=1
    )
    sorted_by_dist = np.argsort(dists_from_center)
    vac_candidates = []
    for idx in sorted_by_dist:
        if len(vac_candidates) == 0:
            vac_candidates.append(idx)
        else:
            pos_i = positions[idx]
            too_close = any(
                np.linalg.norm(pos_i - positions[vc]) < 3.5
                for vc in vac_candidates
            )
            if not too_close:
                vac_candidates.append(idx)
        if len(vac_candidates) == 3:
            break

    vac_positions = positions[vac_candidates].copy()

    mask = np.ones(n_atoms, dtype=bool)
    mask[vac_candidates] = False
    kept_symbols = [s for i, s in enumerate(symbols) if mask[i]]
    kept_positions = positions[mask]

    x2d, y2d, depth = _project_2d(kept_positions, "001")
    vx, vy, _ = _project_2d(vac_positions, "001")

    colors = {"W": GRAY}
    radii = {"W": 0.45}
    rim_colors = {"W": ORANGE}

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_facecolor("white")

    _draw_cell_box(ax, cell, "001")
    _draw_bonds(ax, kept_positions, kept_symbols, x2d, y2d, depth, cutoff=3.3, color="#BBBBBB")
    _draw_atoms(ax, x2d, y2d, depth, kept_symbols, colors, radii, rim_colors)

    for i in range(len(vac_positions)):
        ell = Ellipse(
            (vx[i], vy[i]),
            width=1.8,
            height=1.5,
            angle=np.random.uniform(0, 30),
            facecolor=ORANGE,
            alpha=0.20,
            edgecolor=ORANGE,
            linewidth=1.8,
            linestyle="-",
            zorder=200,
        )
        ax.add_patch(ell)
        ax.annotate(
            r"$V_{\mathrm{W}}$",
            (vx[i], vy[i]),
            fontsize=10,
            fontweight="bold",
            color=ORANGE,
            ha="center",
            va="center",
            zorder=201,
        )

    pad = 0.8
    ax.set_xlim(x2d.min() - pad, x2d.max() + pad)
    ax.set_ylim(y2d.min() - pad, y2d.max() + pad)

    ax.text(
        x2d.min() - pad + 0.15,
        y2d.max() + pad - 0.15,
        "(b)  BCC W  [001]",
        fontsize=11,
        fontweight="bold",
    )

    # ── [110] saddle inset ──
    atoms_110 = ase.io.read(str(CIF_DIR / "bcc_W.cif"))
    sc_110 = atoms_110.repeat([3, 3, 2])
    pos_110 = sc_110.positions.copy()

    center = pos_110.mean(axis=0)
    dists_c = np.linalg.norm(pos_110 - center, axis=1)
    sorted_c = np.argsort(dists_c)
    hop_atom = sorted_c[0]
    hop_pos = pos_110[hop_atom].copy()

    x110, y110, d110 = _project_2d(pos_110, "110")
    hx, hy, _ = _project_2d(hop_pos.reshape(1, -1), "110")

    near_mask = np.linalg.norm(pos_110 - hop_pos, axis=1) < 4.5
    near_x, near_y = x110[near_mask], y110[near_mask]

    inset_ax = fig.add_axes([0.60, 0.55, 0.33, 0.38])
    inset_ax.set_facecolor("#F8F8F8")
    inset_ax.set_aspect("equal")

    inset_ax.scatter(
        near_x, near_y,
        s=200, c=GRAY, edgecolors="black", linewidths=0.8, zorder=3,
    )

    inset_ax.scatter(
        hx, hy,
        s=300, c=ORANGE, alpha=0.5, edgecolors=ORANGE, linewidths=2.0, zorder=5,
    )

    inset_ax.set_title("[110] saddle", fontsize=9, fontweight="bold")
    inset_ax.set_xticks([])
    inset_ax.set_yticks([])
    for spine in inset_ax.spines.values():
        spine.set_edgecolor("#888888")
        spine.set_linewidth(1.0)

    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=GRAY, markeredgecolor=ORANGE, markeredgewidth=1.5, markersize=10, label="W"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor=ORANGE, alpha=0.3, markersize=10, label="ADP halo"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", fontsize=9, framealpha=0.85)

    out_path = str(OUT_DIR / "panel_b_crystal.png")
    fig.savefig(out_path, dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Panel (b) Crystal: {out_path}")
    return out_path


# ═══════════════════════════════════════════════════════════════════════════════
# Panel (c): WC hexagonal — V_C + C_i Frenkel pair
# ═══════════════════════════════════════════════════════════════════════════════

def panel_c():
    atoms = ase.io.read(str(CIF_DIR / "hexagonal_WC.cif"))
    sc = atoms.repeat([2, 2, 1])
    symbols = list(sc.get_chemical_symbols())
    positions = sc.positions.copy()
    cell = sc.cell[:]

    c_indices = [i for i, s in enumerate(symbols) if s == "C"]
    w_indices = [i for i, s in enumerate(symbols) if s == "W"]

    vac_c_idx = c_indices[0]
    vac_c_pos = positions[vac_c_idx].copy()

    interstitial_pos = vac_c_pos + np.array([0.3, 0.25, 0.5])

    c_dists = np.linalg.norm(positions[c_indices] - vac_c_pos, axis=1)
    sorted_c_dist = np.argsort(c_dists)
    adj_c_idx = c_indices[sorted_c_dist[1]]
    saddle_pos = (vac_c_pos + positions[adj_c_idx]) / 2.0

    mask = np.ones(len(symbols), dtype=bool)
    mask[vac_c_idx] = False
    kept_symbols = [s for i, s in enumerate(symbols) if mask[i]]
    kept_positions = positions[mask]

    x2d, y2d, depth = _project_2d(kept_positions, "001")

    colors = {"W": DARK_GRAY, "C": WHITE}
    radii = {"W": 0.50, "C": 0.25}
    rim_colors = {"W": None, "C": GREEN}

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_facecolor("white")

    _draw_cell_box(ax, cell, "001")
    _draw_bonds(ax, kept_positions, kept_symbols, x2d, y2d, depth, cutoff=2.5)
    _draw_atoms(ax, x2d, y2d, depth, kept_symbols, colors, radii, rim_colors)

    vx, vy, _ = _project_2d(vac_c_pos.reshape(1, -1), "001")
    ix, iy, _ = _project_2d(interstitial_pos.reshape(1, -1), "001")
    sx, sy, _ = _project_2d(saddle_pos.reshape(1, -1), "001")

    vac_circle = Circle(
        (vx[0], vy[0]),
        radii["C"],
        fill=False,
        edgecolor=GREEN,
        linewidth=2.0,
        linestyle="--",
        zorder=200,
    )
    ax.add_patch(vac_circle)
    ax.annotate(
        r"$V_{\mathrm{C}}$",
        (vx[0], vy[0]),
        fontsize=11,
        fontweight="bold",
        color=GREEN,
        ha="center",
        va="center",
        zorder=201,
    )

    ci_circle = Circle(
        (ix[0], iy[0]),
        radii["C"] * 0.9,
        fill=False,
        edgecolor=GREEN,
        linewidth=2.0,
        linestyle="--",
        zorder=200,
    )
    ax.add_patch(ci_circle)
    ax.annotate(
        r"$C_{\mathrm{i}}$",
        (ix[0], iy[0]),
        fontsize=10,
        fontweight="bold",
        color=GREEN,
        ha="center",
        va="center",
        zorder=201,
    )

    dx = ix[0] - vx[0]
    dy = iy[0] - vy[0]
    perp_x = -dy * 0.18
    perp_y = dx * 0.18

    zigzag_x = [
        vx[0],
        vx[0] + dx * 0.33 + perp_x,
        vx[0] + dx * 0.66 - perp_x,
        ix[0],
    ]
    zigzag_y = [
        vy[0],
        vy[0] + dy * 0.33 + perp_y,
        vy[0] + dy * 0.66 - perp_y,
        iy[0],
    ]
    ax.annotate(
        "",
        xy=(zigzag_x[-1], zigzag_y[-1]),
        xytext=(zigzag_x[-2], zigzag_y[-2]),
        arrowprops=dict(arrowstyle="->", color=GREEN, lw=2.0),
        zorder=195,
    )
    ax.plot(
        zigzag_x[:-1],
        zigzag_y[:-1],
        color=GREEN,
        linewidth=2.0,
        linestyle="-",
        solid_capstyle="round",
        zorder=195,
    )

    saddle_circle = Circle(
        (sx[0], sy[0]),
        radii["C"] * 0.85,
        fill=True,
        facecolor=GREEN,
        alpha=0.35,
        edgecolor=GREEN,
        linewidth=1.8,
        zorder=205,
    )
    ax.add_patch(saddle_circle)
    ax.annotate(
        "TS",
        (sx[0], sy[0] + 0.35),
        fontsize=8,
        fontweight="bold",
        color=GREEN,
        ha="center",
        zorder=206,
    )

    pad = 0.6
    ax.set_xlim(x2d.min() - pad, x2d.max() + pad)
    ax.set_ylim(y2d.min() - pad, y2d.max() + pad)

    ax.text(
        x2d.min() - pad + 0.1,
        y2d.max() + pad - 0.1,
        "(c)  WC hexagonal  [001]",
        fontsize=11,
        fontweight="bold",
    )

    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=DARK_GRAY, markersize=12, label="W"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=WHITE, markeredgecolor=GREEN, markeredgewidth=1.5, markersize=8, label="C"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", fontsize=9, framealpha=0.85)

    out_path = str(OUT_DIR / "panel_c_crystal.png")
    fig.savefig(out_path, dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Panel (c) Crystal: {out_path}")
    return out_path


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    apply_aps_style()
    print("=" * 60)
    print("Generating vacancy-migration panels via Crystal MCP (ASE+mpl)")
    print("=" * 60)

    a = panel_a()
    b = panel_b()
    c = panel_c()

    print("\n── All Crystal MCP panels complete ──")
    print(f"  (a) {a}")
    print(f"  (b) {b}")
    print(f"  (c) {c}")
