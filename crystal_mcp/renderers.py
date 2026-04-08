"""
renderers.py
Matplotlib-based crystal structure renderers for publication-quality figures.

Supports ball-and-stick, space-filling, and wireframe projections with
configurable atom colors, radii, bonds, and annotations.
"""

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle
from matplotlib.collections import LineCollection
from pathlib import Path

# CPK-inspired color scheme (matches fig10 palette)
DEFAULT_COLORS = {
    "Zr": "#4a86c8",
    "O":  "#e74c3c",
    "Y":  "#9b59b6",
    "Ti": "#95a5a6",
    "Si": "#f39c12",
    "Al": "#bdc3c7",
    "Fe": "#d35400",
    "Ca": "#27ae60",
    "Mg": "#2ecc71",
    "Na": "#3498db",
    "K":  "#8e44ad",
    "Li": "#1abc9c",
    "N":  "#2c3e50",
    "C":  "#34495e",
    "H":  "#ecf0f1",
    "S":  "#f1c40f",
    "P":  "#e67e22",
    "Cl": "#16a085",
    "F":  "#2980b9",
}

DEFAULT_RADII = {
    "Zr": 0.28, "O": 0.18, "Y": 0.30, "Ti": 0.24,
    "Si": 0.22, "Al": 0.22, "Fe": 0.24, "Ca": 0.28,
    "Mg": 0.24, "Na": 0.26, "K": 0.30, "Li": 0.20,
    "N": 0.18, "C": 0.20, "H": 0.12, "S": 0.22,
    "P": 0.22, "Cl": 0.20, "F": 0.16,
}

import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))
from styles import get_style_dict, _APS_RCPARAMS, _NATURE_RCPARAMS

_STYLE_PRESETS = {
    "aps": _APS_RCPARAMS,
    "nature": _NATURE_RCPARAMS,
}

APS_RCPARAMS = _APS_RCPARAMS


def _parse_projection(projection_str):
    """Convert '001', '110', '111' etc. to a rotation matrix."""
    digits = [int(c) for c in projection_str.replace(" ", "")]
    if len(digits) != 3:
        raise ValueError(f"Projection must be 3 digits (e.g. '001'), got: {projection_str}")

    normal = np.array(digits, dtype=float)
    if np.linalg.norm(normal) == 0:
        raise ValueError("Projection direction cannot be [000]")
    normal = normal / np.linalg.norm(normal)

    if abs(normal[2]) < 0.99:
        up = np.array([0, 0, 1.0])
    else:
        up = np.array([1, 0, 0.0])

    x_axis = np.cross(up, normal)
    x_axis = x_axis / np.linalg.norm(x_axis)
    y_axis = np.cross(normal, x_axis)
    y_axis = y_axis / np.linalg.norm(y_axis)

    return np.array([x_axis, y_axis, normal])


def _project_atoms(atoms, rotation):
    """Project atom positions through rotation matrix, return 2D coords + depth."""
    positions = atoms.get_positions()
    rotated = positions @ rotation.T
    return rotated[:, 0], rotated[:, 1], rotated[:, 2]


def _project_cell(atoms, rotation):
    """Project unit cell edges through rotation matrix."""
    cell = atoms.cell
    origin = np.zeros(3)
    corners = []
    for i in range(2):
        for j in range(2):
            for k in range(2):
                corners.append(i * cell[0] + j * cell[1] + k * cell[2])
    corners = np.array(corners)
    proj = corners @ rotation.T

    edges = []
    for a, b in [(0,1),(0,2),(0,4),(1,3),(1,5),(2,3),
                 (2,6),(3,7),(4,5),(4,6),(5,7),(6,7)]:
        edges.append([(proj[a, 0], proj[a, 1]), (proj[b, 0], proj[b, 1])])
    return edges


def _find_bonds(atoms, cutoff=3.0):
    """Find bonds between atoms within cutoff distance."""
    positions = atoms.get_positions()
    symbols = atoms.get_chemical_symbols()
    n = len(atoms)
    bonds = []
    for i in range(n):
        for j in range(i + 1, n):
            dist = np.linalg.norm(positions[i] - positions[j])
            if dist < cutoff:
                if symbols[i] != symbols[j] or dist < cutoff * 0.6:
                    bonds.append((i, j, dist))
    return bonds


def _get_color(symbol, user_colors=None):
    if user_colors and symbol in user_colors:
        return user_colors[symbol]
    return DEFAULT_COLORS.get(symbol, "#777777")


def _get_radius(symbol, user_radii=None, scale=1.0):
    if user_radii and symbol in user_radii:
        return user_radii[symbol] * scale
    return DEFAULT_RADII.get(symbol, 0.22) * scale


def render_lattice_projection(
    atoms,
    output_file="lattice.pdf",
    projection="001",
    style="ball_and_stick",
    atom_colors=None,
    atom_radii=None,
    bond_cutoff=3.0,
    show_cell=True,
    show_labels=False,
    background="white",
    figsize=None,
    dpi=300,
    title=None,
    style_preset="aps",
):
    """Render a 2D projection of a crystal structure."""
    rc = _STYLE_PRESETS.get(style_preset, APS_RCPARAMS)
    plt.rcParams.update(rc)

    rotation = _parse_projection(projection)
    x, y, z = _project_atoms(atoms, rotation)
    symbols = atoms.get_chemical_symbols()

    depth_order = np.argsort(z)

    if figsize is None:
        x_range = x.max() - x.min()
        y_range = y.max() - y.min()
        aspect = y_range / max(x_range, 0.1)
        w = max(4, min(8, x_range / 1.5))
        h = max(w * aspect, 2)
        figsize = (w, h)

    fig, ax = plt.subplots(figsize=figsize, facecolor=background)
    ax.set_facecolor(background)
    ax.set_aspect("equal")
    ax.axis("off")

    if show_cell:
        edges = _project_cell(atoms, rotation)
        lc = LineCollection(edges, colors="#cccccc", linewidths=0.5, zorder=0)
        ax.add_collection(lc)

    if style in ("ball_and_stick", "wireframe"):
        bonds = _find_bonds(atoms, bond_cutoff)
        proj_pos = np.column_stack([x, y])
        for i, j, dist in bonds:
            ax.plot(
                [proj_pos[i, 0], proj_pos[j, 0]],
                [proj_pos[i, 1], proj_pos[j, 1]],
                color="#888888", lw=0.8, zorder=1, alpha=0.6,
            )

    radius_scale = 1.0 if style != "space_filling" else 2.5
    if style == "wireframe":
        radius_scale = 0.4

    for idx in depth_order:
        sym = symbols[idx]
        color = _get_color(sym, atom_colors)
        r = _get_radius(sym, atom_radii, scale=radius_scale)

        depth_alpha = 0.5 + 0.5 * (z[idx] - z.min()) / max(z.max() - z.min(), 0.01)

        circle = Circle(
            (x[idx], y[idx]), r,
            fc=color, ec="#333333", lw=0.4,
            alpha=depth_alpha, zorder=2 + idx,
        )
        ax.add_patch(circle)

        if show_labels:
            ax.text(
                x[idx], y[idx], sym,
                ha="center", va="center",
                fontsize=5, color="white", fontweight="bold",
                zorder=100 + idx,
            )

    pad = 0.5
    ax.set_xlim(x.min() - pad, x.max() + pad)
    ax.set_ylim(y.min() - pad, y.max() + pad)

    if title:
        ax.set_title(title, fontsize=10, fontweight="bold", pad=10)

    unique = sorted(set(symbols))
    legend_elements = []
    from matplotlib.lines import Line2D
    for sym in unique:
        c = _get_color(sym, atom_colors)
        legend_elements.append(
            Line2D([0], [0], marker="o", color="w", markerfacecolor=c,
                   markersize=6, label=sym, markeredgecolor="#333", markeredgewidth=0.4)
        )
    ax.legend(handles=legend_elements, loc="upper right", fontsize=6,
              framealpha=0.9, handlelength=1.0)

    output_path = str(Path(output_file).resolve())
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", pad_inches=0.06,
                facecolor=background)
    plt.close(fig)
    return output_path


def render_unit_cell(
    atoms,
    pmg_structure,
    output_file="unit_cell.pdf",
    projection="001",
    show_wyckoff=True,
    show_bond_lengths=True,
    show_lattice_params=True,
    atom_colors=None,
    atom_radii=None,
    dpi=300,
    title=None,
    style_preset="aps",
):
    """Render an annotated unit cell with Wyckoff labels and bond lengths."""
    rc = _STYLE_PRESETS.get(style_preset, APS_RCPARAMS)
    plt.rcParams.update(rc)

    rotation = _parse_projection(projection)
    x, y, z = _project_atoms(atoms, rotation)
    symbols = atoms.get_chemical_symbols()

    fig, ax = plt.subplots(figsize=(5, 5), facecolor="white")
    ax.set_facecolor("white")
    ax.set_aspect("equal")
    ax.axis("off")

    edges = _project_cell(atoms, rotation)
    lc = LineCollection(edges, colors="#0072B2", linewidths=0.8, zorder=0)
    ax.add_collection(lc)

    bonds = _find_bonds(atoms, cutoff=3.5)
    proj_pos = np.column_stack([x, y])

    for i, j, dist in bonds:
        ax.plot(
            [proj_pos[i, 0], proj_pos[j, 0]],
            [proj_pos[i, 1], proj_pos[j, 1]],
            color="#888888", lw=0.6, zorder=1, alpha=0.5,
        )
        if show_bond_lengths:
            mx = (proj_pos[i, 0] + proj_pos[j, 0]) / 2
            my = (proj_pos[i, 1] + proj_pos[j, 1]) / 2
            ax.text(
                mx, my, f"{dist:.2f} \u00c5",
                fontsize=4.5, color="#555555", ha="center", va="center",
                bbox=dict(fc="white", ec="none", alpha=0.8, pad=0.5),
                zorder=10,
            )

    wyckoff_labels = None
    if show_wyckoff:
        try:
            from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
            sga = SpacegroupAnalyzer(pmg_structure, symprec=0.01)
            sym_data = sga.get_symmetry_dataset()
            wyckoff_labels = sym_data.get("wyckoffs", [])
        except Exception:
            wyckoff_labels = None

    depth_order = np.argsort(z)
    for idx in depth_order:
        sym = symbols[idx]
        color = _get_color(sym, atom_colors)
        r = _get_radius(sym, atom_radii, scale=1.0)

        circle = Circle(
            (x[idx], y[idx]), r,
            fc=color, ec="#333333", lw=0.5,
            zorder=2 + idx,
        )
        ax.add_patch(circle)

        if wyckoff_labels and idx < len(wyckoff_labels):
            ax.text(
                x[idx], y[idx] - r - 0.15,
                wyckoff_labels[idx],
                fontsize=4, color="#666666", ha="center", va="top",
                style="italic", zorder=100,
            )

    if show_lattice_params:
        cell = atoms.cell.cellpar()
        param_text = (
            f"a = {cell[0]:.3f} \u00c5,  "
            f"b = {cell[1]:.3f} \u00c5,  "
            f"c = {cell[2]:.3f} \u00c5"
        )
        ax.text(
            0.5, -0.02, param_text,
            transform=ax.transAxes, fontsize=6, ha="center",
            color="#555555",
        )

    pad = 0.8
    ax.set_xlim(x.min() - pad, x.max() + pad)
    ax.set_ylim(y.min() - pad, y.max() + pad)

    if title:
        ax.set_title(title, fontsize=10, fontweight="bold", pad=10)

    unique = sorted(set(symbols))
    from matplotlib.lines import Line2D
    legend_elements = []
    for sym in unique:
        c = _get_color(sym, atom_colors)
        legend_elements.append(
            Line2D([0], [0], marker="o", color="w", markerfacecolor=c,
                   markersize=6, label=sym, markeredgecolor="#333", markeredgewidth=0.4)
        )
    ax.legend(handles=legend_elements, loc="upper right", fontsize=6, framealpha=0.9)

    output_path = str(Path(output_file).resolve())
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)
    return output_path


def render_compare_structures(
    atoms_a,
    atoms_b,
    output_file="compare.pdf",
    label_a="Structure A",
    label_b="Structure B",
    projection="001",
    arrow_label=None,
    atom_colors=None,
    dpi=300,
    style_preset="aps",
):
    """Side-by-side rendering of two structures with an arrow between them."""
    rc = _STYLE_PRESETS.get(style_preset, APS_RCPARAMS)
    plt.rcParams.update(rc)

    rotation = _parse_projection(projection)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5), facecolor="white")

    for ax, atoms, label in [(ax1, atoms_a, label_a), (ax2, atoms_b, label_b)]:
        ax.set_facecolor("white")
        ax.set_aspect("equal")
        ax.axis("off")

        x, y, z = _project_atoms(atoms, rotation)
        symbols = atoms.get_chemical_symbols()
        depth_order = np.argsort(z)

        edges = _project_cell(atoms, rotation)
        lc = LineCollection(edges, colors="#cccccc", linewidths=0.6, zorder=0)
        ax.add_collection(lc)

        bonds = _find_bonds(atoms, 3.0)
        proj_pos = np.column_stack([x, y])
        for i, j, dist in bonds:
            ax.plot(
                [proj_pos[i, 0], proj_pos[j, 0]],
                [proj_pos[i, 1], proj_pos[j, 1]],
                color="#888888", lw=0.6, zorder=1, alpha=0.5,
            )

        for idx in depth_order:
            sym = symbols[idx]
            color = _get_color(sym, atom_colors)
            r = _get_radius(sym, scale=1.0)
            circle = Circle(
                (x[idx], y[idx]), r,
                fc=color, ec="#333333", lw=0.4, zorder=2 + idx,
            )
            ax.add_patch(circle)

        pad = 0.5
        ax.set_xlim(x.min() - pad, x.max() + pad)
        ax.set_ylim(y.min() - pad, y.max() + pad)
        ax.set_title(label, fontsize=9, fontweight="bold", pad=8)

    arrow_text = arrow_label or "\u2192"
    fig.text(
        0.5, 0.5, arrow_text,
        ha="center", va="center", fontsize=14,
        fontweight="bold", color="#555555",
        transform=fig.transFigure,
    )

    output_path = str(Path(output_file).resolve())
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)
    return output_path
