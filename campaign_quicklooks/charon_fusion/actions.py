"""Parse a SAPHIR experiment action log into timestamped events.

The chamber log is copy-pasted as lines like::

    12:36 r M.A. CHANGE: Close Roof
    13:05 X L.M. CHANGE: Inject 16 uL Hydrocarbon solution
    14:55 $ M.A. STATUS: The roof will be kept open overnight ...
                         (continuation lines are appended to the previous event)

Format per line: ``HH:MM <code> <initials> CHANGE|STATUS: <description>``. Times
carry no date, so they are anchored to the experiment date (first data point)
with roll-over to the next day if the clock decreases (multi-day experiments).

Action codes (SAPHIR convention):
  H/h humidification · F/f flushing · Z/z humidified flow · P/p (de)pressurize ·
  R/r roof · U/u UV lamp · V/v fans · O ozone · D NO2 · M NO · c CO · C CO2 ·
  X VOC · Y/y PLUS transfer · S/s seed · J/j JULIAC · $ comment/status
"""
from __future__ import annotations

import re

import pandas as pd

CODE_LABELS = {
    "H": "Humidification on", "h": "Humidification off",
    "F": "Flushing on", "f": "Flushing off",
    "Z": "Humidified flow on", "z": "Humidified flow off",
    "P": "Pressurize", "p": "Depressurize",
    "R": "Roof open", "r": "Roof close",
    "U": "UV lamp on", "u": "UV lamp off",
    "V": "Fans on", "v": "Fans off",
    "O": "Ozone", "D": "NO2", "M": "NO", "c": "CO", "C": "CO2", "X": "VOC",
    "Y": "PLUS transfer start", "y": "PLUS transfer stop",
    "S": "Seed injection start", "s": "Seed injection stop",
    "J": "JULIAC start", "j": "JULIAC stop", "$": "Comment / status",
}

CATEGORY_COLORS = {
    "VOC": "#2ca02c",
    "Gas / oxidant": "#d62728",
    "Physical": "#1f77b4",
    "Seed / transfer": "#9467bd",
    "Comment": "#7f7f7f",
    "Other": "#555555",
}

_LINE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s+(.*?)\s+(CHANGE|STATUS)\s*:\s*(.*)$",
                   re.IGNORECASE)


def _category(code: str) -> str:
    if code == "X":
        return "VOC"
    if code in ("O", "D", "M", "c", "C"):
        return "Gas / oxidant"
    if code == "$":
        return "Comment"
    if code in ("S", "s", "Y", "y", "J", "j"):
        return "Seed / transfer"
    if code[:1].upper() in ("R", "U", "V", "F", "H", "Z", "P"):
        return "Physical"
    return "Other"


_EMPTY = pd.DataFrame(columns=["time", "code", "who", "kind", "description",
                               "label", "category", "color"])


def parse_action_log(text: str, base_time) -> pd.DataFrame:
    """Parse a pasted log; anchor HH:MM to ``base_time``'s date. Returns a
    DataFrame sorted by time (empty if nothing parseable)."""
    if not text or not text.strip():
        return _EMPTY.copy()
    base = pd.Timestamp(base_time).normalize()

    rows = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = _LINE.match(line)
        if not m:
            if rows:  # continuation of the previous event's description
                rows[-1]["description"] += " " + line.strip()
            continue
        hh, mm, mid, kind, desc = m.groups()
        parts = mid.split()
        code = parts[0] if parts else ""
        who = " ".join(parts[1:]) if len(parts) > 1 else ""
        rows.append({"hh": int(hh), "mm": int(mm), "code": code, "who": who,
                     "kind": kind.upper(), "description": desc.strip()})
    if not rows:
        return _EMPTY.copy()

    times, day, prev = [], 0, None
    for r in rows:
        t = base + pd.Timedelta(hours=r["hh"], minutes=r["mm"], days=day)
        if prev is not None and t < prev:
            day += 1
            t += pd.Timedelta(days=1)
        times.append(t)
        prev = t

    df = pd.DataFrame(rows)
    df["time"] = times
    df["label"] = df["code"].map(lambda c: CODE_LABELS.get(c, c))
    df["category"] = df["code"].map(_category)
    df["color"] = df["category"].map(CATEGORY_COLORS).fillna("#555555")
    return df[["time", "code", "who", "kind", "description", "label",
               "category", "color"]].sort_values("time").reset_index(drop=True)


def first_time(events: pd.DataFrame, codes) -> pd.Timestamp | None:
    """Earliest event time whose code is in ``codes`` (e.g. the first VOC 'X')."""
    if events is None or events.empty:
        return None
    hit = events[events["code"].isin(list(codes))]
    return pd.Timestamp(hit["time"].min()) if not hit.empty else None
