"""Molecular-formula assignment and volatility/oxidation chemistry for CHARON-FUSION.

The CHARON-FUSION IDA export labels every ion only by exact ``m/z`` — the
sum-formula assignment lives in the Tofware project and is dropped on export.
So we assign a neutral C/H/O/N formula to each ion from its exact mass, assuming
protonated detection ``[M+H]+`` (H3O+ reagent ion), and derive the composition
metrics used by the quicklook plots.

The volatility (Li et al., ACP 16, 3327, 2016) and carbon-oxidation-state
(Kroll et al., Nat. Chem. 3, 133, 2011) parameterizations are lifted verbatim
from the MCM_SAPHIR_Tool "Chemical Space" tab so the science matches that tool.

Assignments can always be overridden by a Tofware peak-table export (see
``assign_table(..., overrides=...)``).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ── monoisotopic masses (u) ──────────────────────────────────────────────
M_C = 12.0
M_H = 1.00782503207
M_O = 15.99491461956
M_N = 14.0030740048
PROTON = 1.007276467  # m/z([M+H]+) = M_neutral + PROTON  (proton, not H atom)

# ── family classification (from MCM_SAPHIR_Tool) ─────────────────────────
CLASS_ORDER = ["CH", "CHO", "CHON1", "CHON2", "CHON3+", "Other"]
CLASS_COLORS = {
    "CH":     "#1f77b4",
    "CHO":    "#2ca02c",
    "CHON1":  "#ff7f0e",
    "CHON2":  "#d62728",
    "CHON3+": "#9467bd",
    "Other":  "#7f7f7f",
}


def classify(nC: int, nH: int, nO: int, nN: int) -> str:
    """CH / CHO / CHON1 / CHON2 / CHON3+ family (MCM_SAPHIR_Tool convention)."""
    if nC == 0:
        return "Other"
    if nO == 0 and nN == 0:
        return "CH"
    if nO > 0 and nN == 0:
        return "CHO"
    if nN == 1:
        return "CHON1"
    if nN == 2:
        return "CHON2"
    if nN >= 3:
        return "CHON3+"
    return "Other"


def osc(nC: int, nH: int, nO: int) -> float:
    """Mean carbon oxidation state, OSc = (2*nO - nH) / nC (Kroll 2011)."""
    if nC <= 0:
        return np.nan
    return (2.0 * nO - nH) / nC


def logc_star(nC: int, nO: int, nN: int, nS: int = 0) -> float:
    """Li et al. 2016 log10(C*) volatility (µg/m³, 300 K).

    Coefficient set chosen by which heteroatoms are present. Verbatim from
    MCM_SAPHIR_Tool._cs_calc_logc_star."""
    if nC <= 0:
        return np.nan
    if nO == 0 and nN == 0 and nS == 0:            # CH
        n0C, bC, bO, bCO, bN, bS = 23.80, 0.4861, 0.0, 0.0, 0.0, 0.0
    elif nO > 0 and nN == 0 and nS == 0:           # CHO
        n0C, bC, bO, bCO, bN, bS = 22.66, 0.4481, 1.656, -0.7790, 0.0, 0.0
    elif nN > 0 and nO == 0 and nS == 0:           # CHN
        n0C, bC, bO, bCO, bN, bS = 24.59, 0.4066, 0.0, 0.0, 0.9619, 0.0
    elif nO > 0 and nN > 0 and nS == 0:            # CHON
        n0C, bC, bO, bCO, bN, bS = 24.13, 0.3667, 0.7732, -0.07790, 1.114, 0.0
    elif nO > 0 and nS > 0 and nN == 0:            # CHOS
        n0C, bC, bO, bCO, bN, bS = 24.06, 0.3637, 1.327, -0.3988, 0.0, 0.7579
    elif nO > 0 and nN > 0 and nS > 0:             # CHONS
        n0C, bC, bO, bCO, bN, bS = 28.50, 0.3848, 1.011, 0.2921, 1.053, 1.316
    else:
        return np.nan
    return (n0C - nC) * bC - nO * bO - 2.0 * (nC * nO / max(nC + nO, 1)) * bCO - nN * bN - nS * bS


# ── formula assignment from exact m/z (protonated [M+H]+) ─────────────────
def assign_formula(mz: float, tol_mda: float = 7.0, max_ppm: float = 12.0,
                   max_N: int = 1, hc_range=(0.2, 3.0), max_oc: float = 3.0):
    """Best neutral CxHyOzNn for a protonated ion at ``mz``, or ``None``.

    Searches integer C/H/O/N minimising the mass error within the looser of
    ``tol_mda`` (absolute) and ``max_ppm``. Applies chemistry filters (DBE>=0,
    valence, H:C and O:C ranges). Returns a dict with counts, formula string,
    neutral mass, mass error (mDa), and DBE.
    """
    M = mz - PROTON
    if M <= 0:
        return None
    tol = max(tol_mda / 1000.0, max_ppm * 1e-6 * mz)
    best = None
    maxC = int(M // M_C) + 1
    for nC in range(1, maxC + 1):
        rem_C = M - nC * M_C
        if rem_C < -tol:
            break
        maxO = min(int(rem_C // M_O) + 1, nC * 3 + 3)
        for nO in range(0, maxO + 1):
            rem_O = rem_C - nO * M_O
            if rem_O < -tol:
                break
            for nN in range(0, max_N + 1):
                rem_N = rem_O - nN * M_N
                if rem_N < -tol:
                    break
                nH = int(round(rem_N / M_H))
                if nH < 0:
                    continue
                Mcalc = nC * M_C + nH * M_H + nO * M_O + nN * M_N
                err = Mcalc - M
                if abs(err) > tol:
                    continue
                # chemistry filters (neutral molecule)
                dbe = nC - nH / 2.0 + nN / 2.0 + 1.0
                if dbe < -0.5:
                    continue
                if nH > 2 * nC + 2 + nN:            # valence ceiling
                    continue
                hc, oc = nH / nC, nO / nC
                if hc < hc_range[0] or hc > hc_range[1] or oc > max_oc:
                    continue
                # prefer smallest error, then fewest heteroatoms, then sane DBE
                score = (abs(err), nN + 0.001 * nO, abs(dbe - round(dbe)))
                if best is None or score < best[0]:
                    best = (score, nC, nH, nO, nN, dbe, err)
    if best is None:
        return None
    _, nC, nH, nO, nN, dbe, err = best
    return {
        "C": nC, "H": nH, "O": nO, "N": nN,
        "formula": _formula_str(nC, nH, nO, nN),
        "mass": nC * M_C + nH * M_H + nO * M_O + nN * M_N,
        "err_mDa": err * 1000.0,
        "dbe": dbe,
    }


def _formula_str(nC: int, nH: int, nO: int, nN: int) -> str:
    out = ""
    for el, n in (("C", nC), ("H", nH), ("N", nN), ("O", nO)):
        if n == 1:
            out += el
        elif n > 1:
            out += f"{el}{n}"
    return out or "?"


def _parse_formula(formula: str):
    """Very small CxHyOzNn parser for override peak tables. Returns dict or None."""
    import re
    counts = {"C": 0, "H": 0, "O": 0, "N": 0}
    for el, n in re.findall(r"([A-Z][a-z]?)(\d*)", str(formula)):
        if el in counts:
            counts[el] += int(n) if n else 1
    if counts["C"] == 0:
        return None
    return counts


def assign_table(mz_values, tol_mda: float = 7.0, max_ppm: float = 12.0,
                 max_N: int = 1, overrides: dict | None = None) -> pd.DataFrame:
    """Assign every ion m/z and derive composition metrics.

    Parameters
    ----------
    mz_values : sequence of float
        Exact m/z of each ion column (the export headers).
    overrides : dict, optional
        Mapping ``m/z -> formula string`` (from a Tofware peak-table export).
        Matched to the nearest ion within 10 mDa; takes precedence over the
        auto-assignment.

    Returns a DataFrame indexed by ion position with columns:
    mz, C, H, O, N, formula, mass, err_mDa, dbe, OC, HC, osc, logc, klass, assigned, source.
    """
    mz_values = np.asarray(mz_values, dtype=float)
    ov = _prep_overrides(overrides, mz_values)
    rows = []
    for i, mz in enumerate(mz_values):
        src = "auto"
        a = None
        if i in ov:
            counts = ov[i]
            a = _row_from_counts(mz, counts)
            src = "override"
        if a is None:
            a = assign_formula(mz, tol_mda=tol_mda, max_ppm=max_ppm, max_N=max_N)
            src = "auto"
        if a is None:
            rows.append(_empty_row(mz))
            continue
        nC, nH, nO, nN = a["C"], a["H"], a["O"], a["N"]
        rows.append({
            "mz": mz, "C": nC, "H": nH, "O": nO, "N": nN,
            "formula": a["formula"], "mass": a["mass"],
            "err_mDa": a.get("err_mDa", 0.0), "dbe": a.get("dbe", np.nan),
            "OC": nO / nC if nC else np.nan,
            "HC": nH / nC if nC else np.nan,
            "osc": osc(nC, nH, nO),
            "logc": logc_star(nC, nO, nN),
            "klass": classify(nC, nH, nO, nN),
            "assigned": True, "source": src,
        })
    df = pd.DataFrame(rows)
    return df


def _row_from_counts(mz, counts):
    nC, nH, nO, nN = counts["C"], counts["H"], counts["O"], counts["N"]
    mass = nC * M_C + nH * M_H + nO * M_O + nN * M_N
    return {
        "C": nC, "H": nH, "O": nO, "N": nN,
        "formula": _formula_str(nC, nH, nO, nN), "mass": mass,
        "err_mDa": (mass + PROTON - mz) * 1000.0,
        "dbe": nC - nH / 2.0 + nN / 2.0 + 1.0,
    }


def _empty_row(mz):
    return {
        "mz": mz, "C": 0, "H": 0, "O": 0, "N": 0, "formula": "",
        "mass": np.nan, "err_mDa": np.nan, "dbe": np.nan,
        "OC": np.nan, "HC": np.nan, "osc": np.nan, "logc": np.nan,
        "klass": "Other", "assigned": False, "source": "none",
    }


def _prep_overrides(overrides, mz_values):
    """Map override {m/z: formula} onto nearest ion index (within 10 mDa)."""
    out = {}
    if not overrides:
        return out
    keys = np.array(sorted(overrides))
    for k in keys:
        counts = _parse_formula(overrides[k])
        if counts is None:
            continue
        j = int(np.argmin(np.abs(mz_values - k)))
        if abs(mz_values[j] - k) <= 0.010:
            out[j] = counts
    return out
