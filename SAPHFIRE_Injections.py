"""SAPHFIRE 2026 — injection preparation toolkit.

Step 1: parse the realized VOC injection fingerprint (Table 1 of the white paper,
maintained in ``Data/SAPHFIRE Injections.xlsx``) from its stacked-block layout
into one tidy table.

The source sheet is organized as five vertically stacked blocks:
    Phenolic Mixture (Solution A), Furanoid Mixture (Solution B),
    Hydrocarbon Mix (Solution C), Oxygenate Mix (Solution D), Gasses Mix.
Each block has the columns: FIRELAB Name | Surrogate | Mass % | Mixture Mass %.
A separate summary in columns F/G gives each block's share of total VOC mass.

Run directly to parse the workbook and print/write the tidy fingerprint.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# --- paths -------------------------------------------------------------------
DATA_XLSX = Path(
    r"C:\Users\g.gkatzelis\Desktop\My Folders\My Campaigns\2026 SAPHFIRE"
    r"\Data\SAPHFIRE Injections.xlsx"
)
SHEET = "Tabelle1"

# Block header label (as it appears in column A) -> (solution id, mixture name).
# "Gasses Mix" has no solution letter: the three light gases are injected
# directly from gas-phase standards, not prepared as a liquid solution.
_BLOCK_MAP = {
    "Phenolic Mixture": ("A", "Phenolic"),
    "Furanoid Mixture": ("B", "Furanoid"),
    "Hydrocarbon Mix": ("C", "Hydrocarbon"),
    "Oxygenate Mix": ("D", "Oxygenate"),
    "Gasses Mix": (None, "Gases"),
}


@dataclass(frozen=True)
class FingerprintComponent:
    solution: str | None      # "A".."D" for liquid solutions, None for gases
    mixture: str              # Phenolic / Furanoid / Hydrocarbon / Oxygenate / Gases
    firelab_name: str         # original FIRELAB species or lumped group
    surrogate: str            # calibration standard used to represent it
    mass_pct: float           # % of full FIRELAB inventory mass
    mixture_mass_pct: float   # % within its own solution (per-block sums to 100)


def load_fingerprint(path: Path = DATA_XLSX, sheet: str = SHEET) -> pd.DataFrame:
    """Parse the stacked-block injection workbook into one tidy DataFrame.

    Returns columns: solution, mixture, firelab_name, surrogate, mass_pct,
    mixture_mass_pct. One row per injected component.
    """
    raw = pd.read_excel(path, sheet_name=sheet, header=None)

    rows: list[FingerprintComponent] = []
    current: tuple[str | None, str] | None = None

    for _, r in raw.iterrows():
        label = str(r[0]).strip() if pd.notna(r[0]) else ""

        # Start of a new block?
        if label in _BLOCK_MAP:
            current = _BLOCK_MAP[label]
            continue
        # Skip per-block header rows and blank separators.
        if current is None or label in ("", "FIRELAB Name", "nan"):
            continue

        surrogate = str(r[1]).strip() if pd.notna(r[1]) else ""
        mass_pct = pd.to_numeric(r[2], errors="coerce")
        mixture_mass_pct = pd.to_numeric(r[3], errors="coerce")
        if pd.isna(mass_pct):  # not a real component row
            continue

        solution, mixture = current
        rows.append(
            FingerprintComponent(
                solution=solution,
                mixture=mixture,
                firelab_name=label,
                surrogate=surrogate,
                mass_pct=float(mass_pct),
                mixture_mass_pct=(
                    float(mixture_mass_pct) if pd.notna(mixture_mass_pct) else float("nan")
                ),
            )
        )

    return pd.DataFrame(rows)


def mixture_summary(fp: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the tidy fingerprint to per-mixture mass shares."""
    g = (
        fp.groupby(["solution", "mixture"], dropna=False)
        .agg(n_components=("surrogate", "size"), mass_pct=("mass_pct", "sum"))
        .reset_index()
        .sort_values("mass_pct", ascending=False)
    )
    return g


if __name__ == "__main__":
    fp = load_fingerprint()
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 160)

    print(f"Loaded {len(fp)} injected components from:\n  {DATA_XLSX}\n")
    print("=== Per-mixture summary ===")
    summ = mixture_summary(fp)
    print(summ.to_string(index=False))
    print(
        f"\nTotal mass_pct over retained species: {fp['mass_pct'].sum():.1f}% "
        "(~84% of inventory; renormalized to 100% across the injected set)\n"
    )
    print("=== Tidy fingerprint ===")
    print(fp.to_string(index=False))

    out = Path(__file__).with_name("fingerprint_tidy.csv")
    fp.to_csv(out, index=False)
    print(f"\nWrote tidy fingerprint -> {out}")
