#!/usr/bin/env python3
"""
ovito_mcp_server.py – Fully-featured MCP server for the OVITO Python API.

Exposes headless atomistic data I/O, analysis, visualization configuration,
and publication-quality rendering via Tachyon/OSPRay/ANARI ray-tracers.

Implements MCP JSON-RPC 2.0 over stdio (protocolVersion 2024-11-05).
"""

import json
import sys
import os
import textwrap
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
        import ovito  # noqa: F401
        _ovito_loaded = True


# ── State: active pipelines keyed by handle ──────────────────────────────────

_pipelines = {}  # handle -> {"pipeline": Pipeline, "path": str, ...}


def _make_handle(tag: str) -> str:
    import hashlib
    return hashlib.sha1(tag.encode()).hexdigest()[:12]


def _get_pipeline(handle: str):
    if handle not in _pipelines:
        raise ValueError(
            f"No pipeline with handle '{handle}'. "
            f"Active: {list(_pipelines.keys())}"
        )
    return _pipelines[handle]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _hex_to_rgb(hex_color: str):
    hc = hex_color.lstrip("#")
    return (int(hc[0:2], 16) / 255.0,
            int(hc[2:4], 16) / 255.0,
            int(hc[4:6], 16) / 255.0)


def _summarize_data(data, max_types=50):
    """Return a JSON-serializable summary of a DataCollection."""
    info = {}
    if data.particles:
        p = data.particles
        info["num_particles"] = p.count
        info["properties"] = list(p.keys())
        ptypes = p.particle_types
        if ptypes is not None:
            try:
                info["particle_types"] = [
                    {"id": t.id, "name": t.name}
                    for t in ptypes.types[:max_types]
                ]
            except Exception:
                pass
        if hasattr(p, "bonds") and p.bonds is not None:
            info["num_bonds"] = p.bonds.count
            info["bond_properties"] = list(p.bonds.keys())

    if data.cell:
        c = data.cell
        info["cell_matrix"] = (
            c.matrix.tolist() if hasattr(c.matrix, "tolist") else list(c.matrix)
        )
        info["cell_pbc"] = list(c.pbc) if hasattr(c, "pbc") else [True, True, True]
        info["cell_is_2d"] = getattr(c, "is2D", False)

    for obj in data.objects:
        cls = type(obj).__name__
        if cls == "SurfaceMesh":
            info["has_surface_mesh"] = True
        elif cls == "DislocationNetwork":
            info["has_dislocation_network"] = True
        elif cls == "VoxelGrid":
            info["has_voxel_grid"] = True

    if hasattr(data, "tables") and data.tables:
        info["data_tables"] = list(data.tables.keys())

    if hasattr(data, "attributes") and data.attributes:
        info["global_attributes"] = {
            k: _safe_json(v) for k, v in data.attributes.items()
        }

    return info


def _safe_json(val):
    """Coerce numpy scalars / arrays to JSON-friendly types."""
    import numpy as np
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, np.ndarray):
        return val.tolist()
    return val


def _build_renderer(args):
    """Construct a headless renderer from tool arguments."""
    _ensure_ovito()
    renderer_type = args.get("renderer", "tachyon").lower()

    if renderer_type == "ospray":
        from ovito.vis import OSPRayRenderer
        r = OSPRayRenderer()
        for attr in ("samples_per_pixel", "max_ray_recursion",
                      "direct_light_intensity", "ambient_light_intensity",
                      "denoising_enabled"):
            if attr in args:
                setattr(r, attr, args[attr])
        return r

    if renderer_type == "anari":
        try:
            from ovito.vis import AnariRenderer
        except ImportError:
            raise ValueError(
                "AnariRenderer not available. Requires NVIDIA VisRTX / CUDA GPU. "
                "Falling back to 'tachyon' or 'ospray'."
            )
        r = AnariRenderer()
        for attr in ("samples_per_pixel", "denoising_enabled",
                      "ambient_light_radiance", "direct_light_irradiance",
                      "material_type", "physically_based_metalness",
                      "physically_based_roughness",
                      "ambient_occlusion_samples", "ambient_occlusion_distance",
                      "outlines_enabled", "dof_enabled", "aperture", "focal_length"):
            if attr in args:
                setattr(r, attr, args[attr])
        return r

    # Default: Tachyon
    from ovito.vis import TachyonRenderer
    r = TachyonRenderer()
    aa = args.get("antialiasing", True)
    if hasattr(r, "antialiasing"):
        r.antialiasing = aa
    if hasattr(r, "antialiasing_samples"):
        r.antialiasing_samples = args.get("antialiasing_samples", 12 if aa else 1)
    if hasattr(r, "shadows"):
        r.shadows = args.get("shadows", True)
    if hasattr(r, "ambient_occlusion"):
        r.ambient_occlusion = args.get("ambient_occlusion", True)
    if "ambient_occlusion_samples" in args and hasattr(r, "ambient_occlusion_samples"):
        r.ambient_occlusion_samples = args["ambient_occlusion_samples"]
    return r


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

# ── I / O ─────────────────────────────────────────────────────────────────────

def handle_import_file(args):
    """Load atomistic data from any supported file format."""
    _ensure_ovito()
    from ovito.io import import_file

    file_path = args["file_path"]
    kwargs = {}
    for key in ("columns", "input_format", "sort_particles", "atom_style"):
        if key in args:
            kwargs[key] = args[key]

    pipeline = import_file(file_path, **kwargs)
    data = pipeline.compute()

    handle = _make_handle(file_path)
    _pipelines[handle] = {"pipeline": pipeline, "path": file_path}

    result = {"handle": handle}
    result.update(_summarize_data(data))
    result["num_frames"] = pipeline.source.num_frames
    return result


def handle_export_file(args):
    """Export pipeline data to a file in the specified format."""
    _ensure_ovito()
    from ovito.io import export_file

    handle = args["handle"]
    output_path = args["output_path"]
    fmt = args["format"]

    entry = _get_pipeline(handle)
    pipeline = entry["pipeline"]

    kwargs = {}
    for key in ("columns", "frame", "multiple_frames", "start_frame",
                 "end_frame", "every_nth_frame", "key", "precision"):
        if key in args:
            kwargs[key] = args[key]

    resolved = str(Path(output_path).resolve())
    Path(resolved).parent.mkdir(parents=True, exist_ok=True)
    export_file(pipeline, resolved, fmt, **kwargs)

    return {"output_path": resolved, "format": fmt, "handle": handle}


def handle_create_pipeline(args):
    """Create a pipeline from scratch (StaticSource) for procedural data."""
    _ensure_ovito()
    from ovito.pipeline import Pipeline, StaticSource
    from ovito.data import DataCollection, SimulationCell
    import numpy as np

    label = args.get("label", "procedural")
    handle = _make_handle(label)

    data = DataCollection()
    if "cell_matrix" in args:
        cell = SimulationCell()
        cell.matrix = np.array(args["cell_matrix"], dtype=float)
        if "pbc" in args:
            cell.pbc = tuple(args["pbc"])
        data.objects.append(cell)

    pipeline = Pipeline(source=StaticSource(data=data))
    _pipelines[handle] = {"pipeline": pipeline, "path": f"<procedural:{label}>"}

    return {"handle": handle, "label": label}


def handle_load_trajectory(args):
    """Load topology + trajectory file pair (e.g. GROMACS TPR+XTC, AMBER)."""
    _ensure_ovito()
    from ovito.io import import_file
    from ovito.modifiers import LoadTrajectoryModifier

    topology_file = args["topology_file"]
    trajectory_file = args["trajectory_file"]

    kwargs = {}
    if "atom_style" in args:
        kwargs["atom_style"] = args["atom_style"]
    if "input_format" in args:
        kwargs["input_format"] = args["input_format"]

    pipeline = import_file(topology_file, **kwargs)
    traj_mod = LoadTrajectoryModifier()
    traj_mod.source.load(trajectory_file)
    pipeline.modifiers.append(traj_mod)

    data = pipeline.compute()
    handle = _make_handle(topology_file + "+" + trajectory_file)
    _pipelines[handle] = {
        "pipeline": pipeline,
        "path": f"{topology_file} + {trajectory_file}",
    }

    result = {"handle": handle}
    result.update(_summarize_data(data))
    result["num_frames"] = pipeline.source.num_frames
    return result


# ── Pipeline Management ───────────────────────────────────────────────────────

def handle_list_pipelines(args):
    """List all active pipelines and their basic info."""
    result = []
    for h, entry in _pipelines.items():
        result.append({
            "handle": h,
            "path": entry["path"],
            "num_modifiers": len(entry["pipeline"].modifiers),
        })
    return {"pipelines": result}


def handle_pipeline_info(args):
    """Detailed pipeline inspection: data, modifiers, frames, properties."""
    _ensure_ovito()
    handle = args["handle"]
    entry = _get_pipeline(handle)
    pipeline = entry["pipeline"]
    frame = args.get("frame", 0)
    data = pipeline.compute(frame)

    modifiers = []
    for i, mod in enumerate(pipeline.modifiers):
        mod_info = {"index": i, "type": type(mod).__name__}
        if hasattr(mod, "enabled"):
            mod_info["enabled"] = mod.enabled
        modifiers.append(mod_info)

    info = {
        "handle": handle,
        "path": entry["path"],
        "num_frames": pipeline.source.num_frames,
        "current_frame": frame,
        "modifiers": modifiers,
    }
    info.update(_summarize_data(data))
    return info


def handle_delete_pipeline(args):
    """Remove a pipeline from memory."""
    handle = args["handle"]
    if handle not in _pipelines:
        raise ValueError(f"No pipeline with handle: {handle}")
    path = _pipelines[handle]["path"]
    del _pipelines[handle]
    return {"deleted": handle, "path": path}


def handle_compute(args):
    """Evaluate the pipeline at a specific frame and return a data summary."""
    _ensure_ovito()
    handle = args["handle"]
    frame = args.get("frame", 0)
    entry = _get_pipeline(handle)
    data = entry["pipeline"].compute(frame)

    result = {"handle": handle, "frame": frame}
    result.update(_summarize_data(data))
    return result


def handle_animation_settings(args):
    """Configure trajectory playback settings on the pipeline's FileSource."""
    _ensure_ovito()
    handle = args["handle"]
    entry = _get_pipeline(handle)
    source = entry["pipeline"].source

    applied = []
    if "playback_ratio" in args and hasattr(source, "playback_ratio"):
        source.playback_ratio = args["playback_ratio"]
        applied.append(f"playback_ratio={args['playback_ratio']}")
    if "playback_start_time" in args and hasattr(source, "playback_start_time"):
        source.playback_start_time = args["playback_start_time"]
        applied.append(f"playback_start_time={args['playback_start_time']}")
    if "static_frame" in args and hasattr(source, "static_frame"):
        val = args["static_frame"]
        source.static_frame = val if val is not None else None
        applied.append(f"static_frame={val}")

    return {
        "handle": handle,
        "applied": applied,
        "num_frames": source.num_frames,
    }


# ── Modifiers ─────────────────────────────────────────────────────────────────

_MODIFIER_CATALOG = None


def _get_modifier_catalog():
    global _MODIFIER_CATALOG
    if _MODIFIER_CATALOG is not None:
        return _MODIFIER_CATALOG
    _ensure_ovito()
    import ovito.modifiers as mods

    catalog = {}
    for name in sorted(dir(mods)):
        obj = getattr(mods, name)
        if isinstance(obj, type) and name.endswith("Modifier"):
            doc = (obj.__doc__ or "").split("\n")[0].strip()
            catalog[name] = doc
    _MODIFIER_CATALOG = catalog
    return catalog


def handle_add_modifier(args):
    """Apply an OVITO modifier to the pipeline."""
    _ensure_ovito()
    import ovito.modifiers as mods

    handle = args["handle"]
    modifier_name = args["modifier"]
    modifier_params = args.get("params", {})

    entry = _get_pipeline(handle)
    pipeline = entry["pipeline"]

    mod_class = getattr(mods, modifier_name, None)
    if mod_class is None:
        catalog = _get_modifier_catalog()
        raise ValueError(
            f"Unknown modifier: {modifier_name}. "
            f"Available: {', '.join(catalog.keys())}"
        )

    modifier = mod_class(**modifier_params)
    pipeline.modifiers.append(modifier)

    return {
        "handle": handle,
        "modifier": modifier_name,
        "params": modifier_params,
        "modifier_index": len(pipeline.modifiers) - 1,
        "total_modifiers": len(pipeline.modifiers),
    }


def handle_remove_modifier(args):
    """Remove a modifier from the pipeline by index."""
    handle = args["handle"]
    index = args["index"]
    entry = _get_pipeline(handle)
    pipeline = entry["pipeline"]

    if index < 0 or index >= len(pipeline.modifiers):
        raise ValueError(
            f"Modifier index {index} out of range [0, {len(pipeline.modifiers)-1}]"
        )

    removed_type = type(pipeline.modifiers[index]).__name__
    del pipeline.modifiers[index]

    return {
        "handle": handle,
        "removed_index": index,
        "removed_type": removed_type,
        "remaining_modifiers": len(pipeline.modifiers),
    }


def handle_modify_modifier(args):
    """Update parameters or toggle enable/disable on an existing modifier."""
    _ensure_ovito()
    handle = args["handle"]
    index = args["index"]
    entry = _get_pipeline(handle)
    pipeline = entry["pipeline"]

    if index < 0 or index >= len(pipeline.modifiers):
        raise ValueError(
            f"Modifier index {index} out of range [0, {len(pipeline.modifiers)-1}]"
        )

    mod = pipeline.modifiers[index]
    applied = []

    if "enabled" in args:
        mod.enabled = args["enabled"]
        applied.append(f"enabled={args['enabled']}")

    for key, value in args.get("params", {}).items():
        if hasattr(mod, key):
            setattr(mod, key, value)
            applied.append(f"{key}={value}")
        else:
            settable = [a for a in dir(mod)
                        if not a.startswith("_") and not callable(getattr(mod, a, None))]
            raise ValueError(
                f"Parameter '{key}' not found on {type(mod).__name__}. "
                f"Available: {', '.join(settable[:30])}"
            )

    return {
        "handle": handle,
        "modifier_index": index,
        "modifier_type": type(mod).__name__,
        "applied": applied,
    }


def handle_configure_color_gradient(args):
    """Set the color gradient on a ColorCodingModifier."""
    _ensure_ovito()
    from ovito.modifiers import ColorCodingModifier
    from ovito.vis import ColorCodingModifier as CCVis

    handle = args["handle"]
    index = args.get("modifier_index")
    gradient_name = args["gradient"]
    entry = _get_pipeline(handle)
    pipeline = entry["pipeline"]

    mod = None
    if index is not None:
        mod = pipeline.modifiers[index]
    else:
        for m in reversed(pipeline.modifiers):
            if isinstance(m, ColorCodingModifier):
                mod = m
                break
    if mod is None or not isinstance(mod, ColorCodingModifier):
        raise ValueError("No ColorCodingModifier found at specified index")

    gradient_map = {}
    for name in dir(ColorCodingModifier):
        obj = getattr(ColorCodingModifier, name, None)
        if obj is not None and hasattr(obj, '__class__') and 'Gradient' in type(obj).__name__:
            gradient_map[name] = obj

    if not gradient_map:
        for name in ("Rainbow", "Grayscale", "Hot", "Jet", "Viridis",
                      "Magma", "BlueWhiteRed", "BlueGreenRed"):
            attr = getattr(ColorCodingModifier, name, None)
            if attr is not None:
                gradient_map[name] = attr

    gn = gradient_name.strip()
    gradient_obj = gradient_map.get(gn)
    if gradient_obj is None:
        for key in gradient_map:
            if key.lower() == gn.lower():
                gradient_obj = gradient_map[key]
                gn = key
                break

    if gradient_obj is None:
        try:
            gradient_obj = getattr(ColorCodingModifier, gn)
        except AttributeError:
            raise ValueError(
                f"Unknown gradient '{gradient_name}'. "
                f"Try: Rainbow, Grayscale, Hot, Jet, Viridis, Magma, BlueWhiteRed"
            )

    mod.gradient = gradient_obj
    return {
        "handle": handle,
        "gradient": gn,
        "modifier_type": type(mod).__name__,
    }


def handle_list_available_modifiers(args):
    """List all available OVITO modifier classes with descriptions."""
    catalog = _get_modifier_catalog()
    return {"modifiers": [{"name": k, "description": v} for k, v in catalog.items()]}


def handle_run_python_script(args):
    """Execute arbitrary OVITO Python code and return its printed output."""
    _ensure_ovito()
    import ovito
    import ovito.io
    import ovito.modifiers
    import ovito.vis
    import ovito.data
    import ovito.pipeline
    import numpy as np
    from io import StringIO

    code = args["code"]
    handle = args.get("handle")

    local_ns = {
        "ovito": ovito,
        "np": np,
        "numpy": np,
        "output_dir": OUTPUT_DIR,
        "_pipelines": _pipelines,
    }

    if handle:
        entry = _get_pipeline(handle)
        local_ns["pipeline"] = entry["pipeline"]
        local_ns["data"] = entry["pipeline"].compute()

    capture = StringIO()
    old_stdout = sys.stdout
    sys.stdout = capture
    try:
        exec(code, local_ns)
    finally:
        sys.stdout = old_stdout

    result_val = local_ns.get("result")
    return {
        "stdout": capture.getvalue(),
        "result": _safe_json(result_val) if result_val is not None else None,
    }


# ── Data Inspection ───────────────────────────────────────────────────────────

def handle_inspect_data(args):
    """Comprehensive snapshot of all data in the pipeline at a given frame."""
    _ensure_ovito()
    handle = args["handle"]
    frame = args.get("frame", 0)
    entry = _get_pipeline(handle)
    data = entry["pipeline"].compute(frame)
    result = {"handle": handle, "frame": frame}
    result.update(_summarize_data(data))
    return result


def handle_get_properties(args):
    """Extract per-particle (or per-bond) property values as JSON arrays."""
    _ensure_ovito()
    import numpy as np

    handle = args["handle"]
    property_name = args["property"]
    max_values = args.get("max_values", 200)
    frame = args.get("frame", 0)
    container = args.get("container", "particles")

    entry = _get_pipeline(handle)
    data = entry["pipeline"].compute(frame)

    if property_name in ("rdf", "RDF"):
        from ovito.modifiers import CoordinationAnalysisModifier
        pipeline = entry["pipeline"]
        has_coord = any(
            isinstance(m, CoordinationAnalysisModifier)
            for m in pipeline.modifiers
        )
        if not has_coord:
            pipeline.modifiers.append(
                CoordinationAnalysisModifier(cutoff=6.0, number_of_bins=200)
            )
            data = pipeline.compute(frame)
        rdf_table = data.tables.get("coordination-rdf")
        if rdf_table is not None:
            return {
                "property": "rdf",
                "r": np.array(rdf_table.x)[:max_values].tolist(),
                "g_r": np.array(rdf_table.y)[:max_values].tolist(),
            }

    source = data.particles if container == "particles" else None
    if container == "bonds" and data.particles and data.particles.bonds:
        source = data.particles.bonds

    if source is None:
        raise ValueError(f"Container '{container}' not found in data")

    if property_name not in source.keys():
        raise ValueError(
            f"Property '{property_name}' not in {container}. "
            f"Available: {', '.join(source.keys())}"
        )

    values = np.array(source[property_name])
    result = {
        "property": property_name,
        "container": container,
        "total_count": len(values),
    }
    if values.ndim == 1:
        result["values"] = values[:max_values].tolist()
        result["mean"] = float(np.mean(values))
        result["std"] = float(np.std(values))
        result["min"] = float(np.min(values))
        result["max"] = float(np.max(values))
    else:
        result["values"] = values[:max_values].tolist()
        result["shape"] = list(values.shape)

    return result


def handle_get_attributes(args):
    """Get global attributes (scalar quantities) from the pipeline output."""
    _ensure_ovito()
    handle = args["handle"]
    frame = args.get("frame", 0)
    entry = _get_pipeline(handle)
    data = entry["pipeline"].compute(frame)

    attrs = {}
    if hasattr(data, "attributes"):
        for k, v in data.attributes.items():
            attrs[k] = _safe_json(v)

    return {"handle": handle, "frame": frame, "attributes": attrs}


def handle_get_data_table(args):
    """Retrieve the contents of a named DataTable (histogram, RDF, etc.)."""
    _ensure_ovito()
    import numpy as np

    handle = args["handle"]
    table_name = args["table"]
    frame = args.get("frame", 0)
    max_rows = args.get("max_rows", 500)

    entry = _get_pipeline(handle)
    data = entry["pipeline"].compute(frame)

    if not hasattr(data, "tables") or table_name not in data.tables:
        available = list(data.tables.keys()) if hasattr(data, "tables") else []
        raise ValueError(
            f"Table '{table_name}' not found. Available: {available}"
        )

    table = data.tables[table_name]
    result = {
        "handle": handle,
        "table": table_name,
        "title": getattr(table, "title", table_name),
    }

    if hasattr(table, "x") and table.x is not None:
        x = np.array(table.x)
        result["x"] = x[:max_rows].tolist()
        result["x_label"] = getattr(table, "x_axis_label", "x")
    if hasattr(table, "y") and table.y is not None:
        y = np.array(table.y)
        result["y"] = y[:max_rows].tolist()
        result["y_label"] = getattr(table, "y_axis_label", "y")

    if hasattr(table, "keys"):
        cols = {}
        for key in table.keys():
            arr = np.array(table[key])
            cols[key] = arr[:max_rows].tolist()
        if cols:
            result["columns"] = cols

    return result


def handle_query_mesh(args):
    """Query SurfaceMesh or DislocationNetwork data from the pipeline."""
    _ensure_ovito()
    import numpy as np

    handle = args["handle"]
    mesh_type = args.get("type", "surface")
    frame = args.get("frame", 0)
    max_items = args.get("max_items", 200)

    entry = _get_pipeline(handle)
    data = entry["pipeline"].compute(frame)

    if mesh_type == "surface":
        mesh = None
        for obj in data.objects:
            if type(obj).__name__ == "SurfaceMesh":
                mesh = obj
                break
        if mesh is None:
            raise ValueError(
                "No SurfaceMesh in pipeline. Add ConstructSurfaceModifier first."
            )
        result = {"type": "surface", "handle": handle}
        if hasattr(mesh, "get_volume"):
            result["volume"] = float(mesh.get_volume())
        if hasattr(mesh, "get_surface_area"):
            result["surface_area"] = float(mesh.get_surface_area())
        if hasattr(mesh, "vertices") and mesh.vertices is not None:
            verts = np.array(mesh.vertices.positions)
            result["num_vertices"] = len(verts)
            result["vertices_sample"] = verts[:max_items].tolist()
        if hasattr(mesh, "faces") and mesh.faces is not None:
            result["num_faces"] = mesh.faces.count
        if hasattr(mesh, "regions") and mesh.regions is not None:
            result["num_regions"] = mesh.regions.count
            if hasattr(mesh.regions, "keys"):
                result["region_properties"] = list(mesh.regions.keys())
        return result

    elif mesh_type == "dislocations":
        dxa = None
        for obj in data.objects:
            if type(obj).__name__ == "DislocationNetwork":
                dxa = obj
                break
        if dxa is None:
            raise ValueError(
                "No DislocationNetwork in pipeline. Add DislocationAnalysisModifier first."
            )
        result = {"type": "dislocations", "handle": handle}
        segments = []
        if hasattr(dxa, "segments"):
            for i, seg in enumerate(dxa.segments):
                if i >= max_items:
                    break
                seg_info = {"index": i}
                if hasattr(seg, "true_burgers_vector"):
                    seg_info["burgers_vector"] = list(seg.true_burgers_vector)
                if hasattr(seg, "length"):
                    seg_info["length"] = float(seg.length)
                if hasattr(seg, "cluster_id"):
                    seg_info["cluster_id"] = int(seg.cluster_id)
                if hasattr(seg, "points") and seg.points is not None:
                    pts = np.array(seg.points)
                    seg_info["num_points"] = len(pts)
                segments.append(seg_info)
            result["num_segments"] = len(dxa.segments)
        result["segments"] = segments

        total_length = sum(s.get("length", 0) for s in segments)
        result["total_line_length"] = total_length
        return result

    elif mesh_type == "voxel_grid":
        grid = None
        for obj in data.objects:
            if type(obj).__name__ == "VoxelGrid":
                grid = obj
                break
        if grid is None:
            raise ValueError(
                "No VoxelGrid in pipeline. Add SpatialBinningModifier first."
            )
        result = {"type": "voxel_grid", "handle": handle}
        if hasattr(grid, "shape"):
            result["shape"] = list(grid.shape)
        result["num_voxels"] = grid.count
        result["properties"] = list(grid.keys())
        for key in grid.keys():
            arr = np.array(grid[key])
            result[f"{key}_stats"] = {
                "min": float(np.min(arr)),
                "max": float(np.max(arr)),
                "mean": float(np.mean(arr)),
            }
        return result

    raise ValueError(f"Unknown mesh type '{mesh_type}'. Use: surface, dislocations, voxel_grid")


def handle_find_neighbors(args):
    """Find neighbors of specific particles using OVITO's neighbor finders."""
    _ensure_ovito()
    import numpy as np
    from ovito.data import CutoffNeighborFinder, NearestNeighborFinder

    handle = args["handle"]
    frame = args.get("frame", 0)
    particle_index = args["particle_index"]
    mode = args.get("mode", "cutoff")

    entry = _get_pipeline(handle)
    data = entry["pipeline"].compute(frame)

    if not data.particles:
        raise ValueError("No particles in pipeline")

    if particle_index < 0 or particle_index >= data.particles.count:
        raise ValueError(
            f"Particle index {particle_index} out of range [0, {data.particles.count-1}]"
        )

    neighbors = []
    if mode == "cutoff":
        cutoff = args.get("cutoff", 5.0)
        finder = CutoffNeighborFinder(cutoff, data)
        for neigh in finder.find(particle_index):
            neighbors.append({
                "index": int(neigh.index),
                "distance": float(neigh.distance),
                "delta": [float(x) for x in neigh.delta],
            })
    elif mode == "nearest":
        num_neighbors = args.get("num_neighbors", 12)
        finder = NearestNeighborFinder(num_neighbors, data)
        for neigh in finder.find(particle_index):
            neighbors.append({
                "index": int(neigh.index),
                "distance": float(neigh.distance),
                "delta": [float(x) for x in neigh.delta],
            })
    else:
        raise ValueError(f"Unknown mode '{mode}'. Use 'cutoff' or 'nearest'.")

    pos = np.array(data.particles.positions[particle_index])
    return {
        "handle": handle,
        "particle_index": particle_index,
        "particle_position": pos.tolist(),
        "mode": mode,
        "num_neighbors": len(neighbors),
        "neighbors": neighbors,
    }


def handle_manage_types(args):
    """Rename particle/bond types or set their mass, radius, and color."""
    _ensure_ovito()

    handle = args["handle"]
    container = args.get("container", "particles")
    entry = _get_pipeline(handle)
    pipeline = entry["pipeline"]

    type_updates = args["types"]

    updates_copy = list(type_updates)
    container_name = container

    def _apply_type_management(frame, data):
        if container_name == "particles" and data.particles is not None:
            ptypes_prop = data.particles_.particle_types_
        elif container_name == "bonds" and data.particles and data.particles.bonds:
            ptypes_prop = data.particles_.bonds_.bond_types_
        else:
            return
        if ptypes_prop is None:
            return

        for upd in updates_copy:
            target_id = None
            if "id" in upd:
                target_id = upd["id"]
            elif "name" in upd:
                for candidate in ptypes_prop.types:
                    if candidate.name == upd["name"]:
                        target_id = candidate.id
                        break
            if target_id is None:
                continue
            t = ptypes_prop.type_by_id_(target_id)
            if "new_name" in upd:
                t.name = upd["new_name"]
            if "mass" in upd and hasattr(t, "mass"):
                t.mass = upd["mass"]
            if "radius" in upd and hasattr(t, "radius"):
                t.radius = upd["radius"]
            if "color" in upd:
                c = upd["color"]
                if isinstance(c, str):
                    c = _hex_to_rgb(c)
                t.color = tuple(c)

    to_remove = [
        i for i, m in enumerate(pipeline.modifiers)
        if getattr(m, "_is_type_mgmt_mod", False)
    ]
    for i in reversed(to_remove):
        del pipeline.modifiers[i]

    _apply_type_management._is_type_mgmt_mod = True
    pipeline.modifiers.append(_apply_type_management)

    return {
        "handle": handle,
        "container": container,
        "num_type_updates": len(type_updates),
    }


def handle_combine_datasets(args):
    """Merge a secondary pipeline into the primary one."""
    _ensure_ovito()
    from ovito.modifiers import CombineDatasetsModifier

    handle = args["handle"]
    secondary_handle = args["secondary_handle"]

    entry = _get_pipeline(handle)
    sec_entry = _get_pipeline(secondary_handle)

    mod = CombineDatasetsModifier()
    mod.source.load(sec_entry["path"])

    entry["pipeline"].modifiers.append(mod)
    data = entry["pipeline"].compute()

    result = {"handle": handle, "secondary_handle": secondary_handle}
    result.update(_summarize_data(data))
    return result


def handle_create_particles(args):
    """Programmatically create particles (and optionally bonds) in a pipeline."""
    _ensure_ovito()
    import numpy as np
    from ovito.data import DataCollection, SimulationCell, Particles
    from ovito.pipeline import Pipeline, StaticSource

    label = args.get("label", "manual")
    positions = np.array(args["positions"], dtype=float)
    type_ids = args.get("type_ids")
    type_names = args.get("type_names", {})

    data = DataCollection()

    if "cell_matrix" in args:
        cell = SimulationCell()
        cell.matrix = np.array(args["cell_matrix"], dtype=float)
        if "pbc" in args:
            cell.pbc = tuple(args["pbc"])
        data.objects.append(cell)

    particles = Particles()
    particles.create_property("Position", data=positions)

    if type_ids is not None:
        tid_arr = np.array(type_ids, dtype=int)
        tp = particles.create_property("Particle Type", data=tid_arr)
        from ovito.data import ParticleType
        unique_ids = sorted(set(int(x) for x in tid_arr))
        for tid_val in unique_ids:
            tname = type_names.get(str(tid_val), type_names.get(tid_val, f"Type{tid_val}"))
            pt = ParticleType(id=tid_val, name=str(tname))
            tp.types.append(pt)

    data.objects.append(particles)

    if "bonds" in args:
        bond_pairs = np.array(args["bonds"], dtype=int)
        from ovito.data import Bonds as BondsObj
        bonds = BondsObj()
        bonds.create_property("Topology", data=bond_pairs)
        particles.bonds = bonds

    pipeline = Pipeline(source=StaticSource(data=data))
    handle = _make_handle(label + str(len(positions)))
    _pipelines[handle] = {"pipeline": pipeline, "path": f"<manual:{label}>"}

    computed = pipeline.compute()
    result = {"handle": handle}
    result.update(_summarize_data(computed))
    return result


def handle_measure(args):
    """Measure distance or angle between specific particles."""
    _ensure_ovito()
    import numpy as np

    handle = args["handle"]
    frame = args.get("frame", 0)
    indices = args["indices"]

    entry = _get_pipeline(handle)
    data = entry["pipeline"].compute(frame)

    if not data.particles:
        raise ValueError("No particles in pipeline")

    positions = np.array(data.particles.positions)
    for idx in indices:
        if idx < 0 or idx >= len(positions):
            raise ValueError(f"Index {idx} out of range [0, {len(positions)-1}]")

    points = positions[indices]
    result = {
        "handle": handle,
        "indices": indices,
        "positions": points.tolist(),
    }

    if len(indices) == 2:
        d = np.linalg.norm(points[1] - points[0])
        result["distance"] = float(d)
    elif len(indices) == 3:
        v1 = points[0] - points[1]
        v2 = points[2] - points[1]
        cos_angle = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-30)
        cos_angle = np.clip(cos_angle, -1, 1)
        angle_deg = float(np.degrees(np.arccos(cos_angle)))
        result["angle_degrees"] = angle_deg
        result["vertex_index"] = indices[1]
    elif len(indices) == 4:
        v1 = points[0] - points[1]
        v2 = points[2] - points[1]
        v3 = points[2] - points[3]
        n1 = np.cross(v1, v2)
        n2 = np.cross(v2, v3)
        n1_norm = np.linalg.norm(n1) + 1e-30
        n2_norm = np.linalg.norm(n2) + 1e-30
        cos_dihedral = np.dot(n1, n2) / (n1_norm * n2_norm)
        cos_dihedral = np.clip(cos_dihedral, -1, 1)
        result["dihedral_degrees"] = float(np.degrees(np.arccos(cos_dihedral)))

    return result


# ── Selection ─────────────────────────────────────────────────────────────────

def handle_select_expression(args):
    """Select particles using a Boolean expression (e.g. 'Position.X > 5')."""
    _ensure_ovito()
    from ovito.modifiers import ExpressionSelectionModifier
    import numpy as np

    handle = args["handle"]
    expression = args["expression"]
    entry = _get_pipeline(handle)
    pipeline = entry["pipeline"]

    mod = ExpressionSelectionModifier(expression=expression)
    pipeline.modifiers.append(mod)
    data = pipeline.compute()

    num_selected = 0
    if data.attributes:
        num_selected = data.attributes.get(
            "ExpressionSelection.count",
            data.attributes.get("SelectExpression.num_selected", 0)
        )
    if num_selected == 0 and data.particles and "Selection" in data.particles.keys():
        num_selected = int(np.sum(np.array(data.particles["Selection"])))

    return {
        "handle": handle,
        "expression": expression,
        "num_selected": int(num_selected),
        "num_total": data.particles.count if data.particles else 0,
    }


def handle_select_type(args):
    """Select particles of one or more specific types."""
    _ensure_ovito()
    from ovito.modifiers import SelectTypeModifier
    import numpy as np

    handle = args["handle"]
    types = args["types"]
    entry = _get_pipeline(handle)
    pipeline = entry["pipeline"]

    mod = SelectTypeModifier(types=set(types))
    pipeline.modifiers.append(mod)
    data = pipeline.compute()

    num_selected = 0
    if data.particles and "Selection" in data.particles.keys():
        num_selected = int(np.sum(np.array(data.particles["Selection"])))

    return {
        "handle": handle,
        "types": types,
        "num_selected": int(num_selected),
        "num_total": data.particles.count if data.particles else 0,
    }


# ── Visualization ─────────────────────────────────────────────────────────────

def handle_set_visual_style(args):
    """Configure particle radii, colors, cell visibility via modifier function."""
    _ensure_ovito()

    handle = args["handle"]
    entry = _get_pipeline(handle)
    pipeline = entry["pipeline"]

    applied = []
    particle_radii = args.get("particle_radii", {})
    particle_colors = args.get("particle_colors", {})
    show_cell = args.get("show_cell")
    cell_line_width = args.get("cell_line_width")
    cell_color = args.get("cell_color")

    color_rgb = {}
    for name, hex_color in particle_colors.items():
        color_rgb[name] = _hex_to_rgb(hex_color)
        applied.append(f"color({name})={hex_color}")
    for name, radius in particle_radii.items():
        applied.append(f"radius({name})={radius}")

    radii_copy = dict(particle_radii)
    colors_copy = dict(color_rgb)
    show_cell_val = show_cell
    cell_lw = cell_line_width
    cell_clr = _hex_to_rgb(cell_color) if cell_color else None

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
                            color_array[type_ids == tid] = colors_copy[tname]
                    data.particles_.create_property("Color", data=color_array)
                if radii_copy:
                    radii_array = np.ones(data.particles.count) * 0.3
                    for tid, tname in type_name_map.items():
                        if tname in radii_copy:
                            radii_array[type_ids == tid] = radii_copy[tname]
                    data.particles_.create_property("Radius", data=radii_array)
        if show_cell_val is not None and data.cell is not None:
            data.cell_.vis.enabled = show_cell_val
        if cell_lw is not None and data.cell is not None:
            data.cell_.vis.line_width = cell_lw
        if cell_clr is not None and data.cell is not None:
            data.cell_.vis.rendering_color = cell_clr

    to_remove = [
        i for i, m in enumerate(pipeline.modifiers)
        if getattr(m, "_is_style_mod", False)
    ]
    for i in reversed(to_remove):
        del pipeline.modifiers[i]

    _apply_visual_style._is_style_mod = True
    pipeline.modifiers.append(_apply_visual_style)

    if show_cell is not None:
        applied.append(f"show_cell={show_cell}")
    if cell_line_width is not None:
        applied.append(f"cell_line_width={cell_line_width}")
    if cell_color is not None:
        applied.append(f"cell_color={cell_color}")

    return {"handle": handle, "applied": applied}


def handle_set_camera(args):
    """Configure camera position, direction, and field of view."""
    _ensure_ovito()
    from ovito.vis import Viewport

    handle = args["handle"]
    entry = _get_pipeline(handle)

    camera_type = args.get("type", "ORTHO")
    direction = args.get("direction")
    fov = args.get("fov")
    camera_pos = args.get("position")
    camera_up = args.get("up")
    zoom_all = args.get("zoom_all", False)

    if "viewport" not in entry:
        vp = Viewport()
        entry["viewport"] = vp
    else:
        vp = entry["viewport"]

    if camera_type.upper() == "ORTHO":
        vp.type = Viewport.Type.Ortho
    elif camera_type.upper() in ("PERSPECTIVE", "PERSP"):
        vp.type = Viewport.Type.Perspective

    if direction is not None:
        vp.camera_dir = tuple(direction)
    if fov is not None:
        vp.fov = fov
    if camera_pos is not None:
        vp.camera_pos = tuple(camera_pos)
    if camera_up is not None and hasattr(vp, "camera_up"):
        vp.camera_up = tuple(camera_up)

    if zoom_all:
        pipeline = entry["pipeline"]
        pipeline.add_to_scene()
        try:
            vp.zoom_all()
        finally:
            pipeline.remove_from_scene()

    return {
        "handle": handle,
        "camera_type": camera_type,
        "direction": list(vp.camera_dir),
        "fov": vp.fov,
        "position": list(vp.camera_pos),
    }


def handle_configure_vis_element(args):
    """Configure visual element properties on data objects."""
    _ensure_ovito()

    handle = args["handle"]
    element = args["element"]
    properties = args.get("properties", {})
    entry = _get_pipeline(handle)
    pipeline = entry["pipeline"]
    data = pipeline.compute()

    vis_obj = None
    element_lower = element.lower()

    if element_lower == "particles" and data.particles:
        vis_obj = data.particles.vis
    elif element_lower == "bonds" and data.particles and hasattr(data.particles, "bonds") and data.particles.bonds:
        vis_obj = data.particles.bonds.vis
    elif element_lower == "cell" and data.cell:
        vis_obj = data.cell.vis
    else:
        type_map = {
            "surface": "SurfaceMesh",
            "dislocations": "DislocationNetwork",
            "vectors": "Vectors",
            "lines": "Lines",
            "voxel_grid": "VoxelGrid",
            "triangle_mesh": "TriangleMesh",
        }
        target_cls = type_map.get(element_lower)
        if target_cls:
            for obj in data.objects:
                if type(obj).__name__ == target_cls:
                    vis_obj = obj.vis
                    break

    if vis_obj is None:
        raise ValueError(
            f"Visual element '{element}' not found in pipeline data. "
            f"Available: particles, bonds, cell, surface, dislocations, "
            f"vectors, lines, voxel_grid, triangle_mesh"
        )

    applied = []
    for key, value in properties.items():
        if hasattr(vis_obj, key):
            if "color" in key.lower() and isinstance(value, str) and value.startswith("#"):
                value = _hex_to_rgb(value)
            setattr(vis_obj, key, value)
            applied.append(f"{key}={value}")
        else:
            available = [a for a in dir(vis_obj) if not a.startswith("_")]
            raise ValueError(
                f"Property '{key}' not found on {type(vis_obj).__name__}. "
                f"Available: {', '.join(available[:30])}"
            )

    return {"handle": handle, "element": element, "applied": applied}


def handle_add_overlay(args):
    """Add a viewport overlay (color legend, text label, coordinate tripod, python)."""
    _ensure_ovito()

    handle = args["handle"]
    overlay_type = args["overlay_type"]
    properties = args.get("properties", {})
    entry = _get_pipeline(handle)

    if "viewport" not in entry:
        from ovito.vis import Viewport
        entry["viewport"] = Viewport()
    vp = entry["viewport"]

    if overlay_type == "color_legend":
        from ovito.vis import ColorLegendOverlay
        from ovito.modifiers import ColorCodingModifier

        modifier = None
        if "modifier_index" in properties:
            idx = properties.pop("modifier_index")
            modifier = entry["pipeline"].modifiers[idx]
        else:
            for mod in reversed(entry["pipeline"].modifiers):
                if isinstance(mod, ColorCodingModifier):
                    modifier = mod
                    break
        if modifier is None:
            raise ValueError(
                "ColorLegendOverlay requires a ColorCodingModifier. "
                "Add one first or specify modifier_index."
            )
        overlay = ColorLegendOverlay(modifier=modifier)

    elif overlay_type == "text_label":
        from ovito.vis import TextLabelOverlay
        overlay = TextLabelOverlay()

    elif overlay_type == "coordinate_tripod":
        from ovito.vis import CoordinateTripodOverlay
        overlay = CoordinateTripodOverlay()

    elif overlay_type == "python_overlay":
        from ovito.vis import PythonViewportOverlay
        overlay = PythonViewportOverlay()
        code = properties.pop("code", None)
        if code:
            overlay.script = code

    else:
        raise ValueError(
            f"Unknown overlay type: {overlay_type}. "
            f"Available: color_legend, text_label, coordinate_tripod, python_overlay"
        )

    for key, value in properties.items():
        if hasattr(overlay, key):
            setattr(overlay, key, value)

    vp.overlays.append(overlay)
    return {
        "handle": handle,
        "overlay_type": overlay_type,
        "total_overlays": len(vp.overlays),
    }


# ── Rendering ─────────────────────────────────────────────────────────────────

def handle_render_image(args):
    """Render the scene to an image file."""
    _ensure_ovito()
    from ovito.vis import Viewport

    handle = args["handle"]
    entry = _get_pipeline(handle)
    pipeline = entry["pipeline"]

    width = args.get("width", 1600)
    height = args.get("height", 1200)
    output_file = args.get("output_file")
    background = args.get("background", "#FFFFFF")
    transparent = args.get("transparent_background", False)
    frame = args.get("frame")

    if not output_file:
        output_file = str(OUTPUT_DIR / f"{handle}_render.png")

    if "viewport" in entry:
        vp = entry["viewport"]
    else:
        vp = Viewport(type=Viewport.Type.Ortho)
        vp.camera_dir = (0, 0, -1)
        entry["viewport"] = vp

    pipeline.add_to_scene()
    try:
        vp.zoom_all()
        renderer = _build_renderer(args)

        output_path = str(Path(output_file).resolve())
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        render_kwargs = {
            "filename": output_path,
            "size": (width, height),
            "renderer": renderer,
        }
        if frame is not None:
            render_kwargs["frame"] = frame
        if transparent:
            render_kwargs["alpha"] = True
        else:
            render_kwargs["background"] = _hex_to_rgb(background)

        vp.render_image(**render_kwargs)
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
    """Render an animation from a trajectory."""
    _ensure_ovito()
    from ovito.vis import Viewport

    handle = args["handle"]
    entry = _get_pipeline(handle)
    pipeline = entry["pipeline"]

    width = args.get("width", 1200)
    height = args.get("height", 900)
    output_file = args.get("output_file")
    fps = args.get("fps", 10)

    if not output_file:
        output_file = str(OUTPUT_DIR / f"{handle}_anim.gif")

    if "viewport" in entry:
        vp = entry["viewport"]
    else:
        vp = Viewport(type=Viewport.Type.Ortho)
        vp.camera_dir = (0, 0, -1)
        entry["viewport"] = vp

    pipeline.add_to_scene()
    try:
        vp.zoom_all()
        renderer = _build_renderer(args)

        output_path = str(Path(output_file).resolve())
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        render_kwargs = {
            "filename": output_path,
            "size": (width, height),
            "renderer": renderer,
            "fps": fps,
        }
        for key, rkey in [("every_nth_frame", "every_nth"),
                           ("start_frame", "start"),
                           ("end_frame", "end")]:
            if key in args:
                render_kwargs[rkey] = args[key]

        vp.render_anim(**render_kwargs)
    finally:
        pipeline.remove_from_scene()

    notify_preview(output_path, "ovito.render_animation", args, "ovito_mcp")
    return {
        "output_file": output_path,
        "num_frames": pipeline.source.num_frames,
        "handle": handle,
    }


def handle_render_multi_pipeline(args):
    """Render multiple pipelines together in a single scene."""
    _ensure_ovito()
    from ovito.vis import Viewport

    handles = args["handles"]
    width = args.get("width", 1600)
    height = args.get("height", 1200)
    output_file = args.get("output_file")
    background = args.get("background", "#FFFFFF")
    transparent = args.get("transparent_background", False)
    frame = args.get("frame")

    if not output_file:
        output_file = str(OUTPUT_DIR / "multi_pipeline_render.png")

    entries = [_get_pipeline(h) for h in handles]

    vp = None
    for entry in entries:
        if "viewport" in entry:
            vp = entry["viewport"]
            break
    if vp is None:
        vp = Viewport(type=Viewport.Type.Ortho)
        vp.camera_dir = (0, 0, -1)

    for entry in entries:
        entry["pipeline"].add_to_scene()

    try:
        vp.zoom_all()
        renderer = _build_renderer(args)

        output_path = str(Path(output_file).resolve())
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        render_kwargs = {
            "filename": output_path,
            "size": (width, height),
            "renderer": renderer,
        }
        if frame is not None:
            render_kwargs["frame"] = frame
        if transparent:
            render_kwargs["alpha"] = True
        else:
            render_kwargs["background"] = _hex_to_rgb(background)

        vp.render_image(**render_kwargs)
    finally:
        for entry in entries:
            entry["pipeline"].remove_from_scene()

    notify_preview(output_path, "ovito.render_multi_pipeline", args, "ovito_mcp")
    return {
        "output_file": output_path,
        "width": width,
        "height": height,
        "handles": handles,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS = {
    # ── I/O ───────────────────────────────────────────────────────────────
    "ovito.import_file": {
        "handler": handle_import_file,
        "description": (
            "Import atomistic data from CIF, LAMMPS dump/data, POSCAR, XYZ, GSD, "
            "PDB, GRO, NetCDF, DCD, CFG, or any other OVITO-supported format. "
            "Returns a pipeline handle plus data summary."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path/URL to data file. '*' for frame sequences."},
                "columns": {"type": "array", "items": {"type": "string"}, "description": "Column mapping for simple XYZ."},
                "input_format": {"type": "string", "description": "Explicit format: cif, lammps/dump, vasp, xyz, pdb, gro, etc."},
                "sort_particles": {"type": "boolean"},
                "atom_style": {"type": "string", "description": "LAMMPS atom style."},
            },
            "required": ["file_path"],
        },
    },
    "ovito.export_file": {
        "handler": handle_export_file,
        "description": (
            "Export pipeline data to file. Formats: lammps/dump, lammps/data, xyz, vasp, "
            "gsd/hoomd, netcdf/amber, vtk/trimesh, gltf, txt/attr, txt/table, fhi-aims, imd, ase/traj."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "output_path": {"type": "string"},
                "format": {"type": "string"},
                "columns": {"type": "array", "items": {"type": "string"}},
                "frame": {"type": "integer"},
                "multiple_frames": {"type": "boolean"},
                "start_frame": {"type": "integer"},
                "end_frame": {"type": "integer"},
                "every_nth_frame": {"type": "integer"},
                "key": {"type": "string"},
                "precision": {"type": "integer"},
            },
            "required": ["handle", "output_path", "format"],
        },
    },
    "ovito.create_pipeline": {
        "handler": handle_create_pipeline,
        "description": "Create an empty pipeline (StaticSource) for procedural data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "cell_matrix": {"type": "array"},
                "pbc": {"type": "array", "items": {"type": "boolean"}},
            },
        },
    },
    "ovito.load_trajectory": {
        "handler": handle_load_trajectory,
        "description": (
            "Load a topology+trajectory file pair (GROMACS TPR+XTC, AMBER prmtop+nc, "
            "LAMMPS data+dump). The topology provides bonds/types, the trajectory provides frames."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topology_file": {"type": "string", "description": "Path to topology file (e.g. .data, .pdb, .gro)."},
                "trajectory_file": {"type": "string", "description": "Path to trajectory file (e.g. .dump, .xtc, .dcd, .nc)."},
                "atom_style": {"type": "string"},
                "input_format": {"type": "string"},
            },
            "required": ["topology_file", "trajectory_file"],
        },
    },

    # ── Pipeline Management ───────────────────────────────────────────────
    "ovito.list_pipelines": {
        "handler": handle_list_pipelines,
        "description": "List all active OVITO pipelines with handles and paths.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "ovito.pipeline_info": {
        "handler": handle_pipeline_info,
        "description": "Detailed pipeline inspection: data, modifiers, frames, all properties.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "frame": {"type": "integer", "description": "Frame to inspect (default 0)."},
            },
            "required": ["handle"],
        },
    },
    "ovito.delete_pipeline": {
        "handler": handle_delete_pipeline,
        "description": "Remove a pipeline from memory.",
        "inputSchema": {
            "type": "object",
            "properties": {"handle": {"type": "string"}},
            "required": ["handle"],
        },
    },
    "ovito.compute": {
        "handler": handle_compute,
        "description": "Evaluate the pipeline at a specific frame and return a data summary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "frame": {"type": "integer"},
            },
            "required": ["handle"],
        },
    },
    "ovito.animation_settings": {
        "handler": handle_animation_settings,
        "description": (
            "Configure trajectory playback: playback_ratio ('1:1', '1:3', '2:1'), "
            "playback_start_time, and static_frame (lock to a single frame)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "playback_ratio": {"type": "string", "description": "Ratio string like '1:3' or '2:1'."},
                "playback_start_time": {"type": "integer"},
                "static_frame": {"type": "integer", "description": "Lock to frame index, or null to unlock."},
            },
            "required": ["handle"],
        },
    },

    # ── Modifiers ─────────────────────────────────────────────────────────
    "ovito.add_modifier": {
        "handler": handle_add_modifier,
        "description": (
            "Append an OVITO modifier to the pipeline. Use list_available_modifiers for full catalog. "
            "Common: CommonNeighborAnalysisModifier, CoordinationAnalysisModifier, VoronoiAnalysisModifier, "
            "DislocationAnalysisModifier, ColorCodingModifier, SliceModifier, ReplicateModifier, "
            "CreateBondsModifier, ConstructSurfaceModifier, AtomicStrainModifier, HistogramModifier, "
            "WignerSeitzAnalysisModifier, CentroSymmetryModifier, PolyhedralTemplateMatchingModifier."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "modifier": {"type": "string", "description": "Modifier class name."},
                "params": {"type": "object", "description": "Constructor kwargs (e.g. {\"cutoff\": 3.5})."},
            },
            "required": ["handle", "modifier"],
        },
    },
    "ovito.remove_modifier": {
        "handler": handle_remove_modifier,
        "description": "Remove a modifier from the pipeline by 0-based index.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "index": {"type": "integer"},
            },
            "required": ["handle", "index"],
        },
    },
    "ovito.modify_modifier": {
        "handler": handle_modify_modifier,
        "description": (
            "Update parameters or toggle enable/disable on an existing modifier without removing it. "
            "Use pipeline_info to see modifier indices and types."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "index": {"type": "integer", "description": "0-based modifier index."},
                "enabled": {"type": "boolean", "description": "Enable/disable the modifier."},
                "params": {"type": "object", "description": "Parameters to update (e.g. {\"cutoff\": 4.0})."},
            },
            "required": ["handle", "index"],
        },
    },
    "ovito.configure_color_gradient": {
        "handler": handle_configure_color_gradient,
        "description": (
            "Set the color gradient on a ColorCodingModifier. "
            "Gradients: Rainbow, Grayscale, Hot, Jet, Viridis, Magma, BlueWhiteRed, BlueGreenRed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "gradient": {"type": "string", "description": "Gradient name (e.g. 'Viridis', 'Hot', 'Rainbow')."},
                "modifier_index": {"type": "integer", "description": "Index of the ColorCodingModifier (auto-detected if omitted)."},
            },
            "required": ["handle", "gradient"],
        },
    },
    "ovito.list_available_modifiers": {
        "handler": handle_list_available_modifiers,
        "description": "List all OVITO modifier classes available for add_modifier.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "ovito.run_python_script": {
        "handler": handle_run_python_script,
        "description": (
            "Execute arbitrary OVITO Python code. Access: pipeline, data, ovito, numpy (np), output_dir. "
            "Set 'result' variable to return data."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "code": {"type": "string"},
            },
            "required": ["code"],
        },
    },

    # ── Data Inspection ───────────────────────────────────────────────────
    "ovito.inspect_data": {
        "handler": handle_inspect_data,
        "description": "Comprehensive snapshot: particles, types, properties, bonds, cell, tables, attributes, meshes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "frame": {"type": "integer"},
            },
            "required": ["handle"],
        },
    },
    "ovito.get_properties": {
        "handler": handle_get_properties,
        "description": "Extract per-particle or per-bond property values as JSON arrays with statistics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "property": {"type": "string"},
                "container": {"type": "string", "enum": ["particles", "bonds"]},
                "max_values": {"type": "integer"},
                "frame": {"type": "integer"},
            },
            "required": ["handle", "property"],
        },
    },
    "ovito.get_attributes": {
        "handler": handle_get_attributes,
        "description": "Get all global attributes (scalar quantities) from the pipeline output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "frame": {"type": "integer"},
            },
            "required": ["handle"],
        },
    },
    "ovito.get_data_table": {
        "handler": handle_get_data_table,
        "description": "Retrieve a named DataTable (histogram, RDF, etc.) as x/y arrays.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "table": {"type": "string"},
                "max_rows": {"type": "integer"},
                "frame": {"type": "integer"},
            },
            "required": ["handle", "table"],
        },
    },
    "ovito.query_mesh": {
        "handler": handle_query_mesh,
        "description": (
            "Query SurfaceMesh (volume, area, vertices, faces), DislocationNetwork "
            "(segments, Burgers vectors, line lengths), or VoxelGrid (shape, stats)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "type": {"type": "string", "enum": ["surface", "dislocations", "voxel_grid"]},
                "frame": {"type": "integer"},
                "max_items": {"type": "integer", "description": "Max segments/vertices to return (default 200)."},
            },
            "required": ["handle"],
        },
    },
    "ovito.find_neighbors": {
        "handler": handle_find_neighbors,
        "description": (
            "Find neighbors of a particle. Modes: 'cutoff' (all within distance), "
            "'nearest' (N nearest). Returns indices, distances, delta vectors."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "particle_index": {"type": "integer", "description": "0-based index of the central particle."},
                "mode": {"type": "string", "enum": ["cutoff", "nearest"]},
                "cutoff": {"type": "number", "description": "Cutoff distance (for mode='cutoff', default 5.0)."},
                "num_neighbors": {"type": "integer", "description": "Number of neighbors (for mode='nearest', default 12)."},
                "frame": {"type": "integer"},
            },
            "required": ["handle", "particle_index"],
        },
    },
    "ovito.manage_types": {
        "handler": handle_manage_types,
        "description": (
            "Rename particle/bond types or set their mass, radius, and color. "
            "Identify types by 'id' or 'name'. Set 'new_name', 'mass', 'radius', 'color'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "container": {"type": "string", "enum": ["particles", "bonds"], "description": "Default: particles."},
                "types": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "name": {"type": "string"},
                            "new_name": {"type": "string"},
                            "mass": {"type": "number"},
                            "radius": {"type": "number"},
                            "color": {"type": "string", "description": "Hex color string."},
                        },
                    },
                    "description": "List of type updates.",
                },
            },
            "required": ["handle", "types"],
        },
    },
    "ovito.combine_datasets": {
        "handler": handle_combine_datasets,
        "description": (
            "Merge a secondary pipeline into the primary one using CombineDatasetsModifier. "
            "Both pipelines must already be loaded from files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string", "description": "Primary pipeline handle."},
                "secondary_handle": {"type": "string", "description": "Pipeline to merge in."},
            },
            "required": ["handle", "secondary_handle"],
        },
    },
    "ovito.create_particles": {
        "handler": handle_create_particles,
        "description": (
            "Create particles programmatically from position arrays. "
            "Optionally add types, bonds, and a simulation cell."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "positions": {"type": "array", "description": "Nx3 array of [x,y,z] positions."},
                "type_ids": {"type": "array", "items": {"type": "integer"}, "description": "Per-particle type IDs."},
                "type_names": {"type": "object", "description": "Map type ID to name: {\"1\": \"Cu\"}."},
                "bonds": {"type": "array", "description": "Mx2 array of [i,j] bond pairs."},
                "cell_matrix": {"type": "array"},
                "pbc": {"type": "array", "items": {"type": "boolean"}},
            },
            "required": ["positions"],
        },
    },
    "ovito.measure": {
        "handler": handle_measure,
        "description": (
            "Measure distance (2 indices), angle (3 indices, vertex is middle), "
            "or dihedral angle (4 indices) between particles."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "indices": {"type": "array", "items": {"type": "integer"}, "description": "2, 3, or 4 particle indices."},
                "frame": {"type": "integer"},
            },
            "required": ["handle", "indices"],
        },
    },

    # ── Selection ─────────────────────────────────────────────────────────
    "ovito.select_expression": {
        "handler": handle_select_expression,
        "description": "Select particles using a Boolean expression (e.g. 'Position.X > 5.0').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "expression": {"type": "string"},
            },
            "required": ["handle", "expression"],
        },
    },
    "ovito.select_type": {
        "handler": handle_select_type,
        "description": "Select particles of specific type(s) by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "types": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["handle", "types"],
        },
    },

    # ── Visualization ─────────────────────────────────────────────────────
    "ovito.set_visual_style": {
        "handler": handle_set_visual_style,
        "description": "Configure particle radii, colors, and cell appearance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "particle_radii": {"type": "object"},
                "particle_colors": {"type": "object"},
                "show_cell": {"type": "boolean"},
                "cell_line_width": {"type": "number"},
                "cell_color": {"type": "string"},
            },
            "required": ["handle"],
        },
    },
    "ovito.set_camera": {
        "handler": handle_set_camera,
        "description": "Position camera (ortho/perspective). Use zoom_all=true to auto-fit.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "type": {"type": "string", "enum": ["ORTHO", "PERSPECTIVE"]},
                "direction": {"type": "array", "items": {"type": "number"}},
                "fov": {"type": "number"},
                "position": {"type": "array", "items": {"type": "number"}},
                "up": {"type": "array", "items": {"type": "number"}},
                "zoom_all": {"type": "boolean"},
            },
            "required": ["handle"],
        },
    },
    "ovito.configure_vis_element": {
        "handler": handle_configure_vis_element,
        "description": (
            "Configure any visual element: particles, bonds, cell, surface, "
            "dislocations, vectors, lines, voxel_grid, triangle_mesh."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "element": {
                    "type": "string",
                    "enum": ["particles", "bonds", "cell", "surface",
                             "dislocations", "vectors", "lines", "voxel_grid", "triangle_mesh"],
                },
                "properties": {"type": "object"},
            },
            "required": ["handle", "element"],
        },
    },
    "ovito.add_overlay": {
        "handler": handle_add_overlay,
        "description": (
            "Add viewport overlay: color_legend, text_label, coordinate_tripod, "
            "or python_overlay (custom drawing with code property)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "overlay_type": {
                    "type": "string",
                    "enum": ["color_legend", "text_label", "coordinate_tripod", "python_overlay"],
                },
                "properties": {"type": "object", "description": "Overlay properties. python_overlay accepts 'code'."},
            },
            "required": ["handle", "overlay_type"],
        },
    },

    # ── Rendering ─────────────────────────────────────────────────────────
    "ovito.render_image": {
        "handler": handle_render_image,
        "description": "Render scene to PNG/TIFF using Tachyon, OSPRay, or ANARI ray-tracers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "output_file": {"type": "string"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "background": {"type": "string"},
                "transparent_background": {"type": "boolean"},
                "renderer": {"type": "string", "enum": ["tachyon", "ospray", "anari"]},
                "antialiasing": {"type": "boolean"},
                "antialiasing_samples": {"type": "integer"},
                "shadows": {"type": "boolean"},
                "ambient_occlusion": {"type": "boolean"},
                "frame": {"type": "integer"},
            },
            "required": ["handle"],
        },
    },
    "ovito.render_animation": {
        "handler": handle_render_animation,
        "description": "Render animation (GIF/AVI/MP4) from trajectory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "output_file": {"type": "string"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "fps": {"type": "integer"},
                "start_frame": {"type": "integer"},
                "end_frame": {"type": "integer"},
                "every_nth_frame": {"type": "integer"},
                "renderer": {"type": "string", "enum": ["tachyon", "ospray", "anari"]},
                "antialiasing": {"type": "boolean"},
                "shadows": {"type": "boolean"},
            },
            "required": ["handle"],
        },
    },
    "ovito.render_multi_pipeline": {
        "handler": handle_render_multi_pipeline,
        "description": "Render multiple pipelines together in a single scene.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handles": {"type": "array", "items": {"type": "string"}, "description": "List of pipeline handles."},
                "output_file": {"type": "string"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "background": {"type": "string"},
                "transparent_background": {"type": "boolean"},
                "renderer": {"type": "string", "enum": ["tachyon", "ospray", "anari"]},
                "frame": {"type": "integer"},
            },
            "required": ["handles"],
        },
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# MCP PROTOCOL
# ═══════════════════════════════════════════════════════════════════════════════

SERVER_INSTRUCTIONS = textwrap.dedent("""\
    OVITO MCP Server v2.0 – Fully-featured headless atomistic visualization & analysis.

    WORKFLOW:
    1. Import data:  ovito.import_file, ovito.load_trajectory, ovito.create_particles
    2. Inspect:      ovito.inspect_data, ovito.pipeline_info, ovito.get_attributes
    3. Analyze:      ovito.add_modifier → ovito.get_properties / get_data_table / query_mesh
    4. Neighbors:    ovito.find_neighbors (cutoff or N-nearest)
    5. Measure:      ovito.measure (distance / angle / dihedral)
    6. Types:        ovito.manage_types (rename, set mass/radius/color)
    7. Select:       ovito.select_expression, ovito.select_type
    8. Visualize:    ovito.set_visual_style, ovito.set_camera, ovito.configure_vis_element
    9. Overlays:     ovito.add_overlay (color_legend, text, tripod, python_overlay)
    10. Render:      ovito.render_image, ovito.render_animation, ovito.render_multi_pipeline
    11. Export:       ovito.export_file (15+ formats)
    12. Modify:      ovito.modify_modifier (tweak params, enable/disable without re-adding)
    13. Gradients:   ovito.configure_color_gradient (Viridis, Hot, Rainbow, etc.)
    14. Merge:       ovito.combine_datasets (multi-pipeline compositing)
    15. Playback:    ovito.animation_settings (playback ratio, static frame)
    16. Escape:      ovito.run_python_script (arbitrary OVITO Python code)

    RENDERERS: tachyon (default, CPU), ospray (CPU, high quality), anari (NVIDIA GPU)

    KEY MODIFIERS:
      Structure: CNA, PTM, AcklandJones, IdentifyDiamond, DislocationAnalysis
      Analysis:  Coordination, Voronoi, AtomicStrain, CentroSymmetry, Cluster,
                 WignerSeitz, Histogram, SpatialBinning, RDF, BondAngle, StructureFactor
      Modify:    Slice, Replicate, AffineTransform, CreateBonds, ConstructSurface,
                 ComputeProperty, WrapPeriodic, DeleteSelected
      Visual:    ColorCoding, ColorByType, AssignColor, AmbientOcclusion, CoordinationPolyhedra
      Trajectory: CalculateDisplacements, GenerateTrajectoryLines, SmoothTrajectory

    VIS ELEMENTS: particles, bonds, cell, surface, dislocations, vectors, lines, voxel_grid, triangle_mesh
""")


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
        "serverInfo": {"name": "ovito_mcp", "version": "2.0.0"},
        "instructions": SERVER_INSTRUCTIONS,
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
    return {"content": [{"type": "text", "text": json.dumps(result, default=_safe_json)}]}


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
