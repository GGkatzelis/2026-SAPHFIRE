"""matplotlib figures for the PTR vs injections comparison (no Qt in here).

Every function draws into an Axes it is given and returns the points a window can use for a
hover readout: dicts with x, y (data coordinates), text, period and formula.

One hue carries the data; a highlighted experiment takes the second hue. Reference marks are
drawn as collections (not lines), so a drag pans these panels in both directions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.colors import to_rgba
from matplotlib.ticker import FuncFormatter, MultipleLocator

from ptr_vs_injections import formula_summary

BLUE, ORANGE = "#2a78d6", "#eb6834"                 # data, highlighted experiment
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
TOLERANCE = 30.0            # % band drawn as the "agrees" reference
LOG_FLOOR = 0.2             # log axes start at this fraction of the smallest expected value
SMALL = 9.5                 # pt: dense row labels and in-plot notes


def _short(text: str, n: int = 36) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip(", ") + "…"


def _frame(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelcolor=INK2, length=3)
    ax.set_axisbelow(True)


def _readout(r) -> str:
    return (f"{r.formula} · {_short(r.compounds, 44)}\n{r.period}\n"
            f"expected {r.expected_ppbv:.2f} ppbv · PTR {r.observed_ppbv:.2f} ppbv\n"
            f"difference {r.pct_difference:+.0f} %\n{_short(r.pattern, 60)}")


def _points(d: pd.DataFrame, x, y) -> list[dict]:
    return [dict(x=float(a), y=float(b), text=_readout(r), period=r.period, formula=r.formula)
            for a, b, r in zip(x, y, d.itertuples())]


def _dots(ax, x, y, colour, label, size=38, z=3):
    ax.scatter(x, y, s=size, color=colour, edgecolors="white", linewidths=1.1, zorder=z, label=label)


def pct_by_formula(ax, cmp: pd.DataFrame, kind: str = "Violin", sort: str = "Median",
                   highlight: str | None = None) -> list[dict]:
    """Distribution of the % difference per formula: one row each, every experiment a point."""
    d = cmp.dropna(subset=["pct_difference"]).copy()
    summ = formula_summary(d)
    summ = summ.sort_values("pct_median" if sort == "Median" else "formula",
                            ascending=sort != "Median").reset_index(drop=True)
    row = {f: i for i, f in enumerate(summ.formula)}           # row 0 at the bottom
    n = len(row)
    d["row"] = d.formula.map(row)
    # spread the points of a row evenly, in date order, so they never sit on top of each other
    rank = d.groupby("formula").cumcount()
    size = d.groupby("formula").formula.transform("size")
    d["ypos"] = d.row + np.where(size > 1, (rank / (size - 1).clip(lower=1) - 0.5) * 0.5, 0.0)

    groups = {i: d.loc[d.formula == f, "pct_difference"].to_numpy() for f, i in row.items()}
    groups = {i: v for i, v in groups.items() if len(v) >= 3 and np.ptp(v) > 0}
    if kind == "Violin" and groups:
        kw = dict(positions=list(groups), widths=0.8, showextrema=False)
        try:
            parts = ax.violinplot(list(groups.values()), orientation="horizontal", **kw)
        except TypeError:                                       # matplotlib < 3.10
            parts = ax.violinplot(list(groups.values()), vert=False, **kw)
        for body in parts["bodies"]:
            body.set_facecolor(to_rgba(BLUE, 0.13)); body.set_edgecolor(BLUE); body.set_linewidth(1.0)
            body.set_alpha(None); body.set_zorder(2)
    elif kind == "Box":
        for i, v in groups.items():
            q1, q3 = np.percentile(v, [25, 75])
            lo, hi = v[v >= q1 - 1.5 * (q3 - q1)].min(), v[v <= q3 + 1.5 * (q3 - q1)].max()
            ax.barh(i, q3 - q1, left=q1, height=0.5, facecolor=to_rgba(BLUE, 0.13), edgecolor=BLUE, linewidth=1.0, zorder=2)
            ax.hlines([i, i], [lo, q3], [q1, hi], colors=BLUE, linewidth=1.0, zorder=2)

    normal = d if highlight is None else d[d.period != highlight]
    _dots(ax, normal.pct_difference, normal.ypos, BLUE, "One experiment")
    if highlight is not None:
        hi_d = d[d.period == highlight]
        _dots(ax, hi_d.pct_difference, hi_d.ypos, ORANGE, highlight, size=46, z=4)
    ax.scatter(summ.pct_median, [row[f] for f in summ.formula], marker="|", s=320, color=INK, linewidths=2.0,
               zorder=5, label="Median")

    ax.axvspan(-TOLERANCE, TOLERANCE, color=MUTED, alpha=0.10, linewidth=0, zorder=0)
    ax.vlines(0, -0.7, n - 0.3, colors=AXIS, linewidth=1.0, zorder=1)
    ax.text(0, n - 0.05, f"expected ± {TOLERANCE:.0f} %", ha="center", va="center", fontsize=SMALL, color=MUTED)
    ax.set_yticks(list(row.values()), [f"{_short(c)}   {f}" for f, c in zip(summ.formula, summ.compounds)])
    ax.set_ylim(-0.7, n + 0.4)
    ax.set_xlim(min(-110.0, d.pct_difference.min() - 8), max(110.0, d.pct_difference.max() + 8))
    ax.xaxis.set_major_locator(MultipleLocator(50))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f} %"))
    ax.set_xlabel("PTR increase relative to expected (%)")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    _frame(ax)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0, labelsize=SMALL)
    ax.legend(loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=3, frameon=False, borderaxespad=0.2,
              handletextpad=0.3, columnspacing=1.4, fontsize=10)
    return _points(d, d.pct_difference, d.ypos)


def _error(g, col: str, mean: pd.Series, how: str, floor: float | None) -> np.ndarray:
    """(2, n) error bars for one axis: standard deviation or min-max between experiments.
    On a logarithmic axis (``floor`` set) the lower end stops at the axis instead of at zero."""
    if how == "Min-max":
        plus, minus = g[col].max() - mean, mean - g[col].min()
    else:
        plus = minus = g[col].std().fillna(0.0)
    plus, minus = plus.reindex(mean.index), minus.reindex(mean.index)     # same order as the points
    if floor is not None:
        minus = np.minimum(minus, (mean - floor).clip(lower=0.0))
    return np.vstack([minus.to_numpy(), plus.to_numpy()])


def observed_vs_expected(ax, cmp: pd.DataFrame, mode: str = "Mean per formula", log_axes: bool = True,
                         labels: str = "Outliers", highlight: str | None = None, error: str = "Std dev"
                         ) -> tuple[list[dict], int, float]:
    """PTR increase against expected ppbv.

    Returns the hover points, the number of points left out on logarithmic axes, and the lower
    axis limit in ppbv. A log axis cannot show zero, so it starts a factor of five below the
    smallest expected value and PTR increases below that are left out."""
    d = cmp.dropna(subset=["pct_difference"])
    if mode == "Mean per formula":
        s = formula_summary(d).set_index("formula")
        floor = s.expected_mean.min() * LOG_FLOOR if log_axes else None
        hidden = int((s.observed_mean < floor).sum()) if log_axes else 0
        s = s[s.observed_mean >= floor] if log_axes else s
        g = d[d.formula.isin(s.index)].groupby("formula")
        ax.errorbar(s.expected_mean, s.observed_mean, xerr=_error(g, "expected_ppbv", s.expected_mean, error, floor),
                    yerr=_error(g, "observed_ppbv", s.observed_mean, error, floor), fmt="none",
                    ecolor=to_rgba(BLUE, 0.5), elinewidth=1.0, zorder=2)
        _dots(ax, s.expected_mean, s.observed_mean, BLUE, "Formula mean", size=52)
        s = s.reset_index()
        show = (s.pct_of_means.abs() > 50) if labels == "Outliers" else pd.Series(labels == "All", index=s.index)
        for r in s[show].itertuples():
            ax.annotate(r.formula, (r.expected_mean, r.observed_mean), xytext=(0, 7), textcoords="offset points",
                        ha="center", fontsize=SMALL, color=INK2, zorder=6)
        spread = s.observed_sd.fillna(0.0)
        points = [dict(x=float(r.expected_mean), y=float(r.observed_mean), period=None, formula=r.formula,
                       text=(f"{r.formula} · {_short(r.compounds, 44)}\n{r.n} experiments\n"
                             f"expected {r.expected_mean:.2f} ppbv · PTR {r.observed_mean:.2f} ± {sd:.2f} ppbv\n"
                             f"difference {r.pct_of_means:+.0f} %"))
                  for r, sd in zip(s.itertuples(), spread)]
        x, y = s.expected_mean, s.observed_mean
    else:
        floor = d.expected_ppbv.min() * LOG_FLOOR if log_axes else None
        hidden = int((d.observed_ppbv < floor).sum()) if log_axes else 0
        d = d[d.observed_ppbv >= floor] if log_axes else d
        normal = d if highlight is None else d[d.period != highlight]
        _dots(ax, normal.expected_ppbv, normal.observed_ppbv, BLUE, "One experiment")
        if highlight is not None:
            hi_d = d[d.period == highlight]
            _dots(ax, hi_d.expected_ppbv, hi_d.observed_ppbv, ORANGE, highlight, size=46, z=4)
            ax.legend(loc="upper left", frameon=False, fontsize=10, handletextpad=0.3)
        points = _points(d, d.expected_ppbv, d.observed_ppbv)
        x, y = d.expected_ppbv, d.observed_ppbv

    lo = floor if log_axes else 0.0
    hi = max(x.max(), y.max()) * (1.8 if log_axes else 1.1)
    x1 = hi / (1 + TOLERANCE / 100) / (1.25 if log_axes else 1.05)        # all three lines end at the same x
    start = lo if log_axes else 0.0
    refs = ((1.0, "1:1", INK2, dict(ha="left", va="center", xytext=(6, 0))),
            (1 + TOLERANCE / 100, f"+{TOLERANCE:.0f} %", AXIS, dict(ha="right", va="bottom", xytext=(-2, 3))),
            (1 - TOLERANCE / 100, f"−{TOLERANCE:.0f} %", AXIS, dict(ha="left", va="top", xytext=(6, -3))))
    ax.add_collection(LineCollection([[(start, start * f), (x1, x1 * f)] for f, *_ in refs],
                                     colors=[c for _, _, c, _ in refs], linewidths=1.0, zorder=1))
    for f, text, _, place in refs:
        ax.annotate(text, (x1, x1 * f), textcoords="offset points", fontsize=SMALL, color=MUTED, **place)
    if log_axes:
        ax.set_xscale("log"); ax.set_yscale("log")
        fmt = FuncFormatter(lambda v, _: f"{v:g}")
        ax.xaxis.set_major_formatter(fmt); ax.yaxis.set_major_formatter(fmt)
    ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
    ax.set_xlabel("Expected from injection (ppbv)")
    ax.set_ylabel("PTR increase (ppbv)")
    ax.grid(color=GRID, linewidth=0.8)
    _frame(ax)
    return points, hidden, (floor or 0.0)


def _clock(hours: float, _pos=None) -> str:
    return f"{int(hours) % 24:02d}:{int(round((hours % 1) * 60)) % 60:02d}"


def time_series(ax, series: pd.Series, rec, injections: pd.DataFrame, background_min: float = 10.0) -> None:
    """The PTR signal of one formula around its injections (x in hours of the day, UTC), with the
    background and averaging windows and the expected level."""
    midnight = pd.Timestamp(rec.date)
    hours = lambda t: (t - midnight).total_seconds() / 3600.0          # noqa: E731
    stamp = lambda hm: hours(pd.Timestamp(f"{rec.date} {hm}"))         # noqa: E731
    times = [stamp(x) for x in rec.injected_utc.split(", ")]
    w0, w1 = stamp(rec.window_start), stamp(rec.window_end)
    x0, x1 = times[0] - 0.5, w1 + 0.5
    s = series[(series.index >= midnight + pd.Timedelta(hours=x0)) & (series.index <= midnight + pd.Timedelta(hours=x1))]
    ax.plot((s.index - midnight).total_seconds() / 3600.0, s.to_numpy(), color=BLUE, linewidth=1.8,
            label=f"PTR {rec.formula}", zorder=3)
    across = ax.get_xaxis_transform()                                  # x in data, y in axes fraction

    def band(a, b, text, colour):
        ax.axvspan(a, b, color=colour, alpha=0.14, linewidth=0, zorder=0)
        ax.text((a + b) / 2, 1.01, text, transform=across, ha="center", va="bottom", fontsize=SMALL, color=MUTED)

    if not np.isnan(rec.background_ppbv):
        band(times[0] - background_min / 60.0, times[0], "background", MUTED)
    band(w0, w1, "average", BLUE)
    ax.vlines(times, 0, 1, transform=across, colors=INK2, linewidth=1.0, zorder=2)
    for tm in times:
        names = ", ".join(injections.loc[injections.time_utc == _clock(tm), "compound"])
        ax.annotate(f"{_clock(tm)} {_short(names, 28)}", (tm, 0.985), xycoords=across, xytext=(4, 0),
                    textcoords="offset points", ha="left", va="top", fontsize=SMALL, color=INK2)
    level = (0.0 if np.isnan(rec.background_ppbv) else rec.background_ppbv) + rec.expected_ppbv
    ax.hlines(level, times[0], x1, colors=INK2, linewidth=1.0, linestyles="dashed", zorder=2)
    ax.annotate(f"expected\n{level:.2f} ppbv", (1.0, level), xycoords=ax.get_yaxis_transform(), xytext=(6, 0),
                textcoords="offset points", ha="left", va="center", fontsize=SMALL, color=INK2, annotation_clip=False)
    top = max(level, float(s.max()) if len(s) else level) * 1.25
    ax.set_xlim(x0, x1)
    ax.set_ylim(min(0.0, float(s.min()) if len(s) else 0.0), top)
    ax.xaxis.set_major_locator(MultipleLocator(0.5 if x1 - x0 > 2.5 else 0.25))
    ax.xaxis.set_major_formatter(FuncFormatter(_clock))
    ax.set_xlabel("time of day (UTC)")
    ax.set_ylabel(f"PTR {rec.formula} (ppbv)")
    ax.grid(color=GRID, linewidth=0.8)
    _frame(ax)
