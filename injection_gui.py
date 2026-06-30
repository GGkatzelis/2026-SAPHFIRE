"""SAPHFIRE 2026 — Injection Planner (Streamlit GUI).

Run with:
    .venv\\Scripts\\streamlit run injection_gui.py
(or just press Run / `python injection_gui.py` — it relaunches itself.)

Workflow:
  1. Scenario (top): pick the combustion regime (flaming/smoldering — this sets
     the NOy:VOC ratio and CO automatically), the total VOC target, and tick
     what goes into the chamber (solutions A-D, gas-phase VOCs, CO/NO/NO2/HONO).
     A live "total emissions" pie shows the resulting composition.
  2. The total VOC is distributed across the included VOC species by the
     fingerprint mass fractions (no scale — everything-included = classic ratio).
  3. Injection plan: how much of each mixture to inject (volume incl. water) and
     the gas-phase target ppb (+ provisional volumes from a default cylinder
     concentration until the real bottle/MFC details are added).

Config lives in ./config/. Edits in the app are session-only.
"""

from __future__ import annotations

import io
import math

import pandas as pd
import streamlit as st

from injection_model import SOLUTION_NAMES, Chamber, carbon_count, load_planner

# Relaunch under `streamlit run` if started as a plain script (IDE Run button).
import logging as _logging
_logging.getLogger(
    "streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(_logging.ERROR)
from streamlit.runtime.scriptrunner import get_script_run_ctx as _get_ctx

if _get_ctx() is None:
    import sys
    from streamlit.web import cli as _stcli

    sys.argv = ["streamlit", "run", __file__]
    raise SystemExit(_stcli.main())

st.set_page_config(page_title="SAPHFIRE Injection Planner", layout="wide")

from saphfire_plots import spectral_colors, styled_pie  # noqa: E402

# Fixed color per category so a given item is the same color in every pie.
CATEGORY_COLORS = {
    "Sol A": (0.96, 0.45, 0.45), "Sol B": (0.98, 0.85, 0.40),
    "Sol C": (0.40, 0.82, 0.78), "Sol D": (0.52, 0.60, 0.95),
    "Propene": (0.99, 0.64, 0.34), "Propene (surrogate)": (0.99, 0.64, 0.34),
    "Ethene": (1.00, 0.80, 0.55), "Acetylene": (0.93, 0.53, 0.24),
    "acetylene": (0.93, 0.53, 0.24), "Gas VOC": (0.99, 0.64, 0.34),
    "CO": (0.55, 0.82, 0.45), "NOy": (0.78, 0.52, 0.92), "NOx": (0.78, 0.52, 0.92),
    "NMOG": (0.62, 0.76, 0.86),
}


def colors_for(labels):
    """Fixed category colors where known, spectral fallback otherwise."""
    fallback = spectral_colors(len(labels))
    return [CATEGORY_COLORS.get(lbl, fallback[i]) for i, lbl in enumerate(labels)]

LIGHT_GASES = ["propene", "ethene", "acetylene"]
NOY_SPECIES = ["no", "no2", "hono"]
NITROGEN = {"no", "no2", "hono"}
ALL_GAS = LIGHT_GASES + ["co"] + NOY_SPECIES
GAS_LABEL = {"propene": "Propene", "ethene": "Ethene", "acetylene": "Acetylene",
             "co": "CO", "no": "NO", "no2": "NO2", "hono": "HONO"}
# Default input-table values per species: (bottle ppm, MFC flow LPM as string).
# Concentrated bottles -> 0.5 LPM; dilute (ppm) -> 5 LPM. Update with real bottles.
GAS_DEFAULTS = {
    "propene":   (10_000.0,  "0.5"),   # 1%
    "ethene":    (100_000.0, "0.5"),   # 10%
    "acetylene": (1_000_000.0, "0.5"), # n/a (folded into propene if surrogate on)
    "co":        (999_970.0, "0.5"),   # 99.997%
    "no":        (3_800.0,   "5"),     # 3800 ppm
    "no2":       (500.0,     "5"),     # 500 ppm
}
# Species injected from cylinders via the MFC table here. HONO is injected by a
# different team (we only report its target ppb); O3 is from the generator.
GAS_TABLE_KEYS = ["propene", "ethene", "acetylene", "co", "no", "no2"]
# MFC gas-correction factor (delivered flow = air setpoint × factor). ~1 for
# dilute mixtures in N2; pure/concentrated gases differ (CO/ethene from the LCU).
GAS_CORR = {"propene": 1.00, "ethene": 1.022, "acetylene": 1.00,
            "co": 0.963, "no": 1.00, "no2": 1.00}


@st.cache_data
def _load():
    return load_planner()


def fmt(df, prec=3):
    return df.style.format(precision=prec, na_rep="—")


planner = _load()

# ===== Sidebar: chamber ===================================================== #
st.sidebar.title("SAPHFIRE Injection Planner")
st.sidebar.header("Chamber — SAPHIR")
V = st.sidebar.number_input("Volume (m³)", value=float(planner.chamber.volume_m3), step=1.0)
T = st.sidebar.number_input("Temperature (K)", value=float(planner.chamber.temperature_K), step=1.0)
P = st.sidebar.number_input("Pressure (Pa)", value=float(planner.chamber.pressure_Pa), step=100.0)
planner.chamber = Chamber("SAPHIR", V, T, P)
st.sidebar.caption(f"n_air = {planner.chamber.n_air:,.0f} mol")

st.title("SAPHFIRE 2026 — Injection Planner")

# ===== 1 · Scenario ========================================================= #
st.header("1 · Scenario — what goes into the chamber")

top = st.columns([1, 1])
with top[0]:
    regime = st.radio("Combustion regime", ["flaming", "smoldering"], horizontal=True)
    mce = planner.noy_params["mce_presets"][regime]
    st.caption(f"MCE {mce} → sets NOy:VOC ratio and CO automatically.")
with top[1]:
    total_voc = st.number_input("Total VOC target (ppb)",
                                value=float(planner.noy_params.get("default_total_voc_ppb", 150.0)),
                                min_value=0.0, step=10.0)

st.markdown("**Include in the chamber:**")
inc = st.columns(3)
with inc[0]:
    st.markdown("VOC solutions")
    active_solutions = [s for s in "ABCD"
                        if st.checkbox(f"{s} · {SOLUTION_NAMES[s]}", value=True, key=f"sol_{s}")]
with inc[1]:
    st.markdown("Gas-phase VOCs")
    active_gases = [g for g in LIGHT_GASES
                    if st.checkbox(g, value=True, key=f"gas_{g}")]
    surrogate = st.checkbox("⤷ propene surrogate for acetylene "
                            "(match OH reactivity)", value=False, key="surrogate")
with inc[2]:
    st.markdown("Inorganics")
    inc_co = st.checkbox("CO", value=True, key="inc_co")
    inc_noy = [sp for sp in NOY_SPECIES
               if st.checkbox(sp.upper(), value=True, key=f"noy_{sp}")]
    no2_surrogate = st.checkbox("⤷ NO₂ surrogate for NO (nighttime)", value=False,
                                key="no2_surrogate")
    inc_o3 = st.checkbox("O₃ (from generator)", value=False, key="inc_o3")

# --- compute the scenario --------------------------------------------------- #
if active_solutions or active_gases:
    res = planner.inverse_voc(total_voc, active_solutions=tuple(active_solutions),
                              active_gases=tuple(active_gases))
else:
    st.warning("No VOC solution or gas selected — pick at least one.")
    res = {"total_voc_ppb": 0.0, "per_solution": pd.DataFrame(),
           "gases": pd.DataFrame(columns=["key", "compound", "ppb"]),
           "components": pd.DataFrame()}
co_ppb = planner.co_from_voc(total_voc)["co_ppb"] if inc_co else 0.0
noy_total = total_voc * planner.noy_voc_ratio(mce)
spec = planner.noy_params["noy_speciation"]
noy_ppb = {sp: noy_total * spec[sp] for sp in inc_noy}
# Nighttime: NO + O3 -> NO2, so inject the NO fraction directly as NO2 (1:1 mole).
if no2_surrogate and "no" in noy_ppb:
    no_folded = noy_ppb.pop("no")
    noy_ppb["no2"] = noy_ppb.get("no2", 0.0) + no_folded
    st.info(f"NO₂ surrogate ON (nighttime): NO ({no_folded:.1f} ppb) injected as NO₂ "
            f"→ NO₂ = {noy_ppb['no2']:.1f} ppb. Total NOy unchanged; pair with O₃ for "
            f"NO₃ chemistry.")


# Build ppb and mass (mg) slices for both pies. Mass uses m = ppb·1e-9·n_air·MW.
inorg_mw = dict(zip(planner.bottles["key"], planner.bottles["MW_g_per_mol"]))
voc_mw = dict(zip(planner.voc["key"], planner.voc["MW_g_per_mol"]))


def mg_from_ppb(ppb, mw):
    return planner.chamber.mass_from_ppb(ppb, mw) * 1e3   # grams -> mg


comp = res["components"]
# Gas-VOC representation: either the individual gases, or one reactivity-matched
# propene slice if the surrogate option is on.
gas_ppb_map = {r["key"]: r["ppb"] for _, r in res["gases"].iterrows()}
gas_mass_map = ({r["key"]: r["mass_mg"] for _, r in comp[comp["role"] == "gas"].iterrows()}
                if not comp.empty else {})
compound_of = dict(zip(planner.voc["key"], planner.voc["compound"]))
if surrogate and "acetylene" in gas_ppb_map:
    # fold ONLY acetylene into propene; ethene (and any other gas) stay real
    sub = {g: gas_ppb_map[g] for g in ("propene", "acetylene") if g in gas_ppb_map}
    equiv = planner.propene_surrogate_ppb(sub)
    gas_voc_ppb = [("Propene (surrogate)", equiv)]
    gas_voc_mass = [("Propene (surrogate)", mg_from_ppb(equiv, voc_mw["propene"]))]
    gas_inject = {"propene": equiv}
    for g, ppb in gas_ppb_map.items():
        if g in ("propene", "acetylene"):
            continue
        gas_voc_ppb.append((compound_of[g], ppb))
        gas_voc_mass.append((compound_of[g], gas_mass_map.get(g, 0.0)))
        gas_inject[g] = ppb
else:
    gas_voc_ppb = [(r["compound"], r["ppb"]) for _, r in res["gases"].iterrows()]
    gas_voc_mass = [(r["compound"], gas_mass_map.get(r["key"], 0.0))
                    for _, r in res["gases"].iterrows()]
    gas_inject = dict(gas_ppb_map)

voc_ppb = [(f"Sol {r['solution']}", r["sum_ppb"]) for _, r in res["per_solution"].iterrows()]
voc_ppb += gas_voc_ppb
voc_mass = [(f"Sol {r['solution']}", r["voc_mass_mg"]) for _, r in res["per_solution"].iterrows()]
voc_mass += gas_voc_mass

voc_mass_total = sum(v for _, v in voc_mass)
em_ppb = [("NMOG", res["total_voc_ppb"])]
em_mass = [("NMOG", voc_mass_total)]
if co_ppb > 0:
    em_ppb.append(("CO", co_ppb))
    em_mass.append(("CO", mg_from_ppb(co_ppb, inorg_mw.get("co", 28.01))))
if noy_ppb:
    em_ppb.append(("NOy", sum(noy_ppb.values())))
    em_mass.append(("NOy", sum(mg_from_ppb(v, inorg_mw.get(sp, 30.0))
                               for sp, v in noy_ppb.items())))


def pie(slices, title, startangle=90):
    if slices and sum(v for _, v in slices) > 0:
        labels = [s[0] for s in slices]
        fig, _ = styled_pie(labels, [s[1] for s in slices], title=title,
                            colors=colors_for(labels), label_fontsize=12,
                            title_fontsize=14, figsize=(7, 5), startangle=startangle)
        st.pyplot(fig)


pcols = st.columns(2)
with pcols[0]:
    # start at the right so the small gas-VOC slices spread down the right edge
    pie(voc_ppb, "VOC composition (ppb)", startangle=0)
    pie(voc_mass, "VOC composition (mass, mg)", startangle=0)
    st.caption("Total VOC distributed across included solutions + gas VOCs by the "
               "fingerprint mass fractions. The mass pie matches the Excel mass basis.")
with pcols[1]:
    pie(em_ppb, "Total emissions (ppb)")
    pie(em_mass, "Total emissions (mass, mg)")
    m1, m2, m3 = st.columns(3)
    m1.metric("VOC (ppb)", f"{res['total_voc_ppb']:.0f}")
    m2.metric("CO (ppb)", f"{co_ppb:.0f}")
    m3.metric("NOy (ppb)", f"{sum(noy_ppb.values()):.1f}")

# ----- per-compound species table with ppbC + OH reactivity ----------------- #
_SOL_GROUP = {s: f"Solution {s} — {SOLUTION_NAMES[s]}" for s in "ABCD"}
_koh = dict(zip(planner.voc["key"], planner.voc["k_oh_298"]))
_carbon = {k: carbon_count(f) for k, f in zip(planner.compounds["key"], planner.compounds["formula"])}
# OH rate constants for the injected inorganics (cm3 molec-1 s-1, ~1 atm).
INORG_KOH = {"co": 2.3e-13, "no": 9.8e-12, "no2": 1.1e-11, "hono": 0.0}

_rows = []
for _, r in res["components"].iterrows():
    if r["role"] in ("A", "B", "C", "D"):
        _rows.append({"compound": r["compound"], "group": _SOL_GROUP[r["role"]],
                      "cat": f"Sol {r['role']}", "MW_g_per_mol": r["MW_g_per_mol"],
                      "ppb": r["ppb"], "carbon": _carbon.get(r["key"], 0),
                      "k_oh": float(_koh.get(r["key"]) or 0), "note": ""})
for gkey, ppb in gas_inject.items():
    note = ("incl. acetylene reactivity"
            if surrogate and gkey == "propene" and "acetylene" in gas_ppb_map else "")
    _rows.append({"compound": compound_of.get(gkey, gkey), "group": "Gas-phase VOC",
                  "cat": "Gas VOC", "MW_g_per_mol": voc_mw.get(gkey), "ppb": ppb,
                  "carbon": _carbon.get(gkey, 0), "k_oh": float(_koh.get(gkey) or 0), "note": note})
if co_ppb > 0:
    _rows.append({"compound": "CO", "group": "Inorganic", "cat": "CO",
                  "MW_g_per_mol": inorg_mw.get("co", 28.01), "ppb": co_ppb,
                  "carbon": 0, "k_oh": INORG_KOH["co"], "note": "Fig 7b"})
for sp, ppb in noy_ppb.items():
    _rows.append({"compound": sp.upper(), "group": "Inorganic (NOy)", "cat": "NOx",
                  "MW_g_per_mol": inorg_mw.get(sp), "ppb": ppb, "carbon": 0,
                  "k_oh": INORG_KOH.get(sp, 0.0),
                  "note": "by other team" if sp == "hono" else ""})
species_df = pd.DataFrame(_rows)
species_df["ppbC"] = species_df["ppb"] * species_df["carbon"]
species_df["OH_reactivity_s-1"] = [
    planner.chamber.oh_reactivity(p, k) for p, k in zip(species_df["ppb"], species_df["k_oh"])]

st.subheader("Carbon (ppbC) and OH reactivity")
rcols = st.columns(2)
with rcols[0]:
    ppbc_by = species_df.groupby("cat")["ppbC"].sum()
    ppbc_by = ppbc_by[ppbc_by > 0]
    pie(list(zip(ppbc_by.index, ppbc_by.values)), "ppbC by mixture", startangle=0)
with rcols[1]:
    koh_by = species_df.groupby("cat")["OH_reactivity_s-1"].sum()
    koh_by = koh_by[koh_by > 0]
    pie(list(zip(koh_by.index, koh_by.values)), "OH reactivity by category (1/s)", startangle=0)
k1, k2 = st.columns(2)
k1.metric("Total ppbC", f"{species_df['ppbC'].sum():.0f}")
k2.metric("Total OH reactivity (s⁻¹)", f"{species_df['OH_reactivity_s-1'].sum():.1f}")

with st.expander("📐 Equations — ppbC and OH reactivity (🆕)"):
    st.markdown("**ppbC** — carbon-weighted mixing ratio (NMOG only; $n_{C,i}$ = "
                "carbon number from the formula):")
    st.latex(r"\mathrm{ppbC} = \sum_i \mathrm{ppb}_i \times n_{C,i}")
    st.markdown("**OH reactivity** — summed over every OH sink (the VOCs **plus CO, NO, "
                "NO₂**), using the number density $M$:")
    st.latex(r"k_\mathrm{OH}^\mathrm{tot} = \sum_i k_{\mathrm{OH},i}\,[X_i]"
             r" = \sum_i k_{\mathrm{OH},i}\,\mathrm{ppb}_i\times10^{-9}\times M"
             r"\qquad M = \frac{P}{k_B\,T}")
    st.caption(f"M = {planner.chamber.number_density:.3e} molec/cm³ (T = {T:.2f} K).  "
               "k(OH) per compound from R. Wegener's reactivity calc — eucalyptol from "
               "literature 1,8-cineole; acetonitrile corrected to 2.2e-14 cm³/s "
               "(his file's 3.0e-11 looks like a typo). Validated against his "
               "per-mixture totals to ~1%.")
st.caption("OH reactivity uses Robert's k(OH) per compound (CO/NO/NO₂ included). "
           "ppbC = ppb × carbon number (NMOG only).")

# ===== 2 · Injection plan =================================================== #
st.header("2 · Injection plan")

st.markdown("**Prepared mixtures** — how much to inject (volume includes water "
            "carried in by aqueous reagents).")
ps = res["per_solution"]
if not ps.empty:
    cols_show = ["solution", "mixture", "inject_volume_uL", "voc_mass_mg",
                 "water_mass_mg", "density_g_per_mL", "sum_ppb"]
    st.dataframe(fmt(ps[cols_show].rename(columns={
        "inject_volume_uL": "inject µL", "voc_mass_mg": "VOC mg",
        "water_mass_mg": "water mg", "density_g_per_mL": "ρ g/mL",
        "sum_ppb": "Σ ppb"})), hide_index=True)

with st.expander("📐 Equations — mixture injection (for verification)"):
    st.latex(r"n_\mathrm{air} = \frac{P\,V}{R\,T}"
             r"\qquad\Rightarrow\qquad n_\mathrm{air} = "
             f"{planner.chamber.n_air:,.0f}\\ \\mathrm{{mol}}")
    st.markdown("Chamber mixing ratio of compound $i$ from its injected mass:")
    st.latex(r"\mathrm{ppb}_i = \frac{m_i / M_i}{n_\mathrm{air}}\times 10^{9}")
    st.markdown("The total VOC target is met by scaling every mass by one factor "
                r"$K$: $\;m_i = K\,w_i\;$ ($w_i$ = fingerprint mass fraction), with "
                r"$K$ chosen so $\sum_i \mathrm{ppb}_i = \mathrm{VOC}_\mathrm{target}$.")
    st.markdown("Injected liquid volume and water carried in by aqueous reagents "
                r"(active fraction $c_i$; 1 for neat, 0.40 for methylglyoxal 40% aq):")
    st.latex(r"V_\mathrm{inject} = \sum_i \frac{m_i}{c_i\,\rho_i}"
             r"\qquad m_\mathrm{water} = \sum_i m_i\,\frac{1-c_i}{c_i}")
    st.caption("m_i = pure VOC mass, M_i = molar mass, ρ_i = reagent density, "
               "c_i = reagent active fraction, R = 8.314 J mol⁻¹ K⁻¹.")
    st.caption(f"Current chamber values (set in the sidebar):  V = {V:,.1f} m³,  "
               f"T = {T:,.2f} K,  P = {P:,.0f} Pa  →  "
               f"n_air = {planner.chamber.n_air:,.0f} mol.")

st.markdown("**Gas-phase injections** — fill in the cylinder + method details; the "
            "planner computes how many injections (volume method) or how many "
            "minutes (MFC) are needed to reach each species' target.")

# Per-species target ppb from the current scenario (gas_inject already folds in
# the propene surrogate if that option is on).
target_by_key = dict(gas_inject)
if co_ppb > 0:
    target_by_key["co"] = co_ppb
target_by_key.update(noy_ppb)
if surrogate and "acetylene" in gas_ppb_map:
    st.info(f"Propene surrogate ON: acetylene folded into propene at "
            f"**{gas_inject['propene']:.1f} ppb** (matches its OH reactivity; "
            f"weight k_acet/k_prop = 0.03). Ethene is injected separately.")

tcol1, tcol2 = st.columns([1, 2])
with tcol1:
    target_inj_s = st.number_input("Target MFC time (s)", value=45.0, min_value=10.0,
                                   max_value=120.0, step=5.0,
                                   help="The planner auto-picks the MFC + setpoint so "
                                        "each MFC injection lands near this time (30–60 s).")
st.markdown("##### ⬇ Input table — fill bottle ppm + MFC correction factor "
            "(delivered flow = air setpoint × factor; ≈1 for dilute mixtures, "
            "differs for pure/concentrated gas)")
gas_inputs = st.data_editor(
    pd.DataFrame({
        "species": [GAS_LABEL[k] for k in GAS_TABLE_KEYS],
        "bottle ppm": [GAS_DEFAULTS[k][0] for k in GAS_TABLE_KEYS],
        "MFC corr.": [GAS_CORR.get(k, 1.0) for k in GAS_TABLE_KEYS],
        "method": ["MFC"] * len(GAS_TABLE_KEYS),
        "loop volume mL": ["—"] * len(GAS_TABLE_KEYS),
    }),
    key="gas_inputs", hide_index=True, disabled=["species"],
    column_config={
        "method": st.column_config.SelectboxColumn(
            options=["MFC", "volume injection"], required=True),
        "loop volume mL": st.column_config.SelectboxColumn(
            options=["—", "0.32", "3.2"], required=True,
            help="Only for volume injection."),
    },
)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


# Auto-size the MFC + setpoint (or compute volume injections) per included species.
rows = []
for k, (_, r) in zip(GAS_TABLE_KEYS, gas_inputs.iterrows()):
    tgt = target_by_key.get(k, 0.0)
    if tgt <= 0:
        continue
    conc = float(r["bottle ppm"] or 0)
    corr = _num(r["MFC corr."]) or 1.0
    if r["method"] == "MFC":
        s = planner.size_mfc(tgt, conc, corr=corr, target_minutes=target_inj_s / 60.0)
        if s:
            rows.append({"species": r["species"], "target ppb": tgt, "method": "MFC",
                         "MFC (LPM)": s["mfc_LPM"], "setpoint %": s["setpoint_pct"],
                         "gas flow (sccm)": s["gas_flow_sccm"], "ppb/min": s["ppb_per_min"],
                         "time (s)": s["time_s"], "ppb/inj": None, "# inj": None})
    else:
        vol = _num(r["loop volume mL"])
        ppb_inj = planner.gas_ppb_from_dosing(conc, method="fixed_volume", volume_mL=vol)
        n = math.ceil(tgt / ppb_inj) if ppb_inj > 0 else math.nan
        rows.append({"species": r["species"], "target ppb": tgt, "method": "volume injection",
                     "MFC (LPM)": None, "setpoint %": None, "gas flow (sccm)": None,
                     "ppb/min": None, "time (s)": None, "ppb/inj": ppb_inj, "# inj": n})
st.markdown("##### ⬆ Output — auto-sized MFC + setpoint (≈ target time), or volume injections")
gas_plan = pd.DataFrame(rows)
if not gas_plan.empty:
    st.dataframe(fmt(gas_plan, 2), hide_index=True)
    mfc_rows = gas_plan[gas_plan["method"] == "MFC"]
    fixed20 = mfc_rows[mfc_rows["MFC (LPM)"] == 20.0]
    if not fixed20.empty:
        st.caption("⚠️ The 20 LPM MFC is constrained to a **fixed 40% setpoint** "
                   f"({', '.join(fixed20['species'])}); its injection time follows from "
                   "that, not the target. Update `MFC_FIXED_SETPOINT` in "
                   "injection_model.py when this constraint changes.")
    floored = mfc_rows[(mfc_rows["MFC (LPM)"] != 20.0) & (mfc_rows["setpoint %"] <= 10.01)]
    if not floored.empty:
        st.caption("Setpoint is floored at 10% (MFC accuracy limit), so "
                   f"{', '.join(floored['species'])} inject faster than the target "
                   "time — use a more dilute cylinder to lengthen it.")
else:
    st.caption("No gas-phase species included in the scenario.")

with st.expander("📐 Equations — gas-phase injection (for verification)"):
    st.markdown("**Volume injection** — a fixed volume $V$ of cylinder gas at "
                "concentration $C$ (ppm), at fill conditions $T,P$:")
    st.latex(r"\mathrm{ppb/injection} = "
             r"\frac{\big(P\,V/(R\,T)\big)\,\cdot\,C\times10^{-6}}{n_\mathrm{air}}\times 10^{9}")
    st.latex(r"N_\mathrm{injections} = "
             r"\left\lceil \frac{\mathrm{target\ ppb}}{\mathrm{ppb/injection}}\right\rceil")
    st.markdown(r"**MFC** — air setpoint $S$ (LPM) with gas-correction factor $f$, so "
                r"the delivered gas flow is $F = S\cdot f$ at concentration $C$:")
    st.latex(r"r_\mathrm{ppb/min} = \frac{\big(P\,(S f\cdot10^{-3})/(R\,T)\big)\,C\times10^{-6}}"
             r"{n_\mathrm{air}}\times 10^{9}\qquad "
             r"t = \frac{\mathrm{target\ ppb}}{r}")
    st.markdown("The planner inverts this: it picks the smallest MFC (0.5/5/20 LPM) "
                "and the setpoint % (floored at 10%) so that **t ≈ the target time**.")
    st.markdown("---")
    st.markdown("**🆕 New — corrections & adjustments**")
    st.markdown("• **MFC air-calibration factor $f$** — MFCs read in air units, so the "
                "real gas flow is $S\\cdot f$ (e.g. CO 0.963, ethene 1.022; from the "
                "SAPHIR LCU). Editable per gas in the input table.")
    st.markdown("• **Auto-sizing** — smallest MFC + setpoint (≥10%) chosen so the time "
                "matches your target. *Constraint: the 20 LPM MFC is fixed at 40% "
                "(hardware limit) — its time follows from that.*")
    st.markdown("• **Propene surrogate** (acetylene → propene, OH-reactivity-matched):")
    st.latex(r"\mathrm{ppb}_\mathrm{propene}\;\mathrel{+}=\;"
             r"\frac{k_\mathrm{OH}^\mathrm{acetylene}}{k_\mathrm{OH}^\mathrm{propene}}\,"
             r"\mathrm{ppb}_\mathrm{acetylene}")
    st.markdown("• **NO₂ surrogate** (nighttime, NO + O₃ → NO₂, mole-for-mole):")
    st.latex(r"\mathrm{ppb}_{\mathrm{NO_2}}\;\mathrel{+}=\;\mathrm{ppb}_{\mathrm{NO}}")
    st.markdown("⚠️ **Reference-temperature caveat** — flow volumes are referenced at "
                f"the MFC standard ({planner.sccm_ref_T:.2f} K); the SAPHIR LCU uses "
                "~298 K, a ~9% difference, pending confirmation of the MFC reference.")
    st.caption(f"f, C (bottle ppm; pure = 1,000,000) and the target time come from the "
               f"input table. V (loop 0.32/3.2 mL) applies only to volume injection. "
               f"Fill conditions T = {planner.fill_T:.2f} K, P = {planner.fill_P:,.0f} Pa; "
               f"n_air = {planner.chamber.n_air:,.0f} mol "
               f"(V = {V:,.1f} m³, T = {T:,.2f} K, P = {P:,.0f} Pa).")

# HONO — injected by a different team; we only report the target ppb.
if noy_ppb.get("hono", 0) > 0:
    st.markdown(f"**HONO** — target **{noy_ppb['hono']:.1f} ppb** "
                f"(10% of NOy). Injected by the other team; communicate this "
                f"target to them (not planned here).")

# O3 — from the ozone generator (not a cylinder).
o3_target = 0.0
if inc_o3:
    st.markdown("**O₃ — from the ozone generator**")
    oc1, oc2 = st.columns(2)
    o3_target = oc1.number_input("O₃ target (ppb)", value=50.0, min_value=0.0, step=10.0,
                                 help="Oxidant level — your experimental choice, "
                                      "not from the VOC/MCE parameterization.")
    o3_rate = oc2.number_input("Generator output (ppb/min)", value=10.0, min_value=0.0,
                               step=1.0, help="Measured O3 rise rate while the "
                                              "generator runs (from your O3 monitor).")
    if o3_rate > 0:
        st.caption(f"Run the O₃ generator for **{o3_target / o3_rate:.1f} min** "
                   f"at {o3_rate:.0f} ppb/min to reach {o3_target:.0f} ppb.")

# ===== 3 · Rough campaign estimate ========================================== #
st.header("3 · Rough campaign estimate")
ec1, ec2 = st.columns([1, 2])
with ec1:
    n_exp = st.number_input("Number of experiments", value=15, min_value=1, step=1)
    safety = st.number_input("Safety factor (dead volume, repeats, losses)",
                             value=1.5, min_value=1.0, step=0.1)
st.caption(f"Per-experiment amounts for the current scenario × {n_exp} experiments "
           f"× {safety:g} safety factor.")
if not ps.empty:
    est = ps[["solution", "mixture", "inject_volume_uL", "sum_ppb"]].copy()
    est["per-exp µL"] = est["inject_volume_uL"]
    est["total µL"] = est["inject_volume_uL"] * n_exp * safety
    est["total mL"] = est["total µL"] / 1000.0
    est = est.rename(columns={"sum_ppb": "per-exp Σppb"})
    st.dataframe(fmt(est[["solution", "mixture", "per-exp µL", "per-exp Σppb",
                          "total µL", "total mL"]], 2), hide_index=True)
    grand_mL = est["total mL"].sum()
    e1, e2 = st.columns(2)
    e1.metric("Total liquid across mixtures (mL)", f"{grand_mL:.1f}")
    e2.metric("Largest single mixture (mL)", f"{est['total mL'].max():.1f}")

    st.markdown("**Gas-phase consumption (ppb)**")
    gas_est = pd.DataFrame(
        [{"species": GAS_LABEL[k], "per-exp ppb": target_by_key[k],
          "total ppb": target_by_key[k] * n_exp * safety}
         for k in GAS_TABLE_KEYS if target_by_key.get(k, 0) > 0])
    if not gas_est.empty:
        st.dataframe(fmt(gas_est, 2), hide_index=True)
    st.caption("Liquid totals size the solution prep; gas-phase cylinder volumes "
               "(mL) will be added once bottle concentrations are set.")

# ===== Export =============================================================== #
st.header("Export")

# (1) Expected ppb + ppbC + OH reactivity per compound (from species_df, which
# already reflects the included items, propene surrogate, regime CO/NOy).
expected_ppb_df = species_df[["compound", "group", "MW_g_per_mol", "ppb", "carbon",
                              "ppbC", "OH_reactivity_s-1", "note"]].rename(
    columns={"ppb": "expected_ppb"})
if inc_o3 and o3_target > 0:
    expected_ppb_df = pd.concat([expected_ppb_df, pd.DataFrame([{
        "compound": "O3", "group": "Oxidant (generator)", "MW_g_per_mol": 48.0,
        "expected_ppb": o3_target, "carbon": 0, "ppbC": 0.0,
        "OH_reactivity_s-1": 0.0, "note": "from O3 generator"}])], ignore_index=True)

# Per-mixture totals (ppb, ppbC, OH reactivity) for the export.
mixture_totals = species_df.groupby("group", as_index=False).agg(
    ppb=("ppb", "sum"), ppbC=("ppbC", "sum"),
    OH_reactivity_s1=("OH_reactivity_s-1", "sum"))

# (2) µL injected per prepared mixture.
mixtures_uL = res["per_solution"][[
    "solution", "mixture", "inject_volume_uL", "voc_mass_mg", "water_mass_mg",
    "density_g_per_mL", "sum_ppb"]].rename(columns={
        "inject_volume_uL": "inject_uL", "voc_mass_mg": "VOC_mg",
        "water_mass_mg": "water_mg", "density_g_per_mL": "density_g_per_mL",
        "sum_ppb": "solution_sum_ppb"})

st.markdown("**Expected chamber concentration per compound**")
st.dataframe(fmt(expected_ppb_df, 3), hide_index=True)
st.caption("Gas-phase ppb carry a ~9% reference-temperature caveat vs the SAPHIR "
           "LCU (0 °C vs ~25 °C) until we align the MFC reference.")

buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as xls:
    expected_ppb_df.to_excel(xls, sheet_name="expected_ppb", index=False)
    mixture_totals.to_excel(xls, sheet_name="mixture_totals", index=False)
    mixtures_uL.to_excel(xls, sheet_name="mixtures_uL", index=False)
    if not gas_plan.empty:
        gas_plan.to_excel(xls, sheet_name="gas_phase_plan", index=False)
    if not ps.empty:
        est.to_excel(xls, sheet_name="campaign_estimate", index=False)
        if not gas_est.empty:
            gas_est.to_excel(xls, sheet_name="campaign_gas_ppb", index=False)
    pd.DataFrame([{"regime": regime, "mce": mce, "total_voc_ppb": total_voc,
                   "co_ppb": co_ppb, "noy_ppb": sum(noy_ppb.values()),
                   "o3_ppb": o3_target, "total_ppbC": species_df["ppbC"].sum(),
                   "total_OH_reactivity_s1": species_df["OH_reactivity_s-1"].sum(),
                   "n_air_mol": planner.chamber.n_air,
                   "volume_m3": V, "T_K": T, "P_Pa": P}]).to_excel(
        xls, sheet_name="summary", index=False)
st.download_button("⬇ Download injection plan (Excel)", buf.getvalue(),
                   file_name="saphfire_injection_plan.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
