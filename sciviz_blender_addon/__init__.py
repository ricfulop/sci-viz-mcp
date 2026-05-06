"""SciViz Blender add-on.

Registers a small set of `bpy.ops.sciviz.*` operators for scientific figure
work (crystal-structure import, publication render presets, high-quality
Cycles renders, 3D annotations) plus a sidebar panel under the "SciViz"
tab in the 3D View N-panel.

The add-on is transport-agnostic: any MCP client (the official Blender
Foundation MCP server, the community ahujasid blender-mcp, Cursor, Claude
Desktop, ...) can drive it through Blender's normal operator surface, e.g.

    bpy.ops.sciviz.import_crystal(filepath="/path/structure.cif")
    bpy.ops.sciviz.apply_preset(preset='SOFT_SHADOW')
    bpy.ops.sciviz.render_hq(filepath="/tmp/out.png", width=2400, height=1800)

Manual users get the same operators as buttons in the SciViz sidebar.
"""

from __future__ import annotations

bl_info = {
    "name": "SciViz",
    "author": "voltivity sci-viz-mcp",
    "version": (0, 2, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > SciViz",
    "description": "Crystal import, publication presets, and HQ Cycles renders for scientific figures",
    "category": "3D View",
}

import importlib

from . import operators, panel, properties

_modules = (properties, operators, panel)


def register() -> None:
    for mod in _modules:
        importlib.reload(mod)
    for mod in _modules:
        mod.register()


def unregister() -> None:
    for mod in reversed(_modules):
        mod.unregister()


if __name__ == "__main__":
    register()
