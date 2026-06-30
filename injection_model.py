"""SAPHFIRE 2026 — injection calculation engine.

Pure-Python (no GUI). Converts between injected amounts and chamber mixing
ratios for the four prepared solutions (A-D), the light-gas VOC cylinders, and
the NOy gases, in both directions:

  forward  : amounts injected            -> chamber ppb (per compound + totals)
  inverse  : target total VOC ppb (+regime) -> required solution / gas amounts

All chemistry rests on the ideal-gas mole count of chamber air:
    n_air = P * V / (R * T)
    ppb_i = (mass_i / MW_i) / n_air * 1e9          (mass basis, for solutions)
    ppb_i = n_species_i / n_air * 1e9              (mole basis, for gases)

Config is read from ./config/ (see scaffold_config.py). Densities/purities are
placeholders flagged needs_review until you confirm them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

R = 8.314462618  # J / (mol K)
K_B = 1.380649e-23  # J / K
MFC_SIZES = (0.5, 5.0, 20.0)  # available MFC full-scale flows (LPM)
# Hardware constraint: some MFCs must run at a FIXED setpoint (% of full scale)
# rather than being auto-sized. UPDATE HERE when the constraint changes.
# Currently: the 20 LPM MFC is restricted to 40%.
MFC_FIXED_SETPOINT = {20.0: 40.0}
CONFIG_DIR = Path(__file__).with_name("config")


def carbon_count(formula) -> int:
    """Number of carbon atoms in a molecular formula (0 if none)."""
    if not isinstance(formula, str):
        return 0
    for el, n in re.findall(r"([A-Z][a-z]?)(\d*)", formula):
        if el == "C":
            return int(n) if n else 1
    return 0

SOLUTION_NAMES = {"A": "Phenolic + Furanoid", "B": "Hydrocarbon",
                  "C": "Oxygenate (carbonyls)", "D": "Oxygenate (acids)"}


@dataclass
class Chamber:
    name: str = "SAPHIR"
    volume_m3: float = 270.0
    temperature_K: float = 298.15
    pressure_Pa: float = 101325.0

    @property
    def n_air(self) -> float:
        """Total moles of air in the chamber."""
        return self.pressure_Pa * self.volume_m3 / (R * self.temperature_K)

    @property
    def number_density(self) -> float:
        """Air number density (molecules per cm^3)."""
        return self.pressure_Pa / (K_B * self.temperature_K) / 1e6

    def oh_reactivity(self, ppb: float, k_oh: float) -> float:
        """OH reactivity (s^-1) of `ppb` of a species with rate constant k_oh."""
        return k_oh * ppb * 1e-9 * self.number_density

    def ppb_from_mass(self, mass_g: float, mw: float) -> float:
        return (mass_g / mw) / self.n_air * 1e9

    def mass_from_ppb(self, ppb: float, mw: float) -> float:
        """Grams of a compound needed for a given chamber mixing ratio."""
        return ppb * 1e-9 * self.n_air * mw

    def ppb_from_moles(self, n_species: float) -> float:
        return n_species / self.n_air * 1e9

    def moles_from_ppb(self, ppb: float) -> float:
        return ppb * 1e-9 * self.n_air


@dataclass
class InjectionPlanner:
    chamber: Chamber
    voc: pd.DataFrame              # config/voc_species.csv
    bottles: pd.DataFrame         # config/gas_bottles.csv
    noy_defaults: pd.DataFrame    # config/noy_defaults.csv
    sol_density: pd.DataFrame     # config/solution_density.csv
    compounds: pd.DataFrame       # config/compound_properties.csv
    solutions: pd.DataFrame       # config/solutions.csv
    noy_params: dict = field(default_factory=dict)  # config/noy_parameterization.json
    # Reference conditions for gas dosing volumes.
    sccm_ref_T: float = 273.15    # MFC "standard" reference for sccm
    sccm_ref_P: float = 101325.0
    fill_T: float = 298.15        # fixed-volume fill conditions (room)
    fill_P: float = 101325.0

    # --- helpers ------------------------------------------------------------
    def solution_factors(self, sol: str) -> dict:
        """Per-solution prep/injection factors that account for water carried in
        by aqueous reagents (e.g. methylglyoxal 40% in H2O).

        vol_per_mg_voc   : injected liquid volume (µL) per mg of VOC delivered
                           — the reagent volume, so it INCLUDES the water.
        water_per_mg_voc : water mass (mg) per mg of VOC.
        voc_mass_fraction: VOC mass / total prepared (VOC+water) mass.
        prepared_density : g/mL of the prepared solution (VOC + water).
        """
        comp = self.solutions[self.solutions["solution"] == sol]
        props = self.compounds.set_index("key")
        vol_per_g = water_per_g = 0.0     # mL / g VOC  (== µL/mg);  g water / g VOC
        for _, r in comp.iterrows():
            p = props.loc[r["key"]]
            f = float(r["mass_fraction"])
            c = float(p["reagent_conc"]) if pd.notna(p.get("reagent_conc")) else 1.0
            d = p["density_g_per_mL"]
            d = float(d) if d not in ("", None) and pd.notna(d) else None
            if d:
                vol_per_g += (f / c) / d   # reagent volume (incl. water)
            water_per_g += f * (1.0 - c) / c
        return {
            "vol_per_mg_voc": vol_per_g,
            "water_per_mg_voc": water_per_g,
            "voc_mass_fraction": 1.0 / (1.0 + water_per_g),
            "prepared_density": (1.0 + water_per_g) / vol_per_g if vol_per_g else float("nan"),
        }

    def solution_density(self, sol: str) -> float:
        """g/mL of the prepared solution: measured if provided, else computed
        (includes water carried in by aqueous reagents)."""
        row = self.sol_density.loc[self.sol_density["solution"] == sol].iloc[0]
        meas = row.get("measured_density_g_per_mL", "")
        if meas not in ("", None) and not pd.isna(meas):
            return float(meas)
        return self.solution_factors(sol)["prepared_density"]

    def prep_volume(self, sol: str) -> float:
        row = self.sol_density.loc[self.sol_density["solution"] == sol].iloc[0]
        v = row.get("prep_volume_mL", 10.0)
        return float(v) if pd.notna(v) else 10.0

    def solution_recipe(self, sol: str, vial_volume_mL: float | None = None) -> dict:
        """Back-calculate how to prepare a vial of one solution.

        Given the batch volume (default from config, 10 mL) and the solution's
        density + composition, returns the mass of pure compound, the reagent
        weigh-out mass (pure / purity), and the neat-liquid volume for each
        component. Solids have no volume (weigh by mass).
        """
        vial = self.prep_volume(sol) if vial_volume_mL is None else vial_volume_mL
        rho = self.solution_density(sol)              # prepared (incl. water)
        fac = self.solution_factors(sol)
        total_mass_g = vial * rho                     # prepared mass (VOC + water)
        voc_mass_g = total_mass_g * fac["voc_mass_fraction"]
        comp = self.solutions[self.solutions["solution"] == sol]
        props = self.compounds.set_index("key")
        rows = []
        for _, r in comp.iterrows():
            p = props.loc[r["key"]]
            pure_g = voc_mass_g * r["mass_fraction"]   # pure VOC mass of this component
            purity = float(p["purity_fraction"]) if pd.notna(p["purity_fraction"]) else 1.0
            conc = float(p["reagent_conc"]) if pd.notna(p.get("reagent_conc")) else 1.0
            # reagent weigh-out accounts for impurity AND dilution (e.g. 40% aq)
            reagent_g = pure_g / (purity * conc)
            water_g = reagent_g * (1.0 - conc)        # water brought by aqueous reagent
            dens = p["density_g_per_mL"]
            vol_uL = (reagent_g / float(dens) * 1000.0
                      if dens not in ("", None) and pd.notna(dens) else np.nan)
            rows.append({
                "compound": p["compound"], "state": p["state_at_RT"],
                "mass_fraction": r["mass_fraction"],
                "pure_mass_mg": pure_g * 1e3,
                "weighout_mass_mg": reagent_g * 1e3,
                "water_brought_mg": water_g * 1e3,
                "volume_uL": vol_uL, "purity": purity, "reagent_conc": conc,
            })
        df = pd.DataFrame(rows).sort_values("weighout_mass_mg", ascending=False)
        return {"solution": sol, "vial_volume_mL": vial, "density_g_per_mL": rho,
                "total_mass_g": total_mass_g, "components": df.reset_index(drop=True)}

    def _gas_moles_for_volume(self, volume_mL: float, ref_T: float, ref_P: float) -> float:
        """Moles of bulk gas in `volume_mL` at the given reference conditions."""
        return ref_P * (volume_mL * 1e-6) / (R * ref_T)

    # --- gas dosing (mole basis, MW-independent) ---------------------------
    def gas_ppb_from_dosing(self, conc_ppm: float, *, method: str,
                            flow_sccm: float = 0.0, minutes: float = 0.0,
                            volume_mL: float = 0.0) -> float:
        """Chamber ppb produced by a cylinder dose.

        method='flow_time': flow_sccm for `minutes`; method='fixed_volume':
        `volume_mL` of cylinder gas at fill conditions.
        """
        if method == "flow_time":
            v_std = flow_sccm * minutes                      # standard cm^3 = mL
            n_mix = self._gas_moles_for_volume(v_std, self.sccm_ref_T, self.sccm_ref_P)
        elif method == "fixed_volume":
            n_mix = self._gas_moles_for_volume(volume_mL, self.fill_T, self.fill_P)
        else:
            raise ValueError(f"unknown dosing method: {method}")
        n_species = n_mix * conc_ppm * 1e-6
        return self.chamber.ppb_from_moles(n_species)

    def size_mfc(self, target_ppb: float, conc_ppm: float, *, corr: float = 1.0,
                 target_minutes: float = 0.75, mfc: float | None = None,
                 min_setpoint: float = 10.0) -> dict | None:
        """Pick an MFC + setpoint (% of full scale) so the injection takes about
        `target_minutes` (default 0.75 min ≈ 45 s).

        `corr` is the MFC gas-correction factor (delivered flow = air setpoint ×
        corr), since the MFCs are calibrated for air. The MFC setpoint is in
        air-equivalent units (what you dial), the delivered gas flow includes corr.
        """
        if conc_ppm <= 0 or target_ppb <= 0 or corr <= 0:
            return None
        rate1 = self.gas_ppb_from_dosing(conc_ppm, method="flow_time",
                                         flow_sccm=1000.0, minutes=1.0)  # ppb/min per LPM gas
        flow_gas = target_ppb / (rate1 * target_minutes)   # LPM of gas for target time
        setpoint_air = flow_gas / corr                     # MFC air-equivalent flow (LPM)
        full = (mfc if mfc is not None
                else next((m for m in MFC_SIZES if setpoint_air <= m), MFC_SIZES[-1]))
        if full in MFC_FIXED_SETPOINT:                     # hardware-constrained MFC
            sp, fixed = MFC_FIXED_SETPOINT[full], True
        else:                                              # auto-size to target time
            sp, fixed = max(min_setpoint, min(100.0, setpoint_air / full * 100.0)), False
        flow_actual = full * (sp / 100.0) * corr           # LPM gas delivered
        rate = rate1 * flow_actual
        return {"mfc_LPM": full, "setpoint_pct": sp, "fixed_setpoint": fixed,
                "gas_flow_sccm": flow_actual * 1000.0, "ppb_per_min": rate,
                "time_s": target_ppb / rate * 60.0 if rate > 0 else float("inf")}

    def gas_dose_for_ppb(self, target_ppb: float, conc_ppm: float) -> dict:
        """Injection amounts needed to reach `target_ppb` for a cylinder gas.

        Returns the required standard volume plus the two equivalent recipes:
        a fixed injected volume, and (flow, time) suggestions.
        """
        n_species = self.chamber.moles_from_ppb(target_ppb)
        if conc_ppm <= 0:
            return {"target_ppb": target_ppb, "bottle_ppm": conc_ppm,
                    "std_volume_mL": np.nan, "fixed_volume_mL": np.nan}
        n_mix = n_species / (conc_ppm * 1e-6)
        # standard volume (sccm reference) and fill-condition volume
        v_std_mL = n_mix * R * self.sccm_ref_T / self.sccm_ref_P / 1e-6
        v_fill_mL = n_mix * R * self.fill_T / self.fill_P / 1e-6
        return {
            "target_ppb": target_ppb,
            "bottle_ppm": conc_ppm,
            "std_volume_mL": v_std_mL,        # e.g. 100 sccm -> minutes = v/100
            "fixed_volume_mL": v_fill_mL,
        }

    # --- VOC: inverse (target total VOC ppb -> amounts) --------------------
    def inverse_voc(self, target_total_voc_ppb: float, *,
                    active_solutions=("A", "B", "C", "D"),
                    active_gases=("propene", "ethene", "acetylene"),
                    solution_scale: dict | None = None) -> dict:
        """Distribute a target total VOC mixing ratio across active species by
        the fingerprint mass weights, then realize per-solution and per-gas
        amounts. solution_scale lets you up/down-weight a solution (key-precursor
        experiments); default 1.0 each.
        """
        solution_scale = solution_scale or {}
        v = self.voc.copy()
        is_sol = v["role"].isin(active_solutions)
        is_gas = (v["role"] == "gas") & (v["key"].isin(active_gases))
        active = v[is_sol | is_gas].copy()
        # effective weight = overall mass % * solution scale factor
        scale = active["role"].map(lambda r: solution_scale.get(r, 1.0)).astype(float)
        active["weight"] = active["overall_mass_pct"] * scale

        # total_ppb = (K / n_air) * 1e9 * sum(weight/MW)  ->  solve for K (grams)
        denom = (active["weight"] / active["MW_g_per_mol"]).sum()
        K = target_total_voc_ppb * self.chamber.n_air / (1e9 * denom)
        active["mass_g"] = K * active["weight"]
        active["mass_mg"] = active["mass_g"] * 1e3
        active["ppb"] = active.apply(
            lambda r: self.chamber.ppb_from_mass(r["mass_g"], r["MW_g_per_mol"]), axis=1)
        return self._assemble_voc_result(active, target_total_voc_ppb)

    # --- VOC: forward (amounts -> ppb) -------------------------------------
    def forward_voc(self, solution_volumes_uL: dict | None = None,
                    gas_doses: dict | None = None) -> dict:
        """Chamber ppb from injected amounts. solution_volumes_uL maps 'A'..'D'
        to injected microliters; gas_doses maps a gas key to a dosing dict
        (see gas_ppb_from_dosing kwargs)."""
        solution_volumes_uL = solution_volumes_uL or {}
        gas_doses = gas_doses or {}
        v = self.voc.copy()
        rows = []
        for sol, vol_uL in solution_volumes_uL.items():
            fac = self.solution_factors(sol)
            # injected volume includes water; back out the VOC mass delivered
            voc_mass_mg = vol_uL / fac["vol_per_mg_voc"] if fac["vol_per_mg_voc"] else 0.0
            sub = v[v["role"] == sol]
            for _, r in sub.iterrows():
                mass_mg = voc_mass_mg * r["within_solution_mass_fraction"]
                rows.append({**r.to_dict(), "mass_mg": mass_mg,
                             "mass_g": mass_mg * 1e-3})
        for gkey, dose in gas_doses.items():
            r = v[(v["role"] == "gas") & (v["key"] == gkey)].iloc[0]
            conc = float(dose.get("conc_ppm", 0.0))
            ppb = self.gas_ppb_from_dosing(conc, **{k: dose[k] for k in dose
                                                    if k in ("method", "flow_sccm",
                                                             "minutes", "volume_mL")})
            rows.append({**r.to_dict(), "mass_mg": np.nan, "mass_g": np.nan, "ppb": ppb})
        active = pd.DataFrame(rows)
        if "ppb" not in active or active["ppb"].isna().any():
            mask = active["ppb"].isna() if "ppb" in active else slice(None)
            active.loc[mask, "ppb"] = active.loc[mask].apply(
                lambda r: self.chamber.ppb_from_mass(r["mass_g"], r["MW_g_per_mol"]), axis=1)
        total = active["ppb"].sum()
        return self._assemble_voc_result(active, total)

    def _assemble_voc_result(self, active: pd.DataFrame, total_ppb: float) -> dict:
        per_solution = []
        for sol in ("A", "B", "C", "D"):
            sub = active[active["role"] == sol]
            if sub.empty:
                continue
            voc_mass_mg = sub["mass_mg"].sum()
            fac = self.solution_factors(sol)
            water_mg = voc_mass_mg * fac["water_per_mg_voc"]
            per_solution.append({
                "solution": sol, "mixture": SOLUTION_NAMES[sol],
                # injected liquid volume INCLUDES water carried by aqueous reagents
                "inject_volume_uL": voc_mass_mg * fac["vol_per_mg_voc"],
                "voc_mass_mg": voc_mass_mg,
                "water_mass_mg": water_mg,
                "inject_mass_mg": voc_mass_mg + water_mg,   # total prepared mass injected
                "density_g_per_mL": fac["prepared_density"],
                "sum_ppb": sub["ppb"].sum(),
                "n_compounds": len(sub),
            })
        gases = active[active["role"] == "gas"][["key", "compound", "ppb"]]
        components = active[["key", "compound", "role", "MW_g_per_mol",
                             "mass_mg", "ppb"]].copy()
        return {
            "total_voc_ppb": total_ppb,
            "per_solution": pd.DataFrame(per_solution),
            "gases": gases.reset_index(drop=True),
            "components": components.sort_values(["role", "ppb"],
                                                 ascending=[True, False]).reset_index(drop=True),
        }

    # --- NOy from MCE (Gkatzelis 2024 Fig 7c) ------------------------------
    def noy_voc_ratio(self, mce: float) -> float:
        """NOy : ΣVOC mixing-ratio ratio (ppbv/ppbv) at a given MCE.

        Power fit from Gkatzelis et al. (2024) ACP Fig. 7c:
            NOy/ΣVOC = y0 + A * MCE**power
        """
        f = self.noy_params["noy_voc_ratio_powerfit"]
        return f["y0"] + f["A"] * mce ** f["power"]

    def k_oh(self) -> dict:
        """Per-compound OH rate constants (cm^3 molec^-1 s^-1, 298 K) from config."""
        out = {}
        for _, r in self.voc.iterrows():
            v = r.get("k_oh_298", "")
            if v not in ("", None) and not pd.isna(v):
                out[r["key"]] = float(v)
        return out

    def propene_surrogate_ppb(self, gas_ppb: dict) -> float:
        """Propene ppb that reproduces the TOTAL OH reactivity of a gas-VOC mix.

        OH reactivity ∝ k·[X], so (number density cancels):
            ppb_propene = Σ_i (k_i / k_propene) · ppb_i
        Used to replace ethene + acetylene (+ propene) by propene alone while
        preserving their combined reactivity rather than their mass.
        """
        k = self.k_oh()
        kp = k["propene"]
        return sum(k.get(g, 0.0) * ppb for g, ppb in gas_ppb.items()) / kp

    def co_from_voc(self, total_voc_ppb: float) -> dict:
        """Co-injected CO from the VOC:CO parameterization.

        Gkatzelis et al. (2024) ACP Fig. 7b: ΣNMOG = intercept + slope * CO
        (ppbv). Inverted: CO = (ΣVOC - intercept) / slope. Clamped to >= 0.
        Returns CO ppb and the injection amounts for the CO cylinder.
        """
        f = self.noy_params["co_from_voc"]
        co_ppb = max(0.0, (total_voc_ppb - f["intercept_ppb_NMOG"])
                     / f["slope_ppbv_NMOG_per_ppbv_CO"])
        bottle_ppm = dict(zip(self.bottles["key"], self.bottles["bottle_concentration_ppm"]))
        conc = bottle_ppm.get("co", np.nan)
        dose = (self.gas_dose_for_ppb(co_ppb, float(conc)) if not pd.isna(conc)
                else {"std_volume_mL": np.nan, "fixed_volume_mL": np.nan})
        return {"co_ppb": co_ppb, "bottle_ppm": conc,
                "std_volume_mL": dose["std_volume_mL"],
                "fixed_volume_mL": dose["fixed_volume_mL"]}

    def noy_from_mce(self, total_voc_ppb: float, mce: float, *,
                     speciation: dict | None = None,
                     nh3_ppb: float | None = None) -> dict:
        """Inject NOy scaled to the VOC load and combustion regime (MCE).

        Returns the total NOy, the NOy:ΣVOC ratio, and a per-species table
        (NO/NO2/HONO from the speciation split, plus NH3 if provided) with the
        injection amounts for each available cylinder.
        """
        speciation = speciation or self.noy_params["noy_speciation"]
        ratio = self.noy_voc_ratio(mce)
        noy_total = total_voc_ppb * ratio
        bottle_ppm = dict(zip(self.bottles["key"], self.bottles["bottle_concentration_ppm"]))

        rows = []
        for sp, frac in speciation.items():
            target = noy_total * frac
            rows.append(self._noy_row(sp, target, frac, bottle_ppm))
        if nh3_ppb is not None:
            rows.append(self._noy_row("nh3", float(nh3_ppb), np.nan, bottle_ppm))
        return {
            "mce": mce, "ratio": ratio, "noy_total_ppb": noy_total,
            "species": pd.DataFrame(rows),
        }

    def _noy_row(self, sp: str, target_ppb: float, frac, bottle_ppm: dict) -> dict:
        conc = bottle_ppm.get(sp, np.nan)
        dose = (self.gas_dose_for_ppb(target_ppb, float(conc))
                if not pd.isna(conc) else
                {"std_volume_mL": np.nan, "fixed_volume_mL": np.nan})
        return {"species": sp.upper(), "fraction_of_NOy": frac,
                "target_ppb": target_ppb, "bottle_ppm": conc,
                "std_volume_mL": dose["std_volume_mL"],
                "fixed_volume_mL": dose["fixed_volume_mL"]}

    # --- NOy from regime (manual defaults) ---------------------------------
    def noy_plan(self, regime: str, overrides: dict | None = None) -> pd.DataFrame:
        """Per-species NOy target ppb for a regime + the injection amounts.
        overrides maps species -> ppb to replace the (TBD) defaults."""
        overrides = overrides or {}
        d = self.noy_defaults[self.noy_defaults["regime"] == regime]
        bottle_ppm = dict(zip(self.bottles["key"], self.bottles["bottle_concentration_ppm"]))
        rows = []
        for _, r in d.iterrows():
            sp = r["species"]
            target = overrides.get(sp, r["target_ppb"])
            target = float(target) if target not in ("", None) and not pd.isna(target) else np.nan
            conc = bottle_ppm.get(sp, np.nan)
            dose = (self.gas_dose_for_ppb(target, float(conc))
                    if not np.isnan(target) and not pd.isna(conc) else
                    {"std_volume_mL": np.nan, "fixed_volume_mL": np.nan})
            rows.append({
                "species": sp.upper(), "regime": regime, "target_ppb": target,
                "bottle_ppm": conc,
                "std_volume_mL": dose["std_volume_mL"],
                "fixed_volume_mL": dose["fixed_volume_mL"],
            })
        return pd.DataFrame(rows)


# --- loading ----------------------------------------------------------------
def load_planner(config_dir: Path = CONFIG_DIR) -> InjectionPlanner:
    chamber_d = json.loads((config_dir / "chamber.json").read_text())
    chamber = Chamber(name=chamber_d["name"], volume_m3=chamber_d["volume_m3"],
                      temperature_K=chamber_d["temperature_K"],
                      pressure_Pa=chamber_d["pressure_Pa"])
    return InjectionPlanner(
        chamber=chamber,
        voc=pd.read_csv(config_dir / "voc_species.csv"),
        bottles=pd.read_csv(config_dir / "gas_bottles.csv"),
        noy_defaults=pd.read_csv(config_dir / "noy_defaults.csv"),
        sol_density=pd.read_csv(config_dir / "solution_density.csv"),
        compounds=pd.read_csv(config_dir / "compound_properties.csv"),
        solutions=pd.read_csv(config_dir / "solutions.csv"),
        noy_params=json.loads((config_dir / "noy_parameterization.json").read_text()),
    )


if __name__ == "__main__":
    p = load_planner()
    print(f"Chamber {p.chamber.name}: n_air = {p.chamber.n_air:,.0f} mol "
          f"(V={p.chamber.volume_m3} m^3, T={p.chamber.temperature_K} K)\n")

    res = p.inverse_voc(target_total_voc_ppb=150.0)
    print("INVERSE: target total VOC = 150 ppb -> per-solution injection")
    print(res["per_solution"].to_string(index=False,
          float_format=lambda x: f"{x:,.3f}"))
    print(f"\nrealized total VOC ppb = {res['total_voc_ppb']:.2f}")

    for label, mce in (("smoldering", 0.90), ("flaming", 0.95)):
        noy = p.noy_from_mce(150.0, mce)
        print(f"\nNOy @ MCE={mce} ({label}): ratio={noy['ratio']:.4f}, "
              f"total NOy={noy['noy_total_ppb']:.2f} ppb")
        print(noy["species"][["species", "fraction_of_NOy", "target_ppb"]].to_string(
            index=False, float_format=lambda x: f"{x:,.3f}"))
