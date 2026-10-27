import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Diverging bar chart template
#
# Expected DataFrame columns:
#   x_column     -> ordered categorical labels (e.g. ranked bins / groups).
#                   The row order of `df` defines the plotting order.
#   y_column     -> signed numeric values (positive = above baseline,
#                   negative = below baseline).
# ---------------------------------------------------------------------------

x_column = "category"   # categorical / ordinal label column
y_column = "value"      # signed numeric column

POSITIVE_COLOR = "#71a79c"
NEGATIVE_COLOR = "#c75b1c"


def _format_value(v):
    """Signed label used both for bar text and for category labels."""
    return f"{v:+.1f}%"


def build_figure(df):
    categories = df[x_column].astype(str).tolist()
    values = df[y_column].astype(float).tolist()

    colors = [POSITIVE_COLOR if v >= 0 else NEGATIVE_COLOR for v in values]
    text_colors = colors

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=categories,
            y=values,
            marker=dict(color=colors, line=dict(width=0)),
            text=[_format_value(v) for v in values],
            textposition="outside",
            textfont=dict(size=15, color=text_colors),
            cliponaxis=False,
            hovertemplate="%{x}: %{y:+.1f}<extra></extra>",
            name="Series 1",
            showlegend=False,
        )
    )

    # Zero baseline drawn as a strong horizontal rule
    fig.add_hline(y=0, line=dict(color="#222222", width=2))

    # Category labels are placed inside the plot, flipped to the opposite side
    # of the baseline from each bar (annotation-dependent axis labelling).
    span = max([abs(v) for v in values] + [1.0])
    offset = span * 0.05
    for cat, val in zip(categories, values):
        if val >= 0:
            y_pos, anchor = -offset, "top"
        else:
            y_pos, anchor = offset, "bottom"
        fig.add_annotation(
            x=cat,
            y=y_pos,
            text=cat,
            showarrow=False,
            yanchor=anchor,
            font=dict(size=14, color="#666666"),
        )

    fig.update_layout(
        title=dict(
            text="<b>Chart title</b><br><span style='font-size:15px;color:#777777'>"
                 "Units / measure description</span>",
            x=0.01,
            xanchor="left",
            font=dict(size=21, color="#111111"),
        ),
        bargap=0.12,
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=40, r=40, t=110, b=80),
        xaxis=dict(
            type="category",
            categoryorder="array",
            categoryarray=categories,
            showticklabels=False,  # labels are drawn as in-plot annotations
            showgrid=False,
            zeroline=False,
            showline=False,
            ticks="",
            title=None,
        ),
        yaxis=dict(
            showgrid=False,
            zeroline=False,
            showticklabels=False,
            showline=False,
            ticks="",
            title=None,
            range=[min(values) - span * 0.30, max(values) + span * 0.25],
        ),
    )

    # Source / credit line
    fig.add_annotation(
        x=0,
        y=-0.12,
        xref="paper",
        yref="paper",
        text="Source / credit",
        showarrow=False,
        xanchor="left",
        font=dict(size=12, color="#999999"),
    )

    return fig