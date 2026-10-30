"""SAPHFIRE 2026 submission rules, transcribed from
``SAPHFIRE_2026_Data_Submission_Format.pdf`` (the version shared with teams).

Everything the validator treats as a *rule* is here, so adding a token or
tightening a check means editing this file only. Section numbers refer to the
PDF.
"""
from __future__ import annotations

import datetime as dt
import re

# --- Section 2, Rule 1: tokens -------------------------------------------------
# The token list is deliberately OPEN: a token not listed here is a WARN ("not yet
# registered"), not a rejection. Add tokens here as teams submit (e.g. EESI,
# NO3CIMS, the uronium Orbitrap, a separate CPC, GC-MS).
TOKENS_OPEN = True

# instrument token -> (description, allowed institution tokens = "Lead" column)
INSTRUMENTS: dict[str, tuple[str, set[str]]] = {
    "PTRMS":        ("H3O+ PTR-ToF-MS",                          {"FZJ", "UOW"}),
    "WALLE":        ("Br- WALL-E Orbitrap, gas + particle phase and volatility", {"FZJ", "IRCELYON"}),
    # AMS: chamber (bypass) time series only; the thermodenuder results go into a
    # separate thermogram file (decision 26 Oct 2026). AMSTD is the token in the PDF.
    "AMS":            ("Aerosol mass spectrometer, chamber (bypass) data", {"FZJ", "PATRAS"}),
    "AMS-THERMOGRAM": ("AMS thermograms: mass fraction remaining vs thermodenuder temperature",
                       {"FZJ", "PATRAS"}),
    "AMS-SPECTRA":    ("AMS mass spectra averaged per period (normalised OA fractions)",
                       {"FZJ", "PATRAS"}),
    "AMSTD":        ("Aerosol mass spectrometer (token as printed in the PDF; prefer AMS)",
                     {"FZJ", "PATRAS"}),
    # The PDF says NH4CHARON, but the reagent ion is H3O+ (PDF typo, 2026-10-03).
    "H3OCHARON":    ("H3O+ CHARON inlet, aerosol composition",   {"FZJ", "PATRAS"}),
    "NH4CHARON":    ("H3O+ CHARON (token as printed in the PDF; prefer H3OCHARON)", {"FZJ", "PATRAS"}),
    "SMPS-AMS":     ("SMPS in the aerosol container",            {"FZJ", "PATRAS"}),
    "SMPS-WALLE":   ("SMPS in the VOC container",                {"FZJ", "PATRAS"}),
    "CPC-WALLE":    ("CPC in the VOC container (next to the SMPS)", {"FZJ", "PATRAS"}),
    "AETHALOMETER": ("Brown carbon absorption",                  {"PATRAS"}),
    "FILTERS":      ("Filter sampling, oxidative potential",     {"FZJ", "PATRAS"}),
    # Built by import_saphir.py from the SAPHIR spectroradiometer files on Z:.
    "JVALUES":      ("Photolysis frequencies, spectroradiometer (chamber + ambient)", {"FZJ"}),
}
INSTITUTIONS = {"FZJ", "UOW", "PATRAS", "IRCELYON"}

# Rows of the submission status page: (label, row name in the experiments
# workbook or None if always expected, file keys). A file key is the instrument
# token of a team file or the product of a native SAPHIR file. Tokens marked
# "TBD" are guesses until the team submits; files with other unknown tokens are
# listed in an extra row automatically.
STATUS_ROWS: list[tuple[str, str | None, tuple[str, ...]]] = [
    ("SAPHIR chamber data",       None,                  ("SAPHIR.collected.all_param",)),
    ("Meteorology",               None,                  ("ASS_METEO.all_param",)),
    ("J-values",                  "J-values",            ("JVALUES",)),
    ("LIF (OH, HO2, RO2)",        "LIF",                 ("SAPHIR.LIF.ROx", "LIF")),
    ("kOH",                       "kOH",                 ("SAPHIR.LP_LIF.kOH", "OHREACTIVITY")),
    ("O3, NO, NO2",               "O3, NO, NO2",         ("NOXO3",)),
    ("HCHO (Picarro)",            "HCHO (Picarro)",      ("HCHO",)),
    ("HONO",                      "HONO",                ("HONO",)),
    ("NH3",                       "NH3",                 ("NH3",)),
    ("TOC",                       "TOC",                 ("TOC",)),
    ("PTR-ToF-MS",                "PTR-ToF-MS",          ("PTRMS",)),
    ("H3O+ CHARON",               "H3O+ CHARON",         ("H3OCHARON", "NH4CHARON")),
    ("Br- WALL-E Orbitrap",       "Br- WALL-E Orbitrap", ("WALLE",)),
    ("Uronium Orbitrap",          "Uronium Orbitrap",    ("URONIUM",)),        # token TBD
    ("NO3- CIMS",                 "NO3- CIMS",           ("NO3CIMS",)),        # token TBD
    ("SMPS (aerosol container)",  "SMPS",                ("SMPS-AMS",)),
    ("SMPS (VOC container)",      "SMPS + CPC",          ("SMPS-WALLE",)),
    ("CPC (VOC container)",       "SMPS + CPC",          ("CPC-WALLE", "CPC")),
    ("AMS",                       "AMS + TD",            ("AMS", "AMSTD")),
    ("AMS thermograms",           "AMS + TD",            ("AMS-THERMOGRAM",)),
    ("AMS mass spectra",          "AMS + TD",            ("AMS-SPECTRA",)),
    ("Aethalometer",              "Aethalometer",        ("AETHALOMETER",)),
    ("EESI",                      "EESI",                ("EESI",)),           # token TBD
    ("Filter sampling",           "Filter sampling",     ("FILTERS",)),
]

# Data availability reported by the teams, shown on the PUBLIC status page (write it
# for everyone, in English). file key -> [(first day, last day, status, note)];
# days None = a note for the whole campaign; "running" = a plain note. "not running" days are not expected
# (the cell shows "Not running" instead of "Missing"); "issue" days flag the cell.
# These override the experiments workbook for the days they cover. Times in UTC,
# checked against the submitted files.
_D = dt.date
INSTRUMENT_NOTES: dict[str, list[tuple[dt.date | None, dt.date | None, str, str]]] = {
    "PTRMS": [
        (_D(2026, 7, 4), _D(2026, 7, 4), "not running",
         "Flow and pressure problems (a clogged inlet capillary was back-flushed); data only "
         "until 06:00 UTC, before the background experiment. No data will be submitted."),
        (_D(2026, 7, 11), _D(2026, 7, 11), "running",
         "The instrument was running without problems; the data have not been processed yet "
         "and will be processed at FZJ."),
    ],
    "SMPS-AMS": [
        (None, None, "", "Raw data: not yet corrected for dilution "
         "or wall losses; corrected files will follow."),
        (None, None, "", "The instrument software lost contact with the SMPS at times, which "
         "stopped the measurement until it was restarted."),
        (_D(2026, 6, 30), _D(2026, 6, 30), "issue",
         "17:20 to 19:31 UTC (run end times): the thermodenuder valves switched out of sync "
         "with the AMS-SMPS, so each run mixes chamber and thermodenuder air. Do not use "
         "these data; they will be removed in the corrected files."),
        (_D(2026, 7, 2), _D(2026, 7, 2), "issue", "No data after 16:12 UTC."),
        (_D(2026, 7, 3), _D(2026, 7, 3), "issue", "No data before 07:04 UTC."),
        (_D(2026, 7, 11), _D(2026, 7, 11), "not running",
         "Stopped at 07:43 UTC, before the experiment started: no data during the experiment."),
        (_D(2026, 7, 12), _D(2026, 7, 12), "not running", "No data."),
        (_D(2026, 7, 13), _D(2026, 7, 13), "issue", "No data before 07:12 UTC."),
        (_D(2026, 7, 14), _D(2026, 7, 14), "not running",
         "Calibration day: stopped at 07:03 UTC, no data after that."),
        (_D(2026, 7, 15), _D(2026, 7, 15), "issue", "No data before 07:21 UTC."),
        (_D(2026, 7, 17), _D(2026, 7, 17), "issue", "No data from 07:28 to 08:42 UTC."),
    ],
    "CPC-WALLE": [
        (None, None, "", "Raw data (PATRAS): not corrected for dilution or wall losses. The "
         "files carry an instrument status column with the error reported at each time."),
        (_D(2026, 7, 2), _D(2026, 7, 2), "issue",
         "Underperforming: about 10% below the SMPS in the aerosol container."),
        (_D(2026, 7, 3), _D(2026, 7, 7), "issue",
         "Pulse-height error from about 08:00 on 3 July: the data are unreliable. Use with care."),
        (_D(2026, 7, 8), _D(2026, 7, 8), "issue",
         "Wick replaced; afterwards the error was gone and the counts are again comparable "
         "with the SMPS in the aerosol container."),
    ],
    "SMPS-WALLE": [
        (None, None, "", "Raw data: not yet corrected for dilution "
         "or wall losses; corrected files will follow."),
        (_D(2026, 7, 3), _D(2026, 7, 7), "issue",
         "Detector pulse-height error from about noon on 3 July: lower counting efficiency than "
         "the SMPS in the aerosol container. Use with care."),
        (_D(2026, 7, 8), _D(2026, 7, 8), "issue",
         "Wick replaced (gap 06:10 to 12:24 UTC); the error was gone afterwards."),
        (_D(2026, 7, 9), _D(2026, 7, 9), "issue",
         "Unusual data (bimodal size distributions); data end at 15:56 UTC."),
        (_D(2026, 7, 10), _D(2026, 7, 17), "not running",
         "Instrument failed: no data until the end of the campaign."),
    ],
    "AMS": [
        (None, None, "", "First-phase data: collection efficiency 1, not corrected for "
         "dilution or wall losses. Timestamps mark the end of each run."),
        (_D(2026, 6, 30), _D(2026, 7, 1), "running",
         "Until 1 July 09:14 UTC: 180 s runs, alternating between chamber air and the "
         "thermodenuder; 60 s runs afterwards."),
        (_D(2026, 6, 30), _D(2026, 6, 30), "issue",
         "17:20 to 19:31 UTC (run end times): the thermodenuder valves switched out of sync "
         "with the AMS, so runs mix chamber and thermodenuder air. Do not use these data."),
    ],
    "AMS-THERMOGRAM": [
        (None, None, "", "Mass fraction remaining after the thermodenuder, relative to the "
         "chamber (bypass) runs around it."),
        (_D(2026, 6, 30), _D(2026, 7, 1), "running",
         "Until 1 July 09:14 UTC each point is a single 3-minute thermodenuder run (no "
         "averaging, no standard deviation); afterwards the valves switched every 6 minutes."),
    ],
}
del _D

# Integration time changes reported by the teams; the metadata gives the value at the end
# of the campaign. file key -> [(valid until, UTC, integration time in s)]. A file that
# covers that time may also step at the earlier integration time.
INTEGRATION_TIME_HISTORY: dict[str, list[tuple[dt.datetime, float]]] = {
    "AMS": [(dt.datetime(2026, 7, 1, 9, 14), 180.0)],   # 60 s (+4 s saving) afterwards
}


def instrument_notes(key: str, day: dt.date | None = None) -> list[tuple[str, str]]:
    """(status, note) reported for one file key; with ``day``, only the notes for that day."""
    return [(st, note) for d0, d1, st, note in INSTRUMENT_NOTES.get(key, [])
            if (day is None and d0 is None) or (day and d0 and d0 <= day <= d1)]


# Email domain -> institution token, used only for a consistency hint.
EMAIL_DOMAINS = {
    "fz-juelich.de": "FZJ",
    "uow.edu.au": "UOW",
    "upatras.gr": "PATRAS",
    "ircelyon.univ-lyon1.fr": "IRCELYON",
    "univ-lyon1.fr": "IRCELYON",
}

# Instruments whose columns must be neutral chemical formulas (Rule 4, MS note).
MS_FORMULA_INSTRUMENTS = {"PTRMS", "WALLE", "H3OCHARON", "NH4CHARON"}

# Reagent ion per MS instrument: (label, mass added to the neutral to give the detected
# ion, in u). Used to check a mass written next to a formula, e.g. C6H6O1_m97.069.
_E = 0.000548580                                  # electron mass
REAGENT_IONS = {
    "PTRMS":     ("H+",  1.00782503 - _E),         # [M+H]+
    "H3OCHARON": ("H+",  1.00782503 - _E),
    "NH4CHARON": ("H+",  1.00782503 - _E),        # PDF typo token, also H3O+
    "WALLE":     ("Br-", 78.9183376 + _E),        # [M+79Br]-
}
MONOISOTOPIC = {"C": 12.0, "H": 1.00782503, "O": 15.99491462, "N": 14.00307401,
                "S": 31.97207117, "Cl": 34.96885268, "Br": 78.9183376, "F": 18.99840316,
                "I": 126.904473, "P": 30.97376163, "Si": 27.97692653}
MASS_TOLERANCE = 0.01                             # u; masses in names have 3 decimals
# "formula + separator + optional m/mz + mass", e.g. C6H6O1_m97.069, C10H16-mz137.132
FORMULA_MASS_RE = re.compile(r"^(?P<formula>(?:[A-Z][a-z]?\d*)+)[_\s-]+(?:[mM](?:/?[zZ])?)?\s*"
                             r"(?P<mass>\d+\.\d+)$")

# Warnings a team has explained and the coordinator accepted, per instrument token:
# (pattern in the warning message, note). They become INFO, so they no longer block
# automatic archiving, and the note appears in the report.
#
# PTRMS is deliberately NOT listed: after the recent processing updates its data should
# contain no exact zeros, so they are checked (WARN) again (decision 08 Oct 2026; day 1
# was archived earlier under a one-off acknowledgement).
_ZERO_COUNTS = (r"^Exact zeros",
                "Zero values are expected for this instrument (zero counts / no "
                "absorption) and are accepted.")
_ZERO_FRACTIONS = (r"^Exact zeros",
                   "Zero fractions are expected (empty m/z, or nothing left at high "
                   "thermodenuder temperature) and are accepted.")
ACKNOWLEDGED_WARNINGS: dict[str, list[tuple[str, str]]] = {
    "AMS":          [_ZERO_COUNTS],         # zeros come from the AMS software (29 Oct 2026)
    "AMS-THERMOGRAM": [_ZERO_FRACTIONS],
    "AMS-SPECTRA":    [_ZERO_FRACTIONS],
    "SMPS-AMS":     [_ZERO_COUNTS],
    "SMPS-WALLE":   [_ZERO_COUNTS],
    "CPC-WALLE":    [_ZERO_COUNTS],         # incl. InstrumentStatus code 0 = no error (22 Oct 2026)
    "AETHALOMETER": [_ZERO_COUNTS],
}

# Fallback campaign period if the experiments workbook cannot be read; normally
# the exact days come from campaign.py. A date outside is a warning only.
CAMPAIGN_WINDOW = (dt.date(2026, 6, 29), dt.date(2026, 7, 17))

# --- Rule 2 exception: native SAPHIR data-system files keep their own names ------
# e.g. 2026-07-07.SAPHIR.collected.all_param.nc, 2026-07-07.ASS_METEO.all_param.nc.
# Recognised by the product prefix (ASS_METEO.all_param.nc would otherwise look
# like a four-field team filename).
SAPHIR_PRODUCTS = ("SAPHIR", "ASS_METEO", "AMBIENT", "PLUS")
SAPHIR_NATIVE_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})\.(?P<product>(?:"
                              + "|".join(SAPHIR_PRODUCTS) + r")\..+)\.nc$")

# --- Rule 1: filenames -----------------------------------------------------------
DATA_EXTENSIONS = {".csv", ".h5", ".nc"}
DATA_NAME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\.(?P<instrument>[^.\s]+)\.(?P<institution>[^.\s]+)"
    r"\.(?P<ext>csv|h5|nc)$"
)
METADATA_NAME_RE = re.compile(
    r"^Metadata\.(?P<instrument>[^.\s]+)\.(?P<institution>[^.\s]+)\.txt$"
)

# --- Rule 3: time ----------------------------------------------------------------
TIME_COL = "time_utc"
TIME_END_COL = "time_utc_end"

# Period files: results averaged over periods, without a time axis of their own. One
# row per axis value per averaging period: period_start_utc, period_end_utc, the axis
# column, then the values. They are CSV and use the metadata file of the instrument
# itself (Metadata.AMS.PATRAS.txt for AMS-THERMOGRAM and AMS-SPECTRA).
#   suffix -> (axis column, what the values are)
PERIOD_FILES = {
    "-THERMOGRAM": ("TD_temperature [degC]", "fraction remaining"),   # MFR / VFR
    "-SPECTRA":    ("mz [1]", "normalised spectrum"),                 # fractions sum to 1
}
PERIOD_COLS = ("period_start_utc", "period_end_utc")
FRACTION_RANGE = (0.0, 1.5)        # MFR/VFR outside this is suspicious (WARN)
SPECTRUM_SUM = (0.9, 1.1)          # a normalised spectrum should add up to about 1 (WARN)
# Old tokens that are still accepted, with the one to use instead.
TOKEN_ALIASES = {"NH4CHARON": "H3OCHARON", "AMSTD": "AMS"}


def period_suffix(instrument: str | None) -> str | None:
    return next((s for s in PERIOD_FILES if instrument and instrument.endswith(s)), None)


def metadata_instrument(instrument: str) -> str:
    """Instrument token whose Metadata.<token>.<inst>.txt describes this file."""
    s = period_suffix(instrument)
    return instrument[:-len(s)] if s else instrument
TIME_TEXT_RE = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d+)?$"

# --- Rule 4 / Section 5: units ---------------------------------------------------
COLUMN_RE = re.compile(r"^(?P<quantity>\S(?:.*\S)?) \[(?P<unit>[^\[\]]*)\]$")
CANONICAL_UNITS = {
    "ppmv", "ppbv", "pptv", "ug m-3", "ng m-3", "cm-3", "s-1", "nm", "K", "degC",
    "hPa", "percent", "cps", "ncps", "lpm", "a.u.", "1",
}
# Common near-misses -> the canonical string we would suggest.
UNIT_SUGGESTIONS = {
    "ppb": "ppbv", "ppt": "pptv", "ppm": "ppmv",
    "ug/m3": "ug m-3", "ug m^-3": "ug m-3", "ugm-3": "ug m-3", "ug.m-3": "ug m-3",
    "ng/m3": "ng m-3", "cm^-3": "cm-3", "#/cm3": "cm-3", "1/cm3": "cm-3", "cm3": "cm-3",
    "1/s": "s-1", "s^-1": "s-1", "%": "percent", "C": "degC", "deg c": "degC",
    "mbar": "hPa", "l/min": "lpm", "slpm": "lpm", "lmin-1": "lpm", "counts": "cps",
    "au": "a.u.", "a.u": "a.u.", "none": "1", "unitless": "1", "-": "1",
}
# A quantity that is only an ion mass ("mz69.069", "m/z 69", "69.07"): rejected.
ION_MASS_RE = re.compile(r"^(m/?z)?[\s_]*\d+(\.\d+)?$", re.IGNORECASE)
FORMULA_RE = re.compile(r"^(?:[A-Z][a-z]?\d*)+$")
ELEMENT_RE = re.compile(r"([A-Z][a-z]?)(\d*)")

# --- Rule 5: missing data --------------------------------------------------------
MISSING_TOKENS = {"", "NaN", "nan", "NAN"}
FILL_VALUES = {-999.0, -9999.0, -99999.0, -999999.0, 9999.0, 99999.0, 999999.0,
               -999.9, -9999.9, 9.96921e36, -3.4028235e38, 3.4028235e38}
FILL_ABS_LIMIT = 1e30      # anything this large is a fill value, not data
SUSPECT_NEGATIVE = -999.0  # <= this but not an exact fill value: warn

# --- Section 4: metadata ---------------------------------------------------------
METADATA_REQUIRED = ["instrument", "institution", "pi_name", "pi_email",
                     "coauthors", "time_reference"]
METADATA_RECOMMENDED = ["data_format", "instrument_long", "measured_quantities",
                        "integration_time_s", "uncertainty", "detection_limit"]
METADATA_KNOWN = set(METADATA_REQUIRED + METADATA_RECOMMENDED + [
    "pi_phone", "workgroup", "institute", "inlet", "calibration", "comments",
])
METADATA_REPEATABLE = {"comments"}
TIME_REFERENCE_VALUES = {
    "start": "start", "begin": "start", "beginning": "start",
    "centre": "centre", "center": "centre", "middle": "centre", "mid": "centre",
    "end": "end", "stop": "end",  # e.g. AMS stores each run at its end
}
EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[A-Za-z]{2,}$")
COAUTHOR_RE = re.compile(r"^(?P<name>[^<>]+?)\s*<(?P<email>[^<>]+)>$")


def file_key(name: str) -> tuple[dt.date | None, str | None]:
    """(UTC day, key) of a data filename; key = SAPHIR product or instrument token.
    Metadata files and unparseable names give (None, None)."""
    m = SAPHIR_NATIVE_RE.match(name)
    if m:
        key = m["product"]
    else:
        m = DATA_NAME_RE.match(name)
        if not m:
            return None, None
        key = m["instrument"]
    try:
        return dt.date.fromisoformat(m["date"]), key
    except ValueError:
        return None, key
