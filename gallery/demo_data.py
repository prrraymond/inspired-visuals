#!/usr/bin/env python3
"""
Demo datasets — one per template, so a chart appears the moment it is opened.

These are the SHAPE a template expects, filled with plausible numbers. They are
generic in MEANING (a "measure", not arrests or profit) but never generic in
STRUCTURE: a U.S. choropleth needs real USPS state codes, and a small-multiples
chart needs real facets. Structure is a requirement of the chart; subject is not.

The demo dataset is also the reference the user's own data is checked against --
`derive_contract(demo_df)` is what `input_check` compares a paste to. That makes
the answer to "what does this template need?" one thing, visible on screen, rather
than a schema written down somewhere else and hoped to still be true.
"""
from __future__ import annotations

import pandas as pd

# --------------------------------------------------------------------------- #
# Shared: U.S. state geography, for any map template.
# --------------------------------------------------------------------------- #
# Approximate label anchors. Real geography, because the chart is a real map.
_STATES = [
    ("AL", "Ala.",  32.8,  -86.8,  14), ("AK", "Alaska", 63.6, -152.4,  -6),
    ("AZ", "Ariz.", 34.3, -111.7,  41), ("AR", "Ark.",  34.9,  -92.4,   9),
    ("CA", "Calif.", 37.2, -119.5, 52), ("CO", "Colo.", 39.0, -105.5,  33),
    ("CT", "Conn.", 41.6,  -72.7,  -4), ("DE", "Del.",  39.0,  -75.5,  17),
    ("DC", "D.C.",  38.9,  -77.0,  58), ("FL", "Fla.",  28.6,  -82.4,  47),
    ("GA", "Ga.",   32.6,  -83.4,  26), ("HI", "Hawaii", 20.3, -156.4,   3),
    ("ID", "Idaho", 44.4, -114.6,  22), ("IL", "Ill.",  40.0,  -89.2,  38),
    ("IN", "Ind.",  39.9,  -86.3,  12), ("IA", "Iowa",  42.1,  -93.5,   7),
    ("KS", "Kan.",  38.5,  -98.4,  11), ("KY", "Ky.",   37.5,  -85.3,  19),
    ("LA", "La.",   31.1,  -92.0,  29), ("ME", "Maine", 45.4,  -69.2,  -9),
    ("MD", "Md.",   39.0,  -76.8,  31), ("MA", "Mass.", 42.3,  -71.8,   2),
    ("MI", "Mich.", 44.3,  -85.4,  16), ("MN", "Minn.", 46.3,  -94.3,   8),
    ("MS", "Miss.", 32.7,  -89.7,  24), ("MO", "Mo.",   38.4,  -92.5,  21),
    ("MT", "Mont.", 47.0, -109.6,  27), ("NE", "Neb.",  41.5,  -99.8,   5),
    ("NV", "Nev.",  39.3, -116.6,  44), ("NH", "N.H.",  43.7,  -71.6,  -2),
    ("NJ", "N.J.",  40.2,  -74.7,  23), ("NM", "N.M.",  34.4, -106.1,  36),
    ("NY", "N.Y.",  42.9,  -75.5,  34), ("NC", "N.C.",  35.5,  -79.4,  28),
    ("ND", "N.D.",  47.4, -100.5,   1), ("OH", "Ohio",  40.3,  -82.8,  15),
    ("OK", "Okla.", 35.6,  -97.5,  20), ("OR", "Ore.",  43.9, -120.6,  43),
    ("PA", "Pa.",   40.9,  -77.8,  18), ("RI", "R.I.",  41.7,  -71.6, -11),
    ("SC", "S.C.",  33.9,  -80.9,  25), ("SD", "S.D.",  44.4,  -100.2,  4),
    ("TN", "Tenn.", 35.8,  -86.4,  22), ("TX", "Texas", 31.4,  -99.3,  49),
    ("UT", "Utah",  39.3, -111.7,  39), ("VT", "Vt.",   44.1,  -72.7, -14),
    ("VA", "Va.",   37.5,  -78.9,  30), ("WA", "Wash.", 47.4, -120.5,  46),
    ("WV", "W.Va.", 38.6,  -80.6,  13), ("WI", "Wis.",  44.6,  -89.8,  10),
    ("WY", "Wyo.",  43.0, -107.6,   6),
]

# Six geographically spread units carry an in-map label, the way an editorial map
# annotates a handful rather than all fifty.
_LABELLED = {"CA", "TX", "FL", "NY", "IL", "WA"}


def _highlight_map() -> pd.DataFrame:
    """Which states meet a condition. Two categories, plus labels for a few."""
    rows = []
    for code, label, lat, lon, value in _STATES:
        rows.append({
            "state_code": code,
            "category": "Above threshold" if value >= 25 else "Below threshold",
            "label": label if code in _LABELLED else None,
            "lat": lat,
            "lon": lon,
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Ranked bars  (CHT-77B304)
# --------------------------------------------------------------------------- #
# Ordered groups with a measure that climbs steeply at the top -- the shape these
# charts exist to show, without which the form looks like any other bar chart.
_RANKED = [("Group A", 2.4), ("Group B", 3.1), ("Group C", 4.6), ("Group D", 6.8),
           ("Group E", 16.2), ("Group F", 29.4), ("Group G", 38.0)]


def _ranked() -> pd.DataFrame:
    return pd.DataFrame(_RANKED, columns=["group", "value"])


# --------------------------------------------------------------------------- #
# Gain/loss bars  (CHT-BC77C6)
# --------------------------------------------------------------------------- #
# Crosses zero, so the template's two-sided colouring and its label placement
# both have something to do.
_GAINLOSS = [("Group A", -3.9), ("Group B", -1.2), ("Group C", -0.4), ("Group D", 0.1),
             ("Group E", 0.5), ("Group F", 0.8), ("Group G", 1.1), ("Group H", 1.3),
             ("Group I", 1.5), ("Group J", 2.3)]


def _gainloss() -> pd.DataFrame:
    return pd.DataFrame(_GAINLOSS, columns=["group", "change"])


# --------------------------------------------------------------------------- #
# Two-part split  (CHT-26F750)
# --------------------------------------------------------------------------- #
# Each row sums to 100: the template draws shares, and a row that does not add up
# would silently misdraw rather than fail.
_SPLIT = [("All", 83, 17), ("Group A", 90, 10), ("Group B", 84, 16), ("Group C", 74, 26)]


def _split() -> pd.DataFrame:
    return pd.DataFrame(_SPLIT, columns=["group", "share_first", "share_second"])


# --------------------------------------------------------------------------- #
# Line against a baseline  (CHT-3389CA)
# --------------------------------------------------------------------------- #
# x spans the template's tick values (10 to 99.9) and y sits either side of 1.0,
# so the reference lines land inside the data rather than off the top.
_BASELINE = [(10, 1.05), (20, 1.18), (30, 1.12), (40, 1.14), (50, 1.06), (60, 1.02),
             (70, 0.96), (75, 0.88), (80, 0.90), (85, 0.86), (90, 0.93), (95, 1.02),
             (97, 1.12), (99, 1.35), (99.5, 1.60), (99.9, 2.20)]


def _baseline() -> pd.DataFrame:
    return pd.DataFrame(_BASELINE, columns=["position", "ratio"])


# --------------------------------------------------------------------------- #
# Diverging bars  (CHT-ABA629)
# --------------------------------------------------------------------------- #
_DIVERGING = [("Statement A", 14), ("Statement B", 6),
              ("Statement C", -12), ("Statement D", -18)]


def _diverging() -> pd.DataFrame:
    return pd.DataFrame(_DIVERGING, columns=["statement", "net"])


BUILDERS = {
    "CHT-77B304": _ranked,
    "CHT-BC77C6": _gainloss,
    "CHT-26F750": _split,
    "CHT-3389CA": _baseline,
    "CHT-ABA629": _diverging,
    "CHT-2AAEE9": _highlight_map,
}


def demo_frame(chartid: str) -> pd.DataFrame | None:
    """A fresh copy every call -- callers edit what they get back."""
    build = BUILDERS.get(chartid)
    return build() if build else None
