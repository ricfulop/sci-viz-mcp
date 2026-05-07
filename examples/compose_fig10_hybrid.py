#!/usr/bin/env python3
"""
Compose final Figure 10 ("Anatomy of Coherent Condensation") using:
  - Panel (a) from fig10_panel_a_v2.png  (new acoustic-blueprint render)
  - Panel (b) from fig10_panel_b_v2.png  (new topotactic-collapse render)
  - Panel (c) from panel_c_hybrid.png    (zone folding + rotated Raman)
  - Panel (d) from panel_d_v3.png        (OVITO 3D Ostwald triptych)

All four lowercase panel labels are drawn here at one common pixel size so
they stay visually consistent after row-level resizing.
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import matplotlib.font_manager as fm

ROOT = Path(__file__).parent.parent.resolve()
OUT_DIR = ROOT / "output"
OUT_DIR.mkdir(exist_ok=True)

BASELINE = Path.home() / "voltivity" / "microscopic-origins-overleaf" / \
    "Microscopic Origins of Voltivity" / "microscopic_origins_latex" / \
    "fig10_anatomy_coherent_condensation.png"

PANEL_A = OUT_DIR / "fig10_panel_a_v2.png"
PANEL_B = OUT_DIR / "fig10_panel_b_v2.png"
PANEL_C = OUT_DIR / "panel_c_hybrid.png"
PANEL_D = OUT_DIR / "panel_d_v3.png"
PANEL_D_STAGE1 = OUT_DIR / "panel_d_stage1.png"
PANEL_D_STAGE2 = OUT_DIR / "panel_d_stage2.png"
PANEL_D_STAGE3 = OUT_DIR / "panel_d_stage3.png"

# Bottom row title strip split: col ~1050 in the whitespace gap between
# "(c) Zone Folding..." (which ends near col 900) and "(d) Macroscopic
# Evolution..." (which begins near col 1075) in the baseline TikZ render.
BASELINE_Y_SPLIT = 1270
BASELINE_X_SPLIT_CD = 1050


def load_white_bg(path):
    img = Image.open(str(path))
    if img.mode == "RGBA":
        out = Image.new("RGB", img.size, (255, 255, 255))
        out.paste(img, mask=img.split()[3])
        return out
    return img.convert("RGB")


def _panel_font(size_px, weight="bold"):
    """APS-style serif font for panel letters and panel-D captions."""
    preferred = []
    if weight == "bold":
        preferred.extend([
            "STIXGeneral:style=Bold",
            "Times New Roman:style=Bold",
            "DejaVu Serif:style=Bold",
        ])
        candidates = [
            "/Library/Fonts/Times New Roman Bold.ttf",
            "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
        ]
    else:
        preferred.extend([
            "STIXGeneral",
            "Times New Roman",
            "DejaVu Serif",
        ])
        candidates = [
            "/Library/Fonts/Times New Roman.ttf",
            "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        ]
    for name in preferred:
        try:
            path = fm.findfont(name, fallback_to_default=False)
            if path and Path(path).exists():
                return ImageFont.truetype(path, size_px)
        except Exception:
            pass
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size_px)
            except OSError:
                pass
    return ImageFont.load_default()


def _draw_panel_label(draw, x, y, label, font_size):
    """Draw an APS-style panel label on a white chip for clear separation."""
    font = _panel_font(font_size, weight="bold")
    bbox = draw.textbbox((x, y), label, font=font)
    chip_pad_x = max(5, font_size // 5)
    chip_pad_y = max(3, font_size // 7)
    chip = (
        bbox[0] - chip_pad_x,
        bbox[1] - chip_pad_y,
        bbox[2] + chip_pad_x,
        bbox[3] + chip_pad_y,
    )
    draw.rounded_rectangle(chip, radius=max(3, font_size // 7),
                           fill=(255, 255, 255))
    draw.text((x, y), label, font=font, fill=(0, 0, 0))
    return chip


def _fit_font_to_width(draw, text, max_width, start_size, min_size=18,
                       weight="bold"):
    """Find the largest APS-style serif font that fits the allotted width."""
    for size in range(start_size, min_size - 1, -1):
        font = _panel_font(size, weight=weight)
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            return font
    return _panel_font(min_size, weight=weight)


def _add_title_band(panel_img, title, band_px, font_size):
    """Add a white title band above a panel with fixed-size APS title text."""
    w, h = panel_img.size
    out = Image.new("RGB", (w, h + band_px), (255, 255, 255))
    out.paste(panel_img, (0, band_px))
    draw = ImageDraw.Draw(out)
    font = _panel_font(font_size, weight="bold")
    draw.text((w // 2, int(round(band_px * 0.56))),
              title, fill=(0, 0, 0), anchor="mm", font=font)
    return out


def _draw_text_chip(draw, x, y, title, subtitle=None, anchor="lt",
                    title_size=24, subtitle_size=15):
    """Draw a rounded white label chip, optionally with a second line."""
    title_font = _panel_font(title_size, weight="bold")
    sub_font = _panel_font(subtitle_size, weight="regular")
    pad_x = max(12, title_size // 2)
    top_pad = max(8, title_size // 3)
    bottom_pad = max(8, title_size // 3)
    line_gap = max(6, subtitle_size // 3)
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    title_h = title_bbox[3] - title_bbox[1]
    subtitle_w = subtitle_h = 0
    if subtitle:
        sub_bbox = draw.textbbox((0, 0), subtitle, font=sub_font)
        subtitle_w = sub_bbox[2] - sub_bbox[0]
        subtitle_h = sub_bbox[3] - sub_bbox[1]
        bottom_pad = max(bottom_pad, subtitle_size // 2)
    chip_w = max(title_w, subtitle_w) + 2 * pad_x
    chip_h = title_h + top_pad + bottom_pad
    if subtitle:
        chip_h += line_gap + subtitle_h

    if anchor == "lt":
        x0, y0 = x, y
    elif anchor == "lb":
        x0, y0 = x, y - chip_h
    elif anchor == "rt":
        x0, y0 = x - chip_w, y
    elif anchor == "rb":
        x0, y0 = x - chip_w, y - chip_h
    else:
        raise ValueError(f"Unsupported anchor: {anchor}")

    chip = (x0, y0, x0 + chip_w, y0 + chip_h)
    draw.rounded_rectangle(
        chip,
        radius=max(8, title_size // 3),
        fill=(255, 255, 255),
        outline=(215, 215, 215),
        width=1,
    )
    text_x = x0 + pad_x
    text_y = y0 + top_pad
    draw.text((text_x, text_y), title, font=title_font, fill=(0, 0, 0))
    if subtitle:
        draw.text(
            (text_x, text_y + title_h + line_gap),
            subtitle,
            font=sub_font,
            fill=(85, 85, 85),
        )
    return chip


def _crop_frac(img, left=0.0, top=0.0, right=1.0, bottom=1.0):
    """Crop by fractional image coordinates."""
    w, h = img.size
    box = (
        int(round(left * w)),
        int(round(top * h)),
        int(round(right * w)),
        int(round(bottom * h)),
    )
    return img.crop(box)


def _resize_to_width(img, target_w):
    target_h = int(round(target_w * img.height / img.width))
    return img.resize((target_w, target_h), Image.LANCZOS)


def _resize_to_height(img, target_h):
    target_w = int(round(target_h * img.width / img.height))
    return img.resize((target_w, target_h), Image.LANCZOS)


def _zoom_crop(img, scale, left_bias=0.10, top_bias=0.65):
    """Zoom an image in-place while protecting left/bottom labels."""
    if scale <= 1.0:
        return img
    w, h = img.size
    zw = int(round(w * scale))
    zh = int(round(h * scale))
    zoomed = img.resize((zw, zh), Image.LANCZOS)
    extra_w = max(0, zw - w)
    extra_h = max(0, zh - h)
    left = min(extra_w, max(0, int(round(extra_w * left_bias))))
    top = min(extra_h, max(0, int(round(extra_h * top_bias))))
    return zoomed.crop((left, top, left + w, top + h))


def _compose_panel_d_layout(stage1_img, stage2_img, stage3_img, panel_width,
                            max_height):
    """Lay out panel (d) within a fixed height budget matching panel (c)."""
    pad_x = max(12, int(round(panel_width * 0.014)))
    bottom_pad = max(8, int(round(max_height * 0.014)))
    gutter = max(14, int(round(panel_width * 0.016)))
    mid_gap = max(12, int(round(max_height * 0.018)))
    title_pad = max(40, int(round(max_height * 0.070)))

    # Crop 3% from the right side of each stage render, plus a tighter
    # vertical focus so the stage content survives the fixed height budget.
    s1_focus = _crop_frac(stage1_img, left=0.10, top=0.20, right=0.97, bottom=0.92)
    s2_focus = _crop_frac(stage2_img, left=0.08, top=0.20, right=0.97, bottom=0.92)
    s3_focus = _crop_frac(stage3_img, left=0.02, top=0.20, right=0.97, bottom=0.80)

    top_available_w = panel_width - 2 * pad_x - gutter
    bottom_available_w = panel_width - 2 * pad_x
    content_h_budget = max_height - title_pad - bottom_pad - mid_gap

    a1 = s1_focus.width / s1_focus.height
    a2 = s2_focus.width / s2_focus.height
    a3 = s3_focus.width / s3_focus.height

    desired_top_h = int(round(content_h_budget * 0.50))
    max_top_h_from_width = int(top_available_w / (a1 + a2))
    top_h = max(140, min(desired_top_h, max_top_h_from_width))
    s1_res = _resize_to_height(s1_focus, top_h)
    s2_res = _resize_to_height(s2_focus, top_h)

    top_total_w = s1_res.width + gutter + s2_res.width
    if top_total_w > (panel_width - 2 * pad_x):
        scale = (panel_width - 2 * pad_x) / top_total_w
        top_h = max(120, int(round(top_h * scale)))
        s1_res = _resize_to_height(s1_focus, top_h)
        s2_res = _resize_to_height(s2_focus, top_h)
        top_total_w = s1_res.width + gutter + s2_res.width

    remaining_h = max(220, content_h_budget - top_h)
    bottom_h = min(remaining_h, int(bottom_available_w / a3))
    s3_res = _resize_to_height(s3_focus, bottom_h)

    total_h = title_pad + top_h + mid_gap + s3_res.height + bottom_pad
    out = Image.new("RGB", (panel_width, max_height), (255, 255, 255))
    draw = ImageDraw.Draw(out)

    top_x0 = (panel_width - top_total_w) // 2
    s1_x = top_x0
    s2_x = top_x0 + s1_res.width + gutter
    top_y = title_pad
    s3_x = (panel_width - s3_res.width) // 2
    s3_y = title_pad + top_h + mid_gap

    out.paste(s1_res, (s1_x, top_y))
    out.paste(s2_res, (s2_x, top_y))
    out.paste(s3_res, (s3_x, s3_y))

    chip_margin = max(8, int(round(panel_width * 0.010)))
    stage_size = max(22, int(round(max_height * 0.040)))
    sub_size = max(13, int(round(max_height * 0.024))) * 2

    _draw_text_chip(
        draw,
        s1_x + chip_margin,
        top_y + chip_margin,
        "Stage 1",
        "~0.5 nm seeds",
        anchor="lt",
        title_size=stage_size,
        subtitle_size=sub_size,
    )
    _draw_text_chip(
        draw,
        s2_x + chip_margin,
        top_y + chip_margin,
        "Stage 2",
        "LSW coarsening",
        anchor="lt",
        title_size=stage_size,
        subtitle_size=sub_size,
    )
    _draw_text_chip(
        draw,
        s3_x + chip_margin,
        s3_y + chip_margin,
        "Stage 3",
        "~200 nm veins",
        anchor="lt",
        title_size=stage_size,
        subtitle_size=sub_size,
    )

    return out, title_pad


def _trim_top(img, n_px):
    """Crop `n_px` from the top of an image (used to remove the thin
    frame line above panel (c) so the title strip meets the plot
    cleanly)."""
    if n_px <= 0:
        return img
    w, h = img.size
    return img.crop((0, n_px, w, h))


def main():
    baseline = load_white_bg(BASELINE)
    bw, bh = baseline.size
    print(f"Baseline: {bw}x{bh}")

    left_col_w = 1200
    right_col_w = bw - left_col_w

    # ── Top row ────────────────────────────────────────────────────────
    panel_a_raw = load_white_bg(PANEL_A)
    panel_b_raw = load_white_bg(PANEL_B)
    pa_raw_w, pa_raw_h = panel_a_raw.size
    pb_raw_w, pb_raw_h = panel_b_raw.size

    panel_a = _resize_to_width(panel_a_raw, left_col_w)
    panel_b = _resize_to_width(panel_b_raw, right_col_w)

    top_title_band = 64
    panel_title_font_px = 26
    panel_a = _add_title_band(panel_a,
                              "Antinode Templating Across Bonding Classes",
                              top_title_band,
                              panel_title_font_px)
    panel_b = _add_title_band(panel_b,
                              "Topotactic Collapse & Metallization",
                              top_title_band,
                              panel_title_font_px)
    pa_w = panel_a.width
    pb_w = panel_b.width
    top_row_h = max(panel_a.height, panel_b.height)

    print(f"Panel A:  {panel_a.size[0]}x{panel_a.size[1]} "
          f"(from {pa_raw_w}x{pa_raw_h})")
    print(f"Panel B:  {panel_b.size[0]}x{panel_b.size[1]} "
          f"(from {pb_raw_w}x{pb_raw_h})")

    target_w = bw

    # ── Bottom row ─────────────────────────────────────────────────────
    panel_c = load_white_bg(PANEL_C)
    # Trim the thin frame line at the top of panel C so the title
    # strip meets the plot cleanly.
    panel_c = _trim_top(panel_c, n_px=6)

    print(f"Panel C:  {panel_c.size[0]}x{panel_c.size[1]}")
    if PANEL_D_STAGE1.exists() and PANEL_D_STAGE2.exists() and PANEL_D_STAGE3.exists():
        stage1_raw = load_white_bg(PANEL_D_STAGE1)
        stage2_raw = load_white_bg(PANEL_D_STAGE2)
        stage3_raw = load_white_bg(PANEL_D_STAGE3)
        print(f"Panel D stages: {stage1_raw.size[0]}x{stage1_raw.size[1]}, "
              f"{stage2_raw.size[0]}x{stage2_raw.size[1]}, "
              f"{stage3_raw.size[0]}x{stage3_raw.size[1]}")
    else:
        stage1_raw = stage2_raw = stage3_raw = None
        panel_d_raw = load_white_bg(PANEL_D)
        print(f"Panel D raw:  {panel_d_raw.size[0]}x{panel_d_raw.size[1]}")

    # Narrower left column gives denser right-column panels more room.
    c_target_w = left_col_w
    d_target_w = right_col_w

    c_scale = c_target_w / panel_c.width
    c_content_h = int(round(panel_c.height * c_scale))
    panel_c_resized = panel_c.resize((c_target_w, c_content_h), Image.LANCZOS)
    c_title_band = 64
    panel_c_resized = _add_title_band(panel_c_resized,
                                      "Zone Folding & Raman Signature",
                                      c_title_band,
                                      panel_title_font_px)
    c_new_h = panel_c_resized.height

    if stage1_raw is not None:
        panel_d_resized, d_inline_title_band = _compose_panel_d_layout(
            stage1_raw, stage2_raw, stage3_raw, d_target_w, c_new_h
        )
    else:
        d_scale = d_target_w / panel_d_raw.width
        d_base_h = int(round(panel_d_raw.height * d_scale))
        panel_d_base = panel_d_raw.resize((d_target_w, d_base_h), Image.LANCZOS)
        panel_d_resized, d_inline_title_band = _compose_panel_d_layout(
            panel_d_base, panel_d_base, panel_d_base, d_target_w, c_new_h
        )
    d_new_h = panel_d_resized.height

    row_gap = 30
    bottom_row_h = max(c_new_h, d_new_h)
    total_h = top_row_h + row_gap + bottom_row_h

    composite = Image.new("RGB", (target_w, total_h), (255, 255, 255))

    # True asymmetric 2x2: narrower left column, wider right column.
    composite.paste(panel_a, (0, 0))
    composite.paste(panel_b, (left_col_w, 0))

    bottom_y = top_row_h + row_gap
    composite.paste(panel_c_resized, (0, bottom_y))
    d_x = c_target_w
    composite.paste(panel_d_resized, (d_x, bottom_y))

    # Unified panel letters at one pixel size so no panel gets
    # accidentally emphasized by a different render/resize path.
    draw = ImageDraw.Draw(composite)
    label_font_px = max(24, int(round(top_title_band * 0.44)))
    pad_x = 14
    top_label_y = 10
    _draw_panel_label(draw, pad_x, top_label_y, "(a)", label_font_px)
    _draw_panel_label(draw, pa_w + pad_x, top_label_y, "(b)", label_font_px)
    c_label_y = bottom_y + 10
    _draw_panel_label(draw, pad_x, c_label_y, "(c)", label_font_px)
    d_label_y = bottom_y + 10
    d_chip = _draw_panel_label(draw, d_x + pad_x, d_label_y,
                               "(d)", label_font_px)
    d_title = "Macroscopic Evolution: Ostwald Ripening"
    d_title_font = _panel_font(panel_title_font_px, weight="bold")
    d_title_y = (d_chip[1] + d_chip[3]) // 2
    title_bbox = draw.textbbox((0, 0), d_title, font=d_title_font)
    title_w = title_bbox[2] - title_bbox[0]
    title_x = max(d_chip[2] + 12, d_x + (d_target_w - title_w) // 2)
    title_x = min(title_x, target_w - 14 - title_w)
    draw.text((title_x, d_title_y), d_title,
              font=d_title_font, fill=(0, 0, 0), anchor="lm")

    out_png = str(OUT_DIR / "fig10_hybrid_composite.png")
    out_pdf = str(OUT_DIR / "fig10_hybrid_composite.pdf")
    composite.save(out_png, quality=95)

    # Save PDF via img2pdf (avoids PIL's JPEG-in-PDF dependency)
    import img2pdf
    with open(out_pdf, "wb") as f:
        f.write(img2pdf.convert(out_png))

    overleaf_dir = Path.home() / "voltivity" / "microscopic-origins-overleaf" / \
        "Microscopic Origins of Voltivity" / "microscopic_origins_latex"
    import shutil
    for fmt, src in [("png", out_png), ("pdf", out_pdf)]:
        dst = overleaf_dir / f"fig10_anatomy_coherent_condensation_v2.{fmt}"
        shutil.copy2(src, str(dst))
        print(f"  Copied to: {dst}")

    print(f"\n  Composite: {composite.size[0]}x{composite.size[1]}")
    print(f"  Saved: {out_png}")
    print(f"  Saved: {out_pdf}")


if __name__ == "__main__":
    main()
