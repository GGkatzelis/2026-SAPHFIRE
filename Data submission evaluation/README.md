# Data submission evaluation

Checks the files teams upload to the SAPHFIRE 2026 sciebo folder against
[`SAPHFIRE_2026_Data_Submission_Format.pdf`](SAPHFIRE_2026_Data_Submission_Format.pdf)
(the version shared with all teams) and emails a report for every upload.

Accepted files are archived automatically: a harmonised CSV goes into the
experiment folder in `Archive - Download`, the untouched original is moved to
`Archive - Download/_Originals/`, so **Incoming only holds what is pending**.
Nothing is ever deleted; reports and watcher state stay local in `reports/` and
`state/` (git-ignored).

```
SAPHFIRE 2026/
  SAPHFIRE_2026_Submission_Status.html      instruments x experiments, refreshed automatically
  SAPHFIRE_2026_Submission_Status.pdf       same page as PDF (opens in the sciebo web viewer)
  Incoming - Upload/                        pending only (rejected / needs confirmation / not yet checked)
  Archive - Download/
    2026-06-30_E01_Smoldering-Fire_Night-to-Day/   harmonised CSVs of all its days + EXPERIMENT_INFO.txt
    ...                                            (E01..E12)
    Non-experiment days/2026-06-29_Integration/ ...
    Metadata/                                      current Metadata.*.txt per instrument
    _Originals/<same folders>/                     untouched originals
    _Originals/<folder>/_superseded/<name>.vN.ext  every earlier version
    archive_log.csv                                one row per version: time, verdict, SHA-256
```

**Archive format** (one format for everything): CSV in the submission layout,
`time_utc` first, `quantity [unit]` columns, provenance header lines (#) with
source file, SHA-256, version, experiment and time reference. Values and
timestamps are never changed (start or centre exactly as delivered, stated in
the header); only unit labels are made ASCII (`cm!U-3!N` -> `cm-3`, `°C` ->
`degC`, blank -> `1`). SAPHIR `@STDEV` becomes `<name>_STDEV`; `@NO_OF_POINTS`
and `@INTERVAL_T` are dropped. HDF5 size distributions get one column per bin.

**Versions:** a re-uploaded file that passes becomes version N+1: the harmonised
CSV is replaced (header shows the version), the previous original moves to
`_superseded/`, and `archive_log.csv` gets a new row. An identical re-upload
creates no new version.

## Files

| File | What it does |
|---|---|
| `rules.py` | Every rule from the PDF: tokens, units, filename pattern, metadata keys. Edit here to add a token. |
| `settings.py` | Paths on this PC (sciebo Incoming/Archive, Z: SAPHIR data), email recipient, polling interval. |
| `campaign.py` | Reads the experiment calendar and per-day instrument status from `SAPHFIRE 2026 - Experiments and Instrument Status.xlsx` (repo root). `python campaign.py` prints the matrix. |
| `import_saphir.py` | For every campaign day on `Z:\IEK8-SAPHIR\data\YYYY\MM\DD`: copies `SAPHIR.collected`, `ASS_METEO`, `SAPHIR.LIF.ROx` and `SAPHIR.LP_LIF.kOH` unmodified into Incoming, merges the 40 photolysis-frequency files into one `YYYY-MM-DD.JVALUES.FZJ.csv`, re-copies/rebuilds whatever changed on Z:, and reports products it does not know yet. `--inventory` prints what exists per day. |
| `jvalues.py` | The J-value merge (chamber `_SAPHIR` and outside `_AMBIENT` columns, values unchanged, metadata file generated). |
| `validator.py` | Checks one file (CSV, HDF5, SAPHIR NetCDF, metadata) and returns PASS/INFO/WARN/FAIL per rule. |
| `report.py` | Turns results into one HTML page (email body + forwardable attachment). |
| `evaluate.py` | Manual run: evaluate Incoming (or given files) and write a report. |
| `watcher.py` | Watches Incoming, evaluates new uploads, emails the report via Outlook. |
| `archive.py` | Archives ACCEPTED files (and ones approved with `--approve`), keeps versions, writes EXPERIMENT_INFO.txt. |
| `harmonise.py` | Converts CSV / HDF5 / SAPHIR NetCDF into the archive CSV layout. |
| `overview.py` | Writes the status page into the SAPHFIRE 2026 folder. |
| `notify.py` | Sends the email through the local Outlook profile. |
| `tests/` | Synthetic good and broken files, one per rule. |

## Verdicts

- **ACCEPTED**: the tool can process the file as is.
- **NEEDS CONFIRMATION** (WARN items): processable, but something needs the
  team's confirmation, e.g. exact zeros, institution vs PI mismatch, odd-H formulas.
- **REJECTED** (any FAIL): the team must fix the file and upload it again.

Policy decisions beyond the PDF (2026-10-03):
- Mass spectrometry columns named by ion mass (`mz69.069 [ppbv]`) are rejected:
  quantified data without a formula assignment are of no use.
- Exact zeros are a warning to clarify with the team, not a rejection.
- Reports go to G. Gkatzelis only during the test-file phase, not to the teams.
- The token list is open: an unregistered instrument or institution token is a
  warning; tokens are added to `rules.py` as submissions arrive. The CHARON
  token is `H3OCHARON` (the PDF's `NH4CHARON` is a typo, still accepted).
- Native SAPHIR files keep their names. Blank units, `%`, `C` and zeros in them
  are accepted as is; `name@STDEV` / `@NO_OF_POINTS` companions are not checked.

Campaign facts the code relies on: the experiment logbook in the workbook is in
**UTC** (roof times match the SAPHIR `roof_all` signal to the minute); the
instrument status notes that say "LT" are local time (CEST = UTC+2).

## Use

```
evaluate_incoming.bat                       # check everything in Incoming now, open report
python evaluate.py path\to\file.csv         # check specific files
python import_saphir.py --dry-run           # SAPHIR files from Z: that would be copied
python import_saphir.py                     # copy new/re-processed SAPHIR files to Incoming
python campaign.py                          # experiments x instrument status matrix
python archive.py --dry-run                 # what would be archived
python archive.py                           # archive everything ACCEPTED, refresh status page
python archive.py --approve <file>          # archive a NEEDS CONFIRMATION file after checking it
python watcher.py --test-email              # check that Outlook can send
python watcher.py --once                    # email a report for anything new, then exit
python watcher.py --baseline                # mark current files as seen (no email)
run_watcher.bat                             # run continuously (what Task Scheduler starts)
```

The watcher pulls new or updated SAPHIR files from Z: every hour (`--no-import` to
skip), scans Incoming every 60 s and waits until a file has been unchanged for 90 s
before evaluating it. Files that arrive together go out as one email. A file
that is replaced (size or time changes) is evaluated again. Log:
`state/watcher.log`.

Start at log-in (one-time setup):
```
schtasks /create /tn "SAPHFIRE upload watcher" /sc onlogon /rl limited /tr "\"<repo>\Data submission evaluation\run_watcher.bat\""
```

Tests: `...\.venv\Scripts\python.exe -m pytest "Data submission evaluation\tests" -q`

## Setup on a new machine

The repository is public, so three things are **not** in git:

- `settings_local.py`: the sciebo folder path, the share link and the email
  recipient. Copy `settings_local.example.py` to `settings_local.py` and fill it in.
- `SAPHFIRE_2026_Data_Submission_Format.pdf`: the rules, which contain the upload
  link and access code. Copy it from the sciebo folder.
- `../SAPHFIRE 2026 - Experiments and Instrument Status.xlsx`: the experiment
  calendar and instrument status read by `campaign.py`. Place it in the repo root.
