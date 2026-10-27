"""Reusable Plotly template: U.S. states shaded along a single-hue scale.

Shape (from the notebook's state_choropleth, after a state-map page chart):
  - Continuous sequential colour from a light to a dark stop, white state borders
  - Small vertical colour bar at the lower right, titled with the unit
  - Optionally capped at a quantile so one outlier does not wash out the rest
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Column placeholders -- one row per state.
# ---------------------------------------------------------------------------
state_column = "state_code"   # two-letter USPS codes ("TX")
value_column = "value"        # the measure
name_column = "state_name"    # optional: the name shown on hover

TITLE = "Chart title"
SUBTITLE = "Units / measure description"
SOURCE_TEXT = "Source / credit"
UNIT_LABEL = "Value"

COLOR_STOPS = ["#EFE8F5", "#B49BD0", "#7B5AA0", "#4A2373"]
CAP_QUANTILE = None           # e.g. 0.97

FONT = "Helvetica, Arial, sans-serif"
INK, TEXT, MUTED, FAINT, RULE, BG = "#1A1A1A", "#333333", "#888888", "#AAAAAA", "#E5E5E5", "#FFFFFF"


def build_figure(df):
    d = df.copy()
    z = pd.to_numeric(d[value_column], errors="coerce")
    zmax = float(z.quantile(CAP_QUANTILE)) if CAP_QUANTILE else float(z.max())
    names = d[name_column] if name_column in d.columns else d[state_column]
    stops = np.linspace(0, 1, len(COLOR_STOPS))
    fig = go.Figure(go.Choropleth(
        locations=d[state_column].astype(str).str.upper(), locationmode="USA-states", z=z,
        zmin=0, zmax=zmax, colorscale=[[float(s), c] for s, c in zip(stops, COLOR_STOPS)],
        marker_line_color="#FFFFFF", marker_line_width=1,
        customdata=np.stack([names.astype(str)], axis=-1),
        hovertemplate="<b>%{customdata[0]}</b><br>%{z:,.1f}<extra></extra>",
        colorbar=dict(title=dict(text=UNIT_LABEL, font=dict(size=11)), thickness=12, len=0.45,
                      x=0.93, y=0.35, outlinewidth=0, tickfont=dict(size=10)),
    ))
    fig.update_geos(scope="usa", projection_type="albers usa", showlakes=True, lakecolor=BG,
                    bgcolor=BG, landcolor="#E8E8E8", showframe=False)
    heading = (f"<b>{TITLE}</b><br>"
               f"<span style='font-size:13px;color:{MUTED}'>{SUBTITLE}</span>")
    fig.update_layout(
        title=dict(text=heading,
                   x=0.01, xanchor="left", y=1, yanchor="top", yref="container",
                   pad=dict(t=18), font=dict(size=18, color=INK)),
        font=dict(family=FONT, size=12, color=TEXT),
        paper_bgcolor=BG, plot_bgcolor=BG, width=900, height=560,
        margin=dict(l=10, r=10, t=80, b=40), showlegend=False,
    )
    fig.add_annotation(text=f"Source: {SOURCE_TEXT}", xref="paper", yref="paper", x=0, y=0,
                       yanchor="bottom", yshift=-34, xanchor="left", showarrow=False,
                       font=dict(size=9, color=FAINT))
    return fig
