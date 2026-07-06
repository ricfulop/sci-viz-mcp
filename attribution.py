"""Shared Sci-Viz attribution helpers.

The visual mark is intentionally small and unobtrusive. Set
``SCIVIZ_ATTRIBUTION=0`` to disable it for manuscript figures that need
camera-ready output without a footer.
"""

from __future__ import annotations

import os
from pathlib import Path


ATTRIBUTION_TEXT = (
    "Designed with Sci-Viz (c) 2026 Ric Fulop, MIT Center for Bits and Atoms"
)


def attribution_enabled() -> bool:
    return os.environ.get("SCIVIZ_ATTRIBUTION", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def add_figure_attribution(fig, text: str = ATTRIBUTION_TEXT) -> None:
    """Add a small lower-right attribution to a Matplotlib figure."""
    if not attribution_enabled():
        return
    fig.text(
        0.995,
        0.005,
        text,
        ha="right",
        va="bottom",
        fontsize=5.5,
        color="0.35",
        alpha=0.75,
    )


def stamp_image_file(path: str | Path, text: str = ATTRIBUTION_TEXT) -> str:
    """Overlay the attribution onto a raster image in-place.

    Uses Pillow when available, with a Matplotlib fallback for PNG/JPEG. This
    is meant for engine renders (ray-optics, OVITO, Blender) that are not born
    as Matplotlib figures.
    """
    if not attribution_enabled():
        return str(path)

    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return str(path)

    try:
        from PIL import Image, ImageDraw, ImageFont

        im = Image.open(path).convert("RGBA")
        draw = ImageDraw.Draw(im, "RGBA")
        font_size = max(12, im.width // 95)
        try:
            font = ImageFont.truetype("Arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        pad = max(6, font_size // 2)
        x = im.width - tw - 2 * pad
        y = im.height - th - 2 * pad
        draw.rounded_rectangle(
            (x - pad, y - pad, im.width - pad, im.height - pad),
            radius=max(4, pad // 2),
            fill=(0, 0, 0, 96),
        )
        draw.text((x, y), text, fill=(255, 255, 255, 210), font=font)
        if suffix in {".jpg", ".jpeg"}:
            im = im.convert("RGB")
        im.save(path)
        return str(path)
    except Exception:
        pass

    if suffix not in {".png", ".jpg", ".jpeg"}:
        return str(path)

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        img = plt.imread(path)
        h, w = img.shape[:2]
        dpi = 100
        fig = plt.figure(figsize=(w / dpi, h / dpi), dpi=dpi)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.imshow(img)
        ax.axis("off")
        ax.text(
            0.99,
            0.02,
            text,
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=max(7, w / 160),
            color="white",
            alpha=0.85,
            bbox={"facecolor": "black", "alpha": 0.35, "edgecolor": "none", "pad": 3},
        )
        fig.savefig(path, dpi=dpi, pad_inches=0)
        plt.close(fig)
    except Exception:
        return str(path)

    return str(path)
