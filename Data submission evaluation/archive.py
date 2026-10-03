"""Move accepted submissions out of Incoming into the archive, with versioning.

For every file in Incoming - Upload that is ACCEPTED (or that you approve by
hand), this
  1. writes the harmonised CSV into its experiment folder of Archive - Download
     (metadata files go to Archive - Download/Metadata),
  2. moves the untouched original to Archive - Download/_Originals/<same folder>,
     so Incoming only ever holds what is still pending,
  3. keeps the previous version when a file is uploaded again: the old original
     goes to _Originals/<folder>/_superseded/<name>.v<N>.<ext>, the harmonised
     copy is replaced and its header shows the new version,
  4. appends one row per version to Archive - Download/archive_log.csv
     (time, file, version, verdict, SHA-256), the version history,
  5. refreshes EXPERIMENT_INFO.txt in every experiment folder and the status
     page SAPHFIRE_2026_Submission_Status.html in the SAPHFIRE 2026 folder.

REJECTED and NEEDS CONFIRMATION files stay in Incoming (= pending).

    python archive.py --dry-run              # what would be archived
    python archive.py                        # archive everything ACCEPTED
    python archive.py --approve 2026-06-30.PTRMS.FZJ.csv   # archive a NEEDS CONFIRMATION file
    python archive.py --status-only          # just rebuild the status page
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import os
import shutil
import sys
from pathlib import Path

import campaign
import rules as R
import settings as S
from evaluate import submission_files
from harmonise import harmonised_text
from validator import FileReport, evaluate_file

LOG_FIELDS = ["archived_utc", "file", "folder", "version", "verdict", "how", "sha256",
              "size_bytes", "harmonised", "superseded_as"]


# --- locations -------------------------------------------------------------------
def folder_for(name: str) -> str:
    """Archive folder (relative) for a file, from the date in its name."""
    if name.startswith("Metadata."):
        return "Metadata"
    day, _ = R.file_key(name)
    exp = campaign.experiment_for(day) if day else None
    if exp:
        return exp.folder
    return f"Other days/{day}" if day else "Other days/undated"


def original_path(name: str) -> Path:
    return S.ARCHIVE_ORIGINALS / folder_for(name) / name


def harmonised_path(name: str) -> Path:
    if name.startswith("Metadata."):
        return S.ARCHIVE_METADATA / name
    return S.ARCHIVE / folder_for(name) / (Path(name).stem + ".csv")


# --- version log -----------------------------------------------------------------
def read_log() -> list[dict]:
    try:
        with open(S.ARCHIVE_LOG, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except FileNotFoundError:
        return []


def latest_versions() -> dict[str, dict]:
    """file name -> its most recent log row."""
    out = {}
    for row in read_log():
        out[row["file"]] = row
    return out


def _append_log(row: dict) -> None:
    new = not S.ARCHIVE_LOG.exists()
    with open(S.ARCHIVE_LOG, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"~{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


# --- archiving -------------------------------------------------------------------
def archive_file(src: Path, rep: FileReport, how: str = "auto", log=print) -> dict:
    name = src.name
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    digest = sha256(src)
    prev = latest_versions().get(name)
    orig, harm = original_path(name), harmonised_path(name)

    if prev and prev["sha256"] == digest and orig.exists():
        os.replace(src, orig)                 # identical re-upload: no new version
        log(f"  same as v{prev['version']}  {name} (identical re-upload, removed from Incoming)")
        return prev

    version = int(prev["version"]) + 1 if prev else 1
    exp = campaign.experiment_for(rep.date) if rep.date else None
    provenance = [
        f"source_file = {name}",
        f"source_sha256 = {digest}",
        f"version = {version} (archived {now} UTC; history in archive_log.csv)",
        f"verdict = {rep.verdict}" + (" (approved by hand)" if how == "approved" else ""),
    ]
    if exp:
        provenance.append(f"experiment = {exp.label if exp.is_experiment else 'non-experiment day'}"
                          f": {exp.title} ({', '.join(map(str, exp.days))})")
    tref = rep.summary.get("time_reference")
    if tref:
        provenance.append(f"time_reference = {tref} of the averaging interval")

    if name.startswith("Metadata."):
        text = src.read_bytes().decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
    else:
        text = harmonised_text(src, provenance)
    _write_atomic(harm, text)

    superseded = ""
    orig.parent.mkdir(parents=True, exist_ok=True)
    if orig.exists():
        old = orig.parent / "_superseded" / f"{orig.stem}.v{version - 1}{orig.suffix}"
        old.parent.mkdir(parents=True, exist_ok=True)
        os.replace(orig, old)
        superseded = str(old.relative_to(S.ARCHIVE))
    shutil.move(str(src), str(orig))

    row = {"archived_utc": now, "file": name, "folder": folder_for(name), "version": version,
           "verdict": rep.verdict, "how": how, "sha256": digest,
           "size_bytes": orig.stat().st_size, "harmonised": str(harm.relative_to(S.ARCHIVE)),
           "superseded_as": superseded}
    _append_log(row)
    log(f"  archived v{version}  {name} -> {row['harmonised']}")
    return row


def write_experiment_info() -> None:
    """EXPERIMENT_INFO.txt in every experiment / non-experiment folder."""
    status = campaign.instrument_status()
    for e in campaign.experiments():
        lines = [f"SAPHFIRE 2026 - {e.label if e.is_experiment else 'Non-experiment day'}: {e.title}",
                 f"Days (UTC): {', '.join(map(str, e.days))}", "",
                 "Logbook (times in UTC; from 'SAPHFIRE 2026 - Experiments and Instrument Status.xlsx')"]
        for d in e.days:
            lines += ["", f"[{d}]"] + [f"  {l}" for l in (e.logbook.get(d) or "(no entry)").splitlines()
                                       if l.strip()]
        lines += ["", "Instrument status during this experiment (from the same workbook; 'LT' = CEST)"]
        for inst, days in status.items():
            parts = []
            for d in e.days:
                st, note = days.get(d, ("unknown", ""))
                parts.append(f"{d:%m-%d} {st}" + (f" - {' '.join(note.split())}" if note else ""))
            lines.append(f"  {inst:22s} " + " | ".join(parts))
        path = S.ARCHIVE / e.folder / "EXPERIMENT_INFO.txt"
        text = "\n".join(lines) + "\n"
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            _write_atomic(path, text)


def evaluate_incoming() -> list[FileReport]:
    return [evaluate_file(p, S.INCOMING, [S.ARCHIVE_METADATA]) for p in submission_files(S.INCOMING)]


def run_archive(reports: list[FileReport] | None = None, approve=(), dry_run: bool = False,
                log=print) -> list[dict]:
    """Archive what qualifies among ``reports`` (default: evaluate all of Incoming)."""
    if reports is None:
        reports = evaluate_incoming()
    approve = set(approve)
    done = []
    # metadata first, so data files of the same batch find it in the archive
    for rep in sorted(reports, key=lambda r: not r.path.name.startswith("Metadata.")):
        name = rep.path.name
        if not rep.path.exists() or rep.path.parent != S.INCOMING:
            continue                                 # gone, or inside a subfolder
        if rep.verdict in S.AUTO_ARCHIVE_VERDICTS:
            how = "auto"
        elif name in approve and rep.verdict != "REJECTED":
            how = "approved"
        else:
            if name in approve:
                log(f"  cannot approve {name}: it is REJECTED (fix the FAIL items first)")
            continue
        if dry_run:
            log(f"  would archive  {name} -> {harmonised_path(name).relative_to(S.ARCHIVE)}")
            done.append({"file": name})
            continue
        done.append(archive_file(rep.path, rep, how, log))
    if not dry_run:
        write_experiment_info()
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--approve", nargs="+", default=[], metavar="FILE",
                    help="also archive these NEEDS CONFIRMATION files")
    ap.add_argument("--status-only", action="store_true", help="only rebuild the status page")
    args = ap.parse_args(argv)

    import overview
    if not args.status_only:
        reports = evaluate_incoming()
        done = run_archive(reports, args.approve, args.dry_run)
        pending = [r for r in reports if r.path.exists() and r.path.parent == S.INCOMING]
        print(f"\n{'would archive' if args.dry_run else 'archived'} {len(done)}, "
              f"pending in Incoming {len(pending) - (len(done) if args.dry_run else 0)}")
    if not args.dry_run:
        out = overview.write_status_page()
        print(f"Status page: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
