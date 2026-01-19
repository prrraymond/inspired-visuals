# Congressional Seat Visualization

This visualization recreates a political seat distribution chart using Plotly and Python, showing three categories of congressional seats with visual highlights for specific subsets.

## Overview

The visualization displays:

1. **36 seats are most competitive** - with 18 tossups highlighted
2. **26 redistricted or under discussion** - with 11 seats in discussion highlighted
3. **49 without incumbents** - with 3 most competitive seats highlighted

Each seat is represented as a colored rectangle:
- **Blue** represents Democratic-leaning seats
- **Red/Pink** represents Republican-leaning seats

Highlighted subsets are marked with gray borders and labeled with annotations.

## Installation

Install the required dependencies:

```bash
pip install -r requirements_plotly.txt
```

Or install individually:

```bash
pip install plotly numpy kaleido
```

## Usage

Run the visualization script:

```bash
python seat_visualization.py
```

This will:
1. Generate the interactive visualization
2. Display it in your default browser
3. Save an HTML file named `seat_visualization.html`

## Customization

You can modify the following parameters in `seat_visualization.py`:

### Visual Parameters
- `SEAT_WIDTH`: Width of each seat rectangle (default: 0.8)
- `SEAT_HEIGHT`: Height of each seat rectangle (default: 1.2)
- `SPACING_X`: Horizontal spacing between seats (default: 1.0)
- `SPACING_Y`: Vertical spacing between rows (default: 1.5)
- `SEATS_PER_ROW`: Number of seats per row (default: 5)

### Data Configuration
Modify the dummy data generation section to change:
- Number of seats in each category
- Party distribution (Democrat 'D' vs Republican 'R')
- Which seats to highlight
- Labels and annotations

### Example: Change highlighted seats in Category 1
```python
cat1_highlight = [0, 1, 2, 5, 6, 7]  # Highlight different seats
```

### Example: Change party distribution
```python
cat1_distribution = ['D'] * 20 + ['R'] * 16  # More Democratic seats
```

## Output

The visualization includes:
- Interactive Plotly chart that can be zoomed and panned
- Hover tooltips (can be enhanced with additional data)
- Responsive HTML file for sharing
- Clean, publication-ready styling

## Features

- **Grid Layout**: Automatically arranges seats in rows
- **Color Coding**: Visual party affiliation
- **Highlighting**: Border boxes around specific seat subsets
- **Annotations**: Labels explaining highlighted groups
- **Responsive**: Works on different screen sizes
- **Interactive**: Zoom, pan, and export functionality

## Export Options

The visualization can be exported as:
- HTML (default)
- PNG, JPG, PDF (requires kaleido)
- SVG for vector graphics

To export as static image:

```python
fig.write_image("seat_visualization.png", width=1200, height=700)
```

## License

This is a demonstration visualization using dummy data for educational purposes.
