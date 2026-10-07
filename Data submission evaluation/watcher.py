"""Watch Incoming - Upload and email an evaluation report for every new upload.

Read-only on sciebo: files are checked, never moved or changed. Reports and the
watcher's memory of what it has already seen stay in this folder (git-ignored).

    python watcher.py                # run forever (what Task Scheduler starts);
                                     # also pulls new/updated SAPHIR files from Z: hourly
    python watcher.py --once         # evaluate whatever is new right now, then exit
    python watcher.py --no-email     # same, but only write the report
    python watcher.py --baseline     # mark everything present as seen, no email
    python watcher.py --test-email   # send a test message to check Outlook works

Files uploaded together (same scan) arrive as ONE email, so a team uploading
thirty days does not produce thirty messages. A file that is replaced by a
new version (size or modification time changes) is evaluated again.
ACCEPTED files are archived straight away (archive.py), REJECTED files are deleted
from Incoming after the report email has gone out (so the team can upload the fix
under the same name), and the status page in the SAPHFIRE 2026 folder is
refreshed. With --no-email nothing is archived or deleted.
"""
from __future__ import annotations

import argparse
import json
import logging
import msvcrt
import sys
import time
from pathlib import Path

import settings as S
from evaluate import submission_files
from report import email_subject, render_html, write_report
from validator import evaluate_file

STATE_FILE = S.STATE_DIR / "seen.json"
LOCK_FILE = S.STATE_DIR / "watcher.lock"
log = logging.getLogger("watcher")


def _key(p: Path) -> str:
    return p.relative_to(S.INCOMING).as_posix()


def _sig(p: Path) -> list:
    st = p.stat()
    return [st.st_size, int(st.st_mtime)]


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    S.STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(STATE_FILE)


def new_files(state: dict) -> list[Path]:
    """Files whose (size, mtime) differ from what was last evaluated."""
    if not S.INCOMING.exists():
        log.warning("Incoming folder not found (is sciebo syncing?): %s", S.INCOMING)
        return []
    files = submission_files(S.INCOMING)
    present = {_key(p) for p in files}
    for gone in [k for k in state if k not in present]:
        del state[gone]          # deleted upstream: a later re-upload counts as new
    return [p for p in files if state.get(_key(p), {}).get("sig") != _sig(p)]


def process(files: list[Path], state: dict, email: bool) -> None:
    """Evaluate, archive what is ACCEPTED (real runs only), email, refresh the status page."""
    from feedback import team_messages
    reports = [evaluate_file(p, S.INCOMING, [S.ARCHIVE_METADATA]) for p in files]
    messages = team_messages(reports)          # ready-to-forward fix list per team
    out, fb_files = write_report(reports, S.REPORT_DIR, messages=messages)
    subject = email_subject(reports, messages)
    for r in reports:
        log.info("%-19s FAIL %2d WARN %2d  %s", r.verdict, r.count("FAIL"), r.count("WARN"),
                 r.path.name)
    if not email:
        log.info("Report: %s (no email, files not marked as seen)", out)
        return
    if S.AUTO_ARCHIVE:
        from archive import run_archive
        archived = run_archive(reports, log=log.info)
        if archived:
            subject += f" ({len(archived)} archived)"
    from notify import send_mail
    send_mail(S.NOTIFY_TO, subject, render_html(reports, messages=messages), [out, *fb_files])
    log.info("Emailed %s: %s", S.NOTIFY_TO, subject)
    if S.DELETE_REJECTED:               # only after the report has gone out
        from archive import delete_rejected
        delete_rejected(reports, log=log.info)
    import overview
    overview.write_status_page({r.path.name: r.verdict for r in reports})
    for p, r in zip(files, reports):
        if not p.exists():          # archived (moved) or rejected (deleted)
            state.pop(_key(p), None)
            continue
        state[_key(p)] = {"sig": _sig(p), "verdict": r.verdict,
                          "evaluated": time.strftime("%Y-%m-%d %H:%M:%S"), "report": out.name}
    save_state(state)
    log.info("Report: %s", out)


def import_from_z() -> None:
    """Copy new/updated SAPHIR files from Z: into Incoming; the scan then reports them."""
    from import_saphir import run_import
    try:
        res = run_import(log=lambda m: log.info("Z: %s", m.strip()))
        for p, ds in res.new_products.items():
            log.warning("New product on Z: not imported: %s (%s)", p, ", ".join(ds))
    except Exception:
        log.exception("SAPHIR import from Z: failed (is Z: mounted?)")


def run_forever(email: bool, z_import: bool = True) -> None:
    state = load_state()
    pending: dict[str, tuple[list, float]] = {}       # key -> (sig, first seen with that sig)
    done: dict[str, list] = {}       # reported this session (matters with --no-email)
    last_import = 0.0
    log.info("Watching %s every %d s (stable after %d s)%s", S.INCOMING, S.POLL_SECONDS,
             S.STABLE_SECONDS, f"; Z: import every {S.SAPHIR_IMPORT_EVERY_MIN} min"
             if z_import else "")
    while True:
        if z_import and time.time() - last_import >= S.SAPHIR_IMPORT_EVERY_MIN * 60:
            import_from_z()
            last_import = time.time()
        try:
            now = time.time()
            ready = []
            for p in new_files(state):
                k, sig = _key(p), _sig(p)
                if done.get(k) == sig:
                    continue
                if k in pending and pending[k][0] == sig:
                    if now - pending[k][1] >= S.STABLE_SECONDS:
                        ready.append(p)
                else:
                    pending[k] = (sig, now)
            if ready:
                process(ready, state, email)
                for p in ready:
                    pending.pop(_key(p), None)
                    if p.exists():              # archived files have left Incoming
                        done[_key(p)] = _sig(p)
        except Exception:
            # keep watching; files stay un-'seen' and are retried on the next scan
            log.exception("Scan failed")
        time.sleep(S.POLL_SECONDS)


def _single_instance():
    S.STATE_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(LOCK_FILE, "w")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        sys.exit("Another watcher is already running.")
    return fh


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true", help="evaluate new files now and exit")
    ap.add_argument("--no-email", action="store_true", help="write reports, send no email")
    ap.add_argument("--baseline", action="store_true", help="mark current files as seen")
    ap.add_argument("--test-email", action="store_true", help="send a test email and exit")
    ap.add_argument("--no-import", action="store_true",
                    help="do not pull SAPHIR files from Z: (default: hourly)")
    args = ap.parse_args(argv)

    S.STATE_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(S.STATE_DIR / "watcher.log", encoding="utf-8")]
    if sys.stderr is not None:          # pythonw.exe (Task Scheduler) has no console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=handlers)

    if args.test_email:
        from notify import send_mail
        send_mail(S.NOTIFY_TO, "[SAPHFIRE upload] test message",
                  "<p>The SAPHFIRE upload watcher can send email from this PC.</p>")
        log.info("Test email sent to %s", S.NOTIFY_TO)
        return 0

    lock = _single_instance()  # noqa: F841  (held open for the process lifetime)
    state = load_state()
    if args.baseline:
        for p in new_files(state):
            state[_key(p)] = {"sig": _sig(p), "verdict": "baseline",
                              "evaluated": time.strftime("%Y-%m-%d %H:%M:%S")}
        save_state(state)
        log.info("Baseline: %d file(s) marked as seen", len(state))
        return 0
    if args.once:
        files = new_files(state)
        if files:
            process(files, state, email=not args.no_email)
        else:
            save_state(state)
            log.info("Nothing new in Incoming")
        return 0
    run_forever(email=not args.no_email, z_import=not args.no_import)
    return 0


if __name__ == "__main__":
    sys.exit(main())
