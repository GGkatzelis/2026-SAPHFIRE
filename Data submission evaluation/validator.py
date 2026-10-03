"""Check one submitted file against the SAPHFIRE 2026 rules (see ``rules.py``).

Read-only: nothing here writes, moves or modifies a submission. Every check
looks at the *whole* file, not an excerpt, and returns ``Check`` records with a
status of PASS / INFO / WARN / FAIL plus the evidence (examples) behind it.

    report = evaluate_file(Path(".../2026-06-30.PTRMS.FZJ.csv"))
    report.verdict   # "REJECTED" / "NEEDS CONFIRMATION" / "ACCEPTED"
"""
from __future__ import annotations

import datetime as dt
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

import rules as R

# Rule labels used to group checks in the report.
LOC = "Upload location"
R1 = "Rule 1 · Filename and one UTC day per file"
R2 = "Rule 2 · File format"
R3 = "Rule 3 · Time in UTC"
R4 = "Rule 4 · Column names and units"
R5 = "Rule 5 · Missing data"
R6 = "Rule 6 · Comments"
R7 = "Rule 7 · Sampling intervals"
R8 = "Rule 8 · Metadata"
RULE_ORDER = [LOC, R1, R2, R3, R4, R5, R6, R7, R8]

STATUS_RANK = {"PASS": 0, "INFO": 1, "WARN": 2, "FAIL": 3}
MAX_EXAMPLES = 2000          # kept in full for the team fix list; tables show the first few


@dataclass
class Check:
    rule: str
    status: str                     # PASS / INFO / WARN / FAIL
    message: str
    examples: list[str] = field(default_factory=list)


@dataclass
class FileReport:
    path: Path
    kind: str                       # "data" / "metadata" / "unexpected"
    instrument: str | None = None
    institution: str | None = None
    date: dt.date | None = None
    checks: list[Check] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def add(self, rule, status, message, examples=None):
        self.checks.append(Check(rule, status, message, list(examples or [])[:MAX_EXAMPLES]))

    @property
    def worst(self) -> str:
        return max((c.status for c in self.checks), key=STATUS_RANK.get, default="PASS")

    @property
    def verdict(self) -> str:
        return {"FAIL": "REJECTED", "WARN": "NEEDS CONFIRMATION"}.get(self.worst, "ACCEPTED")

    def count(self, status: str) -> int:
        return sum(c.status == status for c in self.checks)


# ============================================================================
# Entry point
# ============================================================================
def evaluate_file(path: Path, incoming: Path | None = None, metadata_dirs=()) -> FileReport:
    """``metadata_dirs``: further places to look for the instrument's metadata file
    (the archive), after the data file's own folder."""
    path = Path(path)
    name = path.name
    if name.startswith("Metadata."):
        rep = FileReport(path, "metadata")
    elif path.suffix.lower() in R.DATA_EXTENSIONS:
        rep = FileReport(path, "data")
    else:
        rep = FileReport(path, "unexpected")

    if incoming is not None:
        _check_location(rep, Path(incoming))

    if rep.kind == "unexpected":
        rep.add(R2, "FAIL", f"File type '{path.suffix or '(none)'}' is not accepted. Only .csv, "
                "HDF5 (.h5) or SAPHIR NetCDF (.nc) data files and Metadata.*.txt files can be "
                "processed. Excel, tab-separated and other formats are rejected.")
        return rep
    if rep.kind == "metadata":
        _validate_metadata(rep)
        return rep

    native = R.SAPHIR_NATIVE_RE.match(name)
    if native:
        rep.summary["native"] = native["product"]
        rep.add(R1, "PASS", f"Native SAPHIR data-system file ({native['product']}); keeps its own "
                "name, as allowed for internal SAPHIR formats.")
        try:
            rep.date = dt.date.fromisoformat(native["date"])
            _check_campaign_day(rep)
        except ValueError:
            rep.add(R1, "FAIL", f"'{native['date']}' is not a valid calendar date.")
        meta = None
    else:
        _check_data_name(rep)
        meta = _find_metadata(path, rep, metadata_dirs)
    ext = path.suffix.lower()
    try:
        if ext == ".csv":
            _validate_csv(rep, meta)
        elif ext == ".h5":
            _validate_h5(rep, meta)
        else:
            _validate_nc(rep, meta)
    except Exception as exc:  # a crash is itself a finding, never silent
        rep.add(R2, "FAIL", f"The file could not be read: {type(exc).__name__}: {exc}")
    return rep


def _check_location(rep: FileReport, incoming: Path):
    try:
        rel = rep.path.resolve().relative_to(incoming.resolve())
    except ValueError:
        return
    if len(rel.parts) > 1:
        rep.add(LOC, "FAIL", "File is inside a subfolder of Incoming-Upload. Please upload flat, "
                "directly into Incoming-Upload, without your own folder structure.",
                ["/".join(rel.parts[:-1])])
    else:
        rep.add(LOC, "PASS", "Uploaded directly into Incoming-Upload (flat).")


# ============================================================================
# Rule 1: filenames
# ============================================================================
def _check_tokens(rep: FileReport, instrument: str, institution: str):
    if instrument in R.INSTRUMENTS:
        rep.add(R1, "PASS", f"Instrument token '{instrument}' is valid "
                f"({R.INSTRUMENTS[instrument][0]}).")
        if instrument == "NH4CHARON":
            rep.add(R1, "WARN", "NH4CHARON is the token printed in the PDF by mistake; the "
                    "instrument is H3O+ CHARON. Please use H3OCHARON.")
    else:
        near = [t for t in R.INSTRUMENTS if t.lower() == instrument.lower()
                or t.replace("-", "") == instrument.upper().replace("-", "")]
        if near:
            rep.add(R1, "FAIL", f"Instrument token '{instrument}' differs from the registered "
                    f"token '{near[0]}' only in spelling. Please use '{near[0]}'.")
        else:
            rep.add(R1, "WARN" if R.TOKENS_OPEN else "FAIL",
                    f"Instrument token '{instrument}' is not registered yet. It will be added to "
                    "the token table; please confirm the spelling with us.",
                    [", ".join(R.INSTRUMENTS)])
    if institution in R.INSTITUTIONS:
        rep.add(R1, "PASS", f"Institution token '{institution}' is valid.")
    else:
        near = [t for t in R.INSTITUTIONS if t.lower() == institution.lower()]
        if near:
            rep.add(R1, "FAIL", f"Institution token '{institution}' differs from the registered "
                    f"token '{near[0]}' only in spelling. Please use '{near[0]}'.")
        else:
            rep.add(R1, "WARN" if R.TOKENS_OPEN else "FAIL",
                    f"Institution token '{institution}' is not registered yet; please confirm.",
                    [", ".join(sorted(R.INSTITUTIONS))])
    if instrument in R.INSTRUMENTS and institution in R.INSTITUTIONS:
        leads = R.INSTRUMENTS[instrument][1]
        if institution not in leads:
            rep.add(R1, "WARN", f"Institution '{institution}' is not listed as a lead for "
                    f"'{instrument}' (expected one of {', '.join(sorted(leads))}). Please confirm.")


def _check_data_name(rep: FileReport):
    name = rep.path.name
    m = R.DATA_NAME_RE.match(name)
    if not m:
        if rep.path.suffix.lower() == ".nc":
            rep.add(R1, "INFO", "Name is not in the YYYY-MM-DD.instrument.institution form. This is "
                    "accepted only for unmodified files from the SAPHIR data system, which keep "
                    "their native names.")
            return
        problems = []
        if " " in name:
            problems.append("contains spaces")
        stem_fields = name.rsplit(".", 1)[0].split(".")
        if len(stem_fields) != 3:
            problems.append(f"has {len(stem_fields) + 1} period-separated fields instead of 4")
        if stem_fields and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", stem_fields[0]):
            problems.append(f"first field '{stem_fields[0]}' is not a YYYY-MM-DD date")
        rep.add(R1, "FAIL", "Filename does not follow YYYY-MM-DD.instrument.institution.csv|h5"
                + (f": {'; '.join(problems)}." if problems else "."), [name])
        return
    try:
        rep.date = dt.date.fromisoformat(m["date"])
    except ValueError:
        rep.add(R1, "FAIL", f"'{m['date']}' in the filename is not a valid calendar date.")
    rep.instrument, rep.institution = m["instrument"], m["institution"]
    rep.add(R1, "PASS", "Filename has the four-field form YYYY-MM-DD.instrument.institution.ext.")
    if rep.date:
        _check_campaign_day(rep)
    _check_tokens(rep, rep.instrument, rep.institution)


def _check_campaign_day(rep: FileReport):
    """Place the file's day in the campaign calendar (experiments workbook)."""
    try:
        import campaign
        exp = campaign.experiment_for(rep.date)
    except Exception:       # workbook missing or unreadable: fall back to the window
        lo, hi = R.CAMPAIGN_WINDOW
        if not lo <= rep.date <= hi:
            rep.add(R1, "WARN", f"Date {rep.date} lies outside the campaign period ({lo} to "
                    f"{hi}). Please confirm this is the UTC day of the data.")
        return
    if exp is None:
        rep.add(R1, "WARN", f"Date {rep.date} is not a campaign day in the experiment calendar. "
                "Please confirm this is the UTC day of the data.")
        return
    rep.summary["experiment"] = f"{exp.label} {exp.start} {exp.title}"
    days = ", ".join(str(d) for d in exp.days)
    rep.add(R1, "INFO", f"{rep.date} belongs to {exp.label if exp.is_experiment else 'a non-experiment day'}: "
            f"{exp.title} ({days}).")


def _find_metadata(path: Path, rep: FileReport, extra_dirs=()) -> dict | None:
    """Locate Metadata.<instr>.<inst>.txt next to the data file or, once it has
    been archived, in ``extra_dirs`` (Archive - Download/Metadata) (Rule 8)."""
    if not (rep.instrument and rep.institution):
        return None
    name = f"Metadata.{rep.instrument}.{rep.institution}.txt"
    mpath = next((d / name for d in [path.parent, *map(Path, extra_dirs)] if (d / name).exists()),
                 None)
    if mpath is None:
        rep.add(R8, "FAIL", f"No metadata file '{name}' was found in Incoming-Upload or the "
                "archive. It is required for every instrument, whatever the data format, because "
                "the time reference and the author list come from it.")
        return None
    meta, _ = parse_metadata(mpath)
    where = "" if mpath.parent == path.parent else " (already archived)"
    rep.add(R8, "PASS", f"Metadata file '{name}' is present{where}; it is evaluated separately.")
    rep.summary["metadata_file"] = str(mpath)
    words = re.findall(r"[a-z]+", (meta.get("time_reference") or "").lower())
    norm = {R.TIME_REFERENCE_VALUES[w] for w in words if w in R.TIME_REFERENCE_VALUES}
    if len(norm) == 1:
        rep.summary["time_reference"] = norm.pop()
    fmt = (meta.get("data_format") or "").strip().lower().lstrip(".")
    ext = path.suffix.lower().lstrip(".")
    if fmt and fmt != ext and not (fmt in {"hdf5", "hdf"} and ext == "h5") \
            and not (fmt in {"netcdf", "saphir"} and ext == "nc"):
        rep.add(R8, "WARN", f"Metadata says data_format = '{fmt}' but this file is .{ext}.")
    return meta


# ============================================================================
# Shared column / time / value checks (used by CSV, HDF5 and NetCDF)
# ============================================================================
def _formula_parity_ok(formula: str) -> bool:
    """Nitrogen rule: a closed-shell neutral has an even (H + halogens + N + P)."""
    odd = 0
    for el, n in R.ELEMENT_RE.findall(formula):
        k = int(n) if n else 1
        if el in {"H", "F", "Cl", "Br", "I", "N", "P"}:
            odd += k
    return odd % 2 == 0


def formula_mass(formula: str) -> float | None:
    """Monoisotopic neutral mass; None if an element is unknown."""
    total = 0.0
    for el, n in R.ELEMENT_RE.findall(formula):
        if el not in R.MONOISOTOPIC:
            return None
        total += R.MONOISOTOPIC[el] * (int(n) if n else 1)
    return total


def _fitting_formula(formula: str, ion_mz: float, add: float) -> str | None:
    """Nearest variant of ``formula`` (H -6..+6, O -1..+1) whose ion matches ``ion_mz``."""
    counts = {el: int(n) if n else 1 for el, n in R.ELEMENT_RE.findall(formula)}
    best = None
    for dh in range(-6, 7):
        for do in (-1, 0, 1):
            c = dict(counts)
            c["H"] = c.get("H", 0) + dh
            c["O"] = c.get("O", 0) + do
            if c["H"] < 0 or c["O"] < 0 or (dh == 0 and do == 0):
                continue
            name = "".join(f"{el}{c[el]}" for el in c if c[el] > 0)
            m = formula_mass(name)
            if m is not None and abs(m + add - ion_mz) <= R.MASS_TOLERANCE:
                d = abs(m + add - ion_mz)
                if best is None or d < best[0]:
                    best = (d, name, m + add)
    return f"{best[1]} ({best[2]:.3f})" if best else None


def _check_formula_mass_suffixes(rep: FileReport, suffixed: list[tuple[str, str, float]],
                                 plain: set[str]) -> list[str]:
    """Columns like 'C6H6O1_m97.069': does the stated m/z fit formula + reagent ion?
    Returns the columns that were explained here (so they are not reported twice)."""
    label, add = R.REAGENT_IONS.get(rep.instrument, (None, None))
    if label is None:
        return []
    agree, disagree = [], []
    for orig, formula, mz in suffixed:
        neutral = formula_mass(formula)
        if neutral is None:
            continue
        expected = neutral + add
        twin = f"; {formula} is also a separate column" if formula in plain else ""
        if abs(mz - expected) <= R.MASS_TOLERANCE:
            agree.append(f"{orig}: m/z {mz:.3f} = {formula}·{label} ({expected:.3f}){twin}")
        else:
            fit = _fitting_formula(formula, mz, add)
            disagree.append(f"{orig}: m/z {mz:.3f} does not fit {formula}·{label} "
                            f"({expected:.3f})" + (f", but fits {fit.split(' ')[0]}·{label} "
                            f"{fit.split(' ')[1]}" if fit else "") + twin)
    if disagree:
        rep.add(R4, "WARN", f"{len(disagree)} column name(s) give a formula and an m/z that "
                f"disagree (expected ion = neutral formula + {label}). Please check the formula "
                "assignment.", disagree)
    if agree:
        rep.add(R4, "WARN", f"{len(agree)} column name(s) carry an m/z suffix that agrees with the "
                "formula, probably to tell a second peak or isomer apart. Use the plain neutral "
                "formula, or explain the suffix in the metadata comments.", agree)
    return [s.split(":")[0] for s in agree + disagree]


def _check_quantities_units(rep: FileReport, cols: list[tuple[str, str, str]],
                            native: bool = False):
    """``cols`` = (original name, quantity, unit) for every data variable.
    ``native``: SAPHIR data-system file, whose blank units are accepted as is."""
    empty, non_ascii, ion_mass, ion_charge, not_formula, odd_h = [], [], [], [], [], []
    suggest, noncanon = {}, set()
    suffixed, plain = [], set()          # 'C6H6O1_m97.069' style names; plain formulas
    for orig, qty, unit in cols:
        if unit is None:
            continue
        if not unit.strip():
            empty.append(orig)
        elif not unit.isascii():
            non_ascii.append(orig)
        elif unit not in R.CANONICAL_UNITS and "/" not in unit:
            if unit in R.UNIT_SUGGESTIONS or unit.lower() in R.UNIT_SUGGESTIONS:
                suggest[unit] = R.UNIT_SUGGESTIONS.get(unit, R.UNIT_SUGGESTIONS.get(unit.lower()))
            else:
                noncanon.add(unit)
        if not qty.isascii():
            non_ascii.append(orig)
        if R.ION_MASS_RE.match(qty):
            ion_mass.append(orig)
        elif qty.endswith(("+", "-")) and R.FORMULA_RE.match(qty[:-1] or "x"):
            ion_charge.append(orig)
        elif rep.instrument in R.MS_FORMULA_INSTRUMENTS:
            if not R.FORMULA_RE.match(qty):
                not_formula.append(orig)
                fm = R.FORMULA_MASS_RE.match(qty)
                if fm:
                    suffixed.append((orig, fm["formula"], float(fm["mass"])))
            else:
                plain.add(qty)
                if not _formula_parity_ok(qty):
                    odd_h.append(orig)

    explained = _check_formula_mass_suffixes(rep, suffixed, plain)
    not_formula = [c for c in not_formula if c not in explained]

    if empty and native:
        rep.add(R4, "INFO", f"{len(empty)} variable(s) have a blank unit (native SAPHIR file, "
                "accepted as is; e.g. status flags such as the roof position).", empty)
        empty = []
    if empty:
        rep.add(R4, "FAIL", f"{len(empty)} variable(s) have an empty unit. Write 1 or a.u. for a "
                "quantity without a unit, never a blank.", empty)
    if non_ascii and native:
        rep.add(R4, "INFO", "Non-ASCII characters in names or units (native SAPHIR file, "
                "accepted as is).", sorted(set(non_ascii)))
        non_ascii = []
    if non_ascii:
        rep.add(R4, "FAIL", f"{len(non_ascii)} variable name(s) or unit(s) contain non-ASCII "
                "characters (e.g. superscripts, µ, °). Use ASCII only, e.g. ug m-3, degC.",
                sorted(set(non_ascii)))
    if ion_mass:
        rep.add(R4, "FAIL", f"{len(ion_mass)} of {len(cols)} variables are named by ion mass "
                "instead of the chemical formula of the neutral molecule. Quantified data "
                "without a formula assignment cannot be used; assign a formula or remove these "
                "columns.", ion_mass)
    if ion_charge:
        rep.add(R4, "FAIL", f"{len(ion_charge)} variable(s) are named as ions (trailing + or -). "
                "Use the neutral formula with the ionising agent subtracted.", ion_charge)
    if not_formula:
        rep.add(R4, "WARN", f"{len(not_formula)} variable(s) are not a plain chemical formula. "
                "Mass spectrometry columns should be named by the neutral formula (e.g. C10H16).",
                not_formula)
    if odd_h:
        rep.add(R4, "WARN", f"{len(odd_h)} formula(s) do not correspond to a closed-shell neutral "
                "molecule (odd H+N count). Check that the ionising agent (H+, NH4+, ...) was "
                "subtracted; radicals are fine if intended.", odd_h)
    if suggest:
        rep.add(R4, "INFO" if native else "WARN", "Non-canonical unit strings with an obvious canonical form. They are "
                "accepted but will not be converted automatically.",
                [f"'{u}' -> '{c}'" for u, c in suggest.items()])
    if noncanon:
        rep.add(R4, "INFO", "Units outside the canonical list (accepted, never converted).",
                sorted(noncanon))
    if not (empty or non_ascii or ion_mass or ion_charge):
        rep.add(R4, "PASS", f"All {len(cols)} variables carry a non-empty ASCII unit.")


def _check_time_axis(rep: FileReport, t: pd.Series, label: str = R.TIME_COL):
    """Rule 1 (one UTC day), duplicates, ordering, gaps; fills rep.summary."""
    t = t.dropna()
    if t.empty:
        rep.add(R3, "FAIL", f"'{label}' contains no valid timestamps.")
        return
    first, last = t.min(), t.max()
    rep.summary.update(first=str(first), last=str(last), n_times=int(len(t)))
    if rep.date is not None:
        day = t.dt.date
        outside = t[day != rep.date]
        if len(outside):
            msg = (f"{len(outside)} of {len(t)} rows are not on {rep.date} (the UTC day in the "
                   "filename). Each file must hold exactly one UTC calendar day, 00:00:00 to "
                   "23:59:59.")
            prev = outside[outside.dt.date < rep.date]
            nxt = outside[outside.dt.date > rep.date]
            if len(prev) and (prev.dt.hour >= 22).all() or len(nxt) and (nxt.dt.hour < 2).all():
                msg += (" The spill-over is within 2 h of midnight, which is typical of local "
                        "time (CEST = UTC+2) or a split on local midnight.")
            rep.add(R1, "FAIL", msg, [str(x) for x in outside.iloc[[0, -1]].unique()])
        else:
            rep.add(R1, "PASS", f"All timestamps fall on {rep.date} (UTC).")
    dups = t[t.duplicated(keep=False)]
    if len(dups):
        rep.add(R3, "FAIL", f"{dups.nunique()} duplicated timestamp(s) in '{label}'.",
                [str(x) for x in dups.unique()])
    back = int((t.diff().dt.total_seconds() < 0).sum())
    if back:
        rep.add(R3, "WARN", f"Timestamps are not in increasing order ({back} step(s) go "
                "backwards). Please sort by time.")
    if not len(dups) and not back:
        rep.add(R3, "PASS", f"'{label}' is strictly increasing with no duplicates "
                f"({first:%H:%M:%S} to {last:%H:%M:%S}).")
    steps = t.sort_values().diff().dt.total_seconds().dropna()
    if len(steps):
        med = float(steps.median())
        rep.summary["median_step_s"] = med
        big = steps[steps > max(5 * med, 600)]
        if len(big):
            ts = t.sort_values()
            ex = [f"{ts.iloc[i - 1]:%H:%M:%S} to {ts.iloc[i]:%H:%M:%S} ({steps.iloc[i - 1] / 60:.0f} min)"
                  for i in (steps.reset_index(drop=True).nlargest(5).index + 1)]
            rep.add(R3, "INFO", f"{len(big)} gap(s) longer than {max(5 * med, 600) / 60:.0f} min "
                    "in the time series.", ex)
    if "native" in rep.summary:      # SAPHIR data system writes UTC
        return
    rep.add(R3, "INFO", "UTC itself cannot be verified from the numbers alone. Please confirm "
            "the instrument clock and the conversion to UTC (Germany was UTC+2 in July).")


def _check_intervals(rep: FileReport, t: pd.Series, meta: dict | None, irregular: bool,
                     t_end: pd.Series | None = None):
    if irregular and t_end is not None:
        bad = (t_end < t).sum()
        if bad:
            rep.add(R7, "FAIL", f"{int(bad)} row(s) have time_utc_end before time_utc.")
        else:
            rep.add(R7, "PASS", "Irregular intervals are declared with a time_utc_end column.")
        return
    steps = t.dropna().sort_values().diff().dt.total_seconds().dropna()
    integ = None
    if meta:
        try:
            integ = float(meta.get("integration_time_s", "").split()[0])
        except (ValueError, IndexError):
            integ = None
    if integ is None:
        rep.add(R7, "WARN", "No time_utc_end column and no integration_time_s in the metadata. "
                "Declare the integration time once in the metadata file (regular sampling) or "
                "add time_utc_end (irregular sampling).")
    if len(steps) > 2:
        med = float(steps.median())
        regular = float((abs(steps - med) <= 0.1 * med + 0.5).mean())
        rep.summary["regular_fraction"] = regular
        if regular < 0.8:
            rep.add(R7, "WARN", f"Sampling looks irregular (only {regular:.0%} of steps are within "
                    f"10 % of the median {med:g} s). If each sample has its own interval, add a "
                    "time_utc_end column.")
        elif integ is not None and abs(med - integ) > 0.5 * integ + 1:
            rep.add(R7, "WARN", f"Median time step ({med:g} s) differs from integration_time_s "
                    f"= {integ:g} in the metadata. Fine for duty-cycled instruments; otherwise "
                    "please check.")
        elif integ is not None:
            rep.add(R7, "PASS", f"Regular sampling ({regular:.0%} of steps at {med:g} s), "
                    f"consistent with integration_time_s = {integ:g}.")


def _check_values(rep: FileReport, data: dict[str, np.ndarray], bad_tokens: dict[str, set],
                  native: bool = False):
    """Rule 5 on numeric arrays. ``bad_tokens``: non-numeric text found per column (CSV).
    ``native``: SAPHIR file; zeros there are real states (roof, valves), so INFO only."""
    if bad_tokens:
        ex = [f"{c}: {', '.join(repr(x) for x in sorted(v)[:3])}" for c, v in bad_tokens.items()]
        rep.add(R5, "FAIL", f"{len(bad_tokens)} column(s) contain text that is not a number. "
                "Missing data must be blank or NaN; text such as N/A, -, error flags or decimal "
                "commas is not allowed.", ex)
    fills, suspect, infs, zeros, empty, negcols, nonint = {}, {}, {}, {}, [], 0, []
    total = n_nan = n_zero = 0
    for name, arr in data.items():
        a = np.asarray(arr)
        if not np.issubdtype(a.dtype, np.floating):
            if np.issubdtype(a.dtype, np.integer):
                nonint.append(name)
            a = a.astype(float)
        total += a.size
        nan = np.isnan(a)
        n_nan += int(nan.sum())
        if nan.all():
            empty.append(name)
            continue
        inf = np.isinf(a)
        if inf.any():
            infs[name] = int(inf.sum())
        fin = a[np.isfinite(a)]
        f = np.isin(fin, list(R.FILL_VALUES)) | (np.abs(fin) >= R.FILL_ABS_LIMIT)
        if f.any():
            fills[name] = int(f.sum())
        # A fill value repeats exactly; noise around zero (e.g. OH in cm-3) does not.
        low = fin[(fin <= R.SUSPECT_NEGATIVE) & ~f]
        if low.size:
            vals, counts = np.unique(low, return_counts=True)
            rep_vals = vals[counts >= 3]
            if rep_vals.size:
                suspect[name] = f"{int(counts[counts >= 3].sum())} x {rep_vals[0]:g}"
        z = int((fin == 0).sum())
        n_zero += z
        if z:
            zeros[name] = (z / fin.size, bool((fin < 0).any()))
        if (fin < 0).any():
            negcols += 1

    if fills:
        rep.add(R5, "FAIL", f"Numeric fill values (-999, -9999, 9.97e36, ...) found in "
                f"{len(fills)} column(s). Every number is treated as a real measurement; use "
                "blank or NaN.", [f"{c}: {n} value(s)" for c, n in fills.items()])
    if infs:
        rep.add(R5, "FAIL", f"Infinite values in {len(infs)} column(s).",
                [f"{c}: {n}" for c, n in infs.items()])
    if suspect:
        rep.add(R5, "WARN", f"The same value <= {R.SUSPECT_NEGATIVE:g} repeats in {len(suspect)} "
                "column(s); repeated large negative numbers look like fill values. Please "
                "confirm they are real.", [f"{c}: {n}" for c, n in suspect.items()])
    if zeros:
        frac_all = n_zero / max(total - n_nan, 1)
        top = sorted(zeros.items(), key=lambda kv: -kv[1][0])
        clipped = [c for c, (fr, has_neg) in zeros.items() if fr >= 0.01 and not has_neg]
        msg = (f"Exact zeros in {len(zeros)} of {len(data)} variables ({frac_all:.1%} of all valid "
               "values). Zero must never be used as a fill value, so these need to be "
               "confirmed as real measurements.")
        if clipped and negcols:
            msg += (f" {len(clipped)} of these variables have zeros but no negative values while "
                    f"{negcols} other variables do go negative, which suggests negatives were "
                    "clipped to 0 in some columns.")
        if native:
            msg = (f"Exact zeros in {len(zeros)} of {len(data)} variables (native SAPHIR file; "
                   "zeros are expected for status and flow variables).")
        rep.add(R5, "INFO" if native else "WARN", msg,
                [f"{c}: {fr:.1%} zeros" for c, (fr, _) in top])
    if empty:
        rep.add(R5, "INFO" if native else "WARN",
                f"{len(empty)} variable(s) contain no valid data at all.", empty)
    if nonint:
        rep.add(R5, "WARN", f"{len(nonint)} variable(s) are stored as integers, which cannot hold "
                "NaN. Store measurements as floats.", nonint)
    rep.summary["nan_fraction"] = n_nan / total if total else 0.0
    if not (fills or infs or bad_tokens):
        rep.add(R5, "PASS", f"No numeric fill values or text in the data. Missing values: "
                f"{n_nan} ({rep.summary['nan_fraction']:.1%}).")


# ============================================================================
# CSV
# ============================================================================
def _validate_csv(rep: FileReport, meta: dict | None):
    raw = rep.path.read_bytes()
    rep.summary["size_MB"] = round(len(raw) / 1e6, 2)
    if raw.startswith(b"\xef\xbb\xbf"):
        rep.add(R2, "INFO", "File starts with a UTF-8 byte-order mark (BOM). Tolerated.")
        raw = raw[3:]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
        rep.add(R2, "FAIL", "File is not UTF-8/ASCII text (looks like a Windows codepage export). "
                "Use plain ASCII.")

    lines = text.splitlines()
    comments = [i for i, l in enumerate(lines) if l.lstrip().startswith("#")]
    body = [(i + 1, l) for i, l in enumerate(lines) if l.strip() and not l.lstrip().startswith("#")]
    rep.add(R6, "PASS" if comments else "INFO",
            f"{len(comments)} comment line(s) starting with # are skipped." if comments
            else "No # comment lines (optional).")
    if not body:
        rep.add(R2, "FAIL", "File contains no header and no data.")
        return

    _, header = body[0]
    if "," not in header:
        sep = ";" if ";" in header else "\\t" if "\t" in header else None
        rep.add(R2, "FAIL", "Header is not comma separated"
                + (f" (uses '{sep}'; typical of German Excel)" if sep else "") + ". Use commas "
                "with a period as decimal separator.", [header[:120]])
        return
    raw_cols = header.split(",")
    cols = [c.strip().strip('"').strip() for c in raw_cols]
    if cols != raw_cols:
        rep.add(R2, "WARN", "Column names carry surrounding spaces or quotes; they were stripped.")
    ncol = len(cols)
    bad_rows = [(ln, l.count(",") + 1) for ln, l in body[1:] if l.count(",") + 1 != ncol]
    if bad_rows:
        rep.add(R2, "FAIL", f"{len(bad_rows)} row(s) do not have {ncol} comma-separated fields "
                "like the header. Common cause: decimal commas or commas inside values.",
                [f"line {ln}: {n} fields" for ln, n in bad_rows])
    else:
        rep.add(R2, "PASS", f"Comma-separated, {ncol} columns, {len(body) - 1} data rows, "
                "consistent field count.")
    rep.summary.update(rows=len(body) - 1, columns=ncol)

    # --- header (Rules 3, 4, 7) ---
    dupes = sorted({c for c in cols if cols.count(c) > 1})
    if dupes:
        rep.add(R4, "FAIL", f"{len(dupes)} duplicated column name(s).", dupes)
    if cols[0] != R.TIME_COL:
        rep.add(R3, "FAIL", f"First column is '{cols[0]}', it must be named exactly "
                f"'{R.TIME_COL}'.")
        return
    irregular = ncol > 1 and cols[1] == R.TIME_END_COL
    if R.TIME_END_COL in cols[2:]:
        rep.add(R7, "FAIL", f"'{R.TIME_END_COL}' must come immediately after '{R.TIME_COL}'.")
    time_cols = cols[:2] if irregular else cols[:1]
    data_cols = [c for c in cols if c not in time_cols]
    parsed, nobracket = [], []
    for c in data_cols:
        m = R.COLUMN_RE.match(c)
        if m:
            parsed.append((c, m["quantity"], m["unit"]))
        elif re.fullmatch(r".+\[\s*\]", c):
            parsed.append((c, c.split("[")[0].strip(), ""))
        else:
            nobracket.append(c)
    if nobracket:
        rep.add(R4, "FAIL", f"{len(nobracket)} column(s) have no unit in square brackets "
                "('quantity [unit]', one space before the bracket).", nobracket)
    _check_quantities_units(rep, parsed)
    rep.summary["variables"] = len(data_cols)

    # --- load ---
    good = [l for _, l in body] if not bad_rows else [body[0][1]] + [
        l for _, l in body[1:] if l.count(",") + 1 == ncol]
    df = pd.read_csv(io.StringIO("\n".join(good)), header=0, names=cols if not dupes else None,
                     dtype={c: str for c in time_cols}, na_values=sorted(R.MISSING_TOKENS),
                     keep_default_na=False, skipinitialspace=True, low_memory=False)

    # --- time (Rule 3) ---
    t = _parse_time_text(rep, df.iloc[:, 0], R.TIME_COL)
    t_end = _parse_time_text(rep, df.iloc[:, 1], R.TIME_END_COL) if irregular else None
    _check_time_axis(rep, t)
    _check_intervals(rep, t, meta, irregular, t_end)

    # --- values (Rule 5) ---
    data, bad_tokens = {}, {}
    for j, c in enumerate(cols):
        if c in time_cols:
            continue
        s = df.iloc[:, j]
        if not pd.api.types.is_numeric_dtype(s):    # object or pandas-3 'str' dtype
            num = pd.to_numeric(s, errors="coerce")
            bad = s[num.isna() & s.notna()].astype(str).str.strip()
            bad = bad[~bad.isin(R.MISSING_TOKENS)]
            if len(bad):
                bad_tokens[c] = set(bad.unique()[:10])
            s = num
        data[c] = s.to_numpy(dtype=float)
    _check_values(rep, data, bad_tokens)


def _parse_time_text(rep: FileReport, s: pd.Series, label: str) -> pd.Series:
    s = s.astype(str).str.strip()
    ok = s.str.match(R.TIME_TEXT_RE)
    if (~ok).any():
        bad = s[~ok]
        hints = []
        if bad.str.contains("T").any():
            hints.append("uses a 'T' separator")
        if bad.str.contains(r"Z$|[+-]\d{2}:?\d{2}$", regex=True).any():
            hints.append("carries a timezone suffix")
        if bad.str.fullmatch(r"-?\d+(\.\d+)?(e[+-]?\d+)?").any():
            hints.append("is numeric (Igor/MATLAB/epoch time is not allowed in CSV)")
        if bad.str.contains(r"\d{2}[./]\d{2}[./]\d{4}", regex=True).any():
            hints.append("is in day.month.year order")
        if bad.isin(["", "nan", "NaN"]).any():
            hints.append("has empty entries")
        rep.add(R3, "FAIL", f"{len(bad)} value(s) in '{label}' are not 'YYYY-MM-DD hh:mm:ss[.fff]'"
                + (f" ({'; '.join(hints)})" if hints else "") + ".", list(bad.unique()))
    t = pd.to_datetime(s.where(ok), format="ISO8601", errors="coerce")
    invalid = ok & t.isna()
    if invalid.any():
        rep.add(R3, "FAIL", f"{int(invalid.sum())} timestamp(s) in '{label}' are not valid dates.",
                list(s[invalid].unique()))
    elif ok.all():
        rep.add(R3, "PASS", f"'{label}' is text in YYYY-MM-DD hh:mm:ss format.")
    return t


# ============================================================================
# HDF5 (Section 3)
# ============================================================================
_EPOCH_RE = re.compile(r"^\s*seconds\s+since\s+(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}:\d{2}(?:\.\d+)?))?"
                       r"\s*(?:UTC|Z|\+00:?00)?\s*$", re.IGNORECASE)


def _attr_str(obj, key: str) -> str | None:
    v = obj.attrs.get(key)
    if v is None:
        return None
    if isinstance(v, np.ndarray):
        v = v.flat[0] if v.size else ""
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)


def _h5_time(rep: FileReport, ds, label: str) -> pd.Series | None:
    units = _attr_str(ds, "units")
    m = _EPOCH_RE.match(units or "")
    if not m:
        rep.add(R3, "FAIL", f"'{label}' needs a units attribute 'seconds since YYYY-MM-DD "
                f"hh:mm:ss UTC'; found {units!r}. Without the epoch the time axis cannot be read.")
        return None
    if ds.ndim != 1:
        rep.add(R3, "FAIL", f"'{label}' must be one-dimensional, it has shape {ds.shape}.")
        return None
    if ds.dtype != np.float64:
        rep.add(R3, "WARN", f"'{label}' is {ds.dtype}, float64 is expected (precision).")
    epoch = pd.Timestamp(f"{m[1]} {m[2] or '00:00:00'}")
    t = pd.Series(epoch + pd.to_timedelta(ds[()].astype(float), unit="s"))
    rep.add(R3, "PASS", f"'{label}' has an epoch units attribute ({units}).")
    return t


def _validate_h5(rep: FileReport, meta: dict | None):
    import h5py

    rep.summary["size_MB"] = round(rep.path.stat().st_size / 1e6, 2)
    with h5py.File(rep.path, "r") as f:
        groups = [k for k in f if isinstance(f[k], h5py.Group)]
        dsets = {k: f[k] for k in f if isinstance(f[k], h5py.Dataset)}
        if groups:
            rep.add(R2, "FAIL", f"{len(groups)} group(s) found. The layout must be flat: every "
                    "dataset at the root, no groups (Igor/Tofware exports are not compliant as "
                    "is; use the template script).", groups)
        else:
            rep.add(R2, "PASS", f"Flat HDF5 layout with {len(dsets)} datasets at the root.")
        if R.TIME_COL not in dsets:
            cand = [k for k in dsets if "time" in k.lower()]
            rep.add(R3, "FAIL", f"No dataset named '{R.TIME_COL}'."
                    + (f" Found {', '.join(cand)}." if cand else ""))
            return
        t = _h5_time(rep, dsets[R.TIME_COL], R.TIME_COL)
        if t is None:
            return
        n = len(t)
        t_end = _h5_time(rep, dsets[R.TIME_END_COL], R.TIME_END_COL) \
            if R.TIME_END_COL in dsets else None
        _check_time_axis(rep, t)
        _check_intervals(rep, t, meta, t_end is not None, t_end)

        others = {k: d for k, d in dsets.items() if k not in (R.TIME_COL, R.TIME_END_COL)}
        axis_lens = {d.shape[1] for d in others.values() if d.ndim == 2 and d.shape[0] == n}
        cols, bracketed, shape_bad, data, axes = [], [], [], {}, []
        for k, d in others.items():
            if "[" in k or "]" in k:
                bracketed.append(k)
            cols.append((k, k.split("[")[0].strip(), _attr_str(d, "units") or ""))
            if d.ndim == 1 and d.shape[0] == n:
                data[k] = d[()]
            elif d.ndim == 2 and d.shape[0] == n:
                data[k] = d[()]
            elif d.ndim == 1 and d.shape[0] in axis_lens:
                axes.append(k)
                ax = d[()]
                if np.any(np.diff(ax) <= 0):
                    rep.add(R4, "WARN", f"Bin axis '{k}' is not strictly increasing.")
            else:
                shape_bad.append(f"{k}: shape {d.shape}")
        if bracketed:
            rep.add(R4, "FAIL", "HDF5 dataset names must be plain, the unit belongs in the "
                    "'units' attribute, not in brackets.", bracketed)
        if shape_bad:
            rep.add(R2, "FAIL", f"{len(shape_bad)} dataset(s) do not match the time axis length "
                    f"({n}) and are not a bin axis of a 2-D dataset.", shape_bad)
        if axes:
            rep.add(R2, "PASS", f"2-D spectra/size distributions with bin axis: {', '.join(axes)}.")
        rep.summary.update(rows=n, variables=len(others))
        # every dataset, bin axes included, needs a non-empty 'units' attribute
        _check_quantities_units(rep, cols)
        _check_values(rep, data, {})


# ============================================================================
# NetCDF (native SAPHIR format)
# ============================================================================
def _validate_nc(rep: FileReport, meta: dict | None):
    import netCDF4

    rep.summary["size_MB"] = round(rep.path.stat().st_size / 1e6, 2)
    native = "native" in rep.summary
    with netCDF4.Dataset(rep.path) as nc:
        nc.set_auto_mask(True)
        if native:
            rep.add(R2, "PASS", "Native SAPHIR NetCDF, read directly (time reference, units and "
                    "fill values come from the file itself).")
        else:
            rep.add(R2, "WARN", "NetCDF is accepted only as an unmodified SAPHIR data-system file, "
                    "but this filename does not look like one. Team data should be CSV or HDF5.")
        tvar = None
        for name, v in nc.variables.items():
            u = getattr(v, "units", "")
            if isinstance(u, str) and " since " in u and v.ndim == 1:
                tvar = name
                break
        if tvar is None:
            rep.add(R3, "FAIL", "No time variable with a 'units = <unit> since <epoch>' attribute.")
            return
        v = nc.variables[tvar]
        times = netCDF4.num2date(v[:], v.units, getattr(v, "calendar", "standard"),
                                 only_use_cftime_datetimes=False,
                                 only_use_python_datetimes=True)
        t = pd.Series(pd.to_datetime([x for x in np.ma.compressed(times)]))
        desc = str(getattr(v, "description", "")).strip().rstrip(".")
        rep.add(R3, "PASS", f"Time variable '{tvar}' ({v.units})" + (f"; {desc}" if desc else "")
                + ".")
        if "center" in desc.lower() or "centre" in desc.lower():
            rep.summary["time_reference"] = "centre"
        if rep.date is not None:
            _check_time_axis(rep, t, tvar)
        else:
            rep.summary.update(first=str(t.min()), last=str(t.max()), n_times=len(t))
            days = sorted({d.isoformat() for d in t.dt.date})
            rep.add(R1, "INFO", f"Covers {len(days)} UTC day(s).", days)
        cols, data, companions = [], {}, 0
        for name, var in nc.variables.items():
            if name == tvar or var.ndim == 0:
                continue
            if "@" in name:      # SAPHIR companions: x@STDEV, x@NO_OF_POINTS, time@INTERVAL_T
                companions += 1
                continue
            cols.append((name, name, str(getattr(var, "units", ""))))
            if var.dtype.kind in "fiu" and var.shape and var.shape[0] == len(v):
                data[name] = np.ma.filled(var[:].astype(float), np.nan)
        rep.summary.update(rows=len(t), variables=len(cols))
        if companions:
            rep.add(R2, "INFO", f"{companions} companion variable(s) (name@STDEV, @NO_OF_POINTS, "
                    "@INTERVAL_T) are kept but not checked.")
        _check_quantities_units(rep, cols, native=native)
        _check_values(rep, data, {}, native=native)


# ============================================================================
# Metadata (Rule 8, Section 4)
# ============================================================================
def parse_metadata(path: Path) -> tuple[dict, list[str]]:
    """Return (key -> value, problems). Repeated keys: last wins, except comments."""
    raw = Path(path).read_bytes()
    problems = []
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
        problems.append("not UTF-8")
    meta: dict = {"comments": []}
    seen: dict[str, int] = {}
    for ln, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            problems.append(f"line {ln}: no '=': {s[:60]}")
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = re.split(r"\s+#", v, maxsplit=1)[0].strip()
        seen[k] = seen.get(k, 0) + 1
        if k in R.METADATA_REPEATABLE:
            meta["comments"].append(v)
        else:
            meta[k] = v
    meta["_repeated"] = [k for k, n in seen.items() if n > 1 and k not in R.METADATA_REPEATABLE]
    return meta, problems


def _validate_metadata(rep: FileReport):
    m = R.METADATA_NAME_RE.match(rep.path.name)
    if not m:
        rep.add(R8, "FAIL", "Metadata filename must be Metadata.instrument.institution.txt.",
                [rep.path.name])
    else:
        rep.instrument, rep.institution = m["instrument"], m["institution"]
        rep.add(R8, "PASS", "Metadata filename has the form Metadata.instrument.institution.txt.")
        _check_tokens(rep, rep.instrument, rep.institution)

    meta, problems = parse_metadata(rep.path)
    rep.summary["metadata"] = {k: v for k, v in meta.items() if not k.startswith("_")}
    for p in problems:
        rep.add(R8, "FAIL" if p != "not UTF-8" else "WARN", f"Metadata format problem: {p}. Use "
                "one 'key = value' per line.")
    if meta["_repeated"]:
        rep.add(R8, "WARN", "Keys given more than once (only 'comments' may repeat; the last value "
                "is used).", meta["_repeated"])
    lower = {k.lower(): k for k in meta if not k.startswith("_")}
    missing = [k for k in R.METADATA_REQUIRED if not str(meta.get(k, "")).strip()]
    wrong_case = [lower[k] for k in missing if k in lower]
    if missing:
        rep.add(R8, "FAIL", "Required keys missing or empty.", missing)
    if wrong_case:
        rep.add(R8, "WARN", "Keys must be lower case as in the template.", wrong_case)
    rec = [k for k in R.METADATA_RECOMMENDED if not str(meta.get(k, "")).strip()]
    if rec:
        rep.add(R8, "INFO", "Recommended keys not given.", rec)
    unknown = [k for k in meta if not k.startswith("_") and k not in R.METADATA_KNOWN]
    if unknown:
        rep.add(R8, "INFO", "Keys not in the template (kept, not used by the tool).", unknown)

    if rep.instrument and meta.get("instrument") and meta["instrument"] != rep.instrument:
        rep.add(R8, "FAIL", f"instrument = '{meta['instrument']}' does not match the filename "
                f"token '{rep.instrument}'.")
    # Several institutions may share an instrument (e.g. 'institution = FZJ; UOW'); the
    # filename carries one of them, the metadata credits all of them.
    credited = [t for t in re.split(r"[;,/\s]+", meta.get("institution", "")) if t]
    if rep.institution and credited and rep.institution not in credited:
        rep.add(R8, "FAIL", f"institution = '{meta['institution']}' does not include the filename "
                f"token '{rep.institution}'.")
    elif len(credited) > 1:
        unknown = [t for t in credited if t not in R.INSTITUTIONS]
        rep.add(R8, "WARN" if unknown else "PASS",
                f"Data credited to {len(credited)} institutions: {', '.join(credited)}."
                + (f" Not registered yet: {', '.join(unknown)}." if unknown else ""))

    tr = (meta.get("time_reference") or "").lower()
    norm = {R.TIME_REFERENCE_VALUES[w] for w in re.findall(r"[a-z]+", tr)
            if w in R.TIME_REFERENCE_VALUES}
    if tr and len(norm) == 1:
        rep.add(R3, "PASS", f"time_reference = '{meta['time_reference']}' -> interval "
                f"{norm.pop()}.")
    elif tr:
        rep.add(R3, "FAIL", f"time_reference = '{meta['time_reference']}' must state 'start' or "
                "'centre' of the averaging interval.")

    pe = meta.get("pi_email", "")
    if pe and not R.EMAIL_RE.match(pe):
        rep.add(R8, "FAIL", f"pi_email '{pe}' is not a valid email address.")
    if pe and rep.institution in R.INSTITUTIONS:
        dom = pe.rsplit("@", 1)[-1].lower()
        inst = next((t for d, t in R.EMAIL_DOMAINS.items() if dom == d or dom.endswith("." + d)),
                    None)
        if inst and inst not in (credited or [rep.institution]):
            rep.add(R8, "WARN", f"institution is '{meta.get('institution', rep.institution)}' but the "
                    f"PI email domain ({dom}) belongs to {inst}. If both institutions should be "
                    f"credited, write 'institution = {rep.institution}; {inst}' in the metadata.")

    co = meta.get("coauthors", "")
    if co:
        items = [x.strip() for x in co.split(";") if x.strip()]
        bad, initials, names = [], [], []
        for it in items:
            mm = R.COAUTHOR_RE.match(it)
            if not mm or not R.EMAIL_RE.match(mm["email"].strip()):
                bad.append(it)
                continue
            nm = mm["name"].strip()
            names.append(nm)
            words = nm.split()
            if len(words) < 2 or any(re.fullmatch(r"[A-Z]\.?(-[A-Z]\.?)?", w) for w in words):
                initials.append(nm)
        if bad:
            rep.add(R8, "FAIL", "Coauthor entries must be 'Full Name <email>' separated by ';'.", bad)
        if initials:
            rep.add(R8, "WARN", "Coauthors should be given with full names, not initials.", initials)
        if not bad:
            rep.add(R8, "PASS", f"{len(names)} coauthor(s) with names and email addresses.", names)

    it = meta.get("integration_time_s")
    if it:
        try:
            if float(it.split()[0]) <= 0:
                raise ValueError
        except (ValueError, IndexError):
            rep.add(R7, "WARN", f"integration_time_s = '{it}' is not a positive number of seconds.")
    fmt = (meta.get("data_format") or "").lower()
    if fmt and fmt not in {"csv", "h5", "hdf5", "nc", "netcdf"}:
        rep.add(R8, "WARN", f"data_format = '{fmt}' should be csv, h5 or nc.")
