"""Logged chamber injections of SAPHFIRE 2026 and the mixing ratios they should give.

The injections are read from ``logged_injections.csv`` (one row per logbook entry, all
times UTC; private and git-ignored, like the logbook itself). Each entry is converted
to the expected increase in chamber mixing ratio with the injection planner in
``../injection_preparation``:

    solution    uL of mix A-D        -> ppbv of every compound in the mix
    neat        uL of a neat liquid  -> ppbv
    mfc         seconds at a setpoint of an MFC -> ppbv, from the bottle mixing ratio
    continuous  MFC setpoint held    -> ppbv per hour
    o3, hono, seed                   -> listed, no calculated amount (output not logged)

Expected values are increases at injection: no dilution, wall loss or chemistry.

    python injections.py        # daily totals; writes output/injection_log.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
EVENTS_CSV = HERE / "logged_injections.csv"
OUTPUT_DIR = HERE / "output"

sys.path.insert(0, str(HERE.parent / "injection_preparation"))
from biogenic_soa import BIOGENIC          # noqa: E402  (MW and density of the neat biogenics)
from injection_model import load_planner   # noqa: E402

# Bottles used in the campaign (ppm) and MFC gas-correction factors (delivered = setpoint x factor).
BOTTLE_PPM = {"propene": 10_000.0, "ethene": 100_000.0, "co": 999_970.0, "no": 3835.0, "no2": 519.0,
              "isoprene_bottle": 11.8}
MFC_CORR = {"propene": 1.00, "ethene": 1.022, "co": 0.963, "no": 1.00, "no2": 1.00, "isoprene_bottle": 1.00}
GASES = {"propene": ("Propene", "C3H6"), "ethene": ("Ethene", "C2H4"), "co": ("CO", "CO"),
         "no": ("NO", "NO"), "no2": ("NO2", "NO2"), "isoprene_bottle": ("Isoprene", "C5H8")}

# Neat liquids: key -> (name as in the solution tables, formula, MW g/mol, density g/mL, purity)
_BIO_NAME = {"isoprene": "Isoprene", "cineole": "Eucalyptol (1,8-cineole)", "a_pinene": "a-pinene",
             "d_limonene": "d-Limonene", "b_pinene": "b-Pinene", "caryophyllene": "b-caryophyllene"}
NEAT = {k: (_BIO_NAME[k], v[1], v[2], v[3], 1.0) for k, v in BIOGENIC.items()}
NEAT.update({"2_nonanone": ("2-nonanone", "C9H18O", 142.242, 0.820, 0.98),
             "2_decanone": ("2-decanone", "C10H20O", 156.269, 0.825, 0.98)})

UNMEASURED = {"o3": ("Ozone generator", "O3", "O3"), "hono": ("HONO bubbler", "HONO", "HNO2"),
              "seed": ("Seed", "Ammonium sulfate", "(NH4)2SO4")}
COLUMNS = ["date", "time_utc", "end_utc", "experiment", "route", "compound", "formula", "amount", "unit",
           "expected_ppbv", "rate_ppbv_per_h", "note"]


def load_events(path: Path = EVENTS_CSV) -> pd.DataFrame:
    """The logbook injections, one row per entry."""
    if not path.exists():
        raise FileNotFoundError(f"{path.name} is missing. It holds the logged injections and is not in git; "
                                "copy it into this folder.")
    ev = pd.read_csv(path, dtype={"date": str, "time_utc": str, "end_utc": str, "note": str})
    return ev.fillna({"end_utc": "", "note": ""})


def injection_log(events: pd.DataFrame | None = None, planner=None) -> pd.DataFrame:
    """One row per compound per injection, with its expected ppbv."""
    p = planner or load_planner()
    ev = load_events() if events is None else events
    formula = dict(zip(p.compounds["compound"], p.compounds["formula"]))
    rows = []
    for e in ev.itertuples():
        base = {"date": e.date, "time_utc": e.time_utc, "end_utc": e.end_utc, "experiment": e.experiment,
                "rate_ppbv_per_h": np.nan, "note": e.note}
        if e.kind == "solution":
            comp = p.forward_voc({e.species: float(e.amount)})["components"].sort_values("ppb", ascending=False)
            for c in comp.itertuples():
                rows.append({**base, "route": f"Solution {e.species}", "compound": c.compound,
                             "formula": formula[c.compound], "amount": e.amount, "unit": "uL of solution",
                             "expected_ppbv": c.ppb})
        elif e.kind == "neat":
            name, f, mw, rho, purity = NEAT[e.species]
            ppb = p.chamber.ppb_from_mass(float(e.amount) * 1e-3 * rho * purity, mw)
            rows.append({**base, "route": "Neat liquid", "compound": name, "formula": f, "amount": e.amount,
                         "unit": "uL", "expected_ppbv": ppb})
        elif e.kind in ("mfc", "continuous"):
            name, f = GASES[e.species]
            sccm = e.mfc_lpm * 1000.0 * e.setpoint_pct / 100.0 * MFC_CORR[e.species]
            unit = f"at {e.setpoint_pct:g} % of {e.mfc_lpm:g} L/min MFC"
            if e.kind == "mfc":
                ppb = p.gas_ppb_from_dosing(BOTTLE_PPM[e.species], method="flow_time", flow_sccm=sccm,
                                            minutes=float(e.amount) / 60.0)
                rows.append({**base, "route": "Gas bottle", "compound": name, "formula": f, "amount": e.amount,
                             "unit": "s " + unit, "expected_ppbv": ppb})
            else:
                rate = p.gas_ppb_from_dosing(BOTTLE_PPM[e.species], method="flow_time", flow_sccm=sccm, minutes=60.0)
                rows.append({**base, "route": "Gas bottle, continuous", "compound": name, "formula": f,
                             "amount": np.nan, "unit": unit, "expected_ppbv": np.nan, "rate_ppbv_per_h": rate})
        elif e.kind in UNMEASURED:
            route, name, f = UNMEASURED[e.kind]
            rows.append({**base, "route": route, "compound": name, "formula": f, "amount": e.amount,
                         "unit": e.unit if isinstance(e.unit, str) else "", "expected_ppbv": np.nan})
        else:
            raise ValueError(f"unknown injection kind {e.kind!r} on {e.date} {e.time_utc}")
    return pd.DataFrame(rows, columns=COLUMNS)


if __name__ == "__main__":
    log = injection_log()
    OUTPUT_DIR.mkdir(exist_ok=True)
    log.to_csv(OUTPUT_DIR / "injection_log.csv", index=False)
    voc = log[log.route.str.startswith(("Solution", "Neat")) | log.compound.isin(["Propene", "Ethene"])]
    print(f"{len(log)} compound injections on {log.date.nunique()} days")
    print(voc.groupby("date").expected_ppbv.sum().round(1).rename("VOC ppbv injected").to_string())
    print(f"\nWritten: {OUTPUT_DIR / 'injection_log.csv'}")
