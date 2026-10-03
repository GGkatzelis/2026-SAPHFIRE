"""Local paths and watcher/notification settings (machine specific, not rules).

The rules themselves live in ``rules.py``; this file only says *where* things
are on this PC and *who* gets the upload emails.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent

# Private values (sciebo folder, share link, email) live in settings_local.py,
# which is git-ignored because this repository is public. Copy
# settings_local.example.py to settings_local.py and fill it in.
try:
    from settings_local import NOTIFY_TO, SCIEBO_ROOT, SCIEBO_SHARE_URL
except ImportError:                                  # fresh clone: harmless placeholders
    SCIEBO_ROOT = HERE / "_sciebo_not_configured" / "SAPHFIRE 2026"
    SCIEBO_SHARE_URL = ""
    NOTIFY_TO = ""
SCIEBO_ROOT = Path(SCIEBO_ROOT)
INCOMING = SCIEBO_ROOT / "Incoming - Upload"
ARCHIVE = SCIEBO_ROOT / "Archive - Download"
ARCHIVE_METADATA = ARCHIVE / "Metadata"            # current metadata file per instrument
ARCHIVE_ORIGINALS = ARCHIVE / "_Originals"         # untouched originals, moved out of Incoming
ARCHIVE_LOG = ARCHIVE / "archive_log.csv"          # one row per archived file version
STATUS_HTML = SCIEBO_ROOT / "SAPHFIRE_2026_Submission_Status.html"
# PDF snapshot of the same page: sciebo's web viewer shows PDFs in the browser
# (HTML is only downloaded), so this is the version that works from a share link.
STATUS_PDF = SCIEBO_ROOT / "SAPHFIRE_2026_Submission_Status.pdf"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

# Which verdicts are archived automatically. NEEDS CONFIRMATION files stay in
# Incoming (pending) until approved with:  python archive.py --approve <file>
AUTO_ARCHIVE = True
AUTO_ARCHIVE_VERDICTS = ("ACCEPTED",)

# SAPHIR data system on the Z: drive: <SAPHIR_Z>\YYYY\MM\DD\YYYY-MM-DD.<product>.nc
SAPHIR_Z = Path(r"Z:\IEK8-SAPHIR\data")
# Copied into Incoming unmodified, with native names, whenever new or updated on Z:.
SAPHIR_IMPORT_PRODUCTS = (
    "SAPHIR.collected.all_param",   # chamber state: flows, dilution, roof, T, p, RH
    "ASS_METEO.all_param",          # meteorology
    "SAPHIR.LIF.ROx",               # LIF: OH, HO2, RO2, ROx
    "SAPHIR.LP_LIF.kOH",            # OH reactivity
)
# Photolysis frequencies: one file per j and location on Z: (SAPHIR.SR.jNO2, AMBIENT.SR.jO1D,
# ...). They are merged into ONE submission-format CSV per day instead of copied.
JVALUE_PREFIXES = ("SAPHIR.SR.j", "AMBIENT.SR.j")
JVALUES_TOKEN = ("JVALUES", "FZJ")
# Products on Z: deliberately not imported (chamber engineering, PLUS reactor, raw sps).
# Anything neither imported nor listed here is reported as "new on Z:".
SAPHIR_IGNORED_PRODUCTS = ("SAPHIR.air.all_param", "SAPHIR.usa.all_param",
                           "SAPHIR.sps.all_param.10sec", "SAPHIR.sps.all_param.60sec",
                           "PLUS.sps.all_param.10sec")
SAPHIR_IMPORT_EVERY_MIN = 60    # the watcher re-checks Z: this often

# Local outputs (git-ignored). Nothing here is ever written to sciebo.
REPORT_DIR = HERE / "reports"
STATE_DIR = HERE / "state"

# Signature under the team fix lists (feedback.py); can be overridden in settings_local.py
try:
    from settings_local import FEEDBACK_SIGNATURE
except ImportError:
    FEEDBACK_SIGNATURE = "The SAPHFIRE 2026 data team"

# Upload watcher (the email recipient NOTIFY_TO is set in settings_local.py)
POLL_SECONDS = 60          # how often Incoming is scanned
STABLE_SECONDS = 90        # a file must be unchanged this long (sync finished)

# Sciebo / OS temporary and sync-bookkeeping files that are never submissions.
IGNORE_PREFIXES = (".", "~", "._")
IGNORE_SUFFIXES = (".part", ".tmp", ".crdownload", ".db", ".lnk", ".ini")
