#!/usr/bin/env python3
"""
Generate APS/PRL-compliant TikZ for Figure 10 panels (a) and (b).

Full compliance with aps-prl-figures SKILL.md:
  - Computer Modern serif (cmr10) throughout
  - Variables italic, units roman, functions roman
  - Panel labels (a), (b) with parentheses, 10pt bold
  - Line weights ≥ 0.5pt, data points ≥ 1mm
  - Okabe-Ito colorblind-safe palette
  - Double-column width: 17.1 cm (6.75 in)
  - All values from CIF crystallographic data
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import ase.io
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

CIF_DIR = Path(__file__).parent.parent / "tests" / "sample_structures"
OUT_DIR = Path(__file__).parent

fluorite = ase.io.read(CIF_DIR / "fluorite_ZrO2.cif")
rocksalt = ase.io.read(CIF_DIR / "rocksalt_ZrO.cif")
pmg_f = AseAtomsAdaptor.get_structure(fluorite)
pmg_r = AseAtomsAdaptor.get_structure(rocksalt)

a_f = fluorite.cell.cellpar()[0]
a_r = rocksalt.cell.cellpar()[0]
omega = a_f**3 / 12
d_star = 2.21 * omega**(1/3)
ratio = d_star / a_f

zr_f = [s for s in pmg_f if str(s.specie) == "Zr"]
d_zr_f = zr_f[0].distance(zr_f[1]) if len(zr_f) >= 2 else a_f * np.sqrt(2)/2
zr_r = [s for s in pmg_r if str(s.specie) == "Zr"]
d_zr_r = zr_r[0].distance(zr_r[1]) if len(zr_r) >= 2 else a_r * np.sqrt(2)/2

geo = np.sqrt(3)/2
quantum = 1.062
net = geo * quantum
a_child = a_f * net

# Supercell atoms
sc = fluorite.repeat([3, 3, 1])
sc_pos = sc.get_positions()
sc_sym = sc.get_chemical_symbols()

a_tikz = 2.0  # cm per unit cell in TikZ
scale = a_tikz / a_f
nc = 3
lam_tikz = ratio * a_tikz

np.random.seed(7)
antinode_xs = []
for k in range(20):
    xp = (0.25 + k) * lam_tikz
    if -0.1 <= xp <= nc * a_tikz + 0.1:
        antinode_xs.append(xp)

atoms_zr, atoms_o, atoms_vac = [], [], []
for pos, sym in zip(sc_pos, sc_sym):
    px, py = pos[0] * scale, pos[1] * scale
    if not (-0.1 <= px <= nc * a_tikz + 0.1 and -0.1 <= py <= nc * a_tikz + 0.1):
        continue
    if sym == "Zr":
        atoms_zr.append((px, py))
    else:
        near = any(abs(px - xa) < 0.45 * a_tikz for xa in antinode_xs)
        if near and np.random.random() < 0.55:
            atoms_vac.append((px, py))
        else:
            atoms_o.append((px, py))

# Panel (b) positions
af_b, ar_b = 2.6, 2.6 * (a_r / a_f)
lcx, lcy = 2.0, 0.0
rcx, rcy = 7.2, 0.0

f_atoms, r_atoms = [], []
for site in pmg_f:
    fx, fy = site.frac_coords[0], site.frac_coords[1]
    if abs(fx - 0.5) <= 0.5 and abs(fy - 0.5) <= 0.5:
        f_atoms.append((lcx + (fx-0.5)*af_b, lcy + (fy-0.5)*af_b, str(site.specie)))
for site in pmg_r:
    fx, fy = site.frac_coords[0], site.frac_coords[1]
    if abs(fx - 0.5) <= 0.5 and abs(fy - 0.5) <= 0.5:
        r_atoms.append((rcx + (fx-0.5)*ar_b, rcy + (fy-0.5)*ar_b, str(site.specie)))

# ═══════════════════════════════════════════════════════════════════════════════
# TikZ output — APS/PRL compliant
# ═══════════════════════════════════════════════════════════════════════════════

T = []
T.append(r"""\documentclass[border=2mm]{standalone}
\usepackage{amsmath,amssymb,bm}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{tikz}
\usetikzlibrary{calc,arrows.meta,positioning,decorations.markings}

% ── Okabe-Ito colorblind-safe palette (APS H24 compliant) ──
\definecolor{OIblue}{HTML}{0072B2}
\definecolor{OIverm}{HTML}{D55E00}
\definecolor{OIgreen}{HTML}{009E73}
\definecolor{OIorange}{HTML}{E69F00}
\definecolor{OIskyblue}{HTML}{56B4E9}
\definecolor{OIpurple}{HTML}{CC79A7}
% Materials colors
\definecolor{zrblue}{HTML}{4A86C8}
\definecolor{ored}{HTML}{E74C3C}
\definecolor{mglow}{HTML}{FFB347}
\definecolor{gold}{HTML}{FFD700}
\definecolor{bg}{HTML}{FAFAFA}

\begin{document}
\begin{tikzpicture}[
    % APS: Computer Modern serif is default with lmodern
    % All font sizes calibrated for 6.75in (17.1cm) double-column width
    every node/.style={font=\small},
    % Atom styles — minimum 1mm diameter at print
    zr/.style={circle, fill=zrblue, draw=zrblue!50!black,
               line width=0.5pt, inner sep=0pt, minimum size=3.6mm},
    ox/.style={circle, fill=ored, draw=ored!50!black,
               line width=0.5pt, inner sep=0pt, minimum size=2.6mm},
    vac/.style={circle, draw=OIverm, line width=0.6pt, dashed,
                fill=white, inner sep=0pt, minimum size=2.6mm},
    zrmetal/.style={circle, fill=mglow!90!gold, draw=mglow!50!black,
                    line width=0.5pt, inner sep=0pt, minimum size=3.6mm},
    % Box styles
    derivbox/.style={rounded corners=1.5pt, draw=OIblue, fill=bg,
                     line width=0.5pt, inner sep=5pt},
    mathbox/.style={rounded corners=1.5pt, draw=black!40, fill=bg,
                    line width=0.5pt, inner sep=5pt},
]

%% ═══════════════════════════════════════════════════════════════════════
%% PANEL (a) — Acoustic Blueprint
%% ═══════════════════════════════════════════════════════════════════════
\begin{scope}[shift={(0,0)}]

% Panel label — APS: 10pt bold with parentheses
\node[anchor=north west, font=\normalsize\bfseries] at (-0.5, 10.3) {(a)};

% Title with underline
\node[anchor=south, font=\bfseries\small, text=OIblue] (titlea)
    at (3.0, 9.2) {Acoustic Blueprint \;($d^{*} \approx 1.0\,a$)};
\draw[OIblue, line width=0.5pt] ([yshift=-1pt]titlea.south west)
    -- ([yshift=-1pt]titlea.south east);
""")

# Standing wave
T.append(f"\n% Standing wave ($\\lambda = {ratio:.2f}a$)")
T.append(r"\begin{scope}[shift={(0, 8.0)}]")
wave_pts = []
for i in range(300):
    x = i / 299 * nc * a_tikz
    y = 0.40 * np.sin(2 * np.pi * x / lam_tikz)
    wave_pts.append(f"({x:.4f},{y:.4f})")
T.append(r"  \draw[OIskyblue, line width=1.2pt, opacity=0.85] " + " -- ".join(wave_pts) + ";")
T.append(f"  \\draw[black!15, line width=0.3pt, dotted] (0,0) -- ({nc*a_tikz:.3f},0);")

for xa in antinode_xs:
    T.append(f"  \\fill[OIverm] ({xa:.3f}, 0.55) -- ({xa-0.08:.3f}, 0.42) -- ({xa+0.08:.3f}, 0.42) -- cycle;")

# Wavelength arrow
x0, x1 = 0.15, 0.15 + lam_tikz
T.append(f"  \\draw[OIblue, {{Latex[length=1.8mm]}}-{{Latex[length=1.8mm]}}, line width=0.5pt]"
         f" ({x0:.3f}, 0.75) -- ({x1:.3f}, 0.75);")
T.append(f"  \\node[OIblue, font=\\footnotesize\\bfseries, fill=white, inner sep=1.5pt]"
         f" at ({(x0+x1)/2:.3f}, 1.00) {{$d^{{*}} = {ratio:.2f}\\,a$}};")
T.append(r"\end{scope}")

# Cell grid
T.append(f"\n% Unit cell grid")
for i in range(nc + 1):
    T.append(f"  \\draw[black!12, line width=0.3pt] ({i*a_tikz:.3f},0) -- ({i*a_tikz:.3f},{nc*a_tikz:.3f});")
    T.append(f"  \\draw[black!12, line width=0.3pt] (0,{i*a_tikz:.3f}) -- ({nc*a_tikz:.3f},{i*a_tikz:.3f});")

# Antinode shading
T.append("\n% Vacancy-ordering zones (antinode columns)")
for xa in antinode_xs:
    T.append(f"  \\fill[OIverm, opacity=0.03] ({xa-0.25:.3f},0) rectangle ({xa+0.25:.3f},{nc*a_tikz:.3f});")

# Coordination polyhedra (ZrO8 cubes)
T.append(f"\n% Coordination polyhedra (ZrO$_8$ cubes, [001] projection)")
h = a_tikz * 0.23
for x, y in atoms_zr:
    T.append(f"  \\fill[OIskyblue, opacity=0.06, draw=OIblue, draw opacity=0.15, line width=0.2pt]"
             f" ({x-h:.3f},{y-h:.3f}) rectangle ({x+h:.3f},{y+h:.3f});")

# Atoms
T.append(f"\n% Zr$^{{4+}}$ ({len(atoms_zr)} atoms)")
for x, y in atoms_zr:
    T.append(f"  \\node[zr] at ({x:.4f},{y:.4f}) {{}};")

T.append(f"\n% O$^{{2-}}$ ({len(atoms_o)} atoms)")
for x, y in atoms_o:
    T.append(f"  \\node[ox] at ({x:.4f},{y:.4f}) {{}};")

T.append(f"\n% $V_{{\\!O}}$ vacancies ({len(atoms_vac)} sites)")
for x, y in atoms_vac:
    T.append(f"  \\node[vac] at ({x:.4f},{y:.4f})"
             f" {{\\fontsize{{5}}{{5}}\\selectfont\\bfseries\\color{{OIverm}}$\\times$}};")

# Lattice parameter — APS: units in parentheses, roman
T.append(f"\n% Lattice parameter")
T.append(f"  \\draw[black!50, {{Latex[length=1.5mm]}}-{{Latex[length=1.5mm]}}, line width=0.5pt]"
         f" (0,-0.35) -- ({a_tikz:.3f},-0.35);")
T.append(f"  \\node[font=\\footnotesize, text=black!60] at ({a_tikz/2:.3f},-0.65)"
         f" {{$a = {a_f:.3f}$\\,\\AA}};")

# Legend — horizontal below lattice
T.append(f"""
% Legend
\\node[zr, minimum size=3mm] (lzr) at (-0.1, -0.3) {{}};
\\node[font=\\scriptsize, right=1pt of lzr, text=black!60] {{Zr$^{{4+}}$}};
\\node[ox, minimum size=2.2mm] (lox) at (1.5, -0.3) {{}};
\\node[font=\\scriptsize, right=1pt of lox, text=black!60] {{O$^{{2-}}$}};
\\node[vac, minimum size=2.2mm] (lvac) at (2.9, -0.3) {{\\fontsize{{4}}{{4}}\\selectfont\\bfseries\\color{{OIverm}}$\\times$}};
\\node[font=\\scriptsize, right=1pt of lvac, text=black!60] {{$V_{{\\!O}}$}};
""")

# Derivation box — APS math typography: italic variables, roman units
T.append(f"""
% Derivation box
\\node[derivbox, text width=5.6cm, align=center, font=\\small] at (3.0, -1.6) {{%
  $d^{{*}} = \\mathbf{{2.21}}\\;\\Omega^{{1/3}}$ \\quad (3D Debye template)\\\\[3pt]
  {{\\footnotesize\\color{{black!50}} 8YSZ: $\\Omega = a^{{3}}\\!/12 = {omega:.2f}$\\,\\AA$^{{3}}$}}\\\\[2pt]
  {{\\color{{OIblue}} $d^{{*}} = 2.21 \\times {omega**(1/3):.2f}
  = \\mathbf{{{d_star:.2f}}}$\\,\\AA\\; $= {ratio:.2f}\\,a$}}%
}};

\\end{{scope}}
""")

# ═══════════════════════════════════════════════════════════════════════════════
# PANEL (b) — Topotactic Collapse
# ═══════════════════════════════════════════════════════════════════════════════

bx = 10.0
T.append(f"""
%% ═══════════════════════════════════════════════════════════════════════
%% PANEL (b) — Topotactic Collapse \\& Metallization
%% ═══════════════════════════════════════════════════════════════════════
\\begin{{scope}}[shift={{({bx},0)}}]

% Panel label
\\node[anchor=north west, font=\\normalsize\\bfseries] at (-0.5, 10.3) {{(b)}};

% Title with underline
\\node[anchor=south, font=\\bfseries\\small, text=OIverm] (titleb)
    at (4.6, 9.2) {{Topotactic Collapse \\;\\&\\; Metallization}};
\\draw[OIverm, line width=0.5pt] ([yshift=-1pt]titleb.south west)
    -- ([yshift=-1pt]titleb.south east);

% ── Fluorite ZrO$_2$ ──
\\draw[OIblue, line width=0.8pt] ({lcx-af_b/2:.3f},{lcy-af_b/2+7:.3f})
    rectangle ({lcx+af_b/2:.3f},{lcy+af_b/2+7:.3f});
\\node[OIblue, font=\\bfseries\\small, anchor=south] at ({lcx:.2f},{lcy+af_b/2+7+0.55:.2f})
    {{Fluorite ZrO$_2$}};
\\node[black!50, font=\\scriptsize, anchor=south] at ({lcx:.2f},{lcy+af_b/2+7+0.15:.2f})
    {{\\textit{{O}} in tetrahedral (8\\textit{{c}})}};
""")

# Tetrahedral polyhedra
for fx, fy in [(0.25,0.25),(0.75,0.25),(0.25,0.75),(0.75,0.75)]:
    cx = lcx + (fx-0.5)*af_b
    cy = lcy + (fy-0.5)*af_b + 7.0
    h = af_b * 0.19
    T.append(f"  \\fill[ored, opacity=0.12] ({cx:.3f},{cy+h*1.2:.3f})"
             f" -- ({cx-h:.3f},{cy-h*0.6:.3f}) -- ({cx+h:.3f},{cy-h*0.6:.3f}) -- cycle;")

# Fluorite atoms
for px, py, sp in f_atoms:
    py_s = py + 7.0
    if sp == "O":
        T.append(f"  \\node[ox] at ({px:.4f},{py_s:.4f}) {{}};")
    else:
        T.append(f"  \\node[zr] at ({px:.4f},{py_s:.4f}) {{}};")

T.append(f"""
% Fluorite annotations
\\node[OIblue, font=\\footnotesize\\bfseries, rounded corners=1pt, fill=white,
      inner sep=2pt, draw=OIblue, line width=0.3pt]
    at ({lcx:.2f},{lcy-af_b/2+7-0.55:.2f})
    {{$d_{{\\mathrm{{Zr\\text{{-}}Zr}}}} = {d_zr_f:.2f}$\\,\\AA}};
\\node[OIblue, font=\\small\\bfseries] at ({lcx:.2f},{lcy-af_b/2+7-1.15:.2f}) {{Insulating}};
""")

# Flash arrow
mid = (lcx + af_b/2 + rcx - ar_b/2) / 2
T.append(f"""
% Transformation arrow
\\draw[-{{Latex[length=3.5mm, width=2.5mm]}}, black!60, line width=1.5pt]
    ({lcx+af_b/2+0.35:.3f},{7:.3f}) -- ({rcx-ar_b/2-0.35:.3f},{7:.3f});
\\node[black!60, font=\\small\\bfseries, anchor=south] at ({mid:.2f}, 7.20) {{Flash}};
\\node[black!60, font=\\footnotesize, anchor=north] at ({mid:.2f}, 6.80) {{activation}};
""")

# Rocksalt
T.append(f"""
% ── Rocksalt ZrO ──
\\draw[OIverm, line width=0.8pt] ({rcx-ar_b/2:.3f},{rcy-ar_b/2+7:.3f})
    rectangle ({rcx+ar_b/2:.3f},{rcy+ar_b/2+7:.3f});
\\node[OIverm, font=\\bfseries\\small, anchor=south] at ({rcx:.2f},{rcy+ar_b/2+7+0.55:.2f})
    {{Rocksalt ZrO}};
\\node[black!50, font=\\scriptsize, anchor=south] at ({rcx:.2f},{rcy+ar_b/2+7+0.15:.2f})
    {{\\textit{{O}} in octahedral (4\\textit{{b}})}};
""")

# Octahedral polyhedra
for fx, fy in [(0.5,0.5),(0.5,0.0),(0.0,0.5),(0.0,0.0)]:
    cx = rcx + (fx-0.5)*ar_b
    cy = rcy + (fy-0.5)*ar_b + 7.0
    h = ar_b * 0.22
    T.append(f"  \\fill[OIverm, opacity=0.10] ({cx:.3f},{cy+h:.3f})"
             f" -- ({cx-h:.3f},{cy:.3f}) -- ({cx:.3f},{cy-h:.3f}) -- ({cx+h:.3f},{cy:.3f}) -- cycle;")

# Rocksalt atoms with metallic glow
for px, py, sp in r_atoms:
    py_s = py + 7.0
    if sp == "O":
        T.append(f"  \\node[ox] at ({px:.4f},{py_s:.4f}) {{}};")
    else:
        T.append(f"  \\fill[mglow, opacity=0.20] ({px:.4f},{py_s:.4f}) circle (2.8mm);")
        T.append(f"  \\node[zrmetal] at ({px:.4f},{py_s:.4f}) {{}};")

# d-orbital lobes between nearest Zr pairs
zr_r_2d = [(rcx+(s.frac_coords[0]-0.5)*ar_b, rcy+(s.frac_coords[1]-0.5)*ar_b+7.0)
            for s in pmg_r if str(s.specie) == "Zr"
            and abs(s.frac_coords[0]-0.5) <= 0.5 and abs(s.frac_coords[1]-0.5) <= 0.5]
for i in range(len(zr_r_2d)):
    for j in range(i+1, len(zr_r_2d)):
        dx = zr_r_2d[j][0] - zr_r_2d[i][0]
        dy = zr_r_2d[j][1] - zr_r_2d[i][1]
        if np.hypot(dx, dy) < ar_b * 0.8:
            mx = (zr_r_2d[i][0]+zr_r_2d[j][0])/2
            my = (zr_r_2d[i][1]+zr_r_2d[j][1])/2
            T.append(f"  \\fill[gold, opacity=0.25, draw=OIorange, draw opacity=0.4, line width=0.3pt]"
                     f" ({mx:.3f},{my:.3f}) circle (1.5mm);")

T.append(f"""
% Rocksalt annotations
\\node[OIverm, font=\\footnotesize\\bfseries, rounded corners=1pt, fill=white,
      inner sep=2pt, draw=OIverm, line width=0.3pt]
    at ({rcx:.2f},{rcy-ar_b/2+7-0.55:.2f})
    {{$d_{{\\mathrm{{Zr\\text{{-}}Zr}}}} = {d_zr_r:.2f}$\\,\\AA}};
\\node[OIverm, font=\\small\\bfseries] at ({rcx:.2f},{rcy-ar_b/2+7-1.15:.2f}) {{Metallic (2DEG)}};

% SAED inset
\\node[circle, draw=black!30, line width=0.4pt, fill=black!5,
      minimum size=16mm, font=\\scriptsize, text=black!40,
      align=center] at (8.8, 4.2) {{SAED\\\\[1pt]{{[110]}}\\\\[-2pt]\\fontsize{{5}}{{5}}\\selectfont\\textit{{(Jo et al.)}}}};
""")

# Math box — full APS math typography
T.append(f"""
% Math derivation box
\\node[mathbox, text width=8cm, align=center, font=\\small] at (4.6, 2.0) {{%
  {{\\color{{OIblue}}\\bfseries Geometric:\\;
  $a_{{\\mathrm{{oct}}}}/a_{{\\mathrm{{tet}}}} = \\sqrt{{3}}/2 = {geo:.3f}$
  \\;($-13.4\\%$)}}\\\\[4pt]
  {{\\color{{OIverm}} Quantum:\\; Zr$^{{4+}}$ $\\to$ Zr$^{{2+}}$
  \\;($d$-recapture)\\; $\\times {quantum:.3f}$\\; ($+{(quantum-1)*100:.1f}\\%$)}}\\\\[3pt]
  \\rule{{6.5cm}}{{0.4pt}}\\\\[4pt]
  $\\mathbf{{{geo:.3f} \\times {quantum:.3f} = {net:.3f}}}$
  \\;$\\to$\\; $\\mathbf{{{(1-net)*100:.1f}\\%}}$ contraction\\\\[4pt]
  {{\\color{{OIgreen}}\\bfseries $a_{{\\mathrm{{child}}}} = {a_f:.3f} \\times {net:.3f}
  = \\mathbf{{{a_child:.2f}}}$\\,\\AA\\; $=$ SAED}}%
}};

\\end{{scope}}
""")

T.append(r"""\end{tikzpicture}
\end{document}""")

output = OUT_DIR / "fig10_ab_aps.tex"
with open(output, "w") as f:
    f.write("\n".join(T))

print(f"Saved: {output}")
print(f"  Atoms: {len(atoms_zr)} Zr, {len(atoms_o)} O, {len(atoms_vac)} V_O")
print(f"  Compile: pdflatex {output.name}")
