"""Reusable Plotly template: stacked areas over time, optionally as shares of 100.

Shape (from the notebook's stacked_area, after a stacked-area page chart):
  - Bands stacked bottom to top in the order the groups first appear in the data
  - Each band labelled inside itself, about 60% of the way across, where it is
    thick enough to hold the text; no legend
  - Value axis on the right; 0-100 with quarter ticks when stacked to shares
"""
import pandas as pd
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Column placeholders -- long form, one row per period per band.
# ---------------------------------------------------------------------------
x_column = "period"        # dates or years along the x-axis
band_column = "group"      # one band per distinct value, first one at the bottom
value_column = "value"     # the measure

TITLE = "Chart title"
SUBTITLE = "Units / measure description"
SOURCE_TEXT = "Source / credit"

NORMALIZE = True           # stack each period to 100
ROLLING = None             # e.g. 7 for a rolling mean over that many rows
INLINE_LABELS = True
PALETTE = ["#1a4e66", "#c4543a", "#e8a63a", "#5a8a6a", "#8c7aa0", "#d4806a",
           "#4a7c8f", "#b5894e"]

FONT = "Helvetica, Arial, sans-serif"
INK, TEXT, MUTED, FAINT, RULE, BG = "#1A1A1A", "#333333", "#888888", "#AAAAAA", "#E5E5E5", "#FFFFFF"


def _fade(color, alpha):
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def build_figure(df):
    d = df[[x_column, band_column, value_column]].copy()
    if not pd.api.types.is_numeric_dtype(d[x_column]):
        d[x_column] = pd.to_datetime(d[x_column])
    d[value_column] = pd.to_numeric(d[value_column], errors="coerce")
    order = list(dict.fromkeys(d[band_column].dropna()))
    wide = d.pivot_table(index=x_column, columns=band_column, values=value_column,
                         aggfunc="sum").sort_index()
    wide = wide[[g for g in order if g in wide.columns]]
    if ROLLING and ROLLING > 1:
        wide = wide.rolling(int(ROLLING), min_periods=1).mean()
    if NORMALIZE:
        wide = wide.div(wide.sum(axis=1), axis=0) * 100
    suffix = "%" if NORMALIZE else ""

    fig = go.Figure()
    for i, g in enumerate(wide.columns):
        base = PALETTE[i % len(PALETTE)]
        fig.add_trace(go.Scatter(
            x=wide.index, y=wide[g], name=str(g), mode="lines", stackgroup="one",
            fillcolor=_fade(base, 0.55), line=dict(width=0.5, color=base),
            hovertemplate=f"{g}: %{{y:,.1f}}{suffix}<extra></extra>",
        ))

    if INLINE_LABELS and len(wide):
        k = int(len(wide) * 0.6)
        total = 100 if NORMALIZE else wide.sum(axis=1).max()
        below = 0.0
        for g in wide.columns:
            band = float(wide[g].iloc[k])
            if total and band / total >= 0.06:
                fig.add_annotation(x=wide.index[k], y=below + band / 2, showarrow=False,
                                   text=str(g), font=dict(size=11, color="#555555"))
            below += band

    fig.update_xaxes(showgrid=False, showline=False, zeroline=False, ticks="",
                     tickfont=dict(size=11, color=MUTED))
    fig.update_yaxes(showgrid=False, showline=False, zeroline=False, ticks="",
                     tickfont=dict(size=11, color=MUTED), side="right", ticksuffix=suffix,
                     **({"range": [0, 100], "tickvals": [0, 25, 50, 75, 100]} if NORMALIZE else {}))
    heading = (f"<b>{TITLE}</b><br>"
               f"<span style='font-size:13px;color:{MUTED}'>{SUBTITLE}</span>")
    fig.update_layout(
        title=dict(text=heading,
                   x=0.01, xanchor="left", y=1, yanchor="top", yref="container",
                   pad=dict(t=18), font=dict(size=18, color=INK)),
        font=dict(family=FONT, size=12, color=TEXT),
        paper_bgcolor=BG, plot_bgcolor=BG, width=650, height=500,
        margin=dict(l=30, r=50, t=80, b=55), showlegend=False, hovermode="x unified",
    )
    fig.add_annotation(text=f"Source: {SOURCE_TEXT}", xref="paper", yref="paper", x=0, y=0,
                       yanchor="bottom", yshift=-49, xanchor="left", showarrow=False,
                       font=dict(size=9, color=FAINT))
    return fig
