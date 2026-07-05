# Campaign quicklooks 🚧

Post-campaign data quicklooks for SAPHFIRE 2026, organized per instrument.

## Planned: CHARON-FUSION (first target)
Load the per-experiment mass-spec HDF5 (`.h5`) files and reproduce the classic
quicklook plots:
- **Mass-spec timeline** — species/ion time series over the experiment
- **Carbon–oxygen distribution** — O:C vs C# / Van Krevelen (H:C vs O:C)
- **VBS** — volatility basis set (C\* distribution)

Built on the plotting patterns from existing projects:
- `Quick looks functions/FUSION_viewer` (CHARON-FUSION viewer + peak lists)
- `CIMplify_GitVersion_V1` (mass-spec plotting)
- `MCM_SAPHIR_Tool` (time-evolving / animated results)

Status: planning — see the proposal in the project discussion. Structure and a
Streamlit GUI mirroring `injection_preparation/` will be added here.
