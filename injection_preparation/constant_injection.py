"""Constant (steady-state) isoprene injection to hold a fixed mixing ratio.

Mimics a constant biogenic isoprene source on top of a wildfire (BB) plume in
SAPHIR. Once the roof is open the dominant isoprene loss is OH oxidation, so at
steady state the injection rate must equal the chemical loss:

    injection rate  =  k_OH(isoprene) · [OH] · [isoprene] · V_chamber

[OH] follows the daytime cycle and is suppressed early by the BB plume's OH
reactivity (competing sinks), so the required injection *rises through the day*
as the BB reactivity decays and [OH] climbs. This module gives the MFC flow
needed as a function of [OH], the dark "increase rate" used to calibrate the
delivered flow before the roof opens, and how long the cylinder lasts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from injection_model import Chamber

N_A = 6.02214076e23                 # molecules / mol
ISOPRENE_KOH = 9.994e-11            # cm3 molec-1 s-1 (compound_properties.csv)
_VM0 = 22413.6                      # cm3/mol at 0 C, 1 atm (sccm reference)


def oh_from_lifetime(minutes: float, k_oh: float = ISOPRENE_KOH) -> float:
    """[OH] implied by an observed isoprene e-folding lifetime (minutes).

    Driving the plan off the *measured* lifetime is the robust choice: it lumps
    every loss (OH chemistry + dilution + walls) into the rate the injection has
    to replace, without needing to know [OH]."""
    return 1.0 / (minutes * 60.0) / k_oh


def steady_state_plan(target_pptv: float, oh_levels, chamber: Chamber | None = None,
                      k_oh: float = ISOPRENE_KOH, bottle_ppm: float = 10.0,
                      bottle_L: float = 10.0, bottle_bar: float = 70.0,
                      min_bar: float = 2.0, mfc_ref_C: float = 0.0) -> tuple[pd.DataFrame, dict]:
    """MFC flow to hold ``target_pptv`` isoprene against OH loss, per [OH] level.

    Returns (per-OH DataFrame, scenario dict). ``mfc_ref_C`` is the MFC's standard
    reference temperature (0 C → sccm; SAPHIR LCU uses ~25 C, ~9 % higher flow).
    """
    ch = chamber or Chamber()
    M = ch.number_density                       # molec/cm3 of air
    V_cm3 = ch.volume_m3 * 1e6
    iso_cm3 = target_pptv * 1e-12 * M           # isoprene molec/cm3
    n_iso = iso_cm3 * V_cm3                      # total isoprene molecules in chamber
    vm = _VM0 * (273.15 + mfc_ref_C) / 273.15   # molar volume at the MFC reference (cm3/mol)

    rows = []
    for oh in oh_levels:
        k_loss = k_oh * oh                       # s-1
        life_min = 1.0 / k_loss / 60.0
        molec_s = k_loss * n_iso                 # molecules/s to replace
        mol_s = molec_s / N_A
        mfc_sccm = mol_s / (bottle_ppm * 1e-6) * vm * 60.0
        rows.append({"OH_molec_cm3": oh, "k_loss_s-1": k_loss, "lifetime_min": life_min,
                     "inject_molec_s": molec_s, "MFC_sccm": mfc_sccm,
                     "dark_rise_pptv_min": target_pptv / life_min})
    df = pd.DataFrame(rows)

    # cylinder inventory + how long it lasts
    n_gas = bottle_bar * 1e5 * (bottle_L * 1e-3) / (8.314462618 * ch.temperature_K)
    iso_mol = n_gas * bottle_ppm * 1e-6
    usable_mol = iso_mol * (bottle_bar - min_bar) / bottle_bar
    df["bottle_hours"] = usable_mol / (df["inject_molec_s"] / N_A) / 3600.0

    scen = {"target_pptv": target_pptv, "iso_molec_cm3": iso_cm3, "n_iso_chamber": n_iso,
            "chamber": ch, "bottle_iso_mol": iso_mol, "usable_iso_mol": usable_mol,
            "bottle_ppm": bottle_ppm, "isoprene_reactivity_s-1": k_oh * iso_cm3}
    return df, scen


def dark_fill(target_pptv: float, mfc_sccm: float, chamber: Chamber | None = None,
              bottle_ppm: float = 10.0, mfc_ref_C: float = 0.0) -> dict:
    """Roof-closed (no OH) accumulation for a chosen flow: isoprene rises linearly.
    Returns the rise rate and time to reach ``target_pptv``."""
    ch = chamber or Chamber()
    vm = _VM0 * (273.15 + mfc_ref_C) / 273.15
    mol_s = mfc_sccm / 60.0 / vm * (bottle_ppm * 1e-6)
    molec_s = mol_s * N_A
    per_pptv = 1e-12 * ch.number_density * ch.volume_m3 * 1e6   # molecules per pptv in chamber
    rise_pptv_s = molec_s / per_pptv
    return {"mfc_sccm": mfc_sccm, "rise_pptv_min": rise_pptv_s * 60,
            "minutes_to_target": target_pptv / (rise_pptv_s * 60)}


# ── constant flow against a diurnal OH cycle ─────────────────────────────
def pptv_min_to_sccm(p_pptv_min: float, chamber: Chamber | None = None,
                     bottle_ppm: float = 10.0, mfc_ref_C: float = 0.0) -> float:
    """Convert a chamber production rate (pptv/min) to bottle flow (sccm)."""
    ch = chamber or Chamber()
    vm = _VM0 * (273.15 + mfc_ref_C) / 273.15
    per_pptv = 1e-12 * ch.number_density * ch.volume_m3 * 1e6   # molecules per pptv
    mol_s = (p_pptv_min / 60.0 * per_pptv) / N_A
    return mol_s / (bottle_ppm * 1e-6) * vm * 60.0


def diurnal_oh(t_h, oh_min: float = 1e6, oh_max: float = 4e6, day_h: float = 10.0):
    """sin² daylight [OH]: ``oh_min`` at roof open/close, ``oh_max`` at mid-day."""
    t = np.clip(np.asarray(t_h, dtype=float), 0.0, day_h)
    return oh_min + (oh_max - oh_min) * np.sin(np.pi * t / day_h) ** 2


def simulate(p_pptv_min: float, c0_pptv: float, t_h, oh, k_oh: float = ISOPRENE_KOH):
    """Integrate dC/dt = P − k(t)·C with an exact exponential step (C in pptv)."""
    t_h = np.asarray(t_h, dtype=float)
    oh = np.asarray(oh, dtype=float)
    dt_s = (t_h[1] - t_h[0]) * 3600.0
    p_s = p_pptv_min / 60.0
    c = np.empty_like(t_h)
    c[0] = c0_pptv
    for i in range(1, t_h.size):
        k = k_oh * oh[i - 1]
        css = p_s / k
        c[i] = css + (c[i - 1] - css) * np.exp(-k * dt_s)
    return c


def best_constant_flow(target_mean_pptv: float, c0_pptv: float, t_h, oh,
                       k_oh: float = ISOPRENE_KOH):
    """The single constant production rate whose *time-average* hits the target.

    dC/dt = P − k(t)C is linear in (C0, P), so C = C_a(C0) + P·C_b(1) exactly —
    two integrations give P in closed form (no iteration)."""
    c_a = simulate(0.0, c0_pptv, t_h, oh, k_oh)      # decay of the initial fill
    c_b = simulate(1.0, 0.0, t_h, oh, k_oh)          # unit-rate response
    p = (target_mean_pptv - c_a.mean()) / c_b.mean()
    return p, simulate(p, c0_pptv, t_h, oh, k_oh)


def _fmt(df, scen):
    d = df.copy()
    d["OH (1e6)"] = d["OH_molec_cm3"] / 1e6
    d = d[["OH (1e6)", "lifetime_min", "MFC_sccm", "dark_rise_pptv_min", "bottle_hours"]]
    d.columns = ["OH /1e6", "τ (min)", "MFC sccm", "dark rise pptv/min", "bottle (h)"]
    out = [d.to_string(index=False, float_format=lambda x: f"{x:.1f}")]
    out.append(f"\n  target = {scen['target_pptv']:.0f} pptv isoprene "
               f"({scen['iso_molec_cm3']:.2e} molec/cm³, {scen['n_iso_chamber']:.2e} in chamber)")
    out.append(f"  isoprene OH-reactivity at target: {scen['isoprene_reactivity_s-1']:.2f} s⁻¹")
    out.append(f"  cylinder: {scen['bottle_iso_mol']*1e6:.1f} µmol isoprene total, "
               f"{scen['usable_iso_mol']*1e6:.1f} µmol usable (to min bar)")
    return "\n".join(out)


if __name__ == "__main__":
    ch = Chamber()
    print(f"SAPHIR V={ch.volume_m3:.0f} m³, T={ch.temperature_K:.2f} K, "
          f"M={ch.number_density:.3e} molec/cm³")

    print("\n=== A. Driven by the MEASURED isoprene lifetime (60–90 min) ===")
    lifetimes = [60, 75, 90]
    df_l, scen = steady_state_plan(500, [oh_from_lifetime(t) for t in lifetimes], ch)
    df_l.insert(0, "measured_tau_min", lifetimes)
    print(df_l[["measured_tau_min", "OH_molec_cm3", "MFC_sccm",
                "dark_rise_pptv_min", "bottle_hours"]].to_string(
        index=False, float_format=lambda x: f"{x:.3g}"))
    print(f"\n  cylinder: {scen['bottle_iso_mol']*1e6:.1f} µmol isoprene "
          f"({scen['usable_iso_mol']*1e6:.1f} µmol usable to 2 bar)")
    print(f"  isoprene's own OH-reactivity at 500 pptv: {scen['isoprene_reactivity_s-1']:.2f} s⁻¹")

    print("\n=== B. If OH climbs as the BB plume decays ===")
    df, scen = steady_state_plan(500, [2e6, 4e6, 6e6, 8e6, 1e7], ch)
    print(_fmt(df, scen))

    print("\n=== C. Roof-closed fill options (rise rate you'd watch) ===")
    for f in (137, 206, 500):
        d = dark_fill(500, f, ch)
        print(f"  {f:3.0f} sccm ({100*f/500:.0f}% of the 0.5 LPM MFC): "
              f"{d['rise_pptv_min']:.1f} pptv/min → 500 pptv in {d['minutes_to_target']:.0f} min")
