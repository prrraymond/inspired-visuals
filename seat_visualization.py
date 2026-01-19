import plotly.graph_objects as go
import numpy as np

# Configuration
SEAT_WIDTH = 0.8
SEAT_HEIGHT = 1.2
SPACING_X = 1.0
SPACING_Y = 1.5
SEATS_PER_ROW = 5

def create_seat_grid(num_seats, start_x, party_distribution, highlight_indices=None):
    """
    Create a grid of seat rectangles.

    Args:
        num_seats: Total number of seats
        start_x: Starting x position for the grid
        party_distribution: List of 'D' (Democrat/Blue) or 'R' (Republican/Red) for each seat
        highlight_indices: List of indices to highlight with border

    Returns:
        List of shapes (rectangles)
    """
    shapes = []
    annotations = []

    for i in range(num_seats):
        row = i // SEATS_PER_ROW
        col = i % SEATS_PER_ROW

        x0 = start_x + col * SPACING_X
        y0 = -row * SPACING_Y
        x1 = x0 + SEAT_WIDTH
        y1 = y0 + SEAT_HEIGHT

        # Determine color
        color = '#5DADE2' if party_distribution[i] == 'D' else '#F1948A'

        # Check if this seat should be highlighted
        is_highlighted = highlight_indices and i in highlight_indices

        # Create seat rectangle
        shapes.append(dict(
            type="rect",
            x0=x0, y0=y0, x1=x1, y1=y1,
            fillcolor=color,
            line=dict(color='white', width=2)
        ))

        # Add highlight border if needed
        if is_highlighted:
            shapes.append(dict(
                type="rect",
                x0=x0-0.15, y0=y0-0.15, x1=x1+0.15, y1=y1+0.15,
                fillcolor='rgba(0,0,0,0)',
                line=dict(color='#666666', width=3)
            ))

    return shapes

def create_highlight_box(seat_indices, start_x, label_text, label_x_offset=0, label_y_offset=-2):
    """Create a bounding box around highlighted seats with label."""
    shapes = []
    annotations = []

    if not seat_indices:
        return shapes, annotations

    # Calculate bounding box
    rows = [idx // SEATS_PER_ROW for idx in seat_indices]
    cols = [idx % SEATS_PER_ROW for idx in seat_indices]

    min_row, max_row = min(rows), max(rows)
    min_col, max_col = min(cols), max(cols)

    x0 = start_x + min_col * SPACING_X - 0.2
    y0 = -max_row * SPACING_Y - 0.2
    x1 = start_x + max_col * SPACING_X + SEAT_WIDTH + 0.2
    y1 = -min_row * SPACING_Y + SEAT_HEIGHT + 0.2

    # Create rounded rectangle highlight box
    shapes.append(dict(
        type="rect",
        x0=x0, y0=y0, x1=x1, y1=y1,
        fillcolor='rgba(0,0,0,0)',
        line=dict(color='#888888', width=2.5)
    ))

    # Add label annotation
    annotations.append(dict(
        x=(x0 + x1) / 2 + label_x_offset,
        y=y0 + label_y_offset,
        text=label_text,
        showarrow=True,
        arrowhead=0,
        arrowcolor='#888888',
        arrowwidth=2,
        ax=0,
        ay=-30,
        font=dict(size=13, color='#666666'),
        bgcolor='rgba(255,255,255,0.9)',
        borderpad=4
    ))

    return shapes, annotations

# Generate dummy data for three categories
# Category 1: 36 seats - most competitive (18 tossups highlighted)
cat1_seats = 36
cat1_distribution = ['D'] * 18 + ['R'] * 18
np.random.shuffle(cat1_distribution)
cat1_highlight = [5, 6, 7, 10, 11, 12, 13, 15, 16, 17, 20, 21, 22, 25, 26, 27, 30, 31]  # 18 tossups

# Category 2: 26 seats - redistricted or under discussion (11 in discussion)
cat2_seats = 26
cat2_distribution = ['D'] * 13 + ['R'] * 13
np.random.shuffle(cat2_distribution)
cat2_highlight = [3, 4, 5, 6, 8, 9, 10, 12, 13, 18, 19]  # 11 in discussion

# Category 3: 49 seats - without incumbents (3 most competitive)
cat3_seats = 49
cat3_distribution = ['D'] * 24 + ['R'] * 25
np.random.shuffle(cat3_distribution)
cat3_highlight = [44, 45, 46]  # 3 most competitive

# Create figure
fig = go.Figure()

# Starting positions for each category
x_positions = [0, 15, 30]
all_shapes = []
all_annotations = []

# Category 1: Most competitive seats
shapes1 = create_seat_grid(cat1_seats, x_positions[0], cat1_distribution, cat1_highlight)
all_shapes.extend(shapes1)

highlight_shapes1, highlight_annot1 = create_highlight_box(
    cat1_highlight, x_positions[0], "18 are tossups", label_y_offset=-3
)
all_shapes.extend(highlight_shapes1)
all_annotations.extend(highlight_annot1)

# Add title for category 1
all_annotations.append(dict(
    x=x_positions[0] + 2,
    y=3,
    text="<b>36</b><br>seats are most<br>competitive",
    showarrow=False,
    font=dict(size=16, color='#333333'),
    align='center'
))

# Category 2: Redistricted or under discussion
shapes2 = create_seat_grid(cat2_seats, x_positions[1], cat2_distribution, cat2_highlight)
all_shapes.extend(shapes2)

highlight_shapes2, highlight_annot2 = create_highlight_box(
    cat2_highlight, x_positions[1], "11 or so are<br>in discussion", label_y_offset=-2.5
)
all_shapes.extend(highlight_shapes2)
all_annotations.extend(highlight_annot2)

# Add title for category 2
all_annotations.append(dict(
    x=x_positions[1] + 2,
    y=3,
    text="<b>26</b><br>redistricted or<br>under discussion",
    showarrow=False,
    font=dict(size=16, color='#333333'),
    align='center'
))

# Category 3: Without incumbents
shapes3 = create_seat_grid(cat3_seats, x_positions[2], cat3_distribution, cat3_highlight)
all_shapes.extend(shapes3)

highlight_shapes3, highlight_annot3 = create_highlight_box(
    cat3_highlight, x_positions[2], "3 are most competitive", label_y_offset=-1.5
)
all_shapes.extend(highlight_shapes3)
all_annotations.extend(highlight_annot3)

# Add title for category 3
all_annotations.append(dict(
    x=x_positions[2] + 2,
    y=3,
    text="<b>49</b><br>without<br>incumbents",
    showarrow=False,
    font=dict(size=16, color='#333333'),
    align='center'
))

# Update layout
fig.update_layout(
    shapes=all_shapes,
    annotations=all_annotations,
    width=1200,
    height=700,
    plot_bgcolor='#F5F5F5',
    xaxis=dict(
        showgrid=False,
        showticklabels=False,
        zeroline=False,
        range=[-2, 36]
    ),
    yaxis=dict(
        showgrid=False,
        showticklabels=False,
        zeroline=False,
        range=[-18, 5]
    ),
    margin=dict(l=20, r=20, t=40, b=20),
    title=dict(
        text="Congressional Seat Distribution Analysis",
        font=dict(size=20, color='#333333'),
        x=0.5,
        xanchor='center'
    )
)

# Add dummy trace (required for plotly to render)
fig.add_trace(go.Scatter(
    x=[None],
    y=[None],
    mode='markers',
    showlegend=False
))

# Show the figure
fig.show()

# Optionally save as HTML
fig.write_html("seat_visualization.html")
print("Visualization saved as 'seat_visualization.html'")
