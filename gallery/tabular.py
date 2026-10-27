#!/usr/bin/env python3
"""
Moving a table between pandas and the browser without losing what it is.

The workspace keeps the working dataset in the page, not on the server: there is
no run id, no session, nothing to expire between an edit and the render that
follows it. That makes the round-trip the only place types can be lost, so both
directions live here rather than being re-improvised at each call site.
"""
from __future__ import annotations

import io
import math

import numpy as np
import pandas as pd

NUMERIC, TEMPORAL, TEXT, BOOL = "number", "date", "text", "boolean"


def coerce(df: pd.DataFrame) -> pd.DataFrame:
    """
    Give text columns the type they are really holding.

    A CSV has no types; every column arrives as text and a numeric column that
    stays text is the difference between a chart and a refusal. The 0.9 threshold
    lets a stray blank or an 'n/a' through without turning a text column numeric
    on the strength of a few digits.
    """
    df = df.copy()
    for c in df.columns:
        if df[c].dtype != object:
            continue
        s = df[c]
        lowered = s.astype(str).str.strip().str.lower()
        if lowered.isin(("true", "false", "")).all() and lowered.isin(("true", "false")).any():
            df[c] = lowered.map({"true": True, "false": False})
            continue
        num = pd.to_numeric(s, errors="coerce")
        if num.notna().mean() > 0.9:
            df[c] = num
            continue
        try:
            dt = pd.to_datetime(s, errors="coerce", format="mixed")
            if dt.notna().mean() > 0.9:
                df[c] = dt
        except Exception:
            pass
    return df


def kind_of(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return BOOL
    if pd.api.types.is_numeric_dtype(series):
        return NUMERIC
    if pd.api.types.is_datetime64_any_dtype(series):
        return TEMPORAL
    return TEXT


def _cell(value, kind: str):
    """One cell, JSON-safe, in the form the grid should show it."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if kind == TEMPORAL:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        # Midnight on every row means the column is dates, not timestamps; showing
        # "2023-01-01T00:00:00" in a cell someone has to retype is just noise.
        return ts.strftime("%Y-%m-%d") if ts.normalize() == ts else ts.isoformat(sep=" ")
    if kind == BOOL:
        return bool(value)
    if kind == NUMERIC:
        v = float(value)
        if pd.isna(v):
            return None
        return int(v) if float(v).is_integer() and abs(v) < 2**53 else round(v, 10)
    return str(value)


def to_grid(df: pd.DataFrame) -> dict:
    kinds = {str(c): kind_of(df[c]) for c in df.columns}
    cols = [str(c) for c in df.columns]
    rows = [[_cell(df.iloc[r][c], kinds[str(c)]) for c in df.columns] for r in range(len(df))]
    return {"columns": cols, "kinds": [kinds[c] for c in cols], "rows": rows}


def from_grid(columns: list, rows: list) -> pd.DataFrame:
    """Rebuild a frame from what the page sent back, then re-type it."""
    clean = [[None if v == "" else v for v in row] for row in rows]
    df = pd.DataFrame(clean, columns=[str(c) for c in columns])
    return coerce(df)


def _looks_numeric(value) -> bool:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    return not pd.isna(pd.to_numeric(str(value).strip(), errors="coerce"))


def first_row_is_data(raw: pd.DataFrame) -> bool:
    """
    Whether the first row of a headerless read is data rather than column names.

    A header is text. So the first row is data when it puts a number in a column
    whose other values are numbers -- a name never looks like that, and a pasted
    table with no header row always does, as long as it has a numeric column.
    A table that is text all the way down gets the benefit of the doubt: its
    first row is read as names, and the notice says so.
    """
    if len(raw) == 0:
        return False
    first = raw.iloc[0]
    if len(raw) == 1:
        return any(_looks_numeric(v) for v in first)
    for c in raw.columns:
        rest = raw[c].iloc[1:].dropna()
        rest = rest[rest.astype(str).str.strip() != ""]
        if len(rest) and rest.map(_looks_numeric).mean() > 0.9 and _looks_numeric(first[c]):
            return True
    return False


def _names(row) -> list[str]:
    """Column names from a header row. A blank or repeated name gets its position."""
    out, seen = [], set()
    for i, v in enumerate(row):
        name = "" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v).strip()
        if not name or name in seen:
            name = f"Column {i + 1}"
        seen.add(name)
        out.append(name)
    return out


def parse_table(text: str, header: bool | None = None) -> tuple[pd.DataFrame, bool]:
    """
    Parse pasted rows. Returns (frame, whether the first row was read as names).

    `header=None` decides from the data (see first_row_is_data); True or False is
    a person overriding that decision. Tabs win when present -- that is what a
    spreadsheet sends.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Nothing to read — the box was empty.")
    sep = "\t" if "\t" in text and text.count("\t") >= text.count(",") else ","
    raw = pd.read_csv(io.StringIO(text), sep=sep, header=None, dtype=str,
                      skip_blank_lines=True)
    if header is None:
        header = not first_row_is_data(raw)
    if header:
        names, body = _names(raw.iloc[0].tolist()), raw.iloc[1:]
    else:
        names, body = [f"Column {i + 1}" for i in range(raw.shape[1])], raw
    body = body.reset_index(drop=True)
    body.columns = names
    return coerce(body), bool(header)


def parse_text(text: str) -> pd.DataFrame:
    return parse_table(text)[0]


def parse_csv_bytes(raw: bytes) -> pd.DataFrame:
    return coerce(pd.read_csv(io.BytesIO(raw)))
