"""Animate Figure 10 of the Microscopic Origins of Voltivity manuscript.

Renders the four-stage narrative of "Ordered Defect Condensation" in 8YSZ:

  Act 1 (0-3 s, frames 0-71)        Acoustic Blueprint           — pristine
                                                                   fluorite supercell,
                                                                   slow rotation
  Act 2 (3-9 s, frames 72-215)      Phonon wave grows            — standing wave at
                                                                   d* ≈ 0.96 a along
                                                                   [001] templates the
                                                                   lattice
  Act 3 (9-17 s, frames 216-407)    Topotactic collapse          — half the O migrate
                                                                   8c → 4b (octahedral),
                                                                   half fade as
                                                                   vacancies / 2DEG
                                                                   seeds; Zr⁴⁺ → Zr²⁺
                                                                   (blue → vermillion);
                                                                   8% [110] contraction
  Act 4 (17-21 s, frames 408-503)   Zone folding overlay         — 2D matplotlib
                                                                   dispersion + Raman
                                                                   panel (rendered
                                                                   separately)
  Act 5 (21-28 s, frames 504-671)   Mesoscale Ostwald ripening   — camera pulls back,
                                                                   nucleation → LSW
                                                                   ripening → ~200 nm
                                                                   dendritic 2DEG
                                                                   colonies

Total: 672 frames at 24 fps = 28 seconds, 1280×720 Eevee Next.

Physics constants are anchored to the manuscript:

  d* = 2.21 Ω^(1/3)  with Ω = a³/12 = 11.35 Å³ for 8YSZ → d* = 4.96 Å ≈ 0.96 a
  Geometric collapse  fluorite 8c → rocksalt 4b: a_oct/a_tet = √3/2 = 0.866
  Electronic expansion Zr⁴⁺ → Zr²⁺ (d-electron recapture): ×1.062
  Combined           a_child = a_parent × 0.920 → 5.145 Å → 4.73 Å (matches SAED)

This file is the Phase 1 implementation. It produces acts 1, 2, 3, and 5 in
Blender. Act 4 (zone-folding overlay) is generated separately by
``examples/animate_fig10_actc.py`` and concatenated in post.

Driven through the Foundation MCP server's execute_blender_code tool:

    >>> exec(open('/path/to/animate_fig10.py').read())
    >>> setup_scene()                         # build the supercell, materials, camera
    >>> animate_all()                         # bake every keyframe in one shot
    >>> render(frame_start=0, frame_end=23)   # quick preview
    >>> render()                              # full animation
"""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path
from typing import Iterable

import bpy
from mathutils import Vector


# ── Physics constants (from manuscript Fig. 10 caption) ─────────────────────

A_PARENT = 5.145          # Å, fluorite ZrO2 lattice parameter
A_CHILD = 4.73            # Å, rocksalt ZrO lattice parameter
GEOMETRIC_FACTOR = math.sqrt(3) / 2.0     # 0.866
ELECTRONIC_FACTOR = 1.062
CONTRACTION = GEOMETRIC_FACTOR * ELECTRONIC_FACTOR        # 0.920
D_STAR = 4.96             # Å, acoustic ridge phonon spacing (= 0.96 × a)
WAVE_K = 2 * math.pi / D_STAR

# Atom colors: Okabe-Ito accessible palette (Wong 2011, Nature Methods)
# Initial = panel a (insulating fluorite), final = panel b (metallic rocksalt)
ZR_COLOR_INSULATING = (0.000, 0.447, 0.698, 1.0)   # Okabe-Ito blue   #0072B2
ZR_COLOR_METALLIC   = (0.835, 0.369, 0.000, 1.0)   # Okabe-Ito vermillion #D55E00
O_COLOR_LATTICE     = (0.835, 0.369, 0.000, 1.0)   # vermillion (CPK red, accessible)
O_COLOR_ROCKSALT    = (0.902, 0.624, 0.000, 1.0)   # Okabe-Ito orange #E69F00 (mark migrated O)
BOND_COLOR          = (0.65, 0.66, 0.69, 1.0)


# ── Animation timeline (24 fps, 672 frames total) ───────────────────────────

FPS = 24

ACT1 = (0,   72)     # establishing rotation
ACT2 = (72,  216)    # phonon wave amplitude growth
ACT3 = (216, 408)    # topotactic transformation + lattice contraction
ACT4 = (408, 504)    # placeholder for zone-folding overlay (rendered separately)
ACT5 = (504, 672)    # mesoscale Ostwald ripening
TOTAL_FRAMES = 672

# Sub-timeline within Act 3
ACT3_O_MIGRATE   = (216, 312)   # O atoms slide tet → oct
ACT3_O_FADE      = (240, 336)   # half of O atoms fade (vacancies forming)
ACT3_ZR_RECOLOR  = (288, 384)   # Zr⁴⁺ → Zr²⁺ color blend
ACT3_CONTRACT    = (312, 408)   # lattice scale 1.0 → 0.92


# ── Scene setup ─────────────────────────────────────────────────────────────


SUPERCELL = (3, 3, 3)                          # 27 fluorite unit cells
ATOM_SCALE = 0.40                              # base sphere radius (Å)
BOND_RADIUS = 0.10
BOND_CUTOFF = 2.6                              # tight enough that Zr-Zr is excluded
COLLECTION_NAME = "Fig10_Crystal"
WAVE_DIR = Vector((0.0, 0.0, 1.0))             # phonon propagation axis


def _clear_scene() -> None:
    """Remove anything our prior runs may have left behind.

    Uses startswith() prefix matching everywhere so Blender's auto-rename
    (`AxisIndicator.001`, `Cylinder.043`, ...) doesn't slip through.
    """
    safe_prefixes = (
        "Fig10_Crystal_pivot", "Mat_",
    )
    target_prefixes_objs = (
        "Fig10Cam", "Fig10Key", "Fig10Fill", "Fig10Rim",
        "OstwaldSeed", "Dendrite",
        "AxisIndicator", "Supercell_wireframe",
        "SciVizCam", "SciVizSun", "NMKey", "NMFill", "NMRim", "NMCam",
        "Cylinder", "Cone", "Text",  # default-named primitives from gizmos
    )
    target_names_objs = {"Cube", "Light", "Camera"}

    def _is_target_obj(name: str) -> bool:
        return name in target_names_objs or any(name.startswith(p) for p in target_prefixes_objs)

    stale: list[bpy.types.Object] = []
    crystal_coll = bpy.data.collections.get(COLLECTION_NAME)
    crystal_objs = set(crystal_coll.objects) if crystal_coll is not None else set()
    for obj in list(bpy.data.objects):
        if obj in crystal_objs:
            continue
        if _is_target_obj(obj.name):
            stale.append(obj)
        elif obj.parent is not None and _is_target_obj(obj.parent.name):
            stale.append(obj)
    for obj in stale:
        bpy.data.objects.remove(obj, do_unlink=True)

    for coll_name in (COLLECTION_NAME, "Crystal", "Fig10_Seeds"):
        coll = bpy.data.collections.get(coll_name)
        if coll is None:
            continue
        for obj in list(coll.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(coll)
    # Purge orphan data-blocks (mesh/material/light leftovers)
    for action in list(bpy.data.actions):
        if action.users == 0:
            bpy.data.actions.remove(action)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    for mat in list(bpy.data.materials):
        if mat.users == 0 and (mat.name.startswith("AxisIndicator")
                               or mat.name.startswith("Mat_OstwaldSeed")):
            bpy.data.materials.remove(mat)


def _build_supercell_cif() -> str:
    """ASE-build a 3×3×3 fluorite ZrO2 supercell, save tmp CIF, return path."""
    import ase.io
    from ase.build import make_supercell
    import numpy as np

    src = "/Users/ricfulop/voltivity/sci-viz-mcp/tests/sample_structures/fluorite_ZrO2.cif"
    atoms = ase.io.read(src)
    supercell = make_supercell(atoms, np.diag(SUPERCELL))
    tmp = tempfile.NamedTemporaryFile(
        suffix=f"_fluorite_{SUPERCELL[0]}x{SUPERCELL[1]}x{SUPERCELL[2]}.cif",
        delete=False,
    )
    tmp.close()
    ase.io.write(tmp.name, supercell)
    return tmp.name


def _import_initial_structure() -> bpy.types.Collection:
    cif_path = _build_supercell_cif()
    bpy.ops.sciviz.import_crystal(
        filepath=cif_path,
        bond_cutoff=BOND_CUTOFF,
        atom_scale=ATOM_SCALE,
        bond_radius=BOND_RADIUS,
        only_unlike_bonds=True,
        collection_name=COLLECTION_NAME,
    )
    try:
        os.unlink(cif_path)
    except OSError:
        pass
    return bpy.data.collections[COLLECTION_NAME]


def _setup_materials() -> None:
    """Color atoms with Okabe-Ito palette; bond mat tuned for animation.

    Eevee + 3-light setup tends to wash specular over base color, so we
    push roughness higher than the static Nature-style render and damp
    specular slightly. Keeps the Okabe-Ito blue / vermillion readable.
    """
    def _tune(mat_name: str, color, roughness: float, specular: float = 0.40):
        mat = bpy.data.materials.get(mat_name)
        if mat is None or not mat.use_nodes:
            return
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is None:
            return
        if "Base Color" in bsdf.inputs:
            bsdf.inputs["Base Color"].default_value = color
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = roughness
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 0.0
        for k in ("Specular IOR Level", "Specular"):
            if k in bsdf.inputs:
                bsdf.inputs[k].default_value = specular
                break

    _tune("Mat_Zr", ZR_COLOR_INSULATING, roughness=0.32, specular=0.40)
    _tune("Mat_O",  O_COLOR_LATTICE,    roughness=0.34, specular=0.38)
    _tune("Mat_Bond", BOND_COLOR,        roughness=0.55, specular=0.30)


def _white_world() -> None:
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
    bg.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def _setup_lighting(center: Vector, extent: float) -> None:
    """Soft 3-light setup, scaled to Eevee's brighter response and tuned
    so the warm key doesn't drown out atom base colors."""
    for name, location, energy, size, color in (
        ("Fig10Key",  (center.x + extent * 1.6, center.y - extent * 1.4, center.z + extent * 1.5),
         500.0, extent * 1.2, (1.0, 0.98, 0.95)),
        ("Fig10Fill", (center.x - extent * 1.4, center.y - extent * 0.6, center.z + extent * 0.8),
         200.0, extent * 1.0, (0.95, 0.97, 1.0)),
        ("Fig10Rim",  (center.x + extent * 0.2, center.y + extent * 1.4, center.z + extent * 1.8),
         260.0, extent * 0.7, (1.0, 1.0, 1.0)),
    ):
        data = bpy.data.lights.new(name, type="AREA")
        data.energy = energy
        data.size = size
        data.color = color
        obj = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = location
        direction = center - Vector(location)
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _setup_camera(center: Vector, extent: float) -> bpy.types.Object:
    cam_data = bpy.data.cameras.new("Fig10Cam")
    cam_data.type = "PERSP"
    cam_data.lens = 50.0
    cam = bpy.data.objects.new("Fig10Cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    cam.location = (
        center.x + extent * 3.4,
        center.y - extent * 3.4,
        center.z + extent * 1.8,
    )
    cam.rotation_euler = (center - Vector(cam.location)).to_track_quat("-Z", "Y").to_euler()
    return cam


def _bbox(coll: bpy.types.Collection) -> tuple[Vector, Vector, Vector, float]:
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
    center = (minp + maxp) * 0.5
    return minp, maxp, center, extent


# ── Atom classification (which O migrate vs which fade) ─────────────────────


def _atom_lists(coll: bpy.types.Collection) -> tuple[list[bpy.types.Object], list[bpy.types.Object], list[bpy.types.Object]]:
    """Split crystal collection into (Zr atoms, O atoms, bonds)."""
    zr, o, bonds = [], [], []
    for obj in coll.objects:
        if obj.type != "MESH":
            continue
        if obj.name.startswith("Bond_"):
            bonds.append(obj)
            continue
        sym = obj.name.split("_", 1)[0]
        if sym == "Zr":
            zr.append(obj)
        elif sym == "O":
            o.append(obj)
    return zr, o, bonds


def _classify_oxygens(o_atoms: list[bpy.types.Object]) -> tuple[list[bpy.types.Object], list[bpy.types.Object]]:
    """Half migrate (8c → 4b), half fade. Use parity of (x+y+z) lattice index
    to alternate, so the result is a structured pattern instead of speckle —
    matches the topotactic story in the caption.
    """
    migrate, fade = [], []
    for obj in o_atoms:
        loc = obj.matrix_world.translation
        # fluorite O sits at (1/4, 1/4, 1/4) within each unit cell, so
        # round((loc - 0.25*a)/a) gives the integer cell index.
        idx = tuple(round((loc[i] / A_PARENT) - 0.25) for i in range(3))
        if (idx[0] + idx[1] + idx[2]) % 2 == 0:
            migrate.append(obj)
        else:
            fade.append(obj)
    return migrate, fade


def _rocksalt_target(o_loc: Vector) -> Vector:
    """Map a fluorite-tetrahedral O position to the nearest rocksalt-octahedral
    site. Rocksalt O sits at fractional (1/2, 0, 0) and equivalents within
    the cell. The fluorite O at (1/4, 1/4, 1/4) shifts to (1/2, 0, 0) — i.e.
    in fractional coords each axis goes from 0.25 → 0.5 / 0.0 in a pattern.
    For the animation we map by snapping each axis to the nearest of {0, 1/2}.
    Returns the world-space target.
    """
    target = []
    for i in range(3):
        frac = (o_loc[i] / A_PARENT) - math.floor(o_loc[i] / A_PARENT)
        snapped = 0.5 if frac >= 0.25 else 0.0
        cell_origin = math.floor(o_loc[i] / A_PARENT) * A_PARENT
        # bias toward the chemistry: pick (1/2, 0, 0) rather than (1/2, 1/2, 1/2)
        target.append(cell_origin + snapped * A_PARENT)
    return Vector(target)


# ── Animation: keyframe insertion helpers ───────────────────────────────────


def _key_loc(obj: bpy.types.Object, frame: int, location: Vector) -> None:
    obj.location = location
    obj.keyframe_insert(data_path="location", frame=frame)


def _key_scale(obj: bpy.types.Object, frame: int, scale: float | Vector) -> None:
    if isinstance(scale, (int, float)):
        scale = Vector((scale, scale, scale))
    obj.scale = scale
    obj.keyframe_insert(data_path="scale", frame=frame)


def _key_color(mat: bpy.types.Material, frame: int, color: tuple[float, ...]) -> None:
    if not mat.use_nodes:
        return
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is None or "Base Color" not in bsdf.inputs:
        return
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Base Color"].keyframe_insert(data_path="default_value", frame=frame)


def _key_visibility(obj: bpy.types.Object, frame: int, visible: bool) -> None:
    obj.hide_render = not visible
    obj.hide_viewport = not visible
    obj.keyframe_insert(data_path="hide_render", frame=frame)
    obj.keyframe_insert(data_path="hide_viewport", frame=frame)


# ── Animation: the four acts ────────────────────────────────────────────────


def _act1_camera_rotation(cam: bpy.types.Object, center: Vector, extent: float) -> None:
    """Slow yaw rotation around the crystal during act 1 + 2 (frames 0-216)."""
    radius = extent * 3.4
    height = center.z + extent * 1.8
    n_keyframes = 12
    for i in range(n_keyframes + 1):
        f = ACT1[0] + (ACT2[1] - ACT1[0]) * i // n_keyframes
        # gentle 25-degree sweep
        theta = math.radians(45 + 25 * i / n_keyframes)
        cam.location = (
            center.x + radius * math.sin(theta),
            center.y - radius * math.cos(theta),
            height,
        )
        cam.rotation_euler = (center - Vector(cam.location)).to_track_quat("-Z", "Y").to_euler()
        cam.keyframe_insert(data_path="location", frame=f)
        cam.keyframe_insert(data_path="rotation_euler", frame=f)


def _act2_phonon_wave(zr: list[bpy.types.Object], o: list[bpy.types.Object]) -> None:
    """Standing acoustic wave along z, amplitude grows from 0 to 0.18 Å.
    Bake one keyframe every 6 frames for smooth interpolation.
    """
    A_max = 0.18
    rest_positions = {obj.name: obj.matrix_world.translation.copy() for obj in zr + o}

    # keyframe positions at rest at start of act 2
    for obj in zr + o:
        _key_loc(obj, ACT2[0], rest_positions[obj.name])

    n_steps = (ACT2[1] - ACT2[0]) // 6
    for step in range(1, n_steps + 1):
        frame = ACT2[0] + step * 6
        t = step / n_steps  # 0 → 1
        amplitude = A_max * t  # linear ramp

        # Zr atoms feel the wave more strongly than O (heavier mass coupling
        # to acoustic mode); use 1.0 for Zr, 0.6 for O.
        for obj_list, mass_factor in ((zr, 1.0), (o, 0.6)):
            for obj in obj_list:
                rest = rest_positions[obj.name]
                phase = WAVE_K * rest.z
                disp = amplitude * mass_factor * math.sin(phase)
                new_loc = rest + Vector((0.0, 0.0, disp))
                _key_loc(obj, frame, new_loc)


def _act3_topotactic(zr: list[bpy.types.Object],
                     o_migrate: list[bpy.types.Object],
                     o_fade: list[bpy.types.Object],
                     coll: bpy.types.Collection,
                     center: Vector) -> None:
    """The structural collapse + electronic transition + lattice contraction."""

    # 1. Hold the wave-displaced positions through the start of act 3,
    #    then begin migrating O atoms 8c → 4b
    rest_positions = {obj.name: obj.matrix_world.translation.copy()
                      for obj in zr + o_migrate + o_fade}

    for obj in zr + o_migrate + o_fade:
        _key_loc(obj, ACT3[0], rest_positions[obj.name])

    # 2. O atoms that migrate: smooth path from current → octahedral target
    f0, f1 = ACT3_O_MIGRATE
    n = 8
    for obj in o_migrate:
        start = rest_positions[obj.name]
        target = _rocksalt_target(start)
        for s in range(1, n + 1):
            t = s / n
            # ease-in-out via smoothstep
            t_smooth = t * t * (3 - 2 * t)
            new_loc = start + (target - start) * t_smooth
            _key_loc(obj, int(f0 + (f1 - f0) * s / n), new_loc)

    # 3. O atoms that fade: shrink + alpha to zero
    f0, f1 = ACT3_O_FADE
    for obj in o_fade:
        _key_scale(obj, f0, 1.0)
        _key_visibility(obj, f0, True)
        _key_scale(obj, f1 - 6, 0.05)
        _key_visibility(obj, f1, False)

    # 4. Zr color animation: Okabe-Ito blue → vermillion (Zr⁴⁺ → Zr²⁺)
    f0, f1 = ACT3_ZR_RECOLOR
    zr_mat = bpy.data.materials.get("Mat_Zr")
    if zr_mat is not None:
        _key_color(zr_mat, f0, ZR_COLOR_INSULATING)
        _key_color(zr_mat, f1, ZR_COLOR_METALLIC)

    # 5. O color: lattice red → rocksalt orange (only migrated O survive)
    o_mat = bpy.data.materials.get("Mat_O")
    if o_mat is not None:
        _key_color(o_mat, f0, O_COLOR_LATTICE)
        _key_color(o_mat, f1, O_COLOR_ROCKSALT)

    # 6. Lattice contraction: scale the Crystal collection's empty parent.
    #    Easier to script: scale every atom & bond toward `center` over the
    #    contraction window. We add an Empty parent to drive this.
    parent = bpy.data.objects.get(f"{COLLECTION_NAME}_pivot")
    if parent is None:
        parent = bpy.data.objects.new(f"{COLLECTION_NAME}_pivot", None)
        bpy.context.scene.collection.objects.link(parent)
        parent.location = center
        for obj in list(coll.objects):
            obj.parent = parent
            obj.matrix_parent_inverse = parent.matrix_world.inverted()

    f0, f1 = ACT3_CONTRACT
    _key_scale(parent, f0, 1.0)
    _key_scale(parent, f1, CONTRACTION)


def _act5_mesoscale_zoom(cam: bpy.types.Object, center: Vector, extent: float,
                         coll: bpy.types.Collection) -> None:
    """Camera pulls back; rocksalt structure shrinks toward a single seed; we
    instance scattered seeds on a wider area, then 'merge' them via scaling
    keyframes to suggest LSW ripening + dendritic condensation.
    """
    f0, f1, f_end = ACT5[0], ACT5[0] + 96, ACT5[1]

    # Camera: pull back and tilt down for a top-3/4 panorama
    radius_start = extent * 3.4
    radius_end = extent * 8.0
    height_start = center.z + extent * 1.8
    height_end = center.z + extent * 4.5

    for step in range(13):
        t = step / 12
        ease = t * t * (3 - 2 * t)
        radius = radius_start + (radius_end - radius_start) * ease
        height = height_start + (height_end - height_start) * ease
        # keep a fixed bearing for cleaner tracking
        theta = math.radians(45 + 25)
        cam.location = (
            center.x + radius * math.sin(theta),
            center.y - radius * math.cos(theta),
            height,
        )
        cam.rotation_euler = (center - Vector(cam.location)).to_track_quat("-Z", "Y").to_euler()
        f = int(f0 + (f1 - f0) * step / 12)
        cam.keyframe_insert(data_path="location", frame=f)
        cam.keyframe_insert(data_path="rotation_euler", frame=f)

    # Scatter "Ostwald seeds" - small orange spheres on a wider grid
    seed_mat = bpy.data.materials.new("Mat_OstwaldSeed")
    seed_mat.use_nodes = True
    seed_bsdf = seed_mat.node_tree.nodes.get("Principled BSDF")
    if seed_bsdf is not None:
        if "Base Color" in seed_bsdf.inputs:
            seed_bsdf.inputs["Base Color"].default_value = ZR_COLOR_METALLIC
        if "Roughness" in seed_bsdf.inputs:
            seed_bsdf.inputs["Roughness"].default_value = 0.32

    seed_coll = bpy.data.collections.get("Fig10_Seeds")
    if seed_coll is None:
        seed_coll = bpy.data.collections.new("Fig10_Seeds")
        bpy.context.scene.collection.children.link(seed_coll)

    # Build a sparse 9x9 grid of seeds at z=0 plane.
    # Track each seed by its (i, j) grid index in a list-of-tuples to dodge
    # Blender's auto-rename collisions on re-runs.
    span = extent * 5.0
    n = 9
    seeds: list[tuple[int, int, bpy.types.Object]] = []
    import random
    rng = random.Random(42)
    for i in range(n):
        for j in range(n):
            x = center.x + (i - n / 2) * (span / n) + rng.uniform(-0.1, 0.1) * span / n
            y = center.y + (j - n / 2) * (span / n) + rng.uniform(-0.1, 0.1) * span / n
            z = center.z
            bpy.ops.mesh.primitive_uv_sphere_add(
                radius=0.4, location=(x, y, z), segments=12, ring_count=8,
            )
            seed = bpy.context.active_object
            seed.name = f"OstwaldSeed_{i}x{j}"
            for face in seed.data.polygons:
                face.use_smooth = True
            seed.data.materials.clear()
            seed.data.materials.append(seed_mat)
            for c in seed.users_collection:
                c.objects.unlink(seed)
            seed_coll.objects.link(seed)
            seeds.append((i, j, seed))
            # start invisible, fade in during pull-back, then evolve
            _key_visibility(seed, ACT3[1], False)
            _key_visibility(seed, f0, False)
            _key_visibility(seed, f0 + 24, True)
            _key_scale(seed, f0 + 24, 0.4)

    # Stage 2: ripening — neighbouring 3x3 patches collapse into one anchor seed
    f_ripen = f0 + 96
    f_dendrites = f0 + 144
    by_cluster: dict[tuple[int, int], list[tuple[int, int, bpy.types.Object]]] = {}
    for i, j, s in seeds:
        cluster = (i // 3, j // 3)
        by_cluster.setdefault(cluster, []).append((i, j, s))

    for cluster, members in by_cluster.items():
        if not members:
            continue
        cx = sum(m[2].location.x for m in members) / len(members)
        cy = sum(m[2].location.y for m in members) / len(members)
        anchor_idx = 0
        for k, (i, j, s) in enumerate(members):
            _key_loc(s, f0 + 24, s.location.copy())
            _key_loc(s, f_ripen, Vector((cx, cy, s.location.z)))
            _key_scale(s, f_ripen, 1.4 if k == anchor_idx else 0.05)
            _key_visibility(s, f_ripen + 4, k == anchor_idx)

    # Stage 3: dendrites — a 4-armed branching shape sprouting from each
    # anchor. Cylinders default to z-aligned, so we rotate them into the
    # x or y axis as needed.
    arm_length = 1.6
    arm_radius = 0.10
    for cluster, members in by_cluster.items():
        if not members:
            continue
        anchor = members[0][2]
        cx, cy = anchor.location.x, anchor.location.y
        cz = anchor.location.z
        for di, dj, name_suffix in (
            ( 1,  0, "rx"), (-1,  0, "lx"),
            ( 0,  1, "fy"), ( 0, -1, "by"),
        ):
            mid_x = cx + di * arm_length * 0.5
            mid_y = cy + dj * arm_length * 0.5
            bpy.ops.mesh.primitive_cylinder_add(
                radius=arm_radius, depth=arm_length,
                location=(mid_x, mid_y, cz),
            )
            arm = bpy.context.active_object
            arm.name = f"Dendrite_{cluster[0]}x{cluster[1]}_{name_suffix}"
            if di != 0:
                # rotate 90° about Y so cylinder points along X
                arm.rotation_euler = (0.0, math.pi / 2, 0.0)
            else:
                # rotate 90° about X so cylinder points along Y
                arm.rotation_euler = (math.pi / 2, 0.0, 0.0)
            arm.data.materials.clear()
            arm.data.materials.append(seed_mat)
            for c in arm.users_collection:
                c.objects.unlink(arm)
            seed_coll.objects.link(arm)
            # start invisible at f0+24 (when seeds appear), fade in with the
            # ripening anchor, then grow to full length over the dendrite
            # window.
            _key_visibility(arm, f0 + 24, False)
            _key_visibility(arm, f_ripen + 4, False)
            _key_scale(arm, f_ripen + 4, Vector((1.0, 1.0, 0.05)))
            _key_visibility(arm, f_dendrites, True)
            _key_scale(arm, f_dendrites, Vector((1.0, 1.0, 1.0)))


# ── Public API ──────────────────────────────────────────────────────────────


def setup_scene() -> dict:
    """Build the supercell, materials, camera, lighting. Returns scene info."""
    _clear_scene()
    coll = _import_initial_structure()
    _setup_materials()
    _white_world()

    minp, maxp, center, extent = _bbox(coll)
    cam = _setup_camera(center, extent)
    _setup_lighting(center, extent)

    scene = bpy.context.scene
    # Blender 5.1 collapsed "Eevee Next" back into "BLENDER_EEVEE"
    for engine_id in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine_id
            break
        except TypeError:
            continue
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.fps = FPS
    scene.frame_start = 0
    scene.frame_end = TOTAL_FRAMES - 1
    scene.frame_set(0)
    if hasattr(scene, "eevee"):
        if hasattr(scene.eevee, "taa_render_samples"):
            scene.eevee.taa_render_samples = 32
        if hasattr(scene.eevee, "use_gtao"):
            scene.eevee.use_gtao = True
        if hasattr(scene.eevee, "use_bloom"):
            scene.eevee.use_bloom = False  # Nature avoids decorative bloom

    return {
        "n_objects_in_crystal": len(coll.objects),
        "extent": extent,
        "center": list(center),
        "frame_end": TOTAL_FRAMES - 1,
    }


def animate_all() -> dict:
    coll = bpy.data.collections[COLLECTION_NAME]
    zr, o, bonds = _atom_lists(coll)
    o_migrate, o_fade = _classify_oxygens(o)

    cam = bpy.data.objects["Fig10Cam"]
    minp, maxp, center, extent = _bbox(coll)

    _act1_camera_rotation(cam, center, extent)
    _act2_phonon_wave(zr, o)
    _act3_topotactic(zr, o_migrate, o_fade, coll, center)

    # Bonds: keep visible through Act 1 + 2 (they reflect the parent fluorite
    # geometry), then fade out at the start of Act 3 so the migration doesn't
    # leave dangling cylinders. The post-rocksalt structure is shown
    # bond-free, which matches how Nature panels often present transformed
    # phases (the Fig. 10 panel b sketch itself omits bonds in the rocksalt
    # half).
    for bond in bonds:
        _key_visibility(bond, ACT3[0] - 1, True)
        _key_visibility(bond, ACT3[0] + 24, False)

    _act5_mesoscale_zoom(cam, center, extent, coll)

    # Set interpolation to Bezier on every fcurve so motion eases naturally.
    # Blender 5.x reorganised actions into slots/layers; walk both shapes.
    def _all_fcurves(action):
        if hasattr(action, "fcurves"):
            try:
                return list(action.fcurves)
            except Exception:
                pass
        out = []
        for layer in getattr(action, "layers", []):
            for strip in getattr(layer, "strips", []):
                for cb in getattr(strip, "channelbags", []):
                    out.extend(getattr(cb, "fcurves", []))
        return out

    for action in bpy.data.actions:
        for fcurve in _all_fcurves(action):
            for kp in fcurve.keyframe_points:
                kp.interpolation = "BEZIER"

    return {
        "zr_count": len(zr),
        "o_total": len(o),
        "o_migrating": len(o_migrate),
        "o_fading": len(o_fade),
    }


def render(frame_start: int | None = None,
           frame_end: int | None = None,
           output_dir: str = "/Users/ricfulop/voltivity/sci-viz-mcp/output/anim_fig10/frames",
           prefix: str = "frame_") -> dict:
    scene = bpy.context.scene
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.color_mode = "RGBA"

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(Path(output_dir) / prefix)

    fs = frame_start if frame_start is not None else 0
    fe = frame_end if frame_end is not None else TOTAL_FRAMES - 1

    rendered = []
    for f in range(fs, fe + 1):
        scene.frame_set(f)
        scene.render.filepath = str(Path(output_dir) / f"{prefix}{f:04d}")
        bpy.ops.render.render(write_still=True)
        rendered.append(scene.render.filepath + ".png")

    return {
        "frames_rendered": len(rendered),
        "first": rendered[0] if rendered else None,
        "last": rendered[-1] if rendered else None,
        "output_dir": output_dir,
    }


if __name__ == "__main__":
    print(setup_scene())
    print(animate_all())
    print(render())
