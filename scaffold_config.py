"""SAPHFIRE 2026 — single source of truth for the injection fingerprint + configs.

Builds the tidy injection fingerprint and all planner config files from one
explicit table (FINGERPRINT below), transcribed from "Saphfire mixtures_v07.xlsx"
(sheets "NMOGs INJECTIONS" + "Georgios Updates RD").

Structure (v07): four prepared liquid mixtures + gases.
  A  Phenolic + Furanoid   (phenolics + furanoids combined in one bottle)
  B  Hydrocarbon
  C  Oxygenate (carbonyls) (incl. methylglyoxal as a 40% aqueous reagent)
  D  Oxygenate (acids)     (acetic, formic, acrylic)
  gas  propene, ethene, acetylene

Excluded vs. the raw inventory: formaldehyde, glycolaldehyde, 1,3-butadiene.
Eugenol slot is filled by eucalyptol (1,8-cineole) — note it is an ETHER, not a
phenol. Densities / water solubilities / states are from the RD sheet; MW is
computed from the molecular formula.

Run to (re)write fingerprint_tidy.csv and config/*.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
CONFIG_DIR = ROOT / "config"
TIDY_CSV = ROOT / "fingerprint_tidy.csv"

SOLUTION_NAMES = {
    "A": "Phenolic + Furanoid",
    "B": "Hydrocarbon",
    "C": "Oxygenate (carbonyls)",
    "D": "Oxygenate (acids)",
}

# --- molecular weight from formula (CHNO only, exact) ------------------------
_ATOMIC = {"C": 12.011, "H": 1.008, "O": 15.999, "N": 14.007}


def formula_mw(formula: str) -> float:
    mw = 0.0
    for elem, count in re.findall(r"([A-Z][a-z]?)(\d*)", formula):
        if not elem:
            continue
        mw += _ATOMIC[elem] * (int(count) if count else 1)
    return round(mw, 3)


# --- the fingerprint --------------------------------------------------------
# Fields: solution, subgroup, firelab_name, surrogate, key, formula, mass_pct,
# density_g_per_mL, solubility_H2O_g_per_L, state, CAS, reagent_conc, comment.
# mass_pct is the FIRELAB inventory mass %; reagent_conc is the active fraction
# of the purchased reagent (1.0 = neat; 0.40 = 40% in water). density/solubility
# from RD sheet; solids use a density≈1 "solid-as-liquid" approximation as in RD.
def _c(solution, subgroup, firelab, surrogate, key, formula, mass_pct,
       density, sol_gL, state, cas, reagent_conc=1.0, comment="", k_oh=None):
    return dict(solution=solution, subgroup=subgroup, firelab_name=firelab,
                surrogate=surrogate, key=key, formula=formula, mass_pct=mass_pct,
                density_g_per_mL=density, solubility_H2O_g_per_L=sol_gL,
                state_at_RT=state, CAS=cas, reagent_conc=reagent_conc, comment=comment,
                k_oh_298=k_oh)   # OH rate const, cm3 molec-1 s-1 at 298 K, ~1 atm


FINGERPRINT = [
    # --- A: Phenolic + Furanoid (subgroup Phenolic) ---
    _c("A", "Phenolic", "Guaiacol (=2-methoxyphenol)", "Guaiacol", "guaiacol", "C7H8O2", 3.9, 1.112, 23, "solid", "90-05-1"),
    _c("A", "Phenolic", "2-Methylphenol (=o-cresol) + anisol", "o-Cresol", "o_cresol", "C7H8O", 2.1, 1.05, 25, "liquid", "95-48-7", comment="mp 31 C"),
    _c("A", "Phenolic", "Catechol", "Catechol", "catechol", "C6H6O2", 1.8, 1.0, 430, "solid", "120-80-9"),
    _c("A", "Phenolic", "2-Methoxy-4-methylphenol (= creosol)", "Creosol", "creosol", "C8H10O2", 1.8, 1.092, None, "liquid", "93-51-6"),
    _c("A", "Phenolic", "Phenol", "Phenol", "phenol", "C6H6O", 2.7, 1.0, 84, "solid", "108-95-2"),
    _c("A", "Phenolic", "Eugenol + isoeugenol", "Eucalyptol (1,8-cineole)", "eucalyptol", "C10H18O", 0.5, 0.9225, None, "liquid", "470-82-6",
       comment="Eugenol unavailable -> eucalyptol substituted; ETHER, not a phenol; mp 1.5 C"),
    # --- A: Furanoid ---
    _c("A", "Furanoid", "2-furfural + 3-furfural + other HCO2", "2-furfural", "furfural", "C5H4O2", 2.9, 1.16, None, "liquid", "98-01-1"),
    _c("A", "Furanoid", "5-methyl-furfural", "5-methyl-furfural", "methylfurfural", "C6H6O2", 1.8, 1.11, None, "liquid", "620-02-0"),
    _c("A", "Furanoid", "2-furanmethanol + other HCO2", "2-furanmethanol", "furfuryl_alcohol", "C5H6O2", 1.7, 1.13, None, "liquid", "98-00-0"),
    _c("A", "Furanoid", "2-(3H)Furanone", "2(3H)-Furanone", "furanone", "C4H4O2", 3.5, 1.209, None, "liquid", "20825-71-2", comment="maybe not enough available at FZJ"),
    _c("A", "Furanoid", "Furan", "Furan", "furan", "C4H4O", 2.6, 0.94, None, "liquid", "110-00-9", comment="volatility risk (bp 31 C)"),
    _c("A", "Furanoid", "5-(hydroxymethyl)-2-furfural", "5-(hydroxymethyl)-2-furfural", "hmf", "C6H6O3", 2.8, 1.0, 10, "solid", "67-47-0"),
    _c("A", "Furanoid", "2-methylfuran + 3-methylfuran + general HCO", "2-methylfuran", "methylfuran", "C5H6O", 1.6, 0.91, None, "liquid", "534-22-5"),
    _c("A", "Furanoid", "2,5-dimethyl furan + 2-ethylfuran + other C2 furans", "2,5-dimethylfuran", "dimethylfuran", "C6H8O", 1.0, 0.905, None, "liquid", "625-86-5"),
    # --- B: Hydrocarbon ---
    _c("B", "", "Monoterpenes", "a-pinene", "a_pinene", "C10H16", 4.4, 0.858, None, "liquid", "80-56-8", comment="looking for monoterpene with enough available"),
    _c("B", "", "Benzene", "benzene", "benzene", "C6H6", 1.3, 0.876, None, "liquid", "71-43-2"),
    _c("B", "", "Toluene", "Toluene", "toluene", "C7H8", 1.4, 0.867, None, "liquid", "108-88-3"),
    _c("B", "", "Isoprene", "Isoprene", "isoprene", "C5H8", 0.8, 0.681, None, "liquid", "78-79-5"),
    _c("B", "", "Ethyl Benzene", "Ethyl Benzene", "ethylbenzene", "C8H10", 0.05, 0.87, None, "liquid", "100-41-4"),
    _c("B", "", "M+P Xylene", "m-xylene", "m_xylene", "C8H10", 0.34, 0.868, None, "liquid", "108-38-3"),
    _c("B", "", "O-xylene", "o-xylene", "o_xylene", "C8H10", 0.115, 0.88, None, "liquid", "95-47-6"),
    _c("B", "", "Sesquiterpenes", "b-caryophyllene", "caryophyllene", "C15H24", 0.5, 0.91, None, "liquid", "87-44-5", comment="mp ~25 C"),
    # --- C: Oxygenate (carbonyls) ---
    _c("C", "", "Methanol", "Methanol", "methanol", "CH4O", 4.2, 0.79, None, "liquid", "67-56-1"),
    _c("C", "", "Acetaldehyde", "Acetaldehyde", "acetaldehyde", "C2H4O", 3.6, 0.784, None, "liquid", "75-07-0"),
    _c("C", "", "Acrolein", "Acrolein", "acrolein", "C3H4O", 3.0, 0.84, None, "liquid", "107-02-8"),
    _c("C", "", "Methyl Acetate", "Methyl Acetate", "methyl_acetate", "C3H6O2", 0.864706, 0.934, None, "liquid", "79-20-9"),
    _c("C", "", "Hydroxy Acetone", "Hydroxy Acetone", "hydroxyacetone", "C3H6O2", 1.235294, 1.08, None, "liquid", "116-09-6"),
    _c("C", "", "2,3-butanedione + methyl acrylate + other HCO2", "2,3-butanedione", "butanedione", "C4H6O2", 1.7, 0.983, None, "liquid", "431-03-8"),
    _c("C", "", "Acetone", "Acetone", "acetone", "C3H6O", 1.6, 0.79, None, "liquid", "67-64-1"),
    _c("C", "", "MVK", "MVK", "mvk", "C4H6O", 0.624, 0.83, None, "liquid", "78-94-4"),
    _c("C", "", "MACR", "MACR", "macr", "C4H6O", 0.247, 0.83, None, "liquid", "78-85-3"),
    _c("C", "", "Crotonaldehyde", "Crotonaldehyde", "crotonaldehyde", "C4H6O", 0.429, 0.85, None, "liquid", "123-73-9"),
    _c("C", "", "Pyruvaldehyde (=methyl glyoxal)", "Methyl Glyoxal", "methylglyoxal", "C3H4O2", 1.15, 1.046, None, "liquid", "78-98-8",
       reagent_conc=0.40, comment="reagent is 40% in H2O"),
    _c("C", "", "Methyl methacrylate + other HCO2", "Methyl methacrylate", "methyl_methacrylate", "C5H8O2", 0.6, 0.94, None, "liquid", "80-62-6", comment="borrowed from JCNS-1"),
    _c("C", "", "Acetonitrile", "acetonitrile", "acetonitrile", "C2H3N", 0.5, 0.786, None, "liquid", "75-05-8"),
    _c("C", "", "MEK + butanal + 2-methylpropanal", "MEK", "mek", "C4H8O", 0.5, 0.805, None, "liquid", "78-93-3"),
    # --- D: Oxygenate (acids) ---
    _c("D", "", "Acetic Acid", "Acetic Acid", "acetic_acid", "C2H4O2", 5.829, 1.05, None, "liquid", "64-19-7"),
    _c("D", "", "Formic Acid", "Formic Acid", "formic_acid", "CH2O2", 1.0, 1.22, None, "liquid", "64-18-6"),
    _c("D", "", "acrylic acid", "Acrylic acid", "acrylic_acid", "C3H4O2", 1.15, 1.051, None, "liquid", "79-10-7",
       comment="mp 13 C; polymerizes (use inhibited stock)"),
    # --- gases (from cylinders, not prepared) ---  k_oh: MCM/IUPAC 298 K, ~1 atm
    _c("gas", "", "Propene", "Propene", "propene", "C3H6", 2.9, None, None, "gas", "115-07-1", k_oh=2.63e-11),
    _c("gas", "", "ethene", "Ethene", "ethene", "C2H4", 1.9, None, None, "gas", "74-85-1", k_oh=8.5e-12),
    _c("gas", "", "acetylene", "acetylene", "acetylene", "C2H2", 1.3, None, None, "gas", "74-86-2", k_oh=7.8e-13),
]

# Per-solution preparation settings: vial/batch volume (mL) and prep notes.
SOLUTION_PREP = {
    "A": (10.0, "Furan is volatile — prepare/seal carefully."),
    "B": (10.0, ""),
    "C": (10.0, "Methylglyoxal is a 40% aqueous reagent (brings water). Aqueous."),
    "D": (10.0, "Acids — keep separate from the carbonyls (Mix C). Acrylic acid polymerizes."),
}

GAS_BOTTLES = ["propene", "ethene", "acetylene", "no", "no2", "hono", "co"]


def _df() -> pd.DataFrame:
    df = pd.DataFrame(FINGERPRINT)
    df["MW_g_per_mol"] = df["formula"].map(formula_mw)
    df["mixture"] = df["solution"].map(lambda s: SOLUTION_NAMES.get(s, "Gases"))
    # within-solution mass fraction (liquids only; gases have no mixture share)
    df["mixture_mass_pct"] = float("nan")
    for sol, sub in df[df["solution"].isin(list("ABCD"))].groupby("solution"):
        tot = sub["mass_pct"].sum()
        df.loc[sub.index, "mixture_mass_pct"] = sub["mass_pct"] / tot * 100.0
    return df


def write_tidy(df: pd.DataFrame) -> None:
    cols = ["solution", "mixture", "subgroup", "firelab_name", "surrogate", "key",
            "formula", "MW_g_per_mol", "mass_pct", "mixture_mass_pct",
            "density_g_per_mL", "solubility_H2O_g_per_L", "state_at_RT",
            "reagent_conc", "k_oh_298", "CAS", "comment"]
    out = df[cols].copy()
    out.loc[out["solution"] == "gas", "solution"] = ""   # gases: blank solution
    out.to_csv(TIDY_CSV, index=False)


def write_compound_properties(df: pd.DataFrame) -> pd.DataFrame:
    props = df[["key", "surrogate", "formula", "MW_g_per_mol", "density_g_per_mL",
                "solubility_H2O_g_per_L", "state_at_RT", "reagent_conc", "k_oh_298",
                "CAS", "comment"]].copy()
    props = props.rename(columns={"surrogate": "compound"})
    props["density_g_per_mL"] = props["density_g_per_mL"].fillna("")
    props["solubility_H2O_g_per_L"] = props["solubility_H2O_g_per_L"].fillna("")
    props["purity_fraction"] = 0.97
    props["enabled"] = True
    props["needs_review"] = True
    props.to_csv(CONFIG_DIR / "compound_properties.csv", index=False)
    return props


def write_solutions(df: pd.DataFrame) -> pd.DataFrame:
    liq = df[df["solution"].isin(list("ABCD"))]
    rows = []
    for _, r in liq.iterrows():
        rows.append({"solution": r["solution"], "key": r["key"],
                     "compound": r["surrogate"],
                     "mass_fraction": round(r["mixture_mass_pct"] / 100.0, 6)})
    out = pd.DataFrame(rows)
    out.to_csv(CONFIG_DIR / "solutions.csv", index=False)

    dens_rows = []
    for sol, sub in df[df["solution"].isin(list("ABCD"))].groupby("solution"):
        inv = liqfrac = 0.0
        for _, r in sub.iterrows():
            d = r["density_g_per_mL"]
            if pd.notna(d):
                inv += (r["mixture_mass_pct"] / 100.0) / float(d)
                liqfrac += r["mixture_mass_pct"] / 100.0
        prep_vol, prep_note = SOLUTION_PREP.get(sol, (10.0, ""))
        dens_rows.append({
            "solution": sol,
            "computed_density_g_per_mL": round(liqfrac / inv, 4) if inv else "",
            "liquid_mass_fraction_covered": round(liqfrac, 4),
            "measured_density_g_per_mL": "",
            "prep_volume_mL": prep_vol, "prep_note": prep_note,
        })
    pd.DataFrame(dens_rows).to_csv(CONFIG_DIR / "solution_density.csv", index=False)
    return out


def write_voc_species(df: pd.DataFrame) -> None:
    rows = []
    for _, r in df.iterrows():
        role = r["solution"] if r["solution"] in list("ABCD") else "gas"
        rows.append({
            "key": r["key"], "compound": r["surrogate"], "role": role,
            "MW_g_per_mol": r["MW_g_per_mol"],
            "density_g_per_mL": r["density_g_per_mL"] if pd.notna(r["density_g_per_mL"]) else "",
            "state_at_RT": r["state_at_RT"],
            "k_oh_298": r["k_oh_298"] if pd.notna(r["k_oh_298"]) else "",
            "overall_mass_pct": round(r["mass_pct"], 6),
            "within_solution_mass_fraction": (round(r["mixture_mass_pct"] / 100.0, 6)
                                              if pd.notna(r["mixture_mass_pct"]) else ""),
        })
    pd.DataFrame(rows).to_csv(CONFIG_DIR / "voc_species.csv", index=False)


def write_gas_bottles(df: pd.DataFrame) -> None:
    mw = dict(zip(df["key"], df["MW_g_per_mol"]))
    name = dict(zip(df["key"], df["surrogate"]))
    extra_mw = {"no": formula_mw("NO"), "no2": formula_mw("NO2"),
                "hono": formula_mw("HNO2"), "co": formula_mw("CO")}
    extra_name = {"no": "NO", "no2": "NO2", "hono": "HONO", "co": "CO"}
    rows = []
    for key in GAS_BOTTLES:
        rows.append({
            "key": key, "species": name.get(key, extra_name.get(key, key)),
            "MW_g_per_mol": mw.get(key, extra_mw.get(key)),
            "bottle_concentration_ppm": "", "balance_gas": "N2",
            "default_dosing": "flow_time", "enabled": True, "needs_review": True,
        })
    pd.DataFrame(rows).to_csv(CONFIG_DIR / "gas_bottles.csv", index=False)


def write_noy_defaults() -> None:
    rows = [{"regime": rg, "species": sp, "target_ppb": "", "enabled": True}
            for rg in ("flaming", "smoldering") for sp in ("no", "no2", "hono")]
    pd.DataFrame(rows).to_csv(CONFIG_DIR / "noy_defaults.csv", index=False)


def write_noy_parameterization() -> None:
    params = {
        "_source": ("Gkatzelis et al. (2024) ACP 24, 929, Fig. 7c: "
                    "NOy/SumVOC = y0 + A*MCE^power (ppbv/ppbv). Speciation "
                    "70/20/10 NO/NO2/HONO from Roberts et al. (2020) FireLab "
                    "flaming PMF, per M. Coggon email."),
        "noy_voc_ratio_powerfit": {"y0": 0.013, "A": 1.72, "power": 31},
        "noy_speciation": {"no": 0.70, "no2": 0.20, "hono": 0.10},
        "mce_presets": {"smoldering": 0.90, "flaming": 0.95},
        "default_total_voc_ppb": 150.0,
        "co_from_voc": {
            "_source": ("Gkatzelis et al. (2024) ACP 24, 929, Fig. 7b: "
                        "SumNMOG = intercept + slope*CO (ppbv). 137 ppbv NMOG "
                        "per ppmv CO = 0.137 ppbv/ppbv. CO = (SumVOC - intercept)/slope."),
            "intercept_ppb_NMOG": 11.29,
            "slope_ppbv_NMOG_per_ppbv_CO": 0.137,
        },
    }
    (CONFIG_DIR / "noy_parameterization.json").write_text(json.dumps(params, indent=2))


def write_chamber() -> None:
    chamber = {"name": "SAPHIR", "volume_m3": 270.0, "temperature_K": 298.15,
               "pressure_Pa": 101325.0,
               "_note": "Edit to match the experiment's actual T/P and effective volume."}
    (CONFIG_DIR / "chamber.json").write_text(json.dumps(chamber, indent=2))


if __name__ == "__main__":
    CONFIG_DIR.mkdir(exist_ok=True)
    df = _df()
    write_tidy(df)
    write_compound_properties(df)
    write_solutions(df)
    write_voc_species(df)
    write_gas_bottles(df)
    write_noy_defaults()
    write_noy_parameterization()
    write_chamber()
    n_liq = (df["solution"] != "gas").sum()
    print(f"Wrote {TIDY_CSV.name} and config/* :")
    for p in sorted(CONFIG_DIR.glob("*")):
        print(f"  - {p.name}")
    print(f"\n{len(df)} species: {n_liq} liquid (A-D) + {(df['solution']=='gas').sum()} gas.")
    print("Mixtures:", {s: SOLUTION_NAMES[s] for s in 'ABCD'})
