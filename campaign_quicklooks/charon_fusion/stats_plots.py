"""Plots for the signal-detection / clustering panel."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

_CLUSTER_CMAP = "tab10"


def plot_period_timeline(times, total, bg_mask, chem_mask, figsize=(9.0, 3.4)):
    """Sigma-signal with the background and chemistry windows shaded."""
    fig, ax = plt.subplots(figsize=figsize)
    times = pd.DatetimeIndex(times)
    ax.plot(times, total, color="0.25", lw=1.2, zorder=3)
    _shade(ax, times, bg_mask, "#1f77b4", "Background")
    _shade(ax, times, chem_mask, "#ff7f0e", "Chemistry")
    ax.set_ylabel("Σ all ions", fontsize=9)
    ax.set_xlabel("Time (UTC)", fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(True, ls="--", alpha=0.3)
    ax.legend(fontsize=8, loc="upper right", framealpha=0.85)
    ax.set_title("Period masks", fontsize=10, fontweight="bold")
    fig.tight_layout()
    return fig


def _shade(ax, times, mask, color, label):
    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        return
    # shade contiguous runs; label only the first
    edges = np.diff(mask.astype(int))
    starts = list(np.where(edges == 1)[0] + 1)
    ends = list(np.where(edges == -1)[0] + 1)
    if mask[0]:
        starts = [0] + starts
    if mask[-1]:
        ends = ends + [len(mask)]
    first = True
    for s, e in zip(starts, ends):
        ax.axvspan(times[s], times[min(e, len(times) - 1)], color=color, alpha=0.18,
                   zorder=1, label=label if first else None)
        first = False


def plot_snr_hist(det: pd.DataFrame, threshold: float, figsize=(6.4, 4.0)):
    """Histogram of per-mass SNR with the detection threshold marked."""
    fig, ax = plt.subplots(figsize=figsize)
    snr = det["snr"].to_numpy()
    snr = snr[np.isfinite(snr)]
    hi = np.nanpercentile(snr, 99.5) if snr.size else 10
    lo = min(-3.0, np.nanpercentile(snr, 1) if snr.size else -3)
    bins = np.linspace(lo, max(hi, threshold * 2), 60)
    ax.hist(np.clip(snr, bins[0], bins[-1]), bins=bins, color="0.6", edgecolor="k", linewidth=0.3)
    ax.axvline(threshold, color="crimson", lw=1.5, ls="--", label=f"threshold = {threshold:g}")
    n_det = int(det["detected"].sum())
    ax.set_xlabel("SNR = (mean$_{chem}$ − mean$_{bg}$) / σ$_{bg}$", fontsize=9)
    ax.set_ylabel("number of masses", fontsize=9)
    ax.set_yscale("log")
    ax.set_title(f"Detection: {n_det} / {len(det)} masses ≥ threshold", fontsize=10, fontweight="bold")
    ax.legend(fontsize=8)
    ax.grid(True, ls="--", alpha=0.3)
    fig.tight_layout()
    return fig


def plot_enhancement_scatter(det: pd.DataFrame, figsize=(6.4, 4.0)):
    """m/z vs enhancement, detected masses highlighted."""
    fig, ax = plt.subplots(figsize=figsize)
    d = det["detected"].to_numpy()
    enh = det["enhancement"].to_numpy()
    ax.scatter(det["mz"][~d], enh[~d], s=8, c="0.7", alpha=0.5, label="noise", zorder=1)
    ax.scatter(det["mz"][d], enh[d], s=14, c="crimson", alpha=0.7, edgecolors="k",
               linewidths=0.3, label="real signal", zorder=2)
    ax.axhline(0, color="0.5", lw=0.7)
    ax.set_yscale("symlog", linthresh=max(1e-3, np.nanmedian(np.abs(enh)) or 1e-3))
    ax.set_xlabel("m/z", fontsize=9)
    ax.set_ylabel("enhancement (chem − bg)", fontsize=9)
    ax.set_title("Enhancement above background", fontsize=10, fontweight="bold")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(True, ls="--", alpha=0.3)
    fig.tight_layout()
    return fig


def plot_corr_heatmap(corr, order, labels, mz=None, figsize=(6.6, 6.0)):
    """Correlation matrix reordered by the dendrogram, with a cluster strip."""
    fig = plt.figure(figsize=figsize)
    gs = fig.add_gridspec(2, 2, width_ratios=[0.04, 1], height_ratios=[0.04, 1],
                          wspace=0.02, hspace=0.02)
    ax = fig.add_subplot(gs[1, 1])
    ax_top = fig.add_subplot(gs[0, 1], sharex=ax)
    ax_left = fig.add_subplot(gs[1, 0], sharey=ax)

    C = corr[np.ix_(order, order)]
    im = ax.imshow(C, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto", origin="upper")
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_xlabel(f"detected masses (n={len(order)}), clustered", fontsize=9)

    lab_ord = np.asarray(labels)[order]
    strip = lab_ord.reshape(1, -1)
    cmap = plt.get_cmap(_CLUSTER_CMAP)
    ax_top.imshow(strip, aspect="auto", cmap=cmap,
                  vmin=lab_ord.min(), vmax=max(lab_ord.max(), lab_ord.min() + 9))
    ax_left.imshow(strip.T, aspect="auto", cmap=cmap,
                   vmin=lab_ord.min(), vmax=max(lab_ord.max(), lab_ord.min() + 9))
    for a in (ax_top, ax_left):
        a.set_xticks([]); a.set_yticks([])
    ax_top.set_title("Correlation heatmap (Ward-clustered)", fontsize=10, fontweight="bold")

    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label("Pearson r", fontsize=8)
    return fig


def plot_cluster_profiles(times, profiles: dict, summary: pd.DataFrame | None = None,
                          figsize=(9.0, 4.4)):
    """Mean normalised time profile per cluster."""
    fig, ax = plt.subplots(figsize=figsize)
    times = pd.DatetimeIndex(times)
    cmap = plt.get_cmap(_CLUSTER_CMAP)
    sizes = {}
    if summary is not None:
        sizes = dict(zip(summary["cluster"], summary["n_masses"]))
    for c in sorted(profiles):
        lbl = f"cluster {c}" + (f"  (n={sizes[c]})" if c in sizes else "")
        ax.plot(times, profiles[c], lw=1.5, color=cmap((c - 1) % 10), label=lbl)
    ax.set_ylabel("mean normalised signal", fontsize=9)
    ax.set_xlabel("Time (UTC)", fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(True, ls="--", alpha=0.3)
    ax.legend(fontsize=7, loc="upper right", ncol=2, framealpha=0.85)
    ax.set_title("Cluster time profiles (co-evolving masses)", fontsize=10, fontweight="bold")
    fig.tight_layout()
    return fig
