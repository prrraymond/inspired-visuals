"""
Abstract Plotly template: single line-with-markers chart over an ordered
percentile-style x axis, with horizontal reference gridlines annotated
inline (left-aligned labels sitting above the lines), a highlighted
end-point annotation, and directional axis end-labels.

Expected input DataFrame
------------------------
A tidy frame with one row per x position, already sorted along the x axis.

    x_column : numeric position along the horizontal axis (e.g. rank,
               percentile, index). Can be unevenly spaced -- the template
               plots it on a linear numeric axis.
    y_column : numeric value of the series (e.g. a ratio relative to a
               baseline). The baseline / reference values are configured
               below.
"""

import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Column placeholders -- point these at your own columns
# ---------------------------------------------------------------------------
x_column = "x_value"   # numeric x position (rank / percentile / index)
y_column = "y_value"   # numeric y value of the series

# ---------------------------------------------------------------------------
# Reference lines: (y value, inline label, is_primary_baseline)
# The primary baseline is drawn darker/solid; the others are light guides.
# ---------------------------------------------------------------------------
REFERENCE_LINES = [
    (2.0, "Annotation text", False),
    (1.0, "Annotation text", True),
    (0.5, "Annotation text", False),
]

# Tick positions / labels along the x axis (generic placeholders)
X_TICK_VALUES = [10, 30, 50, 70, 90, 99.9]
X_TICK_LABELS = ["Category A", "Category B", "Category C",
                 "Category D", "Category E", "Category F"]

# Index of the point to call out with an annotation (-1 = last point)
HIGHLIGHT_INDEX = -1

ACCENT = "#d2492a"
INK = "#121212"
GUIDE = "#dcdcdc"


def _add_reference_lines(fig, x_min, x_max):
    """Horizontal reference lines with left-aligned inline labels."""
    for y_val, label, is_primary in REFERENCE_LINES:
        fig.add_shape(
            type="line",
            xref="x", yref="y",
            x0=x_min, x1=x_max, y0=y_val, y1=y_val,
            line=dict(
                color=INK if is_primary else GUIDE,
                width=1.2 if is_primary else 1,
            ),
            layer="below",
        )
        fig.add_annotation(
            xref="x", yref="y",
            x=x_min, y=y_val,
            text=label,
            showarrow=False,
            xanchor="left", yanchor="bottom",
            font=dict(size=12, color="#555555"),
        )


def _add_highlight(fig, x_hi, y_hi):
    """Call-out annotation anchored to a single emphasised data point."""
    fig.add_annotation(
        xref="x", yref="y",
        x=x_hi, y=y_hi,
        text="<span style='color:#888888'>Annotation text</span>"
             "<br><b>Annotation text</b>",
        showarrow=False,
        xanchor="right", yanchor="bottom",
        align="right",
        yshift=12,
        font=dict(size=13, color=INK),
    )


def build_figure(df):
    """Build the figure from a tidy DataFrame (see module docstring)."""
    data = df.sort_values(x_column)
    x_vals = data[x_column].tolist()
    y_vals = data[y_column].tolist()

    x_min, x_max = min(x_vals), max(x_vals)
    pad = (x_max - x_min) * 0.04 if x_max > x_min else 1
    x_lo, x_hi_axis = x_min - pad, x_max + pad

    fig = go.Figure()

    _add_reference_lines(fig, x_lo, x_hi_axis)

    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="lines+markers",
            name="Series 1",
            line=dict(color=ACCENT, width=2.5),
            marker=dict(color=ACCENT, size=7),
            hovertemplate="Axis label: %{x}<br>Axis label: %{y:.2f}<extra></extra>",
        )
    )

    if x_vals:
        _add_highlight(fig, x_vals[HIGHLIGHT_INDEX], y_vals[HIGHLIGHT_INDEX])

    # Directional end-labels under the x axis
    for x_pos, text, anchor in (
        (0.0, "\u2190 Category A", "left"),
        (1.0, "Category B \u2192", "right"),
    ):
        fig.add_annotation(
            xref="paper", yref="paper",
            x=x_pos, y=-0.16,
            text=text,
            showarrow=False,
            xanchor=anchor, yanchor="top",
            font=dict(size=12, color=INK),
        )

    fig.add_annotation(
        xref="paper", yref="paper",
        x=0.5, y=-0.16,
        text="Axis label",
        showarrow=False,
        xanchor="center", yanchor="top",
        font=dict(size=12, color="#555555"),
    )

    fig.add_annotation(
        xref="paper", yref="paper",
        x=0, y=-0.30,
        text="Source / credit",
        showarrow=False,
        xanchor="left", yanchor="top",
        font=dict(size=11, color="#666666"),
    )

    fig.update_layout(
        title=dict(
            text="<b>Chart title</b><br>"
                 "<span style='font-size:13px;color:#666666'>"
                 "Units / measure description</span>",
            x=0, xanchor="left", y=0.95,
            font=dict(size=18, color=INK),
        ),
        showlegend=False,
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=60, r=40, t=110, b=130),
        height=620,
        width=780,
        hovermode="closest",
    )

    fig.update_xaxes(
        range=[x_lo, x_hi_axis],
        tickmode="array",
        tickvals=X_TICK_VALUES,
        ticktext=X_TICK_LABELS,
        ticks="outside",
        ticklen=6,
        tickcolor="#999999",
        showgrid=False,
        zeroline=False,
        showline=False,
        title=None,
        tickfont=dict(size=12, color=INK),
    )

    fig.update_yaxes(
        showgrid=False,
        zeroline=False,
        showline=False,
        showticklabels=False,
        title=None,
    )

    return fig


if __name__ == "__main__":
    import pandas as pd  # noqa: F401  (demo harness only)
    # Replace with your own DataFrame load, e.g.:
    # df = pd.read_csv("your_data.csv")
    # build_figure(df).show()
    pass