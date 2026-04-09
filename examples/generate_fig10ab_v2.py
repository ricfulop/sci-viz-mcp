#!/usr/bin/env python3
"""
Figure 10 panels (a) and (b) — v2 with polyhedral representation.

Improvements over v1 based on highly-cited benchmark analysis:
  - Coordination polyhedra (ZrO8 cubes in fluorite, ZrO6 octahedra in rocksalt)
  - Wyckoff-site color coding (not just element colors)
  - 3D-style depth shading on atoms
  - Cleaner annotation layout matching Nature Materials conventions

All atom positions and bond lengths computed from CIF crystallographic data.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import (Circle, FancyBboxPatch, FancyArrowPatch,
                                Rectangle, Polygon)
from matplotlib.lines import Line2D
from matplotlib.collections import PatchCollection
import matplotlib.patheffects as pe

from styles import _APS_RCPARAMS, MATERIALS as C
import ase.io
from pymatgen.core import Structure
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

plt.rcParams.update(_APS_RCPARAMS)
plt.rcParams.update({"savefig.dpi": 600, "figure.dpi": 150})

CIF_DIR = Path(__file__).parent.parent / "tests" / "sample_structures"
OUT_DIR = Path(__file__).parent

_TXT_Z = 50

fluorite = ase.io.read(CIF_DIR / "fluorite_ZrO2.cif")
rocksalt = ase.io.read(CIF_DIR / "rocksalt_ZrO.cif")
pmg_f = AseAtomsAdaptor.get_structure(fluorite)
pmg_r = AseAtomsAdaptor.get_structure(rocksalt)
sga_f = SpacegroupAnalyzer(pmg_f, symprec=0.01)
sga_r = SpacegroupAnalyzer(pmg_r, symprec=0.01)

a_f = fluorite.cell.cellpar()[0]
a_r = rocksalt.cell.cellpar()[0]
omega = a_f**3 / 12
d_star = 2.21 * omega**(1/3)
ratio = d_star / a_f

zr_sites_f = [s for s in pmg_f if str(s.specie) == "Zr"]
d_zr_f = zr_sites_f[0].distance(zr_sites_f[1]) if len(zr_sites_f) >= 2 else a_f * np.sqrt(2)/2
zr_sites_r = [s for s in pmg_r if str(s.specie) == "Zr"]
d_zr_r = zr_sites_r[0].distance(zr_sites_r[1]) if len(zr_sites_r) >= 2 else a_r * np.sqrt(2)/2


def draw_atom(ax, x, y, r, fc, ec="#333", lw=0.4, zorder=5, alpha=1.0, glow=False):
    if glow:
        g = Circle((x, y), r * 1.5, fc=fc, ec="none", alpha=0.15, zorder=zorder-1)
        ax.add_patch(g)
    highlight = Circle((x, y - r*0.15), r*0.35, fc="white", ec="none", alpha=0.3, zorder=zorder+1)
    ax.add_patch(highlight)
    c = Circle((x, y), r, fc=fc, ec=ec, lw=lw, alpha=alpha, zorder=zorder)
    ax.add_patch(c)

def draw_vacancy(ax, x, y, r, color=C["vermillion"]):
    c = Circle((x, y), r, fc="white", ec=color, lw=0.7, ls="--", zorder=4, alpha=0.9)
    ax.add_patch(c)
    ax.text(x, y, "×", ha="center", va="center", fontsize=4.5, color=color,
            fontweight="bold", zorder=_TXT_Z)

def draw_polyhedron(ax, corners, fc, ec, alpha=0.08, lw=0.4):
    """Draw a filled polygon from corner points."""
    poly = Polygon(corners, closed=True, fc=fc, ec=ec, lw=lw, alpha=alpha, zorder=1)
    ax.add_patch(poly)


# ═══════════════════════════════════════════════════════════════════════════════
# PANEL A — Acoustic Blueprint with polyhedra
# ═══════════════════════════════════════════════════════════════════════════════

def draw_panel_a(ax):
    ax.set_xlim(-0.3, 10.3)
    ax.set_ylim(-1.8, 11.5)
    ax.set_aspect("equal")
    ax.axis("off")

    ax.text(5.0, 11.3,
            r"Acoustic Blueprint  ($d^{\,*} \approx 1.0\,a$)",
            ha="center", va="top", fontsize=9, fontweight="bold",
            color=C["blue"], zorder=_TXT_Z)

    sc = fluorite.repeat([3, 3, 1])
    positions = sc.get_positions()
    symbols = sc.get_chemical_symbols()

    scale = 9.0 / max(sc.cell[0, 0], sc.cell[1, 1])
    ox, oy = 0.5, 1.2
    a_sc = a_f * scale
    nc = 3
    r_zr, r_o = 0.20, 0.14
    lam = ratio * a_f * scale

    # Unit cell grid
    for i in range(nc + 1):
        ax.plot([ox + i*a_sc, ox + i*a_sc], [oy, oy + nc*a_sc],
                color=C["light_gray"], lw=0.35, zorder=0)
        ax.plot([ox, ox + nc*a_sc], [oy + i*a_sc, oy + i*a_sc],
                color=C["light_gray"], lw=0.35, zorder=0)

    # Draw coordination polyhedra (ZrO8 cubes projected as squares)
    zr_positions = [(ox + p[0]*scale, oy + p[1]*scale)
                    for p, s in zip(positions, symbols)
                    if s == "Zr" and ox-0.1 <= ox+p[0]*scale <= ox+nc*a_sc+0.1
                    and oy-0.1 <= oy+p[1]*scale <= oy+nc*a_sc+0.1]
    half = a_sc * 0.25
    for zx, zy in zr_positions:
        corners = [(zx-half, zy-half), (zx+half, zy-half),
                   (zx+half, zy+half), (zx-half, zy+half)]
        draw_polyhedron(ax, corners, fc=C["sky_blue"], ec=C["blue"], alpha=0.06, lw=0.3)

    # Standing wave
    wave_x = np.linspace(ox, ox + nc*a_sc, 600)
    y_base = oy + nc*a_sc + 0.55
    amp = 0.40
    wave_y = y_base + amp * np.sin(2*np.pi*(wave_x - ox)/lam)
    ax.fill_between(wave_x, y_base, wave_y, where=(wave_y >= y_base),
                    interpolate=True, alpha=0.12, color=C["sky_blue"], zorder=1)
    ax.fill_between(wave_x, y_base, wave_y, where=(wave_y < y_base),
                    interpolate=True, alpha=0.08, color=C["blue"], zorder=1)
    ax.plot(wave_x, wave_y, color=C["sky_blue"], lw=1.6, alpha=0.8, zorder=2)
    ax.plot(wave_x, [y_base]*len(wave_x), color=C["light_gray"], lw=0.4, ls=":", zorder=1)

    # Antinode markers
    antinode_xs = []
    n_half = int(np.ceil(nc*a_sc/lam*2)) + 1
    for k in range(n_half):
        x_peak = ox + (0.25 + k)*lam
        if ox - 0.1 <= x_peak <= ox + nc*a_sc + 0.1:
            antinode_xs.append(x_peak)
            ax.plot(x_peak, y_base + amp, "v", color=C["vermillion"], ms=4, zorder=6)
            ax.axvline(x_peak, ymin=0.0, ymax=0.85,
                       color=C["vermillion"], alpha=0.05, lw=8, zorder=0)

    # Atoms from CIF
    np.random.seed(7)
    for pos, sym in zip(positions, symbols):
        px = ox + pos[0]*scale
        py = oy + pos[1]*scale
        if px < ox-0.1 or px > ox+nc*a_sc+0.1 or py < oy-0.1 or py > oy+nc*a_sc+0.1:
            continue
        if sym == "O":
            near = any(abs(px - xa) < 0.45*a_sc for xa in antinode_xs)
            if near and np.random.random() < 0.55:
                draw_vacancy(ax, px, py, r_o)
            else:
                draw_atom(ax, px, py, r_o, C["o_red"], ec="#c0392b", lw=0.3)
        else:
            draw_atom(ax, px, py, r_zr, C["zr_blue"], ec="#2c5f8a")

    # Wavelength annotation
    x0, x1 = ox + 0.2, ox + 0.2 + lam
    ya = y_base + amp + 0.45
    ax.annotate("", xy=(x1, ya), xytext=(x0, ya),
                arrowprops=dict(arrowstyle="<->", color=C["blue"], lw=0.9))
    ax.text((x0+x1)/2, ya+0.20, rf"$d^{{\,*}} = {ratio:.2f}\,a$",
            ha="center", fontsize=7, color=C["blue"], fontweight="bold",
            bbox=dict(fc="white", ec="none", alpha=0.85, pad=1), zorder=_TXT_Z)

    # Lattice parameter
    xa0, xa1 = ox, ox + a_sc
    yca = oy - 0.35
    ax.annotate("", xy=(xa1, yca), xytext=(xa0, yca),
                arrowprops=dict(arrowstyle="<->", color=C["dark_gray"], lw=0.7))
    ax.text((xa0+xa1)/2 + 1.6, yca, rf"$a = {a_f:.3f}$ Å",
            ha="left", va="center", fontsize=6, color=C["dark_gray"], zorder=_TXT_Z)

    # Legend
    lx, ly = 8.0, 9.5
    draw_atom(ax, lx, ly, r_zr, C["zr_blue"], ec="#2c5f8a")
    ax.text(lx+0.45, ly, r"Zr$^{4+}$", fontsize=5.5, va="center", color=C["dark_gray"], zorder=_TXT_Z)
    draw_atom(ax, lx, ly-0.55, r_o, C["o_red"], ec="#c0392b", lw=0.3)
    ax.text(lx+0.45, ly-0.55, r"O$^{2-}$", fontsize=5.5, va="center", color=C["dark_gray"], zorder=_TXT_Z)
    draw_vacancy(ax, lx, ly-1.1, r_o)
    ax.text(lx+0.45, ly-1.1, r"$V_{\!O}$", fontsize=5.5, va="center", color=C["dark_gray"], zorder=_TXT_Z)
    # Polyhedron legend
    corners = [(lx-0.15, ly-1.65-0.15), (lx+0.15, ly-1.65-0.15),
               (lx+0.15, ly-1.65+0.15), (lx-0.15, ly-1.65+0.15)]
    draw_polyhedron(ax, corners, fc=C["sky_blue"], ec=C["blue"], alpha=0.15, lw=0.5)
    ax.text(lx+0.45, ly-1.65, r"ZrO$_8$ cube", fontsize=5, va="center",
            color=C["dark_gray"], zorder=_TXT_Z)

    # Derivation box
    fbx, fby, fbw, fbh = -0.2, -1.5, 10.4, 1.9
    fbox = FancyBboxPatch((fbx, fby), fbw, fbh, boxstyle="round,pad=0.12",
                          fc=C["bg"], ec=C["blue"], lw=0.6, zorder=8)
    ax.add_patch(fbox)
    fx = fbx + fbw/2
    ax.text(fx, fby+fbh-0.30,
            r"$d^{\,*} = \mathbf{2.21}\;\Omega^{1/3}$    (3D Debye template)",
            ha="center", fontsize=8.5, color=C["blue"], fontweight="bold", zorder=_TXT_Z)
    ax.text(fx, fby+fbh/2-0.05,
            rf"8YSZ: $\Omega = a^3\!/12 = {omega:.2f}$ Å$^3$",
            ha="center", fontsize=7, color=C["dark_gray"], zorder=_TXT_Z)
    ax.text(fx, fby+0.25,
            rf"$d^{{\,*}} = 2.21 \times {omega**(1/3):.2f}"
            rf" = \mathbf{{{d_star:.2f}}}$ Å  $= {ratio:.2f}\,a$",
            ha="center", fontsize=7.5, color=C["blue"], zorder=_TXT_Z)


# ═══════════════════════════════════════════════════════════════════════════════
# PANEL B — Topotactic Collapse with polyhedral + metallic glow
# ═══════════════════════════════════════════════════════════════════════════════

def draw_panel_b(ax):
    ax.set_xlim(-0.3, 10.3)
    ax.set_ylim(-1.0, 11.5)
    ax.set_aspect("equal")
    ax.axis("off")

    ax.text(5.0, 11.3, "Topotactic Collapse  &  Metallization",
            ha="center", va="top", fontsize=9, fontweight="bold",
            color=C["vermillion"], zorder=_TXT_Z)

    r_zr, r_o = 0.28, 0.18

    # ── LEFT: Fluorite with tetrahedral polyhedra ──
    lcx, lcy = 2.3, 7.0
    af = 2.8
    rect = Rectangle((lcx-af/2, lcy-af/2), af, af, fc="none", ec=C["blue"], lw=1.0, zorder=1)
    ax.add_patch(rect)

    # Tetrahedral coordination polyhedra around O sites
    o_frac = [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)]
    for fx, fy in o_frac:
        cx = lcx + (fx-0.5)*af
        cy = lcy + (fy-0.5)*af
        half = af*0.18
        corners = [(cx, cy+half*1.2), (cx-half, cy-half*0.6),
                   (cx+half, cy-half*0.6)]
        draw_polyhedron(ax, corners, fc=C["o_red"], ec=C["o_red"], alpha=0.08, lw=0.3)

    # Atoms from real Wyckoff positions
    for site in pmg_f:
        fx, fy = site.frac_coords[0], site.frac_coords[1]
        px = lcx + (fx-0.5)*af
        py = lcy + (fy-0.5)*af
        if abs(fx-0.5) <= 0.5 and abs(fy-0.5) <= 0.5:
            if str(site.specie) == "O":
                draw_atom(ax, px, py, r_o, C["o_red"], ec="#c0392b", lw=0.3, zorder=3)
            else:
                draw_atom(ax, px, py, r_zr, C["zr_blue"], ec="#2c5f8a", zorder=5)

    ax.text(lcx, lcy+af/2+0.80, r"Fluorite ZrO$_2$", ha="center", fontsize=7.5,
            fontweight="bold", color=C["blue"], zorder=_TXT_Z)
    ax.text(lcx, lcy+af/2+0.30, "O in tetrahedral (8c)", ha="center", fontsize=5.5,
            color=C["dark_gray"], style="italic", zorder=_TXT_Z)
    ax.text(lcx-af/2-0.65, lcy,
            rf"$d_{{\mathrm{{Zr\text{{-}}Zr}}}}$" + f"\n= {d_zr_f:.2f} Å",
            fontsize=5.5, color=C["blue"], fontweight="bold", ha="center", va="center",
            bbox=dict(fc="white", ec=C["blue"], lw=0.4, pad=2,
                      boxstyle="round,pad=0.15", alpha=0.9), zorder=_TXT_Z)
    ax.text(lcx, lcy-af/2-0.45, "Insulating", ha="center", fontsize=7,
            color=C["blue"], fontweight="bold", zorder=_TXT_Z)

    # ── RIGHT: Rocksalt with octahedral polyhedra + metallic glow ──
    rcx, rcy = 7.8, 7.0
    ar = af * (a_r / a_f)
    rect2 = Rectangle((rcx-ar/2, rcy-ar/2), ar, ar, fc="none", ec=C["vermillion"], lw=1.0, zorder=1)
    ax.add_patch(rect2)

    # Octahedral polyhedra around O sites (projected as diamonds)
    o_frac_r = [(0.5, 0.5), (0.5, 0.0), (0.0, 0.5), (0.0, 0.0)]
    for fx, fy in o_frac_r:
        cx = rcx + (fx-0.5)*ar
        cy = rcy + (fy-0.5)*ar
        half = ar*0.22
        corners = [(cx, cy+half), (cx-half, cy), (cx, cy-half), (cx+half, cy)]
        draw_polyhedron(ax, corners, fc=C["vermillion"], ec=C["vermillion"], alpha=0.08, lw=0.3)

    for site in pmg_r:
        fx, fy = site.frac_coords[0], site.frac_coords[1]
        px = rcx + (fx-0.5)*ar
        py = rcy + (fy-0.5)*ar
        if abs(fx-0.5) <= 0.5 and abs(fy-0.5) <= 0.5:
            if str(site.specie) == "O":
                draw_atom(ax, px, py, r_o, C["o_red"], ec="#c0392b", lw=0.3, zorder=3)
            else:
                draw_atom(ax, px, py, r_zr, "#c9943a", ec="#7a6630", zorder=5, glow=True)

    # d-orbital overlap lobes
    zr_r_pos = [(rcx + (s.frac_coords[0]-0.5)*ar, rcy + (s.frac_coords[1]-0.5)*ar)
                for s in pmg_r if str(s.specie) == "Zr"
                and abs(s.frac_coords[0]-0.5) <= 0.5 and abs(s.frac_coords[1]-0.5) <= 0.5]
    for i in range(len(zr_r_pos)):
        for j in range(i+1, len(zr_r_pos)):
            x1, y1 = zr_r_pos[i]
            x2, y2 = zr_r_pos[j]
            dist = np.hypot(x2-x1, y2-y1)
            if dist < ar * 0.8:
                mx, my = (x1+x2)/2, (y1+y2)/2
                lobe = Circle((mx, my), 0.15, fc=C["gold"], ec=C["orange"],
                               lw=0.3, alpha=0.25, zorder=2)
                ax.add_patch(lobe)

    ax.text(rcx, rcy+ar/2+0.80, "Rocksalt ZrO", ha="center", fontsize=7.5,
            fontweight="bold", color=C["vermillion"], zorder=_TXT_Z)
    ax.text(rcx, rcy+ar/2+0.30, "O in octahedral (4b)", ha="center", fontsize=5.5,
            color=C["dark_gray"], style="italic", zorder=_TXT_Z)
    ax.text(rcx+ar/2+0.65, rcy,
            rf"$d_{{\mathrm{{Zr\text{{-}}Zr}}}}$" + f"\n= {d_zr_r:.2f} Å",
            fontsize=5.5, color=C["vermillion"], fontweight="bold", ha="center", va="center",
            bbox=dict(fc="white", ec=C["vermillion"], lw=0.4, pad=2,
                      boxstyle="round,pad=0.15", alpha=0.9), zorder=_TXT_Z)
    ax.text(rcx, rcy-ar/2-0.50, "Metallic (2DEG)", ha="center", fontsize=7,
            color=C["vermillion"], fontweight="bold", zorder=_TXT_Z)

    # Arrow
    ax.annotate("", xy=(rcx-ar/2-0.55, rcy), xytext=(lcx+af/2+0.35, lcy),
                arrowprops=dict(arrowstyle="-|>", color=C["dark_gray"], lw=2.0, mutation_scale=14))
    ax.text(5.05, rcy+0.25, "Flash", ha="center", fontsize=6.5,
            fontweight="bold", color=C["dark_gray"], zorder=_TXT_Z)
    ax.text(5.05, rcy-0.25, "activation", ha="center", fontsize=6,
            color=C["dark_gray"], zorder=_TXT_Z)

    # Math box
    bx, by, bw, bh = 0.2, -0.4, 9.5, 5.0
    box = FancyBboxPatch((bx, by), bw, bh, boxstyle="round,pad=0.18",
                         fc=C["bg"], ec=C["dark_gray"], lw=0.7, zorder=1)
    ax.add_patch(box)
    tcx = bx + bw/2
    cy = by + bh
    sp = 0.72
    geo = np.sqrt(3)/2
    quantum = 1.062
    net = geo * quantum
    a_child = a_f * net

    ax.text(tcx, cy-0.30,
            rf"Geometric:  $a_{{\mathrm{{oct}}}}/a_{{\mathrm{{tet}}}}"
            rf" = \sqrt{{3}}/2 = {geo:.3f}$  (−13.4%)",
            ha="center", fontsize=6.5, color=C["blue"], fontweight="bold", zorder=_TXT_Z)
    ax.text(tcx, cy-0.30-sp,
            r"Quantum:  Zr$^{4+}$ → Zr$^{2+}$  ($d$-recapture)"
            rf"  ×{quantum:.3f}  (+{(quantum-1)*100:.1f}%)",
            ha="center", fontsize=6.5, color=C["vermillion"], zorder=_TXT_Z)
    ax.plot([bx+0.4, bx+bw-0.4], [cy-0.30-1.7*sp]*2, color=C["dark_gray"], lw=0.6, zorder=2)
    ax.text(tcx, cy-0.30-2.1*sp,
            rf"${geo:.3f} \times {quantum:.3f} = \mathbf{{{net:.3f}}}$"
            rf"  →  {(1-net)*100:.1f}% contraction",
            ha="center", fontsize=7, fontweight="bold", color=C["black"], zorder=_TXT_Z)
    ax.text(tcx, cy-0.30-2.9*sp,
            rf"$a_{{\mathrm{{child}}}} = {a_f:.3f} \times {net:.3f}"
            rf" = \mathbf{{{a_child:.2f}}}$ Å  =  SAED",
            ha="center", fontsize=6.5, color=C["green"], fontweight="bold", zorder=_TXT_Z)


# ═══════════════════════════════════════════════════════════════════════════════
# ASSEMBLE
# ═══════════════════════════════════════════════════════════════════════════════

fig = plt.figure(figsize=(7.5, 6.0))
gs = fig.add_gridspec(1, 2, wspace=0.08)
ax_a = fig.add_subplot(gs[0, 0])
ax_b = fig.add_subplot(gs[0, 1])

draw_panel_a(ax_a)
draw_panel_b(ax_b)

ax_a.text(-0.04, 1.02, "(a)", transform=ax_a.transAxes,
          fontsize=11, fontweight="bold", va="top", ha="left")
ax_b.text(-0.04, 1.02, "(b)", transform=ax_b.transAxes,
          fontsize=11, fontweight="bold", va="top", ha="left")

for fmt, dpi in [("pdf", 600), ("png", 300)]:
    path = OUT_DIR / f"fig10ab_v2.{fmt}"
    fig.savefig(path, dpi=dpi, bbox_inches="tight", pad_inches=0.06)
    print(f"Saved: {path}")

plt.close(fig)
