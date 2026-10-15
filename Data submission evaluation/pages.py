"""Publish the public status page to GitHub Pages (settings.PAGES_URL).

The page goes to the ``gh-pages`` branch of the (public) repository through a
separate clone in ``state/pages``, so the working copy of the code is never
touched. Only when the page text changed is a commit pushed. A failed push is
logged and retried with the next refresh; it never stops the watcher.

Before every push the page is checked for the private values in
settings_local.py (sciebo folder, share link, email), which must never be public.

    python pages.py          # publish the current page now
"""
from __future__ import annotations

import logging
import subprocess

import settings as S

log = logging.getLogger("watcher")
CLONE = S.STATE_DIR / "pages"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)     # pythonw: no console flashes


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(CLONE), *args], capture_output=True, text=True,
                          timeout=120, creationflags=NO_WINDOW)


def _private_values() -> list[str]:
    vals = [S.SCIEBO_SHARE_URL, S.NOTIFY_TO, str(S.SCIEBO_ROOT), "sciebo.de/s/"]
    return [v for v in vals if v and len(v) > 5]


def _ensure_clone() -> None:
    if (CLONE / ".git").exists():
        return
    CLONE.mkdir(parents=True, exist_ok=True)
    _git("init", "-q")
    _git("remote", "add", "origin", S.PAGES_REMOTE)
    if _git("fetch", "-q", "--depth", "1", "origin", S.PAGES_BRANCH).returncode == 0:
        _git("checkout", "-q", "-B", S.PAGES_BRANCH, "FETCH_HEAD")
    else:                                        # first publish: new branch with no history
        _git("checkout", "-q", "--orphan", S.PAGES_BRANCH)
        (CLONE / ".nojekyll").write_text("")     # serve index.html as is


def publish(html_text: str) -> bool:
    """Commit and push ``html_text`` as index.html; True when the page is online."""
    leaks = [v for v in _private_values() if v in html_text]
    if leaks:
        log.error("Pages: NOT published, the page contains private values (%d)", len(leaks))
        return False
    try:
        _ensure_clone()
        (CLONE / "index.html").write_text(html_text, encoding="utf-8", newline="\n")
        _git("add", "index.html", ".nojekyll")
        if _git("diff", "--cached", "--quiet").returncode != 0:
            r = _git("commit", "-q", "-m", "Status page update")
            if r.returncode != 0:
                log.warning("Pages: commit failed: %s", r.stderr.strip()[:300])
                return False
        r = _git("push", "-q", "origin", f"HEAD:{S.PAGES_BRANCH}")
        if r.returncode != 0:
            log.warning("Pages: push failed (retried with the next refresh): %s",
                        r.stderr.strip()[:300])
            return False
        log.info("Pages: status page published to %s", S.PAGES_URL)
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Pages: not published: %s", exc)
        return False


if __name__ == "__main__":
    import overview

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ok = publish(overview.render(public=True))
    print(("Published: " if ok else "Not published, see messages above. ") + S.PAGES_URL)
