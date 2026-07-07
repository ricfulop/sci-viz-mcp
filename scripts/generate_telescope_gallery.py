#!/usr/bin/env python3
"""
Render the README telescope gallery from the ray_optics_mcp presets.

Usage:
    python3 scripts/generate_telescope_gallery.py [--out assets/telescopes]

Requires ray_optics_mcp/vendor to be built (npm install).
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ray_optics_mcp"))
sys.path.insert(0, str(ROOT))

import ray_optics_mcp_server as srv  # noqa: E402

GALLERY = [
    ("newtonian", {}, "Newtonian"),
    ("ritchey_chretien", {}, "Ritchey-Chretien"),
    ("schmidt_cassegrain", {}, "Schmidt-Cassegrain"),
    ("maksutov_cassegrain", {}, "Maksutov-Cassegrain"),
    ("apo_triplet", {"chromatic": True}, "Apochromatic ED Triplet"),
    ("flatfield_petzval", {"chromatic": True}, "Flatfield Petzval"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "assets" / "telescopes"))
    ap.add_argument("--width", type=int, default=1100)
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for design, params, label in GALLERY:
        made = srv.handle_make_telescope({"design": design, "params": params,
                                          "name": f"gallery_{design}"})
        scene_id = made["scene_id"]
        out_file = out_dir / f"{design}.png"
        # Explicit region: auto-bounds ignore TextLabel extents, so pad the
        # right side generously to keep prescription labels inside the frame.
        scene = srv._scenes[scene_id]["scene"]
        x0, y0, x1, y1 = srv._scene_bounds(scene)
        res = srv.handle_render({
            "scene_id": scene_id,
            "image_width": args.width,
            "region": {"x0": x0 - 80, "y0": y0 - 80, "x1": x1 + 420, "y1": y1 + 80},
            "output_file": str(out_file),
        })
        print(f"  {label:28s} -> {res['image_path']}")


if __name__ == "__main__":
    main()
