"""Readers for CHARON-FUSION time-series exports.

The rest of the tool (chemistry, plots, stats, video) only ever sees a
``CharonData`` object — a universal in-memory model of *times x m/z x values*.
File formats are decoupled from that model: ``load_timeseries`` dispatches on
extension to a reader, and every reader returns a ``CharonData``. To support a
new export format, add one reader that produces a ``CharonData`` and register it
in ``load_timeseries`` — nothing downstream changes.

Currently supported:
* Excel (``.xlsx`` / ``.xls``) — the Tofware **IDA export** (wide time x m/z sheet).
* CSV / TSV (``.csv`` / ``.txt``) — any wide table with a time column + m/z columns.

Both go through the same generic tidier, which auto-detects the time column
(name or epoch) and the ion columns (``m/z 101.023 []``, ``mz101.023`` or a bare
numeric header). Nothing about a specific experiment (file name, sheet name,
date) is hard-coded.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ── time-column names and ion-header patterns (case-insensitive) ─────────
_TIME_STR_NAMES = ("time_string", "datetime", "date_time", "timestamp", "date", "time")
_TIME_NUM_NAMES = ("time_number", "time_s", "time_sec", "seconds", "t")
_MZ_RE = re.compile(r"m\s*/?\s*z\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)

_EXCEL_EPOCH = datetime(1899, 12, 30)
_IGOR_EPOCH = datetime(1904, 1, 1)
_CACHE_DIR = Path(__file__).resolve().parent / ".cache"


@dataclass
class CharonData:
    """Universal CHARON-FUSION time series (source-format independent)."""
    times: pd.DatetimeIndex   # length T
    mz: np.ndarray            # length N (float m/z per ion)
    values: np.ndarray        # shape (T, N) signal
    source: str = ""
    meta: dict = field(default_factory=dict)   # free-form (sheet, units, ...)

    @property
    def n_times(self) -> int:
        return len(self.times)

    @property
    def n_ions(self) -> int:
        return len(self.mz)

    def frame(self) -> pd.DataFrame:
        """Wide DataFrame: DatetimeIndex x m/z columns."""
        return pd.DataFrame(self.values, index=self.times, columns=self.mz)

    def window_mean(self, t0=None, t1=None, clip_negative=True) -> np.ndarray:
        """Mean signal per ion over [t0, t1] (defaults to full record)."""
        mask = np.ones(self.n_times, dtype=bool)
        if t0 is not None:
            mask &= np.asarray(self.times >= t0)
        if t1 is not None:
            mask &= np.asarray(self.times <= t1)
        if not mask.any():
            return np.zeros(self.n_ions)
        v = self.values[mask].mean(axis=0)
        return np.clip(v, 0, None) if clip_negative else v


# ── public loader (format dispatch) ──────────────────────────────────────
def load_timeseries(path, sheet: str | None = None, use_cache: bool = True) -> CharonData:
    """Load any supported export into a ``CharonData``.

    Dispatches on file extension. Excel is parquet-cached (slow to parse);
    add new formats by extending the dispatch below.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    ext = path.suffix.lower()

    if ext in (".xlsx", ".xls"):
        return _read_excel(path, sheet=sheet, use_cache=use_cache)
    if ext in (".csv", ".txt", ".tsv"):
        return _read_csv(path)
    raise ValueError(f"Unsupported export format '{ext}'. Supported: .xlsx/.xls/.csv/.txt/.tsv. "
                     "Add a reader in charon_io.load_timeseries for new formats.")


# backwards-compatible alias
read_ida_export = load_timeseries


# ── Excel reader (IDA export) ────────────────────────────────────────────
def _read_excel(path: Path, sheet: str | None, use_cache: bool) -> CharonData:
    if sheet is None:
        sheet = _detect_sheet(path)
    cache = _cache_key(path, sheet)
    if use_cache and cache.exists():
        return _from_cache(pd.read_parquet(cache), str(path), sheet)

    raw = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    df = _tidy(raw)

    if use_cache:
        _CACHE_DIR.mkdir(exist_ok=True)
        out = df.copy()
        out.insert(0, "__time__", out.index)
        out.columns = [str(c) for c in out.columns]
        try:
            out.to_parquet(cache, index=False)
        except Exception:
            pass  # caching is best-effort (e.g. missing pyarrow)
    return _from_frame(df, str(path), {"sheet": sheet})


def _detect_sheet(xlsx: Path) -> str:
    """Pick the sheet whose header row looks like a time + m/z table."""
    import openpyxl
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    try:
        best = None
        for sn in wb.sheetnames:
            ws = wb[sn]
            first = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
            names = [str(c).strip().lower() if c is not None else "" for c in first]
            if any(n in _TIME_STR_NAMES or n in _TIME_NUM_NAMES for n in names[:3]) \
                    and any(_MZ_RE.search(str(c) or "") for c in first):
                return sn
            if best is None and (ws.max_row or 0) > 1:
                best = sn
        return best or wb.sheetnames[0]
    finally:
        wb.close()


# ── CSV / TSV reader ─────────────────────────────────────────────────────
def _read_csv(path: Path) -> CharonData:
    sep = "\t" if path.suffix.lower() == ".tsv" else None  # None -> sniff
    raw = pd.read_csv(path, sep=sep, engine="python")
    df = _tidy(raw)
    return _from_frame(df, str(path), {})


# ── generic tidier: raw wide frame -> time-indexed m/z frame ─────────────
def _tidy(raw: pd.DataFrame) -> pd.DataFrame:
    cols = list(raw.columns)
    time_cols, times = _parse_times(raw, cols)

    ion_cols, mz = [], []
    for c in cols:
        if c in time_cols:
            continue
        val = _column_mz(c)
        if val is not None:
            ion_cols.append(c)
            mz.append(val)
    if not ion_cols:
        raise ValueError("No ion (m/z) columns found — expected headers like "
                         "'m/z 101.023 []', 'mz101.023' or a numeric column name.")

    data = raw[ion_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    df = pd.DataFrame(data, index=times, columns=np.asarray(mz, dtype=float))
    df = df[~df.index.isna()]
    df = df.loc[:, ~df.columns.duplicated()]
    return df.sort_index()


def _column_mz(col) -> float | None:
    """Return the m/z encoded in a column header, or None if it isn't an ion."""
    s = str(col).strip()
    m = _MZ_RE.search(s)
    if m:
        return float(m.group(1))
    # bare numeric header, e.g. "101.023" or "101.023 []"
    cleaned = s.rstrip("[] ").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_times(raw: pd.DataFrame, cols) -> tuple[list, pd.DatetimeIndex]:
    """Detect the time column(s) and return (columns_used, DatetimeIndex).

    Prefers a numeric epoch column (precise), falls back to a parseable string
    column. Epoch type (Excel serial / Unix / Igor) is inferred by magnitude.
    """
    lower = {str(c).strip().lower(): c for c in cols}

    num_col = next((lower[n] for n in _TIME_NUM_NAMES if n in lower), None)
    str_col = next((lower[n] for n in _TIME_STR_NAMES if n in lower), None)

    if num_col is not None:
        idx = _epoch_to_datetime(raw[num_col])
        if idx.notna().mean() > 0.5:
            used = [num_col] + ([str_col] if str_col is not None else [])
            return used, idx
    if str_col is not None:
        idx = pd.DatetimeIndex(pd.to_datetime(raw[str_col], errors="coerce"))
        if idx.notna().mean() > 0.5:
            used = [str_col] + ([num_col] if num_col is not None else [])
            return used, idx
    # last resort: first column if it parses as datetime
    first = cols[0]
    idx = pd.DatetimeIndex(pd.to_datetime(raw[first], errors="coerce"))
    if idx.notna().mean() > 0.5:
        return [first], idx
    raise ValueError("No usable time column found (looked for names like "
                     "time_number / time_string / datetime).")


def _epoch_to_datetime(series: pd.Series) -> pd.DatetimeIndex:
    """Convert a numeric time column to datetimes, inferring the epoch by magnitude."""
    v = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    finite = v[np.isfinite(v)]
    med = float(np.nanmedian(finite)) if finite.size else 0.0

    if 1e3 < med < 1e5:           # Excel serial days (1900-2100)
        return pd.DatetimeIndex([_EXCEL_EPOCH + timedelta(days=float(x)) if np.isfinite(x)
                                 else pd.NaT for x in v])
    if 1e11 < med < 1e13:         # Unix milliseconds
        return pd.to_datetime(v, unit="ms", errors="coerce")
    if 2.5e9 < med < 1e11:        # Igor Pro seconds (since 1904)
        return pd.DatetimeIndex([_IGOR_EPOCH + timedelta(seconds=float(x)) if np.isfinite(x)
                                 else pd.NaT for x in v])
    if 1e8 < med <= 2.5e9:        # Unix seconds
        return pd.to_datetime(v, unit="s", errors="coerce")
    # fallback: treat as Excel serial days
    return pd.DatetimeIndex([_EXCEL_EPOCH + timedelta(days=float(x)) if np.isfinite(x)
                             else pd.NaT for x in v])


# ── frame <-> CharonData helpers ─────────────────────────────────────────
def _from_frame(df: pd.DataFrame, source: str, meta: dict) -> CharonData:
    return CharonData(times=pd.DatetimeIndex(df.index),
                      mz=np.asarray(df.columns, dtype=float),
                      values=df.to_numpy(dtype=float), source=source, meta=meta)


def _from_cache(cached: pd.DataFrame, source: str, sheet: str) -> CharonData:
    times = pd.DatetimeIndex(pd.to_datetime(cached["__time__"]))
    ion_cols = [c for c in cached.columns if c != "__time__"]
    mz = np.asarray([float(c) for c in ion_cols], dtype=float)
    values = cached[ion_cols].to_numpy(dtype=float)
    return CharonData(times=times, mz=mz, values=values, source=source, meta={"sheet": sheet})


def _cache_key(path: Path, sheet: str | None) -> Path:
    st = path.stat()
    raw = f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}|{sheet}"
    return _CACHE_DIR / f"{path.stem}_{hashlib.md5(raw.encode()).hexdigest()[:16]}.parquet"


# ── optional formula-override peak table ─────────────────────────────────
def load_overrides(path) -> dict:
    """Load a peak-table override (CSV/XLSX) with m/z + formula columns.

    Recognises columns named like 'm/z'/'mz'/'mass' and 'formula'/'sumformula'/'ion'.
    Returns {m/z: formula}.
    """
    path = Path(path)
    tbl = pd.read_excel(path) if path.suffix.lower() in (".xlsx", ".xls") else pd.read_csv(path)
    cols = {str(c).strip().lower(): c for c in tbl.columns}
    mz_col = next((cols[k] for k in cols if k in ("m/z", "mz", "mass", "exactmass")), None)
    f_col = next((cols[k] for k in cols
                  if k in ("formula", "sumformula", "sum_formula", "ion", "assignment")), None)
    if mz_col is None or f_col is None:
        raise ValueError("Override table needs an m/z column and a formula column.")
    out = {}
    for _, r in tbl.iterrows():
        try:
            out[float(r[mz_col])] = str(r[f_col])
        except (TypeError, ValueError):
            continue
    return out
