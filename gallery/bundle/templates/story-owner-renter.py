"""Reusable Plotly template: stacked bars, one bar per group, one segment per part.

Shape (from the notebook's stacked_bar):
  - Vertical or horizontal bars; parts stack in the order they first appear
  - Optionally each bar normalised to 100 (shares)
  - Labels: inside each segment, the bar's total above it, or the bar's share of the
    grand total above it
  - Legend across the top, or no legend and the part names coloured in the title
"""
import re

import pandas as pd
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Column placeholders -- long form, one row per group per part.
# ---------------------------------------------------------------------------
group_column = "group"     # one bar per distinct value, in order of appearance
part_column = "part"       # one segment per distinct value, first one at the base
value_column = "value"     # the measure

TITLE = "Chart title"
SUBTITLE = "Units / measure description"
SOURCE_TEXT = "Source / credit"

HORIZONTAL = False
NORMALIZE = False          # each bar to 100
NUMBERS = "segments"       # "segments", "total", "share" or "none"
LEGEND = "top"             # "top", "title" (colour the part names in the title) or "none"
PALETTE = ["#1a4e66", "#c4543a", "#e8a63a", "#5a8a6a", "#8c7aa0", "#d4806a",
           "#4a7c8f", "#b5894e"]
WIDTH, HEIGHT = 680, 480

FONT = "Helvetica, Arial, sans-serif"
INK, TEXT, MUTED, FAINT, RULE, BG = "#1A1A1A", "#333333", "#888888", "#AAAAAA", "#E5E5E5", "#FFFFFF"


def _dark(color):
    c = color.lstrip("#")
    return sum(int(c[k:k + 2], 16) for k in (0, 2, 4)) < 380


def _title_with_parts(title, parts, colors):
    """Colour each part's name where it appears in the title, as an inline legend."""
    out = title
    for part, color in zip(parts, colors):
        pattern = re.compile(rf"\b({re.escape(str(part))})\b", re.I)
        out = pattern.sub(lambda m: f"<span style='color:{color}'>{m.group(1)}</span>", out, count=1)
    return out


def build_figure(df):
    d = df[[group_column, part_column, value_column]].copy()
    d[value_column] = pd.to_numeric(d[value_column], errors="coerce")
    groups = list(dict.fromkeys(d[group_column].dropna()))
    parts = list(dict.fromkeys(d[part_column].dropna()))
    wide = d.pivot_table(index=group_column, columns=part_column, values=value_column,
                         aggfunc="sum").reindex(index=groups, columns=parts).fillna(0.0)
    if NORMALIZE:
        wide = wide.div(wide.sum(axis=1), axis=0) * 100
    totals = wide.sum(axis=1)
    cats = [str(g) for g in groups]
    if HORIZONTAL:                                # first group at the top
        cats, wide, totals = cats[::-1], wide.iloc[::-1], totals.iloc[::-1]
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(parts))]
    fmt = ".0f" if NORMALIZE else ",.0f"
    suffix = "%" if NORMALIZE else ""

    fig = go.Figure()
    for i, (part, color) in enumerate(zip(parts, colors)):
        v = wide[part].tolist()
        is_top = i == len(parts) - 1
        text, pos = None, None
        if NUMBERS == "segments":
            # Skip slivers too thin to hold a number.
            text = [f"{x:{fmt}}" if x >= (8 if NORMALIZE else 0) else "" for x in v]
            pos = "inside"
        elif is_top and NUMBERS in ("total", "share"):
            text = ([f"{t:{fmt}}" for t in totals] if NUMBERS == "total"
                    else [f"{100 * t / totals.sum():.0f}%" for t in totals])
            pos = "outside"
        xy = dict(y=cats, x=v, orientation="h") if HORIZONTAL else dict(x=cats, y=v)
        fig.add_trace(go.Bar(
            **xy, name=str(part), marker=dict(color=color, line_width=0),
            text=text, textposition=pos, insidetextanchor="middle", cliponaxis=False,
            textfont=dict(size=11 if pos == "inside" else 12,
                          color="#FFFFFF" if _dark(color) and pos == "inside" else TEXT),
            hovertemplate=f"%{{{'y' if HORIZONTAL else 'x'}}}<br>{part}: "
                          f"%{{{'x' if HORIZONTAL else 'y'}:{fmt}}}{suffix}<extra></extra>",
        ))

    top = 100 if NORMALIZE else totals.max() * (1.12 if NUMBERS in ("total", "share") else 1.02)
    legend = LEGEND == "top"
    if HORIZONTAL:
        fig.update_xaxes(visible=False, range=[0, top])
        fig.update_yaxes(showgrid=False, showline=False, zeroline=False, ticks="",
                         tickfont=dict(size=12, color=INK), automargin=True)
        margin = dict(l=20, r=30, t=135 if legend else 100, b=50)
    else:
        fig.update_yaxes(visible=False, range=[0, top])
        fig.update_xaxes(showgrid=False, zeroline=False, ticks="", showline=True,
                         linecolor=INK, linewidth=1.5, tickfont=dict(size=12, color=INK))
        margin = dict(l=30, r=30, t=135 if legend else 100, b=60)

    head = _title_with_parts(TITLE, parts, colors) if LEGEND == "title" else TITLE
    heading = (f"<b>{head}</b><br>"
               f"<span style='font-size:13px;color:{MUTED}'>{SUBTITLE}</span>")
    fig.update_layout(
        title=dict(text=heading,
                   x=0.01, xanchor="left", y=1, yanchor="top", yref="container",
                   pad=dict(t=18), font=dict(size=18, color=INK)),
        font=dict(family=FONT, size=12, color=TEXT),
        paper_bgcolor=BG, plot_bgcolor=BG, width=WIDTH, height=HEIGHT, margin=margin,
        barmode="stack", bargap=0.25, showlegend=legend,
        legend=dict(orientation="h", x=0, y=1.02, xanchor="left", yanchor="bottom",
                    traceorder="normal", font=dict(size=11)),
    )
    fig.add_annotation(text=f"Source: {SOURCE_TEXT}", xref="paper", yref="paper", x=0, y=0,
                       yanchor="bottom", yshift=-(margin["b"] - 6), xanchor="left",
                       showarrow=False, font=dict(size=9, color=FAINT))
    return fig
