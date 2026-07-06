#!/usr/bin/env python3
"""End-to-end test of ray_optics_mcp_server over its stdio JSON-RPC interface."""

import json
import subprocess
import sys
from pathlib import Path

SERVER = Path(__file__).parent / "ray_optics_mcp_server.py"


def main():
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )

    rid = [0]

    def rpc(method, params=None):
        rid[0] += 1
        req = {"jsonrpc": "2.0", "id": rid[0], "method": method, "params": params or {}}
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()
        resp = json.loads(proc.stdout.readline())
        if "error" in resp:
            raise RuntimeError(f"{method}: {resp['error']['message']}\n"
                               f"{resp['error'].get('data', {}).get('traceback', '')}")
        return resp["result"]

    def call(tool, args=None):
        res = rpc("tools/call", {"name": tool, "arguments": args or {}})
        return json.loads(res["content"][0]["text"])

    rpc("initialize")
    tools = rpc("tools/list")["tools"]
    print(f"tools/list: {len(tools)} tools -> {[t['name'] for t in tools]}")

    for design, params in [
        ("newtonian", {"aperture": 200, "focal_length": 800}),
        ("cassegrain", {"aperture": 240, "primary_focal_length": 600,
                        "secondary_distance": 450, "back_focal_distance": 120}),
        ("keplerian_refractor", {"aperture": 160, "objective_focal_length": 700,
                                 "eyepiece_focal_length": 100}),
        ("ritchey_chretien", {}),
        ("dall_kirkham", {}),
        ("gregorian", {}),
        ("nasmyth", {}),
        ("herschelian", {}),
        ("schmidt_cassegrain", {}),
        ("maksutov_cassegrain", {}),
        ("achromat_doublet", {}),
        ("petzval_refractor", {}),
        ("apo_triplet", {}),
        ("flatfield_petzval", {"elements": 5}),
    ]:
        made = call("ray_optics_make_telescope", {"design": design, "params": params})
        sid = made["scene_id"]
        print(f"\n{design}: scene_id={sid}")
        print(f"  design_info: {json.dumps(made['design_info'])}")

        sim = call("ray_optics_simulate", {"scene_id": sid})
        for d in sim["detectors"]:
            print(f"  detector '{d['name']}': power={d['power']:.4f}")
        print(f"  rays={sim['processedRayCount']} error={sim['error']} "
              f"warning={sim['warning']}")
        assert sim["detectors"] and abs(sim["detectors"][0]["power"]) > 1, \
            f"{design}: no power at detector!"
        assert not sim["error"], f"{design}: engine error {sim['error']}"

        ren = call("ray_optics_render", {"scene_id": sid, "image_width": 1400})
        print(f"  render -> {ren['image_path']}")

    # Exercise the editing tools: patch the Keplerian eyepiece focal length
    scenes = call("ray_optics_list_scenes")["scenes"]
    sid = next(s["scene_id"] for s in scenes
               if s["scene_id"].startswith("keplerian"))
    objs = call("ray_optics_list_objects", {"scene_id": sid})["objects"]
    eyepiece_idx = next(o["index"] for o in objs
                        if o.get("name") == "eyepiece")
    call("ray_optics_update_object",
         {"scene_id": sid, "index": eyepiece_idx, "patch": {"focalLength": 80}})
    print(f"\nedit test: patched eyepiece focalLength on {sid} -> ok")

    ref = call("ray_optics_reference", {"topic": "objects"})
    print(f"reference: got {len(ref['content'])} chars of objects.md")

    proc.stdin.close()
    proc.wait(timeout=10)
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()
