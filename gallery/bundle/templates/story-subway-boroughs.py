"""Reusable Plotly template: one filled-line panel per group, sharing the time axis.

Shape (from the notebook's small_multiples):
  - A grid of panels, one per group, each a line over a light fill of its own colour
  - Shared scale (panels compare in size) or per-panel scale (shapes compare)
  - Panel name in bold above each panel; two ticks per panel, at half and full
"""
import math

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# Column placeholders -- long form, one row per date per group.
# ---------------------------------------------------------------------------
date_column = "date"       # dates along the x-axis
panel_column = "group"     # one panel per distinct value
value_column = "value"     # the measure

TITLE = "Chart title"
SUBTITLE = "Units / measure description"
SOURCE_TEXT = "Source / credit"

SHARED_Y = True            # False scales each panel to itself
ROLLING = None             # e.g. 7 for a rolling mean over that many rows
COLS = 3
PALETTE = ["#D34A3A", "#E67E22", "#777777", "#4A6F8A", "#5A8C4A", "#8c7aa0",
           "#d4806a", "#4a7c8f"]

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


def build_figure(df):
    d = df[[date_column, panel_column, value_column]].copy()
    d[date_column] = pd.to_datetime(d[date_column])
    d[value_column] = pd.to_numeric(d[value_column], errors="coerce")
    order = list(dict.fromkeys(d[panel_column].dropna()))
    wide = d.pivot_table(index=date_column, columns=panel_column, values=value_column,
                         aggfunc="sum").sort_index()
    wide = wide[[g for g in order if g in wide.columns]]
    if ROLLING and ROLLING > 1:
        wide = wide.rolling(int(ROLLING), min_periods=1).mean()

    names = list(wide.columns)
    n_cols = max(1, min(len(names), int(COLS)))
    n_rows = math.ceil(len(names) / n_cols)
    fig = make_subplots(rows=n_rows, cols=n_cols, shared_xaxes=True,
                        horizontal_spacing=0.07, vertical_spacing=0.2,
                        subplot_titles=[f"<b>{n}</b>" for n in names])

    upper_all = _nice_ceiling(wide.max().max() * 1.05)
    for i, name in enumerate(names):
        r, c = i // n_cols + 1, i % n_cols + 1
        color = PALETTE[i % len(PALETTE)]
        s = wide[name]
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines", line=dict(color=color, width=1.5),
            fill="tozeroy", fillcolor=_fade(color, 0.22), name=str(name),
            hovertemplate=f"{name} %{{x|%b %-d, %Y}}: %{{y:,.0f}}<extra></extra>",
        ), row=r, col=c)
        upper = upper_all if SHARED_Y else _nice_ceiling(s.max() * 1.05)
        lower = 0 if SHARED_Y or s.min() >= 0 else -_nice_ceiling(-s.min() * 1.05)
        fig.update_yaxes(range=[lower, upper], tickvals=[upper / 2, upper], tickformat=",",
                         showgrid=True, gridcolor=RULE, row=r, col=c)

    fig.update_annotations(font=dict(size=14, color=INK), xanchor="left")
    for ann, axis in zip(fig.layout.annotations, range(1, len(names) + 1)):
        ann.x = fig.layout[f"xaxis{axis if axis > 1 else ''}"].domain[0]
        ann.yshift = 8
    fig.update_xaxes(showgrid=False, showline=False, zeroline=False, ticks="",
                     tickfont=dict(size=10, color=MUTED))
    fig.update_yaxes(showline=False, zeroline=False, ticks="", tickfont=dict(size=10, color=MUTED))
    heading = (f"<b>{TITLE}</b><br>"
               f"<span style='font-size:13px;color:{MUTED}'>{SUBTITLE}</span>")
    fig.update_layout(
        title=dict(text=heading,
                   x=0.01, xanchor="left", y=1, yanchor="top", yref="container",
                   pad=dict(t=18), font=dict(size=18, color=INK)),
        font=dict(family=FONT, size=12, color=TEXT),
        paper_bgcolor=BG, plot_bgcolor=BG, width=900, height=260 * n_rows + 80,
        margin=dict(l=55, r=20, t=110, b=50), showlegend=False, hovermode="x unified",
    )
    fig.add_annotation(text=f"Source: {SOURCE_TEXT}", xref="paper", yref="paper", x=0, y=0,
                       yanchor="bottom", yshift=-44, xanchor="left", showarrow=False,
                       font=dict(size=9, color=FAINT))
    return fig
