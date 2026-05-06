"""Nature Materials-style crystal-structure render.

Produces a publication-quality ball-and-stick render of an arbitrary CIF
through the SciViz Blender add-on. Style choices are anchored to the
official Nature research figure guide
(https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/)
and to Wong B., "Points of view: Colour blindness", Nature Methods 8,
441 (2011) — the Okabe–Ito palette Nature cites for accessibility.

What this layers on top of bpy.ops.sciviz.{import_crystal, apply_preset,
render_hq}:

  * Pure white world (Nature explicitly avoids decorative gradients;
    depth comes from the 3-point lighting, not the background)
  * 3-point Area lighting (warm key, cool fill, top rim) sized to the
    crystal so soft falloff scales with the structure
  * Okabe–Ito-mapped element palette — the colour-blind-safe set that
    Nature recommends — instead of saturated CPK that prints candy
  * Per-element covalent radii (Cordero 2008) so W is visibly larger
    than C, etc., for both physical accuracy and visual hierarchy
  * Polished but non-metallic Principled BSDF (low roughness, slight
    specular, subtle clearcoat) for the wet-highlight Nature look
  * Bonds slightly darker / rougher so they read as scaffolding rather
    than competing with atoms
  * 70-85 mm perspective camera with a touch of depth of field on the
    central atom for subtle falloff
  * Cycles 1024 samples + adaptive sampling, Standard view transform

Note on a/b/c "axis indicators": Nature does NOT require crystallographic
a/b/c arrows. The "a, b, c, d" the figure guide mentions is the
8-pt bold lowercase label on each subfigure of a multi-panel figure,
not a crystal-axes gizmo. The helper to draw lattice arrows is kept
here for authors who want them but it defaults to off.

Run this either:

  * Directly inside Blender via the Scripting tab, or
  * Through the Foundation MCP server's execute_blender_code tool, e.g.
    `exec(open(__file__).read())` then call `configure(...)`.
"""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path
from typing import Iterable

import bpy
from mathutils import Vector


# ── Okabe–Ito accessible palette (Wong 2011, recommended by Nature) ──────────
# https://www.nature.com/articles/nmeth.1618
OKABE_ITO: dict[str, tuple[float, float, float, float]] = {
    "orange":         (0.902, 0.624, 0.000, 1.0),  # #E69F00
    "sky_blue":       (0.337, 0.706, 0.914, 1.0),  # #56B4E9
    "bluish_green":   (0.000, 0.620, 0.451, 1.0),  # #009E73
    "yellow":         (0.941, 0.894, 0.259, 1.0),  # #F0E442
    "blue":           (0.000, 0.447, 0.698, 1.0),  # #0072B2
    "vermillion":     (0.835, 0.369, 0.000, 1.0),  # #D55E00
    "reddish_purple": (0.800, 0.475, 0.655, 1.0),  # #CC79A7
    "black":          (0.000, 0.000, 0.000, 1.0),  # #000000
}

# Element → Okabe–Ito mapping for Nature-style figures. Picks preserve
# chemistry conventions (O red, Cu warm orange, Au yellow, etc.) while
# staying inside the colour-blind-safe palette.
NATURE_ELEMENT_COLORS: dict[str, tuple[float, float, float, float]] = {
    # Heavy / transition metals
    "W":  OKABE_ITO["blue"],
    "Mo": OKABE_ITO["sky_blue"],
    "Zr": OKABE_ITO["bluish_green"],
    "Y":  OKABE_ITO["reddish_purple"],
    "Ti": (0.62, 0.62, 0.66, 1.0),
    "V":  (0.65, 0.55, 0.50, 1.0),
    "Cr": (0.55, 0.60, 0.78, 1.0),
    "Mn": OKABE_ITO["reddish_purple"],
    "Fe": OKABE_ITO["vermillion"],
    "Co": OKABE_ITO["reddish_purple"],
    "Ni": (0.30, 0.70, 0.40, 1.0),
    "Cu": OKABE_ITO["orange"],
    "Zn": (0.55, 0.55, 0.62, 1.0),
    "Ag": (0.86, 0.86, 0.88, 1.0),
    "Pt": (0.82, 0.82, 0.86, 1.0),
    "Au": OKABE_ITO["yellow"],
    "Sn": (0.45, 0.50, 0.55, 1.0),
    # Light elements
    "H":  (0.95, 0.95, 0.95, 1.0),
    "C":  (0.10, 0.10, 0.11, 1.0),
    "N":  OKABE_ITO["bluish_green"],
    "O":  OKABE_ITO["vermillion"],
    "F":  OKABE_ITO["bluish_green"],
    "Si": OKABE_ITO["orange"],
    "P":  OKABE_ITO["orange"],
    "S":  OKABE_ITO["yellow"],
    "Cl": OKABE_ITO["bluish_green"],
    "Na": OKABE_ITO["reddish_purple"],
    "Mg": (0.55, 0.80, 0.10, 1.0),
    "Al": (0.72, 0.74, 0.78, 1.0),
    "K":  OKABE_ITO["reddish_purple"],
    "Ca": (0.62, 0.66, 0.70, 1.0),
}

# Cordero 2008 covalent radii in Å, used for per-element atom scaling.
# Beatriz Cordero et al., "Covalent radii revisited", Dalton Trans. 2008.
COVALENT_RADII: dict[str, float] = {
    "H": 0.31, "He": 0.28,
    "Li": 1.28, "Be": 0.96, "B": 0.84, "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57,
    "Na": 1.66, "Mg": 1.41, "Al": 1.21, "Si": 1.11, "P": 1.07, "S": 1.05, "Cl": 1.02,
    "K": 2.03, "Ca": 1.76, "Sc": 1.70, "Ti": 1.60, "V": 1.53, "Cr": 1.39, "Mn": 1.39,
    "Fe": 1.32, "Co": 1.26, "Ni": 1.24, "Cu": 1.32, "Zn": 1.22,
    "Y": 1.90, "Zr": 1.75, "Nb": 1.64, "Mo": 1.54, "Ru": 1.46, "Rh": 1.42, "Pd": 1.39,
    "Ag": 1.45, "Cd": 1.44, "Sn": 1.39,
    "W": 1.62, "Re": 1.51, "Os": 1.44, "Ir": 1.41, "Pt": 1.36, "Au": 1.36,
}


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


def _polish_atom_materials(
    roughness: float = 0.18,
    specular: float = 0.55,
    clearcoat: float = 0.08,
) -> None:
    """Bump atom shaders to a Nature-Materials-style polished finish.

    Lower roughness + small clearcoat give the wet highlight that
    distinguishes Nature/Nature Materials renders from a matte default.
    """
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
        for coat_key in ("Coat Weight", "Clearcoat Weight", "Clearcoat"):
            if coat_key in bsdf.inputs:
                bsdf.inputs[coat_key].default_value = clearcoat
                break
        for coat_rough_key in ("Coat Roughness", "Clearcoat Roughness"):
            if coat_rough_key in bsdf.inputs:
                bsdf.inputs[coat_rough_key].default_value = 0.10
                break

    bond = bpy.data.materials.get("Mat_Bond")
    if bond is not None and bond.use_nodes:
        bsdf = bond.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            if "Base Color" in bsdf.inputs:
                bsdf.inputs["Base Color"].default_value = (0.62, 0.63, 0.66, 1.0)
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = 0.45
            if "Metallic" in bsdf.inputs:
                bsdf.inputs["Metallic"].default_value = 0.0


def _apply_per_element_radii(
    coll: bpy.types.Collection,
    radii: dict[str, float] | None = None,
    compression: float = 0.7,
) -> dict[str, float]:
    """Scale each atom Object by its (compressed) covalent radius.

    SciViz's ``import_crystal`` creates every sphere at the same base
    radius (the ``atom_scale`` arg). This post-processes per-atom
    Object scale so the rendered radii follow Cordero 2008, with the
    user's ``atom_scale`` acting as a global multiplier on top.

    ``compression`` exponent below 1.0 lifts small atoms relative to
    big ones — physically less accurate but visually clearer for
    ball-and-stick.  Use ``compression=1.0`` for true covalent radii
    (W:C = 2.13:1 makes light atoms read as dots).
    """
    radii = radii if radii is not None else COVALENT_RADII
    applied: dict[str, float] = {}
    for obj in coll.objects:
        if obj.type != "MESH":
            continue
        if obj.name.startswith("Bond_") or obj.name.startswith("Supercell_"):
            continue
        symbol = obj.name.split("_", 1)[0]
        radius_ang = radii.get(symbol)
        if radius_ang is None:
            continue
        scaled = radius_ang ** compression
        obj.scale = (scaled, scaled, scaled)
        applied[symbol] = round(scaled, 3)
    return applied


def _white_world(strength: float = 1.0,
                 color: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0)) -> None:
    """Flat white world. Nature avoids decorative backgrounds; let the
    3-point lighting carry depth instead of a gradient."""
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
    bg.inputs["Color"].default_value = color
    bg.inputs["Strength"].default_value = strength
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


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


def _retune_atom_colors(palette: dict[str, tuple[float, float, float, float]] | None = None) -> None:
    """Repaint atom shaders with a Nature-friendly Okabe-Ito palette.

    The default palette (NATURE_ELEMENT_COLORS) is colour-blind safe per
    Wong 2011 / Nature Methods 8, 441 — the palette Nature explicitly
    cites in its figure guide.
    """
    palette = palette if palette is not None else NATURE_ELEMENT_COLORS
    for sym, color in palette.items():
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
    samples: int = 1024,
    atom_scale: float = 0.40,
    bond_radius: float = 0.10,
    bond_cutoff: float = 3.0,
    only_unlike_bonds: bool = True,
    lens_mm: float = 70.0,
    fstop: float = 8.0,
    show_supercell_box: bool = False,
    show_axis_indicator: bool = False,
    axis_indicator_position: str = "lower_left",
    palette: dict[str, tuple[float, float, float, float]] | None = None,
    use_per_element_radii: bool = True,
    radii_compression: float = 0.7,
    background: str = "white",
    look: str = "None",
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

    radii_applied: dict[str, float] = {}
    if use_per_element_radii:
        radii_applied = _apply_per_element_radii(coll, compression=radii_compression)

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
    _retune_atom_colors(palette)

    if background == "gradient":
        _gradient_world()
    else:
        _white_world()

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
        "background": background,
        "per_element_radii_applied": radii_applied,
        "palette": "Okabe-Ito (Wong 2011)" if palette is None else "custom",
    }


if __name__ == "__main__":
    print(configure(
        cif_path="/Users/ricfulop/voltivity/sci-viz-mcp/tests/sample_structures/hexagonal_WC.cif",
        output_path="/Users/ricfulop/voltivity/sci-viz-mcp/output/WC_nature_style.png",
        expansion=(2, 2, 2),
        bond_cutoff=2.5,
        atom_scale=0.40,
        bond_radius=0.10,
    ))
