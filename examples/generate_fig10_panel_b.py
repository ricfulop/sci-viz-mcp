#!/usr/bin/env python3
"""
Panel (b) -- APS-style "Topotactic Collapse & Metallization".

Minimal redesign:
  - 8YSZ parent -> Ar600 child suboxide with "Flash activation" arrow
  - Zr-Zr spacing shown explicitly for parent and contracted child
  - Reference-pattern + flashed SAED strip directly below the schematics
  - Self-explanatory "Why 8% in SAED?" arithmetic below the diffraction
  - APS serif typography and vector-friendly export
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, Rectangle
import matplotlib.image as mpimg
from PIL import Image

from styles import apply_aps_style

OUT_DIR = Path(__file__).parent.parent / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SAED_IMG = OUT_DIR / "saed_jo_110_clean.png"
DUAL_SAED_IMG = Path.home() / ".cursor" / "projects" / \
    "Users-ricfulop-voltivity-phonon-cascades-flash-electrons-repo" / \
    "assets" / "62BBD83E-6F0E-400A-819F-B68549F10C18_1_201_a-8091b797-7c8f-44f3-861d-79ef57266f18.png"

# Muted Nature-friendly palette
ZR_BLUE   = "#3B6FB0"
O_RED     = "#D84B3A"
METAL_ORANGE = "#C4632B"
GREEN     = "#2E8C60"
DARK_GRAY = "#333333"
MID_GRAY  = "#666666"
LIGHT_GRAY = "#BBBBBB"
PALE_AMBER = "#F3D39C"


def _load_image_any_format(path):
    """Load image data even when the filename extension is wrong."""
    if not path.exists():
        return None
    return np.asarray(Image.open(path))


def _split_diffraction_pair(img):
    """Split the dual reference/SAED figure at its bright center separator."""
    if img is None:
        return None, None

    h, w = img.shape[:2]
    if w < 1.6 * h:
        return img, None

    gray = img.mean(axis=2) if img.ndim == 3 else img
    center = w // 2
    search_half = max(24, w // 10)
    x0 = max(0, center - search_half)
    x1 = min(w, center + search_half)
    col_mean = gray[:, x0:x1].mean(axis=0)
    bright = np.where(col_mean > 250)[0]
    if len(bright) > 0:
        sep_l = x0 + int(bright[0])
        sep_r = x0 + int(bright[-1]) + 1
    else:
        sep_l = center - max(8, w // 40)
        sep_r = center + max(8, w // 40)

    left = img[:, :sep_l]
    right = img[:, sep_r:]
    return left, right


def _draw_fluorite_cell(ax, cx, cy, side):
    scale = side / 1.78
    h = side / 2
    ax.add_patch(Rectangle((cx - h, cy - h), side, side,
                            facecolor="none", edgecolor=MID_GRAY,
                            linewidth=0.8, zorder=10))
    for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1), (0, 0)]:
        ax.add_patch(Circle((cx + dx * h, cy + dy * h), 0.22 * scale,
                             facecolor=ZR_BLUE, edgecolor="none",
                             zorder=15))
    for dx, dy in [(-0.5, -0.5), (0.5, -0.5), (-0.5, 0.5), (0.5, 0.5)]:
        ax.add_patch(Circle((cx + dx * h, cy + dy * h), 0.15 * scale,
                             facecolor=O_RED, edgecolor="none",
                             zorder=16))


def _draw_suboxide_child_cell(ax, cx, cy, side):
    scale = side / 1.78
    h = side / 2
    ax.add_patch(Rectangle((cx - h, cy - h), side, side,
                            facecolor="none", edgecolor=METAL_ORANGE,
                            linewidth=0.9, zorder=10))
    for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1), (0, 0)]:
        ax.add_patch(Circle((cx + dx * h, cy + dy * h), 0.30 * scale,
                             facecolor=PALE_AMBER, edgecolor="none",
                             alpha=0.35, zorder=14))
        ax.add_patch(Circle((cx + dx * h, cy + dy * h), 0.22 * scale,
                             facecolor=ZR_BLUE, edgecolor="none",
                             zorder=15))
    # 2 occupied + 2 vacant O sites (partial depletion / suboxide child)
    for dx, dy in [(0, -1), (-1, 0)]:
        ax.add_patch(Circle((cx + dx * h, cy + dy * h), 0.15 * scale,
                             facecolor=O_RED, edgecolor="none",
                             zorder=16))
    for dx, dy in [(0, 1), (1, 0)]:
        ax.add_patch(Circle((cx + dx * h, cy + dy * h), 0.17 * scale,
                             facecolor="none", edgecolor=METAL_ORANGE,
                             linewidth=1.0, linestyle=(0, (2, 1.3)),
                             zorder=16))


def _draw_diffraction_image(ax, img, center_x, center_y, img_h,
                            title, subtitle=None, title_y_offset=0.14):
    """Render a diffraction image at native aspect with compact captions."""
    aspect = img.shape[1] / img.shape[0]
    img_w = img_h * aspect
    x0 = center_x - img_w / 2
    y0 = center_y - img_h / 2
    ax.imshow(img, extent=(x0, x0 + img_w, y0, y0 + img_h),
              zorder=22, aspect="auto")
    ax.add_patch(Rectangle((x0, y0), img_w, img_h,
                           facecolor="none", edgecolor=LIGHT_GRAY,
                           linewidth=0.55, zorder=23))
    ax.text(center_x, y0 - title_y_offset,
            title, fontsize=7.0, color=MID_GRAY, ha="center", va="top")
    if subtitle:
        ax.text(center_x, y0 - title_y_offset - 0.22,
                subtitle, fontsize=6.1, color=MID_GRAY, ha="center", va="top",
                fontstyle="italic")
    return img_w, img_h


def panel_b(ax):
    ax.set_xlim(0, 15.8)
    ax.set_ylim(0.35, 7.25)
    ax.set_aspect("equal")
    ax.axis("off")

    dual_img = None
    if DUAL_SAED_IMG.exists():
        dual_img = _load_image_any_format(DUAL_SAED_IMG)
    elif SAED_IMG.exists():
        dual_img = _load_image_any_format(SAED_IMG)
    ref_img, flash_img = _split_diffraction_pair(dual_img)
    if flash_img is None:
        flash_img = ref_img

    # ── Two compact evidence groups: parent on left, child on right ──
    left_cx = 3.55
    right_cx = 12.25
    cell_y = 5.20
    diff_y = 5.06

    side_f = 1.78 * 1.15
    side_r = side_f * 0.92  # visibly smaller (8% contraction)
    fc_x, fc_y = left_cx - 1.45, cell_y
    rc_x, rc_y = right_cx - 1.35, cell_y

    _draw_fluorite_cell(ax, fc_x, fc_y, side_f)
    _draw_suboxide_child_cell(ax, rc_x, rc_y, side_r)

    # Group titles
    ax.text(left_cx, 6.95,
            "8YSZ Parent",
            fontsize=10, fontweight="bold", color=ZR_BLUE,
            ha="center", va="center")
    ax.text(right_cx, 6.95,
            "Ar600 Child\nSuboxide",
            fontsize=9.6, fontweight="bold", color=METAL_ORANGE,
            ha="center", va="center")

    # Sub-labels
    ax.text(fc_x, fc_y - side_f / 2 - 0.35,
            "fluorite,  O in 8c", fontsize=7.4, color=MID_GRAY,
            ha="center", va="center", fontstyle="italic")
    ax.text(rc_x, rc_y - side_r / 2 - 0.35,
            "rocksalt-like,  O in 4b", fontsize=7.4, color=MID_GRAY,
            ha="center", va="center", fontstyle="italic")

    # ── Zr-Zr distance arrows inside cells + inline labels (no box) ──
    h_f = side_f / 2
    ax.annotate("", xy=(fc_x, fc_y), xytext=(fc_x - h_f, fc_y - h_f),
                arrowprops=dict(arrowstyle="<->", color=ZR_BLUE, lw=1.0),
                zorder=20)
    ax.text(fc_x - h_f * 1.05, fc_y - h_f * 0.75,
            "3.63 Å", fontsize=10, color=ZR_BLUE,
            ha="right", va="center", fontweight="bold")

    h_r = side_r / 2
    ax.annotate("", xy=(rc_x, rc_y), xytext=(rc_x - h_r, rc_y - h_r),
                arrowprops=dict(arrowstyle="<->", color=METAL_ORANGE,
                                lw=1.0),
                zorder=20)
    ax.text(rc_x - h_r * 1.05, rc_y - h_r * 0.75,
            "3.34 Å", fontsize=10, color=METAL_ORANGE,
            ha="right", va="center", fontweight="bold")

    # Diffraction companions next to each CIF
    img_h = 1.90 * 1.15
    _draw_diffraction_image(ax, ref_img, left_cx + 1.36, diff_y, img_h,
                            "Reference [110]")
    _draw_diffraction_image(ax, flash_img, right_cx + 1.26, diff_y, img_h,
                            "Flashed SAED [110]",
                            subtitle="(single-crystal 8YSZ, Jo et al.)")

    # ── Flash activation arrow between the two groups ──
    arr = FancyArrowPatch((7.05, cell_y), (8.75, cell_y),
                          arrowstyle="-|>", mutation_scale=14,
                          linewidth=1.4, color=DARK_GRAY, zorder=18)
    ax.add_patch(arr)
    ax.text(7.90, cell_y + 0.20, "Flash",
            fontsize=9, color=DARK_GRAY, ha="center", va="bottom")

    # ── Compact explanation band beneath the two groups ──
    math_cx = 7.9
    math_y = 3.00

    ax.text(math_cx, math_y,
            "Why is the child 8% smaller in SAED?",
            fontsize=9.1, color=DARK_GRAY, ha="center", va="bottom",
            fontweight="bold")

    ax.text(math_cx, math_y - 0.44,
            "Packing collapse:  8c $\\rightarrow$ 4b  $\\Rightarrow$  "
            "$\\sqrt{3}/2 = 0.866$  (−13.4%)",
            fontsize=8.3, color=ZR_BLUE, ha="center", va="center")

    ax.text(math_cx, math_y - 0.92,
            "Electronic expansion:  $\\mathrm{Zr}^{4+}\\!\\to\\mathrm{Zr}^{2+}$"
            r"  $\Rightarrow$  $\times 1.062$  (+6.2%)",
            fontsize=8.3, color=METAL_ORANGE, ha="center", va="center")

    ax.plot([2.10, 13.70], [math_y - 1.26, math_y - 1.26],
            color=LIGHT_GRAY, lw=0.5, zorder=30)

    ax.text(math_cx, math_y - 1.58,
            r"Net child lattice:  $0.866 \times 1.062 = \mathbf{0.920}$"
            r"  $\Rightarrow$  $\mathbf{8.0\%}$ contraction",
            fontsize=8.8, color=DARK_GRAY, ha="center", va="center")

    ax.text(math_cx, math_y - 1.98,
            r"$a_{\mathrm{child}} = 5.145 \times 0.920 = "
            r"\mathbf{4.73\;\mathrm{\AA}}$  (SAED)",
            fontsize=8.6, color=GREEN, ha="center", va="center",
            fontweight="bold")


def main():
    apply_aps_style()
    fig, ax = plt.subplots(figsize=(5.6, 2.45))
    panel_b(ax)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)

    out_png = str(OUT_DIR / "fig10_panel_b_v2.png")
    out_pdf = str(OUT_DIR / "fig10_panel_b_v2.pdf")
    fig.savefig(out_png, dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(out_pdf, dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    print(f"Panel (b):  {out_png}")
    print(f"            {out_pdf}")


if __name__ == "__main__":
    main()
