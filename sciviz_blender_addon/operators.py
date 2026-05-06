"""Operators registered under `bpy.ops.sciviz.*`.

Each operator is independently usable from:
  * the SciViz sidebar panel (View3D > N > SciViz)
  * arbitrary Python in Blender's scripting tab
  * any MCP client driving Blender via the official Blender Foundation MCP
    server (or the community ahujasid blender-mcp), which can call
    `bpy.ops.sciviz.<name>(...)` through its execute-Python surface.

All operators write a `RESULT:{json}` line to stdout so callers that scrape
Blender's text output (some MCP servers do) can parse a structured payload.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator
from mathutils import Vector

from .cpk_colors import color_for
from .preview_notify import notify_preview
from .properties import PRESET_ITEMS


# ── helpers ─────────────────────────────────────────────────────────────────


def _emit_result(payload: dict) -> None:
    print("RESULT:" + json.dumps(payload))


def _get_or_make_collection(name: str, clear: bool = False) -> bpy.types.Collection:
    if name in bpy.data.collections:
        coll = bpy.data.collections[name]
        if clear:
            for obj in list(coll.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
        return coll
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    return coll


def _move_to_collection(obj: bpy.types.Object, coll: bpy.types.Collection) -> None:
    for c in obj.users_collection:
        c.objects.unlink(obj)
    coll.objects.link(obj)


def _ensure_material(name: str, color: tuple[float, float, float, float],
                     metallic: float = 0.1, roughness: float = 0.3) -> bpy.types.Material:
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = color
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = metallic
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = roughness
    return mat


def _read_structure(filepath: str):
    """Return (positions, symbols, formula). Tries ASE first, then pymatgen."""
    try:
        import ase.io  # type: ignore
        atoms = ase.io.read(filepath)
        return (
            list(atoms.get_positions()),
            list(atoms.get_chemical_symbols()),
            atoms.get_chemical_formula(),
        )
    except ImportError:
        pass
    except Exception as e:
        raise RuntimeError(f"ASE failed to read {filepath}: {e}")

    try:
        from pymatgen.core import Structure  # type: ignore
        s = Structure.from_file(filepath)
        positions = [tuple(site.coords) for site in s.sites]
        symbols = [site.specie.symbol for site in s.sites]
        return positions, symbols, s.composition.reduced_formula
    except ImportError as e:
        raise ImportError(
            "Neither ASE nor pymatgen is available in Blender's bundled Python. "
            "Install with: <blender>/python/bin/python3 -m pip install ase numpy"
        ) from e


# ── sciviz.import_crystal ───────────────────────────────────────────────────


class SCIVIZ_OT_import_crystal(Operator):
    """Import a crystal structure (CIF / POSCAR / XYZ) as a ball-and-stick model."""

    bl_idname = "sciviz.import_crystal"
    bl_label = "Import Crystal"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    bond_cutoff: FloatProperty(default=3.0, min=0.5, max=10.0)
    atom_scale: FloatProperty(default=0.4, min=0.05, max=2.0)
    bond_radius: FloatProperty(default=0.08, min=0.01, max=0.5)
    only_unlike_bonds: BoolProperty(default=True)
    collection_name: StringProperty(default="Crystal")

    def invoke(self, context, event):
        props = context.scene.sciviz
        if not self.filepath and props.crystal_filepath:
            self.filepath = bpy.path.abspath(props.crystal_filepath)
            self.bond_cutoff = props.bond_cutoff
            self.atom_scale = props.atom_scale
            self.bond_radius = props.bond_radius
            self.only_unlike_bonds = props.only_unlike_bonds
        return self.execute(context)

    def execute(self, context):
        path = bpy.path.abspath(self.filepath) if self.filepath else ""
        if not path or not os.path.isfile(path):
            self.report({"ERROR"}, f"Structure file not found: {self.filepath!r}")
            return {"CANCELLED"}

        try:
            positions, symbols, formula = _read_structure(path)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        coll = _get_or_make_collection(self.collection_name, clear=True)

        for i, (pos, sym) in enumerate(zip(positions, symbols)):
            bpy.ops.mesh.primitive_uv_sphere_add(
                radius=self.atom_scale,
                location=tuple(pos),
                segments=24,
                ring_count=16,
            )
            obj = context.active_object
            obj.name = f"{sym}_{i}"
            for face in obj.data.polygons:
                face.use_smooth = True
            mat = _ensure_material(f"Mat_{sym}", color_for(sym))
            obj.data.materials.clear()
            obj.data.materials.append(mat)
            _move_to_collection(obj, coll)

        bond_mat = _ensure_material(
            "Mat_Bond", (0.6, 0.6, 0.6, 1.0), metallic=0.3, roughness=0.5
        )
        bond_count = 0
        n = len(positions)
        for i in range(n):
            for j in range(i + 1, n):
                if self.only_unlike_bonds and symbols[i] == symbols[j]:
                    continue
                pi, pj = Vector(positions[i]), Vector(positions[j])
                diff = pj - pi
                length = diff.length
                if length >= self.bond_cutoff or length < 1e-3:
                    continue
                bpy.ops.mesh.primitive_cylinder_add(
                    radius=self.bond_radius,
                    depth=length,
                    location=tuple((pi + pj) / 2.0),
                )
                bond = context.active_object
                bond.name = f"Bond_{i}_{j}"
                rot = Vector((0.0, 0.0, 1.0)).rotation_difference(diff.normalized())
                bond.rotation_euler = rot.to_euler()
                for face in bond.data.polygons:
                    face.use_smooth = True
                bond.data.materials.clear()
                bond.data.materials.append(bond_mat)
                _move_to_collection(bond, coll)
                bond_count += 1

        result = {
            "atoms_created": n,
            "bonds_created": bond_count,
            "formula": formula,
            "collection": self.collection_name,
            "source": path,
        }
        _emit_result(result)
        self.report({"INFO"}, f"Imported {n} atoms, {bond_count} bonds ({formula})")
        return {"FINISHED"}


# ── sciviz.apply_preset ─────────────────────────────────────────────────────


_PRESETS: dict[str, dict] = {
    "WHITE_CLEAN": {
        "bg_color": (1.0, 1.0, 1.0, 1.0),
        "ao": True,
        "shadow": False,
        "camera": "ORTHO",
    },
    "SOFT_SHADOW": {
        "bg_color": (1.0, 1.0, 1.0, 1.0),
        "ao": True,
        "shadow": True,
        "camera": "ORTHO",
    },
    "PERSPECTIVE_DEPTH": {
        "bg_color": (0.95, 0.95, 0.95, 1.0),
        "ao": True,
        "shadow": True,
        "camera": "PERSP",
    },
    "DARK_PRESENTATION": {
        "bg_color": (0.05, 0.05, 0.05, 1.0),
        "ao": True,
        "shadow": True,
        "camera": "PERSP",
    },
}


class SCIVIZ_OT_apply_preset(Operator):
    """Apply a publication-quality render preset (background, camera, color management)."""

    bl_idname = "sciviz.apply_preset"
    bl_label = "Apply SciViz Preset"
    bl_options = {"REGISTER", "UNDO"}

    preset: EnumProperty(items=PRESET_ITEMS, default="WHITE_CLEAN")
    transparent_background: BoolProperty(default=False)

    def invoke(self, context, event):
        props = context.scene.sciviz
        self.preset = props.preset
        self.transparent_background = props.transparent_background
        return self.execute(context)

    def execute(self, context):
        cfg = _PRESETS.get(self.preset, _PRESETS["WHITE_CLEAN"])
        scene = context.scene

        scene.render.engine = "CYCLES"
        scene.cycles.samples = 128
        scene.cycles.use_denoising = True
        scene.render.film_transparent = bool(self.transparent_background)

        world = scene.world
        if world is None:
            world = bpy.data.worlds.new("World")
            scene.world = world
        world.use_nodes = True
        bg_node = world.node_tree.nodes.get("Background")
        if bg_node is not None:
            bg_node.inputs["Color"].default_value = cfg["bg_color"]
            bg_node.inputs["Strength"].default_value = 1.0

        for obj in scene.objects:
            if obj.type == "CAMERA":
                cam = obj.data
                cam.type = cfg["camera"]
                if cam.type == "ORTHO":
                    cam.ortho_scale = 12
                break

        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.view_settings.gamma = 1.0

        result = {
            "preset": self.preset,
            "transparent_background": bool(self.transparent_background),
        }
        _emit_result(result)
        self.report({"INFO"}, f"Applied preset {self.preset}")
        return {"FINISHED"}


# ── sciviz.render_hq ────────────────────────────────────────────────────────


class SCIVIZ_OT_render_hq(Operator):
    """Render the current scene with Cycles at the requested resolution and notify the live preview dashboard."""

    bl_idname = "sciviz.render_hq"
    bl_label = "Render HQ (Cycles)"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH", default="//sciviz_render.png")
    width: IntProperty(default=2400, min=64, max=8192)
    height: IntProperty(default=1800, min=64, max=8192)
    samples: IntProperty(default=256, min=1, max=4096)

    def invoke(self, context, event):
        props = context.scene.sciviz
        self.filepath = props.render_filepath
        self.width = props.width
        self.height = props.height
        self.samples = props.samples
        return self.execute(context)

    def execute(self, context):
        scene = context.scene
        scene.render.engine = "CYCLES"
        scene.cycles.samples = self.samples
        scene.cycles.use_denoising = True
        scene.render.resolution_x = self.width
        scene.render.resolution_y = self.height
        scene.render.resolution_percentage = 100

        out = bpy.path.abspath(self.filepath)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        scene.render.filepath = out
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_depth = "16"

        bpy.ops.render.render(write_still=True)

        notify_preview(
            output_file=out,
            tool_name="sciviz.render_hq",
            params={"width": self.width, "height": self.height, "samples": self.samples},
        )

        result = {
            "output_file": out,
            "width": self.width,
            "height": self.height,
            "samples": self.samples,
        }
        _emit_result(result)
        self.report({"INFO"}, f"Rendered → {out}")
        return {"FINISHED"}


# ── sciviz.add_annotation_3d ────────────────────────────────────────────────


def _hex_to_rgba(hex_color: str) -> tuple[float, float, float, float]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (0.2, 0.2, 0.2, 1.0)
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return (r, g, b, 1.0)


class SCIVIZ_OT_add_annotation_3d(Operator):
    """Add a 3D text label at the given world position."""

    bl_idname = "sciviz.add_annotation_3d"
    bl_label = "Add 3D Annotation"
    bl_options = {"REGISTER", "UNDO"}

    text: StringProperty(default="label")
    location_x: FloatProperty(default=0.0)
    location_y: FloatProperty(default=0.0)
    location_z: FloatProperty(default=0.0)
    size: FloatProperty(default=0.3, min=0.01, max=10.0)
    color: StringProperty(default="#333333")
    target_collection: StringProperty(default="Crystal")

    def execute(self, context):
        bpy.ops.object.text_add(
            location=(self.location_x, self.location_y, self.location_z)
        )
        obj = context.active_object
        obj.data.body = self.text
        obj.data.size = self.size
        obj.data.align_x = "CENTER"
        obj.data.align_y = "CENTER"
        mat = _ensure_material(
            f"Mat_Label_{self.text[:8]}",
            _hex_to_rgba(self.color),
            metallic=0.0,
            roughness=0.5,
        )
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        if self.target_collection and self.target_collection in bpy.data.collections:
            _move_to_collection(obj, bpy.data.collections[self.target_collection])
        result = {
            "text": self.text,
            "position": [self.location_x, self.location_y, self.location_z],
        }
        _emit_result(result)
        return {"FINISHED"}


# ── registration ────────────────────────────────────────────────────────────


_classes = (
    SCIVIZ_OT_import_crystal,
    SCIVIZ_OT_apply_preset,
    SCIVIZ_OT_render_hq,
    SCIVIZ_OT_add_annotation_3d,
)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
