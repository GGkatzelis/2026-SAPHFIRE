"""SAPHFIRE 2026 — presentation plots.

Spectral composition pie charts in the de Gouw / NOAA VOC style:
solid wedges with thin black outlines, each slice labeled "Name (X%)" on a
leader line with a dot at the rim, colors running around the spectrum
(red -> yellow -> green -> blue -> purple).

Generates one pie per injection category:
  - overall: the 5 surrogate mixtures (+ gases) by inventory mass %
  - one pie per Solution A-D: species within the solution (mixture mass %)
  - the three light gases by relative mass

Run directly to render all PNGs into ./figures/.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

from SAPHFIRE_Injections import load_fingerprint

# --- global presentation style ----------------------------------------------
mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "font.size": 15,
    "figure.dpi": 200,
    "savefig.dpi": 200,
    "savefig.bbox": "tight",
    "savefig.facecolor": "white",
})

FIG_DIR = Path(__file__).with_name("figures")


def spectral_colors(n: int, lighten: float = 0.4) -> list:
    """n soft colors around the spectrum, red -> purple (matches the reference).

    ``lighten`` (0..1) blends each color toward white, turning the vivid
    spectral wheel into the softer pastel tones of the reference figure.
    0 = full saturation, higher = lighter/more washed out.
    """
    cmap = mpl.colormaps["gist_rainbow"]
    white = np.array([1.0, 1.0, 1.0])
    # 0.0 = red ... 0.83 = magenta/purple; stop before it wraps back to red.
    out = []
    for t in np.linspace(0.0, 0.83, n):
        rgb = np.array(cmap(t)[:3])
        soft = (1.0 - lighten) * rgb + lighten * white
        out.append((*soft, 1.0))
    return out


def styled_pie(
    labels: list[str],
    values: list[float],
    *,
    title: str | None = None,
    colors: list | None = None,
    min_pct_label: float = 0.0,
    label_fontsize: float = 18,
    title_fontsize: float = 18,
    startangle: float = 90,
    figsize: tuple[float, float] = (11, 6.5),
    ax=None,
):
    """Render one spectral composition pie in the reference style.

    Parameters
    ----------
    labels, values : slice names and their (unnormalised) weights.
    min_pct_label  : slices below this percentage are drawn but left unlabeled
                     (avoids leader-line clutter on tiny wedges).
    ax             : draw into this axis (for multi-panel figures); if None a
                     new standalone figure is created.
    """
    values = np.asarray(values, dtype=float)
    pct = 100 * values / values.sum()
    if colors is None:
        colors = spectral_colors(len(values))

    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure
    wedges, _ = ax.pie(
        values,
        colors=colors,
        startangle=startangle,  # where the first slice starts (90 = top)
        counterclock=False,     # ... and runs clockwise, like the reference
        wedgeprops={"edgecolor": "white", "linewidth": 1.5},
    )

    # Leader-line labels with a dot at the rim.
    for w, lab, p in zip(wedges, labels, pct):
        if p < min_pct_label:
            continue
        ang = np.deg2rad((w.theta1 + w.theta2) / 2.0)
        x, y = np.cos(ang), np.sin(ang)
        ax.plot([x], [y], marker="o", markersize=5, color="black", zorder=5)
        ha = "left" if x >= 0 else "right"
        conn = f"angle,angleA=0,angleB={np.rad2deg(ang):.1f}"
        ax.annotate(
            f"{lab} ({p:.0f}%)",
            xy=(x, y),
            xytext=(1.35 * np.sign(x), 1.25 * y),
            horizontalalignment=ha,
            va="center",
            fontsize=label_fontsize,
            zorder=4,
            arrowprops=dict(
                arrowstyle="-", color="black", linewidth=1.0,
                connectionstyle=conn,
            ),
        )

    if title:
        ax.set_title(title, fontsize=title_fontsize, fontweight="bold", pad=18)
    ax.set_aspect("equal")
    return fig, ax


# Cleaned display names for slice labels (raw surrogate strings -> presentation).
NAME_MAP = {
    "Actic Acid": "Acetic acid",
    "formaldehyde": "Formaldehyde",
    "2-(3H)Furanoe": "2(3H)-Furanone",
    "50% methyl glyoxal, 50% acrylic acid": "Methylglyoxal + acrylic acid",
    "68% M+P, 10% EB, 23% OX": "Ethylbenzene",
    "a-pinene or whatever monoterpenes you want": "Monoterpenes",
    "ethene": "Ethene",
    "acetylene": "Acetylene",
    "acetonitrile": "Acetonitrile",
    "benzene": "Benzene",
}


# Each solution draws its slice colors from a distinct band of the hue wheel,
# so the four pies use visibly different color schemes with no shared colors
# when shown together. (hsv hue: 0=red, 0.17=yellow, 0.33=green, 0.5=cyan,
# 0.66=blue, 0.83=magenta.)
_HUE_BAND = {
    "A": (0.00, 0.12),   # Phenolic    -> reds / oranges
    "B": (0.15, 0.34),   # Furanoid    -> yellows / greens
    "C": (0.42, 0.60),   # Hydrocarbon -> teals / blues
    "D": (0.66, 0.92),   # Oxygenate   -> blues / purples / magentas
}


def solution_colors(sol: str, n: int, lighten: float = 0.4) -> list:
    """n light colors for one solution, spanning its hue band (distinct shades)."""
    lo, hi = _HUE_BAND[sol]
    cmap = mpl.colormaps["hsv"]
    white = np.array([1.0, 1.0, 1.0])
    ts = np.linspace(lo, hi, n) if n > 1 else [0.5 * (lo + hi)]
    out = []
    for t in ts:
        rgb = np.array(cmap(t)[:3])
        out.append((*((1.0 - lighten) * rgb + lighten * white), 1.0))
    return out


def _short(name: str) -> str:
    """Trim/clean verbose surrogate strings for slice labels."""
    if name in NAME_MAP:
        return NAME_MAP[name]
    return name.split(" or ")[0].split(" + ")[0].strip()


def lump_small(labels, values, *, threshold_pct, other_label="Other"):
    """Roll slices below ``threshold_pct`` of the total into one 'Other' wedge.

    Mirrors the reference figure's 'other OVOCs' / 'other CxHy' convention so
    dense pies stay legible. Kept slices preserve their input order; the
    'Other' wedge is appended last.
    """
    values = np.asarray(values, dtype=float)
    total = values.sum()
    keep_lab, keep_val, other = [], [], 0.0
    for lab, v in zip(labels, values):
        if 100 * v / total >= threshold_pct:
            keep_lab.append(lab)
            keep_val.append(v)
        else:
            other += v
    if other > 0:
        keep_lab.append(other_label)
        keep_val.append(other)
    return keep_lab, keep_val


_SOLUTIONS = {"A": "Phenolic", "B": "Furanoid", "C": "Hydrocarbon", "D": "Oxygenate"}

# Biogenic VOC scenarios (extended experiments) — composition by mass % of
# total VOC, transcribed from the scenario table. (name, mass_pct).
BIOGENIC = {
    "A": {
        "title": "Biogenic Option A — realism-balanced (eucalypt-faithful)",
        "startangle": 0,   # small terpenes (end of list) land on the right edge
        "components": [
            ("Isoprene", 32.1),
            ("1,8-cineole", 20.4),
            ("α-pinene", 11.6),
            ("(E)-β-ocimene", 10.3),
            ("d-limonene", 10.3),
            ("β-pinene", 6.4),
            ("α-phellandrene", 2.6),
            ("p-cymene", 2.5),
            ("β-caryophyllene", 3.9),
        ],
    },
    "B": {
        "title": "Biogenic Option B — MCM-closable (minimal / model-friendly)",
        "startangle": 90,
        "components": [
            ("Isoprene", 32.9),
            ("α-pinene", 23.7),
            ("d-limonene", 21.1),
            ("β-pinene", 18.4),
            ("β-caryophyllene", 3.9),
        ],
    },
}

# Per-solution pie rotation (90 = first slice at top). Solution C starts at the
# right (0) so its big Monoterpenes wedge sweeps the left/bottom and the small
# slices + "other hydrocarbons" land on the right edge instead of crowding top-left.
_START_ANGLE = {"A": 90, "B": 90, "C": 0, "D": 90}


def _solution_slices(fp, sol: str):
    """(labels, values) for one solution, minor species lumped for legibility."""
    sub = fp[fp["solution"] == sol]
    labels = [_short(s) for s in sub["surrogate"]]
    return lump_small(
        labels, list(sub["mixture_mass_pct"]),
        threshold_pct=3.0, other_label=f"other {_SOLUTIONS[sol].lower()}s",
    )


def panel_figure(
    fp,
    *,
    suptitle: str = "SAPHFIRE injection fingerprint — Solutions A–D",
    figsize: tuple[float, float] = (16, 12),
):
    """One figure, four pies: Solutions A–D in a 2×2 block (two left, two right).

    Each solution uses its own distinct color scheme (per-solution hue band),
    so no color is shared across pies. Each pie keeps its standalone look
    (light wedges, white separators, leader-line labels).
    """
    fig = plt.figure(figsize=figsize)
    gs = fig.add_gridspec(2, 2, wspace=0.55, hspace=0.28)
    ax_pos = {
        "A": fig.add_subplot(gs[0, 0]),   # top-left
        "B": fig.add_subplot(gs[0, 1]),   # top-right
        "C": fig.add_subplot(gs[1, 0]),   # bottom-left
        "D": fig.add_subplot(gs[1, 1]),   # bottom-right
    }
    for sol, ax in ax_pos.items():
        labels, values = _solution_slices(fp, sol)
        styled_pie(
            labels, values, ax=ax,
            colors=solution_colors(sol, len(values)),
            title=f"Solution {sol} — {_SOLUTIONS[sol]}",
            label_fontsize=14, title_fontsize=14,
            startangle=_START_ANGLE[sol],
        )

    if suptitle:
        fig.suptitle(suptitle, fontsize=20, fontweight="bold", y=0.97)
    return fig


def render_all(out_dir: Path = FIG_DIR) -> list[Path]:
    out_dir.mkdir(exist_ok=True)
    fp = load_fingerprint()
    written: list[Path] = []

    # 1) Overall: the 5 categories by inventory mass %.
    by_mix = (
        fp.groupby("mixture")["mass_pct"].sum()
        .reindex(["Oxygenate", "Furanoid", "Phenolic", "Hydrocarbon", "Gases"])
    )
    fig, _ = styled_pie(
        list(by_mix.index), list(by_mix.values),
        title="SAPHFIRE injection fingerprint — by mixture",
    )
    p = out_dir / "pie_overall_mixtures.png"
    fig.savefig(p); plt.close(fig); written.append(p)

    # 2) One pie per liquid solution (species within the solution).
    for sol, mix in _SOLUTIONS.items():
        labels, values = _solution_slices(fp, sol)
        fig, _ = styled_pie(
            labels, values,
            colors=solution_colors(sol, len(values)),
            title=f"Solution {sol} — {mix} mixture",
            startangle=_START_ANGLE[sol],
        )
        p = out_dir / f"pie_solution_{sol}_{mix.lower()}.png"
        fig.savefig(p); plt.close(fig); written.append(p)

    # 2b) Combined panel: Solutions A-D (2x2) + gas phase, all in one figure.
    fig = panel_figure(fp)
    p = out_dir / "pie_panel_all.png"
    fig.savefig(p); plt.close(fig); written.append(p)

    # 3) The three light gases by relative mass.
    gases = fp[fp["mixture"] == "Gases"]
    fig, _ = styled_pie(
        [_short(s) for s in gases["surrogate"]], list(gases["mass_pct"]),
        title="Gas-phase species",
    )
    p = out_dir / "pie_gases.png"
    fig.savefig(p); plt.close(fig); written.append(p)

    # 4) Biogenic VOC scenarios (extended experiments), each on its own.
    for opt, spec in BIOGENIC.items():
        labels = [c[0] for c in spec["components"]]
        values = [c[1] for c in spec["components"]]
        fig, _ = styled_pie(
            labels, values, title=spec["title"],
            startangle=spec["startangle"],
        )
        p = out_dir / f"pie_biogenic_option{opt}.png"
        fig.savefig(p); plt.close(fig); written.append(p)

    return written


if __name__ == "__main__":
    paths = render_all()
    print(f"Wrote {len(paths)} figures to {FIG_DIR}:")
    for p in paths:
        print(f"  - {p.name}")
