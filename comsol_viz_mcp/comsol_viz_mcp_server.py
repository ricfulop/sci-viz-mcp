#!/usr/bin/env python3
"""
comsol_viz_mcp_server.py
MCP server for publication-quality visualization of COMSOL field exports.

Reads HDF5/CSV field data exported by comsol_mcp (export_fields, export_kpis)
and renders them as APS/Nature-styled figures: 2D field maps, line cuts,
mesh overlays, and multi-panel comparison plots.

Implements MCP JSON-RPC 2.0 over stdio (protocolVersion 2024-11-05).
"""

import json
import sys
import os
import traceback
import hashlib
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.tri import Triangulation
from matplotlib.collections import PolyCollection

_THIS_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_THIS_DIR.parent))
from styles import get_style_dict, _APS_RCPARAMS, _NATURE_RCPARAMS

_STYLE_PRESETS = {"aps": _APS_RCPARAMS, "nature": _NATURE_RCPARAMS}

OUTPUT_DIR = Path(os.environ.get(
    "COMSOL_VIZ_OUTPUT_DIR",
    str(Path.home() / "voltivity" / "sci-viz-mcp" / "output"),
))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── State: loaded datasets ───────────────────────────────────────────────────

_datasets = {}  # handle -> {"coords": ndarray, "values": dict, "path": str, ...}


def _make_handle(path):
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

def handle_load_field(args):
    """Load COMSOL field export (HDF5 or CSV)."""
    file_path = args["file_path"]
    ext = Path(file_path).suffix.lower()
    handle = _make_handle(file_path)

    if ext in (".h5", ".hdf5"):
        import h5py
        with h5py.File(file_path, "r") as f:
            # Auto-discover coordinates and field datasets
            coords = None
            values = {}
            for key in f.keys():
                ds = f[key]
                if not hasattr(ds, "shape"):
                    continue
                name = key.lower()
                arr = np.array(ds)
                if name in ("x", "y", "z", "coordinates", "coords"):
                    coords = arr
                elif name in ("mesh", "points"):
                    coords = arr
                else:
                    values[key] = arr

            # If coords not found by name, check for common COMSOL layouts
            if coords is None and "x" in values and "y" in values:
                coords = np.column_stack([values.pop("x"), values.pop("y")])
            if coords is None:
                first_key = list(f.keys())[0]
                arr = np.array(f[first_key])
                if arr.ndim == 2 and arr.shape[1] >= 3:
                    coords = arr[:, :2]
                    for i, key in enumerate(list(f.keys())[1:]):
                        values[key] = np.array(f[key])

    elif ext in (".csv", ".txt", ".dat"):
        data = np.genfromtxt(file_path, delimiter=",", names=True, skip_header=0)
        if data.dtype.names is None:
            data = np.genfromtxt(file_path, skip_header=1)
            coords = data[:, :2]
            values = {f"field_{i}": data[:, i+2] for i in range(data.shape[1] - 2)}
        else:
            names = list(data.dtype.names)
            coords = np.column_stack([data[names[0]], data[names[1]]])
            values = {n: np.array(data[n]) for n in names[2:]}
    else:
        raise ValueError(f"Unsupported format: {ext}. Use .h5, .hdf5, .csv, .txt, or .dat")

    if coords is None:
        raise ValueError("Could not find coordinate data in file")

    _datasets[handle] = {
        "coords": coords,
        "values": values,
        "path": file_path,
        "n_points": len(coords),
    }

    return {
        "handle": handle,
        "n_points": len(coords),
        "coord_shape": list(coords.shape),
        "fields": list(values.keys()),
        "path": file_path,
    }


def handle_render_field_map(args):
    """Render a 2D field map (contour/pcolormesh) of COMSOL data."""
    handle = args["handle"]
    field_name = args["field"]

    if handle not in _datasets:
        raise ValueError(f"No dataset with handle: {handle}")

    ds = _datasets[handle]
    if field_name not in ds["values"]:
        raise ValueError(f"Field '{field_name}' not found. Available: {list(ds['values'].keys())}")

    coords = ds["coords"]
    field = ds["values"][field_name]
    output_file = args.get("output_file", str(OUTPUT_DIR / f"{handle}_{field_name}_map.png"))
    style_preset = args.get("style_preset", "aps")
    cmap = args.get("colormap", "viridis")
    title = args.get("title", field_name)
    xlabel = args.get("xlabel", "x (m)")
    ylabel = args.get("ylabel", "y (m)")
    clabel = args.get("colorbar_label", field_name)
    vmin = args.get("vmin")
    vmax = args.get("vmax")
    dpi = args.get("dpi", 300)
    figsize = args.get("figsize")

    rc = _STYLE_PRESETS.get(style_preset, _APS_RCPARAMS)
    plt.rcParams.update(rc)

    if figsize:
        fig, ax = plt.subplots(figsize=tuple(figsize))
    else:
        fig, ax = plt.subplots(figsize=(6.75, 4.0) if style_preset == "aps" else (7.08, 4.0))

    x, y = coords[:, 0], coords[:, 1]

    try:
        tri = Triangulation(x, y)
        im = ax.tripcolor(tri, field, cmap=cmap, shading="gouraud",
                          vmin=vmin, vmax=vmax)
    except Exception:
        im = ax.tricontourf(x, y, field, levels=50, cmap=cmap,
                            vmin=vmin, vmax=vmax)

    cb = fig.colorbar(im, ax=ax, label=clabel, shrink=0.85)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_aspect("equal")

    output_path = str(Path(output_file).resolve())
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)

    return {"output_file": output_path, "handle": handle, "field": field_name}


def handle_render_line_cut(args):
    """Render a 1D line cut through field data."""
    handle = args["handle"]
    field_name = args["field"]

    if handle not in _datasets:
        raise ValueError(f"No dataset with handle: {handle}")

    ds = _datasets[handle]
    if field_name not in ds["values"]:
        raise ValueError(f"Field '{field_name}' not found. Available: {list(ds['values'].keys())}")

    coords = ds["coords"]
    field = ds["values"][field_name]

    axis = args.get("axis", "x")
    cut_value = args.get("cut_value")
    tolerance = args.get("tolerance", None)
    output_file = args.get("output_file", str(OUTPUT_DIR / f"{handle}_{field_name}_linecut.png"))
    style_preset = args.get("style_preset", "aps")
    xlabel = args.get("xlabel")
    ylabel = args.get("ylabel", field_name)
    title = args.get("title")
    dpi = args.get("dpi", 300)

    rc = _STYLE_PRESETS.get(style_preset, _APS_RCPARAMS)
    plt.rcParams.update(rc)

    x, y = coords[:, 0], coords[:, 1]

    if axis == "x":
        sweep = x
        fixed = y
        default_xlabel = "x (m)"
    else:
        sweep = y
        fixed = x
        default_xlabel = "y (m)"

    if cut_value is None:
        cut_value = np.median(fixed)
    if tolerance is None:
        tolerance = (fixed.max() - fixed.min()) * 0.02

    mask = np.abs(fixed - cut_value) < tolerance
    if mask.sum() == 0:
        raise ValueError(f"No points within tolerance {tolerance} of {axis}={cut_value}")

    sort_idx = np.argsort(sweep[mask])
    plot_x = sweep[mask][sort_idx]
    plot_y = field[mask][sort_idx]

    fig, ax = plt.subplots(figsize=(6.75, 3.2) if style_preset == "aps" else (7.08, 3.0))
    ax.plot(plot_x, plot_y, "-", lw=1.2, color="#0072B2")
    ax.set_xlabel(xlabel or default_xlabel)
    ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title)

    output_path = str(Path(output_file).resolve())
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)

    return {
        "output_file": output_path,
        "n_points": int(mask.sum()),
        "cut_axis": axis,
        "cut_value": float(cut_value),
    }


def handle_render_mesh(args):
    """Render the mesh/triangulation of coordinate data."""
    handle = args["handle"]
    if handle not in _datasets:
        raise ValueError(f"No dataset with handle: {handle}")

    ds = _datasets[handle]
    coords = ds["coords"]
    output_file = args.get("output_file", str(OUTPUT_DIR / f"{handle}_mesh.png"))
    style_preset = args.get("style_preset", "aps")
    dpi = args.get("dpi", 300)
    title = args.get("title", "COMSOL Mesh")

    rc = _STYLE_PRESETS.get(style_preset, _APS_RCPARAMS)
    plt.rcParams.update(rc)

    fig, ax = plt.subplots(figsize=(5, 5))
    x, y = coords[:, 0], coords[:, 1]
    tri = Triangulation(x, y)
    ax.triplot(tri, lw=0.3, color="#999999", alpha=0.6)
    ax.plot(x, y, ".", ms=0.5, color="#0072B2", alpha=0.4)
    ax.set_aspect("equal")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_title(title)

    output_path = str(Path(output_file).resolve())
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)

    return {"output_file": output_path, "n_points": len(coords), "n_triangles": len(tri.triangles)}


def handle_list_datasets(args):
    """List all loaded field datasets."""
    result = []
    for h, ds in _datasets.items():
        result.append({
            "handle": h,
            "path": ds["path"],
            "n_points": ds["n_points"],
            "fields": list(ds["values"].keys()),
        })
    return {"datasets": result}


def handle_get_field_stats(args):
    """Get statistics for a field."""
    handle = args["handle"]
    field_name = args["field"]

    if handle not in _datasets:
        raise ValueError(f"No dataset with handle: {handle}")

    ds = _datasets[handle]
    if field_name not in ds["values"]:
        raise ValueError(f"Field '{field_name}' not found. Available: {list(ds['values'].keys())}")

    field = ds["values"][field_name]
    finite = field[np.isfinite(field)]

    return {
        "field": field_name,
        "n_points": len(field),
        "n_finite": len(finite),
        "min": float(np.min(finite)) if len(finite) > 0 else None,
        "max": float(np.max(finite)) if len(finite) > 0 else None,
        "mean": float(np.mean(finite)) if len(finite) > 0 else None,
        "std": float(np.std(finite)) if len(finite) > 0 else None,
        "median": float(np.median(finite)) if len(finite) > 0 else None,
    }


# ── Tool registry ────────────────────────────────────────────────────────────

TOOLS = {
    "comsol_viz.load_field": {
        "handler": handle_load_field,
        "description": "Load COMSOL field export (HDF5 or CSV) for visualization. Returns handle and list of available fields.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to HDF5 (.h5) or CSV field export from comsol.export_fields"},
            },
            "required": ["file_path"],
        },
    },
    "comsol_viz.render_field_map": {
        "handler": handle_render_field_map,
        "description": "Render a 2D field map (temperature, E-field, current density, etc.) with colorbar in APS or Nature style.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "field": {"type": "string", "description": "Field name to visualize"},
                "output_file": {"type": "string"},
                "style_preset": {"type": "string", "enum": ["aps", "nature"]},
                "colormap": {"type": "string", "description": "Matplotlib colormap (default: viridis)"},
                "title": {"type": "string"},
                "xlabel": {"type": "string"},
                "ylabel": {"type": "string"},
                "colorbar_label": {"type": "string"},
                "vmin": {"type": "number"},
                "vmax": {"type": "number"},
                "figsize": {"type": "array", "items": {"type": "number"}},
                "dpi": {"type": "integer"},
            },
            "required": ["handle", "field"],
        },
    },
    "comsol_viz.render_line_cut": {
        "handler": handle_render_line_cut,
        "description": "Render a 1D line cut through field data along x or y axis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "field": {"type": "string"},
                "axis": {"type": "string", "enum": ["x", "y"], "description": "Sweep axis (default: x)"},
                "cut_value": {"type": "number", "description": "Fixed coordinate for cut (default: median)"},
                "tolerance": {"type": "number", "description": "Tolerance for point selection"},
                "output_file": {"type": "string"},
                "style_preset": {"type": "string", "enum": ["aps", "nature"]},
                "xlabel": {"type": "string"},
                "ylabel": {"type": "string"},
                "title": {"type": "string"},
                "dpi": {"type": "integer"},
            },
            "required": ["handle", "field"],
        },
    },
    "comsol_viz.render_mesh": {
        "handler": handle_render_mesh,
        "description": "Render the COMSOL mesh triangulation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "output_file": {"type": "string"},
                "style_preset": {"type": "string", "enum": ["aps", "nature"]},
                "title": {"type": "string"},
                "dpi": {"type": "integer"},
            },
            "required": ["handle"],
        },
    },
    "comsol_viz.list_datasets": {
        "handler": handle_list_datasets,
        "description": "List all loaded COMSOL field datasets.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "comsol_viz.get_field_stats": {
        "handler": handle_get_field_stats,
        "description": "Get min/max/mean/std statistics for a field.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "field": {"type": "string"},
            },
            "required": ["handle", "field"],
        },
    },
}


# ── MCP protocol ─────────────────────────────────────────────────────────────

def handle_initialize(params):
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "comsol_viz_mcp", "version": "0.1.0"},
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
