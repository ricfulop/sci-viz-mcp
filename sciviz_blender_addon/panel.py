"""Sidebar panel for the SciViz add-on.

Exposes the four operators as buttons in View3D > N-panel > SciViz so the
add-on is useful by hand even when no MCP client is connected.
"""

from __future__ import annotations

import bpy
from bpy.types import Panel


class SCIVIZ_PT_main(Panel):
    bl_idname = "SCIVIZ_PT_main"
    bl_label = "SciViz"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "SciViz"

    def draw(self, context):
        layout = self.layout
        props = context.scene.sciviz

        col = layout.column(align=True)
        col.label(text="Crystal import", icon="MESH_UVSPHERE")
        col.prop(props, "crystal_filepath", text="")
        row = col.row(align=True)
        row.prop(props, "atom_scale")
        row.prop(props, "bond_radius")
        row = col.row(align=True)
        row.prop(props, "bond_cutoff")
        row.prop(props, "only_unlike_bonds", text="hetero only")
        op = col.operator("sciviz.import_crystal", icon="IMPORT")
        op.filepath = props.crystal_filepath
        op.atom_scale = props.atom_scale
        op.bond_radius = props.bond_radius
        op.bond_cutoff = props.bond_cutoff
        op.only_unlike_bonds = props.only_unlike_bonds

        layout.separator()

        col = layout.column(align=True)
        col.label(text="Render preset", icon="SHADING_RENDERED")
        col.prop(props, "preset", text="")
        col.prop(props, "transparent_background")
        op = col.operator("sciviz.apply_preset", icon="WORLD")
        op.preset = props.preset
        op.transparent_background = props.transparent_background

        layout.separator()

        col = layout.column(align=True)
        col.label(text="Render HQ", icon="RENDER_STILL")
        col.prop(props, "render_filepath", text="")
        row = col.row(align=True)
        row.prop(props, "width")
        row.prop(props, "height")
        col.prop(props, "samples")
        op = col.operator("sciviz.render_hq", icon="RENDER_RESULT")
        op.filepath = props.render_filepath
        op.width = props.width
        op.height = props.height
        op.samples = props.samples


_classes = (SCIVIZ_PT_main,)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
