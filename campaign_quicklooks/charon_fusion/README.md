# CHARON-FUSION quicklooks

Turn a CHARON-FUSION **IDA export** (a time × m/z matrix) into the classic
SAPHFIRE quicklook plots. Reads the Tofware **HDF5** (`…IDA_Export….h5`), the
**Excel** export (`…-IDA_Export_*.xlsx`), or CSV/TSV.

## Run
```
run_quicklooks.bat
```
(auto-kills stale instances, then serves the GUI at http://localhost:8501)

In the sidebar, either **Browse folder** (pick an experiment from a directory of
exports — defaults to this tool's `Data/` folder, override with the `CHARON_DIR`
env var) or **File / upload** (drop a file or paste a path). If a file is an
incomplete/corrupt export, the app says so and you just pick another.

## What it does
The export labels every ion only by exact **m/z** (the sum-formula assignment
lives in the Tofware `.ida` project and is dropped on export). So the tool
**auto-assigns a neutral CₓHᵧOᵤNᵥ formula to each ion from its exact mass**,
assuming protonated detection `[M+H]⁺` (H₃O⁺ reagent). On the FLAMING-Day file
this explains **~98 % of the total signal**. Assignments can be overridden by a
Tofware peak-table export (see below).

From the formulas it derives O:C, H:C, carbon number, mean carbon oxidation
state (OSc, Kroll 2011) and volatility log₁₀C\* (Li et al. 2016), then draws:

| Tab | Plot |
|---|---|
| 📈 Timeline & masks | **Interactive** (Plotly) ion time series — zoom/pan/hover, click the legend to toggle traces, search all ions by m/z or formula. Paste the **SAPHIR action log** to overlay the events as vertical markers. Define the background & chemistry windows (or snap them to the first VOC injection), the SNR threshold, and what period + mass set the composition plots use. This one tab drives the rest. |
| 🔬 Signal & clusters | How many masses are **real signal** (SNR) above the background, and HCA of co-evolving masses |
| 🧱 Carbon–oxygen | Signal vs carbon number, stacked by oxygen number and by CHO(N) family |
| 🫧 VBS | Volatility basis set: log₁₀C\* vs OSc, sized by signal, coloured by family |
| 🎯 Mass defect | Neutral mass defect vs mass, coloured by family |
| 🎬 Animation | Time-evolving 2×2 chemical space exported as MP4/GIF |
| 🔎 Peak table | Assigned ions + properties (CSV download) |

The **period is chosen once** in *Timeline & masks* (Chemistry window / All data /
Background), with an optional "real-signal masses only" filter, and the
composition, VBS and mass-defect panels all follow that choice — so they focus on
the chemistry that matters. There is no global time slider (it forced a full
recompute on every change).

### Signal & clusters (detection + patterns)
Define a **background** window and a **chemistry** window on the Σ-signal
timeline. For each mass, SNR = (mean_chem − mean_bg) / σ_bg; masses with
SNR ≥ threshold (default 3) are flagged **real signal**. This answers *"how many
of the 1500+ masses actually carry signal?"* — on the FLAMING file, ~24 % of
masses, but they hold ~93 % of the chemistry signal. The detected masses are
then **hierarchically clustered** (Ward on 1−Pearson-r over the whole record)
into co-evolving groups — separating primary emission from secondary/aged
patterns — shown as a clustered correlation heatmap and per-cluster time
profiles (CSV download of the mass→cluster table).

## Files
| File | Purpose |
|---|---|
| `quicklooks_gui.py` | Streamlit GUI. **Entry point.** |
| `charon_io.py` | Read the IDA export (time × m/z), parquet-cached; load override tables. |
| `chemistry.py` | [M+H]⁺ formula assignment; Li 2016 C\*, Kroll OSc, CHO(N) family (lifted from MCM_SAPHIR_Tool). |
| `ql_plots.py` | The four matplotlib panels. |
| `interactive.py` | Plotly zoom/pan timeline with event + period overlays. |
| `actions.py` | Parse the pasted SAPHIR action log into timestamped events. |
| `stats.py` | Background-vs-chemistry SNR detection, correlation, Ward HCA. |
| `stats_plots.py` | Period-mask timeline, SNR histogram, enhancement scatter, correlation heatmap, cluster profiles. |
| `video.py` | Off-screen imageio 2×2 animation (timeline rendered once, cursor overlaid; fixed panel scales). |
| `.cache/` | Parquet cache of parsed exports (safe to delete). |

## Architecture (format-independent)
The analysis is decoupled from the file format. Everything downstream operates on
a single in-memory model:

```
CharonData(times, mz, values, source, meta)   # T×N signal — the ONLY thing analysis sees
```

```
 file ──► charon_io.load_timeseries() ──► CharonData ──► chemistry / ql_plots / stats / video
          (dispatch by extension)
```

`load_timeseries(path)` dispatches on extension to a reader (`.h5/.hdf5`, Excel,
CSV/TSV); each returns a `CharonData`. Time is auto-detected by name
(`time_string`/`time_number`/`datetime`) with the epoch inferred by magnitude
(Excel-serial / Unix s / Unix ms / Igor / **MATLAB datenum**), and ion labels
from `m/z 101.023 []`, `mz101.023`, or a bare number. The HDF5 reader finds the
2-D matrix + label/time vectors by shape (names/orientation need not match) and
raises a clear error if the export is incomplete/corrupt. No experiment specifics
are hard-coded — the Excel sheet is auto-detected and the source is chosen in the
sidebar (browse a folder or upload/paste; `CHARON_DIR`/`CHARON_EXPORT` prefill).

**To add a new export format:** write one reader that returns a `CharonData`
(reuse `_tidy` if it's a wide table) and add a branch in `load_timeseries`.
Chemistry, plots, stats and video need no changes.

## Notes
- **First load of a 50 MB Excel export takes a few minutes** (openpyxl parses the
  XML); it is then cached to `.cache/*.parquet` and reloads in seconds. CSV/TSV
  load directly.
- Auto-assignment over-fits at low mass — use the sidebar **mass-error filter**
  (`|Δm| ≤ …`) to drop poor assignments, or supply an **override peak table**
  (CSV/XLSX with `m/z` + `formula` columns) for publication-quality composition.
- Signal units in the export are arbitrary (`[]`); relabel via the sidebar.
- C\* and OSc parameterizations match the MCM_SAPHIR_Tool "Chemical Space" tab.
