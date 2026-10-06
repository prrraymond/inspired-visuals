#!/usr/bin/env python3
"""
Present a data contract to a human.

The contract was designed as a machine artifact -- a validation input for
render_guard. Displaying it raw is unreadable: nine deciles per numeric column,
null_fraction to four decimals, and an `all_null` boolean that only matters when
it is True. This module transforms rather than duplicates: nothing here is stored,
and the contract on disk stays the machine's shape.

The transformations that matter:
  * quantiles -> a positional distribution bar, because five numbers describing a
    spread are a picture, not a list
  * null counts -> a status word, since 0 nulls is the uninteresting case
  * proposals -> the accepted values first, reasoning second, provenance last
"""
from __future__ import annotations

import os
import sys
from typing import Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Scripts", "lib"))
from render_guard import is_reviewed, normalize_proposal, review_label  # noqa: E402


# pandas names its storage types, not the reader's idea of a type: a column of
# state codes is "object", which on screen reads as a column *called* object. The
# storage name is still true and still useful when debugging, so it stays -- behind
# the developer view -- while the page says what the column holds.
DTYPE_PLAIN = {
    "object": "text", "string": "text", "category": "text",
    "bool": "yes / no", "boolean": "yes / no",
}


def plain_dtype(dtype: str | None) -> str:
    if not dtype:
        return ""
    d = str(dtype)
    if d in DTYPE_PLAIN:
        return DTYPE_PLAIN[d]
    if d.startswith(("int", "uint", "float", "Int", "Float")):
        return "number"
    if d.startswith("datetime") or d.startswith("timedelta"):
        return "date"
    return d


def _fmt(v: Any, sig: int = 4) -> str:
    """Numbers a human reads. Large magnitudes get thousands separators, not e-notation."""
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int,)) and not isinstance(v, bool):
        return f"{v:,}"
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return f"{int(v):,}"
        if abs(v) >= 10000:
            return f"{v:,.0f}"
        return f"{round(v, sig):g}"
    return str(v)


def describe_column(col: dict) -> dict:
    """One column, flattened for display."""
    kind = col.get("kind")
    nulls = col.get("nulls", 0)
    total = col.get("non_null", 0) + nulls

    if col.get("all_null"):
        completeness, severity = "empty — every row is null", "bad"
    elif nulls:
        completeness, severity = f"{nulls} of {total} rows null", "warn"
    else:
        completeness, severity = "complete", "ok"

    out = {
        "name": col.get("name"),
        "kind": kind,
        "dtype": plain_dtype(col.get("dtype")),
        "raw_dtype": col.get("dtype"),
        "distinct": col.get("distinct"),
        "completeness": completeness,
        "severity": severity,
        "summary": "",
        "spread": None,
        "sample": None,   # NB: not "values" -- dict.values shadows it in Jinja
    }

    if kind == "numeric" and col.get("stats"):
        s = col["stats"]
        out["summary"] = f"{_fmt(s['min'])} to {_fmt(s['max'])}, median {_fmt(s['median'])}"
        lo, hi = s["min"], s["max"]
        span = (hi - lo) or 1
        out["spread"] = {
            "min": _fmt(s["min"]), "q1": _fmt(s["q1"]), "median": _fmt(s["median"]),
            "q3": _fmt(s["q3"]), "max": _fmt(s["max"]),
            "mean": _fmt(s.get("mean")), "std": _fmt(s.get("std")),
            # positions as percentages across the observed range
            "q1_pct": round((s["q1"] - lo) / span * 100, 2),
            "q3_pct": round((s["q3"] - lo) / span * 100, 2),
            "median_pct": round((s["median"] - lo) / span * 100, 2),
        }
    elif kind == "temporal" and col.get("stats"):
        s = col["stats"]
        out["summary"] = f"{str(s.get('min'))[:10]} to {str(s.get('max'))[:10]}"
    else:
        n = col.get("cardinality", col.get("distinct"))
        out["summary"] = f"{_fmt(n)} distinct value{'' if n == 1 else 's'}"
        vals = col.get("values") or col.get("sample_values")
        if vals:
            out["sample"] = vals[:12]
            out["sample_truncated"] = len(col.get("values") or []) > 12 or bool(col.get("sample_values"))
    return out


def describe_proposal(p: dict) -> dict:
    """
    One parameter proposal.

    Reads `status` and `review` as two facts, because they are two facts. The
    display no longer infers "was this reviewed?" from the actor type -- that
    inference was a patch over a modelling gap, and the model now carries it.
    """
    p = normalize_proposal(p)          # tolerate any artifact still on the old shape
    edges = [e for e in (p.get("edges") or []) if isinstance(e, (int, float))]
    occ = p.get("occupancy")

    bins = []
    if edges:
        labels = p.get("labels") or []
        bounds = ["−∞"] + [_fmt(e) for e in edges] + ["∞"]
        for i in range(len(edges) + 1):
            bins.append({
                "label": labels[i] if i < len(labels) else f"Bin {i + 1}",
                "range": f"{bounds[i]} – {bounds[i + 1]}",
                "count": occ[i] if occ and i < len(occ) else None,
            })

    return {
        "column": p.get("value_column"),
        "status": p.get("status"),
        "review": p.get("review"),
        "review_label": review_label(p),
        "reviewed": is_reviewed(p),
        "selected": p.get("status") == "selected",
        "reliable": p.get("reliable", False),
        "method": p.get("method"),
        "edges": [_fmt(e) for e in edges],
        "baseline": _fmt(p.get("baseline")),
        "bins": bins,
        "reasoning": p.get("reasoning") or [],
        "warnings": p.get("warnings") or [],
        "caveat": p.get("caveat"),
        "selected_by": p.get("selected_by"),
        "selected_by_type": p.get("selected_by_type"),
        "selected_at": (p.get("selected_at") or "")[:19].replace("T", " "),
        "selection_reason": p.get("selection_reason"),
        "confirmed_by": p.get("confirmed_by"),
        "confirmed_at": (p.get("confirmed_at") or "")[:19].replace("T", " "),
        "confirmation_reason": p.get("confirmation_reason"),
        "over_warnings": p.get("selected_over_warnings") or [],
    }


def describe_contract(contract: Optional[dict]) -> Optional[dict]:
    if not contract:
        return None
    cols = [describe_column(c) for c in contract.get("columns", [])]
    return {
        "name": contract.get("name"),
        "row_count": contract.get("row_count"),
        "column_count": contract.get("column_count"),
        "columns": cols,
        "problems": [c for c in cols if c["severity"] != "ok"],
        "proposals": [describe_proposal(p) for p in contract.get("suggested_parameters", []) or []],
    }
