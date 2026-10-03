#!/usr/bin/env python3
"""
Refuse generated code that captions the chart.

The library supplies the template, the encoding, the validated parameters and the
caveats. The user supplies the data and says what it means. A template that ships
a real title has taken the second job, and it has taken it by guessing.

This is a mechanical check with no semantic judgment: a string literal in a
caption position must be empty or drawn from the canonical placeholder
vocabulary. "Chart title" passes. "Increase in Arrests by U.S. State" fails --
whether or not it is accurate, because accuracy is not the point. A correct
guess is still a guess.

Only caption POSITIONS are inspected. `locationmode="USA-states"` and
`dash="dot"` are encoding, not caption, and are never looked at.
"""
from __future__ import annotations

import ast
import re
from typing import Iterable

# --- canonical placeholder vocabulary ------------------------------------- #
# One set, so a reviewer can tell a placeholder from a caption without reading
# the chart. Templates should use these verbatim.
CANONICAL = {
    "title": "Chart title",
    "subtitle": "Units / measure description",
    "axis": "Axis label",
    "value_axis": "Value",
    "category_axis": "Category",
    "series": "Series",
    "source": "Source / credit",
    "annotation": "Annotation text",
    "category_prefix": "Category A",     # Category A, Category B, … accepted
    "positive": "Above baseline",
    "negative": "Below baseline",
}

_ACCEPTED_EXACT = {v.lower() for v in CANONICAL.values()} | {
    "", "category", "value", "series", "label", "n/a", "—", "-",
    # structural words: they describe the chart's own shape, not its subject
    "before", "after", "total", "other", "baseline", "source", "source line",
}

# Category A/B/C…, Series 1/2…, Bin 1/2… are generated placeholder families.
_ACCEPTED_PATTERNS = (
    re.compile(r"^category [a-z0-9]+$", re.I),
    re.compile(r"^series \d+$", re.I),
    re.compile(r"^bin \d+$", re.I),
    re.compile(r"^group [a-z0-9]+$", re.I),
    re.compile(r"^\{[\w\.\[\]'\"]+\}$"),          # a bare f-string placeholder
    re.compile(r"^<b>\{[\w\.\[\]'\"]+\}</b>$"),
    re.compile(r"^%\{[\w\.]+\}$"),                # plotly hovertemplate token
    re.compile(r"^</?[a-z]+\s*/?>$", re.I),       # a bare HTML tag fragment: <b>, </b>, <br>
    re.compile(r"^source\b.{0,12}$", re.I),       # "Source / credit", "Source line", "Source:"
)

# Variable names whose string value is a caption.
_CAPTION_NAMES = re.compile(
    r"(title|subtitle|caption|source|credit|annotation|label|legend_?title|axis_?title)",
    re.I)

# …but a name ending in _column / _col / _field / _key holds a COLUMN IDENTIFIER,
# not a caption. `label_flag_column = "show_label"` names a dataframe column.
_IDENTIFIER_NAMES = re.compile(r"(_column|_col|_field|_key|_name)$", re.I)

# Keyword arguments whose string value is a caption.
_CAPTION_KWARGS = {
    "title", "title_text", "text", "subtitle", "suffix", "prefix",
    "xaxis_title", "yaxis_title", "legend_title", "legend_title_text", "name",
}


class CaptionViolation(Exception):
    def __init__(self, findings: list[dict]):
        self.findings = findings
        lines = "\n  - ".join(
            f"line {f['line']}: {f['where']} = {f['text']!r}" for f in findings)
        super().__init__(
            f"{len(findings)} subject-specific caption(s) in generated code:\n  - {lines}")


def _acceptable(s: str) -> bool:
    t = re.sub(r"</?[a-z]+\s*/?>", "", s, flags=re.I).strip()   # drop markup tags
    if t.lower() in _ACCEPTED_EXACT:
        return True
    if any(p.match(t) for p in _ACCEPTED_PATTERNS):
        return True
    # Pure formatting/encoding tokens: no letters, or a single word with no space.
    if not re.search(r"[A-Za-z]", t):
        return True
    return False


def find_captions(code: str) -> list[dict]:
    """Return every subject-specific string literal in a caption position."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [{"line": exc.lineno or 0, "where": "<unparseable>", "text": str(exc.msg)}]

    findings: list[dict] = []

    def check(node, where: str):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if not _acceptable(node.value):
                findings.append({"line": node.lineno, "where": where, "text": node.value})
        elif isinstance(node, ast.JoinedStr):
            # f-string: inspect only its literal parts
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    if not _acceptable(part.value):
                        findings.append({"line": node.lineno, "where": where, "text": part.value})

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                name = getattr(target, "id", None)
                if name and _CAPTION_NAMES.search(name) and not _IDENTIFIER_NAMES.search(name):
                    check(node.value, name)
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg and kw.arg.lower() in _CAPTION_KWARGS:
                    check(kw.value, f"{kw.arg}=")
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str) \
                        and k.value.lower() in _CAPTION_KWARGS:
                    check(v, f"{k.value!r}:")
    # de-duplicate on (line, text)
    seen, out = set(), []
    for f in findings:
        key = (f["line"], f["text"])
        if key not in seen:
            seen.add(key)
            out.append(f)
    return sorted(out, key=lambda f: f["line"])


def check_captions(code: str, *, chart: str | None = None) -> None:
    """Raise CaptionViolation if the code captions the chart. Part of the review gate."""
    findings = find_captions(code)
    if findings:
        exc = CaptionViolation(findings)
        exc.chart = chart
        raise exc
