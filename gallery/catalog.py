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
    "CHT-77B304": {
        "name": "Ranked comparison",
        "form": "Bar chart",
        "job": "Show how a measure climbs or falls across groups that have a "
               "natural order.",
        "traits": ["Ordered groups", "One measure", "Ends called out"],
        "needs": "One row per group — a group name and a number.",
        "mapping": {"x_column": "group", "y_column": "value"},
        "measure": "value",
        "derive": {},
        "captions": {"title": "Measure by group", "source": "Sample data"},
        "controls": [],
    },
    "CHT-BC77C6": {
        "name": "Gains and losses",
        "form": "Bar chart around zero",
        "job": "Show which groups gained and which lost, across groups that have "
               "a natural order.",
        "traits": ["Above/below zero", "Ordered groups", "Every bar labelled"],
        "needs": "One row per group — a group name and a number that may be "
                 "negative.",
        "mapping": {"x_column": "group", "y_column": "change"},
        "measure": "change",
        "derive": {},
        "captions": {"title": "Change by group", "source": "Sample data"},
        "controls": [],
    },
    "CHT-26F750": {
        "name": "Two-part split",
        "form": "Stacked bar",
        "job": "Compare how a two-way split differs between groups.",
        "traits": ["Two parts", "Several groups", "Shares of 100"],
        "needs": "One row per group — a group name and two numbers that add up "
                 "to 100.",
        "mapping": {"category_column": "group",
                    "value_column_1": "share_first",
                    "value_column_2": "share_second"},
        "measure": "share_first",
        "derive": {},
        "captions": {"title": "Split by group", "source": "Sample data"},
        "controls": [],
    },
    "CHT-3389CA": {
        "name": "Measure against a baseline",
        "form": "Line chart",
        "job": "Show how a measure moves above and below a reference level "
               "across an ordered range.",
        "traits": ["Reference lines", "Ordered range", "Endpoint called out"],
        "needs": "One row per position — a position along the range and a number.",
        "mapping": {"x_column": "position", "y_column": "ratio"},
        "measure": "ratio",
        "derive": {},
        "captions": {"title": "Measure against the baseline", "source": "Sample data"},
        # The template ships three reference lines all labelled with the same
        # generic placeholder. Naming them is what makes the form readable.
        "constants": {"REFERENCE_LINES": [(2.0, "Upper reference", False),
                                          (1.0, "Baseline", True),
                                          (0.5, "Lower reference", False)]},
        "controls": [],
    },
    "CHT-ABA629": {
        "name": "Net agreement",
        "form": "Diverging bar chart",
        "job": "Compare how far several statements land on one side or the other "
               "of neutral.",
        "traits": ["Two directions", "Labelled statements", "Diverges from zero"],
        "needs": "One row per statement — the statement and a number that may be "
                 "negative.",
        "mapping": {"label_column": "statement", "value_column": "net"},
        "measure": "net",
        "derive": {},
        "captions": {"title": "Net position by statement", "source": "Sample data"},
        "controls": [],
    },
    "CHT-2AAEE9": {
        "name": "Highlight map",
        "form": "Choropleth map",
        "job": "Show which U.S. states fall into each of a few groups.",
        "traits": ["U.S. states", "A few groups", "Labelled states"],
        "needs": "One row per state — a two-letter state code and the group it "
                 "belongs to.",
        "mapping": {"location_column": "state_code", "category_column": "category",
                    "label_column": "label", "lat_column": "lat", "lon_column": "lon"},
        # The category is a column the user supplies here, not something derived
        # from the numbers, so there is no measure and nothing to bin.
        "measure": None,
        "derive": {},
        "captions": {"title": "States by group", "source": "Sample data"},
        # Order fixes which group gets the accent colour. Left to first-appearance
        # in the data it was whichever state happened to sort first, so the
        # highlighted group was the one below the threshold.
        "constants": {"category_order": ["Above threshold", "Below threshold"]},
        "controls": [],
    },
}

# Display order on the library page: simplest form first, map last.
ORDER = ["CHT-77B304", "CHT-BC77C6", "CHT-26F750",
         "CHT-3389CA", "CHT-ABA629", "CHT-2AAEE9"]


def entry(chartid: str) -> dict | None:
    return CATALOG.get(chartid)


def has(chartid: str) -> bool:
    return chartid in CATALOG
