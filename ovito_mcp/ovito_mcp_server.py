#!/usr/bin/env python3
"""
ovito_mcp_server.py
MCP server for atomistic visualization and analysis using OVITO Python API.

Supports headless rendering via Tachyon, pipeline-based data processing,
and modifier application for publication-quality atomistic figures.

Implements MCP JSON-RPC 2.0 over stdio (protocolVersion 2024-11-05).
"""

import json
import sys
import os
import traceback
from pathlib import Path

_THIS_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_THIS_DIR.parent))
from preview.notify import notify_preview

OUTPUT_DIR = Path(os.environ.get(
    "OVITO_MCP_OUTPUT_DIR",
    str(Path.home() / "voltivity" / "sci-viz-mcp" / "output"),
))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Lazy OVITO import ────────────────────────────────────────────────────────

_ovito_loaded = False


def _ensure_ovito():
    global _ovito_loaded
    if not _ovito_loaded:
        import ovito
        _ovito_loaded = True


# ── State: active pipelines keyed by handle ──────────────────────────────────

_pipelines = {}  # handle -> {"pipeline": Pipeline, "path": str, "scene": Scene}


def _make_handle(path):
    import hashlib
    return hashlib.sha1(path.encode()).hexdigest()[:12]


# ── MCP JSON-RPC helpers ─────────────────────────────────────────────────────

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


# ── Tool handlers ────────────────────────────────────────────────────────────

def handle_import_data(args):
    """Load atomistic data from CIF, LAMMPS, POSCAR, XYZ, GSD, etc."""
    _ensure_ovito()
    from ovito.io import import_file

    file_path = args["file_path"]
    columns = args.get("columns")

    kwargs = {}
    if columns:
        kwargs["columns"] = columns

    pipeline = import_file(file_path, **kwargs)
    data = pipeline.compute()

    handle = _make_handle(file_path)
    _pipelines[handle] = {
        "pipeline": pipeline,
        "path": file_path,
    }

    info = {
        "handle": handle,
        "num_particles": data.particles.count if data.particles else 0,
        "num_frames": pipeline.source.num_frames,
    }

    if data.cell:
        cell = data.cell
        matrix = cell.matrix.tolist() if hasattr(cell.matrix, "tolist") else list(cell.matrix)
        info["cell_matrix"] = matrix
        info["cell_pbc"] = list(cell.pbc) if hasattr(cell, "pbc") else [True, True, True]

    if data.particles:
        ptypes = data.particles.particle_types
        if ptypes is not None:
            try:
                type_names = [t.name for t in ptypes.types]
                info["particle_types"] = type_names
            except Exception:
                pass

        prop_names = list(data.particles.keys())
        info["available_properties"] = prop_names

    return info


def handle_add_modifier(args):
    """Apply an OVITO modifier to the pipeline."""
    _ensure_ovito()
    import ovito.modifiers as mods

    handle = args["handle"]
    modifier_name = args["modifier"]
    modifier_params = args.get("params", {})

    if handle not in _pipelines:
        raise ValueError(f"No pipeline with handle: {handle}")

    mod_class = getattr(mods, modifier_name, None)
    if mod_class is None:
        available = [name for name in dir(mods) if name.endswith("Modifier")]
        raise ValueError(
            f"Unknown modifier: {modifier_name}. "
            f"Available: {', '.join(available)}"
        )

    modifier = mod_class(**modifier_params)
    _pipelines[handle]["pipeline"].modifiers.append(modifier)

    return {
        "handle": handle,
        "modifier": modifier_name,
        "params": modifier_params,
        "total_modifiers": len(_pipelines[handle]["pipeline"].modifiers),
    }


def handle_set_visual_style(args):
    """Configure particle radii, colors, rendering quality.

    Uses a PythonScriptModifier to apply styles during pipeline evaluation,
    which guarantees mutable data access in OVITO 3.x.
    """
    _ensure_ovito()
    from ovito.pipeline import PythonScriptSource

    handle = args["handle"]
    if handle not in _pipelines:
        raise ValueError(f"No pipeline with handle: {handle}")

    pipeline = _pipelines[handle]["pipeline"]

    applied = []
    particle_radii = args.get("particle_radii", {})
    particle_colors = args.get("particle_colors", {})
    show_cell = args.get("show_cell")

    color_rgb = {}
    for name, hex_color in particle_colors.items():
        hc = hex_color.lstrip("#")
        color_rgb[name] = (
            int(hc[0:2], 16) / 255.0,
            int(hc[2:4], 16) / 255.0,
            int(hc[4:6], 16) / 255.0,
        )
        applied.append(f"color({name})={hex_color}")

    for name, radius in particle_radii.items():
        applied.append(f"radius({name})={radius}")

    radii_copy = dict(particle_radii)
    colors_copy = dict(color_rgb)
    show_cell_copy = show_cell

    def _apply_visual_style(frame, data):
        import numpy as np
        if data.particles is not None and data.particles.count > 0:
            ptypes_prop = data.particles.particle_types
            if ptypes_prop is not None and (colors_copy or radii_copy):
                type_name_map = {t.id: t.name for t in ptypes_prop.types}
                type_ids = np.array(ptypes_prop)

                if colors_copy:
                    color_array = np.ones((data.particles.count, 3)) * 0.5
                    for tid, tname in type_name_map.items():
                        if tname in colors_copy:
                            mask = type_ids == tid
                            color_array[mask] = colors_copy[tname]
                    data.particles_.create_property("Color", data=color_array)

                if radii_copy:
                    radii_array = np.ones(data.particles.count) * 0.3
                    for tid, tname in type_name_map.items():
                        if tname in radii_copy:
                            mask = type_ids == tid
                            radii_array[mask] = radii_copy[tname]
                    data.particles_.create_property("Radius", data=radii_array)

        if show_cell_copy is not None and data.cell is not None:
            data.cell_.vis.enabled = show_cell_copy

    # Remove any previous style modifier we added
    to_remove = [
        i for i, m in enumerate(pipeline.modifiers)
        if getattr(m, "_is_style_mod", False)
    ]
    for i in reversed(to_remove):
        del pipeline.modifiers[i]

    # Append user-defined modifier function (OVITO accepts plain functions)
    _apply_visual_style._is_style_mod = True
    pipeline.modifiers.append(_apply_visual_style)

    if show_cell is not None:
        applied.append(f"show_cell={show_cell}")

    return {"handle": handle, "applied": applied}


def handle_set_camera(args):
    """Configure camera position and type."""
    _ensure_ovito()
    from ovito.vis import Viewport

    handle = args["handle"]
    if handle not in _pipelines:
        raise ValueError(f"No pipeline with handle: {handle}")

    camera_type = args.get("type", "ORTHO")
    direction = args.get("direction", [0, 0, -1])
    fov = args.get("fov", 20.0)
    camera_pos = args.get("position")

    if "viewport" not in _pipelines[handle]:
        vp = Viewport()
        _pipelines[handle]["viewport"] = vp
    else:
        vp = _pipelines[handle]["viewport"]

    if camera_type.upper() == "ORTHO":
        vp.type = Viewport.Type.Ortho
    elif camera_type.upper() in ("PERSPECTIVE", "PERSP"):
        vp.type = Viewport.Type.Perspective

    vp.camera_dir = tuple(direction)
    vp.fov = fov

    if camera_pos:
        vp.camera_pos = tuple(camera_pos)

    return {
        "handle": handle,
        "camera_type": camera_type,
        "direction": direction,
        "fov": fov,
    }


def handle_render_image(args):
    """Render the scene to an image file."""
    _ensure_ovito()
    from ovito.vis import Viewport, TachyonRenderer

    handle = args["handle"]
    if handle not in _pipelines:
        raise ValueError(f"No pipeline with handle: {handle}")

    width = args.get("width", 1600)
    height = args.get("height", 1200)
    output_file = args.get("output_file")
    background = args.get("background", "#FFFFFF")
    antialiasing = args.get("antialiasing", True)

    if not output_file:
        output_file = str(OUTPUT_DIR / f"{handle}_render.png")

    pipeline = _pipelines[handle]["pipeline"]

    if "viewport" in _pipelines[handle]:
        vp = _pipelines[handle]["viewport"]
    else:
        vp = Viewport(type=Viewport.Type.Ortho)
        vp.camera_dir = (0, 0, -1)

    pipeline.add_to_scene()

    try:
        vp.zoom_all()

        renderer = TachyonRenderer()
        if hasattr(renderer, "antialiasing"):
            renderer.antialiasing = antialiasing
        if hasattr(renderer, "antialiasing_samples"):
            renderer.antialiasing_samples = 12 if antialiasing else 1

        output_path = str(Path(output_file).resolve())
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        vp.render_image(
            filename=output_path,
            size=(width, height),
            renderer=renderer,
        )
    finally:
        pipeline.remove_from_scene()

    notify_preview(output_path, "ovito.render_image", args, "ovito_mcp")
    return {
        "output_file": output_path,
        "width": width,
        "height": height,
        "handle": handle,
    }


def handle_render_animation(args):
    """Render frame sequence for time-resolved simulations."""
    _ensure_ovito()
    from ovito.vis import Viewport, TachyonRenderer

    handle = args["handle"]
    if handle not in _pipelines:
        raise ValueError(f"No pipeline with handle: {handle}")

    width = args.get("width", 1200)
    height = args.get("height", 900)
    output_file = args.get("output_file")
    fps = args.get("fps", 10)

    if not output_file:
        output_file = str(OUTPUT_DIR / f"{handle}_anim.gif")

    pipeline = _pipelines[handle]["pipeline"]

    if "viewport" in _pipelines[handle]:
        vp = _pipelines[handle]["viewport"]
    else:
        vp = Viewport(type=Viewport.Type.Ortho)
        vp.camera_dir = (0, 0, -1)

    pipeline.add_to_scene()

    try:
        vp.zoom_all()
        renderer = TachyonRenderer()

        output_path = str(Path(output_file).resolve())
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        vp.render_anim(
            filename=output_path,
            size=(width, height),
            renderer=renderer,
            fps=fps,
        )
    finally:
        pipeline.remove_from_scene()

    notify_preview(output_path, "ovito.render_animation", args, "ovito_mcp")
    return {
        "output_file": output_path,
        "num_frames": pipeline.source.num_frames,
        "handle": handle,
    }


def handle_compute_property(args):
    """Extract computed data as JSON-serializable values."""
    _ensure_ovito()

    handle = args["handle"]
    property_name = args["property"]
    max_values = args.get("max_values", 100)

    if handle not in _pipelines:
        raise ValueError(f"No pipeline with handle: {handle}")

    data = _pipelines[handle]["pipeline"].compute()

    if property_name in ("rdf", "RDF"):
        from ovito.modifiers import CoordinationAnalysisModifier
        has_coord = any(
            isinstance(m, CoordinationAnalysisModifier)
            for m in _pipelines[handle]["pipeline"].modifiers
        )
        if not has_coord:
            _pipelines[handle]["pipeline"].modifiers.append(
                CoordinationAnalysisModifier(cutoff=6.0, number_of_bins=200)
            )
            data = _pipelines[handle]["pipeline"].compute()

        rdf_table = data.tables.get("coordination-rdf")
        if rdf_table is not None:
            import numpy as np
            rdf_data = np.array(rdf_table.y)
            r_data = np.array(rdf_table.x)
            return {
                "property": "rdf",
                "r": r_data[:max_values].tolist(),
                "g_r": rdf_data[:max_values].tolist(),
            }

    if data.particles and property_name in data.particles.keys():
        import numpy as np
        values = np.array(data.particles[property_name])
        if values.ndim == 1:
            return {
                "property": property_name,
                "values": values[:max_values].tolist(),
                "total_count": len(values),
                "mean": float(np.mean(values)),
                "std": float(np.std(values)),
                "min": float(np.min(values)),
                "max": float(np.max(values)),
            }
        else:
            return {
                "property": property_name,
                "values": values[:max_values].tolist(),
                "shape": list(values.shape),
            }

    available = list(data.particles.keys()) if data.particles else []
    raise ValueError(
        f"Property '{property_name}' not found. "
        f"Available: {', '.join(available)}"
    )


def handle_pipeline_status(args):
    """Inspect current pipeline state."""
    _ensure_ovito()

    handle = args["handle"]
    if handle not in _pipelines:
        raise ValueError(f"No pipeline with handle: {handle}")

    pipeline = _pipelines[handle]["pipeline"]
    data = pipeline.compute()

    modifiers = []
    for mod in pipeline.modifiers:
        modifiers.append({
            "type": type(mod).__name__,
        })

    info = {
        "handle": handle,
        "path": _pipelines[handle]["path"],
        "num_frames": pipeline.source.num_frames,
        "modifiers": modifiers,
    }

    if data.particles:
        info["num_particles"] = data.particles.count
        info["properties"] = list(data.particles.keys())

    return info


def handle_list_pipelines(args):
    """List all active pipelines."""
    result = []
    for h, pdata in _pipelines.items():
        result.append({
            "handle": h,
            "path": pdata["path"],
            "num_modifiers": len(pdata["pipeline"].modifiers),
        })
    return {"pipelines": result}


# ── Tool registry ────────────────────────────────────────────────────────────

TOOLS = {
    "ovito.import_data": {
        "handler": handle_import_data,
        "description": "Load atomistic data from CIF, LAMMPS dump, POSCAR, XYZ, GSD, or other supported format.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to data file"},
                "columns": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Column mapping for text-based formats",
                },
            },
            "required": ["file_path"],
        },
    },
    "ovito.add_modifier": {
        "handler": handle_add_modifier,
        "description": "Apply an OVITO modifier to the pipeline (e.g. CoordinationAnalysisModifier, ColorCodingModifier, SliceModifier, CommonNeighborAnalysisModifier, VoronoiAnalysisModifier).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "modifier": {"type": "string", "description": "Modifier class name (e.g. 'CoordinationAnalysisModifier')"},
                "params": {"type": "object", "description": "Keyword arguments for the modifier constructor"},
            },
            "required": ["handle", "modifier"],
        },
    },
    "ovito.set_visual_style": {
        "handler": handle_set_visual_style,
        "description": "Configure particle radii, colors, and cell visibility for rendering.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "particle_radii": {"type": "object", "description": "Map of type name to radius, e.g. {\"Zr\": 0.6}"},
                "particle_colors": {"type": "object", "description": "Map of type name to hex color, e.g. {\"Zr\": \"#4a86c8\"}"},
                "show_cell": {"type": "boolean"},
            },
            "required": ["handle"],
        },
    },
    "ovito.set_camera": {
        "handler": handle_set_camera,
        "description": "Position the camera for rendering (orthographic or perspective).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "type": {"type": "string", "enum": ["ORTHO", "PERSPECTIVE"], "description": "Camera type"},
                "direction": {"type": "array", "items": {"type": "number"}, "description": "Camera viewing direction [x,y,z]"},
                "fov": {"type": "number", "description": "Field of view (ortho: box size; perspective: angle in degrees)"},
                "position": {"type": "array", "items": {"type": "number"}, "description": "Camera position [x,y,z]"},
            },
            "required": ["handle"],
        },
    },
    "ovito.render_image": {
        "handler": handle_render_image,
        "description": "Render the scene to a PNG/TIFF image using Tachyon ray-tracer (headless-compatible).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "output_file": {"type": "string"},
                "width": {"type": "integer", "description": "Image width in pixels (default 1600)"},
                "height": {"type": "integer", "description": "Image height in pixels (default 1200)"},
                "background": {"type": "string", "description": "Background hex color (default #FFFFFF)"},
                "antialiasing": {"type": "boolean"},
            },
            "required": ["handle"],
        },
    },
    "ovito.render_animation": {
        "handler": handle_render_animation,
        "description": "Render a frame sequence for time-resolved simulation data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "output_file": {"type": "string"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "fps": {"type": "integer", "description": "Frames per second (default 10)"},
            },
            "required": ["handle"],
        },
    },
    "ovito.compute_property": {
        "handler": handle_compute_property,
        "description": "Extract computed per-particle properties or analysis results (RDF, coordination, etc.) as JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "property": {"type": "string", "description": "Property name or 'rdf' for radial distribution function"},
                "max_values": {"type": "integer", "description": "Max number of values to return (default 100)"},
            },
            "required": ["handle", "property"],
        },
    },
    "ovito.pipeline_status": {
        "handler": handle_pipeline_status,
        "description": "Inspect current pipeline state: loaded data, active modifiers, computed properties.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
            },
            "required": ["handle"],
        },
    },
    "ovito.list_pipelines": {
        "handler": handle_list_pipelines,
        "description": "List all active OVITO pipelines.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
}


# ── MCP protocol ─────────────────────────────────────────────────────────────

def handle_initialize(params):
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "ovito_mcp", "version": "0.1.0"},
    }


def handle_tools_list():
    tools = []
    for name, tool in TOOLS.items():
        tools.append({
            "name": name,
            "description": tool["description"],
            "inputSchema": tool["inputSchema"],
        })
    return {"tools": tools}


def handle_tools_call(params):
    tool_name = params.get("name")
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
