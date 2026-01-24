import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import random

# Configuration
SEAT_WIDTH = 0.8
SEAT_HEIGHT = 1.2
SPACING_X = 1.0
SPACING_Y = 1.5
SEATS_PER_ROW = 5

def create_seat_grid(ax, num_seats, start_x, party_distribution, highlight_indices=None):
    """Create a grid of seat rectangles."""
    if highlight_indices is None:
        highlight_indices = []

    for i in range(num_seats):
        row = i // SEATS_PER_ROW
        col = i % SEATS_PER_ROW

        x = start_x + col * SPACING_X
        y = -row * SPACING_Y

        # Determine color
        color = '#5DADE2' if party_distribution[i] == 'D' else '#F1948A'

        # Create seat rectangle
        rect = mpatches.Rectangle((x, y), SEAT_WIDTH, SEAT_HEIGHT,
                                  facecolor=color, edgecolor='white', linewidth=2)
        ax.add_patch(rect)

        # Add highlight border if needed
        if i in highlight_indices:
            highlight_rect = mpatches.Rectangle((x-0.15, y-0.15), SEAT_WIDTH+0.3, SEAT_HEIGHT+0.3,
                                              facecolor='none', edgecolor='#666666', linewidth=3)
            ax.add_patch(highlight_rect)

def create_highlight_box(ax, seat_indices, start_x, label_text, label_y_offset=-2):
    """Create a bounding box around highlighted seats with label."""
    if not seat_indices:
        return

    rows = [idx // SEATS_PER_ROW for idx in seat_indices]
    cols = [idx % SEATS_PER_ROW for idx in seat_indices]

    min_row, max_row = min(rows), max(rows)
    min_col, max_col = min(cols), max(cols)

    x0 = start_x + min_col * SPACING_X - 0.2
    y0 = -max_row * SPACING_Y - 0.2
    x1 = start_x + max_col * SPACING_X + SEAT_WIDTH + 0.2
    y1 = -min_row * SPACING_Y + SEAT_HEIGHT + 0.2

    # Create bounding box
    box = mpatches.Rectangle((x0, y0), x1-x0, y1-y0,
                            facecolor='none', edgecolor='#888888', linewidth=2.5)
    ax.add_patch(box)

    # Add label with arrow
    label_x = (x0 + x1) / 2
    label_y = y0 + label_y_offset
    ax.annotate(label_text, xy=(label_x, y0), xytext=(label_x, label_y),
               fontsize=11, color='#666666', ha='center',
               bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor='#888888', alpha=0.9),
               arrowprops=dict(arrowstyle='-', color='#888888', lw=2))

# Create figure
fig, ax = plt.subplots(figsize=(14, 8))
ax.set_xlim(-2, 36)
ax.set_ylim(-18, 5)
ax.set_aspect('equal')
ax.axis('off')
ax.set_facecolor('#F5F5F5')
fig.patch.set_facecolor('#F5F5F5')

# Generate data
random.seed(42)  # For consistent output

# Category 1: 36 seats - most competitive
cat1_seats = 36
cat1_distribution = ['D'] * 18 + ['R'] * 18
random.shuffle(cat1_distribution)
cat1_highlight = [5, 6, 7, 10, 11, 12, 13, 15, 16, 17, 20, 21, 22, 25, 26, 27, 30, 31]

# Category 2: 26 seats - redistricted
cat2_seats = 26
cat2_distribution = ['D'] * 13 + ['R'] * 13
random.shuffle(cat2_distribution)
cat2_highlight = [3, 4, 5, 6, 8, 9, 10, 12, 13, 18, 19]

# Category 3: 49 seats - without incumbents
cat3_seats = 49
cat3_distribution = ['D'] * 24 + ['R'] * 25
random.shuffle(cat3_distribution)
cat3_highlight = [44, 45, 46]

# Starting positions
x_positions = [0, 15, 30]

# Category 1
create_seat_grid(ax, cat1_seats, x_positions[0], cat1_distribution, cat1_highlight)
create_highlight_box(ax, cat1_highlight, x_positions[0], '18 are tossups', -3)
ax.text(x_positions[0] + 2, 3, '36\nseats are most\ncompetitive',
        fontsize=14, weight='bold', ha='center', va='bottom', color='#333333')

# Category 2
create_seat_grid(ax, cat2_seats, x_positions[1], cat2_distribution, cat2_highlight)
create_highlight_box(ax, cat2_highlight, x_positions[1], '11 or so are\nin discussion', -2.5)
ax.text(x_positions[1] + 2, 3, '26\nredistricted or\nunder discussion',
        fontsize=14, weight='bold', ha='center', va='bottom', color='#333333')

# Category 3
create_seat_grid(ax, cat3_seats, x_positions[2], cat3_distribution, cat3_highlight)
create_highlight_box(ax, cat3_highlight, x_positions[2], '3 are most competitive', -1.5)
ax.text(x_positions[2] + 2, 3, '49\nwithout\nincumbents',
        fontsize=14, weight='bold', ha='center', va='bottom', color='#333333')

# Title
plt.suptitle('Congressional Seat Distribution Analysis', fontsize=18, weight='bold', color='#333333', y=0.98)

plt.tight_layout()
plt.savefig('seat_visualization.png', dpi=150, bbox_inches='tight', facecolor='#F5F5F5')
print("Saved visualization to seat_visualization.png")
