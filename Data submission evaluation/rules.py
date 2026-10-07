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
    "AMSTD":        ("Aerosol mass spectrometer with thermodenuder", {"FZJ", "PATRAS"}),
    # The PDF says NH4CHARON, but the reagent ion is H3O+ (PDF typo, 2026-10-03).
    "H3OCHARON":    ("H3O+ CHARON inlet, aerosol composition",   {"FZJ", "PATRAS"}),
    "NH4CHARON":    ("H3O+ CHARON (token as printed in the PDF; prefer H3OCHARON)", {"FZJ", "PATRAS"}),
    "SMPS-AMS":     ("SMPS in the aerosol container",            {"FZJ", "PATRAS"}),
    "SMPS-WALLE":   ("SMPS in the VOC container",                {"FZJ", "PATRAS"}),
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
    ("CPC (VOC container)",       "SMPS + CPC",          ("CPC",)),            # token TBD
    ("AMS + TD",                  "AMS + TD",            ("AMSTD",)),
    ("Aethalometer",              "Aethalometer",        ("AETHALOMETER",)),
    ("EESI",                      "EESI",                ("EESI",)),           # token TBD
    ("Filter sampling",           "Filter sampling",     ("FILTERS",)),
]

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
ACKNOWLEDGED_WARNINGS: dict[str, list[tuple[str, str]]] = {
    "PTRMS": [
        (r"^Exact zeros",
         "Accepted for PTRMS: confirmed by the PTRMS PI (UOW) on 04 Oct 2026 as real "
         "values at or below the baseline LOD after background subtraction."),
    ],
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
