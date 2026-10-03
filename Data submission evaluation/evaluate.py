"""Evaluate submissions by hand and write an HTML report plus a ready-to-forward
<team>_feedback.txt per team with issues (read-only on sciebo).

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
    ap.add_argument("--email", action="store_true",
                    help="also email the report to NOTIFY_TO (e.g. to re-send a pending file)")
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
    from feedback import team_messages
    messages = team_messages(reports)
    out, fb = write_report(reports, S.REPORT_DIR, messages=messages)
    print(f"\nReport: {out}")
    for p in fb:
        print(f"Team feedback: {p}")
    if args.email:
        from notify import send_mail
        from report import email_subject, render_html
        subject = email_subject(reports, messages)
        send_mail(S.NOTIFY_TO, subject, render_html(reports, messages=messages), [out, *fb])
        print(f"Emailed {S.NOTIFY_TO}: {subject}")
    if args.open:
        webbrowser.open(out.as_uri())
    return 1 if any(r.verdict == "REJECTED" for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
