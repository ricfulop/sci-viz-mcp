#!/usr/bin/env python3
"""Trace every telescope preset through the engine; report power and RMS spot."""

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import run_scene
from telescope_designs import BUILDERS, CHROMATIC_DEFAULT, spot_stats


def check(design, params=None):
    t0 = time.time()
    params = params or {}
    builder = design[:-2] if design.endswith("_5") else design
    try:
        objs, info = BUILDERS[builder](params)
    except Exception as e:
        print(f"{design:24s} BUILD FAIL: {e}")
        return False
    scene = {"version": 5, "width": 1500, "height": 900,
             "rayModeDensity": 0.5, "objs": objs}
    if params.get("chromatic", design in CHROMATIC_DEFAULT):
        scene["simulateColors"] = True
    result = run_scene(scene)
    det = (result.get("detectors") or [{}])[0]
    power = det.get("power", 0)
    rms = None
    if det.get("irradianceMap"):
        _, rms = spot_stats(det["irradianceMap"], det["binPositions"])
    err = result.get("error")
    ok = power > 1 and not err
    extra = ""
    if "rms_spot_radius" in info and info["rms_spot_radius"] is not None:
        extra = f" tuned_rms={info['rms_spot_radius']:.2f}"
    print(f"{design:24s} {'OK ' if ok else 'BAD'} power={power:8.2f} "
          f"rms_bins={rms if rms is None else round(rms, 2)} "
          f"t={time.time() - t0:.1f}s{extra}"
          + (f"\n{'':28s}ERROR: {err}" if err else ""))
    return ok


def main():
    cases = {
        "newtonian": {},
        "prime_focus": {},
        "herschelian": {},
        "cassegrain": {},
        "ritchey_chretien": {},
        "dall_kirkham": {},
        "gregorian": {},
        "nasmyth": {},
        "schmidt_camera": {},
        "schmidt_cassegrain": {},
        "maksutov_cassegrain": {},
        "keplerian_refractor": {},
        "galilean_refractor": {},
        "singlet_refractor": {},
        "achromat_doublet": {},
        "petzval_refractor": {},
        "apo_triplet": {},
        "flatfield_petzval": {"elements": 4},
        "flatfield_petzval_5": {},
    }
    results = [check(d, p) for d, p in cases.items()]
    # Off-axis sanity: RC should beat classical Cassegrain at a field angle
    print("\nfield-angle comparison (0.75 deg):")
    for d in ["cassegrain", "ritchey_chretien"]:
        check(d, {"field_angle_deg": 0.75})
    n_bad = results.count(False)
    print(f"\n{len(results) - n_bad}/{len(results)} designs OK")
    sys.exit(1 if n_bad else 0)


if __name__ == "__main__":
    main()
