"""Evaluate submissions by hand and write an HTML report (read-only on sciebo).

    python evaluate.py                       # every file in Incoming - Upload
    python evaluate.py path\\to\\file.csv ...  # specific files
    python evaluate.py --open                # also open the report in the browser
"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

import settings as S
from report import write_report
from validator import evaluate_file


def submission_files(folder: Path) -> list[Path]:
    """All candidate files below ``folder`` (subfolders included, so they get flagged)."""
    out = []
    for p in sorted(folder.rglob("*")):
        if not p.is_file():
            continue
        if p.name.startswith(S.IGNORE_PREFIXES) or p.name.lower().endswith(S.IGNORE_SUFFIXES):
            continue
        out.append(p)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path, help="files to check (default: all of Incoming)")
    ap.add_argument("--open", action="store_true", help="open the HTML report when done")
    args = ap.parse_args(argv)

    files = args.files or submission_files(S.INCOMING)
    if not files:
        print(f"Nothing to evaluate in {S.INCOMING}")
        return 0
    reports = []
    for f in files:
        r = evaluate_file(f, S.INCOMING, [S.ARCHIVE_METADATA])
        reports.append(r)
        print(f"{r.verdict:<19} FAIL {r.count('FAIL'):>2}  WARN {r.count('WARN'):>2}  {f.name}")
    out = write_report(reports, S.REPORT_DIR)
    print(f"\nReport: {out}")
    if args.open:
        webbrowser.open(out.as_uri())
    return 1 if any(r.verdict == "REJECTED" for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
