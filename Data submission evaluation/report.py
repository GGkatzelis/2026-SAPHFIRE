"""Render ``FileReport``s as one self-contained HTML page.

The same HTML serves as the email body and as the attachment you can forward
to a team, so styles are inline (Outlook ignores most <style> rules).
"""
from __future__ import annotations

import datetime as dt
import html
import re
from pathlib import Path

from validator import RULE_ORDER, STATUS_RANK, FileReport

COLORS = {"PASS": "#1e7b34", "INFO": "#4a5a6a", "WARN": "#b26a00", "FAIL": "#b3261e"}
VERDICT_COLORS = {"ACCEPTED": "#1e7b34", "NEEDS CONFIRMATION": "#b26a00", "REJECTED": "#b3261e"}
VERDICT_TEXT = {
    "ACCEPTED": "Can be processed by the tool as it is.",
    "NEEDS CONFIRMATION": "Can be processed, but the points below need confirmation from the team.",
    "REJECTED": "Cannot be processed. The team must fix the FAIL items and upload again.",
}
FONT = "font-family:Segoe UI,Calibri,Arial,sans-serif;"
TD = "padding:4px 8px;border-bottom:1px solid #e3e6ea;vertical-align:top;"


def _e(s) -> str:
    return html.escape(str(s))


def _badge(text: str, color: str) -> str:
    return (f'<span style="background:{color};color:#fff;padding:1px 7px;border-radius:3px;'
            f'font-size:11px;font-weight:600;white-space:nowrap">{_e(text)}</span>')


def subject_line(reports: list[FileReport]) -> str:
    if len(reports) == 1:
        r = reports[0]
        return f"[SAPHFIRE upload] {r.path.name}: {r.verdict}"
    counts = {}
    for r in reports:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    parts = [f"{n} {v.lower()}" for v, n in sorted(counts.items(), key=lambda kv: kv[0])]
    return f"[SAPHFIRE upload] {len(reports)} files: {', '.join(parts)}"


def _summary_line(r: FileReport) -> str:
    s = r.summary
    bits = []
    if "rows" in s:
        bits.append(f"{s['rows']} rows")
    if "variables" in s:
        bits.append(f"{s['variables']} variables")
    if "first" in s:
        bits.append(f"{s['first'][11:19]} to {s['last'][11:19]} UTC")
    if "median_step_s" in s:
        bits.append(f"step {s['median_step_s']:g} s")
    if "size_MB" in s:
        bits.append(f"{s['size_MB']} MB")
    return " · ".join(bits)


TABLE_EXAMPLES = 8          # the full lists are in the team fix list (feedback.py)


def _file_section(r: FileReport) -> str:
    v = r.verdict
    head = (f'<h2 style="{FONT}font-size:16px;margin:24px 0 4px">{_e(r.path.name)} '
            f'{_badge(v, VERDICT_COLORS[v])}</h2>'
            f'<div style="{FONT}font-size:12px;color:#555;margin-bottom:6px">'
            f'{_e(VERDICT_TEXT[v])} {_e(_summary_line(r))}</div>')

    checks = sorted(r.checks, key=lambda c: (RULE_ORDER.index(c.rule) if c.rule in RULE_ORDER
                                             else 99, -STATUS_RANK[c.status]))
    rows = []
    for c in checks:
        ex = ""
        if c.examples:
            shown = [_e(x) for x in c.examples[:TABLE_EXAMPLES]]
            if len(c.examples) > TABLE_EXAMPLES:
                shown.append(f"... and {len(c.examples) - TABLE_EXAMPLES} more")
            ex = ('<div style="color:#666;font-size:11px;font-family:Consolas,monospace;'
                  'margin-top:2px">' + "<br>".join(shown) + "</div>")
        rows.append(f'<tr><td style="{TD}white-space:nowrap;color:#555">{_e(c.rule)}</td>'
                    f'<td style="{TD}">{_badge(c.status, COLORS[c.status])}</td>'
                    f'<td style="{TD}">{_e(c.message)}{ex}</td></tr>')
    table = (f'<table style="{FONT}font-size:12px;border-collapse:collapse;width:100%">'
             + "".join(rows) + "</table>")

    meta = r.summary.get("metadata")
    meta_html = ""
    if meta:
        items = "".join(f'<tr><td style="{TD}color:#555">{_e(k)}</td><td style="{TD}">'
                        f'{_e("; ".join(v) if isinstance(v, list) else v)}</td></tr>'
                        for k, v in meta.items() if v)
        meta_html = (f'<div style="{FONT}font-size:12px;margin-top:8px;font-weight:600">'
                     f'Metadata as parsed</div><table style="{FONT}font-size:12px;'
                     f'border-collapse:collapse">{items}</table>')

    return head + table + meta_html


def render_html(reports: list[FileReport], title: str = "SAPHFIRE 2026 submission check",
                messages=()) -> str:
    """Email body / report page. With ``messages`` (feedback.TeamMessage) the team report(s)
    come first, written so the email can be forwarded as is; the full check table follows
    as an appendix ("Technical details")."""
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    overview = "".join(
        f'<tr><td style="{TD}font-family:Consolas,monospace">{_e(r.path.name)}</td>'
        f'<td style="{TD}">{_badge(r.verdict, VERDICT_COLORS[r.verdict])}</td>'
        f'<td style="{TD}text-align:right">{r.count("FAIL")}</td>'
        f'<td style="{TD}text-align:right">{r.count("WARN")}</td></tr>' for r in reports)
    th = f'style="{TD}text-align:left;color:#555;font-weight:600"'
    technical = (
        f'<table style="{FONT}font-size:12px;border-collapse:collapse">'
        f'<tr><th {th}>File</th><th {th}>Verdict</th><th {th}>FAIL</th><th {th}>WARN</th></tr>'
        f'{overview}</table>' + "".join(_file_section(r) for r in reports))
    if messages:
        sep = '<hr style="border:0;border-top:1px solid #d9dee3;margin:22px 0">'
        body = (sep.join(m.html for m in messages) + sep
                + f'<h2 style="{FONT}font-size:16px;margin:0 0 2px">Technical details: all '
                f'checks</h2><div style="{FONT}font-size:12px;color:#555;margin-bottom:8px">'
                f'Every rule checked for every file (generated {now}).</div>' + technical)
    else:
        body = (f'<h1 style="{FONT}font-size:20px;margin:0">{_e(title)}</h1>'
                f'<div style="{FONT}font-size:12px;color:#555;margin:2px 0 12px">Generated {now}'
                ' · checked against SAPHFIRE_2026_Data_Submission_Format.pdf</div>' + technical)
    return (f'<html><head><meta charset="utf-8"><title>{_e(title)}</title></head>'
            f'<body style="{FONT}color:#1f2328;background:#ffffff;max-width:1000px;margin:16px">'
            + body + "</body></html>")


def email_subject(reports: list[FileReport], messages=()) -> str:
    """One team with issues: the team report's subject; otherwise the batch summary."""
    if len(messages) == 1 and all(_team_key(r) == messages[0].team for r in reports):
        return messages[0].subject
    return subject_line(reports)


def _team_key(r: FileReport) -> str:
    from feedback import _team_of
    return _team_of(r)


def write_report(reports: list[FileReport], out_dir: Path, stem: str | None = None,
                 messages=()) -> tuple[Path, list[Path]]:
    """Write the HTML report and one <team>_feedback.txt per team message.
    Returns (report path, feedback paths)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = f"{dt.datetime.now():%Y%m%d-%H%M%S}"
    if stem is None:
        stem = (reports[0].path.stem if len(reports) == 1 else "batch")
    path = out_dir / f"{ts}_{stem}.html"
    path.write_text(render_html(reports, messages=messages), encoding="utf-8")
    fb_paths = []
    for m in messages:
        safe = re.sub(r"[^A-Za-z0-9.-]+", "_", m.team).strip("_")
        p = out_dir / f"{ts}_{safe}_feedback.txt"
        p.write_text(m.text, encoding="utf-8")
        fb_paths.append(p)
    return path, fb_paths
