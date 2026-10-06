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


def parse_text(text: str) -> pd.DataFrame:
    """Parse pasted rows. Tabs win when present -- that is what a spreadsheet sends."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Nothing to read — the box was empty.")
    sep = "\t" if "\t" in text and text.count("\t") >= text.count(",") else ","
    return coerce(pd.read_csv(io.StringIO(text), sep=sep))


def parse_csv_bytes(raw: bytes) -> pd.DataFrame:
    return coerce(pd.read_csv(io.BytesIO(raw)))
