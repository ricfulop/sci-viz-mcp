"""Scene-level properties for the SciViz panel.

Each property mirrors a parameter on one of the operators so the panel
can offer a single set of inputs that the buttons read from.
"""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


PRESET_ITEMS = (
    ("WHITE_CLEAN", "White Clean", "Pure white background, ortho camera, AO on, no shadows"),
    ("SOFT_SHADOW", "Soft Shadow", "White background with soft shadows, ortho camera"),
    ("PERSPECTIVE_DEPTH", "Perspective Depth", "Light gray background, perspective camera, shadows + AO"),
    ("DARK_PRESENTATION", "Dark Presentation", "Near-black background for slide decks"),
)


class SciVizProps(PropertyGroup):
    crystal_filepath: StringProperty(
        name="Structure file",
        description="CIF / POSCAR / XYZ to import",
        subtype="FILE_PATH",
        default="",
    )
    bond_cutoff: FloatProperty(
        name="Bond cutoff (Å)",
        description="Maximum distance to draw a bond between two atoms",
        default=3.0,
        min=0.5,
        max=10.0,
    )
    atom_scale: FloatProperty(
        name="Atom radius",
        description="Sphere radius for each atom",
        default=0.4,
        min=0.05,
        max=2.0,
    )
    bond_radius: FloatProperty(
        name="Bond radius",
        description="Cylinder radius for bonds",
        default=0.08,
        min=0.01,
        max=0.5,
    )
    only_unlike_bonds: BoolProperty(
        name="Heteroatomic bonds only",
        description="Skip bonds between atoms of the same element (typical for ionic crystals)",
        default=True,
    )

    preset: EnumProperty(
        name="Preset",
        items=PRESET_ITEMS,
        default="WHITE_CLEAN",
    )
    transparent_background: BoolProperty(
        name="Transparent background",
        default=False,
    )

    render_filepath: StringProperty(
        name="Output file",
        description="Where to save the Cycles render",
        subtype="FILE_PATH",
        default="//sciviz_render.png",
    )
    width: IntProperty(name="Width", default=2400, min=64, max=8192)
    height: IntProperty(name="Height", default=1800, min=64, max=8192)
    samples: IntProperty(name="Cycles samples", default=256, min=1, max=4096)


_classes = (SciVizProps,)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.sciviz = bpy.props.PointerProperty(type=SciVizProps)


def unregister() -> None:
    del bpy.types.Scene.sciviz
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
