"""Reusable Plotly template: ordered categorical bar chart with endpoint value labels.

Structure detected in the source screenshot:
  - Single-series vertical bar chart over an ordered categorical axis
  - Percent-formatted y-axis with horizontal gridlines only
  - Value labels annotated on the FIRST and LAST bars only
  - Directional arrow annotations below the axis marking the ordering of categories
  - Axis label centered beneath the category axis
  - Source / credit footnote beneath the plot
"""

import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Column placeholders -- map these to your own DataFrame columns.
# ---------------------------------------------------------------------------
x_column = "category"      # ordered categorical labels (e.g. ranked bins / groups)
y_column = "value"         # numeric magnitude per category (percent on a 0-100 scale)

# Explicit ordering of the categorical axis. Leave as None to use DataFrame order.
category_order = None      # e.g. ["Category A", "Category B", ...]

# Text placeholders (generic on purpose).
TITLE = "Chart title"
SUBTITLE = "Units / measure description"
X_AXIS_TITLE = "Axis label"
Y_AXIS_TITLE = ""          # y values are self-labelled via percent ticks
LEFT_DIRECTION_LABEL = "Below baseline"
RIGHT_DIRECTION_LABEL = "Above baseline"
SOURCE_TEXT = "Source / credit"

BAR_COLOR = "#cc4b16"
ACCENT_COLOR = "#cc4b16"
GRID_COLOR = "#d9d9d9"


def _ordered_frame(df):
    """Return x/y sequences honouring the optional explicit category order."""
    frame = df.copy()
    if category_order is not None:
        frame[x_column] = frame[x_column].astype("category")
        frame[x_column] = frame[x_column].cat.set_categories(
            category_order, ordered=True
        )
        frame = frame.sort_values(x_column)
    return list(frame[x_column]), list(frame[y_column])


def _endpoint_annotations(categories, values):
    """Value labels on the first and last bars only."""
    annotations = []
    if not categories:
        return annotations
    for idx in {0, len(categories) - 1}:
        annotations.append(
            dict(
                x=categories[idx],
                y=values[idx],
                text=f"{values[idx]:g}%",
                showarrow=False,
                yshift=16,
                font=dict(size=14, color=ACCENT_COLOR, family="Arial Black, Arial"),
                xref="x",
                yref="y",
            )
        )
    return annotations


def build_figure(df):
    """Build the bar chart figure from a tidy DataFrame.

    Expected columns:
      df[x_column] : ordered category labels (one row per category)
      df[y_column] : numeric values (percent, 0-100)
    """
    categories, values = _ordered_frame(df)

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=categories,
            y=values,
            name="Series 1",
            marker=dict(color=BAR_COLOR, line=dict(width=0)),
            hovertemplate="%{x}<br>%{y:.1f}%<extra></extra>",
            width=0.82,
        )
    )

    annotations = _endpoint_annotations(categories, values)

    # Directional cues beneath the categorical axis.
    annotations.extend(
        [
            dict(
                x=0.0,
                y=-0.17,
                xref="paper",
                yref="paper",
                xanchor="left",
                text=f"&#8592;  {LEFT_DIRECTION_LABEL.upper()}",
                showarrow=False,
                font=dict(size=12, color="#666666"),
            ),
            dict(
                x=1.0,
                y=-0.17,
                xref="paper",
                yref="paper",
                xanchor="right",
                text=f"{RIGHT_DIRECTION_LABEL.upper()}  &#8594;",
                showarrow=False,
                font=dict(size=12, color="#666666"),
            ),
            dict(
                x=0.5,
                y=-0.17,
                xref="paper",
                yref="paper",
                xanchor="center",
                text=X_AXIS_TITLE,
                showarrow=False,
                font=dict(size=12, color="#666666"),
            ),
            dict(
                x=0.0,
                y=-0.30,
                xref="paper",
                yref="paper",
                xanchor="left",
                yanchor="top",
                align="left",
                text=SOURCE_TEXT,
                showarrow=False,
                font=dict(size=12, color="#777777"),
            ),
        ]
    )

    fig.update_layout(
        title=dict(
            text=f"<b>{TITLE}</b><br><span style='font-size:14px;color:#666'>{SUBTITLE}</span>",
            x=0.0,
            xanchor="left",
            font=dict(size=18, color="#121212"),
        ),
        annotations=annotations,
        showlegend=False,
        bargap=0.22,
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=60, r=30, t=90, b=150),
        height=560,
        width=680,
        font=dict(family="Arial, Helvetica, sans-serif", size=12, color="#333333"),
    )

    fig.update_xaxes(
        type="category",
        categoryorder="array" if category_order is not None else "trace",
        categoryarray=category_order,
        showgrid=False,
        showline=True,
        linecolor="#bbbbbb",
        ticks="",
        tickfont=dict(size=12, color="#444444"),
    )

    fig.update_yaxes(
        title=dict(text=Y_AXIS_TITLE),
        showgrid=True,
        gridcolor=GRID_COLOR,
        gridwidth=1,
        zeroline=False,
        showline=False,
        ticks="",
        ticksuffix="%",
        tickfont=dict(size=12, color="#666666"),
        rangemode="tozero",
    )

    return fig


if __name__ == "__main__":
    import pandas as pd

    # Minimal smoke test with synthetic placeholder values.
    demo = pd.DataFrame(
        {
            x_column: [f"Category {c}" for c in "ABCDEFG"],
            y_column: [2.4, 3.6, 5.0, 7.2, 16.5, 29.5, 38.0],
        }
    )
    build_figure(demo).show()