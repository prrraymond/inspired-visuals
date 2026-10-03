#!/usr/bin/env python3
"""
Product copy for the templates — authored here, not derived from Notion.

The catalog rows describe the SOURCE chart each template was reverse-engineered
from: "Increase in Arrests by U.S. State", "Profit and Loss Ratios...". Those are
subjects, and a subject is the one thing a reusable template must not carry. The
`Subject`, `Description` and `Chart notes` properties are all empty, so nothing in
the catalog answers the only question a person browsing actually has -- *what is
this chart FOR?*

That answer has to be written. It lives here rather than in Notion because the
metadata model should not grow a column to serve a prototype; if this survives,
the right move is a `Purpose` property, not more of this file.

Names and one-liners are DRAFTS. Rewrite them freely -- nothing reads them but the
library page.
"""
from __future__ import annotations

CATALOG: dict[str, dict] = {
    "CHT-678195": {
        "name": "Before/after trend",
        "form": "Line chart",
        "job": "Show how a measure changes over time around an important breakpoint.",
        "traits": ["Over time", "One measure", "Two regimes"],
        "needs": "One row per time period — a date and a number.",
        # Demo mapping: template role -> demo column. Explicit, so the demo path
        # never has to guess and never shows a mapping screen.
        "mapping": {"x_column": "month", "y_column": "value"},
        "measure": "value",
        "derive": {},
        "captions": {"title": "Monthly total", "subtitle": "Sample data"},
        # The two shaded bands are the whole point of this chart, and where they
        # meet was decided by a rule nobody could see. It is a control now.
        "controls": [
            {"const": "SPLIT_X", "label": "Breakpoint", "kind": "date",
             "column": "month", "auto": "midpoint",
             "help": "The shaded bands change here — everything before it is one "
                     "regime, everything after it the other."},
        ],
    },
    "CHT-6FBD47": {
        "name": "State comparison map",
        "form": "Choropleth map",
        "job": "Show how a measure varies geographically across U.S. states, "
               "grouped into value ranges.",
        "traits": ["U.S. states", "Value ranges", "Labelled highlights"],
        "needs": "One row per state — a two-letter state code and a number.",
        "mapping": {
            "state_column": "state", "value_column": "value",
            "label_column": "label", "lat_column": "lat", "lon_column": "lon",
            "label_flag_column": "show_label",
        },
        "measure": "value",
        # `category` is not a column the user supplies: it is the PRODUCT of the
        # value ranges. Deriving it is what makes the map categorical.
        "derive": {"category": "value"},
        "captions": {"title": "Measure by state", "source": "Sample data"},
        "controls": [],
    },
    "CHT-85FB02": {
        "name": "Small-multiple comparison",
        "form": "Faceted bar chart",
        "job": "Compare movement above and below a baseline across several groups "
               "over time.",
        "traits": ["Several groups", "Over time", "Above/below a baseline"],
        "needs": "One row per group and period — a group name, a period and a number.",
        "mapping": {"facet_column": "group", "x_column": "year", "y_column": "value"},
        "measure": "value",
        "derive": {},
        # `above` / `below` are left unset: the template's own canonical
        # placeholders already say exactly that, and repeating them here would be
        # two places to change one word.
        "captions": {"title": "Measure by group, 2014–2024", "units": "Index",
                     "source": "Sample data"},
        "controls": [
            {"const": "GRID_STEP", "label": "Gridline step", "kind": "number",
             "auto": "computed",
             "help": "The dotted line sits this far above the baseline, so panels "
                     "can be compared by eye."},
        ],
    },
}

# Display order on the library page. Simplest form first.
ORDER = ["CHT-678195", "CHT-6FBD47", "CHT-85FB02"]


def entry(chartid: str) -> dict | None:
    return CATALOG.get(chartid)


def has(chartid: str) -> bool:
    return chartid in CATALOG
