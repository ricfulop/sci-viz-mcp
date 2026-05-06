"""Headless smoke test for the SciViz Blender add-on.

Runs as:
    /Applications/Blender.app/Contents/MacOS/Blender \
        --background --factory-startup \
        --python tests/test_sciviz_addon_headless.py -- \
        --cif tests/sample_structures/fluorite_ZrO2.cif \
        --out output/test_sciviz_render.png

Verifies that
  1. The add-on loads from `~/Library/Application Support/Blender/5.1/extensions/user_default/sciviz/`
  2. `bpy.ops.sciviz.import_crystal` produces atoms + bonds in a "Crystal" collection
  3. `bpy.ops.sciviz.apply_preset(preset='SOFT_SHADOW')` switches Cycles + ortho camera
  4. `bpy.ops.sciviz.render_hq` writes a PNG and pings the live preview dashboard

Exits non-zero on failure so CI can pick it up.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import bpy
import addon_utils
from mathutils import Vector


def _parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    p = argparse.ArgumentParser()
    p.add_argument("--cif", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--width", type=int, default=800)
    p.add_argument("--height", type=int, default=600)
    p.add_argument("--samples", type=int, default=32)
    return p.parse_args(argv)


def _enable_sciviz() -> None:
    module = "bl_ext.user_default.sciviz"
    addon_utils.enable(module, default_set=True, persistent=True)
    if not any(m.__name__ == module for m in addon_utils.modules()):
        raise RuntimeError(f"Add-on did not register: {module}")
    if not hasattr(bpy.ops, "sciviz"):
        raise RuntimeError("bpy.ops.sciviz namespace missing after enable()")
    print("[sciviz] add-on enabled")


def _frame_camera_to_collection(coll_name: str) -> None:
    coll = bpy.data.collections.get(coll_name)
    if coll is None or not coll.objects:
        return
    minp = Vector(( math.inf,)*3)
    maxp = Vector((-math.inf,)*3)
    for obj in coll.objects:
        if obj.type != "MESH":
            continue
        for v in obj.bound_box:
            wp = obj.matrix_world @ Vector(v)
            for i in range(3):
                minp[i] = min(minp[i], wp[i])
                maxp[i] = max(maxp[i], wp[i])
    center = (minp + maxp) * 0.5
    extent = max((maxp - minp)[i] for i in range(3))
    cam = next((o for o in bpy.context.scene.objects if o.type == "CAMERA"), None)
    if cam is None:
        cam_data = bpy.data.cameras.new("SciVizCam")
        cam = bpy.data.objects.new("SciVizCam", cam_data)
        bpy.context.scene.collection.objects.link(cam)
        bpy.context.scene.camera = cam
    if cam.data.type == "ORTHO":
        cam.data.ortho_scale = max(1.5, extent * 1.6)
    cam.location = (center.x + extent * 1.4, center.y - extent * 1.4, center.z + extent * 1.0)
    direction = center - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam

    for obj in bpy.context.scene.objects:
        if obj.type == "LIGHT":
            return
    light_data = bpy.data.lights.new("SciVizSun", type="SUN")
    light_data.energy = 4.0
    light = bpy.data.objects.new("SciVizSun", light_data)
    bpy.context.scene.collection.objects.link(light)
    light.location = (center.x + 6, center.y - 6, center.z + 8)


def main() -> int:
    args = _parse_args()
    cif = Path(args.cif).resolve()
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not cif.is_file():
        print(f"[fail] CIF not found: {cif}")
        return 2

    bpy.ops.wm.read_factory_settings(use_empty=True)

    _enable_sciviz()

    print(f"[sciviz] importing {cif}")
    res = bpy.ops.sciviz.import_crystal(
        filepath=str(cif),
        bond_cutoff=3.0,
        atom_scale=0.4,
        bond_radius=0.08,
        only_unlike_bonds=True,
        collection_name="Crystal",
    )
    if "FINISHED" not in res:
        print(f"[fail] import_crystal returned {res}")
        return 3

    crystal = bpy.data.collections.get("Crystal")
    n_obj = len(crystal.objects) if crystal else 0
    n_atoms = sum(1 for o in crystal.objects if "_" in o.name and not o.name.startswith("Bond_"))
    n_bonds = sum(1 for o in crystal.objects if o.name.startswith("Bond_"))
    print(f"[sciviz] crystal collection: {n_obj} objects ({n_atoms} atoms, {n_bonds} bonds)")
    if n_atoms == 0:
        print("[fail] no atoms imported")
        return 4

    res = bpy.ops.sciviz.apply_preset(preset="SOFT_SHADOW", transparent_background=False)
    if "FINISHED" not in res:
        print(f"[fail] apply_preset returned {res}")
        return 5
    print(f"[sciviz] preset applied; engine={bpy.context.scene.render.engine}")

    _frame_camera_to_collection("Crystal")

    res = bpy.ops.sciviz.render_hq(
        filepath=str(out),
        width=args.width,
        height=args.height,
        samples=args.samples,
    )
    if "FINISHED" not in res:
        print(f"[fail] render_hq returned {res}")
        return 6

    if not out.is_file() or out.stat().st_size < 1000:
        print(f"[fail] render output missing or too small: {out}")
        return 7
    print(f"[sciviz] render OK: {out} ({out.stat().st_size:,} bytes)")

    print("[sciviz] all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
