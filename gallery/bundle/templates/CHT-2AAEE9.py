"""Abstract template: categorical (discrete) choropleth map of US states
with per-state text labels, a top-placed legend, a free-floating note
annotation and a source/credit line.

Expected DataFrame columns (rename the placeholders below to match your data):
  location_column : two-letter USA state codes, e.g. "CA", "TX" (one row per state)
  category_column : discrete category each state belongs to (drives the fill colour)
  label_column    : optional short text drawn on the map for that state
  lat_column      : optional latitude for placing the label
  lon_column      : optional longitude for placing the label
"""

import plotly.graph_objects as go

# ---------------------------------------------------------------- placeholders
location_column = "state_code"      # USA-states location codes
category_column = "category"        # discrete grouping -> discrete fill colour
label_column = "label"              # optional on-map text label
lat_column = "lat"                  # optional label latitude
lon_column = "lon"                  # optional label longitude

# Explicit category order controls legend order and colour assignment.
# Set to None to derive the order from the data.
category_order = None               # e.g. ["Category A", "Category B", "Category C"]

# Discrete palette cycled across categories (colour choice is cosmetic only).
PALETTE = ["#8f7fc4", "#9e9e9e", "#dcdcdc", "#6baed6", "#fdae6b"]


def _categories(df):
    """Return the ordered list of categories present in the data."""
    if category_order:
        return [c for c in category_order if c in set(df[category_column])]
    seen, out = set(), []
    for value in df[category_column]:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def build_figure(df):
    fig = go.Figure()

    cats = _categories(df)

    # One choropleth trace per category => discrete colouring + a legend entry.
    for i, cat in enumerate(cats):
        sub = df[df[category_column] == cat]
        colour = PALETTE[i % len(PALETTE)]
        fig.add_trace(
            go.Choropleth(
                locations=sub[location_column],
                locationmode="USA-states",
                z=[i] * len(sub),
                colorscale=[[0, colour], [1, colour]],
                showscale=False,
                marker_line_color="white",
                marker_line_width=1,
                name=str(cat),
                showlegend=True,
                hovertemplate="%{location}<extra>" + str(cat) + "</extra>",
            )
        )

    # Optional on-map text labels (requires lat/lon columns).
    if label_column in df.columns and lat_column in df.columns and lon_column in df.columns:
        labelled = df.dropna(subset=[label_column, lat_column, lon_column])
        if len(labelled):
            fig.add_trace(
                go.Scattergeo(
                    locationmode="USA-states",
                    lat=labelled[lat_column],
                    lon=labelled[lon_column],
                    text=labelled[label_column],
                    mode="text",
                    textfont=dict(size=10, color="#333333"),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

    fig.update_geos(
        scope="usa",
        projection_type="albers usa",
        showland=True,
        landcolor="#e9e9e9",
        showlakes=False,
        showframe=False,
        showcoastlines=False,
        bgcolor="white",
    )

    fig.update_layout(
        title=dict(text="Chart title", x=0.02, xanchor="left", y=0.97,
                   font=dict(size=16)),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=1.06,
            xanchor="left",
            x=0.02,
        ),
        margin=dict(l=10, r=10, t=90, b=60),
        paper_bgcolor="white",
        plot_bgcolor="white",
        annotations=[
            # Free-floating explanatory note placed over the map.
            dict(
                text="Annotation text",
                x=0.55, y=0.08,
                xref="paper", yref="paper",
                showarrow=False,
                align="left",
                font=dict(size=11, color="#7a7a7a"),
            ),
            # Source / credit line.
            dict(
                text="Source / credit",
                x=1.0, y=-0.06,
                xref="paper", yref="paper",
                showarrow=False,
                xanchor="right",
                font=dict(size=11, color="#555555"),
            ),
            # Optional units / measure description under the title.
            dict(
                text="Units / measure description",
                x=0.02, y=1.13,
                xref="paper", yref="paper",
                showarrow=False,
                xanchor="left",
                font=dict(size=12, color="#666666"),
            ),
        ],
    )

    return fig