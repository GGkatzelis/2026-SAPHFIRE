# Campaign quicklooks

Post-campaign data quicklooks for SAPHFIRE 2026, organized per instrument.

## Tools

### [`charon_fusion/`](charon_fusion/) — CHARON-FUSION ✅
Load a CHARON-FUSION **IDA export** (time × m/z) and reproduce the classic
quicklooks: mass-spec timeline, carbon–oxygen distribution, VBS (volatility),
mass defect, and a chemical-space animation. Formulas are auto-assigned from
exact m/z (`[M+H]⁺`) since the export drops the Tofware assignment.

Run: `charon_fusion\run_quicklooks.bat` — see [charon_fusion/README.md](charon_fusion/README.md).

## Design
Each instrument is a self-contained subfolder with a Streamlit GUI mirroring
`injection_preparation/`. Shared conventions:
- **Chemistry** (Li 2016 C\*, Kroll OSc, CHO(N) families) lifted from
  `MCM_SAPHIR_Tool` so plots match that tool.
- **Data access** patterns from `Quick looks functions/FUSION_viewer`.
- **Animation** via off-screen imageio frame compositing (no GUI animation).
