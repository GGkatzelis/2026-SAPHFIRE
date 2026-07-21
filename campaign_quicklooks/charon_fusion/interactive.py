"""Interactive (Plotly) timeline for the CHARON-FUSION GUI.

Zoom/pan/hover and click-legend-to-toggle come for free; we overlay the
background/chemistry period shading and the pasted action-log events.
WebGL (Scattergl) keeps it smooth with tens of thousands of time points.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

_PALETTE = px.colors.qualitative.Dark24


def timeline_figure(times, values, mz, selected_idx=None, labels=None,
                    show_total=True, log_y=False, unit_label="signal (a.u.)",
                    events=None, bg_win=None, chem_win=None, height=480):
    times = pd.DatetimeIndex(times)
    fig = go.Figure()

    # period shading (drawn below the data)
    for win, color, name in ((bg_win, "#1f77b4", "background"),
                             (chem_win, "#ff7f0e", "chemistry")):
        if win and win[0] is not None and win[1] is not None:
            fig.add_vrect(x0=pd.Timestamp(win[0]), x1=pd.Timestamp(win[1]),
                          fillcolor=color, opacity=0.12, line_width=0, layer="below",
                          annotation_text=name, annotation_position="top left",
                          annotation_font=dict(size=10, color=color))

    if show_total:
        fig.add_trace(go.Scattergl(
            x=times, y=np.clip(values, 0, None).sum(axis=1), name="Σ all ions",
            line=dict(color="#444", width=1.4),
            hovertemplate="%{x|%H:%M:%S}<br>Σ = %{y:.1f}<extra>Σ all ions</extra>"))

    for k, j in enumerate(selected_idx or []):
        lab = labels[k] if labels is not None else f"m/z {mz[j]:.3f}"
        fig.add_trace(go.Scattergl(
            x=times, y=values[:, j], name=lab, mode="lines",
            line=dict(width=1.1, color=_PALETTE[k % len(_PALETTE)]),
            hovertemplate=f"{lab}<br>%{{x|%H:%M:%S}}<br>%{{y:.2f}}<extra></extra>"))

    # action-log event verticals + code labels along the top
    if events is not None and len(events):
        for _, e in events.iterrows():
            x = pd.Timestamp(e["time"])
            fig.add_vline(x=x, line=dict(color=e["color"], width=1, dash="dot"), opacity=0.65)
            fig.add_annotation(x=x, y=1.0, yref="paper", text=str(e["code"]),
                               hovertext=f"{e['time']:%H:%M} · {e['label']}: {e['description']}",
                               showarrow=False, textangle=-90, yanchor="bottom",
                               font=dict(size=9, color=e["color"]))

    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=24, b=10),
        hovermode="x unified", dragmode="zoom",
        legend=dict(orientation="h", yanchor="top", y=-0.12, x=0),
        xaxis_title="Time (UTC)", yaxis_title=unit_label,
        xaxis=dict(rangeslider=dict(visible=False)))
    if log_y:
        fig.update_yaxes(type="log")
    return fig
