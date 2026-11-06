# Data analysis

Analysis of the SAPHFIRE 2026 data in the sciebo archive. First analysis: do the
instruments see what was injected?

## PTR-ToF-MS vs injections

Compares the expected mixing ratio of every logged injection with the increase the
PTR-ToF-MS measured before the roof opened.

```
run_ptr_vs_injections.bat          # desktop window (PyQt), no browser, no console
python ptr_vs_injections.py        # summary in the terminal, CSVs in output/
python injections.py               # the injection log with expected ppbv, CSV in output/
```

| File | What it does |
|---|---|
| `logged_injections.csv` | Every injection in the logbook: time (UTC), what, how much. **Not in git** (see below). Edit here to correct an amount or a time. |
| `injections.py` | Turns each logged injection into expected ppbv per compound, using the planner in `../injection_preparation` (solution compositions, chamber volume, bottles, MFC corrections). |
| `ptr_vs_injections.py` | The comparison: expected, PTR background, PTR average, % difference and the pattern at injection, per experiment and PTR formula. The averaging windows are in `WINDOWS`. |
| `ptr_vs_injections_figures.py` | The matplotlib figures (no Qt), each drawn into a given Axes. |
| `ptr_vs_injections_gui.py` | The desktop window (PyQt6). Look, loading box and mouse interaction come from `../saphfire_gui`, the JUICE format. |

### Method

- **Expected** is the increase at injection: 270 m3 chamber at 298.15 K and 1013.25 hPa,
  no dilution, wall loss or chemistry. MFC flows use 0 degC as the standard temperature.
- **Formulas, not compounds.** PTR cannot separate isomers, so injected compounds with the
  same formula are summed and compared with the one PTR signal (for example the three C8
  aromatics at C8H10).
- **Averaging window:** the 10 min before the roof opened (length adjustable in the GUI).
  Night experiments use the 10 min before the first oxidant; injections with no later roof
  opening use the minutes up to 20 min after the injection. An injection inside the window
  shortens it to the minutes after that injection.
- **Background:** PTR mean over the 10 min before the first injection of the formula. If
  the PTR was not running then, the background is taken as 0 and the row says so.
- **% difference** = (PTR average - background - expected) / expected x 100.
- **Pattern:** compares the mean 3 to 13 min after an injection with the 10 min before.
  "Increase at injection" needs a step above 5 x noise and above 20 % of the expected
  amount; "Slow increase" misses the step but reaches it by the averaging window.
- **Not corrected:** PTR fragmentation and interferences between formulas (for example
  1,8-cineole also appears at C10H16), and reactive loss before the window.
- Not measured by the PTR: ethene, CO, NO, NO2, HONO, O3 and the seed.

### GUI

An offline desktop window in the format of the JUICE results viewer: filters on the
left (experiments, how the compound was injected, averaging length, only clear
increases) apply to every tab; each tab has one row of options above its plot.

- **% difference by formula:** one row per formula, every experiment as a point, as
  violin, box or points only; one experiment can be highlighted.
- **Observed vs expected:** mean per formula with error bars (standard deviation or
  min-max between experiments), or every experiment as its own point; log or linear axes.
- **Time series:** the PTR signal of one formula around its injections, with the
  background and averaging windows and the expected level.
- **Table:** the numbers behind the plots; click a header to sort, Export CSV to save.

Mouse on every plot, as in JUICE: wheel zooms horizontally, Ctrl+wheel or right-drag
up/down zooms vertically, left-drag pans, double-click resets, right-click opens the
zoom / log scale menu. Hovering a point shows its values; clicking a point opens its
time series. "Save image" writes PNG, SVG or PDF.

### Data and privacy

The repository is public. `logged_injections.csv` (from the logbook) and `output/` are
git-ignored; on a new PC copy the CSV into this folder. The PTR files are read from the
sciebo archive, found through `../Data submission evaluation/settings.py` (which needs
`settings_local.py`) or the environment variable `SAPHFIRE_ARCHIVE`.

The 2-decanone value is calculated here from its density (23.4 ppbv); the injections
workbook kept the draft value of 23.5 ppbv.
