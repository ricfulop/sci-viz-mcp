#!/usr/bin/env python3
"""
Ordered Defect Condensation — standing-wave template panels.

Visualizes the d* = 2.21 Ω^(1/3) acoustic template on three lattice types,
showing how commensurability (d*/a) selects qualitatively different ordering:
  (a) Fluorite ZrO₂  d*/a = 0.97  → commensurate epitaxial ordering
  (b) BCC W           d*/a = 1.75  → incommensurate filamentary coarsening
  (c) Hexagonal WC    d*/a = 1.66  → incommensurate basal-plane void sheets

Uses ASE for structure building and matplotlib for 2D schematic projection
(Crystal MCP approach — full annotation control).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import ase.io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, Ellipse, Rectangle, FancyBboxPatch
from matplotlib.collections import PatchCollection
from matplotlib.lines import Line2D
import matplotlib.colors as mcolors
import matplotlib.patheffects as pe

from styles import apply_aps_style, MATERIALS, APS_DOUBLE, _APS_RCPARAMS

CIF_DIR = Path(__file__).parent.parent / "tests" / "sample_structures"
OUT_DIR = Path(__file__).parent.parent / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Okabe-Ito bonding-class colors
IONIC_BLUE  = "#0072B2"
METAL_ORANGE = "#D55E00"
COVAL_GREEN = "#009E73"
GOLD        = "#FFB800"
GOLD_LIGHT  = "#FFE066"
GRAY        = "#999999"
DARK_GRAY   = "#555555"
LIGHT_GRAY  = "#C8C8C8"
WHITE       = "#FFFFFF"
BG          = "#FAFAFA"


def _project_2d(positions, projection="001"):
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
    return pts @ x_axis, pts @ y_axis, pts @ normal


def _draw_cell_box(ax, cell, projection="001", **kwargs):
    corners_frac = np.array([
        [0,0,0],[1,0,0],[1,1,0],[0,1,0],
        [0,0,1],[1,0,1],[1,1,1],[0,1,1],
    ], dtype=float)
    corners = corners_frac @ cell
    x, y, _ = _project_2d(corners, projection)
    edges = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),
             (0,4),(1,5),(2,6),(3,7)]
    kw = dict(color="#BBBBBB", linewidth=0.5, linestyle="-", alpha=0.5, zorder=1)
    kw.update(kwargs)
    for i, j in edges:
        ax.plot([x[i], x[j]], [y[i], y[j]], **kw)


def _draw_standing_wave_band(ax, x_range, y_range, d_star, accent_color,
                             alpha_max=0.18, n_pts=500, phase_offset=0.0):
    """Draw semi-transparent vertical bands at antinode positions of the
    acoustic standing wave with wavelength d*."""
    x_lo, x_hi = x_range
    xs = np.linspace(x_lo, x_hi, n_pts)
    for xi in xs:
        phase = np.sin(2 * np.pi * (xi - phase_offset) / d_star)
        intensity = phase ** 2
        if intensity > 0.05:
            ax.axvline(xi, ymin=0, ymax=1, color=accent_color,
                       alpha=alpha_max * intensity, linewidth=1.2, zorder=2)


def _draw_standing_wave_curve(ax, x_range, y_top, d_star, amplitude,
                              accent_color, label=None, phase_offset=0.0):
    """Draw the sinusoidal displacement curve u(x) above the lattice."""
    xs = np.linspace(x_range[0], x_range[1], 400)
    ys = y_top + amplitude * np.sin(2 * np.pi * (xs - phase_offset) / d_star)
    ax.plot(xs, ys, color=accent_color, linewidth=1.5, zorder=50, alpha=0.9)
    ax.axhline(y_top, xmin=0, xmax=1, color=accent_color, linewidth=0.4,
               linestyle=":", alpha=0.4, zorder=49)
    if label:
        ax.text(x_range[1] + 0.3, y_top, label, fontsize=10, color=accent_color,
                va="center", fontstyle="italic")


def _draw_antinode_markers(ax, antinode_xs, y_range, accent_color):
    """Draw dashed vertical lines at antinode positions."""
    for xi in antinode_xs:
        ax.axvline(xi, ymin=0, ymax=1, color=accent_color,
                   linewidth=0.7, linestyle="--", alpha=0.35, zorder=3)


def _draw_atoms(ax, x2d, y2d, depth, symbols, fill_colors, radii,
                rim_colors=None, rim_width=1.2, alpha=1.0):
    order = np.argsort(depth)
    for idx in order:
        s = symbols[idx]
        r = radii.get(s, 0.2)
        fc = fill_colors.get(s, GRAY)
        rc = rim_colors.get(s, "black") if rim_colors else "black"
        lw = rim_width if (rim_colors and s in rim_colors) else 0.4
        circle = Circle((x2d[idx], y2d[idx]), r,
                        facecolor=fc, edgecolor=rc, linewidth=lw,
                        zorder=50 + depth[idx], alpha=alpha)
        ax.add_patch(circle)


ELECTRON_CYAN = "#00C8FF"
INTERSTITIAL_MAGENTA = "#CC79A7"


def _vacancy_marker(ax, x, y, r, accent_color, label=None, fontsize=9):
    """Dashed circle for vacancy site with optional Kroger-Vink label.
    Uses a fine custom dash pattern so the dashes are visible even on
    small circles."""
    r_vis = max(r, 0.32)
    c = Circle((x, y), r_vis, fill=True, facecolor=GOLD_LIGHT, alpha=0.50,
               edgecolor=accent_color, linewidth=2.0, linestyle=(0, (2, 1.5)),
               zorder=200)
    ax.add_patch(c)
    if label:
        ax.text(x, y, label, fontsize=fontsize, fontweight="bold",
                color=accent_color, ha="center", va="center", zorder=201)


def _draw_2deg_channel(ax, vac_xs, vac_ys, y_lo, y_hi, accent_color,
                       channel_width=0.30):
    """Draw electron-flow path threading through each vacancy site
    left-to-right, representing the percolating 2DEG defect band."""
    if len(vac_xs) < 2:
        return

    pts = np.column_stack([vac_xs, vac_ys])
    order = np.argsort(pts[:, 0])
    pts = pts[order]

    x_lo_ext = pts[0, 0] - 2.5
    x_hi_ext = pts[-1, 0] + 2.5
    ext_l = np.array([[x_lo_ext, pts[0, 1]]])
    ext_r = np.array([[x_hi_ext, pts[-1, 1]]])
    pts = np.vstack([ext_l, pts, ext_r])

    from scipy.interpolate import make_interp_spline
    try:
        t_param = np.linspace(0, 1, len(pts))
        t_fine = np.linspace(0, 1, 300)
        spl_x = make_interp_spline(t_param, pts[:, 0], k=min(3, len(pts) - 1))
        spl_y = make_interp_spline(t_param, pts[:, 1], k=min(3, len(pts) - 1))
        xs = spl_x(t_fine)
        ys = spl_y(t_fine)
    except Exception:
        xs = pts[:, 0]
        ys = pts[:, 1]

    ax.fill_between(xs, ys - channel_width, ys + channel_width,
                    color=ELECTRON_CYAN, alpha=0.07, zorder=5)
    ax.plot(xs, ys, color=ELECTRON_CYAN, linewidth=1.6, alpha=0.40,
            zorder=160, solid_capstyle="round")

    n_chev = min(len(vac_xs) + 2, 6)
    chev_idxs = np.linspace(30, len(xs) - 30, n_chev, dtype=int)
    chev_size = 0.28
    for ci in chev_idxs:
        if ci + 2 < len(xs):
            dx = xs[min(ci + 3, len(xs) - 1)] - xs[max(ci - 3, 0)]
            dy = ys[min(ci + 3, len(xs) - 1)] - ys[max(ci - 3, 0)]
            ang = np.arctan2(dy, dx)
            cx, cy = xs[ci], ys[ci]
            tri_x = [cx + chev_size * np.cos(ang),
                     cx + chev_size * 0.6 * np.cos(ang + 2.4),
                     cx + chev_size * 0.6 * np.cos(ang - 2.4)]
            tri_y = [cy + chev_size * np.sin(ang),
                     cy + chev_size * 0.6 * np.sin(ang + 2.4),
                     cy + chev_size * 0.6 * np.sin(ang - 2.4)]
            ax.fill(tri_x, tri_y, color=ELECTRON_CYAN, alpha=0.7, zorder=166)

    mid = len(xs) // 2
    ax.text(xs[mid], ys[mid] - channel_width - 0.30,
            r"$e^-$", fontsize=9, color=ELECTRON_CYAN,
            ha="center", va="top", fontweight="bold", alpha=0.8, zorder=170)


def _draw_expelled_interstitials(ax, vac_xs, vac_ys,
                                 all_x2d, all_y2d, all_symbols,
                                 ref_species, accent_color, radius=0.18):
    """Place interstitial in the cage of ref_species atoms nearest each
    vacancy.  For ionic: ref_species = cation species (Zr) so O_i goes
    between Zr.  For WC: ref_species = W so C_i goes between W.
    For BCC metals: ref_species = same species (nearest-neighbor cage)."""
    chev = 0.22
    same_mask = np.array([s == ref_species for s in all_symbols])
    same_x = all_x2d[same_mask]
    same_y = all_y2d[same_mask]

    for vx, vy in zip(vac_xs, vac_ys):
        dists = np.sqrt((same_x - vx)**2 + (same_y - vy)**2)
        sorted_idx = np.argsort(dists)
        nbr1 = sorted_idx[1] if dists[sorted_idx[0]] < 0.01 else sorted_idx[0]
        nbr2 = sorted_idx[2] if dists[sorted_idx[0]] < 0.01 else sorted_idx[1]

        mid_x = (same_x[nbr1] + same_x[nbr2]) / 2
        mid_y = (same_y[nbr1] + same_y[nbr2]) / 2

        outward_dx = mid_x - vx
        outward_dy = mid_y - vy
        norm = max(np.sqrt(outward_dx**2 + outward_dy**2), 0.01)
        push = 0.15
        ix = mid_x + push * outward_dx / norm
        iy = mid_y + push * outward_dy / norm

        c = Circle((ix, iy), radius, facecolor=INTERSTITIAL_MAGENTA,
                    edgecolor=accent_color, linewidth=0.8, alpha=0.75,
                    zorder=210)
        ax.add_patch(c)

        angle = np.arctan2(iy - vy, ix - vx)
        tip_x = ix + chev * 1.1 * np.cos(angle)
        tip_y = iy + chev * 1.1 * np.sin(angle)
        tri_x = [tip_x,
                 ix + chev * 0.55 * np.cos(angle + 2.2),
                 ix + chev * 0.55 * np.cos(angle - 2.2)]
        tri_y = [tip_y,
                 iy + chev * 0.55 * np.sin(angle + 2.2),
                 iy + chev * 0.55 * np.sin(angle - 2.2)]
        ax.fill(tri_x, tri_y, color=INTERSTITIAL_MAGENTA,
                alpha=0.7, zorder=215)


# ═══════════════════════════════════════════════════════════════════════════════
# Panel (a): Fluorite ZrO₂ — commensurate (d*/a = 0.97)
# ═══════════════════════════════════════════════════════════════════════════════

def panel_a(ax):
    atoms = ase.io.read(str(CIF_DIR / "fluorite_ZrO2.cif"))
    sc = atoms.repeat([5, 5, 1])
    a_lat = 5.145

    N_at = 12
    V_cell = a_lat ** 3
    omega = V_cell / N_at
    d_star = 2.21 * omega ** (1.0 / 3.0)
    dstar_over_a = d_star / a_lat

    symbols = list(sc.get_chemical_symbols())
    positions = sc.positions.copy()
    cell = sc.cell[:]
    x2d, y2d, depth = _project_2d(positions, "001")

    o_mask = np.array([s == "O" for s in symbols])
    zr_mask = np.array([s == "Zr" for s in symbols])

    pad = 1.0
    x_lo, x_hi = x2d.min() - pad, x2d.max() + pad
    y_lo, y_hi = y2d.min() - pad, y2d.max() + pad + 3.5
    ax.set_xlim(x_lo, x_hi)
    ax.set_ylim(y_lo, y_hi)
    ax.set_aspect("equal")
    ax.axis("off")

    _draw_cell_box(ax, cell, "001")

    # Phase wave to an O sublattice column
    o_x = x2d[o_mask]
    o_y = y2d[o_mask]
    o_idx_global = np.where(o_mask)[0]
    o_x_cols = np.unique(np.round(o_x, 1))
    phase_off = o_x_cols[len(o_x_cols) // 4] - 0.25 * d_star

    _draw_standing_wave_band(ax, (x2d.min(), x2d.max()),
                             (y2d.min(), y2d.max()), d_star, GOLD,
                             alpha_max=0.12, phase_offset=phase_off)
    wave_y = y2d.max() + 2.0
    _draw_standing_wave_curve(ax, (x2d.min(), x2d.max()), wave_y, d_star,
                              amplitude=0.8, accent_color=GOLD,
                              phase_offset=phase_off)

    # Shannon ionic radii: O²⁻ (1.38 Å) > Zr⁴⁺ (0.84 Å)
    fill_colors = {"Zr": GRAY, "O": WHITE}
    radii = {"Zr": 0.28, "O": 0.46}
    rim_colors = {"Zr": "#666666", "O": IONIC_BLUE}

    # 2D depleted region: band 3 O-rows thick at lattice center (~40% V_O)
    y_mid = np.mean(o_y)
    band_half = a_lat * 0.8
    in_band = (o_y > y_mid - band_half) & (o_y < y_mid + band_half)
    np.random.seed(42)
    in_band_idx = np.where(in_band)[0]
    deplete_frac = 0.45
    n_deplete = int(len(in_band_idx) * deplete_frac)
    deplete_local = np.random.choice(len(in_band_idx), n_deplete, replace=False)
    vac_local_in_o = in_band_idx[deplete_local]
    vac_indices = o_idx_global[vac_local_in_o]

    # Draw the 2DEG band (semi-transparent cyan rectangle over depleted region)
    band_y_lo = y_mid - band_half - 0.3
    band_y_hi = y_mid + band_half + 0.3
    band_rect = Rectangle((x2d.min() - 0.5, band_y_lo),
                           x2d.max() - x2d.min() + 1.0,
                           band_y_hi - band_y_lo,
                           facecolor=ELECTRON_CYAN, alpha=0.06,
                           edgecolor=ELECTRON_CYAN, linewidth=1.0,
                           linestyle="-", zorder=4)
    ax.add_patch(band_rect)

    # Draw atoms: depleted O as faded, intact O normal
    deplete_set = set(vac_indices.tolist())
    order = np.argsort(depth)
    for idx in order:
        s = symbols[idx]
        r = radii.get(s, 0.2)
        fc = fill_colors.get(s, GRAY)
        rc = rim_colors.get(s, "black")
        lw = 1.2 if s in rim_colors else 0.4
        if idx in deplete_set:
            c = Circle((x2d[idx], y2d[idx]), r, facecolor=GOLD_LIGHT,
                        edgecolor=IONIC_BLUE, linewidth=1.6,
                        linestyle=(0, (2, 1.5)), alpha=0.4,
                        zorder=50 + depth[idx])
        else:
            c = Circle((x2d[idx], y2d[idx]), r, facecolor=fc,
                        edgecolor=rc, linewidth=lw,
                        zorder=50 + depth[idx])
        ax.add_patch(c)

    # Label a few representative vacancies
    label_vacs = vac_indices[::max(1, len(vac_indices) // 3)][:3]
    for vi in label_vacs:
        ax.text(x2d[vi], y2d[vi], r"$V_{\!O}$", fontsize=8,
                fontweight="bold", color=IONIC_BLUE, ha="center",
                va="center", zorder=201)

    # e⁻ flow chevrons across the band
    chev_ys = np.linspace(band_y_lo + 0.8, band_y_hi - 0.8, 3)
    chev_xs = np.linspace(x2d.min() + 2, x2d.max() - 2, 5)
    chev_size = 0.30
    for cy in chev_ys:
        for cx in chev_xs:
            tri_x = [cx + chev_size, cx - chev_size * 0.5, cx - chev_size * 0.5]
            tri_y = [cy, cy + chev_size * 0.5, cy - chev_size * 0.5]
            ax.fill(tri_x, tri_y, color=ELECTRON_CYAN, alpha=0.5, zorder=160)

    ax.text(x2d.mean(), band_y_lo - 0.4, r"$e^-$ 2DEG channel",
            fontsize=9, color=ELECTRON_CYAN, ha="center", va="top",
            fontweight="bold", alpha=0.8, zorder=170)

    # Interstitials expelled above and below the band
    edge_vacs_top = vac_indices[o_y[vac_local_in_o] > y_mid][:3]
    edge_vacs_bot = vac_indices[o_y[vac_local_in_o] < y_mid][:3]
    zr_x, zr_y = x2d[zr_mask], y2d[zr_mask]
    for vi in np.concatenate([edge_vacs_top[:2], edge_vacs_bot[:2]]):
        _draw_expelled_interstitials(
            ax, [x2d[vi]], [y2d[vi]], x2d, y2d, symbols, "Zr",
            IONIC_BLUE, radius=0.18)

    ax.text(x_lo + 0.3, y_hi - 0.3,
            r"$\mathbf{(a)}$  ZrO$_2$ fluorite  [001]",
            fontsize=11, fontweight="bold", va="top")

    bbox = dict(boxstyle="round,pad=0.25", facecolor=GOLD_LIGHT, alpha=0.35,
                edgecolor=GOLD, linewidth=0.6)
    ax.text(x_lo + 0.3, y_hi - 1.8,
            f"$d^*/a = {dstar_over_a:.2f}$\nCommensurate\nEpitaxial ordering",
            fontsize=9, ha="left", va="top", bbox=bbox, color="#333333",
            linespacing=1.4)
    ax.text(x_hi - 0.3, wave_y, r"$u(x)$", fontsize=10, color=GOLD,
            ha="left", va="center", fontstyle="italic")

    # Inset: fluorite → rocksalt
    inset_x0, inset_y0 = x_hi - 7.5, y_lo + 0.3
    inset_w, inset_h = 7.0, 3.0
    inset_rect = FancyBboxPatch((inset_x0, inset_y0), inset_w, inset_h,
                                 boxstyle="round,pad=0.15",
                                 facecolor=WHITE, edgecolor="#AAAAAA",
                                 linewidth=0.6, alpha=0.92, zorder=300)
    ax.add_patch(inset_rect)
    ix, iy = inset_x0 + 0.4, inset_y0 + inset_h * 0.55
    for i in range(3):
        cx = ix + i * 1.5
        ax.add_patch(Circle((cx, iy), 0.20, facecolor=GRAY, edgecolor="#666",
                            linewidth=0.4, zorder=310))
        ax.add_patch(Circle((cx + 0.7, iy + 0.55), 0.32, facecolor=WHITE,
                            edgecolor=IONIC_BLUE, linewidth=0.8, zorder=309))
        ax.add_patch(Circle((cx + 0.7, iy - 0.55), 0.32, facecolor=WHITE,
                            edgecolor=IONIC_BLUE, linewidth=0.8, zorder=309))
    arr_x = ix + 3 * 1.5 + 0.1
    ax.annotate("", xy=(arr_x + 0.7, iy), xytext=(arr_x, iy),
                arrowprops=dict(arrowstyle="->", color=IONIC_BLUE, lw=1.5),
                zorder=320)
    rx = arr_x + 1.0
    for i in range(2):
        cx = rx + i * 1.0
        ax.add_patch(Circle((cx, iy), 0.20, facecolor="#B0B0B0",
                            edgecolor="#666", linewidth=0.4, zorder=310, alpha=0.6))
        ax.add_patch(Circle((cx + 0.5, iy), 0.28, facecolor="#E0E0E0",
                            edgecolor=IONIC_BLUE, linewidth=0.8, zorder=309, alpha=0.6))
    ax.text(inset_x0 + inset_w / 2, inset_y0 + 0.2,
            r"Fluorite $\to$ Rocksalt ($-8\%$)",
            fontsize=8, ha="center", va="bottom", color=IONIC_BLUE,
            fontstyle="italic", zorder=320)


# ═══════════════════════════════════════════════════════════════════════════════
# Panel (b): BCC W — incommensurate (d*/a = 1.75)
# ═══════════════════════════════════════════════════════════════════════════════

def panel_b(ax):
    atoms = ase.io.read(str(CIF_DIR / "bcc_W.cif"))
    sc = atoms.repeat([6, 6, 1])
    a_lat = 3.165

    N_at = 2
    V_cell = a_lat ** 3
    omega = V_cell / N_at
    d_star = 2.21 * omega ** (1.0 / 3.0)
    dstar_over_a = d_star / a_lat

    symbols = list(sc.get_chemical_symbols())
    positions = sc.positions.copy()
    cell = sc.cell[:]
    x2d, y2d, depth = _project_2d(positions, "001")

    pad = 1.0
    x_lo, x_hi = x2d.min() - pad, x2d.max() + pad
    y_lo, y_hi = y2d.min() - pad, y2d.max() + pad + 3.5
    ax.set_xlim(x_lo, x_hi)
    ax.set_ylim(y_lo, y_hi)
    ax.set_aspect("equal")
    ax.axis("off")

    _draw_cell_box(ax, cell, "001")
    _draw_standing_wave_band(ax, (x2d.min(), x2d.max()),
                             (y2d.min(), y2d.max()), d_star, GOLD, alpha_max=0.12)
    wave_y = y2d.max() + 2.0
    _draw_standing_wave_curve(ax, (x2d.min(), x2d.max()), wave_y, d_star,
                              amplitude=0.8, accent_color=GOLD)

    fill_colors = {"W": GRAY}
    radii = {"W": 0.42}
    rim_colors = {"W": METAL_ORANGE}

    # Dendritic vacancy cluster: grow from center, ~10 atoms, branching
    center = np.array([np.mean(x2d), np.mean(y2d)])
    dists_c = np.sqrt((x2d - center[0])**2 + (y2d - center[1])**2)
    seed = np.argmin(dists_c)
    np.random.seed(7)
    cluster = [seed]
    for _ in range(11):
        frontier = []
        for ci in cluster:
            d = np.sqrt((x2d - x2d[ci])**2 + (y2d - y2d[ci])**2)
            nbrs = np.where((d > 0.1) & (d < a_lat * 1.2))[0]
            for nb in nbrs:
                if nb not in cluster:
                    frontier.append(nb)
        if not frontier:
            break
        chosen = frontier[np.random.randint(len(frontier))]
        cluster.append(chosen)
    vac_indices = cluster

    deplete_set = set(vac_indices)
    order = np.argsort(depth)
    for idx in order:
        s = symbols[idx]
        r = radii.get(s, 0.2)
        if idx in deplete_set:
            c = Circle((x2d[idx], y2d[idx]), r, facecolor=GOLD_LIGHT,
                        edgecolor=METAL_ORANGE, linewidth=1.6,
                        linestyle=(0, (2, 1.5)), alpha=0.4,
                        zorder=50 + depth[idx])
        else:
            c = Circle((x2d[idx], y2d[idx]), r, facecolor=GRAY,
                        edgecolor=METAL_ORANGE, linewidth=1.2,
                        zorder=50 + depth[idx])
        ax.add_patch(c)

    # 2DEG band: convex hull of cluster + buffer
    from scipy.spatial import ConvexHull
    vac_pts = np.column_stack([[x2d[v] for v in vac_indices],
                                [y2d[v] for v in vac_indices]])
    if len(vac_pts) >= 3:
        hull = ConvexHull(vac_pts)
        hull_x = vac_pts[hull.vertices, 0]
        hull_y = vac_pts[hull.vertices, 1]
        hull_x = np.append(hull_x, hull_x[0])
        hull_y = np.append(hull_y, hull_y[0])
        ax.fill(hull_x, hull_y, facecolor=ELECTRON_CYAN, alpha=0.08, zorder=4)
        ax.plot(hull_x, hull_y, color=ELECTRON_CYAN, linewidth=1.2,
                alpha=0.4, zorder=5)

    # Chevrons showing e⁻ flow through the cluster
    vac_x_arr = np.array([x2d[v] for v in vac_indices])
    vac_y_arr = np.array([y2d[v] for v in vac_indices])
    sort_x = np.argsort(vac_x_arr)
    chev_size = 0.28
    for i in range(0, len(sort_x) - 1, 2):
        cx = (vac_x_arr[sort_x[i]] + vac_x_arr[sort_x[min(i+1, len(sort_x)-1)]]) / 2
        cy = (vac_y_arr[sort_x[i]] + vac_y_arr[sort_x[min(i+1, len(sort_x)-1)]]) / 2
        tri_x = [cx + chev_size, cx - chev_size * 0.5, cx - chev_size * 0.5]
        tri_y = [cy, cy + chev_size * 0.5, cy - chev_size * 0.5]
        ax.fill(tri_x, tri_y, color=ELECTRON_CYAN, alpha=0.5, zorder=160)

    label_vacs = vac_indices[:3]
    for vi in label_vacs:
        ax.text(x2d[vi], y2d[vi], r"$V_{\!W}$", fontsize=8,
                fontweight="bold", color=METAL_ORANGE, ha="center",
                va="center", zorder=201)

    ax.text(vac_x_arr.mean(), vac_y_arr.max() + 1.0,
            r"$e^-$ 2DEG", fontsize=9, color=ELECTRON_CYAN,
            ha="center", fontweight="bold", alpha=0.8, zorder=170)

    # Interstitials expelled from cluster edges
    edge_vacs = [vac_indices[i] for i in hull.vertices[:4]] if len(vac_pts) >= 3 else vac_indices[:3]
    for vi in edge_vacs:
        _draw_expelled_interstitials(
            ax, [x2d[vi]], [y2d[vi]], x2d, y2d, symbols, "W",
            METAL_ORANGE, radius=0.18)

    ax.text(x_lo + 0.3, y_hi - 0.3, r"$\mathbf{(b)}$  BCC W  [001]",
            fontsize=11, fontweight="bold", va="top")
    bbox = dict(boxstyle="round,pad=0.25", facecolor=GOLD_LIGHT, alpha=0.35,
                edgecolor=GOLD, linewidth=0.6)
    ax.text(x_lo + 0.3, y_hi - 1.8,
            f"$d^*/a = {dstar_over_a:.2f}$\nIncommensurate\nFilamentary coarsening",
            fontsize=9, ha="left", va="top", bbox=bbox, color="#333333",
            linespacing=1.4)
    ax.text(x_hi - 0.3, wave_y, r"$u(x)$", fontsize=10, color=GOLD,
            ha="left", va="center", fontstyle="italic")


# ═══════════════════════════════════════════════════════════════════════════════
# Panel (c): Hexagonal WC — formation bottleneck (d*/a ≈ 1.66)
# ═══════════════════════════════════════════════════════════════════════════════

def panel_c(ax):
    atoms = ase.io.read(str(CIF_DIR / "hexagonal_WC.cif"))
    sc = atoms.repeat([4, 7, 1])
    a_lat = 2.906
    c_lat = 2.837

    N_at = 2
    V_cell = a_lat ** 2 * np.sin(np.radians(120)) * c_lat
    omega = V_cell / N_at
    d_star = 2.21 * omega ** (1.0 / 3.0)
    dstar_over_a = d_star / a_lat

    symbols = list(sc.get_chemical_symbols())
    positions = sc.positions.copy()
    cell = sc.cell[:]
    x2d, y2d, depth = _project_2d(positions, "001")

    c_mask = np.array([s == "C" for s in symbols])
    w_mask = np.array([s == "W" for s in symbols])
    c_idx_global = np.where(c_mask)[0]

    pad = 1.0
    x_lo, x_hi = x2d.min() - pad, x2d.max() + pad
    y_lo, y_hi = y2d.min() - pad, y2d.max() + pad + 3.5
    ax.set_xlim(x_lo, x_hi)
    ax.set_ylim(y_lo, y_hi)
    ax.set_aspect("equal")
    ax.axis("off")

    _draw_cell_box(ax, cell, "001")
    _draw_standing_wave_band(ax, (x2d.min(), x2d.max()),
                             (y2d.min(), y2d.max()), d_star, GOLD, alpha_max=0.12)
    wave_y = y2d.max() + 2.0
    _draw_standing_wave_curve(ax, (x2d.min(), x2d.max()), wave_y, d_star,
                              amplitude=0.8, accent_color=GOLD)

    fill_colors = {"W": DARK_GRAY, "C": WHITE}
    radii = {"W": 0.46, "C": 0.22}
    rim_colors = {"W": "#444444", "C": COVAL_GREEN}

    # Basal-plane void sheet: deplete C atoms in a horizontal band
    c_x = x2d[c_mask]
    c_y = y2d[c_mask]
    y_mid = np.mean(c_y)
    band_half = a_lat * 0.6
    in_band = (c_y > y_mid - band_half) & (c_y < y_mid + band_half)
    np.random.seed(33)
    in_band_idx = np.where(in_band)[0]
    deplete_frac = 0.55
    n_deplete = int(len(in_band_idx) * deplete_frac)
    deplete_local = np.random.choice(len(in_band_idx), n_deplete, replace=False)
    vac_local_in_c = in_band_idx[deplete_local]
    vac_indices = c_idx_global[vac_local_in_c]

    # 2DEG band across depleted sheet
    band_y_lo = y_mid - band_half - 0.2
    band_y_hi = y_mid + band_half + 0.2
    band_rect = Rectangle((x2d.min() - 0.5, band_y_lo),
                           x2d.max() - x2d.min() + 1.0,
                           band_y_hi - band_y_lo,
                           facecolor=ELECTRON_CYAN, alpha=0.06,
                           edgecolor=ELECTRON_CYAN, linewidth=1.0,
                           zorder=4)
    ax.add_patch(band_rect)

    deplete_set = set(vac_indices.tolist())
    order = np.argsort(depth)
    for idx in order:
        s = symbols[idx]
        r = radii.get(s, 0.2)
        fc = fill_colors.get(s, GRAY)
        rc = rim_colors.get(s, "black")
        lw = 1.2 if s in rim_colors else 0.4
        if idx in deplete_set:
            c = Circle((x2d[idx], y2d[idx]), r, facecolor=GOLD_LIGHT,
                        edgecolor=COVAL_GREEN, linewidth=1.6,
                        linestyle=(0, (2, 1.5)), alpha=0.4,
                        zorder=50 + depth[idx])
        else:
            c = Circle((x2d[idx], y2d[idx]), r, facecolor=fc,
                        edgecolor=rc, linewidth=lw,
                        zorder=50 + depth[idx])
        ax.add_patch(c)

    label_vacs = vac_indices[::max(1, len(vac_indices) // 3)][:3]
    for vi in label_vacs:
        ax.text(x2d[vi], y2d[vi], r"$V_{\!C}$", fontsize=8,
                fontweight="bold", color=COVAL_GREEN, ha="center",
                va="center", zorder=201)

    # e⁻ chevrons across the band
    chev_ys = [y_mid]
    chev_xs = np.linspace(x2d[c_mask].min() + 1, x2d[c_mask].max() - 1, 4)
    chev_size = 0.25
    for cy in chev_ys:
        for cx in chev_xs:
            tri_x = [cx + chev_size, cx - chev_size * 0.5, cx - chev_size * 0.5]
            tri_y = [cy, cy + chev_size * 0.5, cy - chev_size * 0.5]
            ax.fill(tri_x, tri_y, color=ELECTRON_CYAN, alpha=0.5, zorder=160)

    ax.text(x2d[c_mask].mean(), band_y_lo - 0.4,
            r"$e^-$ 2DEG", fontsize=9, color=ELECTRON_CYAN,
            ha="center", va="top", fontweight="bold", alpha=0.8, zorder=170)

    # Interstitials expelled from band edges
    edge_top = vac_indices[c_y[vac_local_in_c] > y_mid][:2]
    edge_bot = vac_indices[c_y[vac_local_in_c] < y_mid][:2]
    for vi in np.concatenate([edge_top, edge_bot]):
        _draw_expelled_interstitials(
            ax, [x2d[vi]], [y2d[vi]], x2d, y2d, symbols, "W",
            COVAL_GREEN, radius=0.14)

    ax.text(x_lo + 0.3, y_hi - 0.3,
            r"$\mathbf{(c)}$  WC hexagonal  [001]",
            fontsize=11, fontweight="bold", va="top")
    bbox = dict(boxstyle="round,pad=0.25", facecolor=GOLD_LIGHT, alpha=0.35,
                edgecolor=GOLD, linewidth=0.6)
    ax.text(x_lo + 0.3, y_hi - 1.8,
            f"$d^*/a = {dstar_over_a:.2f}$\nIncommensurate\nBasal-plane void sheets",
            fontsize=9, ha="left", va="top", bbox=bbox, color="#333333",
            linespacing=1.4)
    ax.text(x_hi - 0.3, wave_y, r"$u(x)$", fontsize=10, color=GOLD,
            ha="left", va="center", fontstyle="italic")

    # Inset: E_defect bar chart
    inset_x0, inset_y0 = x_hi - 7.0, y_lo + 0.3
    inset_w, inset_h = 6.5, 3.2
    inset_rect = FancyBboxPatch((inset_x0, inset_y0), inset_w, inset_h,
                                 boxstyle="round,pad=0.15",
                                 facecolor=WHITE, edgecolor="#AAAAAA",
                                 linewidth=0.6, alpha=0.92, zorder=300)
    ax.add_patch(inset_rect)
    bar_x0 = inset_x0 + 0.6
    bar_w = 1.4
    bar_gap = 0.4
    bar_y0 = inset_y0 + 0.7
    materials = [("W", 0.3, METAL_ORANGE),
                 ("8YSZ", 0.5, IONIC_BLUE),
                 ("WC", 2.3, COVAL_GREEN)]
    scale = (inset_h - 1.4) / 2.5
    for i, (name, e_def, color) in enumerate(materials):
        bx = bar_x0 + i * (bar_w + bar_gap)
        bh = e_def * scale
        rect = Rectangle((bx, bar_y0), bar_w, bh, facecolor=color, alpha=0.5,
                          edgecolor=color, linewidth=0.8, zorder=310)
        ax.add_patch(rect)
        ax.text(bx + bar_w / 2, bar_y0 + bh + 0.15, f"{e_def} eV",
                fontsize=7, ha="center", va="bottom", color=color,
                fontweight="bold", zorder=320)
        ax.text(bx + bar_w / 2, bar_y0 - 0.2, name,
                fontsize=7, ha="center", va="top", color="#444", zorder=320)
    ax.text(inset_x0 + inset_w / 2, inset_y0 + 0.15,
            r"$E_{\mathrm{defect}}$",
            fontsize=8, ha="center", va="bottom", color=COVAL_GREEN,
            fontweight="bold", zorder=320)


# ═══════════════════════════════════════════════════════════════════════════════
# Composite figure
# ═══════════════════════════════════════════════════════════════════════════════

def make_composite():
    apply_aps_style()
    import matplotlib.gridspec as gridspec

    fig = plt.figure(figsize=(16.0, 6.0))
    gs = gridspec.GridSpec(1, 3, width_ratios=[1.05, 0.85, 1.1],
                           wspace=0.06, left=0.01, right=0.99,
                           top=0.95, bottom=0.06)

    ax_a = fig.add_subplot(gs[0])
    ax_b = fig.add_subplot(gs[1])
    ax_c = fig.add_subplot(gs[2])

    panel_a(ax_a)
    panel_b(ax_b)
    panel_c(ax_c)

    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=GRAY,
               markeredgecolor="#666", markersize=7, label="Cation (Zr / W)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=WHITE,
               markeredgecolor=IONIC_BLUE, markeredgewidth=1.0, markersize=5,
               label="Anion (O / C)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=GOLD_LIGHT,
               markeredgecolor=GOLD, markeredgewidth=1.0, markersize=6,
               linestyle="--", label=r"Vacancy at antinode"),
        Line2D([0], [0], color=GOLD, linewidth=1.5,
               label=r"Acoustic template $u(x) \propto \sin(2\pi x/d^*)$"),
        Line2D([0], [0], color=ELECTRON_CYAN, linewidth=1.5, alpha=0.7,
               label="2DEG channel (quasi-ballistic $e^-$)"),
        Line2D([0], [0], marker="o", color="w",
               markerfacecolor=INTERSTITIAL_MAGENTA, markeredgecolor="#888",
               markeredgewidth=0.5, markersize=5, alpha=0.8,
               label=r"Expelled interstitial ($\to$ matrix)"),
    ]
    fig.legend(handles=legend_elements, loc="lower center", ncol=3,
               fontsize=9, framealpha=0.9, edgecolor="#CCC", handlelength=2.2,
               bbox_to_anchor=(0.5, -0.02))

    fig.text(0.5, 0.99,
             r"Acoustic Template Commensurability: $d^* = 2.21\,\Omega^{1/3}$",
             ha="center", va="top", fontsize=12, fontweight="bold")

    out = str(OUT_DIR / "ordered_defect_panels.png")
    fig.savefig(out, dpi=400, bbox_inches="tight", facecolor="white")
    out_pdf = str(OUT_DIR / "ordered_defect_panels.pdf")
    fig.savefig(out_pdf, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Composite: {out}")
    print(f"           {out_pdf}")
    return out


def make_individual():
    apply_aps_style()
    for name, fn in [("a", panel_a), ("b", panel_b), ("c", panel_c)]:
        fig, ax = plt.subplots(figsize=(5.5, 5.5))
        fn(ax)
        out = str(OUT_DIR / f"ordered_panel_{name}.png")
        fig.savefig(out, dpi=400, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        print(f"Panel ({name}): {out}")


if __name__ == "__main__":
    print("=" * 60)
    print("Ordered Defect Condensation — standing-wave template panels")
    print("=" * 60)
    make_individual()
    make_composite()
    print("\nDone.")
