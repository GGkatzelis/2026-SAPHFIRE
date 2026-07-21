"""Biogenic mixture — injection volumes and SOA prediction.

Given a target **total biogenic VOC mixing ratio** (ppb) in SAPHIR, compute the
neat-liquid microlitres of each component to inject, and — assuming a lumped SOA
mass yield — the predicted secondary organic aerosol mass concentration (µg/m³).

Composition = the Australian forest mix (Max's email), given as **mass % of the
total biogenic VOC**:

    Isoprene 32 · 1,8-cineole 22 · α-pinene 18 · d-limonene 14 · β-pinene 10 · β-caryophyllene 4

Because the split is by mass, each compound's mixing ratio follows mass_i / MW_i,
so the low-MW isoprene dominates the ppb even at 32 % by mass.

This is a standalone scenario (not part of the A–D injection fingerprint); the
component properties live here so it stays decoupled from the campaign config.
"""
from __future__ import annotations

import pandas as pd

from injection_model import Chamber

# key: (display name, formula, MW g/mol, density g/mL, mass % of total biogenic VOC)
BIOGENIC = {
    "isoprene":      ("Isoprene",           "C5H8",   68.119, 0.681,  32.0),
    "cineole":       ("1,8-cineole",        "C10H18O", 154.253, 0.9225, 22.0),
    "a_pinene":      ("α-pinene",           "C10H16", 136.238, 0.858,  18.0),
    "d_limonene":    ("d-limonene",         "C10H16", 136.234, 0.8411, 14.0),
    "b_pinene":      ("β-pinene",           "C10H16", 136.238, 0.872,  10.0),
    "caryophyllene": ("β-caryophyllene",    "C15H24", 204.357, 0.9052,  4.0),
}


def biogenic_plan(total_voc_ppb: float, chamber: Chamber | None = None,
                  mass_yield: float = 0.30, composition: dict = BIOGENIC) -> dict:
    """Injection volumes + SOA for a biogenic mix scaled to a total VOC ppb.

    Parameters
    ----------
    total_voc_ppb : target sum of the component mixing ratios in the chamber.
    chamber       : SAPHIR chamber (defaults to 270 m³, 298.15 K, 1 atm).
    mass_yield    : lumped SOA mass yield (SOA mass / reacted VOC mass), default 0.30,
                    applied assuming the injected VOC is fully oxidised.
    composition   : {key: (name, formula, MW, density, mass_pct)}.

    Returns a dict with a per-compound DataFrame and scenario totals.
    """
    ch = chamber or Chamber()
    total_pct = sum(v[4] for v in composition.values())
    fracs = {k: v[4] / total_pct for k, v in composition.items()}  # mass fractions (renormalised)

    # total_voc_ppb = (M_total / n_air · 1e9) · Σ(f_i / MW_i)   ->   solve for M_total (g)
    s = sum(fracs[k] / composition[k][2] for k in composition)
    m_total_g = total_voc_ppb * ch.n_air * 1e-9 / s

    rows = []
    for k, (name, formula, mw, dens, pct) in composition.items():
        mass_g = fracs[k] * m_total_g
        ppb_i = ch.ppb_from_mass(mass_g, mw)
        uL = mass_g / dens * 1e3            # g / (g/mL) = mL → µL
        rows.append({"compound": name, "formula": formula, "MW_g_per_mol": mw,
                     "density_g_per_mL": dens, "mass_pct": pct,
                     "ppb": ppb_i, "mass_mg": mass_g * 1e3, "inject_uL": uL})
    df = pd.DataFrame(rows)

    voc_ugm3 = m_total_g * 1e6 / ch.volume_m3          # total injected VOC mass conc
    soa_ugm3 = mass_yield * voc_ugm3
    # isoprene makes very little SOA in reality — also report the terpene-only estimate
    iso_ugm3 = df.loc[df["compound"] == "Isoprene", "mass_mg"].sum() * 1e3 / ch.volume_m3
    soa_excl_isoprene = mass_yield * (voc_ugm3 - iso_ugm3)

    return {
        "per_compound": df,
        "total_voc_ppb": float(df["ppb"].sum()),
        "total_inject_uL": float(df["inject_uL"].sum()),
        "total_mass_mg": float(df["mass_mg"].sum()),
        "voc_ugm3": voc_ugm3,
        "mass_yield": mass_yield,
        "soa_ugm3": soa_ugm3,
        "soa_ugm3_excl_isoprene": soa_excl_isoprene,
        "chamber": ch,
    }


def _fmt(res: dict) -> str:
    df = res["per_compound"].copy()
    df = df[["compound", "mass_pct", "ppb", "mass_mg", "inject_uL"]]
    df.columns = ["compound", "mass %", "ppb", "mass (mg)", "inject (µL)"]
    lines = [df.to_string(index=False, float_format=lambda x: f"{x:.3f}")]
    lines.append("")
    lines.append(f"  Total VOC              : {res['total_voc_ppb']:.1f} ppb  "
                 f"({res['total_inject_uL']:.2f} µL of mix, {res['total_mass_mg']:.2f} mg)")
    lines.append(f"  Injected VOC mass conc : {res['voc_ugm3']:.2f} µg/m³")
    lines.append(f"  Predicted SOA @ {res['mass_yield']*100:.0f}% yield : "
                 f"{res['soa_ugm3']:.2f} µg/m³   "
                 f"(excl. isoprene: {res['soa_ugm3_excl_isoprene']:.2f} µg/m³)")
    return "\n".join(lines)


if __name__ == "__main__":
    ch = Chamber()
    print(f"SAPHIR: V={ch.volume_m3:.0f} m³, T={ch.temperature_K:.2f} K, "
          f"n_air={ch.n_air:,.0f} mol\n")
    for target in (10, 20, 30, 50):
        print(f"===== target total biogenic VOC = {target} ppb =====")
        print(_fmt(biogenic_plan(target)))
        print()
