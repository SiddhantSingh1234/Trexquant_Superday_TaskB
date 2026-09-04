"""Shared Plotly chart builders + the dashboard palette (Section 0.4).

Every figure uses ``TEMPLATE`` (a registered Plotly template) and colours from
``PALETTE`` — no page uses an inline hex.  Legible on the dark Streamlit theme
and on a forced-light theme (D8 verifies both).

This module must not import ``src.*`` (asserted by the D0 test).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# --------------------------------------------------------------------------- #
# Palette                                                                      #
# --------------------------------------------------------------------------- #
PALETTE: dict = {
    "accent": "#4C9BE8",
    "accent2": "#F2A65A",
    "pos": "#3FB984",
    "neg": "#E5606B",
    "grid": "#2E3646",
    "text": "#E6E6E6",
    "muted": "#9AA4B2",
    "bg": "#0E1117",
    "cat": [
        "#4C9BE8", "#F2A65A", "#3FB984", "#E5606B", "#B085F5",
        "#57C7D4", "#E8C547", "#8FA6C4",
    ],
    "seq": [
        "#10233A", "#173A5E", "#1E5285", "#2E6DA8", "#4C9BE8",
        "#7FBCF0", "#B8DBF8",
    ],
}

TEMPLATE: str = "alphafactory"

_tmpl = go.layout.Template()
_tmpl.layout = go.Layout(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=PALETTE["text"], size=13),
    colorway=PALETTE["cat"],
    xaxis=dict(gridcolor=PALETTE["grid"], zerolinecolor=PALETTE["grid"],
               linecolor=PALETTE["grid"]),
    yaxis=dict(gridcolor=PALETTE["grid"], zerolinecolor=PALETTE["grid"],
               linecolor=PALETTE["grid"]),
    margin=dict(l=50, r=20, t=50, b=40),
    legend=dict(bgcolor="rgba(0,0,0,0)"),
)
pio.templates[TEMPLATE] = _tmpl


def _fig(title: str = "", y_title: str = "") -> go.Figure:
    fig = go.Figure()
    fig.update_layout(template=TEMPLATE, title=title, yaxis_title=y_title)
    return fig


# --------------------------------------------------------------------------- #
# KPI row                                                                      #
# --------------------------------------------------------------------------- #
def kpi_row(items: list[tuple[str, str, str | None]]) -> None:
    """Render ``st.columns`` of metric tiles: ``(label, value, delta|None)``."""
    if not items:
        return
    cols = st.columns(len(items))
    for col, (label, value, delta) in zip(cols, items):
        col.metric(label, value, delta)


# --------------------------------------------------------------------------- #
# Generic builders                                                             #
# --------------------------------------------------------------------------- #
def line(df, x, y, color=None, title="", y_title="", ref: float | None = None) -> go.Figure:
    fig = _fig(title, y_title)
    ys = y if isinstance(y, (list, tuple)) else [y]
    if color and color in df.columns:
        for i, (key, grp) in enumerate(df.groupby(color)):
            fig.add_scatter(x=grp[x], y=grp[ys[0]], mode="lines", name=str(key),
                            line=dict(color=PALETTE["cat"][i % len(PALETTE["cat"])]))
    else:
        for i, yy in enumerate(ys):
            fig.add_scatter(x=df[x], y=df[yy], mode="lines", name=yy,
                            line=dict(color=PALETTE["cat"][i % len(PALETTE["cat"])]))
    if ref is not None:
        fig.add_hline(y=ref, line_dash="dash", line_color=PALETTE["muted"])
    fig.update_layout(xaxis_title=x)
    return fig


def bar(df, x, y, color=None, title="", horizontal=False, sort=None) -> go.Figure:
    d = df.copy()
    if sort in ("asc", "desc"):
        d = d.sort_values(y, ascending=(sort == "asc"))
    fig = _fig(title)
    orient = "h" if horizontal else "v"
    if horizontal:
        fig.add_bar(y=d[x], x=d[y], orientation=orient, marker_color=PALETTE["accent"])
        fig.update_layout(xaxis_title=y, yaxis_title=x)
    else:
        fig.add_bar(x=d[x], y=d[y], orientation=orient, marker_color=PALETTE["accent"])
        fig.update_layout(xaxis_title=x, yaxis_title=y)
    return fig


def hist(series, title="", bins=40, x_title="") -> go.Figure:
    fig = _fig(title)
    fig.add_histogram(x=np.asarray(series, dtype=float), nbinsx=bins,
                      marker_color=PALETTE["accent"])
    fig.update_layout(xaxis_title=x_title, yaxis_title="count")
    return fig


def violin(df, x, y, title="") -> go.Figure:
    fig = _fig(title)
    for i, (key, grp) in enumerate(df.groupby(x)):
        fig.add_violin(y=grp[y], name=str(key), box_visible=True, meanline_visible=True,
                       line_color=PALETTE["cat"][i % len(PALETTE["cat"])])
    fig.update_layout(xaxis_title=x, yaxis_title=y)
    return fig


def box(df, x, y, title="") -> go.Figure:
    fig = _fig(title)
    for i, (key, grp) in enumerate(df.groupby(x)):
        fig.add_box(y=grp[y], name=str(key),
                    marker_color=PALETTE["cat"][i % len(PALETTE["cat"])])
    fig.update_layout(xaxis_title=x, yaxis_title=y)
    return fig


def heatmap(matrix_df, title="", zmid=None, colorscale=None) -> go.Figure:
    fig = _fig(title)
    fig.add_heatmap(
        z=matrix_df.values,
        x=list(matrix_df.columns),
        y=list(matrix_df.index),
        zmid=zmid,
        colorscale=colorscale or "RdBu",
    )
    return fig


def stacked_area(df, x, y, color, title="") -> go.Figure:
    fig = _fig(title)
    piv = df.pivot_table(index=x, columns=color, values=y, aggfunc="sum").fillna(0.0)
    for i, col in enumerate(piv.columns):
        fig.add_scatter(x=piv.index, y=piv[col], name=str(col), mode="lines",
                        stackgroup="one",
                        line=dict(color=PALETTE["cat"][i % len(PALETTE["cat"])]))
    fig.update_layout(xaxis_title=x, yaxis_title=y)
    return fig


def candlestick(df, title="", markers: pd.DataFrame | None = None) -> go.Figure:
    fig = _fig(title)
    fig.add_candlestick(x=df["date"], open=df["open"], high=df["high"],
                        low=df["low"], close=df["close"],
                        increasing_line_color=PALETTE["pos"],
                        decreasing_line_color=PALETTE["neg"], name="OHLC")
    if markers is not None and len(markers):
        mcol = "date" if "date" in markers else markers.columns[0]
        yv = df["high"].max()
        fig.add_scatter(x=markers[mcol], y=[yv] * len(markers), mode="markers",
                        marker=dict(color=PALETTE["accent2"], symbol="triangle-down",
                                    size=10), name="corp. action")
    fig.update_layout(xaxis_rangeslider_visible=False)
    return fig


def gantt(df, start="start", end="end", label="symbol", color=None, title="") -> go.Figure:
    fig = _fig(title)
    cats = list(df[label])
    for i, row in df.reset_index(drop=True).iterrows():
        key = row[color] if color and color in df.columns else label
        fig.add_scatter(
            x=[row[start], row[end]], y=[row[label], row[label]], mode="lines",
            line=dict(color=PALETTE["cat"][hash(str(key)) % len(PALETTE["cat"])], width=12),
            name=str(key), showlegend=False,
        )
    fig.update_layout(yaxis=dict(categoryorder="array", categoryarray=cats[::-1]),
                      xaxis_title="date")
    return fig


def scatter(df, x, y, color=None, trend=False, title="") -> go.Figure:
    fig = _fig(title)
    if color and color in df.columns:
        for i, (key, grp) in enumerate(df.groupby(color)):
            fig.add_scatter(x=grp[x], y=grp[y], mode="markers", name=str(key),
                            marker=dict(color=PALETTE["cat"][i % len(PALETTE["cat"])]))
    else:
        fig.add_scatter(x=df[x], y=df[y], mode="markers",
                        marker=dict(color=PALETTE["accent"]))
    if trend and len(df) >= 2:
        xv = pd.to_numeric(df[x], errors="coerce").to_numpy()
        yv = pd.to_numeric(df[y], errors="coerce").to_numpy()
        ok = np.isfinite(xv) & np.isfinite(yv)
        if ok.sum() >= 2:
            m, b = np.polyfit(xv[ok], yv[ok], 1)
            xs = np.array([np.nanmin(xv[ok]), np.nanmax(xv[ok])])
            fig.add_scatter(x=xs, y=m * xs + b, mode="lines", name="trend",
                            line=dict(color=PALETTE["accent2"], dash="dash"))
    fig.update_layout(xaxis_title=x, yaxis_title=y)
    return fig


def gauge(value: float, maximum: float, label: str,
          thresholds: dict | None = None) -> go.Figure:
    steps = []
    if thresholds:
        for lo, hi, colour in thresholds.get("bands", []):
            steps.append(dict(range=[lo, hi], color=colour))
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        title={"text": label},
        gauge={
            "axis": {"range": [0, maximum]},
            "bar": {"color": PALETTE["accent"]},
            "steps": steps,
            "bordercolor": PALETTE["grid"],
        },
    ))
    fig.update_layout(template=TEMPLATE, margin=dict(l=30, r=30, t=50, b=10))
    return fig


# --------------------------------------------------------------------------- #
# Purpose-built                                                                #
# --------------------------------------------------------------------------- #
def coverage_chart(daily: pd.DataFrame, target: int = 200) -> tuple[go.Figure, dict]:
    """``daily``: ``date`` + ``n_members`` (or ``n_panel``).  Returns
    ``(figure, {'slope_per_year': float, 'verdict': 'FLAT'|'SLOPING'})``.

    The figure carries a constant-``target`` reference line and a fitted OLS
    trend line.  ``verdict`` is ``'FLAT'`` if ``|slope_per_year| < 3`` names/year.
    """
    d = daily.copy()
    ycol = "n_panel" if "n_panel" in d.columns else "n_members"
    d = d.dropna(subset=["date", ycol]).sort_values("date")
    dt = pd.to_datetime(d["date"])
    x_years = (dt - dt.min()).dt.total_seconds().to_numpy() / (365.25 * 86400.0)
    y = d[ycol].to_numpy(dtype=float)

    slope = 0.0
    intercept = float(np.nanmean(y)) if len(y) else 0.0
    if len(y) >= 2 and np.ptp(x_years) > 0:
        slope, intercept = np.polyfit(x_years, y, 1)

    verdict = "FLAT" if abs(slope) < 3.0 else "SLOPING"

    fig = _fig("Universe coverage — names in the panel per day", "names")
    fig.add_scatter(x=dt, y=y, mode="lines", name=ycol,
                    line=dict(color=PALETTE["accent"], width=1))
    if len(y):
        fig.add_scatter(x=dt, y=intercept + slope * x_years, mode="lines",
                        name=f"OLS trend ({slope:+.2f}/yr)",
                        line=dict(color=PALETTE["accent2"], dash="dash", width=2))
    fig.add_hline(y=target, line_dash="dot", line_color=PALETTE["muted"],
                  annotation_text=f"target {target}")
    return fig, {"slope_per_year": float(slope), "verdict": verdict}


def decay_curve(by_horizon: dict, title="RankIC decay") -> go.Figure:
    hs = sorted(by_horizon)
    fig = _fig(title, "RankIC")
    fig.add_scatter(x=hs, y=[by_horizon[h] for h in hs], mode="lines+markers",
                    line=dict(color=PALETTE["accent"]))
    fig.add_hline(y=0.0, line_color=PALETTE["muted"], line_width=1)
    fig.update_layout(xaxis_title="horizon (days)")
    return fig


def equity_curve(daily_returns: pd.Series, title="Long-short equity") -> go.Figure:
    r = pd.Series(daily_returns).dropna().astype(float)
    eq = (1.0 + r).cumprod()
    fig = _fig(title, "growth of 1")
    fig.add_scatter(x=eq.index, y=eq.to_numpy(), mode="lines",
                    line=dict(color=PALETTE["pos"]))
    fig.update_layout(xaxis_title="date")
    return fig


def ic_bar(df, feature_col="feature", ic_col="rank_ic", err_col=None,
           noise_band: float | None = None) -> go.Figure:
    d = df.copy().sort_values(ic_col)
    colours = [PALETTE["pos"] if v >= 0 else PALETTE["neg"] for v in d[ic_col]]
    fig = _fig("Feature RankIC", "RankIC")
    fig.add_bar(x=d[feature_col], y=d[ic_col], marker_color=colours,
                error_y=dict(type="data", array=d[err_col]) if err_col else None)
    if noise_band is not None:
        fig.add_hrect(y0=-noise_band, y1=noise_band, line_width=0,
                      fillcolor=PALETTE["muted"], opacity=0.15)
    fig.update_layout(xaxis_title=feature_col)
    return fig
