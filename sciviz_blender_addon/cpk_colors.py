"""CPK-style colors for chemical elements.

Used by `sciviz.import_crystal` to color atom spheres. Values are RGBA
floats in the 0-1 range matching Blender's Principled BSDF Base Color.
"""

from __future__ import annotations

CPK: dict[str, tuple[float, float, float, float]] = {
    "H":  (0.93, 0.94, 0.95, 1.0),
    "C":  (0.20, 0.29, 0.37, 1.0),
    "N":  (0.17, 0.24, 0.31, 1.0),
    "O":  (0.91, 0.30, 0.24, 1.0),
    "F":  (0.56, 0.88, 0.31, 1.0),
    "Na": (0.67, 0.36, 0.95, 1.0),
    "Mg": (0.54, 1.00, 0.00, 1.0),
    "Al": (0.74, 0.76, 0.78, 1.0),
    "Si": (0.95, 0.61, 0.07, 1.0),
    "P":  (1.00, 0.50, 0.00, 1.0),
    "S":  (1.00, 0.78, 0.20, 1.0),
    "Cl": (0.12, 0.94, 0.12, 1.0),
    "K":  (0.56, 0.25, 0.83, 1.0),
    "Ca": (0.15, 0.68, 0.38, 1.0),
    "Ti": (0.58, 0.65, 0.65, 1.0),
    "Cr": (0.54, 0.60, 0.78, 1.0),
    "Mn": (0.61, 0.48, 0.78, 1.0),
    "Fe": (0.83, 0.33, 0.00, 1.0),
    "Co": (0.94, 0.56, 0.63, 1.0),
    "Ni": (0.31, 0.82, 0.31, 1.0),
    "Cu": (0.78, 0.50, 0.20, 1.0),
    "Zn": (0.49, 0.50, 0.69, 1.0),
    "Y":  (0.61, 0.35, 0.71, 1.0),
    "Zr": (0.29, 0.53, 0.78, 1.0),
    "Mo": (0.33, 0.71, 0.71, 1.0),
    "Ag": (0.75, 0.75, 0.75, 1.0),
    "Sn": (0.40, 0.50, 0.50, 1.0),
    "W":  (0.13, 0.58, 0.84, 1.0),
    "Pt": (0.82, 0.82, 0.88, 1.0),
    "Au": (1.00, 0.82, 0.14, 1.0),
}

DEFAULT_COLOR: tuple[float, float, float, float] = (0.47, 0.47, 0.47, 1.0)


def color_for(symbol: str) -> tuple[float, float, float, float]:
    return CPK.get(symbol, DEFAULT_COLOR)
