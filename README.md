# SAPHFIRE 2026 — campaign tools

A multi-tool codebase for the **SAPHFIRE 2026** wildfire chamber campaign (SAPHIR,
FZJ). Each subfolder is a self-contained tool; they share one Python venv.

## Tools

### [`injection_preparation/`](injection_preparation/) — injection planner ✅
A Streamlit GUI + engine that turns the VOC fingerprint into a full, verifiable
chamber-injection plan: per-mixture prep recipes and volumes, gas-phase MFC
sizing (with air-calibration correction), MCE-driven NOy/CO, propene/NO₂
surrogates, and per-compound ppb / ppbC / OH-reactivity — with Excel export.

Run it:
```
injection_preparation\run_planner.bat
```
(or `…\.venv\Scripts\streamlit.exe run injection_preparation\injection_gui.py`)

### [`campaign_quicklooks/`](campaign_quicklooks/) — instrument quicklooks
Post-campaign data quicklooks, per instrument. First tool: **CHARON-FUSION**
(`charon_fusion/`) — a Streamlit GUI that loads an IDA export (time × m/z),
auto-assigns `[M+H]⁺` formulas from exact mass, and draws mass-spec timelines,
carbon–oxygen distributions, VBS (volatility), mass-defect plots, and a
chemical-space animation.

Run it:
```
campaign_quicklooks\charon_fusion\run_quicklooks.bat
```

### [`Data submission evaluation/`](Data%20submission%20evaluation/) — submission checker
Checks every file teams upload to the sciebo `Incoming - Upload` folder against
the SAPHFIRE 2026 data submission rules (CSV / HDF5 / SAPHIR NetCDF + metadata)
and emails an HTML report per upload via Outlook. Read-only on sciebo for now.

Run it:
```
"Data submission evaluation\evaluate_incoming.bat"   (manual check)
"Data submission evaluation\run_watcher.bat"         (watch + email)
```

### [`publications/`](publications/) — reference papers
Open-access ACP papers behind the parameterizations (Gkatzelis 2024, Roberts 2020).

## Setup
All tools use the shared venv at
`C:\Users\g.gkatzelis\Desktop\My Folders\My Coding\Python\.venv`.
Install deps with `…\.venv\Scripts\python.exe -m pip install -r requirements.txt`.
