#!/usr/bin/env python3
"""
Derive a data_contract from a real dataframe.

Deliberately NOT model-authored. The model describes the template's placeholders;
this describes the data that will actually be fed to it. The difference is what
catches the two failure classes seen in practice:

  * bin thresholds a template hard-codes that don't span the real distribution
    (CATEGORY_EDGES = [100, 200, inf] against a 9.8-22.7 range)
  * columns that exist but are entirely NULL (station_daily.ridership_proxy)

Both are parameters the template cannot know and the SQL does not reveal.
"""
from __future__ import annotations
import pandas as pd
import numpy as np

LOW_CARD = 25          # at or below this, record the actual values
SAMPLE_N = 12


def _num(x):
    """JSON-safe scalar."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return float(x)
    return x


def derive_contract(df: pd.DataFrame, *, name: str | None = None) -> dict:
    contract: dict = {
        "name": name,
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": [],
    }
    for col in df.columns:
        s = df[col]
        entry = {
            "name": str(col),
            "dtype": str(s.dtype),
            "non_null": int(s.notna().sum()),
            "nulls": int(s.isna().sum()),
            "null_fraction": round(float(s.isna().mean()), 4),
            "distinct": int(s.nunique(dropna=True)),
        }
        # A column that is entirely null is a defect, not a statistic.
        entry["all_null"] = entry["non_null"] == 0

        if pd.api.types.is_numeric_dtype(s) and entry["non_null"]:
            v = pd.to_numeric(s, errors="coerce").dropna().astype(float)
            entry["kind"] = "numeric"
            entry["stats"] = {
                "min": _num(v.min()), "max": _num(v.max()),
                "mean": _num(round(v.mean(), 6)), "std": _num(round(v.std(), 6)) if len(v) > 1 else None,
                "q1": _num(v.quantile(0.25)), "median": _num(v.quantile(0.50)), "q3": _num(v.quantile(0.75)),
            }
            # Deciles, so equal-frequency binning can be derived exactly rather than
            # interpolated from the quartiles. Interpolating ignores skew: on a
            # right-skewed column it put 25/23/7 rows in three bins instead of ~18/18/19.
            entry["stats"]["deciles"] = {
                str(round(q, 1)): _num(round(v.quantile(q), 6)) for q in
                (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
            }
        elif pd.api.types.is_datetime64_any_dtype(s) and entry["non_null"]:
            entry["kind"] = "temporal"
            entry["stats"] = {"min": str(s.min()), "max": str(s.max())}
        else:
            entry["kind"] = "categorical"
            entry["cardinality"] = entry["distinct"]
            if 0 < entry["distinct"] <= LOW_CARD:
                entry["values"] = [str(x) for x in sorted(s.dropna().unique().tolist(), key=str)]
            elif entry["non_null"]:
                entry["sample_values"] = [str(x) for x in s.dropna().unique()[:SAMPLE_N].tolist()]
        contract["columns"].append(entry)
    return contract


def column(contract: dict, name: str) -> dict | None:
    return next((c for c in contract["columns"] if c["name"] == name), None)


def validate_bins(contract: dict, value_column: str, edges: list) -> list[str]:
    """
    Check a template's bin thresholds against the real distribution.

    Returns a list of problems; empty means the parameters are usable.
    This is the difference between a contract that documents and one that prevents.
    """
    problems = []
    c = column(contract, value_column)
    if c is None:
        return [f"value column {value_column!r} is not in the dataset "
                f"(available: {[x['name'] for x in contract['columns']]})"]
    if c["all_null"]:
        return [f"column {value_column!r} exists but is 100% NULL ({c['nulls']} rows)"]
    if c["kind"] != "numeric":
        return [f"column {value_column!r} is {c['kind']}, not numeric — cannot be binned"]

    lo, hi = c["stats"]["min"], c["stats"]["max"]
    finite = [e for e in edges if e not in (None, float("inf"), float("-inf"))]
    if not finite:
        return ["no finite bin edges supplied"]

    if min(finite) > hi:
        problems.append(
            f"every bin edge ({finite}) is above the data maximum ({hi}); "
            f"all {c['non_null']} rows collapse into the first bin")
    elif max(finite) < lo:
        problems.append(
            f"every bin edge ({finite}) is below the data minimum ({lo}); "
            f"all {c['non_null']} rows collapse into the last bin")
    else:
        outside = [e for e in finite if e < lo or e > hi]
        if outside:
            problems.append(f"bin edge(s) {outside} fall outside the data range [{lo}, {hi}] and split nothing")

    # occupancy: how many bins actually receive rows
    if c["stats"]["q1"] is not None:
        spread = [lo, c["stats"]["q1"], c["stats"]["median"], c["stats"]["q3"], hi]
        used = {sum(1 for e in finite if p > e) for p in spread}
        if len(used) == 1:
            problems.append(
                f"the quartile spread {spread} lands entirely in one bin — the chart will be single-coloured")
    if c["nulls"]:
        problems.append(f"{c['nulls']} of {contract['row_count']} rows are NULL in {value_column!r} and will not be drawn")
    return problems


def required_columns_present(contract: dict, required: list[str]) -> list[str]:
    have = {c["name"] for c in contract["columns"]}
    return [r for r in required if r not in have]
