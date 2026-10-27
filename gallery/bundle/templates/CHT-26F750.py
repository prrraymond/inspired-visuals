import plotly.graph_objects as go

# ----------------------------------------------------------------------
# Template: 100% horizontal stacked bar (two-part "share" bars)
#
# Expected tidy-ish wide DataFrame `df` with one row per category:
#   category_column : str   -> label shown on the y-axis (e.g. group name)
#   value_column_1  : float -> first (left) segment, e.g. share in percent
#   value_column_2  : float -> second (right) segment; the two should sum to 100
#
# Rows are plotted top-to-bottom in the order they appear in the DataFrame.
# ----------------------------------------------------------------------

category_column = "category"   # categorical axis labels
value_column_1 = "value_1"     # left / primary segment (numeric, percent)
value_column_2 = "value_2"     # right / secondary segment (numeric, percent)

COLOR_1 = "#8FB8BC"
COLOR_2 = "#F8C676"


def _labels(values, first_with_suffix=True, suffix="%"):
    """Format segment labels; optionally only the first row carries the unit."""
    out = []
    for i, v in enumerate(values):
        txt = f"{v:g}"
        if first_with_suffix and i == 0:
            txt += suffix
        out.append(txt)
    return out


def build_figure(df):
    categories = df[category_column].tolist()
    v1 = df[value_column_1].tolist()
    v2 = df[value_column_2].tolist()

    fig = go.Figure()

    # First (left) segment -- label anchored inside, at the left edge
    fig.add_trace(
        go.Bar(
            x=v1,
            y=categories,
            orientation="h",
            name="Series 1",
            marker=dict(color=COLOR_1, line=dict(width=0)),
            text=_labels(v1),
            textposition="inside",
            insidetextanchor="start",
            textfont=dict(size=16, color="#20343a"),
            hovertemplate="%{y}: %{x}<extra>Series 1</extra>",
        )
    )

    # Second (right) segment -- label anchored inside, at the right edge
    fig.add_trace(
        go.Bar(
            x=v2,
            y=categories,
            orientation="h",
            name="Series 2",
            marker=dict(color=COLOR_2, line=dict(width=0)),
            text=_labels(v2, first_with_suffix=False),
            textposition="inside",
            insidetextanchor="end",
            textfont=dict(size=16, color="#20343a"),
            hovertemplate="%{y}: %{x}<extra>Series 2</extra>",
        )
    )

    fig.update_layout(
        barmode="stack",
        bargap=0.45,
        title=dict(
            text="<b>Chart title</b><br><span style='font-size:14px'>Units / measure description</span>",
            x=0,
            xanchor="left",
            y=0.95,
            font=dict(size=20, color="#111111"),
        ),
        showlegend=False,  # column headers act as the legend (see annotations)
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=130, r=30, t=120, b=70),
        height=420,
        xaxis=dict(
            range=[0, 100],
            showgrid=False,
            zeroline=False,
            showticklabels=False,
            fixedrange=True,
            title=None,
        ),
        yaxis=dict(
            autorange="reversed",  # keeps DataFrame row order top-to-bottom
            showgrid=False,
            zeroline=False,
            showline=False,
            ticks="",
            tickfont=dict(size=15, color="#222222"),
            title=None,
        ),
        annotations=[
            # Header labels standing in for a legend, above each stack side
            dict(
                x=0, y=1.03, xref="x", yref="paper",
                text="<b>Series 1</b>", showarrow=False,
                xanchor="left", yanchor="bottom",
                font=dict(size=15, color="#111111"),
            ),
            dict(
                x=100, y=1.03, xref="x", yref="paper",
                text="<b>Series 2</b>", showarrow=False,
                xanchor="right", yanchor="bottom",
                font=dict(size=15, color="#111111"),
            ),
            # Source / credit line
            dict(
                x=0, y=-0.16, xref="paper", yref="paper",
                text="Source / credit", showarrow=False,
                xanchor="left", yanchor="top",
                font=dict(size=13, color="#777777"),
            ),
        ],
    )

    return fig


if __name__ == "__main__":
    import pandas as pd

    demo = pd.DataFrame(
        {
            category_column: ["Category A", "Category B", "Category C", "Category D"],
            value_column_1: [83, 90, 84, 74],
            value_column_2: [17, 11, 17, 26],
        }
    )
    build_figure(demo).show()