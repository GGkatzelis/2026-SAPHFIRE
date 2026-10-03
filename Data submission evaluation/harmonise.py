"""Write the harmonised archive copy of an accepted file: one CSV layout for all.

Layout = the submission CSV layout: provenance comment lines (#), then
``time_utc`` (UTC text, YYYY-MM-DD hh:mm:ss[.fff]), optional ``time_utc_end``,
then one ``quantity [unit]`` column per variable.

What is changed: only the layout and unit *labels* (SAPHIR markup such as
``cm!U-3!N`` -> ``cm-3``, ``°C`` -> ``degC``, a blank unit -> ``1``).
What is never changed: values (written with 10 significant digits, more than
any instrument resolves), timestamps (start or centre exactly as delivered; the
header states which), units themselves (no conversion), gaps (no filling).

* CSV submissions are copied line by line (only the header lines are added).
* HDF5: 1-D datasets become columns; a 2-D spectrum/size distribution becomes
  one column per bin, ``dNdlogDp 14.6nm [cm-3]``.
* Native SAPHIR NetCDF: every time-series variable becomes a column, its
  ``@STDEV`` companion a ``<name>_STDEV`` column next to it; ``@NO_OF_POINTS`` and
  ``@INTERVAL_T`` are dropped.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import numpy as np
import pandas as pd

import rules as R
from jvalues import ascii_unit

FLOAT_FORMAT = "%.10g"


def clean_unit(u) -> str:
    u = ascii_unit(str(u or "")).replace("°C", "degC").replace("°", "deg").replace("µ", "u")
    u = {"%": "percent", "": "1"}.get(u.strip(), u.strip())
    return u.encode("ascii", "replace").decode()


def _time_text(t: pd.Series | pd.DatetimeIndex) -> pd.Series:
    t = pd.Series(pd.DatetimeIndex(t).round("ms"))
    fmt = "%Y-%m-%d %H:%M:%S.%f" if (t.dt.microsecond != 0).any() else "%Y-%m-%d %H:%M:%S"
    s = t.dt.strftime(fmt)
    return s.str[:-3] if fmt.endswith("%f") else s          # microseconds -> milliseconds


def _frame_to_csv(df: pd.DataFrame) -> str:
    buf = io.StringIO()
    df.to_csv(buf, index=False, float_format=FLOAT_FORMAT, na_rep="", lineterminator="\n")
    return buf.getvalue()


def _from_csv(src: Path) -> tuple[str, list[str]]:
    text = src.read_bytes().decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
    lines = text.split("\n")
    original_comments = [l for l in lines if l.lstrip().startswith("#")]
    body = [l for l in lines if l.strip() and not l.lstrip().startswith("#")]
    return "\n".join(body) + "\n", original_comments


def _from_h5(src: Path) -> str:
    import h5py
    from validator import _EPOCH_RE, _attr_str

    with h5py.File(src, "r") as f:
        def times(name):
            m = _EPOCH_RE.match(_attr_str(f[name], "units") or "")
            epoch = pd.Timestamp(f"{m[1]} {m[2] or '00:00:00'}")
            return epoch + pd.to_timedelta(f[name][()].astype(float), unit="s")

        t = times(R.TIME_COL)
        n = len(t)
        cols = {R.TIME_COL: _time_text(t)}
        if R.TIME_END_COL in f:
            cols[R.TIME_END_COL] = _time_text(times(R.TIME_END_COL))
        dsets = [k for k in f if isinstance(f[k], h5py.Dataset)
                 and k not in (R.TIME_COL, R.TIME_END_COL)]
        # bin axis of each 2-D dataset: a 1-D dataset of matching length, preferring
        # axis-like names (needed when the number of bins equals the number of times)
        axis_like = re.compile(r"diam|^dp|bin|size|axis|mass|^mz|wavelength|temp", re.I)
        axis_of = {}
        for k in dsets:
            if f[k].ndim == 2 and f[k].shape[0] == n:
                cands = [a for a in dsets if f[a].ndim == 1 and f[a].shape[0] == f[k].shape[1]]
                cands.sort(key=lambda a: (not axis_like.search(a), f[a].shape[0] == n))
                axis_of[k] = cands[0] if cands else None
        axes = {a for a in axis_of.values() if a}
        for k in dsets:
            d, unit = f[k], clean_unit(_attr_str(f[k], "units"))
            if k in axes:
                continue
            if d.ndim == 1 and d.shape[0] == n:
                cols[f"{k} [{unit}]"] = d[()]
            elif d.ndim == 2 and d.shape[0] == n:
                ax_name = axis_of[k]
                ax = f[ax_name][()] if ax_name else np.arange(d.shape[1])
                ax_unit = clean_unit(_attr_str(f[ax_name], "units")) if ax_name else ""
                data = d[()]
                for i, b in enumerate(ax):
                    cols[f"{k} {b:g}{ax_unit if ax_unit != '1' else ''} [{unit}]"] = data[:, i]
    return _frame_to_csv(pd.DataFrame(cols))


def _from_nc(src: Path) -> str:
    import netCDF4

    with netCDF4.Dataset(src) as nc:
        nc.set_auto_mask(True)
        tname = next(k for k, v in nc.variables.items()
                     if " since " in str(getattr(v, "units", "")).lower() and v.ndim == 1)
        tv = nc[tname]
        t = netCDF4.num2date(tv[:], tv.units, getattr(tv, "calendar", "standard"),
                             only_use_python_datetimes=True, only_use_cftime_datetimes=False)
        n = len(tv)
        cols = {R.TIME_COL: _time_text(pd.to_datetime(list(t)))}
        for k, v in nc.variables.items():
            if k == tname or "@" in k or v.ndim != 1 or v.shape[0] != n or v.dtype.kind not in "fiu":
                continue
            unit = clean_unit(getattr(v, "units", ""))
            cols[f"{k} [{unit}]"] = np.ma.filled(v[:].astype(float), np.nan)
            sd = f"{k}@STDEV"
            if sd in nc.variables:
                cols[f"{k}_STDEV [{unit}]"] = np.ma.filled(nc[sd][:].astype(float), np.nan)
    return _frame_to_csv(pd.DataFrame(cols))


def harmonised_text(src: Path, provenance: list[str]) -> str:
    """Full text of the archive CSV for ``src`` (provenance lines without '# ')."""
    ext = src.suffix.lower()
    original_comments: list[str] = []
    if ext == ".csv":
        body, original_comments = _from_csv(src)
    elif ext == ".h5":
        body = _from_h5(src)
    elif ext == ".nc":
        body = _from_nc(src)
    else:
        raise ValueError(f"cannot harmonise {src.name}")
    head = ["# SAPHFIRE 2026 harmonised archive copy (values unchanged from the source file)"]
    head += [f"# {p}" for p in provenance]
    if original_comments:
        head.append("# --- comments from the submitted file ---")
        head += [re.sub(r"^\s*#\s?", "# ", c) for c in original_comments]
    return "\n".join(head) + "\n" + body
