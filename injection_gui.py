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

from injection_model import SOLUTION_NAMES, Chamber, load_planner

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

from saphfire_plots import styled_pie  # noqa: E402  (after set_page_config)

LIGHT_GASES = ["propene", "ethene", "acetylene"]
NOY_SPECIES = ["no", "no2", "hono"]
NITROGEN = {"no", "no2", "hono"}
ALL_GAS = LIGHT_GASES + ["co"] + NOY_SPECIES
GAS_LABEL = {"propene": "Propene", "ethene": "Ethene", "acetylene": "Acetylene",
             "co": "CO", "no": "NO", "no2": "NO2", "hono": "HONO"}


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
    surrogate = st.checkbox("⤷ propene surrogate for ethene + acetylene "
                            "(match OH reactivity)", value=False, key="surrogate")
with inc[2]:
    st.markdown("Inorganics")
    inc_co = st.checkbox("CO", value=True, key="inc_co")
    inc_noy = [sp for sp in NOY_SPECIES
               if st.checkbox(sp.upper(), value=True, key=f"noy_{sp}")]

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
if surrogate and gas_ppb_map:
    equiv = planner.propene_surrogate_ppb(gas_ppb_map)
    gas_voc_ppb = [("Propene (surrogate)", equiv)]
    gas_voc_mass = [("Propene (surrogate)", mg_from_ppb(equiv, voc_mw["propene"]))]
    gas_inject = {"propene": equiv}            # only propene is injected
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
        fig, _ = styled_pie([s[0] for s in slices], [s[1] for s in slices],
                            title=title, label_fontsize=12, title_fontsize=14,
                            figsize=(7, 5), startangle=startangle)
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
if surrogate and gas_ppb_map:
    st.info(f"Propene surrogate ON: ethene + acetylene folded into propene at "
            f"**{gas_inject['propene']:.1f} ppb** (matches the OH reactivity of the "
            f"three gases; weights k_eth/k_prop=0.32, k_acet/k_prop=0.03).")

st.markdown("##### ⬇ Input table — you fill in (bottle ppm; pure = 1,000,000. "
            "Volume injection loop = 0.32 or 3.2 mL; MFC max flow = 0.5/5/20 LPM)")
# Editable input table (all gas-phase species; edits persist across reruns).
gas_inputs = st.data_editor(
    pd.DataFrame({
        "species": [GAS_LABEL[k] for k in ALL_GAS],
        "bottle ppm": [1_000_000.0] * len(ALL_GAS),     # default: pure
        "method": ["volume injection"] * len(ALL_GAS),
        "loop volume mL": ["3.2"] * len(ALL_GAS),
        "MFC flow LPM": ["—"] * len(ALL_GAS),            # off by default (volume method)
    }),
    key="gas_inputs", hide_index=True, disabled=["species"],
    column_config={
        "method": st.column_config.SelectboxColumn(
            options=["volume injection", "MFC"], required=True),
        "loop volume mL": st.column_config.SelectboxColumn(
            options=["—", "0.32", "3.2"], required=True,
            help="Set to — if this species uses an MFC."),
        "MFC flow LPM": st.column_config.SelectboxColumn(
            options=["—", "0.5", "5", "20"], required=True,
            help="Set to — if this species uses volume injection."),
    },
)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


# Compute injections / minutes for the included species (target > 0).
rows = []
for k, (_, r) in zip(ALL_GAS, gas_inputs.iterrows()):
    tgt = target_by_key.get(k, 0.0)
    if tgt <= 0:
        continue
    conc = float(r["bottle ppm"] or 0)
    if r["method"] == "MFC":
        flow = _num(r["MFC flow LPM"])
        rate = planner.gas_ppb_from_dosing(conc, method="flow_time",
                                           flow_sccm=flow * 1000.0, minutes=1.0)
        rows.append({"species": r["species"], "target ppb": tgt, "method": "MFC",
                     "ppb/injection": None, "# injections": None,
                     "ppb/min": rate, "minutes (MFC)": tgt / rate if rate > 0 else math.nan})
    else:
        vol = _num(r["loop volume mL"])
        ppb_inj = planner.gas_ppb_from_dosing(conc, method="fixed_volume", volume_mL=vol)
        n = math.ceil(tgt / ppb_inj) if ppb_inj > 0 else math.nan
        rows.append({"species": r["species"], "target ppb": tgt,
                     "method": "volume injection", "ppb/injection": ppb_inj,
                     "# injections": n, "ppb/min": None, "minutes (MFC)": None})
st.markdown("##### ⬆ Output table — computed plan (# injections or minutes per species)")
gas_plan = pd.DataFrame(rows)
if not gas_plan.empty:
    st.dataframe(fmt(gas_plan, 3), hide_index=True)
else:
    st.caption("No gas-phase species included in the scenario.")

with st.expander("📐 Equations — gas-phase injection (for verification)"):
    st.markdown("**Volume injection** — a fixed volume $V$ of cylinder gas at "
                "concentration $C$ (ppm), at fill conditions $T,P$:")
    st.latex(r"\mathrm{ppb/injection} = "
             r"\frac{\big(P\,V/(R\,T)\big)\,\cdot\,C\times10^{-6}}{n_\mathrm{air}}\times 10^{9}")
    st.latex(r"N_\mathrm{injections} = "
             r"\left\lceil \frac{\mathrm{target\ ppb}}{\mathrm{ppb/injection}}\right\rceil")
    st.markdown(r"**MFC** — flow $F$ (LPM) of cylinder gas at concentration $C$:")
    st.latex(r"r_\mathrm{ppb/min} = \frac{\big(P\,(F\cdot10^{-3})/(R\,T)\big)\,C\times10^{-6}}"
             r"{n_\mathrm{air}}\times 10^{9}\qquad "
             r"t_\mathrm{minutes} = \frac{\mathrm{target\ ppb}}{r}")
    st.caption("V (loop 0.32/3.2 mL), F (MFC flow 0.5/5/20 LPM) and C (bottle ppm; "
               "pure = 1,000,000) come from the input table above.")
    st.caption(f"Injected-gas fill conditions:  T = {planner.fill_T:.2f} K,  "
               f"P = {planner.fill_P:,.0f} Pa (room).   "
               f"n_air from the chamber (sidebar):  V = {V:,.1f} m³,  T = {T:,.2f} K,  "
               f"P = {P:,.0f} Pa  →  {planner.chamber.n_air:,.0f} mol.")

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
         for k in ALL_GAS if target_by_key.get(k, 0) > 0])
    if not gas_est.empty:
        st.dataframe(fmt(gas_est, 2), hide_index=True)
    st.caption("Liquid totals size the solution prep; gas-phase cylinder volumes "
               "(mL) will be added once bottle concentrations are set.")

# ===== Export =============================================================== #
st.header("Export")
st.caption("Mixtures are finalized; gas-phase injection export will be completed "
           "once the bottle / MFC / volume-injection details are provided.")
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as xls:
    ps.to_excel(xls, sheet_name="mixtures", index=False)
    res["components"].to_excel(xls, sheet_name="voc_components", index=False)
    if not gas_plan.empty:
        gas_plan.to_excel(xls, sheet_name="gas_phase_provisional", index=False)
    if not ps.empty:
        est.to_excel(xls, sheet_name="campaign_estimate", index=False)
        if not gas_est.empty:
            gas_est.to_excel(xls, sheet_name="campaign_gas_ppb", index=False)
    pd.DataFrame([{"regime": regime, "mce": mce, "total_voc_ppb": total_voc,
                   "co_ppb": co_ppb, "noy_ppb": sum(noy_ppb.values()),
                   "n_air_mol": planner.chamber.n_air}]).to_excel(
        xls, sheet_name="summary", index=False)
st.download_button("⬇ Download injection plan (Excel)", buf.getvalue(),
                   file_name="saphfire_injection_plan.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
