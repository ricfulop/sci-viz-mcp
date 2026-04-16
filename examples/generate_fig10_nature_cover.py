#!/usr/bin/env python3
"""
Figure 10 — "Anatomy of Condensation" (Nature Cover style)

Strict 2×2 grid:
  (a) Acoustic Blueprint      — pymatgen → Blender (volumetric sine + gold vacancies)
  (b) Topotactic Collapse      — pymatgen → Blender (polyhedra + 2DEG cloud)
  (c) Zone Folding             — matplotlib (dispersion + Raman, shared Freq Y-axis)
  (d) Ostwald Ripening         — OVITO → Blender (50k seeds → clusters → 3D mesh)

Usage:
  python3 generate_fig10_nature_cover.py          # full pipeline
  python3 generate_fig10_nature_cover.py --panel c # single panel for testing
"""

import sys
import os
import json
import socket
import argparse
import tempfile
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from styles import apply_nature_style, MATERIALS as C, _NATURE_RCPARAMS, NATURE_DOUBLE

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyArrowPatch, ConnectionPatch

# ═══════════════════════════════════════════════════════════════════════════════
# PATHS
# ═══════════════════════════════════════════════════════════════════════════════

ROOT      = Path(__file__).parent.parent.resolve()
CIF_DIR   = ROOT / "tests" / "sample_structures"
OUT_DIR   = ROOT / "output"
OUT_DIR.mkdir(exist_ok=True)

FLUORITE_CIF  = CIF_DIR / "fluorite_ZrO2.cif"
ROCKSALT_CIF  = CIF_DIR / "rocksalt_ZrO_4733.cif"

# Nature Cover color overrides (glossy/volumetric palette)
NC = {
    "zr_teal":   "#00B8A9",   # glossy cyan/teal for Zr ions
    "o_coral":   "#E05D5D",   # matte coral/red for O ions
    "gold":      "#FFB800",   # volumetric glowing gold/amber for vacancies/2DEG
    "gold_glow": "#FFDE59",
    "cyan_band": "#00D4FF",
    "bg":        "#FFFFFF",
    **C,
}

# ═══════════════════════════════════════════════════════════════════════════════
# BLENDER MCP COMMUNICATION
# ═══════════════════════════════════════════════════════════════════════════════

BLENDER_HOST = "localhost"
BLENDER_PORT = 9876
BLENDER_TIMEOUT = 120


def blender_send(command: dict, timeout=BLENDER_TIMEOUT) -> dict:
    """Send JSON command to the Blender MCP addon socket."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((BLENDER_HOST, BLENDER_PORT))
    sock.sendall(json.dumps(command).encode("utf-8"))
    chunks = []
    while True:
        try:
            chunk = sock.recv(8192)
            if not chunk:
                break
            chunks.append(chunk)
            try:
                json.loads(b"".join(chunks))
                break
            except json.JSONDecodeError:
                continue
        except socket.timeout:
            break
    sock.close()
    raw = b"".join(chunks).decode("utf-8")
    return json.loads(raw) if raw else {"status": "error", "message": "Empty response"}


def blender_exec(code: str, timeout=BLENDER_TIMEOUT) -> dict:
    """Execute Python code inside Blender."""
    result = blender_send({"type": "execute_code", "params": {"code": code}}, timeout=timeout)
    if result.get("status") == "error":
        print(f"  [Blender ERROR] {result.get('message', '?')}")
        tb = result.get("traceback", "")
        if tb:
            print(f"  {tb[:500]}")
    return result


def blender_ping() -> bool:
    """Check if Blender MCP addon is reachable."""
    try:
        r = blender_send({"type": "get_scene_info"})
        return r.get("status") != "error"
    except Exception:
        return False


def blender_clear_scene():
    """Clear all objects from the Blender scene."""
    blender_exec("""
import bpy
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for c in list(bpy.data.collections):
    bpy.data.collections.remove(c)
for m in list(bpy.data.materials):
    bpy.data.materials.remove(m)
for mesh in list(bpy.data.meshes):
    bpy.data.meshes.remove(mesh)
print("RESULT:scene_cleared")
""")


# ═══════════════════════════════════════════════════════════════════════════════
# PANEL C — Zone Folding (matplotlib, Nature style)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_panel_c(output_path=None):
    """BZ folding: phonon dispersion (left) + Raman spectrum (right).

    Both subplots share a Frequency (cm⁻¹) Y-axis. A translucent cyan
    horizontal band links the folded 0.73 dispersion mode to the 458 cm⁻¹
    Raman peak.
    """
    if output_path is None:
        output_path = OUT_DIR / "panel_c.png"

    apply_nature_style()
    plt.rcParams.update({
        "figure.dpi": 150, "savefig.dpi": 300,
        "font.size": 14, "axes.labelsize": 14,
        "xtick.labelsize": 12, "ytick.labelsize": 12,
        "axes.linewidth": 1.2,
    })

    fig_w = 7.08
    fig_h = 4.0
    fig = plt.figure(figsize=(fig_w, fig_h))
    gs = gridspec.GridSpec(1, 2, width_ratios=[1.2, 0.8], wspace=0.06)
    ax_disp = fig.add_subplot(gs[0])
    ax_ram  = fig.add_subplot(gs[1], sharey=ax_disp)

    LW_MAIN = 2.5
    FS_ANNOT = 14

    # ── Physical constants ────────────────────────────────────────────────
    kB_cm = 0.6950
    theta_lo, theta_hi = 670, 730
    omega_D_lo = kB_cm * theta_lo
    omega_D_hi = kB_cm * theta_hi
    omega_D_mid = kB_cm * 700
    q_star = 0.73
    sin_factor = np.sin(np.pi * q_star / 2)

    omega_ridge_lo = omega_D_lo * sin_factor
    omega_ridge_hi = omega_D_hi * sin_factor
    omega_star = omega_D_mid * sin_factor

    # ── Left: Phonon Dispersion ───────────────────────────────────────────
    q = np.linspace(0, 1, 500)
    omega_ac = omega_D_mid * np.sin(np.pi * q / 2)
    omega_lo_branch = 620 - 90 * q**2
    omega_to_branch = 490 - 70 * q**2

    ax_disp.plot(q, omega_ac, "-", color=NC["blue"], lw=LW_MAIN, label="Acoustic")
    ax_disp.plot(q, omega_lo_branch, "-", color=NC["green"], lw=LW_MAIN * 0.6, alpha=0.4, label="LO")
    ax_disp.plot(q, omega_to_branch, "--", color=NC["green"], lw=LW_MAIN * 0.6, alpha=0.4, label="TO")

    for ax in [ax_disp, ax_ram]:
        ax.axhspan(omega_ridge_lo, omega_ridge_hi, color=NC["cyan_band"], alpha=0.15, zorder=0)

    ax_disp.plot(q_star, omega_star, "o", color=NC["vermillion"], ms=10,
                 zorder=6, markeredgecolor="white", markeredgewidth=1.0)
    ax_disp.annotate(
        f"$q^{{\\,*}}\\!=0.73\\,q_D$\n({omega_star:.0f} cm$^{{-1}}$)",
        xy=(q_star, omega_star),
        xytext=(q_star + 0.06, omega_star + 110),
        fontsize=FS_ANNOT, color=NC["vermillion"], fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=NC["vermillion"], lw=1.5),
        bbox=dict(fc="white", ec="none", alpha=0.85, pad=2))

    # Folding arrow — thick and dark
    ax_disp.annotate(
        "", xy=(0.025, omega_star - 5),
        xytext=(q_star - 0.025, omega_star - 5),
        arrowprops=dict(arrowstyle="-|>", color="#B85C00", lw=3.0,
                        ls="--", connectionstyle="arc3,rad=0.25",
                        mutation_scale=18))
    ax_disp.text(q_star / 2, omega_star + 60,
                 "zone folding", ha="center", fontsize=FS_ANNOT,
                 color="#B85C00", fontweight="bold", style="italic",
                 bbox=dict(fc="white", ec="none", alpha=0.85, pad=2))

    ax_disp.plot(0, omega_star, "*", color=NC["orange"], ms=14, zorder=6)
    ax_disp.annotate(
        "folded to $\\Gamma$\n$\\rightarrow$ Raman active",
        xy=(0.01, omega_star - 15),
        xytext=(0.16, omega_star - 140),
        fontsize=FS_ANNOT - 2, color=NC["orange"], fontweight="bold", ha="center",
        arrowprops=dict(arrowstyle="->", color=NC["orange"], lw=1.2))

    ax_disp.axhline(omega_star, color=NC["orange"], ls=":", lw=1.0, alpha=0.4)

    ax_disp.text(0.97, 0.03,
                 "$\\omega(q^{\\,*}) = \\omega_D \\sin\\!\\left("
                 "\\frac{\\pi q^{\\,*}}{2 q_D}\\right)$"
                 "\n$\\theta_D = 670$–$730$ K",
                 transform=ax_disp.transAxes,
                 fontsize=10, color=NC["dark_gray"], ha="right", va="bottom",
                 fontweight="bold",
                 bbox=dict(fc="white", ec=NC["light_gray"], lw=0.5, pad=3,
                           boxstyle="round,pad=0.2", alpha=0.9))

    ax_disp.set_ylabel("Frequency  (cm$^{-1}$)", fontsize=14, fontweight="bold")
    ax_disp.set_xlim(-0.08, 1.05)
    ax_disp.set_ylim(100, 800)
    ax_disp.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax_disp.set_xticklabels(["$\\Gamma$", "", "", "", "$q_D$"], fontsize=12, fontweight="bold")
    ax_disp.set_xlabel("Wavevector  $q\\,/\\,q_D$", fontsize=14, fontweight="bold")
    ax_disp.tick_params(axis='both', labelsize=12, width=1.2, length=5)
    ax_disp.legend(fontsize=10, loc="upper right", framealpha=0.9, handlelength=1.2)

    # ── Right: Raman Spectrum ─────────────────────────────────────────────
    wn = np.linspace(100, 800, 1200)

    def lor(x, x0, g, A):
        return A * g**2 / ((x - x0)**2 + g**2)

    pristine = (lor(wn, 260, 18, 0.25) + lor(wn, 340, 22, 0.10) +
                lor(wn, 467, 14, 0.18) + lor(wn, 615, 16, 0.35))
    ar600 = pristine + lor(wn, 458, 7, 0.55)

    ax_ram.fill_betweenx(wn, 0, pristine, alpha=0.06, color=NC["blue"])
    ax_ram.plot(pristine, wn, "-", color=NC["blue"], lw=LW_MAIN, alpha=0.55, label="Pristine 8YSZ")
    ax_ram.plot(ar600, wn, "-", color=NC["vermillion"], lw=LW_MAIN, label="Ar600 (flashed)")

    mask = (wn > 442) & (wn < 474)
    ax_ram.fill_betweenx(wn[mask], pristine[mask], ar600[mask],
                         alpha=0.30, color=NC["orange"])

    peak_y = 458
    peak_x = lor(458, 458, 7, 0.55) + lor(458, 467, 14, 0.18)
    ax_ram.annotate(
        "458 cm$^{-1}$\n(anomalous)",
        xy=(peak_x + 0.02, peak_y),
        xytext=(0.55, 300),
        fontsize=FS_ANNOT, color=NC["vermillion"], fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=NC["vermillion"], lw=1.2),
        bbox=dict(fc="white", ec="none", alpha=0.85, pad=2))

    ax_ram.axhline(458, color=NC["orange"], ls=":", lw=1.2, alpha=0.5)

    ax_ram.set_xlabel("Intensity (a.u.)", fontsize=14, fontweight="bold")
    ax_ram.set_xlim(0, max(ar600) * 1.15)
    ax_ram.set_xticks([])
    plt.setp(ax_ram.get_yticklabels(), visible=False)
    ax_ram.tick_params(axis='both', labelsize=12, width=1.2, length=5)
    ax_ram.legend(fontsize=9, loc="lower right", framealpha=0.9, handlelength=1.2)

    con = ConnectionPatch(
        xyA=(1.0, omega_star), xyB=(0.0, omega_star),
        coordsA="data", coordsB="data",
        axesA=ax_disp, axesB=ax_ram,
        color=NC["orange"], ls=":", lw=1.5, alpha=0.5, zorder=0)
    fig.add_artist(con)

    ax_disp.text(-0.12, 1.05, "(c)", transform=ax_disp.transAxes,
                 fontsize=16, fontweight="bold", va="top", ha="left",
                 fontfamily="sans-serif")

    for fmt in ["png", "pdf"]:
        p = str(output_path).replace(".png", f".{fmt}")
        fig.savefig(p, dpi=300, bbox_inches="tight", pad_inches=0.03)
        print(f"  Panel C saved: {p}")
    plt.close(fig)
    return str(output_path)


# ═══════════════════════════════════════════════════════════════════════════════
# PANEL A — Acoustic Blueprint (pymatgen → Blender)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_panel_a(output_path=None):
    """3×3×1 8YSZ supercell with volumetric sine wave and gold vacancy spheres."""
    if output_path is None:
        output_path = str(OUT_DIR / "panel_a.png")

    import ase.io
    from pymatgen.core import Structure

    atoms = ase.io.read(str(FLUORITE_CIF))
    sc = atoms.repeat([3, 3, 1])
    positions = sc.get_positions()
    symbols = sc.get_chemical_symbols()
    cell = sc.cell

    a_f = 5.145
    wavelength = 0.96 * a_f

    # Compute antinode X positions (peaks of sin wave)
    cell_x = cell[0, 0]
    antinode_xs = []
    n_half = int(np.ceil(cell_x / wavelength * 2)) + 1
    for k in range(n_half):
        x_peak = (0.25 + k) * wavelength
        if -0.1 <= x_peak <= cell_x + 0.1:
            antinode_xs.append(x_peak)

    # Determine vacancy positions: O sites near antinodes
    np.random.seed(7)
    vacancy_positions = []
    o_positions = []
    zr_positions = []
    for pos, sym in zip(positions, symbols):
        if sym == "O":
            near = any(abs(pos[0] - xa) < 0.45 * a_f for xa in antinode_xs)
            if near and np.random.random() < 0.55:
                vacancy_positions.append(pos.tolist())
            else:
                o_positions.append(pos.tolist())
        else:
            zr_positions.append(pos.tolist())

    # Save temp files for Blender
    tmp_dir = tempfile.mkdtemp(prefix="fig10_")
    sc_path = os.path.join(tmp_dir, "supercell_8ysz.xyz")
    ase.io.write(sc_path, sc, format="xyz")

    blender_clear_scene()

    cx = float(cell[0, 0])
    cy = float(cell[1, 1])
    cz = float(cell[2, 2])
    center = (cx / 2, cy / 2, cz / 2)

    # Step 1: Scene setup — white bg, Cycles, slight isometric camera
    blender_exec(f"""
import bpy
import math
from mathutils import Vector

scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.samples = 256
scene.cycles.use_denoising = True
scene.render.resolution_x = 2400
scene.render.resolution_y = 1800
scene.render.film_transparent = False

world = scene.world
if world is None:
    world = bpy.data.worlds.new("World")
    scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
if bg:
    bg.inputs["Color"].default_value = (1, 1, 1, 1)
    bg.inputs["Strength"].default_value = 1.0

scene.view_settings.view_transform = 'Standard'
scene.view_settings.look = 'None'

# Slight isometric angle: elevated, rotated
cam_dist = {max(cx, cy, cz) * 3.2}
cam_x = {center[0]} + cam_dist * 0.45
cam_y = {center[1]} - cam_dist * 0.55
cam_z = {center[2]} + cam_dist * 0.65
bpy.ops.object.camera_add(location=(cam_x, cam_y, cam_z))
cam = bpy.context.active_object
cam.data.type = 'ORTHO'
cam.data.ortho_scale = {max(cx, cy) * 1.5}

direction = Vector(({center[0]}, {center[1]}, {center[2]})) - Vector((cam_x, cam_y, cam_z))
rot = direction.to_track_quat('-Z', 'Y')
cam.rotation_euler = rot.to_euler()
scene.camera = cam

bpy.ops.object.light_add(type='SUN', location=(10, -10, 25))
sun = bpy.context.active_object
sun.data.energy = 3.5
sun.data.angle = math.radians(12)

bpy.ops.object.light_add(type='AREA', location=(-8, 8, 18))
fill = bpy.context.active_object
fill.data.energy = 60
fill.data.size = 12

print("RESULT:scene_setup_done")
""")

    # Step 2: Create Zr atoms (glossy cyan/teal)
    zr_json = json.dumps(zr_positions)
    blender_exec(f"""
import bpy
import json

positions = json.loads('''{zr_json}''')

mat = bpy.data.materials.new("Mat_Zr")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.0, 0.722, 0.663, 1)  # teal
bsdf.inputs["Metallic"].default_value = 0.6
bsdf.inputs["Roughness"].default_value = 0.15
bsdf.inputs["Coat Weight"].default_value = 0.8

bpy.ops.mesh.primitive_uv_sphere_add(radius=0.35, segments=32, ring_count=16)
template = bpy.context.active_object
template.name = "Zr_template"
for face in template.data.polygons:
    face.use_smooth = True
template.data.materials.append(mat)

for i, pos in enumerate(positions):
    if i == 0:
        template.location = pos
        continue
    obj = template.copy()
    obj.data = template.data
    obj.name = f"Zr_{{i}}"
    obj.location = pos
    bpy.context.scene.collection.objects.link(obj)

print(f"RESULT:zr_atoms_{{len(positions)}}")
""")

    # Step 3: Create O atoms (matte coral)
    o_json = json.dumps(o_positions)
    blender_exec(f"""
import bpy
import json

positions = json.loads('''{o_json}''')

mat = bpy.data.materials.new("Mat_O")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.878, 0.365, 0.365, 1)  # coral
bsdf.inputs["Metallic"].default_value = 0.0
bsdf.inputs["Roughness"].default_value = 0.7

bpy.ops.mesh.primitive_uv_sphere_add(radius=0.25, segments=24, ring_count=12)
template = bpy.context.active_object
template.name = "O_template"
for face in template.data.polygons:
    face.use_smooth = True
template.data.materials.append(mat)

for i, pos in enumerate(positions):
    if i == 0:
        template.location = pos
        continue
    obj = template.copy()
    obj.data = template.data
    obj.name = f"O_{{i}}"
    obj.location = pos
    bpy.context.scene.collection.objects.link(obj)

print(f"RESULT:o_atoms_{{len(positions)}}")
""")

    # Step 4: Create vacancy spheres (glowing gold at antinodes)
    vac_json = json.dumps(vacancy_positions)
    blender_exec(f"""
import bpy
import json

positions = json.loads('''{vac_json}''')

mat = bpy.data.materials.new("Mat_Vacancy")
mat.use_nodes = True
nodes = mat.node_tree.nodes
links = mat.node_tree.links

bsdf = nodes["Principled BSDF"]
nodes.remove(bsdf)

output_node = nodes["Material Output"]
emission = nodes.new("ShaderNodeEmission")
emission.inputs["Color"].default_value = (1.0, 0.722, 0.0, 1)  # gold
emission.inputs["Strength"].default_value = 5.0

glass = nodes.new("ShaderNodeBsdfTransparent")
glass.inputs["Color"].default_value = (1.0, 0.871, 0.345, 1)

mix = nodes.new("ShaderNodeMixShader")
mix.inputs["Fac"].default_value = 0.3

links.new(emission.outputs["Emission"], mix.inputs[1])
links.new(glass.outputs["BSDF"], mix.inputs[2])
links.new(mix.outputs["Shader"], output_node.inputs["Surface"])

bpy.ops.mesh.primitive_uv_sphere_add(radius=0.28, segments=24, ring_count=12)
template = bpy.context.active_object
template.name = "Vac_template"
for face in template.data.polygons:
    face.use_smooth = True
template.data.materials.append(mat)

for i, pos in enumerate(positions):
    if i == 0:
        template.location = pos
        continue
    obj = template.copy()
    obj.data = template.data
    obj.name = f"Vac_{{i}}"
    obj.location = pos
    bpy.context.scene.collection.objects.link(obj)

print(f"RESULT:vacancies_{{len(positions)}}")
""")

    # Step 5: Volumetric sine wave — cube fully encloses supercell
    blender_exec(f"""
import bpy
import math

cx = {cx}
cy = {cy}
cz = {cz}
wavelength = {wavelength}

bpy.ops.mesh.primitive_cube_add(
    size=1,
    location=(cx/2, cy/2, cz/2)
)
cube = bpy.context.active_object
cube.name = "VolumetricWave"
cube.scale = (cx * 0.52, cy * 0.52, cz * 0.52)

mat = bpy.data.materials.new("Mat_Volume")
mat.use_nodes = True
nodes = mat.node_tree.nodes
links = mat.node_tree.links

for n in list(nodes):
    nodes.remove(n)

output = nodes.new("ShaderNodeOutputMaterial")
volume = nodes.new("ShaderNodeVolumePrincipled")

tex_coord = nodes.new("ShaderNodeTexCoord")
mapping = nodes.new("ShaderNodeMapping")

sep_xyz = nodes.new("ShaderNodeSeparateXYZ")
links.new(tex_coord.outputs["Object"], mapping.outputs["Vector"] if False else mapping.inputs["Vector"])
links.new(mapping.outputs["Vector"], sep_xyz.inputs["Vector"])

divide = nodes.new("ShaderNodeMath")
divide.operation = 'DIVIDE'
links.new(sep_xyz.outputs["X"], divide.inputs[0])
divide.inputs[1].default_value = wavelength / cx

mul_2pi = nodes.new("ShaderNodeMath")
mul_2pi.operation = 'MULTIPLY'
links.new(divide.outputs["Value"], mul_2pi.inputs[0])
mul_2pi.inputs[1].default_value = 2 * math.pi

sin_node = nodes.new("ShaderNodeMath")
sin_node.operation = 'SINE'
links.new(mul_2pi.outputs["Value"], sin_node.inputs[0])

clamp = nodes.new("ShaderNodeMath")
clamp.operation = 'MAXIMUM'
links.new(sin_node.outputs["Value"], clamp.inputs[0])
clamp.inputs[1].default_value = 0.0

density_scale = nodes.new("ShaderNodeMath")
density_scale.operation = 'MULTIPLY'
links.new(clamp.outputs["Value"], density_scale.inputs[0])
density_scale.inputs[1].default_value = 0.8

volume.inputs["Color"].default_value = (0.0, 0.85, 1.0, 1)
links.new(density_scale.outputs["Value"], volume.inputs["Density"])

emission_scale = nodes.new("ShaderNodeMath")
emission_scale.operation = 'MULTIPLY'
links.new(clamp.outputs["Value"], emission_scale.inputs[0])
emission_scale.inputs[1].default_value = 0.3

volume.inputs["Emission Color"].default_value = (0.0, 0.85, 1.0, 1)
links.new(emission_scale.outputs["Value"], volume.inputs["Emission Strength"])

links.new(volume.outputs["Volume"], output.inputs["Volume"])

print("RESULT:volumetric_done")
""")

    # Step 6: Render Panel A
    blender_exec(f"""
import bpy
scene = bpy.context.scene
scene.render.filepath = "{output_path}"
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_depth = '16'
bpy.ops.render.render(write_still=True)
print("RESULT:panel_a_rendered")
""", timeout=300)

    print(f"  Panel A saved: {output_path}")
    return output_path


# ═══════════════════════════════════════════════════════════════════════════════
# PANEL B — Topotactic Collapse & Metallization (pymatgen → Blender)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_panel_b(output_path=None):
    """Two unit cells side-by-side: Fluorite (parent) → Rocksalt (child)."""
    if output_path is None:
        output_path = str(OUT_DIR / "panel_b.png")

    from pymatgen.core import Structure

    struct_f = Structure.from_file(str(FLUORITE_CIF))
    struct_r = Structure.from_file(str(ROCKSALT_CIF))

    a_f = struct_f.lattice.a
    a_r = struct_r.lattice.a
    d_zr_f = a_f * np.sqrt(2) / 2
    d_zr_r = a_r * np.sqrt(2) / 2

    # Extract fractional positions
    f_sites = [(str(s.specie), s.frac_coords.tolist()) for s in struct_f]
    r_sites = [(str(s.specie), s.frac_coords.tolist()) for s in struct_r]

    f_json = json.dumps(f_sites)
    r_json = json.dumps(r_sites)

    blender_clear_scene()

    # Scene setup with slight isometric angle
    blender_exec(f"""
import bpy
import math

scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.samples = 256
scene.cycles.use_denoising = True
scene.render.resolution_x = 2400
scene.render.resolution_y = 1800
scene.render.film_transparent = False

world = scene.world
if world is None:
    world = bpy.data.worlds.new("World")
    scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
if bg:
    bg.inputs["Color"].default_value = (1, 1, 1, 1)
    bg.inputs["Strength"].default_value = 1.0
scene.view_settings.view_transform = 'Standard'

bpy.ops.object.camera_add(location=(0, -18, 8))
cam = bpy.context.active_object
cam.data.type = 'ORTHO'
cam.data.ortho_scale = 16
cam.rotation_euler = (math.radians(65), 0, 0)
scene.camera = cam

bpy.ops.object.light_add(type='SUN', location=(5, -5, 15))
sun = bpy.context.active_object
sun.data.energy = 3.0
sun.data.angle = math.radians(15)

bpy.ops.object.light_add(type='AREA', location=(-5, 5, 10))
fill = bpy.context.active_object
fill.data.energy = 80
fill.data.size = 12

print("RESULT:b_scene_done")
""")

    # Create materials
    blender_exec("""
import bpy

def make_mat(name, color, metallic=0.0, roughness=0.5, emission=0.0, emission_color=None):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission > 0 and emission_color:
        bsdf.inputs["Emission Color"].default_value = emission_color
        bsdf.inputs["Emission Strength"].default_value = emission
    return mat

make_mat("Zr_Fluorite", (0.0, 0.722, 0.663, 1), metallic=0.6, roughness=0.15)
make_mat("O_Coral", (0.878, 0.365, 0.365, 1), metallic=0.0, roughness=0.7)
make_mat("Zr_Metallic", (0.788, 0.580, 0.227, 1), metallic=0.85, roughness=0.1,
         emission=2.0, emission_color=(1.0, 0.722, 0.0, 1))
# Translucent pink glass for tetrahedral polyhedra
mat_tet = bpy.data.materials.new("Poly_Tet")
mat_tet.use_nodes = True
nt = mat_tet.node_tree
bsdf_t = nt.nodes["Principled BSDF"]
bsdf_t.inputs["Base Color"].default_value = (0.95, 0.55, 0.65, 1)
bsdf_t.inputs["Alpha"].default_value = 0.12
bsdf_t.inputs["Roughness"].default_value = 0.1
bsdf_t.inputs["Transmission Weight"].default_value = 0.9

# Translucent red glass for octahedral polyhedra
mat_oct = bpy.data.materials.new("Poly_Oct")
mat_oct.use_nodes = True
no = mat_oct.node_tree
bsdf_o = no.nodes["Principled BSDF"]
bsdf_o.inputs["Base Color"].default_value = (0.95, 0.45, 0.35, 1)
bsdf_o.inputs["Alpha"].default_value = 0.12
bsdf_o.inputs["Roughness"].default_value = 0.1
bsdf_o.inputs["Transmission Weight"].default_value = 0.9

# 2DEG cloud material: Emission + Transparent via Layer Weight
mat_2deg = bpy.data.materials.new("Mat_2DEG")
mat_2deg.use_nodes = True
nodes = mat_2deg.node_tree.nodes
links = mat_2deg.node_tree.links
bsdf = nodes["Principled BSDF"]
nodes.remove(bsdf)
output = nodes["Material Output"]

emission = nodes.new("ShaderNodeEmission")
emission.inputs["Color"].default_value = (1.0, 0.85, 0.0, 1)
emission.inputs["Strength"].default_value = 8.0

transparent = nodes.new("ShaderNodeBsdfTransparent")
transparent.inputs["Color"].default_value = (1.0, 0.871, 0.345, 1)

layer_weight = nodes.new("ShaderNodeLayerWeight")
layer_weight.inputs["Blend"].default_value = 0.3

mix = nodes.new("ShaderNodeMixShader")
links.new(layer_weight.outputs["Facing"], mix.inputs["Fac"])
links.new(transparent.outputs["BSDF"], mix.inputs[1])
links.new(emission.outputs["Emission"], mix.inputs[2])
links.new(mix.outputs["Shader"], output.inputs["Surface"])

mat_2deg.blend_method = 'BLEND' if hasattr(mat_2deg, 'blend_method') else None

# Cell wireframe material
make_mat("Cell_Blue", (0.0, 0.45, 0.70, 1), metallic=0.0, roughness=0.8)
make_mat("Cell_Red", (0.84, 0.37, 0.0, 1), metallic=0.0, roughness=0.8)

print("RESULT:materials_done")
""")

    # Build the Fluorite cell (left, centered at x=-4)
    blender_exec(f"""
import bpy
import json
import numpy as np

a = {a_f}
offset_x = -4.5
sites = json.loads('''{f_json}''')

# Unit cell as thin wireframe edges visible in Cycles
bpy.ops.mesh.primitive_cube_add(size=1, location=(offset_x + a/2, a/2, a/2))
cell = bpy.context.active_object
cell.name = "Cell_Fluorite"
cell.scale = (a, a, a)
wf = cell.modifiers.new(name="Wireframe", type='WIREFRAME')
wf.thickness = 0.04
wf.use_replace = True
mat = bpy.data.materials["Cell_Blue"]
cell.data.materials.append(mat)

# 8 translucent pink glass tetrahedral polyhedra enclosing O
o_fracs = [(0.25,0.25,0.25),(0.75,0.25,0.25),(0.25,0.75,0.25),(0.75,0.75,0.25),
           (0.25,0.25,0.75),(0.75,0.25,0.75),(0.25,0.75,0.75),(0.75,0.75,0.75)]
for fx, fy, fz in o_fracs:
    cx = offset_x + fx * a
    cy = fy * a
    cz = fz * a
    size = a * 0.25
    bpy.ops.mesh.primitive_uv_sphere_add(radius=size, location=(cx, cy, cz), segments=8, ring_count=6)
    poly = bpy.context.active_object
    poly.name = f"TetPoly_{{fx:.0f}}{{fy:.0f}}{{fz:.0f}}"
    for face in poly.data.polygons: face.use_smooth = True
    poly.data.materials.append(bpy.data.materials["Poly_Tet"])

# Atoms
for sym, frac in sites:
    px = offset_x + frac[0] * a
    py = frac[1] * a
    pz = frac[2] * a
    if sym == "Zr":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.4, location=(px, py, pz), segments=32, ring_count=16)
        obj = bpy.context.active_object
        for face in obj.data.polygons: face.use_smooth = True
        obj.data.materials.append(bpy.data.materials["Zr_Fluorite"])
    else:
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.28, location=(px, py, pz), segments=24, ring_count=12)
        obj = bpy.context.active_object
        for face in obj.data.polygons: face.use_smooth = True
        obj.data.materials.append(bpy.data.materials["O_Coral"])

print("RESULT:fluorite_built")
""")

    # Build the Rocksalt cell (right, centered at x=+4)
    blender_exec(f"""
import bpy
import json
import numpy as np

a = {a_r}
offset_x = 4.5
sites = json.loads('''{r_json}''')

# Unit cell as thin wireframe edges (8% smaller)
bpy.ops.mesh.primitive_cube_add(size=1, location=(offset_x + a/2, a/2, a/2))
cell = bpy.context.active_object
cell.name = "Cell_Rocksalt"
cell.scale = (a, a, a)
wf = cell.modifiers.new(name="Wireframe", type='WIREFRAME')
wf.thickness = 0.04
wf.use_replace = True
mat = bpy.data.materials["Cell_Red"]
cell.data.materials.append(mat)

# 4 translucent octahedral polyhedra enclosing O
o_fracs = [(0.5,0.5,0.5),(0.5,0.0,0.0),(0.0,0.5,0.0),(0.0,0.0,0.5)]
for fx, fy, fz in o_fracs:
    cx = offset_x + fx * a
    cy = fy * a
    cz = fz * a
    size = a * 0.22
    bpy.ops.mesh.primitive_uv_sphere_add(radius=size, location=(cx, cy, cz), segments=6, ring_count=4)
    poly = bpy.context.active_object
    poly.name = f"OctPoly_{{fx:.1f}}{{fy:.1f}}{{fz:.1f}}"
    for face in poly.data.polygons: face.use_smooth = True
    poly.data.materials.append(bpy.data.materials["Poly_Oct"])

# Atoms
zr_positions = []
for sym, frac in sites:
    px = offset_x + frac[0] * a
    py = frac[1] * a
    pz = frac[2] * a
    if sym == "Zr":
        zr_positions.append((px, py, pz))
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.4, location=(px, py, pz), segments=32, ring_count=16)
        obj = bpy.context.active_object
        for face in obj.data.polygons: face.use_smooth = True
        obj.data.materials.append(bpy.data.materials["Zr_Metallic"])
    else:
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.28, location=(px, py, pz), segments=24, ring_count=12)
        obj = bpy.context.active_object
        for face in obj.data.polygons: face.use_smooth = True
        obj.data.materials.append(bpy.data.materials["O_Coral"])

# 2DEG Cloud: spheres at midpoints of nearest-neighbor Zr pairs (face diagonals)
import itertools
mat_2deg = bpy.data.materials["Mat_2DEG"]
for (x1,y1,z1), (x2,y2,z2) in itertools.combinations(zr_positions, 2):
    dist = ((x2-x1)**2 + (y2-y1)**2 + (z2-z1)**2)**0.5
    if dist < a * 0.75:
        mx, my, mz = (x1+x2)/2, (y1+y2)/2, (z1+z2)/2
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.55, location=(mx, my, mz), segments=24, ring_count=12)
        obj = bpy.context.active_object
        obj.name = "2DEG_cloud"
        for face in obj.data.polygons: face.use_smooth = True
        obj.data.materials.append(mat_2deg)

print("RESULT:rocksalt_built")
""")

    # Add text labels — 300% larger (size 0.3→0.9, 0.4→1.2, 0.25→0.75)
    blender_exec(f"""
import bpy
import math

def add_label(text, location, size=0.9, color=(0.0, 0.0, 0.0, 1), rotation=(math.pi/2, 0, 0)):
    bpy.ops.object.text_add(location=location, rotation=rotation)
    obj = bpy.context.active_object
    obj.data.body = text
    obj.data.size = size
    obj.data.align_x = 'CENTER'
    obj.data.align_y = 'CENTER'
    mat = bpy.data.materials.new(f"Mat_Label_{{text[:8]}}")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = color
    obj.data.materials.append(mat)
    return obj

add_label("Fluorite ZrO2", (-4.5 + {a_f}/2, -1.5, {a_f} + 2.0), size=1.2,
          color=(0.0, 0.45, 0.70, 1))
add_label("d(Zr-Zr) = {d_zr_f:.2f} A", (-4.5 + {a_f}/2, -1.5, -1.5), size=0.9,
          color=(0.0, 0.45, 0.70, 1))

add_label("Rocksalt ZrO", (4.5 + {a_r}/2, -1.5, {a_r} + 2.0), size=1.2,
          color=(0.84, 0.37, 0.0, 1))
add_label("d(Zr-Zr) = {d_zr_r:.2f} A", (4.5 + {a_r}/2, -1.5, -1.5), size=0.9,
          color=(0.84, 0.37, 0.0, 1))

# Bold black math text
add_label("[-13.4% Geom] + [+6.2% Quantum] = 8.0% Net Contraction",
          (0, -1.5, -3.5), size=0.75, color=(0.0, 0.0, 0.0, 1))

# Arrow between cells
bpy.ops.curve.primitive_bezier_curve_add(location=(0, {a_f}/2, {a_f}/2))
arrow = bpy.context.active_object
arrow.name = "TransformArrow"
points = arrow.data.splines[0].bezier_points
points[0].co = (-2.5, 0, 0)
points[0].handle_right = (-1.5, 0, 0)
points[1].co = (2.5, 0, 0)
points[1].handle_left = (1.5, 0, 0)
arrow.data.bevel_depth = 0.08
mat = bpy.data.materials.new("Mat_Arrow")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.2, 0.2, 0.2, 1)
arrow.data.materials.append(mat)

print("RESULT:labels_done")
""")

    # Render Panel B
    blender_exec(f"""
import bpy
scene = bpy.context.scene
scene.render.filepath = "{output_path}"
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_depth = '16'
bpy.ops.render.render(write_still=True)
print("RESULT:panel_b_rendered")
""", timeout=300)

    print(f"  Panel B saved: {output_path}")
    return output_path


# ═══════════════════════════════════════════════════════════════════════════════
# PANEL D — Ostwald Ripening (OVITO → Blender)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_panel_d(output_path=None):
    """3-stage Ostwald ripening: random seeds → clusters → percolating channels."""
    if output_path is None:
        output_path = str(OUT_DIR / "panel_d.png")

    box_size = 200.0  # nm
    n_seeds = 50000

    np.random.seed(42)
    positions = np.random.rand(n_seeds, 3) * box_size

    # Bias positions along diagonal crystallographic planes [110]
    diagonal_bias = (positions[:, 0] + positions[:, 1]) / (box_size * np.sqrt(2))
    plane_attraction = 0.3 * np.sin(2 * np.pi * diagonal_bias * 8)
    positions[:, 2] += plane_attraction * box_size * 0.05

    # Save as XYZ for OVITO
    tmp_dir = tempfile.mkdtemp(prefix="fig10d_")
    xyz_path = os.path.join(tmp_dir, "seeds.xyz")
    with open(xyz_path, "w") as f:
        f.write(f"{n_seeds}\n")
        f.write(f"Lattice=\"{box_size} 0 0 0 {box_size} 0 0 0 {box_size}\" Properties=species:S:1:pos:R:3\n")
        for p in positions:
            f.write(f"X {p[0]:.4f} {p[1]:.4f} {p[2]:.4f}\n")

    # Use OVITO Python API directly for clustering and surface mesh
    from ovito.io import import_file
    from ovito.modifiers import (ClusterAnalysisModifier,
                                 ConstructSurfaceModifier,
                                 ColorCodingModifier)
    from ovito.vis import Viewport, TachyonRenderer
    from ovito.data import SimulationCell
    from ase import Atoms
    import ase.io as ase_io

    pipeline = import_file(xyz_path)

    # Set cell on source
    src_data = pipeline.source.data
    if src_data.cell is None:
        cell_obj = SimulationCell()
        cell_obj.matrix = np.array([
            [box_size, 0, 0, 0],
            [0, box_size, 0, 0],
            [0, 0, box_size, 0],
        ], dtype=float)
        cell_obj.pbc = (True, True, True)
        cell_obj.vis.enabled = True
        cell_obj.vis.line_width = 1.0
        cell_obj.vis.rendering_color = (0.2, 0.2, 0.2)
        src_data.objects.append(cell_obj)

    WHITE_BG = (1.0, 1.0, 1.0)
    AMBER = [1.0, 0.72, 0.0]

    # Stage 1: Glowing amber seeds on white background
    def style_seeds(frame, data):
        n = data.particles.count
        data.particles_.create_property("Color", data=np.tile(AMBER, (n, 1)))
        data.particles_.create_property("Radius", data=np.full(n, 0.5))

    pipeline.modifiers.append(style_seeds)

    renderer = TachyonRenderer()
    renderer.antialiasing_samples = 12
    renderer.direct_light_intensity = 0.9
    renderer.ambient_occlusion = True
    renderer.ambient_occlusion_brightness = 0.7

    vp = Viewport(type=Viewport.Type.Ortho)
    vp.camera_dir = (2, 1.5, -1)
    vp.fov = box_size * 1.4
    vp.zoom_all()

    stage1_path = os.path.join(tmp_dir, "stage1.png")
    pipeline.add_to_scene()
    vp.render_image(filename=stage1_path, size=(1600, 1200),
                    renderer=renderer, background=WHITE_BG)
    pipeline.remove_from_scene()
    print(f"  Stage 1 rendered: {stage1_path}")

    # Stage 2: Clustered amber spheres on white background
    pipeline2 = import_file(xyz_path)
    src2 = pipeline2.source.data
    if src2.cell is None:
        cell2 = SimulationCell()
        cell2.matrix = np.array([
            [box_size, 0, 0, 0],
            [0, box_size, 0, 0],
            [0, 0, box_size, 0],
        ], dtype=float)
        cell2.pbc = (True, True, True)
        cell2.vis.enabled = True
        cell2.vis.line_width = 1.0
        cell2.vis.rendering_color = (0.3, 0.3, 0.3)
        src2.objects.append(cell2)

    cluster_mod = ClusterAnalysisModifier(cutoff=5.0, sort_by_size=True)
    pipeline2.modifiers.append(cluster_mod)

    def style_clusters(frame, data):
        n = data.particles.count
        clusters = data.particles["Cluster"]
        colors = np.zeros((n, 3))
        radii = np.full(n, 0.35)
        for i in range(n):
            c = clusters[i]
            if c <= 10:
                colors[i] = AMBER
                radii[i] = 0.7
            else:
                colors[i] = [0.85, 0.60, 0.15]
                radii[i] = 0.3
        data.particles_.create_property("Color", data=colors)
        data.particles_.create_property("Radius", data=radii)

    pipeline2.modifiers.append(style_clusters)

    stage2_path = os.path.join(tmp_dir, "stage2.png")
    pipeline2.add_to_scene()
    vp.render_image(filename=stage2_path, size=(1600, 1200),
                    renderer=renderer, background=WHITE_BG)
    pipeline2.remove_from_scene()
    print(f"  Stage 2 rendered: {stage2_path}")

    # Stage 3: ConstructSurface alpha-shape → solid gold 3D mesh
    pipeline3 = import_file(xyz_path)
    src3 = pipeline3.source.data
    if src3.cell is None:
        cell3 = SimulationCell()
        cell3.matrix = np.array([
            [box_size, 0, 0, 0],
            [0, box_size, 0, 0],
            [0, 0, box_size, 0],
        ], dtype=float)
        cell3.pbc = (True, True, True)
        cell3.vis.enabled = True
        cell3.vis.line_width = 1.0
        cell3.vis.rendering_color = (0.3, 0.3, 0.3)
        src3.objects.append(cell3)

    cluster_mod3 = ClusterAnalysisModifier(cutoff=5.0, sort_by_size=True)
    pipeline3.modifiers.append(cluster_mod3)

    surf_mod = ConstructSurfaceModifier(
        radius=4.0,
        smoothing_level=8,
        only_selected=False,
    )
    pipeline3.modifiers.append(surf_mod)

    # Hide particles, show only the gold surface mesh
    def style_stage3_mesh(frame, data):
        n = data.particles.count
        data.particles_.create_property("Radius", data=np.full(n, 0.0))

    pipeline3.modifiers.append(style_stage3_mesh)

    # Configure surface mesh visual — glossy metallic gold
    data3 = pipeline3.compute()
    if hasattr(data3, 'surfaces'):
        for surf_key in data3.surfaces.keys():
            mesh = data3.surfaces[surf_key]
            if hasattr(mesh, 'vis'):
                mesh.vis.surface_color = (1.0, 0.75, 0.0)
                mesh.vis.surface_transparency = 0.0
                mesh.vis.show_cap = True

    stage3_path = os.path.join(tmp_dir, "stage3.png")
    pipeline3.add_to_scene()
    vp.render_image(filename=stage3_path, size=(1600, 1200),
                    renderer=renderer, background=WHITE_BG)
    pipeline3.remove_from_scene()
    print(f"  Stage 3 rendered: {stage3_path}")

    # Composite the 3 stages with white background + massive text
    from PIL import Image, ImageDraw, ImageFont

    imgs = [Image.open(p) for p in [stage1_path, stage2_path, stage3_path]]
    w, h = imgs[0].size
    text_h = 160
    composite = Image.new("RGB", (w * 3 + 40, h + text_h + 80), color=(255, 255, 255))
    draw = ImageDraw.Draw(composite)

    labels = ["Stage 1: Nucleation", "Stage 2: LSW Ripening", "Stage 3: Condensation"]
    try:
        font_title = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
    except Exception:
        font_title = ImageFont.load_default()

    for i, (img, label) in enumerate(zip(imgs, labels)):
        x_off = i * (w + 20)
        composite.paste(img, (x_off, 60))
        draw.text((x_off + w // 2, 20), label, fill=(30, 30, 30), anchor="mt", font=font_title)

    # Massive, highly legible callout text at bottom
    try:
        font_big = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 52)
    except Exception:
        font_big = ImageFont.load_default()
    callout = "Parallel Transport: M = 1000x  |  Channel Cond. = 10^5x Bulk"
    draw.text((composite.width // 2, composite.height - 30), callout,
              fill=(0, 0, 0), anchor="mb", font=font_big)

    composite.save(output_path)
    print(f"  Panel D saved: {output_path}")

    # Cleanup
    for p in [stage1_path, stage2_path, stage3_path, xyz_path]:
        try:
            os.unlink(p)
        except Exception:
            pass
    return output_path


# ═══════════════════════════════════════════════════════════════════════════════
# FINAL COMPOSITE — 2×2 grid
# ═══════════════════════════════════════════════════════════════════════════════

def composite_figure(panel_paths, output_path=None):
    """Assemble 4 panels into a strict 2×2 grid with Helvetica labels."""
    if output_path is None:
        output_path = str(OUT_DIR / "fig10_nature_cover.png")

    from PIL import Image, ImageDraw, ImageFont
    Image.MAX_IMAGE_PIXELS = None

    panels = []
    for p in panel_paths:
        if p and os.path.exists(p):
            panels.append(Image.open(p).convert("RGB"))
        else:
            img = Image.new("RGB", (2400, 1800), (240, 240, 240))
            d = ImageDraw.Draw(img)
            d.text((1200, 900), "Panel not rendered", fill=(150, 150, 150), anchor="mm")
            panels.append(img)

    # Normalize all panels to the same size
    target_w, target_h = 2400, 1800
    resized = []
    for img in panels:
        r = min(target_w / img.width, target_h / img.height)
        new_w, new_h = int(img.width * r), int(img.height * r)
        img_r = img.resize((new_w, new_h), Image.LANCZOS)
        canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))
        canvas.paste(img_r, ((target_w - new_w) // 2, (target_h - new_h) // 2))
        resized.append(canvas)

    margin = 60
    label_margin = 50
    total_w = target_w * 2 + margin * 3
    total_h = target_h * 2 + margin * 3 + label_margin

    composite = Image.new("RGB", (total_w, total_h), (255, 255, 255))
    draw = ImageDraw.Draw(composite)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 48)
    except Exception:
        font = ImageFont.load_default()

    positions_2x2 = [
        (margin, margin + label_margin),
        (margin * 2 + target_w, margin + label_margin),
        (margin, margin * 2 + target_h + label_margin),
        (margin * 2 + target_w, margin * 2 + target_h + label_margin),
    ]
    labels = ["(a)", "(b)", "(c)", "(d)"]

    for (x, y), img, label in zip(positions_2x2, resized, labels):
        composite.paste(img, (x, y))
        draw.text((x + 15, y - label_margin + 5), label, fill=(0, 0, 0), font=font)

    composite.save(output_path, quality=95)
    pdf_path = output_path.replace(".png", ".pdf")
    composite.save(pdf_path)
    print(f"\n  Final composite saved: {output_path}")
    print(f"  Final composite saved: {pdf_path}")
    return output_path


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Figure 10: Anatomy of Condensation")
    parser.add_argument("--panel", choices=["a", "b", "c", "d", "all"], default="all")
    parser.add_argument("--no-blender", action="store_true", help="Skip Blender panels")
    args = parser.parse_args()

    print("=" * 60)
    print("Figure 10 — Anatomy of Condensation (Nature Cover)")
    print("=" * 60)

    panel_paths = [None, None, None, None]

    if args.panel in ("c", "all"):
        print("\n[Panel C] Zone Folding (matplotlib)...")
        panel_paths[2] = generate_panel_c()

    if not args.no_blender:
        if not blender_ping():
            print("\n⚠  Blender MCP not reachable on localhost:9876")
            print("   Please start Blender and enable the BlenderMCP addon.")
            print("   Skipping Blender panels (A, B, D-final).\n")
            args.no_blender = True

    if args.panel in ("a", "all") and not args.no_blender:
        print("\n[Panel A] Acoustic Blueprint (Blender)...")
        panel_paths[0] = generate_panel_a()

    if args.panel in ("b", "all") and not args.no_blender:
        print("\n[Panel B] Topotactic Collapse (Blender)...")
        panel_paths[1] = generate_panel_b()

    if args.panel in ("d", "all"):
        print("\n[Panel D] Ostwald Ripening (OVITO)...")
        panel_paths[3] = generate_panel_d()

    if args.panel == "all":
        print("\n[Composite] Assembling 2×2 grid...")
        composite_figure(panel_paths)

    print("\nDone.")


if __name__ == "__main__":
    main()
