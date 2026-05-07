#!/usr/bin/env python3
"""
Panel (a) -- APS-style universal antinode templating panel for Figure 10.

This panel communicates the cross-class claim from the manuscript:
the same coherent ridge standing wave templates initial defect nucleation
at displacement antinodes, while the commensurability ratio d*/a selects
the structural product.

Columns:
  - Ionic:    8YSZ fluorite (commensurate, d*/a ~ 0.97)
  - Covalent: 3C-SiC zincblende (near-commensurate, d*/a ~ 1.10)
  - Metal:    BCC W (incommensurate, d*/a ~ 1.75)
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import ase.io
from ase.build import bulk
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle

from styles import apply_aps_style

CIF_DIR = Path(__file__).parent.parent / "tests" / "sample_structures"
OUT_DIR = Path(__file__).parent.parent / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

IONIC_BLUE = "#0072B2"
METAL_ORANGE = "#E69F00"
COVAL_GREEN = "#009E73"
RIDGE_GOLD = "#AA9432"
DARK_GRAY = "#3A3A3A"
MID_GRAY = "#6A6A6A"
LIGHT_GRAY = "#D7D7D7"
SOFT_BG = "#FBFBFB"


def _project_001(positions, a_lat):
    """Project onto the [001] plane and normalize lengths by the lattice a."""
    pts = np.atleast_2d(positions)
    return pts[:, 0] / a_lat, pts[:, 1] / a_lat, pts[:, 2] / a_lat


def _build_examples():
    fluorite = ase.io.read(str(CIF_DIR / "fluorite_ZrO2.cif")).repeat([4, 4, 1])
    sic = bulk("SiC", "zincblende", a=4.3596, cubic=True).repeat([4, 4, 1])
    tungsten = ase.io.read(str(CIF_DIR / "bcc_W.cif")).repeat([4, 4, 1])

    return [
        dict(
            atoms=fluorite,
            a_lat=5.145,
            n_atoms_conv=12,
            class_name="Ionic",
            structure_name="8YSZ fluorite",
            class_color=IONIC_BLUE,
            vacancy_species="O",
            vacancy_label=r"$V_{\!O}$",
            outcome="Commensurate\nEpitaxial Superstructure",
            styles={
                "Zr": dict(radius=0.10, face=DARK_GRAY, edge="#2E2E2E", lw=0.45),
                "O": dict(radius=0.060, face="white", edge=MID_GRAY, lw=0.55),
            },
        ),
        dict(
            atoms=sic,
            a_lat=4.3596,
            n_atoms_conv=8,
            class_name="Covalent",
            structure_name="3C-SiC",
            class_color=COVAL_GREEN,
            vacancy_species="C",
            vacancy_label=r"$V_{\!C}$",
            outcome=r"Near-Commensurate" + "\n" + r"$\{111\}$ Vacancy Planes",
            styles={
                "Si": dict(radius=0.090, face=DARK_GRAY, edge="#2E2E2E", lw=0.45),
                "C": dict(radius=0.055, face="white", edge=MID_GRAY, lw=0.55),
            },
        ),
        dict(
            atoms=tungsten,
            a_lat=3.165,
            n_atoms_conv=2,
            class_name="Metal",
            structure_name="BCC W",
            class_color=METAL_ORANGE,
            vacancy_species="W",
            vacancy_label=r"$V_{\!W}$",
            outcome="Incommensurate\nFilamentary Coarsening",
            styles={
                "W": dict(radius=0.10, face=DARK_GRAY, edge="#2E2E2E", lw=0.45),
            },
        ),
    ]


def _all_antinode_positions(x_lo, x_hi, ratio, phase_offset):
    """Return all antinode columns (both crest and trough families)."""
    antinode_xs = []
    step = max(ratio / 2.0, 1e-6)
    start_n = int(np.floor((x_lo - phase_offset) / step)) - 2
    stop_n = int(np.ceil((x_hi - phase_offset) / step)) + 2
    for n in range(start_n, stop_n + 1):
        xp = phase_offset + (0.25 * ratio) + n * step
        if x_lo - 0.2 <= xp <= x_hi + 0.2:
            antinode_xs.append(xp)
    antinode_xs = sorted(set(round(x, 6) for x in antinode_xs))
    return antinode_xs


def _make_antinode_positions(x_vals, ratio):
    x_lo = float(np.min(x_vals))
    x_hi = float(np.max(x_vals))
    unique_cols = np.unique(np.round(x_vals, 3))
    if len(unique_cols) == 0:
        return []
    tol = 0.08 if ratio < 1.2 else 0.12

    best_phase = unique_cols[0] - 0.25 * ratio
    best_score = (-1, 1e9)
    for anchor in unique_cols:
        phase = anchor - 0.25 * ratio
        antinode_xs = _all_antinode_positions(x_lo, x_hi, ratio, phase)
        dists = [min(abs(col - xp) for xp in antinode_xs) for col in unique_cols]
        score = (sum(d <= tol for d in dists), np.mean(np.square(dists)))
        if score[0] > best_score[0] or (score[0] == best_score[0] and score[1] < best_score[1]):
            best_phase = phase
            best_score = score

    phase_offset = best_phase
    antinode_xs = _all_antinode_positions(x_lo, x_hi, ratio, phase_offset)
    return antinode_xs, phase_offset


def _draw_wave(ax, x_lo, x_hi, ratio, phase_offset, antinode_xs):
    wave_y = 4.40
    amp = 0.23
    xs = np.linspace(x_lo, x_hi, 400)
    ys = wave_y + amp * np.sin(2 * np.pi * (xs - phase_offset) / ratio)
    ax.plot(xs, ys, color=RIDGE_GOLD, linewidth=1.1, zorder=30)
    for xp in antinode_xs:
        yp = wave_y + amp * np.sin(2 * np.pi * (xp - phase_offset) / ratio)
        ax.add_patch(Circle((xp, yp), 0.035, facecolor=RIDGE_GOLD,
                            edgecolor="white", linewidth=0.35, zorder=31))
    ax.text(x_hi + 0.04, wave_y, r"$u(x)$", fontsize=7.5, color=RIDGE_GOLD,
            va="center", ha="left", fontstyle="italic")


def _draw_antinode_bands(ax, antinode_xs):
    for xp in antinode_xs:
        ax.add_patch(Rectangle((xp - 0.09, 0.05), 0.18, 3.95,
                               facecolor=RIDGE_GOLD, edgecolor="none",
                               alpha=0.08, zorder=1))


def _draw_lattice_grid(ax):
    for v in range(5):
        ax.plot([v, v], [0, 4], color=LIGHT_GRAY, lw=0.35, zorder=0)
        ax.plot([0, 4], [v, v], color=LIGHT_GRAY, lw=0.35, zorder=0)


def _select_vacancies(x2d, y2d, symbols, vacancy_species, antinode_xs, ratio):
    vac_mask = np.array([s == vacancy_species for s in symbols])
    y_mid = 0.5 * (float(np.min(y2d[vac_mask])) + float(np.max(y2d[vac_mask])))
    band_half = 0.80
    tol = 0.12 if ratio < 1.2 else 0.18

    candidates = []
    for idx in np.where(vac_mask)[0]:
        if abs(y2d[idx] - y_mid) > band_half:
            continue
        dist = min(abs(x2d[idx] - xp) for xp in antinode_xs) if antinode_xs else 999
        if dist <= tol:
            candidates.append(idx)
    return candidates


def _draw_structure(ax, spec):
    atoms = spec["atoms"]
    a_lat = spec["a_lat"]
    omega = atoms.get_volume() / len(atoms)
    ratio = 2.21 * (omega ** (1.0 / 3.0)) / a_lat

    symbols = np.array(atoms.get_chemical_symbols())
    x2d, y2d, depth = _project_001(atoms.positions, a_lat)

    antinode_xs, phase_offset = _make_antinode_positions(
        x2d[symbols == spec["vacancy_species"]], ratio
    )
    vacancy_indices = _select_vacancies(
        x2d, y2d, symbols, spec["vacancy_species"], antinode_xs, ratio
    )

    ax.set_xlim(-0.15, 4.15)
    ax.set_ylim(-0.55, 4.75)
    ax.set_aspect("equal")
    ax.axis("off")

    _draw_lattice_grid(ax)
    _draw_antinode_bands(ax, antinode_xs)
    _draw_wave(ax, 0.0, 4.0, ratio, phase_offset, antinode_xs)

    order = np.argsort(depth)
    vac_set = set(vacancy_indices)
    for idx in order:
        symbol = symbols[idx]
        style = spec["styles"][symbol]
        if idx in vac_set:
            ax.add_patch(Circle((x2d[idx], y2d[idx]), style["radius"] * 1.15,
                                facecolor="white", edgecolor=spec["class_color"],
                                linewidth=1.0, linestyle=(0, (2, 1.3)),
                                zorder=20 + depth[idx]))
        else:
            ax.add_patch(Circle((x2d[idx], y2d[idx]), style["radius"],
                                facecolor=style["face"], edgecolor=style["edge"],
                                linewidth=style["lw"], zorder=20 + depth[idx]))

    label_indices = vacancy_indices[:2]
    for idx in label_indices:
        ax.text(x2d[idx], y2d[idx] - 0.17, spec["vacancy_label"],
                color=spec["class_color"], fontsize=6.2, fontweight="bold",
                ha="center", va="top", zorder=80)

    ax.text(0.50, 1.07, spec["class_name"], transform=ax.transAxes,
            ha="center", va="bottom", fontsize=8.4, fontweight="bold",
            color=spec["class_color"])
    ax.text(0.50, 1.00, spec["structure_name"], transform=ax.transAxes,
            ha="center", va="bottom", fontsize=7.0, color=DARK_GRAY)
    ax.plot([0.18, 0.82], [0.985, 0.985], transform=ax.transAxes,
            color=spec["class_color"], lw=0.8, solid_capstyle="round")

    badge = dict(boxstyle="round,pad=0.22", facecolor="white",
                 edgecolor=spec["class_color"], linewidth=0.6)
    ax.text(0.03, 0.90, rf"$d^*/a = {ratio:.2f}$",
            transform=ax.transAxes, ha="left", va="top",
            fontsize=7.0, color=spec["class_color"], bbox=badge)
    ax.text(0.50, -0.01, spec["outcome"],
            transform=ax.transAxes, ha="center", va="top",
            fontsize=6.7, color=DARK_GRAY, linespacing=1.2)


def main():
    apply_aps_style()
    plt.rcParams.update({
        "font.size": 8,
        "axes.labelsize": 8,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "savefig.dpi": 600,
        "figure.dpi": 150,
    })

    fig, axes = plt.subplots(1, 3, figsize=(4.8, 3.25))
    specs = _build_examples()
    for ax, spec in zip(axes, specs):
        _draw_structure(ax, spec)

    fig.subplots_adjust(left=0.03, right=0.99, top=0.91, bottom=0.18, wspace=0.15)

    out_png = str(OUT_DIR / "fig10_panel_a_v2.png")
    out_pdf = str(OUT_DIR / "fig10_panel_a_v2.pdf")
    fig.savefig(out_png, dpi=350, bbox_inches="tight", facecolor="white", pad_inches=0.04)
    fig.savefig(out_pdf, dpi=600, bbox_inches="tight", facecolor="white", pad_inches=0.04)
    plt.close(fig)

    print(f"Panel (a):  {out_png}")
    print(f"            {out_pdf}")


if __name__ == "__main__":
    main()
