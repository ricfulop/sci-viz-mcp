"""Nature Materials-style crystal-structure render.

Produces a publication-quality ball-and-stick render of an arbitrary CIF
through the SciViz Blender add-on, layered with the polish that
distinguishes Nature Materials / Nature Photonics figures from a default
ball-and-stick:

  * Gradient near-white world (subliminal depth, no harsh white wall)
  * 3-point area lighting (warm key, cool fill, top rim) with soft falloff
  * Polished but non-metallic atom shaders (low roughness, slight specular)
  * Bonds slightly darker and rougher than atoms so they read as scaffolding
  * Optional supercell wireframe (thin dark edges) to anchor the lattice
  * 85 mm perspective camera with a touch of depth of field on the
    centroid for a subtle highlight falloff
  * Cycles 512 samples with Standard view + Medium High Contrast look

Run this either:

  * Directly inside Blender via the SciViz panel + the scripting tab, or
  * Through the Foundation MCP server's execute_blender_code tool, e.g.
    `exec(open(__file__).read())`.

The ``configure(...)`` function is the only public API.
"""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path
from typing import Iterable

import bpy
from mathutils import Vector


def _clear_default_props() -> None:
    """Remove the default Cube/Light/Camera and any prior SciViz scaffolding.

    Also purges the AxisIndicator empty + every object parented to it so
    repeated renders don't accumulate stale arrow gizmos.
    """
    named = (
        "Cube", "Light", "Camera",
        "SciVizCam", "SciVizSun", "SciVizSunKey", "SciVizSunFill",
        "NMKey", "NMFill", "NMRim", "NMCam",
        "Supercell_wireframe", "AxisIndicator",
    )
    stale: list[bpy.types.Object] = []
    for obj in list(bpy.data.objects):
        if obj.name in named:
            stale.append(obj)
        elif obj.parent is not None and obj.parent.name == "AxisIndicator":
            stale.append(obj)
    for obj in stale:
        bpy.data.objects.remove(obj, do_unlink=True)
    for mat in list(bpy.data.materials):
        if mat.name.startswith("AxisIndicator_") and mat.users == 0:
            bpy.data.materials.remove(mat)


def _maybe_supercell(src_cif: str, expansion: tuple[int, int, int] | None) -> str:
    """If ``expansion`` is given, build a supercell with ASE and return a
    temp CIF path. Otherwise return ``src_cif`` unchanged.
    """
    if expansion is None:
        return src_cif
    import ase.io  # type: ignore
    from ase.build import make_supercell  # type: ignore
    import numpy as np  # type: ignore

    atoms = ase.io.read(src_cif)
    P = np.diag(expansion)
    super_atoms = make_supercell(atoms, P)
    tmp = tempfile.NamedTemporaryFile(
        suffix=f"_super_{expansion[0]}x{expansion[1]}x{expansion[2]}.cif",
        delete=False,
    )
    tmp.close()
    ase.io.write(tmp.name, super_atoms)
    return tmp.name


def _bbox(coll: bpy.types.Collection) -> tuple[Vector, Vector, float]:
    minp = Vector((math.inf,) * 3)
    maxp = Vector((-math.inf,) * 3)
    for obj in coll.objects:
        if obj.type != "MESH":
            continue
        for v in obj.bound_box:
            wp = obj.matrix_world @ Vector(v)
            for i in range(3):
                minp[i] = min(minp[i], wp[i])
                maxp[i] = max(maxp[i], wp[i])
    extent = max((maxp - minp)[i] for i in range(3))
    return minp, maxp, extent


def _polish_atom_materials(roughness: float = 0.22, specular: float = 0.55) -> None:
    """Bump atom shaders to a Nature-Materials-style soft-gloss finish."""
    for mat in bpy.data.materials:
        if not mat.name.startswith("Mat_") or mat.name == "Mat_Bond":
            continue
        if not mat.use_nodes:
            mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is None:
            continue
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = roughness
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 0.0
        for spec_key in ("Specular IOR Level", "Specular"):
            if spec_key in bsdf.inputs:
                bsdf.inputs[spec_key].default_value = specular
                break

    bond = bpy.data.materials.get("Mat_Bond")
    if bond is not None and bond.use_nodes:
        bsdf = bond.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            if "Base Color" in bsdf.inputs:
                bsdf.inputs["Base Color"].default_value = (0.55, 0.56, 0.58, 1.0)
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = 0.40
            if "Metallic" in bsdf.inputs:
                bsdf.inputs["Metallic"].default_value = 0.10


def _gradient_world(top: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0),
                    bottom: tuple[float, ...] = (0.92, 0.94, 0.97, 1.0),
                    strength: float = 1.0) -> None:
    scene = bpy.context.scene
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        scene.world = world
    world.use_nodes = True
    nt = world.node_tree

    for n in list(nt.nodes):
        nt.nodes.remove(n)

    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    grad = nt.nodes.new("ShaderNodeTexGradient")
    grad.gradient_type = "LINEAR"
    mapping = nt.nodes.new("ShaderNodeMapping")
    coord = nt.nodes.new("ShaderNodeTexCoord")

    nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], grad.inputs["Vector"])
    nt.links.new(grad.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])

    bg.inputs["Strength"].default_value = strength
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = bottom
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = top


def _add_area_light(name: str, location, energy: float, size: float,
                    color=(1.0, 1.0, 1.0)) -> bpy.types.Object:
    data = bpy.data.lights.new(name, type="AREA")
    data.energy = energy
    data.size = size
    data.color = color
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    return obj


def _three_point_lighting(center: Vector, extent: float) -> None:
    key = _add_area_light(
        "NMKey",
        location=(center.x + extent * 1.6, center.y - extent * 1.4, center.z + extent * 1.5),
        energy=900.0, size=extent * 1.2, color=(1.0, 0.96, 0.90),
    )
    fill = _add_area_light(
        "NMFill",
        location=(center.x - extent * 1.5, center.y - extent * 0.6, center.z + extent * 0.8),
        energy=350.0, size=extent * 1.0, color=(0.85, 0.90, 1.0),
    )
    rim = _add_area_light(
        "NMRim",
        location=(center.x + extent * 0.2, center.y + extent * 1.4, center.z + extent * 1.8),
        energy=500.0, size=extent * 0.7, color=(1.0, 1.0, 1.0),
    )
    for lo in (key, fill, rim):
        direction = center - Vector(lo.location)
        lo.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _aimed_camera(center: Vector, extent: float, lens_mm: float = 85.0,
                  focus_object: bpy.types.Object | None = None,
                  fstop: float = 6.3,
                  distance_mult: float = 2.6) -> bpy.types.Object:
    cam_data = bpy.data.cameras.new("NMCam")
    cam_data.type = "PERSP"
    cam_data.lens = lens_mm
    cam_data.dof.use_dof = focus_object is not None
    if focus_object is not None:
        cam_data.dof.focus_object = focus_object
        cam_data.dof.aperture_fstop = fstop

    cam = bpy.data.objects.new("NMCam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    cam.location = (
        center.x + extent * distance_mult,
        center.y - extent * distance_mult,
        center.z + extent * distance_mult * 0.55,
    )
    cam.rotation_euler = (center - Vector(cam.location)).to_track_quat("-Z", "Y").to_euler()
    return cam


_NM_W_COLOR = (0.20, 0.55, 0.82, 1.0)
_NM_C_COLOR = (0.22, 0.26, 0.32, 1.0)


def _retune_atom_colors(overrides: dict[str, tuple[float, float, float, float]] | None = None) -> None:
    """Replace overly-saturated CPK defaults with print-friendlier tones."""
    overrides = overrides or {"W": _NM_W_COLOR, "C": _NM_C_COLOR}
    for sym, color in overrides.items():
        mat = bpy.data.materials.get(f"Mat_{sym}")
        if mat is None or not mat.use_nodes:
            continue
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None and "Base Color" in bsdf.inputs:
            bsdf.inputs["Base Color"].default_value = color


def _axis_indicator(origin: Vector, vectors: dict[str, Vector],
                    length: float, name: str = "AxisIndicator",
                    label_size: float | None = None) -> None:
    """Draw a small a/b/c arrow gizmo at ``origin`` (world space).

    Arrows are short cylinders + cone tips; labels are 3D text. Colors
    follow the standard convention: a red, b green, c blue.
    """
    colors = {
        "a": (0.85, 0.20, 0.18, 1.0),
        "b": (0.20, 0.65, 0.30, 1.0),
        "c": (0.20, 0.40, 0.85, 1.0),
    }
    label_size = label_size if label_size is not None else length * 0.35
    parent = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(parent)
    parent.location = origin

    for axis, direction in vectors.items():
        d = direction.normalized()
        rot = Vector((0, 0, 1)).rotation_difference(d).to_euler()
        col = colors.get(axis, (0.5, 0.5, 0.5, 1.0))
        mat = bpy.data.materials.new(f"{name}_{axis}_mat")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            if "Base Color" in bsdf.inputs:
                bsdf.inputs["Base Color"].default_value = col
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = 0.45

        bpy.ops.mesh.primitive_cylinder_add(
            radius=length * 0.05,
            depth=length * 0.85,
            location=tuple(origin + d * (length * 0.425)),
        )
        shaft = bpy.context.active_object
        shaft.rotation_euler = rot
        shaft.data.materials.clear()
        shaft.data.materials.append(mat)
        shaft.parent = parent

        bpy.ops.mesh.primitive_cone_add(
            radius1=length * 0.10,
            depth=length * 0.20,
            location=tuple(origin + d * (length * 0.95)),
        )
        tip = bpy.context.active_object
        tip.rotation_euler = rot
        tip.data.materials.clear()
        tip.data.materials.append(mat)
        tip.parent = parent

        bpy.ops.object.text_add(location=tuple(origin + d * (length * 1.25)))
        label = bpy.context.active_object
        label.data.body = axis
        label.data.size = label_size
        label.data.align_x = "CENTER"
        label.data.align_y = "CENTER"
        label.data.materials.clear()
        label.data.materials.append(mat)
        label.parent = parent
        label.rotation_euler = bpy.context.scene.camera.rotation_euler if bpy.context.scene.camera else (0, 0, 0)


def _supercell_wireframe(minp: Vector, maxp: Vector, name: str = "Supercell_wireframe",
                         color=(0.18, 0.20, 0.23, 1.0), thickness: float = 0.025) -> None:
    """Draw thin dark cylinders along the 12 edges of the supercell box."""
    mesh = bpy.data.meshes.new(name + "_data")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    corners = [Vector((x, y, z)) for x in (minp.x, maxp.x)
               for y in (minp.y, maxp.y) for z in (minp.z, maxp.z)]
    edges_idx = [
        (0, 1), (2, 3), (4, 5), (6, 7),
        (0, 2), (1, 3), (4, 6), (5, 7),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    mesh.from_pydata(corners, edges_idx, [])
    mesh.update()

    mat = bpy.data.materials.new(name + "_mat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        if "Base Color" in bsdf.inputs:
            bsdf.inputs["Base Color"].default_value = color
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.6
    obj.data.materials.append(mat)

    skin = obj.modifiers.new("Skin", type="SKIN")
    for v in obj.data.skin_vertices[0].data:
        v.radius = (thickness, thickness)
    obj.modifiers.new("Subdivision", type="SUBSURF").levels = 1


def configure(
    cif_path: str,
    output_path: str,
    *,
    expansion: tuple[int, int, int] | None = None,
    width: int = 1600,
    height: int = 1200,
    samples: int = 512,
    atom_scale: float = 0.45,
    bond_radius: float = 0.10,
    bond_cutoff: float = 3.0,
    only_unlike_bonds: bool = True,
    lens_mm: float = 85.0,
    fstop: float = 6.3,
    show_supercell_box: bool = True,
    show_axis_indicator: bool = False,
    axis_indicator_position: str = "lower_left",
    nm_color_overrides: dict[str, tuple[float, float, float, float]] | None = None,
    look: str = "Medium High Contrast",
) -> dict:
    """Import ``cif_path`` and produce a Nature-Materials-style render at
    ``output_path``. Returns the import/preset/render result envelopes.
    """
    _clear_default_props()
    src = _maybe_supercell(cif_path, expansion)

    res_imp = bpy.ops.sciviz.import_crystal(
        filepath=src,
        bond_cutoff=bond_cutoff,
        atom_scale=atom_scale,
        bond_radius=bond_radius,
        only_unlike_bonds=only_unlike_bonds,
        collection_name="Crystal",
    )
    res_pre = bpy.ops.sciviz.apply_preset(
        preset="PERSPECTIVE_DEPTH",
        transparent_background=False,
    )

    coll = bpy.data.collections["Crystal"]
    minp, maxp, extent = _bbox(coll)
    center = (minp + maxp) * 0.5

    central_atom = None
    best_d = math.inf
    for obj in coll.objects:
        if obj.type != "MESH" or obj.name.startswith("Bond_"):
            continue
        d = (obj.matrix_world.translation - center).length
        if d < best_d:
            best_d = d
            central_atom = obj

    cam = _aimed_camera(center, extent, lens_mm=lens_mm,
                        focus_object=central_atom, fstop=fstop)
    _three_point_lighting(center, extent)
    _polish_atom_materials()
    _retune_atom_colors(nm_color_overrides)
    _gradient_world()

    if show_supercell_box:
        _supercell_wireframe(minp, maxp)

    if show_axis_indicator:
        # Place the gizmo in screen-space-aware world position: take the
        # camera basis and offset the origin along (-right, -up) from the
        # crystal centre so the gizmo always lands in the camera's lower-
        # left corner regardless of the chosen view angle.
        cam_matrix = cam.matrix_world
        right = cam_matrix.to_3x3().col[0].copy()
        up = cam_matrix.to_3x3().col[1].copy()
        forward = -cam_matrix.to_3x3().col[2].copy()

        sign_right = -1.0 if axis_indicator_position.endswith("left") else 1.0
        sign_up = -1.0 if axis_indicator_position.startswith("lower") else 1.0

        gizmo_origin = (
            center
            + right * (sign_right * extent * 1.15)
            + up * (sign_up * extent * 0.75)
            + forward * (extent * 0.20)
        )
        _axis_indicator(
            origin=gizmo_origin,
            vectors={
                "a": Vector((1.0, 0.0, 0.0)),
                "b": Vector((0.0, 1.0, 0.0)),
                "c": Vector((0.0, 0.0, 1.0)),
            },
            length=extent * 0.45,
            label_size=extent * 0.20,
        )

    scene = bpy.context.scene
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.01
    scene.cycles.samples = samples
    scene.view_settings.view_transform = "Standard"
    try:
        scene.view_settings.look = look
    except Exception:
        pass

    out_path = str(Path(output_path).expanduser())
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    res_ren = bpy.ops.sciviz.render_hq(
        filepath=out_path,
        width=width,
        height=height,
        samples=samples,
    )

    if expansion is not None and src != cif_path and os.path.isfile(src):
        try:
            os.unlink(src)
        except OSError:
            pass

    return {
        "import": list(res_imp),
        "preset": list(res_pre),
        "render": list(res_ren),
        "output_file": out_path,
        "output_size_bytes": os.path.getsize(out_path) if os.path.isfile(out_path) else 0,
        "extent": extent,
        "n_objects": len(coll.objects),
        "n_atoms": sum(1 for o in coll.objects
                       if o.type == "MESH" and not o.name.startswith("Bond_")),
        "n_bonds": sum(1 for o in coll.objects
                       if o.name.startswith("Bond_")),
        "supercell_expansion": expansion,
        "lens_mm": lens_mm,
        "samples": samples,
    }


if __name__ == "__main__":
    print(configure(
        cif_path="/Users/ricfulop/voltivity/sci-viz-mcp/tests/sample_structures/hexagonal_WC.cif",
        output_path="/Users/ricfulop/voltivity/sci-viz-mcp/output/WC_nature_style.png",
        expansion=(3, 3, 2),
        bond_cutoff=2.5,
        atom_scale=0.45,
        bond_radius=0.10,
    ))
