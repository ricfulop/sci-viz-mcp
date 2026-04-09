#!/usr/bin/env python3
"""
blender_mcp_server.py
MCP server for Blender-based scientific 3D rendering.

Extends the ahujasid/blender-mcp architecture with science-specific tools:
crystal import via Atomic Blender, publication rendering presets, and
high-quality Cycles rendering.

Communicates with Blender via TCP socket (localhost:9876) where the
Blender addon must be running. Exposes tools via MCP JSON-RPC 2.0 over stdio.

Prerequisites:
  1. Install Blender 4.x: https://www.blender.org/download/
  2. Install blender-mcp addon in Blender:
     - pip install blender-mcp (or uvx blender-mcp)
     - In Blender: Edit > Preferences > Add-ons > Install from File
  3. Enable the BlenderMCP addon and click "Start MCP Server"
  4. Register this server in ~/.cursor/mcp.json
"""

import json
import sys
import socket
import traceback
from pathlib import Path

_THIS_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_THIS_DIR.parent))
from preview.notify import notify_preview

BLENDER_HOST = "localhost"
BLENDER_PORT = 9876
TIMEOUT = 30


# ── Blender socket communication ─────────────────────────────────────────────

def _send_to_blender(command: dict, timeout=TIMEOUT) -> dict:
    """Send a JSON command to the Blender addon socket server."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((BLENDER_HOST, BLENDER_PORT))

        message = json.dumps(command)
        sock.sendall(message.encode("utf-8"))

        chunks = []
        while True:
            try:
                chunk = sock.recv(8192)
                if not chunk:
                    break
                chunks.append(chunk)
                try:
                    json.loads(b"".join(chunks))
                    break
                except json.JSONDecodeError:
                    continue
            except socket.timeout:
                break

        sock.close()
        raw = b"".join(chunks).decode("utf-8")
        return json.loads(raw) if raw else {"status": "error", "message": "Empty response"}

    except ConnectionRefusedError:
        raise ConnectionError(
            "Cannot connect to Blender. Ensure Blender is running with the "
            "BlenderMCP addon active (Start MCP Server button clicked). "
            f"Expected at {BLENDER_HOST}:{BLENDER_PORT}"
        )
    except Exception as e:
        raise RuntimeError(f"Blender communication error: {e}")


def _execute_code(code: str) -> dict:
    """Execute arbitrary Python code inside Blender."""
    return _send_to_blender({"type": "execute_code", "params": {"code": code}})


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

def handle_ping(args):
    """Check if Blender is reachable."""
    try:
        result = _send_to_blender({"type": "get_scene_info"})
        return {"status": "connected", "scene_info": result.get("result", {})}
    except Exception as e:
        return {"status": "disconnected", "error": str(e)}


def handle_import_crystal(args):
    """Import a crystal structure CIF/XYZ into Blender as ball-and-stick model."""
    file_path = args["file_path"]
    bond_cutoff = args.get("bond_cutoff", 3.0)
    atom_scale = args.get("atom_scale", 0.4)
    bond_radius = args.get("bond_radius", 0.08)

    code = f"""
import bpy
import json
import numpy as np

# Use ASE to read structure (must be installed in Blender's Python)
try:
    import ase.io
    atoms = ase.io.read("{file_path}")
except ImportError:
    # Fallback: try to parse CIF manually with basic handling
    raise ImportError(
        "ASE not available in Blender Python. Install it: "
        "Blender Python path > pip install ase"
    )

# CPK colors
CPK = {{
    "Zr": (0.29, 0.53, 0.78, 1), "O": (0.91, 0.30, 0.24, 1),
    "Y": (0.61, 0.35, 0.71, 1), "Ti": (0.58, 0.65, 0.65, 1),
    "Si": (0.95, 0.61, 0.07, 1), "Al": (0.74, 0.76, 0.78, 1),
    "Fe": (0.83, 0.33, 0.0, 1), "Ca": (0.15, 0.68, 0.38, 1),
    "C": (0.20, 0.29, 0.37, 1), "N": (0.17, 0.24, 0.31, 1),
    "H": (0.93, 0.94, 0.95, 1),
}}
DEFAULT_COLOR = (0.47, 0.47, 0.47, 1)

# Clear existing crystal collection
coll_name = "Crystal"
if coll_name in bpy.data.collections:
    coll = bpy.data.collections[coll_name]
    for obj in list(coll.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(coll)

coll = bpy.data.collections.new(coll_name)
bpy.context.scene.collection.children.link(coll)

positions = atoms.get_positions()
symbols = atoms.get_chemical_symbols()

# Create atoms as UV spheres
atom_objects = []
for i, (pos, sym) in enumerate(zip(positions, symbols)):
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius={atom_scale},
        location=tuple(pos),
        segments=24, ring_count=16,
    )
    obj = bpy.context.active_object
    obj.name = f"{{sym}}_{{i}}"

    # Smooth shading
    for face in obj.data.polygons:
        face.use_smooth = True

    # Material
    mat_name = f"Mat_{{sym}}"
    if mat_name not in bpy.data.materials:
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            color = CPK.get(sym, DEFAULT_COLOR)
            bsdf.inputs["Base Color"].default_value = color
            bsdf.inputs["Metallic"].default_value = 0.1
            bsdf.inputs["Roughness"].default_value = 0.3
    mat = bpy.data.materials[mat_name]
    obj.data.materials.clear()
    obj.data.materials.append(mat)

    # Move to crystal collection
    for c in obj.users_collection:
        c.objects.unlink(obj)
    coll.objects.link(obj)
    atom_objects.append(obj)

# Create bonds
bond_count = 0
for i in range(len(positions)):
    for j in range(i + 1, len(positions)):
        dist = np.linalg.norm(positions[i] - positions[j])
        if dist < {bond_cutoff} and symbols[i] != symbols[j]:
            mid = (positions[i] + positions[j]) / 2
            diff = positions[j] - positions[i]
            length = np.linalg.norm(diff)
            direction = diff / length

            bpy.ops.mesh.primitive_cylinder_add(
                radius={bond_radius},
                depth=length,
                location=tuple(mid),
            )
            bond = bpy.context.active_object
            bond.name = f"Bond_{{i}}_{{j}}"

            # Orient cylinder along bond direction
            from mathutils import Vector
            up = Vector((0, 0, 1))
            bond_dir = Vector(direction)
            rot = up.rotation_difference(bond_dir)
            bond.rotation_euler = rot.to_euler()

            # Smooth + gray material
            for face in bond.data.polygons:
                face.use_smooth = True
            if "Mat_Bond" not in bpy.data.materials:
                mat = bpy.data.materials.new("Mat_Bond")
                mat.use_nodes = True
                bsdf = mat.node_tree.nodes.get("Principled BSDF")
                if bsdf:
                    bsdf.inputs["Base Color"].default_value = (0.6, 0.6, 0.6, 1)
                    bsdf.inputs["Metallic"].default_value = 0.3
                    bsdf.inputs["Roughness"].default_value = 0.5
            bond.data.materials.clear()
            bond.data.materials.append(bpy.data.materials["Mat_Bond"])

            for c in bond.users_collection:
                c.objects.unlink(bond)
            coll.objects.link(bond)
            bond_count += 1

result = json.dumps({{
    "atoms_created": len(positions),
    "bonds_created": bond_count,
    "formula": atoms.get_chemical_formula(),
    "collection": coll_name,
}})
print("RESULT:" + result)
"""
    response = _execute_code(code)
    result_text = response.get("result", "")

    if "RESULT:" in str(result_text):
        json_str = str(result_text).split("RESULT:")[-1].strip()
        try:
            return json.loads(json_str)
        except Exception:
            pass

    return {"status": "ok", "response": result_text}


def handle_set_science_preset(args):
    """Apply publication-quality rendering preset."""
    preset = args.get("preset", "white_clean")
    transparent_bg = args.get("transparent_background", False)

    presets = {
        "white_clean": {
            "bg_color": "(1, 1, 1, 1)",
            "ao": True,
            "shadow": False,
            "camera": "ORTHO",
        },
        "soft_shadow": {
            "bg_color": "(1, 1, 1, 1)",
            "ao": True,
            "shadow": True,
            "camera": "ORTHO",
        },
        "perspective_depth": {
            "bg_color": "(0.95, 0.95, 0.95, 1)",
            "ao": True,
            "shadow": True,
            "camera": "PERSP",
        },
        "dark_presentation": {
            "bg_color": "(0.05, 0.05, 0.05, 1)",
            "ao": True,
            "shadow": True,
            "camera": "PERSP",
        },
    }

    cfg = presets.get(preset, presets["white_clean"])
    transparent = "True" if transparent_bg else "False"

    code = f"""
import bpy

scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.samples = 128
scene.cycles.use_denoising = True
scene.render.film_transparent = {transparent}

# World background
world = scene.world
if world is None:
    world = bpy.data.worlds.new("World")
    scene.world = world
world.use_nodes = True
bg_node = world.node_tree.nodes.get("Background")
if bg_node:
    bg_node.inputs["Color"].default_value = {cfg['bg_color']}
    bg_node.inputs["Strength"].default_value = 1.0

# Camera type
for obj in scene.objects:
    if obj.type == 'CAMERA':
        obj.data.type = '{"ORTHO" if cfg["camera"] == "ORTHO" else "PERSP"}'
        if obj.data.type == 'ORTHO':
            obj.data.ortho_scale = 12
        break

# Color management for accurate scientific colors
scene.view_settings.view_transform = 'Standard'
scene.view_settings.look = 'None'
scene.view_settings.gamma = 1.0

print("RESULT:preset_applied")
"""
    response = _execute_code(code)
    return {"preset": preset, "transparent_background": transparent_bg, "response": str(response.get("result", ""))}


def handle_render_hq(args):
    """Render with Cycles at specified resolution."""
    width = args.get("width", 2400)
    height = args.get("height", 1800)
    samples = args.get("samples", 256)
    output_file = args.get("output_file", str(Path.home() / "voltivity" / "sci-viz-mcp" / "output" / "blender_render.png"))

    code = f"""
import bpy

scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.samples = {samples}
scene.cycles.use_denoising = True
scene.render.resolution_x = {width}
scene.render.resolution_y = {height}
scene.render.resolution_percentage = 100
scene.render.filepath = "{output_file}"
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_depth = '16'

bpy.ops.render.render(write_still=True)
print("RESULT:rendered")
"""
    response = _execute_code(code)
    notify_preview(output_file, "blender.render_hq", args, "blender_mcp")
    return {
        "output_file": output_file,
        "width": width,
        "height": height,
        "samples": samples,
    }


def handle_add_annotation_3d(args):
    """Add a 3D text label to the scene."""
    text = args["text"]
    position = args.get("position", [0, 0, 0])
    size = args.get("size", 0.3)
    color = args.get("color", "#333333")

    hex_c = color.lstrip("#")
    r = int(hex_c[0:2], 16) / 255.0
    g = int(hex_c[2:4], 16) / 255.0
    b = int(hex_c[4:6], 16) / 255.0

    code = f"""
import bpy

bpy.ops.object.text_add(location=({position[0]}, {position[1]}, {position[2]}))
obj = bpy.context.active_object
obj.data.body = "{text}"
obj.data.size = {size}
obj.data.align_x = 'CENTER'
obj.data.align_y = 'CENTER'

mat = bpy.data.materials.new("Mat_Label")
mat.use_nodes = True
bsdf = mat.node_tree.nodes.get("Principled BSDF")
if bsdf:
    bsdf.inputs["Base Color"].default_value = ({r}, {g}, {b}, 1)
obj.data.materials.clear()
obj.data.materials.append(mat)

# Move to Crystal collection if it exists
if "Crystal" in bpy.data.collections:
    for c in obj.users_collection:
        c.objects.unlink(obj)
    bpy.data.collections["Crystal"].objects.link(obj)

print("RESULT:annotation_added")
"""
    response = _execute_code(code)
    return {"text": text, "position": position}


def handle_execute_code(args):
    """Execute arbitrary Blender Python code."""
    code = args["code"]
    response = _execute_code(code)
    return {"result": response.get("result", ""), "status": response.get("status", "unknown")}


def handle_get_scene_info(args):
    """Get current Blender scene information."""
    response = _send_to_blender({"type": "get_scene_info"})
    return response.get("result", response)


# ── Tool registry ────────────────────────────────────────────────────────────

TOOLS = {
    "blender.ping": {
        "handler": handle_ping,
        "description": "Check if Blender is running and reachable via the addon socket.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "blender.import_crystal": {
        "handler": handle_import_crystal,
        "description": "Import a crystal structure (CIF/XYZ) into Blender as a ball-and-stick 3D model with CPK-colored materials.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to CIF or XYZ file"},
                "bond_cutoff": {"type": "number", "description": "Max bond length in Angstroms (default 3.0)"},
                "atom_scale": {"type": "number", "description": "Atom sphere radius (default 0.4)"},
                "bond_radius": {"type": "number", "description": "Bond cylinder radius (default 0.08)"},
            },
            "required": ["file_path"],
        },
    },
    "blender.set_science_preset": {
        "handler": handle_set_science_preset,
        "description": "Apply a publication rendering preset: white_clean, soft_shadow, perspective_depth, or dark_presentation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "preset": {
                    "type": "string",
                    "enum": ["white_clean", "soft_shadow", "perspective_depth", "dark_presentation"],
                },
                "transparent_background": {"type": "boolean"},
            },
        },
    },
    "blender.render_hq": {
        "handler": handle_render_hq,
        "description": "Render the scene with Cycles at specified resolution and sample count.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "output_file": {"type": "string"},
                "width": {"type": "integer", "description": "Image width (default 2400)"},
                "height": {"type": "integer", "description": "Image height (default 1800)"},
                "samples": {"type": "integer", "description": "Cycles samples (default 256)"},
            },
        },
    },
    "blender.add_annotation_3d": {
        "handler": handle_add_annotation_3d,
        "description": "Add a 3D text label to the scene at a specified position.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "position": {"type": "array", "items": {"type": "number"}, "description": "[x, y, z]"},
                "size": {"type": "number", "description": "Text size (default 0.3)"},
                "color": {"type": "string", "description": "Hex color (default #333333)"},
            },
            "required": ["text"],
        },
    },
    "blender.execute_code": {
        "handler": handle_execute_code,
        "description": "Execute arbitrary Python code inside Blender (full bpy access).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute in Blender"},
            },
            "required": ["code"],
        },
    },
    "blender.get_scene_info": {
        "handler": handle_get_scene_info,
        "description": "Get information about the current Blender scene (objects, materials, etc.).",
        "inputSchema": {"type": "object", "properties": {}},
    },
}


# ── MCP protocol ─────────────────────────────────────────────────────────────

def handle_initialize(params):
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "blender_mcp", "version": "0.1.0"},
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
