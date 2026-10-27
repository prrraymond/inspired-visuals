"""Reusable Plotly template: series indexed to a common start, on a y-axis broken in two.

Shape (from the notebook's split_axis_lines):
  - One line per series, each indexed to 100 at the first period every series reports,
    so the lines read as relative change rather than in their own units
  - The value axis is split into two panels with the same units: the lower panel keeps
    the series that stay near the start readable, the upper carries whatever runs away
  - Every series is drawn in both panels, so a line that crosses the split continues
  - Break marks on the left edge, a dotted rule at the starting level, end labels
"""
import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# Column placeholders -- long form, one row per period per series.
# ---------------------------------------------------------------------------
date_column = "period"       # dates (or numbers) along the x-axis
series_column = "series"     # which line the row belongs to
value_column = "value"       # the measure, in each series' own units

TITLE = "Chart title"
SUBTITLE = "Units / measure description"
SOURCE_TEXT = "Source / credit"
REF_LABEL = "Baseline"

INDEX_TO_START = True        # False plots the values as given
SPLIT = 200                  # where the axis breaks, in plotted units
UPPER_SHARE = 0.62           # share of the height given to the upper panel
PALETTE = ["#1a4e66", "#c4543a", "#e8a63a", "#5a8a6a", "#8c7aa0", "#d4806a"]

FONT = "Helvetica, Arial, sans-serif"
INK, TEXT, MUTED, FAINT, RULE, BG = "#1A1A1A", "#333333", "#888888", "#AAAAAA", "#E5E5E5", "#FFFFFF"


def _nice_ceiling(x):
    if x <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(x))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= x)


def _wide(df):
    d = df[[date_column, series_column, value_column]].copy()
    if not pd.api.types.is_numeric_dtype(d[date_column]):
        d[date_column] = pd.to_datetime(d[date_column])
    d[value_column] = pd.to_numeric(d[value_column], errors="coerce")
    order = list(dict.fromkeys(d[series_column].dropna()))
    wide = d.pivot_table(index=date_column, columns=series_column, values=value_column,
                         aggfunc="mean").sort_index()
    wide = wide[[s for s in order if s in wide.columns]]
    if INDEX_TO_START:
        full = wide.dropna()
        if full.empty:
            raise ValueError("there is no period where every series has a value to index from")
        start = full.index[0]
        wide = wide.loc[start:] / wide.loc[start] * 100
    return wide


def build_figure(df):
    wide = _wide(df)
    names = list(wide.columns)
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(names))]
    lo, hi = float(np.nanmin(wide.values)), float(np.nanmax(wide.values))
    split = SPLIT if (SPLIT is not None and lo < SPLIT < hi) else None
    rows = 2 if split is not None else 1

    if rows == 2:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.035,
                            row_heights=[UPPER_SHARE, 1 - UPPER_SHARE])
        panels = {1: (split, hi * 1.05), 2: (min(0, lo), split)}
    else:
        fig = make_subplots(rows=1, cols=1)
        panels = {1: (min(0, lo), hi * 1.05)}
    bottom = max(panels)

    labels = []
    for name, color in zip(names, colors):
        s = wide[name].dropna()
        for row in panels:
            fig.add_trace(go.Scatter(
                x=s.index, y=s.values, mode="lines", name=str(name),
                line=dict(color=color, width=2.2), showlegend=False,
                hovertemplate=f"{name}: %{{y:,.0f}}<extra></extra>",
            ), row=row, col=1)
        if len(s):
            labels.append((float(s.iloc[-1]), s.index[-1], name, color))

    ref = 100 if INDEX_TO_START else None
    axis_ref = "" if bottom == 1 else str(bottom)
    if ref is not None and panels[bottom][0] <= ref <= panels[bottom][1]:
        fig.add_hline(y=ref, line=dict(color=FAINT, width=1, dash="dot"), row=bottom, col=1)
        fig.add_annotation(x=0, xref=f"x{axis_ref} domain", y=ref, yref=f"y{axis_ref}",
                           text=REF_LABEL, xanchor="left", yanchor="bottom", showarrow=False,
                           font=dict(size=10, color=MUTED), bgcolor=BG)

    # End labels go in whichever panel the last value falls in, nudged apart there.
    for row, (p_lo, p_hi) in panels.items():
        gap = (p_hi - p_lo) * 0.08
        placed = []
        mine = [l for l in labels if (rows == 1) or ((l[0] > split) == (row == 1))]
        for y, xv, name, color in sorted(mine, key=lambda l: l[0]):
            y_lab = max(y, placed[-1] + gap) if placed else y
            placed.append(y_lab)
            ref_axis = "" if row == 1 else str(row)
            fig.add_annotation(x=xv, y=y_lab, xref=f"x{ref_axis}", yref=f"y{ref_axis}",
                               text=f"<b>{name}</b> {y:,.0f}", xanchor="left", xshift=6,
                               showarrow=False, font=dict(size=11, color=color))

    fig.update_xaxes(showgrid=False, showline=False, zeroline=False, ticks="",
                     tickfont=dict(size=11, color=MUTED),
                     range=[wide.index.min(), wide.index.max()])
    for row, (p_lo, p_hi) in panels.items():
        step = _nice_ceiling((p_hi - p_lo) / (5 if row == 1 else 3))
        first = math.ceil(p_lo / step) * step
        if rows == 2 and p_lo % step == 0:
            # The upper panel starts at the split, which is the lower panel's top; the
            # lower one starts at zero, which would sit on the year labels.
            first += step
        fig.update_yaxes(range=[p_lo, p_hi], tickvals=list(np.arange(first, p_hi, step)),
                         tickformat=",", showgrid=True, gridcolor=RULE, gridwidth=0.6,
                         showline=False, zeroline=False, ticks="",
                         tickfont=dict(size=11, color=MUTED), row=row, col=1)

    if rows == 2:
        gap_lo, gap_hi = fig.layout.yaxis2.domain[1], fig.layout.yaxis.domain[0]
        for yb in (gap_lo, gap_hi):
            fig.add_shape(type="line", xref="paper", yref="paper", x0=-0.012, x1=0.012,
                          y0=yb - 0.008, y1=yb + 0.008, line=dict(color=MUTED, width=1.2))

    heading = (f"<b>{TITLE}</b><br>"
               f"<span style='font-size:13px;color:{MUTED}'>{SUBTITLE}</span>")
    fig.update_layout(
        title=dict(text=heading,
                   x=0.01, xanchor="left", y=1, yanchor="top", yref="container",
                   pad=dict(t=18), font=dict(size=18, color=INK)),
        font=dict(family=FONT, size=12, color=TEXT),
        paper_bgcolor=BG, plot_bgcolor=BG, width=720, height=540,
        margin=dict(l=55, r=190, t=90, b=60), showlegend=False, hovermode="x unified",
    )
    fig.add_annotation(text=f"Source: {SOURCE_TEXT}", xref="paper", yref="paper", x=0, y=0,
                       yanchor="bottom", yshift=-54, xanchor="left", showarrow=False,
                       font=dict(size=9, color=FAINT))
    return fig
