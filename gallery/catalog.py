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

import pathlib

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
        "colors": [{"const": "BAR_COLOR", "label": "Bars"}],
        "attribution": {"designer": None, "url": None},
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
        "colors": [{"const": "POSITIVE_COLOR", "label": "Above zero"},
                   {"const": "NEGATIVE_COLOR", "label": "Below zero"}],
        "attribution": {"designer": None, "url": None},
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
        "colors": [{"const": "COLOR_1", "label": "First part"},
                   {"const": "COLOR_2", "label": "Second part"}],
        "attribution": {"designer": None, "url": None},
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
        "colors": [{"const": "ACCENT", "label": "Line"}],
        "attribution": {"designer": None, "url": None},
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
        "colors": [{"const": "POSITIVE_COLOR", "label": "Above zero"},
                   {"const": "NEGATIVE_COLOR", "label": "Below zero"}],
        "attribution": {"designer": None, "url": None},
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
        "colors": [{"const": "PALETTE", "index": 0, "label": "First group"},
                   {"const": "PALETTE", "index": 1, "label": "Second group"}],
        "attribution": {"designer": None, "url": None},
        "controls": [],
    },
}

# --------------------------------------------------------------------------- #
# Stories
# --------------------------------------------------------------------------- #
# A story is a template that opens with real data and a real headline instead of a
# placeholder dataset -- the charts from viz_code_v20261025.ipynb, adapted from
# published designs and remixed with our own warehouse data. The template itself
# is as generic as any other (it passes the same caption gate); the story's words
# live here, as captions, and its data is a snapshot in stories/data/ written by
# Scripts/export_story_data.py.
#
# `template` names a file in stories/templates/. Several stories share one.
STORIES_DIR = pathlib.Path(__file__).parent / "stories"


def _palette(n: int, noun: str) -> list[dict]:
    return [{"const": "PALETTE", "index": i, "label": f"{noun} {i + 1}"} for i in range(n)]


STORIES: dict[str, dict] = {
    "story-stocks-vs-mood": {
        "name": "Stocks soared. The public's mood didn't.",
        "form": "Indexed lines on a split axis",
        "template": "split_axis",
        "job": "Compare how several measures moved from the same starting point, even "
               "when one runs far ahead of the rest.",
        "traits": ["Indexed to 100", "Split axis", "Several series"],
        "needs": "One row per period per series — a date, the series name and its value. "
                 "Each series is indexed to 100 at the first period they all share.",
        "mapping": {"date_column": "month", "series_column": "series",
                    "value_column": "value"},
        "measure": None,
        "derive": {},
        "captions": {"title": "Stocks soared. The public's mood didn't.",
                     "subtitle": "Monthly, indexed to Jan. 1980 = 100",
                     "source": "Yahoo Finance; University of Michigan; Gallup and other "
                               "polls via UCSB American Presidency Project"},
        "constants": {"REF_LABEL": "Start"},
        "colors": _palette(3, "Series"),
        "attribution": {"original": True},
        "controls": [{"const": "SPLIT", "label": "Break the axis at", "kind": "number",
                      "help": "Index values above this are drawn in the upper panel."}],
    },
    "story-subway-recovery": {
        "name": "The subway's long climb back",
        "form": "Line with a headline change",
        "template": "line_headline",
        "job": "Show where one measure stands now, and how far it has moved over the "
               "past year, in the headline itself.",
        "traits": ["One series", "Latest date", "Change over a year"],
        "needs": "One row per date — a date and a number.",
        "mapping": {"date_column": "date", "value_column": "entries_daily_avg"},
        "measure": None,
        "derive": {},
        "captions": {"title": "Subway entries, average per day",
                     "source": "MTA hourly ridership via NY Open Data; weekly averages"},
        "constants": {"LINE_COLOR": "#1a4e66", "FILL": True, "CHANGE_SINCE": "1y"},
        "colors": [{"const": "LINE_COLOR", "label": "Line"}],
        "attribution": {"designer": "The New York Times", "url": None,
                        "source_chart": "CHT-774380", "confirmed": True},
        "controls": [],
    },
    "story-nfl-home-states": {
        "name": "Where NFL players grew up",
        "form": "Shaded state map",
        "template": "choropleth_scale",
        "job": "Show how a rate varies from state to state, shaded from low to high.",
        "traits": ["U.S. states", "One rate", "Single-hue scale"],
        "needs": "One row per state — a two-letter state code and a number. A third "
                 "column with the state's name is optional; it is shown on hover.",
        "mapping": {"state_column": "state_code", "value_column": "players_per_million",
                    "name_column": "state_name"},
        "measure": None,
        "derive": {},
        "captions": {"title": "Where NFL players grew up, 2025 season",
                     "subtitle": "Players who dressed for at least one game, per million "
                                 "residents of their home state",
                     "units": "Per million",
                     "source": "ESPN game-day rosters; Census ACS 1-year population"},
        "constants": {"CAP_QUANTILE": 0.97},
        "colors": [{"const": "COLOR_STOPS", "index": 0, "label": "Lowest"},
                   {"const": "COLOR_STOPS", "index": 3, "label": "Highest"}],
        "attribution": {"designer": "The New York Times", "url": None,
                        "source_chart": "CHT-0AC21B", "confirmed": False},
        "controls": [],
    },
    "story-stock-ownership": {
        "name": "Who owns stock, by income",
        "form": "Stacked area, shares of 100",
        "template": "stacked_area",
        "job": "Show how a total is divided among groups, and how the split shifts "
               "over time.",
        "traits": ["Shares of 100", "Over time", "Bands labelled in place"],
        "needs": "One row per period per group — a date or year, the group, and a number. "
                 "Groups stack in the order they first appear, first at the bottom.",
        "mapping": {"x_column": "year", "band_column": "income_group",
                    "value_column": "share_of_stock_owners"},
        "measure": None,
        "derive": {},
        "captions": {"title": "Who owns stock, by income percentile",
                     "subtitle": "Share of all families holding stock, directly or indirectly",
                     "source": "Federal Reserve, Survey of Consumer Finances"},
        "constants": {"NORMALIZE": True},
        "colors": _palette(6, "Band"),
        "attribution": {"designer": "The New York Times", "url": None,
                        "source_chart": "CHT-F3CC10", "confirmed": False},
        "controls": [],
    },
    "story-education-states": {
        "name": "How much school adults have finished",
        "form": "Stacked bars, shares of 100",
        "template": "stacked_bar",
        "job": "Compare how each group divides into the same ordered parts.",
        "traits": ["Shares of 100", "Ordered parts", "Values in the bars"],
        "needs": "One row per group per part — the group, the part, and a number. Bars "
                 "and parts keep the order they first appear in.",
        "mapping": {"group_column": "name", "part_column": "education",
                    "value_column": "share_pct"},
        "measure": None,
        "derive": {},
        "captions": {"title": "How much school adults have finished",
                     "subtitle": "Adults 25 and over, by highest level completed (%)",
                     "source": "Census Bureau, American Community Survey 5-year (B15003)"},
        "constants": {"HORIZONTAL": True, "NORMALIZE": True, "NUMBERS": "segments",
                      "LEGEND": "top", "WIDTH": 820, "HEIGHT": 520,
                      "PALETTE": ["#C8632A", "#E8A86B", "#E8D9B0", "#B9CFD6", "#6E9FB5",
                                  "#1a4e66"]},
        "colors": _palette(6, "Part"),
        "attribution": {"designer": "Pew Research Center", "url": None,
                        "source_chart": "CHT-167E58", "confirmed": False},
        "controls": [],
    },
    "story-owner-renter": {
        "name": "Owners and renters, by education",
        "form": "Stacked bars with a share on top",
        "template": "stacked_bar",
        "job": "Show how a whole splits across groups, and two parts within each group.",
        "traits": ["Two parts", "Share of the total", "Legend in the title"],
        "needs": "One row per group per part — the group, the part, and a number. Name "
                 "the parts in the title and they are coloured to match.",
        "mapping": {"group_column": "education", "part_column": "tenure",
                    "value_column": "estimate"},
        "measure": None,
        "derive": {},
        "captions": {"title": "Share of owner and renter households",
                     "subtitle": "By the householder's education; label is the share of "
                                 "all households",
                     "source": "Census Bureau, American Community Survey (B25013)"},
        "constants": {"NUMBERS": "share", "LEGEND": "title", "WIDTH": 620,
                      "PALETTE": ["#E8C170", "#A994C8"]},
        "colors": _palette(2, "Part"),
        "attribution": {"designer": "The New York Times", "url": None,
                        "source_chart": "CHT-131830", "confirmed": False},
        "controls": [],
    },
    "story-311-boroughs": {
        "name": "NYC 311 requests, borough by borough",
        "form": "Small multiples",
        "template": "small_multiples",
        "job": "Give each group its own panel on the same scale, so both their size and "
               "their shape over time compare at a glance.",
        "traits": ["One panel per group", "Shared scale", "Over time"],
        "needs": "One row per date per group — a date, the group, and a number.",
        "mapping": {"date_column": "date", "panel_column": "borough",
                    "value_column": "requests"},
        "measure": None,
        "derive": {},
        "captions": {"title": "NYC 311 requests per day",
                     "subtitle": "Weekly average, by borough",
                     "source": "NYC 311 Open Data"},
        "constants": {"SHARED_Y": True},
        "colors": _palette(5, "Panel"),
        "attribution": {"designer": "The New York Times", "url": None,
                        "source_chart": "CHT-F846C9", "confirmed": True},
        "controls": [],
    },
    "story-subway-boroughs": {
        "name": "Subway entries, borough by borough",
        "form": "Small multiples, each on its own scale",
        "template": "small_multiples",
        "job": "Compare the shape of several series over time when their sizes are too "
               "different to share one scale.",
        "traits": ["One panel per group", "Own scale each", "Over time"],
        "needs": "One row per date per group — a date, the group, and a number.",
        "mapping": {"date_column": "date", "panel_column": "borough",
                    "value_column": "entries"},
        "measure": None,
        "derive": {},
        "captions": {"title": "Subway entries by borough",
                     "subtitle": "Average per day by week, last two years; each panel on "
                                 "its own scale",
                     "source": "MTA hourly ridership via NY Open Data"},
        "constants": {"SHARED_Y": False},
        "colors": _palette(5, "Panel"),
        "attribution": {"designer": "The New York Times", "url": None,
                        "source_chart": "CHT-F846C9", "confirmed": True},
        "controls": [],
    },
    "story-311-share": {
        "name": "Each borough's share of 311",
        "form": "Stacked area, shares of 100",
        "template": "stacked_area",
        "job": "Show how a total is divided among groups, and how the split shifts "
               "over time.",
        "traits": ["Shares of 100", "Over time", "Bands labelled in place"],
        "needs": "One row per date per group — a date, the group, and a number. Groups "
                 "stack in the order they first appear, first at the bottom.",
        "mapping": {"x_column": "date", "band_column": "borough",
                    "value_column": "requests"},
        "measure": None,
        "derive": {},
        "captions": {"title": "NYC 311 requests by borough",
                     "subtitle": "Share of weekly volume",
                     "source": "NYC 311 Open Data"},
        "constants": {"NORMALIZE": True},
        "colors": _palette(5, "Band"),
        "attribution": {"designer": "The New York Times", "url": None,
                        "source_chart": "CHT-F3CC10", "confirmed": False},
        "controls": [],
    },
    "story-sp500-year": {
        "name": "The S&P 500's year",
        "form": "Line with a headline change",
        "template": "line_headline",
        "job": "Show where one measure stands now, and how far it has moved over the "
               "past year, in the headline itself.",
        "traits": ["One series", "Latest date", "Change over a year"],
        "needs": "One row per date — a date and a number.",
        "mapping": {"date_column": "date", "value_column": "close"},
        "measure": None,
        "derive": {},
        "captions": {"title": "S&P 500", "source": "Yahoo Finance"},
        "constants": {"CHANGE_SINCE": "1y"},
        "colors": [{"const": "LINE_COLOR", "label": "Line"}],
        "attribution": {"designer": "The New York Times", "url": None,
                        "source_chart": "CHT-774380", "confirmed": True},
        "controls": [],
    },
    "story-311-week": {
        "name": "One week of 311, by borough",
        "form": "Bar chart with values",
        "template": "bar_values",
        "job": "Rank a handful of groups by one number, with the number printed on "
               "every bar.",
        "traits": ["Largest first", "Every bar labelled", "One colour each"],
        "needs": "One row per group — a group name and a number.",
        "mapping": {"label_column": "borough", "value_column": "requests"},
        "measure": None,
        "derive": {},
        "captions": {"title": "311 requests by borough",
                     "subtitle": "Feb. 2 – Feb. 8, 2026",
                     "source": "NYC 311 Open Data"},
        "constants": {},
        "colors": _palette(5, "Bar"),
        "attribution": {"designer": None, "url": None},
        "controls": [],
    },
}

for _spec in STORIES.values():
    _spec["story"] = True
CATALOG.update(STORIES)

# Designer credit (PRD R16). Every template is adapted from someone's published
# chart, and that person is owed a credit. The six basic templates are not sourced
# yet -- the Notion row's Asset URL is the screenshot in storage, not the
# publication -- so each is a placeholder, shown as one, until a person fills it in.
#
# The stories' credits were matched by eye against the library's source
# screenshots (`source_chart`). `confirmed: False` marks a likely match that a
# person has not checked; no publication URLs are recorded yet. A story drawn from
# no one's design says so (`original`).
ATTRIBUTION_PLACEHOLDER = "original designer (credit to be added)"


def attribution(chartid: str) -> dict:
    """{designer, url, placeholder, original} for the "Design adapted from" line."""
    a = (CATALOG.get(chartid) or {}).get("attribution") or {}
    original = bool(a.get("original"))
    return {"designer": a.get("designer"), "url": a.get("url"), "original": original,
            "placeholder": not (a.get("designer") or original)}


# Display order on the library page: stories first, then the basic shapes --
# simplest form first, map last.
STORY_ORDER = ["story-stocks-vs-mood", "story-subway-recovery", "story-nfl-home-states",
               "story-stock-ownership", "story-education-states", "story-owner-renter",
               "story-311-boroughs", "story-subway-boroughs", "story-311-share",
               "story-sp500-year", "story-311-week"]
BASIC_ORDER = ["CHT-77B304", "CHT-BC77C6", "CHT-26F750",
               "CHT-3389CA", "CHT-ABA629", "CHT-2AAEE9"]
ORDER = STORY_ORDER + BASIC_ORDER


def entry(chartid: str) -> dict | None:
    return CATALOG.get(chartid)


def has(chartid: str) -> bool:
    return chartid in CATALOG


def is_story(chartid: str) -> bool:
    return chartid in STORIES


def story_template(chartid: str) -> str | None:
    """The source of a story's template, read from the repo. None for anything else."""
    spec = STORIES.get(chartid)
    if spec is None:
        return None
    path = STORIES_DIR / "templates" / f"{spec['template']}.py"
    return path.read_text() if path.exists() else None


def story_data_path(chartid: str) -> pathlib.Path | None:
    if chartid not in STORIES:
        return None
    return STORIES_DIR / "data" / f"{chartid}.csv"
