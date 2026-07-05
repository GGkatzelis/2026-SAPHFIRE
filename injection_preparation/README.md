# Injection preparation

Plan and verify the SAPHFIRE 2026 chamber injections.

## Run
```
run_planner.bat
```
(auto-kills stale instances, then serves the GUI at http://localhost:8501)

## Files
| File | Purpose |
|---|---|
| `injection_gui.py` | Streamlit GUI (scenario → plan → export). **Entry point.** |
| `injection_model.py` | Engine: chamber gas law, forward/inverse VOC, MFC sizing, NOy/CO, ppbC + OH reactivity. |
| `scaffold_config.py` | Single source of truth: builds `fingerprint_tidy.csv` + `config/` from the v07 mixtures + rate constants. |
| `saphfire_plots.py` | Spectral composition pies (mixtures, gases, NOy, emissions, biogenic). |
| `generate_prep_table.py` | Colleague-facing solution-prep tables (Excel). |
| `prepare_bottle_form.py` | Fill-in form for bottle/syringe details. |
| `config/` | Editable configs (compounds, solutions, gas bottles, NOy, chamber). |
| `fingerprint_tidy.csv` | The tidy injection fingerprint (generated). |
| `figures/` | Rendered PNG pies. |

## Regenerate data / figures
```
python scaffold_config.py      # rebuild fingerprint_tidy.csv + config/
python saphfire_plots.py       # rebuild figures/
python generate_prep_table.py  # rebuild prep-table Excel
```

## Notes
- Densities/purities/CAS in `config/` are literature placeholders (`needs_review`) — verify before prep.
- k(OH) from R. Wegener's reactivity calc; validated against his per-mixture totals to ~1%.
- Gas-phase ppb carry a ~9% MFC reference-temperature caveat vs the SAPHIR LCU (0 °C vs ~25 °C), pending confirmation.
