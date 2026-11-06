"""Compare what was injected with what the PTR-ToF-MS measured.

For every experiment and every injected chemical formula the PTR reports:

    expected   sum of the expected ppbv of all injected compounds with that formula
               (PTR cannot separate isomers) up to the averaging window
    background PTR mean over the 10 min before the first injection of the formula
    observed   PTR mean over the averaging window minus the background
    % difference = (observed - expected) / expected x 100
    pattern    did the signal step up when the injection went in?

The averaging window is the 10 min before the roof opened. Where no roof opening
followed the injections, the window is defined per experiment in ``WINDOWS``.

PTR data: the archived ``<date>.PTRMS.FZJ.csv`` files in the sciebo archive, located
through ``../Data submission evaluation/settings.py`` or the environment variable
``SAPHFIRE_ARCHIVE``.

    python ptr_vs_injections.py     # summary; writes output/ptr_vs_expected*.csv
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from injections import OUTPUT_DIR, injection_log

HERE = Path(__file__).resolve().parent
SETTLE_MIN = 3.0            # minutes after an injection before the signal is used
MIN_POINTS = 3              # PTR points needed for a mean
ROOF = "10 min before roof opening"


@dataclass(frozen=True)
class Window:
    """Which injections of a day are compared, and when the PTR average ends (UTC)."""
    experiment: str
    date: str
    inj_from: str       # injections from this time...
    inj_to: str         # ...up to this time belong to the window
    anchor: str         # the average covers the minutes before this time
    rule: str

    @property
    def label(self) -> str:
        return f"{self.experiment} · {pd.Timestamp(self.date):%d %b} {self.anchor}"


WINDOWS = [
    Window("E01", "2026-06-30", "00:00", "11:58", "11:58", "Night: before the first NO2/O3 (roof opened next day)"),
    Window("E02", "2026-07-02", "00:00", "08:30", "08:30", ROOF),
    Window("E03", "2026-07-03", "00:00", "08:30", "08:30", ROOF),
    Window("E05", "2026-07-05", "00:00", "09:15", "09:15", "Roof stayed closed: up to 20 min after the last injection"),
    Window("E06", "2026-07-06", "00:00", "09:02", "09:02", ROOF),
    Window("E07", "2026-07-07", "00:00", "10:20", "10:20", "Night: before the first O3 (roof stayed closed)"),
    Window("E08", "2026-07-09", "00:00", "11:30", "11:30", ROOF),
    Window("E08", "2026-07-10", "00:00", "14:50", "14:50", ROOF),
    Window("E10", "2026-07-13", "00:00", "07:15", "07:15", ROOF),
    Window("E10", "2026-07-13", "07:15", "23:59", "13:42", "Roof already open: up to 20 min after the injection"),
    Window("E11", "2026-07-15", "00:00", "08:06", "08:06", ROOF),
    Window("E12", "2026-07-16", "00:00", "09:11", "09:11", ROOF),
    Window("E12", "2026-07-17", "07:00", "23:59", "08:25", "Roof already open: up to 20 min after the injection"),
]


def canon(formula: str) -> str:
    """Elemental composition as a key, so 'CH4O' matches the PTR column 'C1H4O1'."""
    counts: dict[str, int] = {}
    for el, n in re.findall(r"([A-Z][a-z]?)(\d*)", formula):
        counts[el] = counts.get(el, 0) + (int(n) if n else 1)
    return "".join(f"{el}{counts[el]}" for el in sorted(counts))


def archive_dir() -> Path:
    """The sciebo 'Archive - Download' folder with the harmonised data files."""
    if os.environ.get("SAPHFIRE_ARCHIVE"):
        return Path(os.environ["SAPHFIRE_ARCHIVE"])
    sys.path.insert(0, str(HERE.parent / "Data submission evaluation"))
    import settings
    return settings.ARCHIVE


@lru_cache(maxsize=None)
def load_ptr(day: str) -> pd.DataFrame | None:
    """PTR mixing ratios (ppbv) of one day, columns keyed by ``canon(formula)``; None if no file."""
    arch = archive_dir()
    name = f"{day}.PTRMS.FZJ.csv"
    hits = list(arch.glob(f"*/{name}")) + list(arch.glob(f"Non-experiment days/*/{name}"))
    if not hits:
        return None
    d = pd.read_csv(hits[0], comment="#", parse_dates=["time_utc"]).set_index("time_utc").sort_index()
    d.columns = [canon(c.split(" [")[0]) for c in d.columns]
    return d


def ptr_series(day: str, formula: str) -> pd.Series | None:
    ptr = load_ptr(day)
    key = canon(formula)
    return None if ptr is None or key not in ptr.columns else ptr[key]


def _mean(s: pd.Series, t0, t1) -> tuple[float, float, int]:
    w = s[(s.index >= t0) & (s.index < t1)].dropna()
    return (w.mean(), w.std(), len(w)) if len(w) else (np.nan, np.nan, 0)


def _pattern(s: pd.Series, t, expected: float, w0, w1) -> str:
    """Did the signal step up at injection time ``t``?

    Compares 3-13 min after with the 10 min before. The noise is taken from point-to-point
    differences, so an earlier injection's step inside the baseline is not counted as noise.
    A signal that misses the step but has risen by the averaging window is a slow increase."""
    m = pd.Timedelta(minutes=1)
    pre, _, npre = _mean(s, t - 10 * m, t)
    post, _, npost = _mean(s, t + SETTLE_MIN * m, t + (SETTLE_MIN + 10) * m)
    if npre < MIN_POINTS:
        return "No PTR data at injection"
    if npost < MIN_POINTS:
        return "No PTR data after injection"
    base = s[(s.index >= t - 10 * m) & (s.index < t)].dropna()
    noise = 1.4826 * base.diff().abs().median() / np.sqrt(2)
    limit = max(5 * noise, 0.2 * expected)
    if post - pre >= limit:
        return "Increase at injection"
    late, _, nlate = _mean(s, w0, w1)
    if nlate >= MIN_POINTS and late - pre >= limit:
        return "Slow increase"
    return "No clear increase"


def compare(log: pd.DataFrame | None = None, window_min: float = 10.0, background_min: float = 10.0) -> pd.DataFrame:
    """One row per averaging window and PTR formula."""
    log = injection_log() if log is None else log
    log = log.assign(key=log.formula.map(canon))
    minute = pd.Timedelta(minutes=1)
    rows = []
    for w in WINDOWS:
        ptr = load_ptr(w.date)
        if ptr is None:
            continue
        ts = lambda hm: pd.Timestamp(f"{w.date} {hm}")          # noqa: E731
        day = log[log.date == w.date]
        inj = day[(day.expected_ppbv > 0) & (day.time_utc >= w.inj_from) & (day.time_utc < w.inj_to)]
        cont = day[day.rate_ppbv_per_h > 0]
        anchor = ts(w.anchor)
        for key, g in inj.groupby("key", sort=False):
            if key not in ptr.columns:
                continue                                         # not measured by PTR
            s = ptr[key]
            times = sorted(g.time_utc.unique())
            t_first, t_last = ts(times[0]), ts(times[-1])
            start, notes = anchor - window_min * minute, []
            if t_last >= start:                                  # injected inside the window
                start = t_last + SETTLE_MIN * minute
                notes.append("Injected inside the averaging window, so only the minutes after it are used.")
            expected = g.expected_ppbv.sum()
            for c in cont[cont.key == key].itertuples():
                mid = start + (anchor - start) / 2
                if ts(c.time_utc) < mid:
                    expected += c.rate_ppbv_per_h * (mid - ts(c.time_utc)).total_seconds() / 3600.0
                    notes.append(f"Includes the continuous injection since {c.time_utc}.")
            bkg, _, nb = _mean(s, t_first - background_min * minute, t_first)
            avg, sd, n = _mean(s, start, anchor)
            if n < MIN_POINTS:
                avg = sd = np.nan
            if nb < MIN_POINTS:
                bkg = np.nan
                notes.append("No PTR data before injection, so background taken as 0.")
            observed = avg - (0.0 if np.isnan(bkg) else bkg)
            pats = [_pattern(s, ts(t), g[g.time_utc == t].expected_ppbv.sum(), start, anchor) for t in times]
            pattern = pats[0] if len(set(pats)) == 1 else "; ".join(f"{t}: {p}" for t, p in zip(times, pats))
            rows.append({
                "period": w.label, "experiment": w.experiment, "date": w.date,
                "window_start": f"{start:%H:%M}", "window_end": w.anchor, "rule": w.rule,
                "formula": g.formula.iloc[0], "compounds": ", ".join(sorted(g.compound.unique())),
                "route": ", ".join(sorted(g.route.unique())), "injected_utc": ", ".join(times),
                "expected_ppbv": expected, "background_ppbv": bkg, "ptr_mean_ppbv": avg, "ptr_sd_ppbv": sd,
                "observed_ppbv": observed, "pct_difference": (observed - expected) / expected * 100.0,
                "pattern": pattern, "n_points": n, "note": " ".join(notes)})
    return pd.DataFrame(rows)


def formula_summary(cmp: pd.DataFrame) -> pd.DataFrame:
    """One row per formula over all its windows: mean and spread of expected and observed."""
    d = cmp.dropna(subset=["pct_difference"])
    g = d.groupby("formula")
    out = pd.DataFrame({
        "compounds": g.compounds.agg(lambda s: max(s, key=len)),
        "route": g.route.agg(lambda s: ", ".join(sorted({r for x in s for r in x.split(", ")}))),
        "n": g.size(),
        "expected_mean": g.expected_ppbv.mean(), "expected_sd": g.expected_ppbv.std(),
        "observed_mean": g.observed_ppbv.mean(), "observed_sd": g.observed_ppbv.std(),
        "pct_median": g.pct_difference.median(), "pct_min": g.pct_difference.min(),
        "pct_max": g.pct_difference.max(),
    })
    out["pct_of_means"] = (out.observed_mean - out.expected_mean) / out.expected_mean * 100.0
    return out.sort_values("pct_median").reset_index()


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    cmp = compare()
    summary = formula_summary(cmp)
    OUTPUT_DIR.mkdir(exist_ok=True)
    cmp.to_csv(OUTPUT_DIR / "ptr_vs_expected.csv", index=False)
    summary.to_csv(OUTPUT_DIR / "ptr_vs_expected_by_formula.csv", index=False)
    print(f"{len(cmp)} comparisons, {cmp.formula.nunique()} formulas, {cmp.period.nunique()} windows\n")
    print(cmp.pattern.where(~cmp.pattern.str.contains(";"), "Mixed").value_counts().to_string(), "\n")
    print(summary[["formula", "compounds", "n", "expected_mean", "observed_mean", "pct_median", "pct_min", "pct_max"]]
          .round(1).to_string(index=False, max_colwidth=36))
    print(f"\nWritten: {OUTPUT_DIR / 'ptr_vs_expected.csv'} and ptr_vs_expected_by_formula.csv")
