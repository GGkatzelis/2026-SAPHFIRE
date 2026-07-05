"""CHARON-FUSION quicklook figures (matplotlib).

Four classic panels, styled to match the MCM_SAPHIR_Tool "Chemical Space" tab:

* ``plot_timeline``      - ion time series over the experiment
* ``plot_c_o``          - composition by carbon number (stacked by nO and family)
* ``plot_vbs``          - volatility basis set: log10(C*) vs carbon oxidation state
* ``plot_mass_defect``  - mass defect vs mass, sized/coloured by family

Each returns a matplotlib Figure and never calls ``show()`` so they work
head-less (Streamlit, video frames).
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .chemistry import CLASS_COLORS, CLASS_ORDER

_CITE = "Li et al., ACP 16, 3327 (2016) · Kroll et al., Nat. Chem. 3, 133 (2011)"


# ── helpers ──────────────────────────────────────────────────────────────
def species_with_conc(prop_table: pd.DataFrame, conc, min_conc: float = 0.0,
                       max_err_mda: float | None = None) -> pd.DataFrame:
    """Assigned ions joined with a per-ion concentration vector, filtered."""
    df = prop_table.copy()
    df["val"] = np.clip(np.asarray(conc, dtype=float), 0, None)
    df = df[df["assigned"] & np.isfinite(df["val"])]
    if max_err_mda is not None:
        df = df[df["err_mDa"].abs() <= max_err_mda]
    df = df[df["val"] > min_conc]
    return df.reset_index(drop=True)


def _sizes(vals, ref=None, lo=12.0, hi=420.0):
    """Marker areas ~ sqrt(conc). ``ref`` sets the normalising max (pass a
    global maximum so markers shrink over time in the video)."""
    v = np.asarray(vals, dtype=float)
    r = ref if (ref and ref > 0) else (v.max() if v.size and v.max() > 0 else 1.0)
    return lo + (hi - lo) * np.sqrt(np.clip(v, 0, None) / r)


# ── 1. timeline ─────────────────────────────────────────────────────────
def plot_timeline(times, values, mz, selected_idx=None, labels=None,
                  show_total=True, log_y=False, unit_label="signal (a.u.)",
                  figsize=(9.0, 4.4)):
    """Ion time series. ``selected_idx`` indexes columns of ``values``."""
    fig, ax = plt.subplots(figsize=figsize)
    times = pd.DatetimeIndex(times)

    if show_total:
        ax.plot(times, np.clip(values, 0, None).sum(axis=1), color="0.25",
                lw=1.4, label="Σ all ions", zorder=1)

    if selected_idx is not None and len(selected_idx):
        cmap = plt.get_cmap("turbo")
        n = len(selected_idx)
        for k, j in enumerate(selected_idx):
            lab = labels[k] if labels is not None else f"m/z {mz[j]:.3f}"
            ax.plot(times, values[:, j], lw=1.1,
                    color=cmap(k / max(n - 1, 1)), label=lab, zorder=2)

    ax.set_ylabel(unit_label, fontsize=9)
    ax.set_xlabel("Time (UTC)", fontsize=9)
    if log_y:
        ax.set_yscale("log")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(True, ls="--", alpha=0.3)
    ncol = 2 if (selected_idx is not None and len(selected_idx) > 6) else 1
    ax.legend(fontsize=7, loc="upper right", ncol=ncol, framealpha=0.85)
    ax.set_title("Mass-spec timeline", fontsize=10, fontweight="bold")
    fig.tight_layout()
    return fig


# ── 2. carbon-oxygen distribution ────────────────────────────────────────
def co_max_height(prop_table, conc, max_err_mda=None) -> float:
    """Tallest stacked bar (max over carbon number of Σ signal) for a conc vector.

    Both C–O subplots stack the *same* per-nC total, so this bounds both. Used to
    fix the y-axis across video frames so the bars grow from ~0 with the signal."""
    spc = species_with_conc(prop_table, conc, max_err_mda=max_err_mda)
    if spc.empty:
        return 0.0
    return float(spc.groupby("C")["val"].sum().max())


def plot_c_o(prop_table, conc, unit_label="Σ signal (a.u.)", max_err_mda=None,
             ymax=None, figsize=(9.5, 4.2)):
    """Two stacked bar plots vs carbon number: by oxygen number and by family.

    ``ymax`` fixes the y-axis of both subplots (e.g. a global maximum for video)."""
    fig = plt.figure(figsize=figsize)
    gs = fig.add_gridspec(1, 2, wspace=0.28)
    ax_no = fig.add_subplot(gs[0])
    ax_cl = fig.add_subplot(gs[1])

    spc = species_with_conc(prop_table, conc, max_err_mda=max_err_mda)
    if spc.empty:
        for ax in (ax_no, ax_cl):
            ax.text(0.5, 0.5, "No assigned signal in window.", ha="center",
                    va="center", transform=ax.transAxes, color="grey")
            ax.set_axis_off()
        return fig

    x_all = sorted(spc["C"].unique())

    # left: stacked by nO
    grp_no = spc.groupby(["C", "O"])["val"].sum().unstack(fill_value=0).reindex(x_all, fill_value=0)
    n_levels = sorted(grp_no.columns)
    cmap = plt.get_cmap("viridis")
    bottoms = np.zeros(len(x_all))
    for no in n_levels:
        vals = grp_no[no].values
        ax_no.bar(x_all, vals, bottom=bottoms, color=cmap(no / max(max(n_levels), 1)),
                  edgecolor="k", linewidth=0.3, label=f"{int(no)}")
        bottoms += vals
    ax_no.set_xlabel("Carbon number (nC)", fontsize=9)
    ax_no.set_ylabel(unit_label, fontsize=9)
    ax_no.set_title("Stacked by oxygen number", fontsize=9)
    ax_no.set_xticks(x_all)
    ax_no.grid(True, axis="y", ls="--", alpha=0.35)
    if n_levels:
        ax_no.legend(fontsize=6, loc="upper right", ncol=2, framealpha=0.85,
                     title="nO", title_fontsize=7)

    # right: stacked by family
    grp_cl = spc.groupby(["C", "klass"])["val"].sum().unstack(fill_value=0).reindex(x_all, fill_value=0)
    bottoms = np.zeros(len(x_all))
    for cls in CLASS_ORDER:
        if cls not in grp_cl.columns:
            continue
        vals = grp_cl[cls].values
        ax_cl.bar(x_all, vals, bottom=bottoms, color=CLASS_COLORS[cls],
                  edgecolor="k", linewidth=0.3, label=cls)
        bottoms += vals
    ax_cl.set_xlabel("Carbon number (nC)", fontsize=9)
    ax_cl.set_ylabel(unit_label, fontsize=9)
    ax_cl.set_title("Stacked by CHO(N) family", fontsize=9)
    ax_cl.set_xticks(x_all)
    ax_cl.grid(True, axis="y", ls="--", alpha=0.35)
    if ax_cl.get_legend_handles_labels()[0]:
        ax_cl.legend(fontsize=7, loc="upper right", framealpha=0.85)

    if ymax and ymax > 0:
        ax_no.set_ylim(0, ymax)
        ax_cl.set_ylim(0, ymax)

    fig.suptitle("Composition by carbon number", fontsize=10, fontweight="bold", y=0.99)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.86, bottom=0.15, wspace=0.28)
    return fig


# ── 3. volatility basis set ──────────────────────────────────────────────
def plot_vbs(prop_table, conc, unit_label="signal (a.u.)", max_err_mda=None,
             size_ref=None, figsize=(6.4, 5.2)):
    """log10(C*) vs OSc scatter, circles sized/coloured by concentration/family."""
    fig, ax = plt.subplots(figsize=figsize)
    spc = species_with_conc(prop_table, conc, max_err_mda=max_err_mda)
    spc = spc[np.isfinite(spc["logc"]) & np.isfinite(spc["osc"])]
    if spc.empty:
        ax.text(0.5, 0.5, "No organic species with valid LogC* in window.",
                ha="center", va="center", transform=ax.transAxes, color="grey")
        ax.set_axis_off()
        return fig

    for (lo, hi), color in [((-3.5, -0.51), "dimgrey"), ((-0.5, 2.49), "darkgrey"),
                            ((2.5, 6.49), "lightgrey")]:
        ax.axvspan(lo, hi, color=color, alpha=0.18, zorder=0)
    for x, label in [(-2, "LVOC"), (1, "SVOC"), (4.5, "IVOC"), (8.5, "VOC")]:
        ax.text(x, 2.25, label, ha="center", va="bottom", fontsize=9, color="#444")

    sizes = _sizes(spc["val"].values, ref=size_ref)
    colors = [CLASS_COLORS.get(c, "#7f7f7f") for c in spc["klass"]]
    ax.scatter(spc["logc"], spc["osc"], s=sizes, c=colors, alpha=0.55,
               edgecolors="k", linewidths=0.4, zorder=2)

    ax.set_xlim(-4, 11)
    ax.set_ylim(-2.5, 2.5)
    ax.set_xticks(range(-3, 12))
    ax.set_xticklabels([str(x) if x % 2 == 0 else "" for x in range(-3, 12)])
    ax.set_xlabel(r"Volatility  $\log_{10}(C^*)$  [µg m$^{-3}$]", fontsize=9)
    ax.set_ylabel(r"Carbon oxidation state  $\overline{\mathrm{OS}}_\mathrm{C}$", fontsize=9)
    ax.set_title(f"Volatility basis set  (N={len(spc)}, sized by {unit_label})",
                 fontsize=10, fontweight="bold")

    from matplotlib.lines import Line2D
    handles = [Line2D([0], [0], marker="o", color="w", markerfacecolor=CLASS_COLORS[c],
                      markersize=8, label=c) for c in CLASS_ORDER if c in spc["klass"].values]
    if handles:
        ax.legend(handles=handles, loc="lower right", fontsize=8, framealpha=0.85)
    ax.grid(True, ls="--", alpha=0.3)
    ax.text(0.01, -0.13, _CITE, transform=ax.transAxes, fontsize=6, color="#666", style="italic")
    fig.subplots_adjust(left=0.12, right=0.96, top=0.90, bottom=0.13)
    return fig


# ── 4. mass defect ───────────────────────────────────────────────────────
def plot_mass_defect(prop_table, conc, unit_label="signal (a.u.)", max_err_mda=None,
                     size_ref=None, figsize=(6.4, 5.2)):
    """Mass defect (mass - round(mass)) vs mass, sized/coloured by family."""
    fig, ax = plt.subplots(figsize=figsize)
    spc = species_with_conc(prop_table, conc, max_err_mda=max_err_mda)
    spc = spc[np.isfinite(spc["mass"])]
    if spc.empty:
        ax.text(0.5, 0.5, "No assigned signal in window.", ha="center",
                va="center", transform=ax.transAxes, color="grey")
        ax.set_axis_off()
        return fig

    md = spc["mass"] - np.round(spc["mass"])
    sizes = _sizes(spc["val"].values, ref=size_ref)
    colors = [CLASS_COLORS.get(c, "#7f7f7f") for c in spc["klass"]]
    ax.scatter(spc["mass"], md, s=sizes, c=colors, alpha=0.55,
               edgecolors="k", linewidths=0.4, zorder=2)
    ax.axhline(0, color="0.6", lw=0.7, ls="--")
    ax.set_xlabel("Neutral mass (u)", fontsize=9)
    ax.set_ylabel("Mass defect (u)", fontsize=9)
    ax.set_title(f"Mass defect  (N={len(spc)}, sized by {unit_label})",
                 fontsize=10, fontweight="bold")

    from matplotlib.lines import Line2D
    handles = [Line2D([0], [0], marker="o", color="w", markerfacecolor=CLASS_COLORS[c],
                      markersize=8, label=c) for c in CLASS_ORDER if c in spc["klass"].values]
    if handles:
        ax.legend(handles=handles, loc="upper left", fontsize=8, framealpha=0.85)
    ax.grid(True, ls="--", alpha=0.3)
    fig.subplots_adjust(left=0.12, right=0.96, top=0.90, bottom=0.12)
    return fig
