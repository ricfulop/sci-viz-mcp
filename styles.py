"""
styles.py
Publication figure style presets for APS (PRL/PRX/PRB) and Nature journals.

Consolidated from existing figure scripts across:
  - microscopic-origins-overleaf
  - flash-positron-natcomms-overleaf
  - critical-voltage-overleaf
  - voltivity-repo

Usage:
    from styles import apply_aps_style, apply_nature_style, OKABE_ITO
    apply_aps_style()
    fig, ax = plt.subplots(figsize=APS_DOUBLE)
"""

import matplotlib.pyplot as plt

# ═══════════════════════════════════════════════════════════════════════════════
# Okabe-Ito colorblind-safe palette (used across all repos)
# ═══════════════════════════════════════════════════════════════════════════════

OKABE_ITO = {
    "blue":       "#0072B2",
    "vermillion": "#D55E00",
    "orange":     "#E69F00",
    "sky_blue":   "#56B4E9",
    "green":      "#009E73",
    "purple":     "#CC79A7",
    "yellow":     "#F0E442",
    "black":      "#000000",
    "gray":       "#999999",
}

OI = OKABE_ITO  # short alias

# Extended palette for crystal/materials figures
MATERIALS = {
    **OKABE_ITO,
    "zr_blue":    "#4a86c8",
    "o_red":      "#e74c3c",
    "gold":       "#FFD700",
    "metallic":   "#FFB347",
    "light_gray": "#C8C8C8",
    "dark_gray":  "#555555",
    "bg":         "#FAFAFA",
}

# ═══════════════════════════════════════════════════════════════════════════════
# Journal column widths (inches)
# ═══════════════════════════════════════════════════════════════════════════════

# APS (PRL, PRX, PRB, PRMaterials)
APS_SINGLE = (3.375, 3.375)        # 85.7 mm single column
APS_DOUBLE = (6.75, 3.2)           # 171.5 mm double column
APS_DOUBLE_TALL = (6.75, 4.0)
APS_DOUBLE_SHORT = (6.75, 2.4)     # compact 3-panel strip

# Nature family (Nature, Nature Comms, Nature Materials, etc.)
NATURE_SINGLE = (3.5, 2.625)       # 89 mm single column
NATURE_1P5 = (5.35, 3.5)           # 136 mm 1.5-column
NATURE_DOUBLE = (7.08, 4.0)        # 180 mm full width

# ═══════════════════════════════════════════════════════════════════════════════
# APS / PRL / PRX style
# ═══════════════════════════════════════════════════════════════════════════════

_APS_RCPARAMS = {
    # Fonts: STIX serif stack, no LaTeX dependency
    "text.usetex": False,
    "mathtext.fontset": "stix",
    "font.family": "serif",
    "font.serif": ["STIX", "Times New Roman", "DejaVu Serif"],
    "font.size": 10,
    "axes.labelsize": 10,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 8,
    "legend.title_fontsize": 8,

    # Axes
    "axes.linewidth": 0.5,
    "axes.formatter.use_mathtext": True,
    "axes.grid": False,

    # Lines
    "lines.linewidth": 0.8,
    "lines.markersize": 4,

    # Ticks: inward, all four sides, minor ticks visible
    "xtick.direction": "in",
    "ytick.direction": "in",
    "xtick.top": True,
    "ytick.right": True,
    "xtick.minor.visible": True,
    "ytick.minor.visible": True,
    "xtick.major.size": 3.5,
    "ytick.major.size": 3.5,
    "xtick.minor.size": 2.0,
    "ytick.minor.size": 2.0,
    "xtick.major.width": 0.5,
    "ytick.major.width": 0.5,
    "xtick.minor.width": 0.4,
    "ytick.minor.width": 0.4,
    "xtick.major.pad": 4,
    "ytick.major.pad": 4,

    # Legend
    "legend.framealpha": 0.9,
    "legend.edgecolor": "0.8",
    "legend.handlelength": 1.2,
    "legend.labelspacing": 0.3,

    # DPI: screen preview at 150, save at 600
    "figure.dpi": 150,
    "savefig.dpi": 600,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,

    # Embed fonts as outlines (required by APS)
    "pdf.fonttype": 42,
    "ps.fonttype": 42,

    # Background
    "figure.facecolor": "white",
    "axes.facecolor": "white",
}

_APS_LATEX_RCPARAMS = {
    **_APS_RCPARAMS,
    "text.usetex": True,
    "font.serif": ["cmr10"],
    "mathtext.fontset": "cm",
}


def apply_aps_style(use_latex=False):
    """Apply APS (PRL/PRX/PRB) figure style.

    Args:
        use_latex: If True, use LaTeX rendering with Computer Modern fonts.
                   Requires a working LaTeX installation.
    """
    if use_latex:
        plt.rcParams.update(_APS_LATEX_RCPARAMS)
    else:
        plt.rcParams.update(_APS_RCPARAMS)


def aps_single():
    """Return APS single-column figsize (3.375 x 3.375 in)."""
    return APS_SINGLE


def aps_double(height=3.2):
    """Return APS double-column figsize (6.75 x height in)."""
    return (6.75, height)


# ═══════════════════════════════════════════════════════════════════════════════
# Nature / Nature Communications style
# ═══════════════════════════════════════════════════════════════════════════════

_NATURE_RCPARAMS = {
    # Fonts: Helvetica/Arial sans-serif, smaller than APS
    "text.usetex": False,
    "mathtext.fontset": "custom",
    "mathtext.rm": "Helvetica",
    "mathtext.it": "Helvetica:italic",
    "mathtext.bf": "Helvetica:bold",
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 7,
    "axes.labelsize": 7,
    "xtick.labelsize": 6,
    "ytick.labelsize": 6,
    "legend.fontsize": 6,

    # Axes: no top/right spines
    "axes.linewidth": 0.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.formatter.use_mathtext": True,
    "axes.grid": False,

    # Lines
    "lines.linewidth": 0.8,
    "lines.markersize": 3,

    # Ticks: outward, only bottom/left
    "xtick.direction": "out",
    "ytick.direction": "out",
    "xtick.top": False,
    "ytick.right": False,
    "xtick.minor.visible": True,
    "ytick.minor.visible": True,
    "xtick.major.size": 3.0,
    "ytick.major.size": 3.0,
    "xtick.minor.size": 1.5,
    "ytick.minor.size": 1.5,
    "xtick.major.width": 0.5,
    "ytick.major.width": 0.5,

    # Legend: frameless
    "legend.frameon": False,
    "legend.handlelength": 1.0,
    "legend.labelspacing": 0.25,

    # DPI: 300 for both screen and save
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,

    # Embed fonts as outlines
    "pdf.fonttype": 42,
    "ps.fonttype": 42,

    # Background
    "figure.facecolor": "white",
    "axes.facecolor": "white",
}


def apply_nature_style():
    """Apply Nature family (Nature, Nature Comms, etc.) figure style."""
    plt.rcParams.update(_NATURE_RCPARAMS)


def nature_single():
    """Return Nature single-column figsize (3.5 x 2.625 in / 89 mm)."""
    return NATURE_SINGLE


def nature_1p5():
    """Return Nature 1.5-column figsize (5.35 x 3.5 in / 136 mm)."""
    return NATURE_1P5


def nature_double(height=4.0):
    """Return Nature full-width figsize (7.08 x height in / 180 mm)."""
    return (7.08, height)


# ═══════════════════════════════════════════════════════════════════════════════
# APS large-font style (for panels rendered at 0.48\textwidth in LaTeX)
# ═══════════════════════════════════════════════════════════════════════════════

_APS_LARGE_RCPARAMS = {
    **_APS_RCPARAMS,
    "font.size": 22,
    "axes.labelsize": 24,
    "xtick.labelsize": 20,
    "ytick.labelsize": 20,
    "legend.fontsize": 16,
    "axes.linewidth": 1.2,
    "lines.linewidth": 2.0,
    "lines.markersize": 8,
    "xtick.major.size": 6,
    "ytick.major.size": 6,
    "xtick.minor.size": 3,
    "ytick.minor.size": 3,
    "xtick.major.width": 1.0,
    "ytick.major.width": 1.0,
    "figure.dpi": 300,
    "savefig.dpi": 300,
}


def apply_aps_large_style():
    """Apply APS large-font style for panels shrunk via 0.48\\textwidth in LaTeX."""
    plt.rcParams.update(_APS_LARGE_RCPARAMS)


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience: get full rcParams dict for external use
# ═══════════════════════════════════════════════════════════════════════════════

def get_style_dict(style="aps"):
    """Return the rcParams dict for a given style name."""
    styles = {
        "aps": _APS_RCPARAMS,
        "aps_latex": _APS_LATEX_RCPARAMS,
        "aps_large": _APS_LARGE_RCPARAMS,
        "nature": _NATURE_RCPARAMS,
    }
    if style not in styles:
        raise ValueError(f"Unknown style: {style}. Available: {list(styles.keys())}")
    return dict(styles[style])
