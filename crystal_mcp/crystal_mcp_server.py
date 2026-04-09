#!/usr/bin/env python3
"""
crystal_mcp_server.py
MCP server for crystal structure visualization using ASE + pymatgen.

Replaces VESTA with a programmatic, reproducible workflow for generating
publication-quality lattice diagrams, unit cell renderings, and TikZ exports.

Implements MCP JSON-RPC 2.0 over stdio (protocolVersion 2024-11-05).
"""

import json
import sys
import os
import traceback
import hashlib
from pathlib import Path

_THIS_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_THIS_DIR))

import numpy as np

from renderers import (
    render_lattice_projection,
    render_unit_cell,
    render_compare_structures,
)
from tikz_export import export_tikz

sys.path.insert(0, str(_THIS_DIR.parent))
from preview.notify import notify_preview

# ── Lazy imports for heavy libs ──────────────────────────────────────────────

_ase = None
_pymatgen = None
_spglib = None


def _get_ase():
    global _ase
    if _ase is None:
        import ase.io
        import ase.build
        _ase = ase
    return _ase


def _get_pymatgen():
    global _pymatgen
    if _pymatgen is None:
        from pymatgen.core import Structure
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
        import pymatgen
        _pymatgen = pymatgen
    return _pymatgen


def _get_spglib():
    global _spglib
    if _spglib is None:
        import spglib
        _spglib = spglib
    return _spglib


# ── State: loaded structures keyed by handle ─────────────────────────────────

_structures = {}  # handle -> {"ase": Atoms, "pmg": Structure, "path": str}

OUTPUT_DIR = Path(os.environ.get(
    "CRYSTAL_MCP_OUTPUT_DIR",
    str(Path.home() / "voltivity" / "sci-viz-mcp" / "output"),
))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _handle_for(path_or_id: str) -> str:
    return hashlib.sha1(path_or_id.encode()).hexdigest()[:12]


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

def handle_import_structure(args):
    """Load CIF, POSCAR, XYZ, or other ASE-readable file."""
    file_path = args["file_path"]
    fmt = args.get("format")

    ase_mod = _get_ase()
    import ase.io

    atoms = ase.io.read(file_path, format=fmt)
    handle = _handle_for(file_path)

    from pymatgen.core import Structure
    from pymatgen.io.ase import AseAtomsAdaptor
    pmg_struct = AseAtomsAdaptor.get_structure(atoms)

    _structures[handle] = {
        "ase": atoms,
        "pmg": pmg_struct,
        "path": file_path,
    }

    cell = atoms.cell.cellpar().tolist()
    symbols = list(atoms.get_chemical_symbols())
    unique = sorted(set(symbols))

    return {
        "handle": handle,
        "formula": atoms.get_chemical_formula(),
        "n_atoms": len(atoms),
        "cell_params": {
            "a": round(cell[0], 4), "b": round(cell[1], 4), "c": round(cell[2], 4),
            "alpha": round(cell[3], 2), "beta": round(cell[4], 2), "gamma": round(cell[5], 2),
        },
        "species": unique,
        "volume": round(float(atoms.cell.volume), 4),
    }


def handle_build_supercell(args):
    """Build NxMxL supercell from loaded structure."""
    handle = args["handle"]
    repeats = args.get("repeats", [2, 2, 2])

    if handle not in _structures:
        raise ValueError(f"No structure loaded with handle: {handle}")

    import ase.build
    from pymatgen.io.ase import AseAtomsAdaptor

    atoms = _structures[handle]["ase"].copy()
    atoms = atoms.repeat(repeats)

    new_handle = handle + f"_{'x'.join(map(str, repeats))}"
    pmg_struct = AseAtomsAdaptor.get_structure(atoms)
    _structures[new_handle] = {
        "ase": atoms,
        "pmg": pmg_struct,
        "path": f"supercell of {_structures[handle]['path']}",
    }

    return {
        "handle": new_handle,
        "formula": atoms.get_chemical_formula(),
        "n_atoms": len(atoms),
        "repeats": repeats,
    }


def handle_create_defect(args):
    """Create point defect: vacancy, substitution, or interstitial."""
    handle = args["handle"]
    defect_type = args["defect_type"]
    site_index = args.get("site_index")
    species = args.get("species")
    position = args.get("position")

    if handle not in _structures:
        raise ValueError(f"No structure loaded with handle: {handle}")

    import ase.build
    from pymatgen.io.ase import AseAtomsAdaptor

    atoms = _structures[handle]["ase"].copy()

    if defect_type == "vacancy":
        if site_index is None:
            raise ValueError("site_index required for vacancy")
        removed = atoms[site_index].symbol
        del atoms[site_index]
        info = {"removed_species": removed, "removed_index": site_index}

    elif defect_type == "substitution":
        if site_index is None or species is None:
            raise ValueError("site_index and species required for substitution")
        original = atoms[site_index].symbol
        atoms[site_index].symbol = species
        info = {"original": original, "substituted": species, "index": site_index}

    elif defect_type == "interstitial":
        if position is None or species is None:
            raise ValueError("position and species required for interstitial")
        from ase import Atom
        atoms.append(Atom(species, position))
        info = {"species": species, "position": position}

    else:
        raise ValueError(f"Unknown defect_type: {defect_type}")

    new_handle = handle + f"_{defect_type}"
    pmg_struct = AseAtomsAdaptor.get_structure(atoms)
    _structures[new_handle] = {
        "ase": atoms,
        "pmg": pmg_struct,
        "path": f"{defect_type} in {_structures[handle]['path']}",
    }

    return {
        "handle": new_handle,
        "n_atoms": len(atoms),
        "defect_type": defect_type,
        **info,
    }


def handle_get_symmetry(args):
    """Return space group, Wyckoff positions, equivalent sites."""
    handle = args["handle"]
    symprec = args.get("symprec", 0.01)

    if handle not in _structures:
        raise ValueError(f"No structure loaded with handle: {handle}")

    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    pmg = _structures[handle]["pmg"]
    sga = SpacegroupAnalyzer(pmg, symprec=symprec)

    sym_data = sga.get_symmetry_dataset()
    wyckoff = sym_data.get("wyckoffs", [])

    sites = []
    for i, site in enumerate(pmg):
        sites.append({
            "index": i,
            "species": str(site.specie),
            "frac_coords": [round(c, 5) for c in site.frac_coords.tolist()],
            "wyckoff": wyckoff[i] if i < len(wyckoff) else None,
        })

    return {
        "space_group_symbol": sga.get_space_group_symbol(),
        "space_group_number": sga.get_space_group_number(),
        "crystal_system": sga.get_crystal_system(),
        "point_group": sga.get_point_group_symbol(),
        "sites": sites,
    }


def handle_render_lattice(args):
    """Render 2D lattice projection to image file."""
    handle = args["handle"]
    if handle not in _structures:
        raise ValueError(f"No structure loaded with handle: {handle}")

    output_file = args.get("output_file")
    if not output_file:
        output_file = str(OUTPUT_DIR / f"{handle}_lattice.pdf")

    result_path = render_lattice_projection(
        _structures[handle]["ase"],
        output_file=output_file,
        projection=args.get("projection", "001"),
        style=args.get("style", "ball_and_stick"),
        atom_colors=args.get("atom_colors"),
        atom_radii=args.get("atom_radii"),
        bond_cutoff=args.get("bond_cutoff", 3.0),
        show_cell=args.get("show_cell", True),
        show_labels=args.get("show_labels", False),
        background=args.get("background", "white"),
        figsize=args.get("figsize"),
        dpi=args.get("dpi", 300),
        title=args.get("title"),
        style_preset=args.get("style_preset", "aps"),
    )

    notify_preview(result_path, "crystal.render_lattice", args, "crystal_mcp")
    return {"output_file": result_path, "handle": handle}


def handle_render_unit_cell(args):
    """Render annotated unit cell with Wyckoff labels and bond lengths."""
    handle = args["handle"]
    if handle not in _structures:
        raise ValueError(f"No structure loaded with handle: {handle}")

    output_file = args.get("output_file")
    if not output_file:
        output_file = str(OUTPUT_DIR / f"{handle}_unit_cell.pdf")

    result_path = render_unit_cell(
        _structures[handle]["ase"],
        _structures[handle]["pmg"],
        output_file=output_file,
        projection=args.get("projection", "001"),
        show_wyckoff=args.get("show_wyckoff", True),
        show_bond_lengths=args.get("show_bond_lengths", True),
        show_lattice_params=args.get("show_lattice_params", True),
        atom_colors=args.get("atom_colors"),
        atom_radii=args.get("atom_radii"),
        dpi=args.get("dpi", 300),
        title=args.get("title"),
        style_preset=args.get("style_preset", "aps"),
    )

    notify_preview(result_path, "crystal.render_unit_cell", args, "crystal_mcp")
    return {"output_file": result_path, "handle": handle}


def handle_compare_structures(args):
    """Side-by-side rendering of two structures."""
    handle_a = args["handle_a"]
    handle_b = args["handle_b"]

    if handle_a not in _structures:
        raise ValueError(f"No structure loaded with handle: {handle_a}")
    if handle_b not in _structures:
        raise ValueError(f"No structure loaded with handle: {handle_b}")

    output_file = args.get("output_file")
    if not output_file:
        output_file = str(OUTPUT_DIR / f"{handle_a}_vs_{handle_b}.pdf")

    result_path = render_compare_structures(
        _structures[handle_a]["ase"],
        _structures[handle_b]["ase"],
        output_file=output_file,
        label_a=args.get("label_a", "Structure A"),
        label_b=args.get("label_b", "Structure B"),
        projection=args.get("projection", "001"),
        arrow_label=args.get("arrow_label"),
        atom_colors=args.get("atom_colors"),
        dpi=args.get("dpi", 300),
        style_preset=args.get("style_preset", "aps"),
    )

    notify_preview(result_path, "crystal.compare_structures", args, "crystal_mcp")
    return {"output_file": result_path}


def handle_export_tikz(args):
    """Export TikZ code for a lattice diagram."""
    handle = args["handle"]
    if handle not in _structures:
        raise ValueError(f"No structure loaded with handle: {handle}")

    output_file = args.get("output_file")
    if not output_file:
        output_file = str(OUTPUT_DIR / f"{handle}_lattice.tex")

    result_path = export_tikz(
        _structures[handle]["ase"],
        output_file=output_file,
        projection=args.get("projection", "001"),
        scale=args.get("scale", 1.0),
        atom_colors=args.get("atom_colors"),
        atom_radii=args.get("atom_radii"),
        show_cell=args.get("show_cell", True),
        show_bonds=args.get("show_bonds", True),
        bond_cutoff=args.get("bond_cutoff", 3.0),
    )

    notify_preview(result_path, "crystal.export_tikz", args, "crystal_mcp")
    return {"output_file": result_path, "handle": handle}


def handle_list_structures(args):
    """List all currently loaded structures."""
    result = []
    for h, data in _structures.items():
        atoms = data["ase"]
        result.append({
            "handle": h,
            "formula": atoms.get_chemical_formula(),
            "n_atoms": len(atoms),
            "path": data["path"],
        })
    return {"structures": result}


# ── Tool registry ────────────────────────────────────────────────────────────

TOOLS = {
    "crystal.import_structure": {
        "handler": handle_import_structure,
        "description": "Load a crystal structure from CIF, POSCAR, XYZ, or other ASE-readable format. Returns a handle for subsequent operations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to structure file (CIF, POSCAR, XYZ, etc.)"},
                "format": {"type": "string", "description": "Optional format hint (cif, vasp, xyz, etc.). Auto-detected if omitted."},
            },
            "required": ["file_path"],
        },
    },
    "crystal.build_supercell": {
        "handler": handle_build_supercell,
        "description": "Build an NxMxL supercell from a loaded structure. Returns a new handle.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string", "description": "Handle from import_structure"},
                "repeats": {
                    "type": "array", "items": {"type": "integer"},
                    "description": "Repetitions along a, b, c (default [2,2,2])",
                },
            },
            "required": ["handle"],
        },
    },
    "crystal.create_defect": {
        "handler": handle_create_defect,
        "description": "Create a point defect (vacancy, substitution, or interstitial) in a loaded structure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "defect_type": {
                    "type": "string",
                    "enum": ["vacancy", "substitution", "interstitial"],
                    "description": "Type of point defect",
                },
                "site_index": {"type": "integer", "description": "Atom index for vacancy/substitution"},
                "species": {"type": "string", "description": "Element symbol for substitution/interstitial"},
                "position": {
                    "type": "array", "items": {"type": "number"},
                    "description": "Cartesian position [x,y,z] for interstitial",
                },
            },
            "required": ["handle", "defect_type"],
        },
    },
    "crystal.get_symmetry": {
        "handler": handle_get_symmetry,
        "description": "Return space group, Wyckoff positions, and equivalent sites for a loaded structure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "symprec": {"type": "number", "description": "Symmetry precision (default 0.01)"},
            },
            "required": ["handle"],
        },
    },
    "crystal.render_lattice": {
        "handler": handle_render_lattice,
        "description": "Render a 2D lattice projection to PDF/PNG/SVG. Configurable projection axis, atom styles, bond display.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "output_file": {"type": "string", "description": "Output path (default: auto-generated in output dir)"},
                "projection": {"type": "string", "description": "Projection direction: '001', '110', '111', etc."},
                "style": {"type": "string", "enum": ["ball_and_stick", "space_filling", "wireframe"]},
                "atom_colors": {"type": "object", "description": "Map of element symbol to hex color, e.g. {\"Zr\": \"#4a86c8\"}"},
                "atom_radii": {"type": "object", "description": "Map of element symbol to radius in Angstroms"},
                "bond_cutoff": {"type": "number", "description": "Max bond length in Angstroms (default 3.0)"},
                "show_cell": {"type": "boolean"},
                "show_labels": {"type": "boolean"},
                "background": {"type": "string", "description": "Background color (default white)"},
                "figsize": {"type": "array", "items": {"type": "number"}, "description": "[width, height] in inches"},
                "dpi": {"type": "integer"},
                "title": {"type": "string"},
                "style_preset": {"type": "string", "enum": ["aps", "nature"], "description": "Journal style preset (default: aps). 'aps' = serif/STIX/inward ticks, 'nature' = sans-serif/Helvetica/outward ticks"},
            },
            "required": ["handle"],
        },
    },
    "crystal.render_unit_cell": {
        "handler": handle_render_unit_cell,
        "description": "Render an annotated unit cell with Wyckoff labels, bond-length annotations, and lattice parameter callouts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "output_file": {"type": "string"},
                "projection": {"type": "string"},
                "show_wyckoff": {"type": "boolean"},
                "show_bond_lengths": {"type": "boolean"},
                "show_lattice_params": {"type": "boolean"},
                "atom_colors": {"type": "object"},
                "atom_radii": {"type": "object"},
                "dpi": {"type": "integer"},
                "title": {"type": "string"},
                "style_preset": {"type": "string", "enum": ["aps", "nature"], "description": "Journal style preset (default: aps)"},
            },
            "required": ["handle"],
        },
    },
    "crystal.compare_structures": {
        "handler": handle_compare_structures,
        "description": "Side-by-side rendering of two structures (e.g., fluorite vs rocksalt transformation).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle_a": {"type": "string"},
                "handle_b": {"type": "string"},
                "output_file": {"type": "string"},
                "label_a": {"type": "string"},
                "label_b": {"type": "string"},
                "projection": {"type": "string"},
                "arrow_label": {"type": "string", "description": "Label on the arrow between structures"},
                "atom_colors": {"type": "object"},
                "dpi": {"type": "integer"},
                "style_preset": {"type": "string", "enum": ["aps", "nature"], "description": "Journal style preset (default: aps)"},
            },
            "required": ["handle_a", "handle_b"],
        },
    },
    "crystal.export_tikz": {
        "handler": handle_export_tikz,
        "description": "Generate TikZ/PGF code for a lattice diagram, compatible with LaTeX workflows.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "output_file": {"type": "string"},
                "projection": {"type": "string"},
                "scale": {"type": "number", "description": "TikZ scale factor (default 1.0)"},
                "atom_colors": {"type": "object"},
                "atom_radii": {"type": "object"},
                "show_cell": {"type": "boolean"},
                "show_bonds": {"type": "boolean"},
                "bond_cutoff": {"type": "number"},
            },
            "required": ["handle"],
        },
    },
    "crystal.list_structures": {
        "handler": handle_list_structures,
        "description": "List all currently loaded crystal structures with their handles.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
}


# ── MCP protocol ─────────────────────────────────────────────────────────────

def handle_initialize(params):
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "crystal_mcp", "version": "0.1.0"},
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
