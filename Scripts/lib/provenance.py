#!/usr/bin/env python3
"""
Whether an entry still renders the subject it was reverse-engineered from.

One implementation, used by both Stage D and the gallery. A second copy of this
would drift, and the whole premise of the provenance problem is two descriptions
of one thing disagreeing.

The comparison is a HEURISTIC: it reads the first FROM/JOIN table out of each
statement. It cannot see a repoint that keeps the table and changes the columns,
and it takes the first table in a join or CTE. Where the operator has recorded a
`Provenance` value on the row, that assertion wins and this is only a check
against it.
"""
from __future__ import annotations

import json
import re
from typing import Optional

# Two different reasons to withhold a field from Stage D.
#
# ALWAYS_STRIP: fields that carry a CAPTION -- a claim about what the data means.
# Captions belong to whoever renders the chart, never to the pipeline. Divergence
# made the wrong answer obvious, but it was not what made it wrong: a chart titled
# by the pipeline asserts a judgment the operator should own, whether or not the
# title happens to be accurate.
ALWAYS_STRIP = (
    "asset_name",       # the source chart's title -- would fill TITLE_TEXT
    "asset_note",       # prose about what the source chart shows
    "add_text",         # free text drawn on the source chart, e.g. a credit line
)

# REPOINT_STRIP: fields that describe the SOURCE chart's data rather than its
# encoding. Legitimate while an entry still renders its source subject; wrong the
# moment the data underneath changes.
REPOINT_STRIP = (
    "asset_url",        # the source screenshot; Stage D renders from data, not from it
    "sql",              # the original spec, superseded by final_sql
    "data_filter",      # describes which rows the SOURCE chart showed
    "sort_by",          # describes the SOURCE chart's ordering
    "default_color",
    "add_line",
    "layout_options",
    "axis_formatting",
)

# Kept for callers that want the full set.
PROVENANCE_KEYS = ALWAYS_STRIP + REPOINT_STRIP + ("highlight_map",)

# Recorded values for the `Provenance` select on the Notion row.
SOURCE_SUBJECT = "Renders source subject"
REPOINTED = "Repointed"
NOT_YET_BOUND = "Not yet bound"

_FROM = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][\w.]*)", re.I)


def first_table(sql: Optional[str]) -> Optional[str]:
    """The first table a statement reads from, lowercased and unqualified."""
    m = _FROM.search(sql or "")
    return m.group(1).lower().split(".")[-1] if m else None


def derive_state(original_sql: Optional[str], final_sql: Optional[str]) -> str:
    """Heuristic provenance state from the two SQL statements."""
    if not (final_sql or "").strip():
        return NOT_YET_BOUND
    a, b = first_table(original_sql), first_table(final_sql)
    if a and b and a != b:
        return REPOINTED
    return SOURCE_SUBJECT


def resolve_state(original_sql: Optional[str], final_sql: Optional[str],
                  recorded: Optional[str] = None) -> tuple[str, Optional[str]]:
    """
    Return (state, disagreement).

    A value recorded on the row wins; `disagreement` is set when the heuristic
    reaches a different conclusion, so the mismatch surfaces instead of one
    silently overriding the other.
    """
    derived = derive_state(original_sql, final_sql)
    if not recorded:
        return derived, None
    if recorded != derived:
        return recorded, (f"row records {recorded!r}; comparing SQL tables suggests "
                          f"{derived!r} ({first_table(original_sql)} → {first_table(final_sql)})")
    return recorded, None


def is_repointed(original_sql: Optional[str], final_sql: Optional[str],
                 recorded: Optional[str] = None) -> bool:
    return resolve_state(original_sql, final_sql, recorded)[0] == REPOINTED


def split_highlight_map(raw) -> Optional[list]:
    """
    Reduce a highlight map to an ordered palette.

    The colours are encoding parameters and reusable. The keys are labels --
    "Arrests increased", "Doubled", "Tripled or more" -- and a label is a caption
    for a category, so it goes the way every other caption goes.
    """
    value = raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    if isinstance(value, dict) and value:
        return [v for v in value.values() if isinstance(v, str)] or None
    if isinstance(value, list) and value:
        return [v for v in value if isinstance(v, str)] or None
    return None


def strip_provenance(parameters: dict, *, repointed: bool) -> tuple[dict, list[str]]:
    """
    Remove source-chart fields from a parameter set bound for the LLM.

    Returns (filtered, dropped_keys). Caption-bearing fields go unconditionally;
    data-describing fields go only when the entry has been repointed. The
    highlight map is not dropped but reduced: `highlight_palette` keeps its
    colours and loses its labels.
    """
    kept, dropped = {}, []
    for k, v in parameters.items():
        if k in ALWAYS_STRIP:
            dropped.append(k)
            continue
        if k == "highlight_map":
            palette = split_highlight_map(v)
            dropped.append("highlight_map")
            if palette and not repointed:
                # Colours survive while the entry still renders its source subject.
                kept["highlight_palette"] = palette
            continue
        if repointed and k in REPOINT_STRIP:
            dropped.append(k)
            continue
        kept[k] = v
    return kept, dropped
