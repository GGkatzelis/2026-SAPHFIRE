"""Signal-detection and pattern statistics for CHARON-FUSION time series.

Given a **background** period and a **chemistry** period (time masks), decide
per mass whether it carries real signal above background noise, then cluster the
detected masses by how their time series co-evolve.

* ``detection_stats`` — per-mass background/chemistry statistics and SNR flag.
* ``correlation_matrix`` — Pearson correlation between detected masses.
* ``cluster_masses`` — hierarchical clustering (Ward on 1-corr) + leaf order.
* ``cluster_profiles`` — mean normalised time profile per cluster.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def detection_stats(values: np.ndarray, bg_mask: np.ndarray, chem_mask: np.ndarray,
                    mz: np.ndarray, snr_threshold: float = 3.0,
                    prop_table: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per-mass detection statistics relative to the background period.

    Parameters
    ----------
    values : (T, N) array of signal.
    bg_mask, chem_mask : boolean (T,) selecting background / chemistry rows.
    mz : (N,) ion m/z.
    snr_threshold : a mass is "detected" if SNR >= this.

    SNR = (mean_chem - mean_bg) / std_bg, with a small-noise floor so masses
    with a degenerate (near-zero-variance) background can't produce infinite SNR.
    Returns a DataFrame (one row per ion).
    """
    bg = values[bg_mask]
    chem = values[chem_mask]
    if bg.shape[0] < 2 or chem.shape[0] < 1:
        raise ValueError("Background needs >=2 points and chemistry >=1 point.")

    bg_mean = bg.mean(axis=0)
    bg_std = bg.std(axis=0, ddof=1)
    chem_mean = chem.mean(axis=0)
    chem_max = chem.max(axis=0)

    # noise floor: median BG std across masses (guards near-constant BG columns)
    floor = np.nanmedian(bg_std[bg_std > 0]) if np.any(bg_std > 0) else 1.0
    noise = np.where(bg_std > floor * 1e-3, bg_std, floor)

    enhancement = chem_mean - bg_mean
    snr = enhancement / noise
    snr_peak = (chem_max - bg_mean) / noise

    df = pd.DataFrame({
        "mz": mz,
        "bg_mean": bg_mean, "bg_std": bg_std,
        "chem_mean": chem_mean, "chem_max": chem_max,
        "enhancement": enhancement, "snr": snr, "snr_peak": snr_peak,
        "detected": snr >= snr_threshold,
    })
    if prop_table is not None:
        df["formula"] = prop_table["formula"].to_numpy()
        df["klass"] = prop_table["klass"].to_numpy()
    return df


def correlation_matrix(values: np.ndarray, idx: np.ndarray,
                       rows: np.ndarray | None = None) -> np.ndarray:
    """Pearson correlation between the columns ``idx`` of ``values``.

    ``rows`` optionally restricts the time rows used (else the whole record).
    Columns with zero variance are handled (their correlations become 0/NaN→0).
    """
    v = values[:, idx]
    if rows is not None:
        v = v[rows]
    v = v.astype(float)
    # guard constant columns
    std = v.std(axis=0)
    ok = std > 0
    corr = np.zeros((v.shape[1], v.shape[1]))
    if ok.any():
        c = np.corrcoef(v[:, ok], rowvar=False)
        c = np.nan_to_num(c, nan=0.0)
        ii = np.where(ok)[0]
        corr[np.ix_(ii, ii)] = c
    np.fill_diagonal(corr, 1.0)
    return corr


def cluster_masses(corr: np.ndarray, n_clusters: int = 6,
                   method: str = "ward"):
    """Hierarchical clustering on a correlation matrix.

    Returns (labels, leaf_order, linkage_Z). Distance = 1 - corr.
    """
    from scipy.cluster.hierarchy import fcluster, leaves_list, linkage
    from scipy.spatial.distance import squareform

    n = corr.shape[0]
    if n < 2:
        return np.ones(n, dtype=int), np.arange(n), None
    dist = 1.0 - corr
    dist = (dist + dist.T) / 2.0        # enforce symmetry
    np.fill_diagonal(dist, 0.0)
    dist = np.clip(dist, 0.0, 2.0)
    condensed = squareform(dist, checks=False)
    Z = linkage(condensed, method=method)
    k = int(max(1, min(n_clusters, n)))
    labels = fcluster(Z, t=k, criterion="maxclust")
    order = leaves_list(Z)
    return labels, order, Z


def cluster_profiles(values: np.ndarray, idx: np.ndarray, labels: np.ndarray,
                     normalize: str = "max") -> dict[int, np.ndarray]:
    """Mean time profile per cluster over the full record.

    Each mass is normalised (``max`` -> peak 1, or ``zscore``) before averaging
    so a cluster's shape isn't dominated by its largest mass.
    Returns {cluster_id: profile (T,)}.
    """
    out = {}
    v = values[:, idx].astype(float)
    if normalize == "max":
        peak = v.max(axis=0)
        peak[peak <= 0] = 1.0
        vn = v / peak
    elif normalize == "zscore":
        mu = v.mean(axis=0)
        sd = v.std(axis=0)
        sd[sd <= 0] = 1.0
        vn = (v - mu) / sd
    else:
        vn = v
    for c in np.unique(labels):
        out[int(c)] = vn[:, labels == c].mean(axis=1)
    return out


def cluster_summary(det: pd.DataFrame, detected_idx: np.ndarray,
                    labels: np.ndarray) -> pd.DataFrame:
    """Per-cluster summary: size, total enhancement, dominant family, m/z range."""
    sub = det.iloc[detected_idx].copy()
    sub["cluster"] = labels
    rows = []
    for c, g in sub.groupby("cluster"):
        fam = g["klass"].mode().iat[0] if "klass" in g and not g["klass"].isna().all() else "-"
        rows.append({
            "cluster": int(c), "n_masses": len(g),
            "sum_enhancement": g["enhancement"].sum(),
            "mz_min": g["mz"].min(), "mz_max": g["mz"].max(),
            "dominant_family": fam,
        })
    return pd.DataFrame(rows).sort_values("sum_enhancement", ascending=False)
