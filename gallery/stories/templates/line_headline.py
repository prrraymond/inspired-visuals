"""Reusable Plotly template: one series, with the latest date and the change in the headline.

Shape (from the notebook's line_chart, after a markets-page line):
  - A single line, optionally filled to zero
  - Headline on one row: title, the date of the last point, and the % change over a
    chosen window, coloured and arrowed by direction
  - Round-number horizontal rules instead of gridlines; no axis lines
"""
import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Column placeholders -- one row per date.
# ---------------------------------------------------------------------------
date_column = "date"       # dates along the x-axis
value_column = "value"     # the measure

TITLE = "Chart title"
SOURCE_TEXT = "Source / credit"

LINE_COLOR = "#5C374C"
FILL = False               # shade the area under the line
CHANGE_SINCE = "1y"        # "1m", "3m", "6m", "1y", "5y", "ytd", or None for the first point
UP_COLOR, DOWN_COLOR = "#27AE60", "#C0392B"

FONT = "Helvetica, Arial, sans-serif"
INK, TEXT, MUTED, FAINT, RULE, BG = "#1A1A1A", "#333333", "#888888", "#AAAAAA", "#E5E5E5", "#FFFFFF"


def _nice_ceiling(x):
    if x <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(x))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= x)


def _fade(color, alpha):
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _reference(t, v):
    """The value the headline's % change is measured from."""
    if CHANGE_SINCE is None:
        return v.iloc[0]
    last = t.iloc[-1]
    offsets = {"1m": pd.DateOffset(months=1), "3m": pd.DateOffset(months=3),
               "6m": pd.DateOffset(months=6), "1y": pd.DateOffset(years=1),
               "5y": pd.DateOffset(years=5)}
    if CHANGE_SINCE == "ytd":
        cutoff = pd.Timestamp(last.year, 1, 1)
    elif CHANGE_SINCE in offsets:
        cutoff = last - offsets[CHANGE_SINCE]
    else:
        return v.iloc[0]
    before = v[t <= cutoff]
    return before.iloc[-1] if len(before) else v.iloc[0]


def build_figure(df):
    d = df[[date_column, value_column]].dropna().copy()
    d[date_column] = pd.to_datetime(d[date_column])
    d[value_column] = pd.to_numeric(d[value_column], errors="coerce")
    d = d.dropna().sort_values(date_column).reset_index(drop=True)
    t, v = d[date_column], d[value_column].astype(float)

    pct = (v.iloc[-1] / _reference(t, v) - 1) * 100
    up = pct >= 0
    head = (f"<b>{TITLE}</b>   "
            f"<span style='font-size:14px;color:{MUTED}'>{t.iloc[-1]:%b. %-d, %Y}</span>   "
            f"<span style='font-size:14px;color:{UP_COLOR if up else DOWN_COLOR}'>"
            f"{pct:+.1f}% {'↑' if up else '↓'}</span>")

    span = t.iloc[-1] - t.iloc[0]
    tickformat = ("%b %-d" if span < pd.Timedelta(days=120) else
                  "%b '%y" if span < pd.Timedelta(days=800) else "%Y")
    lo, hi = v.min(), v.max()
    pad = (hi - lo) * 0.06 or 1
    step = _nice_ceiling((hi - lo) / 5)
    floor = 0 if FILL else lo - pad
    ticks = [x for x in np.arange(math.floor(floor / step) * step, hi + pad, step) if x >= floor]

    fig = go.Figure(go.Scatter(
        x=t, y=v, mode="lines", line=dict(color=LINE_COLOR, width=1.6),
        fill="tozeroy" if FILL else None, fillcolor=_fade(LINE_COLOR, 0.15) if FILL else None,
        hovertemplate="%{x|%b %-d, %Y}: %{y:,.0f}<extra></extra>",
    ))
    for tv in ticks:
        fig.add_hline(y=tv, line=dict(color=RULE, width=0.6))
    fig.update_xaxes(showgrid=False, showline=False, zeroline=False, ticks="",
                     tickfont=dict(size=11, color=MUTED), tickformat=tickformat)
    fig.update_yaxes(showgrid=False, showline=False, zeroline=False, ticks="",
                     tickfont=dict(size=11, color=MUTED), tickvals=ticks, tickformat=",",
                     range=[floor, hi + pad])
    fig.update_layout(
        title=dict(text=head, x=0.01, xanchor="left", y=1, yanchor="top", yref="container",
                   pad=dict(t=18), font=dict(size=20, color=INK)),
        font=dict(family=FONT, size=12, color=TEXT),
        paper_bgcolor=BG, plot_bgcolor=BG, width=620, height=400,
        margin=dict(l=55, r=20, t=70, b=55), showlegend=False, hovermode="x unified",
    )
    fig.add_annotation(text=f"Source: {SOURCE_TEXT}", xref="paper", yref="paper", x=0, y=0,
                       yanchor="bottom", yshift=-49, xanchor="left", showarrow=False,
                       font=dict(size=9, color=FAINT))
    return fig
