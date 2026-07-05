r"""CHARON-FUSION quicklooks — Streamlit GUI.

Load a SAPHFIRE IDA export (time x m/z), auto-assign [M+H]+ formulas, and draw
the classic quicklooks: mass-spec timeline, carbon-oxygen distribution, VBS, and
a chemical-space animation.

Run:  campaign_quicklooks\charon_fusion\run_quicklooks.bat
 or:  ...\.venv\Scripts\streamlit.exe run quicklooks_gui.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# ── run under Streamlit even if launched as a plain script ───────────────
def _ensure_streamlit():
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx() is not None:
            return
    except Exception:
        pass
    import subprocess
    exe = Path(sys.executable)
    streamlit = exe.with_name("streamlit.exe") if os.name == "nt" else exe.with_name("streamlit")
    cmd = [str(streamlit if streamlit.exists() else "streamlit"), "run", str(Path(__file__).resolve())]
    print("Relaunching under Streamlit:", " ".join(cmd))
    raise SystemExit(subprocess.call(cmd))


_ensure_streamlit()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for `charon_fusion` package

import numpy as np
import pandas as pd
import streamlit as st

from charon_fusion import charon_io, chemistry, ql_plots, stats, stats_plots, video

# Optional convenience prefill for the path box (not required). Set the
# CHARON_EXPORT environment variable to your usual export, or just upload / paste.
DEFAULT_PATH = os.environ.get("CHARON_EXPORT", "")

st.set_page_config(page_title="CHARON-FUSION quicklooks", page_icon="🔥", layout="wide")


# ── cached loaders ───────────────────────────────────────────────────────
@st.cache_data(show_spinner="Loading export (first load parses the whole file)…")
def load_data(path: str, mtime: float, size: int):
    return charon_io.load_timeseries(path)


@st.cache_data(show_spinner="Assigning formulas…")
def assign(mz_tuple, tol_mda, max_ppm, max_N, ov_key, ov_path):
    overrides = None
    if ov_path:
        try:
            overrides = charon_io.load_overrides(ov_path)
        except Exception as e:
            st.warning(f"Could not read override table: {e}")
    return chemistry.assign_table(np.asarray(mz_tuple), tol_mda=tol_mda,
                                  max_ppm=max_ppm, max_N=max_N, overrides=overrides)


# ── sidebar: data + settings ─────────────────────────────────────────────
st.sidebar.title("CHARON-FUSION")
st.sidebar.caption("SAPHFIRE 2026 quicklooks")

st.sidebar.markdown("**Data source**")
upload = st.sidebar.file_uploader("Upload export (xlsx / csv / tsv)",
                                  type=["xlsx", "xls", "csv", "txt", "tsv"])
path = st.sidebar.text_input("…or path to an export", value=DEFAULT_PATH,
                             help="A wide time × m/z table. Set the CHARON_EXPORT "
                                  "env var to prefill this.")

src = None
if upload is not None:
    tmp = Path(tempfile.gettempdir()) / f"charon_upload_{upload.name}"
    tmp.write_bytes(upload.getbuffer())
    src = str(tmp)
elif path and Path(path).exists():
    src = path

if src is None:
    st.title("CHARON-FUSION quicklooks 🔥")
    st.info("**Upload** a CHARON-FUSION export or **enter its path** in the sidebar.\n\n"
            "Any wide *time × m/z* table works — Excel IDA exports "
            "(`…-IDA_Export_*.xlsx`) or CSV/TSV. The time column may be "
            "`time_number`/`time_string`/`datetime`; ion columns like "
            "`m/z 101.023 []`, `mz101.023` or a bare number.")
    st.stop()

stat = Path(src).stat()
data = load_data(src, stat.st_mtime, stat.st_size)

st.sidebar.markdown("**Formula assignment** ([M+H]⁺)")
tol_mda = st.sidebar.slider("Mass tolerance (mDa)", 2.0, 20.0, 7.0, 0.5)
max_ppm = st.sidebar.slider("… or ppm (whichever looser)", 2.0, 40.0, 12.0, 1.0)
max_N = st.sidebar.selectbox("Max N atoms", [0, 1, 2], index=1)
max_err = st.sidebar.slider("Plot filter: |mass error| ≤ (mDa)", 1.0, 20.0, 5.0, 0.5)
ov_path = st.sidebar.text_input("Override peak table (optional CSV/XLSX)", value="")
unit_label = st.sidebar.text_input("Signal unit label", value="signal (a.u.)")

tbl = assign(tuple(data.mz.tolist()), tol_mda, max_ppm, int(max_N),
             ov_path or "", ov_path or "")

# ── time window ──────────────────────────────────────────────────────────
t0, t1 = data.times[0].to_pydatetime(), data.times[-1].to_pydatetime()
win = st.sidebar.slider("Time window", min_value=t0, max_value=t1, value=(t0, t1),
                        format="MM-DD HH:mm")
conc = data.window_mean(pd.Timestamp(win[0]), pd.Timestamp(win[1]))

# ── header / assignment summary ──────────────────────────────────────────
st.title("CHARON-FUSION quicklooks 🔥")
n_asg = int(tbl["assigned"].sum())
sig_expl = 100 * conc[tbl["assigned"].to_numpy()].sum() / max(conc.sum(), 1e-9)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Ions", f"{data.n_ions}")
c2.metric("Assigned", f"{n_asg}  ({100*n_asg/data.n_ions:.0f}%)")
c3.metric("Signal explained", f"{sig_expl:.1f}%")
c4.metric("Time points", f"{data.n_times}")
_sheet = data.meta.get("sheet")
st.caption(f"Source: `{Path(src).name}`" + (f"  ·  sheet `{_sheet}`" if _sheet else "") +
           f"  ·  {data.times[0]:%Y-%m-%d %H:%M} → {data.times[-1]:%Y-%m-%d %H:%M} UTC  ·  "
           f"m/z {data.mz.min():.2f}–{data.mz.max():.2f}")

tab_tl, tab_co, tab_vbs, tab_md, tab_stats, tab_anim, tab_tbl = st.tabs(
    ["📈 Timeline", "🧱 Carbon–oxygen", "🫧 VBS", "🎯 Mass defect",
     "🔬 Signal & clusters", "🎬 Animation", "🔎 Peak table"])

# ── timeline ─────────────────────────────────────────────────────────────
with tab_tl:
    order = np.argsort(conc)[::-1]
    labels_all = [(f"m/z {data.mz[j]:.3f}"
                   + (f"  ({tbl.loc[j,'formula']})" if tbl.loc[j, "assigned"] else "")) for j in range(data.n_ions)]
    default_sel = order[:8].tolist()
    colL, colR = st.columns([3, 1])
    with colR:
        show_total = st.checkbox("Show Σ all ions", value=True)
        log_y = st.checkbox("Log y-axis", value=False)
        n_top = st.slider("Quick-pick top-N ions", 0, 20, 8)
    picks = st.multiselect(
        "Ions to plot", options=list(range(data.n_ions)),
        default=order[:n_top].tolist(),
        format_func=lambda j: labels_all[j])
    sel = picks if picks else default_sel
    lab = [tbl.loc[j, "formula"] if tbl.loc[j, "assigned"] else f"m/z {data.mz[j]:.2f}" for j in sel]
    fig = ql_plots.plot_timeline(data.times, data.values, data.mz, selected_idx=sel,
                                 labels=lab, show_total=show_total, log_y=log_y,
                                 unit_label=unit_label)
    st.pyplot(fig, width="stretch")

# ── carbon-oxygen ────────────────────────────────────────────────────────
with tab_co:
    st.caption("Window-mean signal, assigned ions only. Left: stacked by oxygen "
               "number; right: stacked by CHO(N) family.")
    st.pyplot(ql_plots.plot_c_o(tbl, conc, unit_label=f"Σ {unit_label}",
                                max_err_mda=max_err), width="stretch")

# ── VBS ──────────────────────────────────────────────────────────────────
with tab_vbs:
    st.caption("Volatility basis set — Li et al. (2016) log₁₀(C*) vs Kroll (2011) "
               "carbon oxidation state. Marker size ∝ window-mean signal.")
    st.pyplot(ql_plots.plot_vbs(tbl, conc, unit_label=unit_label, max_err_mda=max_err),
              width="content")

# ── mass defect ──────────────────────────────────────────────────────────
with tab_md:
    st.caption("Neutral mass defect (mass − nominal) coloured by family — separates "
               "CH / CHO / CHON series.")
    st.pyplot(ql_plots.plot_mass_defect(tbl, conc, unit_label=unit_label, max_err_mda=max_err),
              width="content")

# ── signal detection & clustering ────────────────────────────────────────
def _render_signal_clusters():
    st.caption(f"How many of the {data.n_ions} masses carry **real signal** above the "
               "background, and which ones **co-evolve**? Define a background and a "
               "chemistry window below; detection and clustering are computed "
               "relative to the background.")

    total = np.clip(data.values, 0, None).sum(axis=1)
    # default windows: BG = first flat stretch; chemistry = from the first rise to end
    thr = 0.30 * total.max()
    rise = int(np.argmax(total >= thr)) if (total >= thr).any() else int(0.2 * data.n_times)
    bg_end_default = data.times[max(int(0.08 * data.n_times), 1)].to_pydatetime()
    chem_start_default = data.times[rise].to_pydatetime()

    m1, m2 = st.columns(2)
    bg_win = m1.slider("Background window", min_value=t0, max_value=t1,
                       value=(t0, bg_end_default), format="MM-DD HH:mm", key="bg_win")
    chem_win = m2.slider("Chemistry window", min_value=t0, max_value=t1,
                         value=(chem_start_default, t1), format="MM-DD HH:mm", key="chem_win")
    snr_thr = st.slider("SNR threshold (real signal if enhancement / σ_bg ≥)",
                        1.0, 10.0, 3.0, 0.5)

    bg_mask = np.asarray((data.times >= pd.Timestamp(bg_win[0])) & (data.times <= pd.Timestamp(bg_win[1])))
    chem_mask = np.asarray((data.times >= pd.Timestamp(chem_win[0])) & (data.times <= pd.Timestamp(chem_win[1])))

    st.pyplot(stats_plots.plot_period_timeline(data.times, total, bg_mask, chem_mask),
              width="stretch")

    if bg_mask.sum() < 2 or chem_mask.sum() < 1:
        st.warning("Background needs ≥2 points and chemistry ≥1 point — widen the windows.")
        return

    det = stats.detection_stats(data.values, bg_mask, chem_mask, data.mz,
                                snr_threshold=snr_thr, prop_table=tbl)
    n_det = int(det["detected"].sum())
    chem_tot = det["chem_mean"].clip(lower=0).sum()
    sig_frac = 100 * det.loc[det["detected"], "chem_mean"].clip(lower=0).sum() / max(chem_tot, 1e-9)
    d1, d2, d3 = st.columns(3)
    d1.metric("Real-signal masses", f"{n_det} / {data.n_ions}")
    d2.metric("… fraction of masses", f"{100*n_det/data.n_ions:.0f}%")
    d3.metric("… of chemistry signal", f"{sig_frac:.1f}%")

    s1, s2 = st.columns(2)
    s1.pyplot(stats_plots.plot_snr_hist(det, snr_thr), width="stretch")
    s2.pyplot(stats_plots.plot_enhancement_scatter(det), width="stretch")

    # ── clustering (detected masses, whole-record correlation) ───────────
    st.markdown("#### Pattern clustering (HCA)")
    detected_idx = np.where(det["detected"].to_numpy())[0]
    if len(detected_idx) < 3:
        st.info("Fewer than 3 detected masses — lower the SNR threshold to cluster.")
        return

    cc1, cc2 = st.columns(2)
    cap = cc1.slider("Max masses in heatmap (top by enhancement)",
                     20, min(600, len(detected_idx)), min(250, len(detected_idx)), 10)
    n_clusters = cc2.slider("Number of clusters", 2, 12, 6)
    # cap to top-N by enhancement for a readable heatmap
    order_by_enh = detected_idx[np.argsort(det["enhancement"].to_numpy()[detected_idx])[::-1]]
    use_idx = np.sort(order_by_enh[:cap])
    if len(use_idx) < len(detected_idx):
        st.caption(f"Showing the top {len(use_idx)} of {len(detected_idx)} detected "
                   "masses by enhancement (heatmap readability).")
    corr = stats.correlation_matrix(data.values, use_idx, rows=None)  # whole record
    labels, leaf_order, _ = stats.cluster_masses(corr, n_clusters=n_clusters)
    summary = stats.cluster_summary(det, use_idx, labels)
    profiles = stats.cluster_profiles(data.values, use_idx, labels, normalize="max")

    h1, h2 = st.columns(2)
    h1.pyplot(stats_plots.plot_corr_heatmap(corr, leaf_order, labels, mz=data.mz), width="content")
    h2.pyplot(stats_plots.plot_cluster_profiles(data.times, profiles, summary), width="stretch")

    st.dataframe(summary, width="stretch")
    assign_tbl = det.iloc[use_idx].copy()
    assign_tbl["cluster"] = labels
    st.download_button("⬇ Download detection + clusters (CSV)",
                       assign_tbl.to_csv(index=False).encode(),
                       file_name="charon_signal_clusters.csv", mime="text/csv")


with tab_stats:
    _render_signal_clusters()


# ── animation ────────────────────────────────────────────────────────────
with tab_anim:
    st.caption("Render the chemical-space evolution over the experiment "
               "(2×2: timeline · VBS · carbon–oxygen · mass defect).")
    a1, a2, a3 = st.columns(3)
    n_frames = a1.slider("Frames", 20, 300, 90, 10)
    fps = a2.slider("Frames/s", 4, 24, 12, 1)
    window_pts = a3.slider("Smoothing window (points)", 1, 61, 9, 2)
    st.caption("Panel scales (marker size, carbon–oxygen y-axis) are fixed across "
               "frames so they grow from ~0 at background and peak during the "
               "chemistry — you can follow the time evolution.")
    co_ymax = st.number_input("Carbon–oxygen y-max (0 = auto global maximum)",
                              min_value=0.0, value=0.0, step=100.0,
                              help="Fix the C–O bar y-axis. Leave 0 to use the tallest bar "
                                   "over the whole experiment.")
    fmt = st.radio("Format", ["mp4", "gif"], horizontal=True)
    if st.button("🎬 Render animation", type="primary"):
        order = np.argsort(conc)[::-1]
        sel = order[:8].tolist()
        lab = [tbl.loc[j, "formula"] if tbl.loc[j, "assigned"] else f"m/z {data.mz[j]:.2f}" for j in sel]
        out = Path(tempfile.gettempdir()) / f"charon_chemspace.{fmt}"
        bar = st.progress(0.0, text="Rendering frames…")
        try:
            video.render_chemspace_video(out, data, tbl, n_frames=n_frames, fps=fps,
                                         window_pts=window_pts, max_err_mda=max_err,
                                         unit_label=unit_label, selected_idx=sel, labels=lab,
                                         co_ymax=(co_ymax or None),
                                         progress=lambda f: bar.progress(min(f, 1.0),
                                                                         text=f"Rendering… {f*100:.0f}%"))
            bar.empty()
            if fmt == "mp4":
                st.video(str(out))
            else:
                st.image(str(out))
            st.download_button(f"⬇ Download {fmt}", data=out.read_bytes(),
                               file_name=f"charon_chemspace.{fmt}", mime=f"video/{fmt}")
        except Exception as e:
            bar.empty()
            st.error(f"Render failed: {e}")

# ── peak table ───────────────────────────────────────────────────────────
with tab_tbl:
    show = tbl.copy()
    show["window_signal"] = conc
    show = show[show["assigned"]].sort_values("window_signal", ascending=False)
    st.caption("Assigned ions with derived properties (window-mean signal). "
               "Download to review or seed an override table.")
    st.dataframe(show[["mz", "formula", "C", "H", "O", "N", "OC", "HC", "osc",
                       "logc", "klass", "err_mDa", "source", "window_signal"]],
                 width="stretch", height=460)
    st.download_button("⬇ Download peak table (CSV)", show.to_csv(index=False).encode(),
                       file_name="charon_peak_table.csv", mime="text/csv")
