import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Diverging horizontal bar chart ("butterfly" / net-difference layout)
#
# Expected DataFrame columns:
#   label_column : str   -> category / item label, one per row (e.g. "question_id")
#   value_column : float -> signed net value; positive bars extend right,
#                           negative bars extend left of a zero baseline
#
# Rows are plotted top-to-bottom in the order they appear in `df`
# (sort beforehand, e.g. df = df.sort_values(value_column, ascending=False)).
# ---------------------------------------------------------------------------

label_column = "label_column"   # categorical label for each bar
value_column = "value_column"   # signed numeric value (can be + or -)

POSITIVE_COLOR = "#b9d4c8"
NEGATIVE_COLOR = "#e8a467"
TEXT_COLOR = "#222222"
BG_COLOR = "#f0f0f0"


def _fmt(v, first=False):
    """Format a signed value; optionally append a unit hint on the first bar."""
    sign = "+" if v > 0 else "\u2212"
    return f"{sign}{abs(v):g}"


def build_figure(df):
    labels = list(df[label_column])
    values = [float(v) for v in df[value_column]]

    # Reverse so the first row of the DataFrame appears at the TOP of the chart
    labels_r = labels[::-1]
    values_r = values[::-1]

    colors = [POSITIVE_COLOR if v >= 0 else NEGATIVE_COLOR for v in values_r]
    texts = [_fmt(v) for v in values_r]
    # Value text sits inside the bar, at the end furthest from the baseline
    text_positions = ["inside" for _ in values_r]

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=values_r,
            y=labels_r,
            orientation="h",
            marker=dict(color=colors, line=dict(width=0)),
            text=texts,
            textposition=text_positions,
            insidetextanchor="end",
            textfont=dict(color=TEXT_COLOR, size=15),
            hovertemplate="%{y}: %{x}<extra></extra>",
            showlegend=False,
            width=0.62,
        )
    )

    max_abs = max(abs(v) for v in values) if values else 1.0
    pad = max_abs * 0.9

    fig.update_layout(
        title=dict(text="Chart title", x=0, xanchor="left",
                   font=dict(size=20, color=TEXT_COLOR)),
        paper_bgcolor=BG_COLOR,
        plot_bgcolor=BG_COLOR,
        bargap=0.35,
        margin=dict(l=40, r=40, t=90, b=70),
        height=520,
        font=dict(family="Helvetica, Arial, sans-serif", color=TEXT_COLOR),
    )

    # X axis: hidden ticks, symmetric domain around the zero baseline
    fig.update_xaxes(
        range=[-max_abs - pad, max_abs + pad],
        showgrid=False,
        zeroline=False,
        showticklabels=False,
        ticks="",
        title_text="",
    )

    # Y axis: category labels are drawn as annotations instead, so hide them
    fig.update_yaxes(
        showgrid=False,
        zeroline=False,
        showticklabels=False,
        ticks="",
        title_text="",
    )

    # Vertical zero baseline
    fig.add_shape(
        type="line",
        x0=0, x1=0,
        y0=-0.5, y1=len(labels_r) - 0.5,
        xref="x", yref="y",
        line=dict(color="#555555", width=1.5),
    )

    # Side headers for the two directions
    fig.add_annotation(
        x=0, y=1.0, xref="x", yref="paper",
        xshift=-10, yshift=18,
        text="Below baseline", showarrow=False,
        xanchor="right", yanchor="bottom",
        font=dict(size=14, color="#555555"),
    )
    fig.add_annotation(
        x=0, y=1.0, xref="x", yref="paper",
        xshift=10, yshift=18,
        text="Above baseline", showarrow=False,
        xanchor="left", yanchor="bottom",
        font=dict(size=14, color="#555555"),
    )

    # Category labels placed on the OPPOSITE side of the baseline from the bar
    for lab, val in zip(labels_r, values_r):
        on_right = val < 0  # negative bar -> label to the right of baseline
        fig.add_annotation(
            x=0, y=lab, xref="x", yref="y",
            xshift=14 if on_right else -14,
            text=str(lab), showarrow=False,
            xanchor="left" if on_right else "right",
            yanchor="middle",
            align="left" if on_right else "right",
            font=dict(size=16, color=TEXT_COLOR),
        )

    # Units / measure description
    fig.add_annotation(
        x=0, y=1.0, xref="paper", yref="paper",
        # 48 put this level with the layout title and the two overlapped.
        yshift=16, text="Units / measure description",
        showarrow=False, xanchor="left", yanchor="bottom",
        font=dict(size=13, color="#666666"),
    )

    # Source / credit
    fig.add_annotation(
        x=1, y=0, xref="paper", yref="paper",
        yshift=-50, text="Source / credit",
        showarrow=False, xanchor="right", yanchor="top",
        font=dict(size=12, color="#888888"),
    )

    return fig


if __name__ == "__main__":
    import pandas as pd

    demo = pd.DataFrame({
        label_column: ["Category A", "Category B", "Category C", "Category D"],
        value_column: [14, 6, -12, -18],
    })
    build_figure(demo).show()