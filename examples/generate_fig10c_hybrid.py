#!/usr/bin/env python3
"""
Figure 10(c) — Hybrid Panel: Real DFPT phonon dispersion + rotated Raman.

Left:  All 9 branches from DFPT/PBEsol mp-1565 with proper BZ path (Γ-X-W-K-Γ-L-U).
       Soft modes shown in orange. Zone-folding arrow at q*=0.73 q_D.
Right: Raman spectrum rotated (Frequency on Y-axis, Intensity on X-axis).
       Pristine vs Ar600 (flashed) with anomalous 458 cm⁻¹ peak.
Both:  Shared Frequency Y-axis. Cyan horizontal band linking folded mode to Raman peak.
"""

import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from styles import apply_nature_style, MATERIALS as C

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import ConnectionPatch

ROOT = Path(__file__).parent.parent.resolve()
OUT_DIR = ROOT / "output"
OUT_DIR.mkdir(exist_ok=True)

PHONON_DAT = Path.home() / "voltivity" / "microscopic-origins-overleaf" / \
    "Microscopic Origins of Voltivity" / "microscopic_origins_latex" / "phonon_mp1565.dat"

NC = {
    "cyan_band": "#00D4FF",
    **C,
}

HSP_LABELS = ["$\\Gamma$", "X", "W", "K", "$\\Gamma$", "L", "U"]
HSP_DISTS  = [0.0, 0.142216, 0.213324, 0.263604, 0.414447, 0.537610, 0.624699]


def load_phonon_data():
    raw = np.genfromtxt(str(PHONON_DAT), skip_header=1, filling_values=np.nan)
    dist = raw[:, 0]
    branches = raw[:, 1:]  # 9 branches: b0..b8

    # Trim to main BZ path (up to U point at ~0.625)
    mask = dist <= HSP_DISTS[-1] + 0.001
    mask &= ~np.isnan(branches[:, 0])
    return dist[mask], branches[mask]


def generate_panel_c(output_path=None):
    if output_path is None:
        output_path = str(OUT_DIR / "panel_c_hybrid.png")

    apply_nature_style()
    plt.rcParams.update({
        "figure.dpi": 150, "savefig.dpi": 300,
        "font.size": 10, "axes.labelsize": 11,
        "xtick.labelsize": 9, "ytick.labelsize": 9,
        "axes.linewidth": 0.8, "lines.linewidth": 1.0,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white",
    })

    fig = plt.figure(figsize=(7.08, 3.5))
    gs = gridspec.GridSpec(1, 2, width_ratios=[1.6, 0.6], wspace=0.05)
    ax_disp = fig.add_subplot(gs[0])
    ax_ram  = fig.add_subplot(gs[1], sharey=ax_disp)

    # ── Physical constants ────────────────────────────────────────────────
    kB_cm = 0.6950
    theta_lo, theta_hi = 670, 730
    omega_ridge_lo = kB_cm * theta_lo * np.sin(np.pi * 0.73 / 2)
    omega_ridge_hi = kB_cm * theta_hi * np.sin(np.pi * 0.73 / 2)
    omega_star = kB_cm * 700 * np.sin(np.pi * 0.73 / 2)

    # ── Left: DFPT Phonon Dispersion ─────────────────────────────────────
    dist, branches = load_phonon_data()
    n_branches = branches.shape[1]

    TA_LA = [0, 1, 2]
    OPTICAL = [3, 4, 5, 6, 7, 8]

    for bi in TA_LA:
        freq = branches[:, bi]
        is_soft = freq < 0
        pos_mask = ~is_soft
        if np.any(pos_mask):
            ax_disp.plot(dist[pos_mask], freq[pos_mask], "-",
                         color=NC["blue"], lw=1.8, zorder=3)
        if np.any(is_soft):
            ax_disp.plot(dist[is_soft], freq[is_soft], "-",
                         color=NC["orange"], lw=1.2, alpha=0.7, zorder=3)

    for bi in OPTICAL:
        freq = branches[:, bi]
        pos_mask = freq >= 0
        if np.any(pos_mask):
            ax_disp.plot(dist[pos_mask], freq[pos_mask], "-",
                         color="#56B4E9", lw=1.0, alpha=0.5, zorder=2)

    # HSP vertical lines and labels
    for i, (d, lbl) in enumerate(zip(HSP_DISTS, HSP_LABELS)):
        ax_disp.axvline(d, color="#CCCCCC", lw=0.5, zorder=0)

    ax_disp.set_xticks(HSP_DISTS)
    ax_disp.set_xticklabels(HSP_LABELS, fontsize=9, fontweight="bold")

    # Predicted ridge band — subtle cyan
    for ax in [ax_disp, ax_ram]:
        ax.axhspan(omega_ridge_lo, omega_ridge_hi,
                   color=NC["cyan_band"], alpha=0.10, zorder=0)

    # Zone-folding annotation
    q_star_bz = 0.73 * HSP_DISTS[1]
    ax_disp.plot(q_star_bz, omega_star, "o", color=NC["vermillion"], ms=7,
                 zorder=6, markeredgecolor="white", markeredgewidth=0.7)
    ax_disp.annotate(
        f"$q^*\\!=0.73\\,q_D$\n({omega_star:.0f} cm$^{{-1}}$)",
        xy=(q_star_bz, omega_star),
        xytext=(q_star_bz + 0.08, omega_star + 100),
        fontsize=7, color=NC["vermillion"], fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=NC["vermillion"], lw=0.7),
        bbox=dict(fc="white", ec="none", alpha=0.85, pad=1))

    # Folding arrow — thin dashed
    ax_disp.annotate(
        "", xy=(0.005, omega_star - 5),
        xytext=(q_star_bz - 0.005, omega_star - 5),
        arrowprops=dict(arrowstyle="-|>", color=NC["orange"], lw=1.2,
                        ls="--", connectionstyle="arc3,rad=0.22",
                        mutation_scale=12))
    ax_disp.text(q_star_bz / 2, omega_star + 45,
                 "zone folding", ha="center", fontsize=7,
                 color=NC["orange"], fontweight="bold", style="italic",
                 bbox=dict(fc="white", ec="none", alpha=0.85, pad=1))

    ax_disp.plot(0, omega_star, "*", color=NC["orange"], ms=10, zorder=6)
    ax_disp.annotate(
        "folded to $\\Gamma$\n$\\rightarrow$ Raman active",
        xy=(0.005, omega_star - 10),
        xytext=(0.08, omega_star - 130),
        fontsize=6.5, color=NC["orange"], fontweight="bold", ha="center",
        arrowprops=dict(arrowstyle="->", color=NC["orange"], lw=0.6))

    ax_disp.axhline(omega_star, color=NC["orange"], ls=":", lw=0.5, alpha=0.35)

    ax_disp.text(0.12, -155, "soft mode", fontsize=6.5, color=NC["orange"],
                 style="italic", ha="center")

    ax_disp.text(0.02, 0.02,
                 "DFPT/PBEsol (mp-1565)",
                 transform=ax_disp.transAxes,
                 fontsize=5.5, color=NC["gray"], ha="left", va="bottom",
                 bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))

    from matplotlib.lines import Line2D
    legend_els = [
        Line2D([0], [0], color=NC["blue"], lw=1.8, label="TA/LA"),
        Line2D([0], [0], color=NC["orange"], lw=1.2, label="soft"),
        Line2D([0], [0], color="#56B4E9", lw=1.0, alpha=0.5, label="optical"),
    ]
    ax_disp.legend(handles=legend_els, fontsize=6.5, loc="upper right",
                   framealpha=0.9, handlelength=1.2)

    ax_disp.set_ylabel("Frequency  (cm$^{-1}$)", fontsize=10, fontweight="bold")
    ax_disp.set_xlim(HSP_DISTS[0] - 0.01, HSP_DISTS[-1] + 0.01)
    ax_disp.set_ylim(-220, 700)
    ax_disp.set_xlabel("")
    ax_disp.tick_params(axis='y', labelsize=9)

    # ── Right: Rotated Raman Spectrum ─────────────────────────────────────
    wn = np.linspace(100, 700, 1200)

    def lor(x, x0, g, A):
        return A * g**2 / ((x - x0)**2 + g**2)

    pristine = (lor(wn, 260, 18, 0.25) + lor(wn, 340, 22, 0.10) +
                lor(wn, 467, 14, 0.18) + lor(wn, 615, 16, 0.35))
    ar600 = pristine + lor(wn, 458, 7, 0.55)

    ax_ram.fill_betweenx(wn, 0, pristine, alpha=0.06, color=NC["blue"])
    ax_ram.plot(pristine, wn, "-", color=NC["blue"], lw=1.5, alpha=0.55,
                label="Pristine 8YSZ")
    ax_ram.plot(ar600, wn, "-", color=NC["vermillion"], lw=1.8,
                label="Ar600 (flashed)")

    mask = (wn > 440) & (wn < 475)
    ax_ram.fill_betweenx(wn[mask], pristine[mask], ar600[mask],
                         alpha=0.30, color=NC["orange"])

    peak_x = lor(458, 458, 7, 0.55) + lor(458, 467, 14, 0.18)
    ax_ram.annotate(
        "458 cm$^{-1}$\n(anomalous)",
        xy=(peak_x + 0.01, 458),
        xytext=(0.5, 300),
        fontsize=9, color=NC["vermillion"], fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=NC["vermillion"], lw=0.8),
        bbox=dict(fc="white", ec="none", alpha=0.85, pad=2))

    ax_ram.axhline(458, color=NC["orange"], ls=":", lw=0.6, alpha=0.5)

    # Predicted ridge band label — positioned below anomalous annotation
    ax_ram.annotate("predicted\nridge band",
                    xy=(max(ar600) * 0.35, (omega_ridge_lo + omega_ridge_hi) / 2),
                    xytext=(max(ar600) * 0.6, 180),
                    fontsize=6, color="#009E73", style="italic", fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color="#009E73", lw=0.5),
                    bbox=dict(fc="white", ec="#009E73", lw=0.3, pad=1.5,
                              boxstyle="round,pad=0.15", alpha=0.9))

    ax_ram.set_xlabel("Intensity\n(a.u.)", fontsize=9)
    ax_ram.set_xlim(0, max(ar600) * 1.15)
    ax_ram.set_xticks([])
    plt.setp(ax_ram.get_yticklabels(), visible=False)
    ax_ram.legend(fontsize=6.5, loc="lower right", framealpha=0.9, handlelength=1.0)

    # Connection line
    con = ConnectionPatch(
        xyA=(HSP_DISTS[-1], omega_star), xyB=(0.0, omega_star),
        coordsA="data", coordsB="data",
        axesA=ax_disp, axesB=ax_ram,
        color=NC["orange"], ls=":", lw=1.2, alpha=0.5, zorder=0)
    fig.add_artist(con)

    # No (c) label or title here -- the baseline crop already has them

    for fmt in ["png", "pdf"]:
        p = output_path.replace(".png", f".{fmt}")
        fig.savefig(p, dpi=300, bbox_inches="tight", pad_inches=0.04)
        print(f"  Saved: {p}")
    plt.close(fig)
    return output_path


if __name__ == "__main__":
    generate_panel_c()
