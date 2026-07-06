"""
tikz_export.py
Generate TikZ/PGF code for crystal lattice diagrams.

Produces standalone .tex files compatible with existing LaTeX workflows,
matching the style of the fig10 TikZ panels.
"""

import numpy as np
from pathlib import Path
import sys as _sys

_sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))
from attribution import ATTRIBUTION_TEXT

DEFAULT_COLORS = {
    "Zr": ("zrblue", "4a86c8"),
    "O":  ("ored",   "e74c3c"),
    "Y":  ("ypurp",  "9b59b6"),
    "Ti": ("tigray", "95a5a6"),
    "Si": ("siyel",  "f39c12"),
    "Al": ("algray", "bdc3c7"),
}

DEFAULT_RADII = {
    "Zr": 0.20, "O": 0.14, "Y": 0.22, "Ti": 0.18,
    "Si": 0.16, "Al": 0.16,
}


def _parse_projection(projection_str):
    digits = [int(c) for c in projection_str.replace(" ", "")]
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


def export_tikz(
    atoms,
    output_file="lattice.tex",
    projection="001",
    scale=1.0,
    atom_colors=None,
    atom_radii=None,
    show_cell=True,
    show_bonds=True,
    bond_cutoff=3.0,
):
    """Generate a standalone TikZ .tex file for the crystal lattice."""
    rotation = _parse_projection(projection)
    positions = atoms.get_positions()
    rotated = positions @ rotation.T
    x, y, z = rotated[:, 0], rotated[:, 1], rotated[:, 2]
    symbols = atoms.get_chemical_symbols()

    unique_elements = sorted(set(symbols))

    color_map = {}
    for elem in unique_elements:
        if atom_colors and elem in atom_colors:
            hex_val = atom_colors[elem].lstrip("#")
            tikz_name = f"c{elem.lower()}"
            color_map[elem] = (tikz_name, hex_val)
        elif elem in DEFAULT_COLORS:
            color_map[elem] = DEFAULT_COLORS[elem]
        else:
            color_map[elem] = (f"c{elem.lower()}", "777777")

    radii_map = {}
    for elem in unique_elements:
        if atom_radii and elem in atom_radii:
            radii_map[elem] = atom_radii[elem] * scale
        elif elem in DEFAULT_RADII:
            radii_map[elem] = DEFAULT_RADII[elem] * scale
        else:
            radii_map[elem] = 0.16 * scale

    lines = []
    lines.append(r"\documentclass[tikz,border=2mm]{standalone}")
    lines.append(r"\usepackage{tikz}")
    lines.append(r"\begin{document}")
    lines.append(r"\begin{tikzpicture}[scale=%.2f]" % scale)
    lines.append("")

    lines.append("% Color definitions")
    for elem in unique_elements:
        tikz_name, hex_val = color_map[elem]
        lines.append(r"\definecolor{%s}{HTML}{%s}" % (tikz_name, hex_val.upper()))
    lines.append("")

    if show_cell:
        cell = atoms.cell
        corners_3d = []
        for i in range(2):
            for j in range(2):
                for k in range(2):
                    corners_3d.append(i * cell[0] + j * cell[1] + k * cell[2])
        corners_3d = np.array(corners_3d)
        proj = corners_3d @ rotation.T

        edge_pairs = [
            (0,1),(0,2),(0,4),(1,3),(1,5),(2,3),
            (2,6),(3,7),(4,5),(4,6),(5,7),(6,7),
        ]
        lines.append("% Unit cell edges")
        for a, b in edge_pairs:
            lines.append(
                r"\draw[gray!40, thin] (%.4f, %.4f) -- (%.4f, %.4f);"
                % (proj[a, 0], proj[a, 1], proj[b, 0], proj[b, 1])
            )
        lines.append("")

    if show_bonds:
        n = len(atoms)
        lines.append("% Bonds")
        for i in range(n):
            for j in range(i + 1, n):
                dist = np.linalg.norm(positions[i] - positions[j])
                if dist < bond_cutoff:
                    if symbols[i] != symbols[j] or dist < bond_cutoff * 0.6:
                        lines.append(
                            r"\draw[gray!60, line width=0.4pt] "
                            r"(%.4f, %.4f) -- (%.4f, %.4f);"
                            % (x[i], y[i], x[j], y[j])
                        )
        lines.append("")

    depth_order = np.argsort(z)
    lines.append("% Atoms (back to front)")
    for idx in depth_order:
        sym = symbols[idx]
        tikz_name = color_map[sym][0]
        r = radii_map[sym]
        lines.append(
            r"\fill[%s, draw=black!60, line width=0.3pt] "
            r"(%.4f, %.4f) circle (%.3fcm);"
            % (tikz_name, x[idx], y[idx], r)
        )
    lines.append("")

    lines.append("% Legend")
    ly = y.min() - 1.0
    for i, elem in enumerate(unique_elements):
        tikz_name = color_map[elem][0]
        r = radii_map[elem]
        lx = x.min() + i * 1.5
        lines.append(
            r"\fill[%s, draw=black!60, line width=0.3pt] "
            r"(%.4f, %.4f) circle (%.3fcm);"
            % (tikz_name, lx, ly, r)
        )
        lines.append(
            r"\node[right, font=\tiny] at (%.4f, %.4f) {%s};"
            % (lx + r + 0.1, ly, elem)
        )
    lines.append("")

    lines.append("% Sci-Viz attribution")
    lines.append(
        r"\node[anchor=south east, font=\tiny, text=black!45] "
        r"at (%.4f, %.4f) {%s};"
        % (x.max() + 0.5, y.min() - 1.3, ATTRIBUTION_TEXT)
    )
    lines.append("")

    lines.append(r"\end{tikzpicture}")
    lines.append(r"\end{document}")

    output_path = str(Path(output_file).resolve())
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return output_path
