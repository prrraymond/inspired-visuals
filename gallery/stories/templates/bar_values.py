"""Reusable Plotly template: vertical bars with the value on top of each.

Shape (from the notebook's bar_chart):
  - One bar per group, largest first, each in its own colour
  - The value printed above every bar; no value axis, a solid baseline rule
"""
import pandas as pd
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Column placeholders -- one row per group.
# ---------------------------------------------------------------------------
label_column = "group"     # bar labels
value_column = "value"     # bar heights

TITLE = "Chart title"
SUBTITLE = "Units / measure description"
SOURCE_TEXT = "Source / credit"

SORT = True                # largest first; False keeps the data's order
PALETTE = ["#1a4e66", "#c4543a", "#e8a63a", "#5a8a6a", "#8c7aa0", "#d4806a",
           "#4a7c8f", "#b5894e"]

FONT = "Helvetica, Arial, sans-serif"
INK, TEXT, MUTED, FAINT, RULE, BG = "#1A1A1A", "#333333", "#888888", "#AAAAAA", "#E5E5E5", "#FFFFFF"


def build_figure(df):
    d = df[[label_column, value_column]].copy()
    d[value_column] = pd.to_numeric(d[value_column], errors="coerce")
    d = d.dropna()
    if SORT:
        d = d.sort_values(value_column, ascending=False)
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(d))]

    fig = go.Figure(go.Bar(
        x=d[label_column].astype(str), y=d[value_column], marker=dict(color=colors, line_width=0),
        text=[f"{v:,.0f}" for v in d[value_column]], textposition="outside",
        textfont=dict(size=13, color=INK), cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>%{y:,.0f}<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color=TEXT, width=1.5))
    fig.update_yaxes(visible=False, range=[0, d[value_column].max() * 1.15])
    fig.update_xaxes(showgrid=False, showline=False, zeroline=False, ticks="",
                     tickfont=dict(size=12, color="#555555"))
    heading = (f"<b>{TITLE}</b><br>"
               f"<span style='font-size:13px;color:{MUTED}'>{SUBTITLE}</span>")
    fig.update_layout(
        title=dict(text=heading,
                   x=0.01, xanchor="left", y=1, yanchor="top", yref="container",
                   pad=dict(t=18), font=dict(size=18, color=INK)),
        font=dict(family=FONT, size=12, color=TEXT),
        paper_bgcolor=BG, plot_bgcolor=BG, width=680, height=450,
        margin=dict(l=50, r=30, t=90, b=60), showlegend=False, bargap=0.3,
    )
    fig.add_annotation(text=f"Source: {SOURCE_TEXT}", xref="paper", yref="paper", x=0, y=0,
                       yanchor="bottom", yshift=-54, xanchor="left", showarrow=False,
                       font=dict(size=9, color=FAINT))
    return fig
