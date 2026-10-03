"""Team-facing fix list: what must be fixed and what needs confirming, as a neutral
report (no salutation or signature) that can be forwarded to anyone. One message per team (instrument + institution) per batch, so
thirty uploaded days with the same problem give one item, not thirty.

    msgs = team_messages(reports)       # list[TeamMessage]
    msgs[0].text                        # plain text (saved as *_feedback.txt)
    msgs[0].html                        # same content for the email body
"""
from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass, field

import settings as S
from validator import FileReport, parse_metadata

# (pattern in the check message, short title, what the team should do)
FIXES: list[tuple[str, str, str]] = [
    (r"named by ion mass", "Mass spectrometry columns named by ion mass",
     "Name every column by the chemical formula of the neutral molecule, e.g. C5H8 [ppbv] "
     "instead of mz69.069 [ppbv]. Peaks without a formula assignment cannot be used and "
     "should be removed from the file."),
    (r"named as ions", "Columns named as ions",
     "Use the neutral formula with the ionising agent subtracted (no trailing + or -)."),
    (r"no unit in square brackets", "Columns without a unit",
     "Write every column as 'quantity [unit]' with one space before the bracket, "
     "e.g. NO2 [ppbv]."),
    (r"empty unit", "Empty units", "Write 1 or a.u. for a quantity without a unit, never a blank."),
    (r"non-ASCII", "Non-ASCII characters",
     "Use plain ASCII, e.g. ug m-3 instead of µg m⁻³ and degC instead of °C."),
    (r"duplicated column", "Duplicated column names", "Every column name must be unique."),
    (r"Numeric fill values", "Numeric fill values",
     "Replace -999, -9999 and similar fill values by an empty field or NaN."),
    (r"not a number", "Text in data columns",
     "Missing values must be empty or NaN. Check for text flags, N/A or decimal commas."),
    (r"Infinite values", "Infinite values", "Replace inf by an empty field or NaN."),
    (r"rows are not on \d{4}-\d{2}-\d{2}", "Data outside the UTC day of the file",
     "Each file must hold exactly one UTC day, 00:00:00 to 23:59:59, matching the date in "
     "the filename. Please check the conversion from local time (CEST = UTC+2)."),
    (r"not 'YYYY-MM-DD hh:mm:ss", "Time format",
     "Write time_utc as text 'YYYY-MM-DD hh:mm:ss' (decimal seconds allowed), in UTC, "
     "without 'T' or a time-zone suffix."),
    (r"not valid dates", "Invalid dates", "Check the listed timestamps."),
    (r"duplicated timestamp", "Duplicated timestamps", "Every timestamp may appear only once."),
    (r"must be named exactly 'time_utc'", "First column",
     "The first column must be named time_utc."),
    (r"must come immediately after", "Position of time_utc_end",
     "Put time_utc_end directly after time_utc."),
    (r"time_utc_end before time_utc", "Interval end before start", "Check the listed rows."),
    (r"Header is not comma separated", "Separator",
     "Save the file comma-separated with a period as decimal separator (German Excel turns "
     "commas into semicolons; close such files without saving)."),
    (r"comma-separated fields", "Rows with a wrong number of fields",
     "Usually decimal commas or commas inside values; every row needs as many fields as "
     "the header."),
    (r"not UTF-8/ASCII", "File encoding", "Save the file as plain ASCII / UTF-8 text."),
    (r"File type .* is not accepted", "File type",
     "Submit CSV (or HDF5 as described in the instructions); Excel and other formats "
     "cannot be processed."),
    (r"Filename does not follow", "Filename",
     "Name the file YYYY-MM-DD.INSTRUMENT.INSTITUTION.csv with the tokens from the "
     "instructions, no spaces and no further periods."),
    (r"differs from the registered token", "Token spelling", "Use the registered spelling."),
    (r"not registered yet", "New token",
     "Please confirm the spelling; we will add it to the token table."),
    (r"No metadata file", "Metadata file missing",
     "Upload Metadata.INSTRUMENT.INSTITUTION.txt (Section 4 of the instructions); it is "
     "needed for the time reference and the author list."),
    (r"Required keys missing", "Metadata keys missing", "Add the listed keys."),
    (r"does not match the filename|does not include the filename token",
     "Metadata does not match the filename", "Use the same tokens as in the filename."),
    (r"must state 'start' or 'centre'", "time_reference",
     "Write time_reference = start or time_reference = centre."),
    (r"Full Name <email>", "Coauthor format",
     "List coauthors as 'Full Name <email>', separated by ';'."),
    (r"not initials", "Coauthors given with initials", "Please give full first names."),
    (r"pi_email .* not a valid", "PI email", "Give a working email address."),
    (r"PI email domain", "Institution to credit",
     "Please confirm which institution(s) should be credited. To credit both, write e.g. "
     "'institution = FZJ; UOW' in the metadata file."),
    (r"Exact zeros", "Exact zeros in the data",
     "Please confirm that these zeros are real measurements, not fill values and not "
     "negative values that were set to zero. If they are not real, replace them by an empty "
     "field or NaN (or keep the original negative values)."),
    (r"repeats in", "Repeated large negative values",
     "Please confirm these are real; fill values must be empty or NaN."),
    (r"closed-shell", "Formulas with an odd H/N count",
     "Please check that the ionising agent was subtracted (radicals are fine if intended)."),
    (r"give a formula and an m/z that disagree", "Formula and m/z in a column name disagree",
     "Please check the formula assignment of these peaks. If the m/z is right, rename the "
     "column to the formula that fits (suggested below where one is close); if the formula "
     "is right, correct or drop the m/z suffix."),
    (r"carry an m/z suffix that agrees", "Column names with an m/z suffix",
     "Use the plain neutral formula. If two peaks share a formula (isomers), keep the suffix "
     "and explain it in the metadata comments."),
    (r"not a plain chemical formula", "Column names that are not plain formulas",
     "Use the plain neutral formula (e.g. C6H6O) or explain the suffix in the metadata "
     "comments."),
    (r"contain no valid data", "Empty columns",
     "Remove columns without any data, or confirm they are intentionally empty."),
    (r"stored as integers", "Integer columns", "Store measurements as floating point."),
    (r"Sampling looks irregular", "Irregular sampling",
     "If every sample has its own interval, add a time_utc_end column."),
    (r"differs from integration_time_s", "Time step vs integration time",
     "Please confirm integration_time_s in the metadata."),
    (r"no integration_time_s", "Integration time missing",
     "Add integration_time_s to the metadata (or a time_utc_end column for irregular samples)."),
    (r"not in increasing order", "Unsorted timestamps", "Please sort the rows by time."),
    (r"outside the campaign|not a campaign day", "Date outside the campaign",
     "Please confirm this is the UTC day of the data."),
    (r"subfolder", "Upload location", "Upload directly into Incoming-Upload, without subfolders."),
    (r"NH4CHARON", "CHARON token", "Please use H3OCHARON."),
    (r"could not be read", "File could not be read", "Please check the file and upload it again."),
]


@dataclass
class Item:
    title: str
    rule: str
    found: str
    todo: str
    blocking: bool
    examples: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


@dataclass
class TeamMessage:
    team: str
    contact: str
    files: list[tuple[str, str]]
    items: list[Item]
    text: str = ""
    html: str = ""

    @property
    def subject(self) -> str:
        n_bad = sum(v == "REJECTED" for _, v in self.files)
        state = (f"{n_bad} of {len(self.files)} file(s) need changes" if n_bad
                 else "points to confirm")
        return f"SAPHFIRE 2026 data check: {self.team}: {state}"


def _classify(message: str) -> tuple[str, str]:
    for pat, title, todo in FIXES:
        if re.search(pat, message):
            return title, todo
    return "", ""


def _team_of(r: FileReport) -> str:
    if r.instrument and r.institution:
        return f"{r.instrument} ({r.institution})"
    return r.summary.get("native") or r.path.name


def _contact(reports: list[FileReport]) -> str:
    for r in reports:
        meta = r.summary.get("metadata")
        if meta is None and r.summary.get("metadata_file"):
            try:
                meta, _ = parse_metadata(r.summary["metadata_file"])
            except OSError:
                meta = None
        if meta and meta.get("pi_email"):
            return f"{meta.get('pi_name', '').strip()} <{meta['pi_email'].strip()}>".strip()
    return ""


def team_messages(reports: list[FileReport]) -> list[TeamMessage]:
    groups: dict[str, list[FileReport]] = {}
    for r in reports:
        groups.setdefault(_team_of(r), []).append(r)
    out = []
    for team, reps in groups.items():
        items: dict[tuple[str, bool], Item] = {}
        for r in reps:
            for c in r.checks:
                if c.status not in ("FAIL", "WARN"):
                    continue
                title, todo = _classify(c.message)
                title = title or c.rule
                key = (title, c.status == "FAIL")
                it = items.get(key)
                if it is None:
                    it = items[key] = Item(title, c.rule, c.message, todo, c.status == "FAIL")
                for e in c.examples:
                    if e not in it.examples:
                        it.examples.append(e)
                if r.path.name not in it.files:
                    it.files.append(r.path.name)
        if not items:
            continue
        msg = TeamMessage(team, _contact(reps), [(r.path.name, r.verdict) for r in reps],
                          sorted(items.values(), key=lambda i: not i.blocking))
        msg.text, msg.html = _render(msg)
        out.append(msg)
    return out


VERDICT_WORDS = {"REJECTED": "Not accepted yet: needs changes",
                 "NEEDS CONFIRMATION": "Acceptable once the points below are confirmed",
                 "ACCEPTED": "Accepted"}
VERDICT_COLOURS = {"REJECTED": ("#fbd9d5", "#8a1c12"), "NEEDS CONFIRMATION": ("#fff1c2", "#7a5200"),
                   "ACCEPTED": ("#d6f0dc", "#14532d")}
RESUBMIT = ("Upload the corrected file(s) under the same name to Incoming-Upload in the "
            "SAPHFIRE 2026 sciebo folder. They are checked automatically; accepted files move "
            "to Archive-Download and appear in SAPHFIRE_2026_Submission_Status.pdf.")
FONT = "font-family:Segoe UI,Calibri,Arial,sans-serif;"


def _footer() -> str:
    who = getattr(S, "FEEDBACK_SIGNATURE", "") or "the SAPHFIRE 2026 data team"
    mail = getattr(S, "NOTIFY_TO", "")
    return f"Questions: {who}" + (f" ({mail})" if mail else "")


def _render(m: TeamMessage) -> tuple[str, str]:
    """A neutral report (no salutation or signature) that can be forwarded to anyone."""
    today = dt.date.today().strftime("%d %b %Y")
    numbered, n = [], 0
    for blocking in (True, False):
        for it in (i for i in m.items if i.blocking == blocking):
            n += 1
            numbered.append((n, blocking, it))

    # --- plain text (the .txt attachment) ---
    lines = [f"SAPHFIRE 2026 data submission check: {m.team}",
             f"Checked {today} against SAPHFIRE_2026_Data_Submission_Format.pdf"]
    if m.contact:
        lines.append(f"Contact (from the metadata file): {m.contact}")
    lines += ["", "FILES"]
    w = max(len(f) for f, _ in m.files)
    lines += [f"  {f:<{w}}  {VERDICT_WORDS[v]}" for f, v in m.files]
    for blocking, head in ((True, "MUST BE FIXED before the data can be archived"),
                           (False, "PLEASE CONFIRM OR CORRECT")):
        sel = [x for x in numbered if x[1] == blocking]
        if not sel:
            continue
        lines += ["", head]
        for k, _, it in sel:
            lines += ["", f"{k}. {it.title}  [{it.rule.split(' ·')[0]}]",
                      f"   Found: {it.found}"]
            if it.todo:
                lines.append(f"   What to do: {it.todo}")
            if it.examples:
                lines.append(f"   Affected ({len(it.examples)}): " + ", ".join(it.examples))
            if len(m.files) > 1:
                lines.append(f"   In: {', '.join(it.files)}")
    lines += ["", "HOW TO RESUBMIT", RESUBMIT, "", _footer()]
    text = "\n".join(lines)

    # --- HTML (the email body; inline styles for Outlook) ---
    e = html.escape
    rows = "".join(
        f'<tr><td style="padding:3px 10px 3px 0;font-family:Consolas,monospace;font-size:12px">'
        f'{e(f)}</td><td style="padding:3px 0"><span style="background:{VERDICT_COLOURS[v][0]};'
        f'color:{VERDICT_COLOURS[v][1]};padding:1px 8px;border-radius:3px;font-size:12px">'
        f'{e(VERDICT_WORDS[v])}</span></td></tr>' for f, v in m.files)
    parts = [f'<div style="{FONT}color:#1f2328;max-width:900px">',
             f'<h2 style="{FONT}font-size:18px;margin:0 0 2px">SAPHFIRE 2026 data submission '
             f'check: {e(m.team)}</h2>',
             f'<div style="font-size:12px;color:#5d6670;margin-bottom:10px">Checked {today} '
             'against SAPHFIRE_2026_Data_Submission_Format.pdf'
             + (f' &middot; contact: {e(m.contact)}' if m.contact else "") + "</div>",
             f'<table style="border-collapse:collapse;margin-bottom:6px">{rows}</table>']
    for blocking, head, colour in ((True, "Must be fixed before the data can be archived",
                                    "#8a1c12"),
                                   (False, "Please confirm or correct", "#7a5200")):
        sel = [x for x in numbered if x[1] == blocking]
        if not sel:
            continue
        parts.append(f'<h3 style="{FONT}font-size:15px;color:{colour};margin:16px 0 4px">'
                     f'{head}</h3>')
        for k, _, it in sel:
            parts.append(
                f'<div style="border-left:3px solid {colour};padding:2px 0 2px 10px;'
                f'margin:8px 0 10px"><div style="font-weight:600;font-size:14px">{k}. '
                f'{e(it.title)} <span style="font-weight:400;color:#5d6670;font-size:12px">'
                f'({e(it.rule.split(" ·")[0])})</span></div>'
                f'<div style="font-size:13px;margin-top:3px"><b>Found:</b> {e(it.found)}</div>'
                + (f'<div style="font-size:13px;margin-top:3px"><b>What to do:</b> '
                   f'{e(it.todo)}</div>' if it.todo else "")
                + (f'<div style="font-size:12px;margin-top:3px"><b>Affected '
                   f'({len(it.examples)}):</b> <span style="font-family:Consolas,monospace;'
                   f'font-size:11.5px;color:#3a434c">{e(", ".join(it.examples))}</span></div>'
                   if it.examples else "")
                + (f'<div style="font-size:12px;color:#5d6670;margin-top:3px">In: '
                   f'{e(", ".join(it.files))}</div>' if len(m.files) > 1 else "")
                + "</div>")
    parts += [f'<h3 style="{FONT}font-size:15px;margin:16px 0 4px">How to resubmit</h3>',
              f'<div style="font-size:13px">{e(RESUBMIT)}</div>',
              f'<div style="font-size:12px;color:#5d6670;margin-top:10px">{e(_footer())}</div>',
              "</div>"]
    return text, "".join(parts)
