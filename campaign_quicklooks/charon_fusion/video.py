"""Off-screen animation of the CHARON-FUSION chemical-space evolution.

Renders the four quicklook panels frame-by-frame into an MP4 (or GIF) by
reading each matplotlib figure's Agg buffer and compositing a 2x2 grid with
numpy -- the same approach as MCM_SAPHIR_Tool._cs_save_video (no GUI animation,
works head-less). Marker sizes use a global reference so they visibly shrink as
concentrations decay across the experiment.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

from . import ql_plots

COL_W, ROW_H = 720, 500  # per-panel pixel size -> 1440 x 1000 frame
_FIGSIZE = (COL_W / 100.0, ROW_H / 100.0)  # dpi 100 -> exact pixel size, no resize


def _fig_rgb(fig):
    fig.canvas.draw()
    w, h = fig.canvas.get_width_height()
    buf = np.asarray(fig.canvas.buffer_rgba()).reshape(h, w, 4)
    return np.ascontiguousarray(buf[:, :, :3])


def _resize(arr, w, h):
    if arr.shape[0] == h and arr.shape[1] == w:
        return arr
    from PIL import Image
    return np.asarray(Image.fromarray(arr).resize((w, h), Image.BILINEAR), dtype=np.uint8)


def _window_mean(values, center, half):
    lo = max(0, center - half)
    hi = min(values.shape[0], center + half + 1)
    v = values[lo:hi].mean(axis=0)
    return np.clip(v, 0, None)


def _timeline_base(data, selected_idx, labels, unit_label):
    """Render the timeline once; return (base_rgb, cursor_fn).

    ``cursor_fn(timestamp)`` returns a copy of the base image with a red
    vertical cursor drawn at that time — far cheaper than re-plotting 3722
    points every frame.
    """
    fig = ql_plots.plot_timeline(data.times, data.values, data.mz,
                                 selected_idx=selected_idx, labels=labels,
                                 unit_label=unit_label, figsize=_FIGSIZE)
    ax = fig.axes[0]
    fig.canvas.draw()
    base = _fig_rgb(fig)
    H, W = base.shape[:2]
    ext = ax.get_window_extent()
    row0, row1 = max(int(H - ext.y1), 0), min(int(H - ext.y0), H)  # top, bottom rows
    # precompute a linear time -> pixel-column mapping (x-axis is linear in date2num)
    x0num, x1num = ax.get_xlim()
    px0 = ax.transData.transform((x0num, 0))[0]
    px1 = ax.transData.transform((x1num, 0))[0]
    import matplotlib.pyplot as plt
    plt.close(fig)

    def cursor(ts):
        img = base.copy()
        xnum = mdates.date2num(pd.Timestamp(ts).to_pydatetime())
        frac = (xnum - x0num) / (x1num - x0num) if x1num != x0num else 0.0
        col = int(round(px0 + frac * (px1 - px0)))
        for c in (col, col + 1):
            if 0 <= c < W:
                img[row0:row1, c] = (220, 20, 60)
        return img

    return base, cursor


def render_chemspace_video(out_path, data, prop_table, *, n_frames=120, fps=12,
                           window_pts=9, max_err_mda=None, unit_label="signal (a.u.)",
                           selected_idx=None, labels=None, co_ymax=None, progress=None):
    """Write a 2x2 chemical-space animation to ``out_path`` (.mp4 or .gif).

    Marker sizes (VBS, mass-defect) and the carbon-oxygen y-axis are held to a
    global reference across frames, so the panels grow from ~0 at background and
    peak during the chemistry — you can follow the time evolution. ``co_ymax``
    overrides the auto carbon-oxygen y-limit. ``progress`` is an optional
    callback(frac in 0..1). Returns the path.
    """
    import imageio.v2 as imageio

    out_path = str(out_path)
    T = data.n_times
    half = max(window_pts // 2, 0)
    frame_centers = np.linspace(0, T - 1, max(int(n_frames), 2)).round().astype(int)

    # global references across all frames: marker size (VBS/mass-defect) and the
    # tallest carbon-oxygen bar, so both grow with the signal instead of rescaling
    size_ref = 0.0
    co_max = 0.0
    concs = []
    for c in frame_centers:
        v = _window_mean(data.values, int(c), half)
        concs.append(v)
        m = v[prop_table["assigned"].to_numpy()].max() if prop_table["assigned"].any() else v.max()
        size_ref = max(size_ref, float(m))
        co_max = max(co_max, ql_plots.co_max_height(prop_table, v, max_err_mda=max_err_mda))
    co_limit = co_ymax if co_ymax else (co_max * 1.05 if co_max > 0 else None)

    is_gif = out_path.lower().endswith(".gif")
    if is_gif:
        writer = imageio.get_writer(out_path, mode="I", duration=1.0 / fps, loop=0)
    else:
        writer = imageio.get_writer(out_path, fps=fps, codec="libx264", quality=8,
                                    pixelformat="yuv420p", macro_block_size=2)

    # timeline is identical every frame (only the cursor moves) -> render once
    ts_base, ts_cursor = _timeline_base(data, selected_idx, labels, unit_label)

    import matplotlib.pyplot as plt
    try:
        for i, (c, conc) in enumerate(zip(frame_centers, concs)):
            tstamp = data.times[int(c)]
            ts_rgb = _resize(ts_cursor(tstamp), COL_W, ROW_H)
            f_vbs = ql_plots.plot_vbs(prop_table, conc, unit_label=unit_label,
                                      max_err_mda=max_err_mda, size_ref=size_ref, figsize=_FIGSIZE)
            f_co = ql_plots.plot_c_o(prop_table, conc, unit_label=f"Σ {unit_label}",
                                     max_err_mda=max_err_mda, ymax=co_limit, figsize=_FIGSIZE)
            f_md = ql_plots.plot_mass_defect(prop_table, conc, unit_label=unit_label,
                                             max_err_mda=max_err_mda, size_ref=size_ref, figsize=_FIGSIZE)

            top = np.hstack([ts_rgb, _resize(_fig_rgb(f_vbs), COL_W, ROW_H)])
            bot = np.hstack([_resize(_fig_rgb(f_co), COL_W, ROW_H),
                             _resize(_fig_rgb(f_md), COL_W, ROW_H)])
            writer.append_data(np.vstack([top, bot]))
            for f in (f_vbs, f_co, f_md):
                plt.close(f)
            if progress:
                progress((i + 1) / len(frame_centers))
    finally:
        writer.close()
    return Path(out_path)
