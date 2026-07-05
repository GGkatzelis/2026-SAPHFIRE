"""Generate a clean, shareable solution-preparation table for SAPHFIRE.

Writes SAPHFIRE_solution_prep.xlsx (one sheet per solution + gases + read-me)
and prints Markdown tables to paste into an email. Amounts are back-calculated
from the injection fingerprint for the configured vial volume (10 mL).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from injection_model import SOLUTION_NAMES, load_planner

OUT = Path(__file__).with_name("SAPHFIRE_solution_prep.xlsx")
VIAL_ML = 10.0


def build(planner):
    cas = dict(zip(planner.compounds["compound"], planner.compounds["CAS"]))
    comm = dict(zip(planner.compounds["compound"], planner.compounds["comment"].fillna("")))
    tables = {}
    for s in "ABCD":
        rc = planner.solution_recipe(s, VIAL_ML)
        c = rc["components"].copy()
        out = pd.DataFrame({
            "Component": c["compound"],
            "CAS": c["compound"].map(cas),
            "State": c["state"],
            "Mass fraction (%)": (c["mass_fraction"] * 100).round(2),
            f"Weigh-out for {VIAL_ML:.0f} mL (mg)": c["weighout_mass_mg"].round(0).astype("Int64"),
            "Volume (µL)": c["volume_uL"].round(0).astype("Int64"),
            "Note": c["compound"].map(comm),
        })
        tables[s] = (rc, out)
    return tables


def gas_table(planner):
    g = planner.voc[planner.voc["role"] == "gas"].copy()
    cas = dict(zip(planner.compounds["compound"], planner.compounds["CAS"]))
    return pd.DataFrame({
        "Gas": g["compound"],
        "CAS": g["compound"].map(cas),
        "Mass % of total VOC": g["overall_mass_pct"].round(2),
        "Injection": "from gas cylinder (not prepared as liquid)",
    })


def to_excel(planner, tables, gases):
    notes = dict(zip(planner.sol_density["solution"], planner.sol_density["prep_note"]))
    with pd.ExcelWriter(OUT, engine="openpyxl") as xls:
        readme = pd.DataFrame({"SAPHFIRE 2026 — solution preparation": [
            f"Back-calculated for a {VIAL_ML:.0f} mL vial of each solution.",
            "Solutions A–D are prepared separately (not co-soluble).",
            "Weigh by mass; 'Neat volume' is a convenience for liquids only.",
            "Solids are weighed by mass (no volume given).",
            "Masses assume ~100% pure reagent — scale up by 1/purity for your stock.",
            "Densities/CAS are provisional literature values — verify before prep.",
            "Formaldehyde is excluded (injection method TBD).",
            "1,3-butadiene + the light gases are injected from cylinders, not prepared.",
        ]})
        readme.to_excel(xls, sheet_name="Read me", index=False)
        for s in "ABCD":
            rc, out = tables[s]
            sheet = f"{s} {SOLUTION_NAMES[s]}"[:31]
            out.to_excel(xls, sheet_name=sheet, startrow=2, index=False)
            ws = xls.sheets[sheet]
            ws["A1"] = (f"Solution {s} — {SOLUTION_NAMES[s]} mixture | {VIAL_ML:.0f} mL | "
                        f"ρ={rc['density_g_per_mL']:.3f} g/mL | total {rc['total_mass_g']:.2f} g")
            note = notes.get(s, "")
            if isinstance(note, str) and note:
                ws["A2"] = f"Note: {note}"
            for col, width in zip("ABCDEF", (30, 12, 10, 16, 18, 16)):
                ws.column_dimensions[col].width = width
        gases.to_excel(xls, sheet_name="Gases", index=False)
    return OUT


def to_markdown(tables, gases):
    blocks = []
    for s in "ABCD":
        rc, out = tables[s]
        blocks.append(
            f"### Solution {s} — {SOLUTION_NAMES[s]} ({VIAL_ML:.0f} mL, "
            f"ρ={rc['density_g_per_mL']:.3f} g/mL, total {rc['total_mass_g']:.2f} g)\n\n"
            + out.to_markdown(index=False))
    blocks.append("### Gases (injected from cylinders)\n\n" + gases.to_markdown(index=False))
    return "\n\n".join(blocks)


if __name__ == "__main__":
    p = load_planner()
    tables = build(p)
    gases = gas_table(p)
    path = to_excel(p, tables, gases)
    print(to_markdown(tables, gases))
    print(f"\nWrote {path}")
