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

### [`campaign_quicklooks/`](campaign_quicklooks/) — instrument quicklooks 🚧
Post-campaign data quicklooks, per instrument. First target: **CHARON-FUSION**
(mass-spec HDF5 per experiment) — mass-spec timelines, carbon–oxygen /
Van Krevelen distributions, and VBS (volatility) plots. In development.

### [`publications/`](publications/) — reference papers
Open-access ACP papers behind the parameterizations (Gkatzelis 2024, Roberts 2020).

## Setup
All tools use the shared venv at
`C:\Users\g.gkatzelis\Desktop\My Folders\My Coding\Python\.venv`.
Install deps with `…\.venv\Scripts\python.exe -m pip install -r requirements.txt`.
