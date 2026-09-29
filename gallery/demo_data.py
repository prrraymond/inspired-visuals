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
# 1. Before/after trend  (CHT-678195)
# --------------------------------------------------------------------------- #
_TREND_VALUES = [
    818_000, 843_000, 861_000, 872_000, 858_000, 889_000,
    905_000, 918_000, 944_000, 971_000, 1_002_000, 1_046_000,
    612_000, 588_000, 631_000, 668_000, 702_000, 744_000,
    771_000, 803_000, 828_000, 869_000, 901_000, 938_000,
]


def _trend() -> pd.DataFrame:
    return pd.DataFrame({
        "month": pd.date_range("2023-01-01", periods=len(_TREND_VALUES), freq="MS"),
        "value": _TREND_VALUES,
    })


# --------------------------------------------------------------------------- #
# 2. State comparison map  (CHT-6FBD47)
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


def _states() -> pd.DataFrame:
    return pd.DataFrame({
        "state":      [s[0] for s in _STATES],
        "label":      [s[1] for s in _STATES],
        "value":      [s[4] for s in _STATES],
        "lat":        [s[2] for s in _STATES],
        "lon":        [s[3] for s in _STATES],
        "show_label": [s[0] in _LABELLED for s in _STATES],
    })


# --------------------------------------------------------------------------- #
# 3. Small-multiple comparison  (CHT-85FB02)
# --------------------------------------------------------------------------- #
_GROUPS = {
    "Group A": [112, 118, 121, 115, 108,  96,  88,  93, 101, 107, 110],
    "Group B": [ 94,  91,  87,  92,  99, 104, 111, 118, 124, 121, 116],
    "Group C": [103, 106, 109, 113, 117, 119, 122, 126, 129, 131, 134],
    "Group D": [131, 127, 122, 118, 112, 106,  99,  94,  89,  85,  82],
    "Group E": [ 97, 101,  96, 102,  98, 105,  99, 103,  96, 100,  95],
    "Group F": [ 86,  89,  95, 104, 115, 123, 118, 109,  97,  91,  88],
}
_YEARS = list(range(2014, 2025))


def _multiples() -> pd.DataFrame:
    rows = []
    for group, series in _GROUPS.items():
        for year, value in zip(_YEARS, series):
            rows.append({"group": group, "year": year, "value": value})
    return pd.DataFrame(rows)


BUILDERS = {
    "CHT-678195": _trend,
    "CHT-6FBD47": _states,
    "CHT-85FB02": _multiples,
}


def demo_frame(chartid: str) -> pd.DataFrame | None:
    """A fresh copy every call -- callers edit what they get back."""
    build = BUILDERS.get(chartid)
    return build() if build else None
