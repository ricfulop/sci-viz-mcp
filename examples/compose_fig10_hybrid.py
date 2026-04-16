#!/usr/bin/env python3
"""
Compose final Figure 10 using:
  - Panels (a), (b), (d) from the baseline fig10_anatomy_coherent_condensation
  - Panel (c) from the new hybrid DFPT + rotated Raman
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent.parent.resolve()
OUT_DIR = ROOT / "output"
OUT_DIR.mkdir(exist_ok=True)

BASELINE = Path.home() / "voltivity" / "microscopic-origins-overleaf" / \
    "Microscopic Origins of Voltivity" / "microscopic_origins_latex" / \
    "fig10_anatomy_coherent_condensation.png"

PANEL_C = OUT_DIR / "panel_c_hybrid.png"
PANEL_D = OUT_DIR / "panel_d_v3.png"


def main():
    baseline_raw = Image.open(str(BASELINE))
    if baseline_raw.mode == "RGBA":
        baseline = Image.new("RGB", baseline_raw.size, (255, 255, 255))
        baseline.paste(baseline_raw, mask=baseline_raw.split()[3])
    else:
        baseline = baseline_raw.convert("RGB")

    def load_white_bg(path):
        img = Image.open(str(path))
        if img.mode == "RGBA":
            out = Image.new("RGB", img.size, (255, 255, 255))
            out.paste(img, mask=img.split()[3])
            return out
        return img.convert("RGB")

    panel_c = load_white_bg(PANEL_C)
    panel_d_new = load_white_bg(PANEL_D) if PANEL_D.exists() else None

    bw, bh = baseline.size
    print(f"Baseline: {bw}x{bh}")
    print(f"Panel C:  {panel_c.size[0]}x{panel_c.size[1]}")

    # The baseline 2x2 layout has an approximate vertical split around y~1170
    # (a) is top-left: ~(0, 0) to (~1150, ~1170)
    # (b) is top-right: ~(1150, 0) to (~2301, ~1170)
    # (c) is bottom-left: ~(0, 1170) to (~1150, ~2400)
    # (d) is bottom-right: ~(1150, 1170) to (~2301, ~2400)

    # y_split captures full top row (a)+(b) including (b)'s math box + SAED
    y_split = 1270
    x_split = 1140

    panel_a = baseline.crop((0, 0, x_split, y_split))
    panel_b = baseline.crop((x_split, 0, bw, y_split))

    # Grab the "(c) Zone Folding..." title strip from baseline
    c_title_strip = baseline.crop((0, y_split, x_split, y_split + 55))

    # Use new 3D Panel D if available, otherwise crop from baseline
    if panel_d_new is not None:
        panel_d = panel_d_new
        # Grab "(d) Macroscopic Evolution..." title strip from baseline
        d_title_strip = baseline.crop((x_split, y_split, bw, y_split + 55))
    else:
        panel_d = baseline.crop((x_split, y_split, bw, bh))
        d_title_strip = None

    print(f"Panel A crop: {panel_a.size}")
    print(f"Panel B crop: {panel_b.size}")
    print(f"Panel D crop: {panel_d.size}")

    target_w = bw

    # Scale panel C to fill bottom-left width
    c_target_w = x_split
    c_scale = c_target_w / panel_c.width
    c_new_h = int(panel_c.height * c_scale)
    panel_c_resized = panel_c.resize((c_target_w, c_new_h), Image.LANCZOS)
    title_h = c_title_strip.height

    # Scale panel D to fill bottom-right width
    d_target_w = target_w - x_split
    if d_title_strip is not None:
        d_scale = d_target_w / panel_d.width
        d_new_h = int(panel_d.height * d_scale)
        panel_d_resized = panel_d.resize((d_target_w, d_new_h), Image.LANCZOS)
        d_title_h = d_title_strip.height
    else:
        panel_d_resized = panel_d
        d_new_h = panel_d.height
        d_title_h = 0

    top_h = max(panel_a.height, panel_b.height)
    bot_h = max(title_h + c_new_h, d_title_h + d_new_h)

    total_h = top_h + bot_h

    composite = Image.new("RGB", (target_w, total_h), (255, 255, 255))

    composite.paste(panel_a, (0, 0))
    composite.paste(panel_b, (x_split, 0))
    composite.paste(c_title_strip, (0, top_h))
    composite.paste(panel_c_resized, (0, top_h + title_h))
    if d_title_strip is not None:
        composite.paste(d_title_strip, (x_split, top_h))
        composite.paste(panel_d_resized, (x_split, top_h + d_title_h))
    else:
        composite.paste(panel_d_resized, (x_split, top_h))

    # Save
    out_png = str(OUT_DIR / "fig10_hybrid_composite.png")
    out_pdf = str(OUT_DIR / "fig10_hybrid_composite.pdf")
    composite.save(out_png, quality=95)
    composite.save(out_pdf)

    # Also copy to the overleaf directory
    overleaf_dir = Path.home() / "voltivity" / "microscopic-origins-overleaf" / \
        "Microscopic Origins of Voltivity" / "microscopic_origins_latex"
    for fmt, src in [("png", out_png), ("pdf", out_pdf)]:
        dst = overleaf_dir / f"fig10_anatomy_coherent_condensation_v2.{fmt}"
        import shutil
        shutil.copy2(src, str(dst))
        print(f"  Copied to: {dst}")

    print(f"\n  Composite: {composite.size[0]}x{composite.size[1]}")
    print(f"  Saved: {out_png}")
    print(f"  Saved: {out_pdf}")


if __name__ == "__main__":
    main()
