#!/usr/bin/env python3
"""
Check a user's data against a template's data contract.

The refusal is part of the design. A generic "invalid data" tells the user
nothing; "column 'region' expected, found 'Region'" tells them exactly what to do
and is one click from doing it. Every finding below names the column, what was
expected, what was found, and where possible carries a fix the caller can apply.

The contract is the shape the template was validated against -- derived from the
data the entry's own SQL returned. It is a reference, not a schema the user's data
has to have been born with, so a case difference is a REPAIR, not a rejection.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import pandas as pd

ERROR, WARN, INFO = "error", "warning", "info"


class Finding:
    def __init__(self, level: str, code: str, message: str,
                 column: Optional[str] = None, fix: Optional[dict] = None):
        self.level = level
        self.code = code
        self.message = message
        self.column = column
        self.fix = fix                 # {"kind": "rename", "from": ..., "to": ...}

    def as_dict(self):
        return {"level": self.level, "code": self.code, "message": self.message,
                "column": self.column, "fix": self.fix}

    def __repr__(self):
        return f"<{self.level}:{self.code} {self.message!r}>"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _numeric_ok(series: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(series):
        return True
    coerced = pd.to_numeric(series, errors="coerce")
    return coerced.notna().mean() > 0.8


def check_input(df: pd.DataFrame, contract: dict) -> list[Finding]:
    """Compare a dataframe against a contract. Returns findings, most severe first."""
    out: list[Finding] = []

    if df is None or len(df) == 0:
        out.append(Finding(ERROR, "empty",
                           "No rows. The file parsed but contains no data."))
        return out

    have = list(df.columns)
    by_norm: dict[str, list[str]] = {}
    for c in have:
        by_norm.setdefault(_norm(c), []).append(c)

    wanted = contract.get("columns", []) or []
    for col in wanted:
        name = col.get("name")
        if name in have:
            found = name
        else:
            cands = by_norm.get(_norm(name), [])
            if len(cands) == 1:
                found = cands[0]
                out.append(Finding(
                    WARN, "name_mismatch",
                    f"column {name!r} expected, found {found!r}",
                    column=name, fix={"kind": "rename", "from": found, "to": name}))
            elif len(cands) > 1:
                out.append(Finding(
                    ERROR, "ambiguous",
                    f"column {name!r} expected; {len(cands)} columns could be it "
                    f"({', '.join(repr(c) for c in cands)})", column=name))
                continue
            else:
                out.append(Finding(
                    ERROR, "missing",
                    f"column {name!r} expected, not found. Your columns: "
                    f"{', '.join(repr(c) for c in have)}", column=name))
                continue

        series = df[found]
        if series.isna().all():
            out.append(Finding(
                ERROR, "all_null",
                f"column {found!r} is present but every one of its "
                f"{len(series)} values is empty", column=name))
            continue

        if col.get("kind") == "numeric" and not _numeric_ok(series):
            sample = [repr(v) for v in series.dropna().unique()[:3]]
            out.append(Finding(
                ERROR, "not_numeric",
                f"column {found!r} should hold numbers -- the template bins it -- "
                f"but its values are text ({', '.join(sample)})", column=name))

        nulls = int(series.isna().sum())
        if nulls and not series.isna().all():
            out.append(Finding(
                WARN, "nulls",
                f"column {found!r} has {nulls} empty value"
                f"{'' if nulls == 1 else 's'} of {len(series)}; those rows will not "
                f"be drawn", column=name))

    wanted_names = {_norm(c.get("name")) for c in wanted}
    extra = [c for c in have if _norm(c) not in wanted_names]
    if extra:
        out.append(Finding(
            INFO, "extra",
            f"{len(extra)} column{'' if len(extra) == 1 else 's'} not used by this "
            f"template: {', '.join(repr(c) for c in extra)}"))

    rank = {ERROR: 0, WARN: 1, INFO: 2}
    return sorted(out, key=lambda f: rank[f.level])


def blocking(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.level == ERROR]


def repairs(findings: list[Finding]) -> dict[str, str]:
    """{found_name: expected_name} the caller can apply with df.rename."""
    return {f.fix["from"]: f.fix["to"] for f in findings
            if f.fix and f.fix.get("kind") == "rename"}
