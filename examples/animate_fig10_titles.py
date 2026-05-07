#!/usr/bin/env python3
"""Generate Helvetica title-card PNGs and ffmpeg-overlay them onto the
Fig. 10 animation.

The system ffmpeg may be built without libfreetype (so no `drawtext`
filter), but `overlay` is universally available. We render the cards as
transparent 1280x720 PNGs in PIL, then composite them with `overlay`
gated on the `enable` expression for each clip range.

Usage:
    /path/to/.venv/bin/python examples/animate_fig10_titles.py

Outputs:
    output/anim_fig10/titles/<i>_<slug>.png    (six PNG cards)
    output/anim_fig10/fig10_animation_titled.mp4
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
DEFAULT_IN = REPO / "output" / "anim_fig10" / "fig10_animation.mp4"
DEFAULT_OUT = REPO / "output" / "anim_fig10" / "fig10_animation_titled.mp4"
TITLE_DIR = REPO / "output" / "anim_fig10" / "titles"

WIDTH, HEIGHT = 1280, 720
FONT_PATHS = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
)

# (start_s, end_s, text)
# We avoid Unicode superscripts (⁴⁺, ²⁺) because macOS system Arial/
# Helvetica TTFs don't ship the Latin-Extended-Superscripts block. Use
# parentheses for oxidation states instead — this is also Nature's
# in-text convention.
#
# Card timing tracks the new templating-aware Blender timeline:
#   0.0 – 3.0 s    Act 1   establishing rotation
#   3.0 – 9.0 s    Act 2   wave grows + antinode discs reveal
#   9.0 – 13.0 s   Act 3a  Frenkel kick + interstitial escape
#  13.0 – 17.0 s   Act 3b  topotactic collapse + lattice contraction
#  17.0 – 21.0 s   Act 4   zone-folding placeholder
#  21.0 – 26.0 s   Act 5   Ostwald ripening
#  26.0 – 28.0 s   closing title
CARDS: list[tuple[float, float, str]] = [
    (0.2,  3.0,  "Acoustic blueprint   d* ≈ 0.96 a"),
    (3.2,  9.0,  "Phonon mode amplifies — antinodes template the lattice"),
    (9.0,  12.8, "Frenkel pairs nucleate at antinode planes"),
    (13.0, 16.8, "Topotactic collapse   Zr(IV) → Zr(II)   8% [110] contraction"),
    (17.0, 20.5, "Zone-folding Raman signature   458 cm-1"),
    (21.0, 25.5, "Ostwald ripening   ~200 nm dendritic 2DEG colonies"),
    (26.0, 28.0, "Ordered Defect Condensation"),
]

CARD_FONT_PT = 30
CARD_BG = (255, 255, 255, 0)          # transparent — video already white
CARD_FG = (24, 26, 32, 255)           # near-black
CARD_PADDING = 0
CARD_MARGIN_X = 40
CARD_MARGIN_Y = 40


def _load_font() -> ImageFont.FreeTypeFont:
    for p in FONT_PATHS:
        if Path(p).is_file():
            return ImageFont.truetype(p, CARD_FONT_PT)
    raise RuntimeError("No suitable font found: " + ", ".join(FONT_PATHS))


def _slugify(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text)[:40].strip("_").lower()


def _render_card(text: str, path: Path, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    text_x = CARD_MARGIN_X - bbox[0]
    text_y = HEIGHT - CARD_MARGIN_Y - th - bbox[1]

    if CARD_BG[3] > 0:
        box_x = text_x + bbox[0] - CARD_PADDING
        box_y = text_y + bbox[1] - CARD_PADDING
        draw.rounded_rectangle(
            [(box_x, box_y),
             (box_x + tw + 2 * CARD_PADDING, box_y + th + 2 * CARD_PADDING)],
            radius=8, fill=CARD_BG,
        )
    draw.text((text_x, text_y), text, font=font, fill=CARD_FG)
    img.save(path, "PNG")
    return tw, th


def _generate_cards() -> list[tuple[Path, float, float]]:
    TITLE_DIR.mkdir(parents=True, exist_ok=True)
    font = _load_font()
    out: list[tuple[Path, float, float]] = []
    for i, (t0, t1, text) in enumerate(CARDS):
        path = TITLE_DIR / f"{i:02d}_{_slugify(text)}.png"
        _render_card(text, path, font)
        out.append((path, t0, t1))
    return out


def _build_filter_complex(card_paths: list[tuple[Path, float, float]]) -> str:
    """Chain N overlay filters together with time gating."""
    parts = ["[0:v]null[v0]"]
    n = len(card_paths)
    for i, (_, t0, t1) in enumerate(card_paths):
        in_label = f"v{i}"
        out_label = "vout" if i == n - 1 else f"v{i+1}"
        parts.append(
            f"[{in_label}][{i+1}:v]"
            f"overlay=enable='between(t,{t0:.2f},{t1:.2f})':x=0:y=0"
            f"[{out_label}]"
        )
    return ";".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="in_path", default=str(DEFAULT_IN))
    parser.add_argument("--out", dest="out_path", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    in_path = Path(args.in_path)
    out_path = Path(args.out_path)
    if not in_path.is_file():
        print(f"error: missing input video {in_path}", file=sys.stderr)
        return 1

    print(f"▸ rendering {len(CARDS)} title cards → {TITLE_DIR}")
    cards = _generate_cards()
    for path, t0, t1 in cards:
        print(f"   {path.name}  [{t0:.1f} – {t1:.1f} s]")

    cmd = ["ffmpeg", "-y", "-i", str(in_path)]
    for path, _, _ in cards:
        cmd.extend(["-i", str(path)])
    filter_complex = _build_filter_complex(cards)
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "18", "-preset", "slow",
        "-movflags", "+faststart",
        str(out_path),
    ])
    print()
    print("▸ ffmpeg")
    print("   " + " ".join(shlex.quote(c) for c in cmd))
    print()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        return proc.returncode

    print(f"\nwrote {out_path}")
    print(f"size: {out_path.stat().st_size / 1024 / 1024:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
