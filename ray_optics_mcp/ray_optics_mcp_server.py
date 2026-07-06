#!/usr/bin/env python3
"""
ray_optics_mcp_server.py
MCP server wrapping the Ray Optics Simulation engine (ricktu288/ray-optics)
for AI-driven 2D optical design — telescopes, spectrometers, interferometers.

The engine itself is the vendored `dist-integrations` build (vendor/rayOptics.js
+ vendor/runner.js, Apache-2.0), executed headlessly via Node.js. Scenes use the
same JSON format as the web app (https://phydemo.app/ray-optics/simulator/), so
any scene built here can be opened and hand-edited in the web app and vice versa.

Implements MCP JSON-RPC 2.0 over stdio (protocolVersion 2024-11-05).
"""

import base64
import copy
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

_THIS_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_THIS_DIR))
sys.path.insert(0, str(_THIS_DIR.parent))
from mcp_runtime import resolve_tool_name
from attribution import ATTRIBUTION_TEXT, stamp_image_file
from engine import run_scene
from telescope_designs import BUILDERS, CHROMATIC_DEFAULT

try:
    from preview.notify import notify_preview
except Exception:  # preview dashboard is optional
    def notify_preview(*args, **kwargs):
        pass

VENDOR_DIR = _THIS_DIR / "vendor"
RUNNER_JS = VENDOR_DIR / "runner.js"
KNOWLEDGE_DIR = _THIS_DIR / "knowledge"

OUTPUT_DIR = Path(os.environ.get(
    "RAY_OPTICS_OUTPUT_DIR",
    str(_THIS_DIR.parent / "output" / "ray_optics"),
))
SCENES_DIR = OUTPUT_DIR / "scenes"
RENDERS_DIR = OUTPUT_DIR / "renders"

DEFAULT_WIDTH = 1500
DEFAULT_HEIGHT = 900

# ── Scene store ──────────────────────────────────────────────────────────────
# scene_id -> {"scene": dict, "name": str, "path": str | None}

_scenes: dict = {}
_counter = 0


def _new_scene_id(name: str) -> str:
    global _counter
    _counter += 1
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "scene").lower()).strip("-") or "scene"
    return f"{slug}-{_counter}"


def _get(scene_id: str) -> dict:
    if scene_id not in _scenes:
        raise ValueError(
            f"Unknown scene_id '{scene_id}'. Active scenes: {list(_scenes.keys()) or 'none'}"
        )
    return _scenes[scene_id]


def _persist(scene_id: str) -> str:
    """Write the scene JSON to disk so it survives restarts and can be opened
    in the web app (Settings -> Show JSON editor, or File -> Open)."""
    SCENES_DIR.mkdir(parents=True, exist_ok=True)
    entry = _scenes[scene_id]
    path = entry.get("path") or str(SCENES_DIR / f"{scene_id}.json")
    entry["path"] = path
    Path(path).write_text(json.dumps(entry["scene"], indent=2))
    return path


def _obj_summary(i: int, obj: dict) -> dict:
    s = {"index": i, "type": obj.get("type")}
    for key in ("name", "p1", "p2", "p3", "x", "y", "focalLength", "refIndex", "module"):
        if key in obj:
            s[key] = obj[key]
    return s


# ── Engine invocation ────────────────────────────────────────────────────────

def _run_engine(scene: dict, timeout_s: int = 120) -> dict:
    return run_scene(scene, timeout_s=timeout_s)


def _scene_bounds(scene: dict):
    """Bounding box over all coordinates found in scene objects."""
    xs, ys = [], []

    def visit(v):
        if isinstance(v, dict):
            if "x" in v and "y" in v and isinstance(v["x"], (int, float)) and isinstance(v["y"], (int, float)):
                xs.append(v["x"])
                ys.append(v["y"])
            for vv in v.values():
                visit(vv)
        elif isinstance(v, list):
            for vv in v:
                visit(vv)

    for obj in scene.get("objs", []):
        visit(obj)
    if not xs:
        return 0, 0, DEFAULT_WIDTH, DEFAULT_HEIGHT
    return min(xs), min(ys), max(xs), max(ys)


# ── Tool handlers: scene lifecycle ───────────────────────────────────────────

def handle_new_scene(args):
    name = args.get("name", "scene")
    scene = {
        "version": 5,
        "name": name,
        "width": args.get("width", DEFAULT_WIDTH),
        "height": args.get("height", DEFAULT_HEIGHT),
        "objs": [],
    }
    for key in ("rayModeDensity", "simulateColors", "mode", "maxRayDepth"):
        if key in args:
            scene[key] = args[key]
    scene_id = _new_scene_id(name)
    _scenes[scene_id] = {"scene": scene, "name": name, "path": None}
    path = _persist(scene_id)
    return {"scene_id": scene_id, "path": path}


def handle_load_scene(args):
    if "file_path" in args:
        scene = json.loads(Path(args["file_path"]).read_text())
        name = args.get("name") or Path(args["file_path"]).stem
    elif "scene_json" in args:
        scene = args["scene_json"]
        if isinstance(scene, str):
            scene = json.loads(scene)
        name = args.get("name") or scene.get("name", "loaded")
    else:
        raise ValueError("Provide file_path or scene_json.")
    scene.setdefault("version", 5)
    scene.setdefault("objs", [])
    scene_id = _new_scene_id(name)
    _scenes[scene_id] = {"scene": scene, "name": name, "path": None}
    path = _persist(scene_id)
    return {
        "scene_id": scene_id,
        "path": path,
        "n_objects": len(scene["objs"]),
        "objects": [_obj_summary(i, o) for i, o in enumerate(scene["objs"])],
    }


def handle_save_scene(args):
    entry = _get(args["scene_id"])
    if "file_path" in args:
        entry["path"] = args["file_path"]
    path = _persist(args["scene_id"])
    return {
        "path": path,
        "hint": "Open this JSON in the web app (https://phydemo.app/ray-optics/simulator/) "
                "via File -> Open, or paste into the JSON editor, for interactive editing.",
    }


def handle_get_scene(args):
    entry = _get(args["scene_id"])
    return {"scene": entry["scene"]}


def handle_list_scenes(args):
    return {
        "scenes": [
            {"scene_id": sid, "name": e["name"], "path": e["path"],
             "n_objects": len(e["scene"].get("objs", []))}
            for sid, e in _scenes.items()
        ]
    }


def handle_list_objects(args):
    entry = _get(args["scene_id"])
    objs = entry["scene"].get("objs", [])
    return {"n_objects": len(objs), "objects": [_obj_summary(i, o) for i, o in enumerate(objs)]}


# ── Tool handlers: scene editing ─────────────────────────────────────────────

def handle_add_objects(args):
    entry = _get(args["scene_id"])
    objs = args["objects"]
    if isinstance(objs, dict):
        objs = [objs]
    start = len(entry["scene"]["objs"])
    for o in objs:
        if "type" not in o:
            raise ValueError(f"Object missing 'type': {json.dumps(o)[:200]}")
        entry["scene"]["objs"].append(o)
    _persist(args["scene_id"])
    return {"added_indices": list(range(start, start + len(objs))),
            "n_objects": len(entry["scene"]["objs"])}


def handle_update_object(args):
    entry = _get(args["scene_id"])
    objs = entry["scene"]["objs"]
    i = args["index"]
    if not 0 <= i < len(objs):
        raise ValueError(f"Index {i} out of range (scene has {len(objs)} objects).")
    if args.get("replace"):
        objs[i] = args["patch"]
    else:
        objs[i].update(args["patch"])
    _persist(args["scene_id"])
    return {"object": objs[i]}


def handle_remove_objects(args):
    entry = _get(args["scene_id"])
    objs = entry["scene"]["objs"]
    indices = sorted(set(args["indices"]), reverse=True)
    removed = []
    for i in indices:
        if not 0 <= i < len(objs):
            raise ValueError(f"Index {i} out of range (scene has {len(objs)} objects).")
        removed.append({"index": i, "type": objs[i].get("type")})
        del objs[i]
    _persist(args["scene_id"])
    return {"removed": removed, "n_objects": len(objs)}


def handle_set_scene_settings(args):
    entry = _get(args["scene_id"])
    settings = args["settings"]
    protected = {"objs", "version"}
    for k, v in settings.items():
        if k in protected:
            raise ValueError(f"Use the object tools to modify '{k}'.")
        entry["scene"][k] = v
    _persist(args["scene_id"])
    return {"scene_settings": {k: v for k, v in entry["scene"].items() if k != "objs"}}


# ── Tool handlers: simulate & render ─────────────────────────────────────────

def handle_simulate(args):
    entry = _get(args["scene_id"])
    scene = copy.deepcopy(entry["scene"])
    # Strip crop boxes: simulation-only call should not pay for rendering
    scene["objs"] = [o for o in scene["objs"] if o.get("type") != "CropBox"]
    result = _run_engine(scene)
    return {
        "detectors": result.get("detectors", []),
        "processedRayCount": result.get("processedRayCount"),
        "totalTruncation": result.get("totalTruncation"),
        "brightnessScale": result.get("brightnessScale"),
        "error": result.get("error"),
        "warning": result.get("warning"),
    }


def handle_render(args):
    entry = _get(args["scene_id"])
    scene = copy.deepcopy(entry["scene"])
    scene["objs"] = [o for o in scene["objs"] if o.get("type") != "CropBox"]

    if "region" in args:
        r = args["region"]
        x0, y0, x1, y1 = r["x0"], r["y0"], r["x1"], r["y1"]
    else:
        x0, y0, x1, y1 = _scene_bounds(scene)
        margin = args.get("margin", 60)
        x0, y0, x1, y1 = x0 - margin, y0 - margin, x1 + margin, y1 + margin

    image_width = args.get("image_width", 1200)
    scene["objs"].append({
        "type": "CropBox",
        "p1": {"x": x0, "y": y0},
        "p4": {"x": x1, "y": y1},
        "width": image_width,
    })

    result = _run_engine(scene)
    if not result.get("images"):
        raise RuntimeError(f"Engine returned no image. error={result.get('error')}")

    RENDERS_DIR.mkdir(parents=True, exist_ok=True)
    out = args.get("output_file") or str(
        RENDERS_DIR / f"{args['scene_id']}_{int(time.time())}.png"
    )
    data = result["images"][0]["dataUrl"].split(",", 1)[1]
    Path(out).write_bytes(base64.b64decode(data))
    stamp_image_file(out)

    notify_preview(out, "ray_optics_render", {"scene_id": args["scene_id"]},
                   server_name="ray_optics_mcp")
    return {
        "image_path": out,
        "region": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
        "detectors": result.get("detectors", []),
        "processedRayCount": result.get("processedRayCount"),
        "error": result.get("error"),
        "warning": result.get("warning"),
        "attribution": ATTRIBUTION_TEXT,
    }


# ── Tool handlers: telescope presets ─────────────────────────────────────────

def handle_make_telescope(args):
    design = args["design"]
    if design not in BUILDERS:
        raise ValueError(f"Unknown design '{design}'. Available: {sorted(BUILDERS)}")
    params = args.get("params", {})
    objs, info = BUILDERS[design](params)

    name = args.get("name", design)
    scene = {
        "version": 5,
        "name": name,
        "width": DEFAULT_WIDTH,
        "height": DEFAULT_HEIGHT,
        "rayModeDensity": params.get("ray_density", 0.3),
        "objs": objs,
    }
    if params.get("chromatic", design in CHROMATIC_DEFAULT):
        scene["simulateColors"] = True
    scene_id = _new_scene_id(name)
    _scenes[scene_id] = {"scene": scene, "name": name, "path": None}
    path = _persist(scene_id)
    return {
        "scene_id": scene_id,
        "path": path,
        "design_info": info,
        "attribution": ATTRIBUTION_TEXT,
        "objects": [_obj_summary(i, o) for i, o in enumerate(objs)],
        "hint": "Use ray_optics_render to see it, ray_optics_simulate for detector "
                "readings, and the object tools to modify the design.",
    }


# ── Tool handlers: reference docs ────────────────────────────────────────────

_REFERENCE_FILES = {
    "objects": "objects.md",
    "modules": "module.md",
    "integrations": "integrations.md",
    "instructions": "instructions.md",
}


def handle_reference(args):
    topic = args.get("topic", "objects")
    if topic not in _REFERENCE_FILES:
        raise ValueError(f"Unknown topic '{topic}'. Available: {list(_REFERENCE_FILES)}")
    text = (KNOWLEDGE_DIR / _REFERENCE_FILES[topic]).read_text()
    return {"topic": topic, "content": text}


# ── Tool registry ────────────────────────────────────────────────────────────

_POINT = {"type": "object",
          "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
          "required": ["x", "y"]}

TOOLS = {
    "ray_optics_new_scene": {
        "handler": handle_new_scene,
        "description": "Create a new empty 2D optical scene (ray-optics JSON format, y-axis points down). Returns a scene_id for subsequent operations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "width": {"type": "number", "description": "Viewport width (default 1500)"},
                "height": {"type": "number", "description": "Viewport height (default 900)"},
                "rayModeDensity": {"type": "number", "description": "Ray density (default 0.1)"},
                "simulateColors": {"type": "boolean", "description": "Enable chromatic simulation (wavelengths, Cauchy dispersion)"},
                "maxRayDepth": {"type": "integer"},
            },
        },
    },
    "ray_optics_load_scene": {
        "handler": handle_load_scene,
        "description": "Load a scene from a JSON file or inline JSON (same format as the web app at phydemo.app/ray-optics). Returns a scene_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to a scene JSON file"},
                "scene_json": {"description": "Inline scene JSON (object or string)"},
                "name": {"type": "string"},
            },
        },
    },
    "ray_optics_save_scene": {
        "handler": handle_save_scene,
        "description": "Save a scene to a JSON file openable in the ray-optics web app for interactive editing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scene_id": {"type": "string"},
                "file_path": {"type": "string", "description": "Target path (default: managed scenes dir)"},
            },
            "required": ["scene_id"],
        },
    },
    "ray_optics_get_scene": {
        "handler": handle_get_scene,
        "description": "Return the full JSON of a scene.",
        "inputSchema": {
            "type": "object",
            "properties": {"scene_id": {"type": "string"}},
            "required": ["scene_id"],
        },
    },
    "ray_optics_list_scenes": {
        "handler": handle_list_scenes,
        "description": "List all scenes currently held by this server.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "ray_optics_list_objects": {
        "handler": handle_list_objects,
        "description": "List the objects in a scene with their indices (for update/remove).",
        "inputSchema": {
            "type": "object",
            "properties": {"scene_id": {"type": "string"}},
            "required": ["scene_id"],
        },
    },
    "ray_optics_add_objects": {
        "handler": handle_add_objects,
        "description": "Append optical objects to a scene. Objects use the ray-optics JSON schema (see ray_optics_reference topic 'objects'): light sources (SingleRay, Beam, PointSource, AngleSource), mirrors (Mirror, ArcMirror, ParabolicMirror, ParamMirror, IdealCurvedMirror), glasses (PlaneGlass, CircleGlass, Glass, ParamGlass, GrinGlass), IdealLens, Blocker, CircleBlocker, BeamSplitter, DiffractionGrating, CustomSurface, Detector, CropBox, TextLabel, LineArrow, ModuleObj.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scene_id": {"type": "string"},
                "objects": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Array of scene objects, each with a 'type' and its geometry/parameters",
                },
            },
            "required": ["scene_id", "objects"],
        },
    },
    "ray_optics_update_object": {
        "handler": handle_update_object,
        "description": "Update the object at an index: shallow-merge a patch (default) or replace it entirely.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scene_id": {"type": "string"},
                "index": {"type": "integer"},
                "patch": {"type": "object"},
                "replace": {"type": "boolean", "description": "Replace instead of merge (default false)"},
            },
            "required": ["scene_id", "index", "patch"],
        },
    },
    "ray_optics_remove_objects": {
        "handler": handle_remove_objects,
        "description": "Remove objects at the given indices.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scene_id": {"type": "string"},
                "indices": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["scene_id", "indices"],
        },
    },
    "ray_optics_set_scene_settings": {
        "handler": handle_set_scene_settings,
        "description": "Merge top-level scene settings: rayModeDensity, simulateColors, mode ('rays'|'extended'|'images'|'observer'), maxRayDepth, width, height, showGrid, etc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scene_id": {"type": "string"},
                "settings": {"type": "object"},
            },
            "required": ["scene_id", "settings"],
        },
    },
    "ray_optics_simulate": {
        "handler": handle_simulate,
        "description": "Run the ray-tracing simulation headlessly and return detector readings (power, irradiance map if irradMap=true) and statistics. Add Detector objects to the scene to measure light.",
        "inputSchema": {
            "type": "object",
            "properties": {"scene_id": {"type": "string"}},
            "required": ["scene_id"],
        },
    },
    "ray_optics_render": {
        "handler": handle_render,
        "description": "Render the scene (rays + elements) to a PNG. Auto-frames all objects unless a region is given. Also returns detector readings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scene_id": {"type": "string"},
                "region": {
                    "type": "object",
                    "properties": {
                        "x0": {"type": "number"}, "y0": {"type": "number"},
                        "x1": {"type": "number"}, "y1": {"type": "number"},
                    },
                    "required": ["x0", "y0", "x1", "y1"],
                    "description": "Scene-coordinate crop region (default: bounding box of all objects + margin)",
                },
                "margin": {"type": "number", "description": "Auto-frame margin (default 60)"},
                "image_width": {"type": "integer", "description": "Output PNG width in px (default 1200)"},
                "output_file": {"type": "string"},
            },
            "required": ["scene_id"],
        },
    },
    "ray_optics_make_telescope": {
        "handler": handle_make_telescope,
        "description": (
            "Build a parametric telescope scene from a preset, with correct conic/glass "
            "prescriptions. Reflectors: 'newtonian' (parabola + flat fold), 'prime_focus', "
            "'herschelian' (off-axis parabola, unobstructed), 'cassegrain' (classical: "
            "parabola + exact confocal hyperbola), 'ritchey_chretien' (aplanatic hyperbola/"
            "hyperbola, coma-free), 'dall_kirkham' (ellipse + spherical secondary), "
            "'gregorian' (parabola + confocal ellipse), 'nasmyth' (Cassegrain + 45-degree "
            "tertiary to side focus). Catadioptrics (auto-tuned by ray tracing): "
            "'schmidt_camera' (aspheric corrector + spherical mirror), 'schmidt_cassegrain' "
            "(corrector + two spherical mirrors), 'maksutov_cassegrain' (achromatic meniscus "
            "+ spherical primary, Gregory spot secondary). Refractors: 'keplerian_refractor' "
            "/ 'galilean_refractor' (ideal lenses), 'singlet_refractor' (real BK7, shows "
            "chromatic aberration), 'achromat_doublet' (Fraunhofer BK7+F2), "
            "'petzval_refractor' (two achromat groups), 'apo_triplet' (ED apochromat "
            "FPL53/F2/FPL53, flint bending auto-tuned for minimum spherical aberration), "
            "'flatfield_petzval' (astrograph: two achromat groups + optional field "
            "flattener, auto-tuned for flat-plane spot at 0 deg AND the design field "
            "angle; params.elements = 4 quadruplet or 5 quintuplet). Returns scene_id + "
            "design info (focus positions, conic constants, magnification, f-ratio, RMS "
            "spot for auto-tuned designs). Scene coordinates: y down, ~1500x900 viewport."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "design": {
                    "type": "string",
                    "enum": ["newtonian", "prime_focus", "herschelian",
                             "cassegrain", "ritchey_chretien", "dall_kirkham",
                             "gregorian", "nasmyth",
                             "schmidt_camera", "schmidt_cassegrain",
                             "maksutov_cassegrain",
                             "keplerian_refractor", "galilean_refractor",
                             "singlet_refractor", "achromat_doublet",
                             "petzval_refractor", "apo_triplet",
                             "flatfield_petzval"],
                },
                "name": {"type": "string"},
                "params": {
                    "type": "object",
                    "description": (
                        "Design parameters (all optional). Common: aperture, axis_y, "
                        "source_x, ray_density, field_angle_deg (tilts the incoming beam "
                        "to show off-axis aberrations like coma), chromatic (adds RGB "
                        "wavelengths + simulateColors). "
                        "newtonian/prime_focus/schmidt_camera: focal_length; newtonian "
                        "also focus_offset. herschelian: focal_length, off_axis_offset. "
                        "Two-mirror (cassegrain/ritchey_chretien/dall_kirkham/gregorian/"
                        "nasmyth/schmidt_cassegrain): primary_focal_length, "
                        "secondary_distance (gregorian needs > primary_focal_length), "
                        "back_focal_distance; nasmyth also tertiary_offset. "
                        "maksutov_cassegrain: primary_focal_length, meniscus_to_primary, "
                        "meniscus_thickness. Ideal refractors: objective_focal_length, "
                        "eyepiece_focal_length. singlet/achromat/apo_triplet: "
                        "focal_length. petzval/flatfield_petzval: front_focal_length, "
                        "rear_focal_length, separation; flatfield_petzval also elements "
                        "(4|5), design_field_deg, flattener_distance."
                    ),
                },
            },
            "required": ["design"],
        },
    },
    "ray_optics_reference": {
        "handler": handle_reference,
        "description": "Return the official ray-optics JSON schema documentation. Topics: 'objects' (all scene object types and their JSON), 'modules' (parametric module system with variables and for-loops), 'integrations' (detector/image output format), 'instructions' (general scene-writing guidance).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string",
                          "enum": ["objects", "modules", "integrations", "instructions"]},
            },
        },
    },
}


# ── MCP protocol ─────────────────────────────────────────────────────────────

def send_response(req_id, result=None, error=None):
    response = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result if result is not None else {}
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def send_error(req_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data:
        error["data"] = data
    send_response(req_id, error=error)


def handle_initialize(params):
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "ray_optics_mcp", "version": "0.1.0"},
    }


def handle_tools_list():
    return {"tools": [
        {"name": name, "description": t["description"], "inputSchema": t["inputSchema"]}
        for name, t in TOOLS.items()
    ]}


def handle_tools_call(params):
    tool_name = resolve_tool_name(params.get("name"), TOOLS)
    arguments = params.get("arguments", {})
    if tool_name not in TOOLS:
        raise ValueError(f"Unknown tool: {tool_name}")
    result = TOOLS[tool_name]["handler"](arguments)
    return {"content": [{"type": "text", "text": json.dumps(result)}]}


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            req_id = req.get("id")
            method = req.get("method")
            params = req.get("params", {})

            if method == "initialize":
                send_response(req_id, handle_initialize(params))
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                send_response(req_id, handle_tools_list())
            elif method == "tools/call":
                send_response(req_id, handle_tools_call(params))
            else:
                send_error(req_id, -32601, f"Method not found: {method}")

        except json.JSONDecodeError as e:
            send_error(None, -32700, f"Parse error: {e}")
        except Exception as e:
            rid = req.get("id") if "req" in dir() else None
            send_error(rid, -32000, str(e), {"traceback": traceback.format_exc()})


if __name__ == "__main__":
    main()
