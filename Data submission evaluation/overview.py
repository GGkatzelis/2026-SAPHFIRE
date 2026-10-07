"""Submission status page: instruments x experiments, written to the shared
SAPHFIRE 2026 folder (settings.STATUS_HTML) for everyone in the campaign.

Each cell says whether data for that instrument and experiment are archived,
waiting in Incoming, missing although the instrument was running, or not
expected because it was not running (from the experiments workbook), and when
they were last updated.
"""
from __future__ import annotations

import datetime as dt
import html
import subprocess
from pathlib import Path

import campaign
import rules as R
import settings as S
from archive import latest_versions, read_rejected
from evaluate import submission_files
from validator import evaluate_file

_verdict_cache: dict[tuple, str] = {}

STATE_TEXT = {
    "done": "Archived", "partial": "Partly archived", "review": "In review",
    "rejected": "Needs fixing", "missing": "Missing", "notrun": "Not running", "none": "",
}


def _e(s) -> str:
    return html.escape(str(s))


def pending_verdicts(known: dict[str, str] | None = None) -> dict[str, tuple[str, float]]:
    """file name -> (verdict, upload time) for everything still in Incoming."""
    out = {}
    for p in submission_files(S.INCOMING):
        st = p.stat()
        key = (p.name, st.st_size, int(st.st_mtime))
        if known and p.name in known:
            _verdict_cache[key] = known[p.name]
        if key not in _verdict_cache:
            _verdict_cache[key] = evaluate_file(p, S.INCOMING, [S.ARCHIVE_METADATA]).verdict
        out[p.name] = (_verdict_cache[key], st.st_mtime)
    return out


def _collect(known_verdicts=None):
    archived = latest_versions()
    arch, pend = {}, {}
    for f, row in archived.items():
        day, key = R.file_key(f)
        if day:
            arch.setdefault((key, day), []).append(row)
    pending = pending_verdicts(known_verdicts)
    for f, (verdict, mtime) in pending.items():
        day, key = R.file_key(f)
        if day:
            pend.setdefault((key, day), []).append((f, verdict, mtime))
    # rejected files were deleted from Incoming; keep showing "Needs fixing" until a
    # corrected version is archived or uploaded
    for f, note in read_rejected().items():
        day, key = R.file_key(f)
        if day and (key, day) not in arch and (key, day) not in pend:
            t = dt.datetime.fromisoformat(note["time"]).replace(tzinfo=dt.timezone.utc)
            pend[(key, day)] = [(f, "REJECTED", t.timestamp())]
    known_keys = {k for _, _, keys in R.STATUS_ROWS for k in keys}
    extra = sorted({k for k, _ in list(arch) + list(pend)} - known_keys)
    rows = list(R.STATUS_ROWS) + [(f"{k} (new token)", None, (k,)) for k in extra]
    return rows, arch, pend, archived, pending


def _cell(row, exp, arch, pend, sheet_status):
    label, sheet, keys = row
    days = exp.days
    arch_rows = [r for d in days for k in keys for r in arch.get((k, d), [])]
    arch_days = {d for d in days for k in keys if (k, d) in arch}
    pend_items = [p for d in days for k in keys for p in pend.get((k, d), [])]

    notes = []
    if sheet and sheet in sheet_status:
        sts = [sheet_status[sheet].get(d, ("unknown", "")) for d in days]
        expected = exp.is_experiment and any(s not in ("not running", "no experiment") for s, _ in sts)
        notes = [f"{d:%d %b}: {s}" + (f" ({' '.join(n.split())})" if n else "")
                 for d, (s, n) in zip(days, sts)]
    else:                       # SAPHIR/meteo rows, or an instrument not in the workbook
        expected = exp.is_experiment

    if len(arch_days) == len(days):
        state = "done"
    elif arch_days:
        state = "partial"
    elif pend_items:
        state = "rejected" if any(v == "REJECTED" for _, v, _ in pend_items) else "review"
    elif expected:
        state = "missing"
    elif exp.is_experiment:
        state = "notrun"
    else:
        state = "none"

    last = max((r["archived_utc"] for r in arch_rows), default="")
    version = max((int(r["version"]) for r in arch_rows), default=0)
    text = STATE_TEXT[state]
    sub = ""
    if state in ("done", "partial"):
        sub = dt.datetime.fromisoformat(last).strftime("%d %b") if last else ""
        if state == "partial":
            text = f"{len(arch_days)}/{len(days)} days"
        if version > 1:
            sub += f" · v{version}"
    if pend_items and arch_days:
        sub += " · update in review"
    tip = [f"{label} - {exp.label if exp.is_experiment else exp.title}"]
    tip += [f"archived: {r['file']} v{r['version']} ({r['archived_utc']} UTC)" for r in arch_rows]
    tip += [f"submitted: {f} ({v.lower()})" for f, v, _ in pend_items]
    tip += notes
    return state, text, sub, "\n".join(tip), last


CSS = """
:root{--bg:#ffffff;--fg:#1f2328;--muted:#5d6670;--line:#e3e6ea;--head:#f4f6f8;
--done:#d6f0dc;--done-fg:#14532d;--partial:#ecf7d8;--partial-fg:#3f6212;--review:#fff1c2;--review-fg:#7a5200;
--rejected:#fbd9d5;--rejected-fg:#8a1c12;--missing:#f3f4f6;--missing-fg:#8a1c12;--notrun:#ffffff;--notrun-fg:#9aa3ad;
--accent:#1f4e79}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#15181c;--fg:#e6e8eb;--muted:#9aa3ad;
--line:#2b3137;--head:#1d2126;--done:#173d24;--done-fg:#b7ebc6;--partial:#2a3a17;--partial-fg:#d4ecb0;
--review:#3d3212;--review-fg:#f5d77a;--rejected:#4a1e1a;--rejected-fg:#f6b9b1;--missing:#1d2126;
--missing-fg:#f19a8f;--notrun:#15181c;--notrun-fg:#5d6670;--accent:#8ab4e0}}
:root[data-theme="dark"]{--bg:#15181c;--fg:#e6e8eb;--muted:#9aa3ad;--line:#2b3137;--head:#1d2126;
--done:#173d24;--done-fg:#b7ebc6;--partial:#2a3a17;--partial-fg:#d4ecb0;--review:#3d3212;--review-fg:#f5d77a;
--rejected:#4a1e1a;--rejected-fg:#f6b9b1;--missing:#1d2126;--missing-fg:#f19a8f;--notrun:#15181c;
--notrun-fg:#5d6670;--accent:#8ab4e0}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 "Segoe UI",system-ui,-apple-system,sans-serif}
main{max-width:1500px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px}
.sub{color:var(--muted);margin:0 0 16px}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 18px}
.card{border:1px solid var(--line);border-radius:6px;padding:8px 14px;min-width:150px}
.card b{display:block;font-size:20px}.card span{color:var(--muted);font-size:12px}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:6px}
table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid var(--line);padding:5px 7px;text-align:center;vertical-align:middle}
thead th{background:var(--head);font-size:12px;font-weight:600;position:sticky;top:0}
th.inst,td.inst{text-align:left;position:sticky;left:0;background:var(--bg);white-space:nowrap;z-index:1}
thead th.inst{background:var(--head);z-index:2}
th .d{display:block;color:var(--muted);font-weight:400;font-size:11px}
th.nonexp{color:var(--muted);font-weight:400}
td.c{font-size:12px;min-width:84px;line-height:1.2}
td.c small{display:block;font-size:10.5px;opacity:.85}
.done{background:var(--done);color:var(--done-fg)}.partial{background:var(--partial);color:var(--partial-fg)}
.review{background:var(--review);color:var(--review-fg)}.rejected{background:var(--rejected);color:var(--rejected-fg)}
.missing{background:var(--missing);color:var(--missing-fg)}.notrun{background:var(--notrun);color:var(--notrun-fg)}
.last{color:var(--muted);font-size:12px;white-space:nowrap}
.legend{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 0;font-size:12px}
.legend span{padding:2px 8px;border-radius:3px;border:1px solid var(--line)}
ul.files{margin:0;padding-left:18px}ul.files li{margin:2px 0}
code{font-family:Consolas,monospace;font-size:12.5px}
footer{margin-top:28px;color:var(--muted);font-size:12px}
a{color:var(--accent)}
@page{size:A3 landscape;margin:8mm}
@media print{*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
.scroll{overflow:visible;border:0}thead th,th.inst,td.inst{position:static}
main{max-width:none;padding:0}td.c{min-width:0}}
"""


def render(known_verdicts=None, theme: str | None = None) -> str:
    """``theme='light'`` pins the light colours (used for the PDF snapshot)."""
    rows, arch, pend, archived, pending = _collect(known_verdicts)
    exps = campaign.experiments()
    sheet = campaign.instrument_status()
    now = dt.datetime.now(dt.timezone.utc)

    head = '<th class="inst">Instrument</th>' + "".join(
        f'<th class="{"" if e.is_experiment else "nonexp"}" title="{_e(e.title)}">'
        f'{_e(e.label if e.is_experiment else e.short_name.replace("-", " "))}'
        f'<span class="d">{e.start:%d %b}{"+" + str(len(e.days) - 1) if len(e.days) > 1 else ""}</span></th>'
        for e in exps) + '<th>Last update</th>'

    body, n_cells, n_done, n_missing = [], 0, 0, 0
    for row in rows:
        cells, last_row = [], ""
        for e in exps:
            state, text, sub, tip, last = _cell(row, e, arch, pend, sheet)
            last_row = max(last_row, last)
            if e.is_experiment and state not in ("notrun", "none"):
                n_cells += 1
                n_done += state == "done"
                n_missing += state == "missing"
            cells.append(f'<td class="c {state}" title="{_e(tip)}">{_e(text)}'
                         + (f"<small>{_e(sub)}</small>" if sub else "") + "</td>")
        last_txt = (dt.datetime.fromisoformat(last_row).strftime("%d %b %Y %H:%M") + " UTC"
                    if last_row else "-")
        body.append(f'<tr><td class="inst">{_e(row[0])}</td>{"".join(cells)}'
                    f'<td class="last">{_e(last_txt)}</td></tr>')

    pend_list = "".join(
        f"<li><code>{_e(f)}</code>: {_e(STATE_TEXT['rejected'] if v == 'REJECTED' else STATE_TEXT['review'])}"
        f", uploaded {dt.datetime.fromtimestamp(m, dt.timezone.utc):%d %b %H:%M} UTC</li>"
        for f, (v, m) in sorted(pending.items())) or "<li>Nothing pending.</li>"
    recent = sorted(archived.values(), key=lambda r: r["archived_utc"], reverse=True)[:12]
    recent_list = "".join(
        f"<li><code>{_e(r['file'])}</code> v{_e(r['version'])}, {_e(r['archived_utc'][:16])} UTC</li>"
        for r in recent) or "<li>Nothing archived yet.</li>"
    legend = "".join(f'<span class="{k}">{_e(v)}</span>' for k, v in STATE_TEXT.items() if v)

    theme_attr = f' data-theme="{theme}"' if theme else ""
    return f"""<!doctype html>
<html lang="en"{theme_attr}><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SAPHFIRE 2026 Submission Status</title><style>{CSS}</style></head>
<body><main>
<h1>SAPHFIRE 2026 data submission status</h1>
<p class="sub">Updated automatically {now:%d %b %Y, %H:%M} UTC. Instruments against experiments; hover a cell
for the files, versions and the instrument notes from the campaign log.</p>
<div class="cards">
<div class="card"><b>{len(archived)}</b><span>files archived</span></div>
<div class="card"><b>{len(pending)}</b><span>files pending in Incoming</span></div>
<div class="card"><b>{n_done} / {n_cells}</b><span>instrument-experiments complete</span></div>
<div class="card"><b>{n_missing}</b><span>expected but missing</span></div>
</div>
<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>
<div class="legend">{legend}</div>
<p class="sub" style="margin-top:8px">"Missing" means the campaign log lists the instrument as running
but no file has been archived yet. "Not running" comes from the same log. Greyed columns are days
without an experiment; data from them are welcome but not required.</p>
<h2>Pending in Incoming-Upload</h2><ul class="files">{pend_list}</ul>
<h2>Recently archived</h2><ul class="files">{recent_list}</ul>
<footer>Campaign folder: <a href="{_e(S.SCIEBO_SHARE_URL)}">{_e(S.SCIEBO_SHARE_URL)}</a>
(access code from the submission instructions). This page is also available there as
<code>{_e(S.STATUS_PDF.name)}</code>, which opens directly in the browser.<br>Harmonised copies are in <code>Archive-Download/&lt;date&gt;_&lt;experiment&gt;/</code>, the
untouched originals in <code>Archive-Download/_Originals/</code>, and every version in
<code>Archive-Download/archive_log.csv</code>. Submission rules:
<code>SAPHFIRE_2026_Data_Submission_Format.pdf</code>.</footer>
</main></body></html>"""


def _write_in_place(path: Path, data: bytes) -> None:
    """Overwrite the existing file instead of replacing it, so sciebo keeps the same
    file (and any share link made for it) and just stores a new version."""
    with open(path, "r+b" if path.exists() else "wb") as fh:
        fh.write(data)
        fh.truncate()


def _pdf_snapshot(html_text: str) -> bytes | None:
    """Print the page to PDF with headless Edge; None if Edge is not available."""
    if not S.EDGE.exists():
        return None
    S.STATE_DIR.mkdir(parents=True, exist_ok=True)
    src, pdf = S.STATE_DIR / "status_print.html", S.STATE_DIR / "status_print.pdf"
    src.write_text(html_text, encoding="utf-8")
    pdf.unlink(missing_ok=True)
    subprocess.run([str(S.EDGE), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", src.as_uri()],
                   capture_output=True, timeout=120, check=False)
    return pdf.read_bytes() if pdf.exists() and pdf.stat().st_size else None


def write_status_page(known_verdicts=None) -> Path:
    _write_in_place(S.STATUS_HTML, render(known_verdicts).encode("utf-8"))
    try:
        pdf = _pdf_snapshot(render(known_verdicts, theme="light"))
        if pdf:
            _write_in_place(S.STATUS_PDF, pdf)
    except (OSError, subprocess.SubprocessError):
        pass                      # the HTML page is the primary output; PDF is a convenience
    return S.STATUS_HTML
