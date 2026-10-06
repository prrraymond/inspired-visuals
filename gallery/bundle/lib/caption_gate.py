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


# A markup tag, including one carrying attributes. The attribute case matters:
# `<span style='font-size:14px'>` must be recognised as markup, not read as
# caption text.
# Markup to split on: a tag (with or without attributes) or a character entity.
# `&#8592;` is an arrow written the long way -- as much decoration as a literal
# one, and invisible to a stripper that only knows the literal form.
MARKUP = re.compile(
    r"</?[a-z][a-z0-9]*(?:\s[^>]*)?/?>"          # <b>, </span>, <span style='...'>
    r"|&(?:#\d+|#x[0-9a-f]+|[a-z]+);",           # &#8592;  &#x2190;  &rarr;
    re.I)
_MARKUP = MARKUP                                 # internal alias, kept for clarity

# A format field: the machinery that says how a number is printed.
_FORMAT_FIELD = re.compile(r"\{[^{}]*\}")


# Leading/trailing characters that are not letters or digits: arrows, bullets,
# dashes, colons, brackets. They decorate a caption without saying anything about
# its subject, so "<- Axis label" is the Axis label placeholder with an arrow on
# it, not a claim about the data.
_DECORATION = re.compile(r"^[^0-9A-Za-z]+|[^0-9A-Za-z]+$")


def _acceptable_fragment(t: str) -> bool:
    """One run of text between markup tags."""
    t = t.strip()
    # Pure formatting/encoding tokens: nothing but a format specification left
    # once the fields are removed. "{:.1f}%" states a precision, not a subject --
    # and its letters are all inside the field, where they are syntax.
    if not re.search(r"[A-Za-z]", _FORMAT_FIELD.sub("", t)):
        return True
    # Checked bare and with decoration stripped. Stripping only the ends cannot
    # launder a subject: "-> Texas leads" still reduces to "Texas leads".
    for candidate in (t, _DECORATION.sub("", t)):
        if candidate.lower() in _ACCEPTED_EXACT:
            return True
        if any(p.match(candidate) for p in _ACCEPTED_PATTERNS):
            return True
    return False


def _acceptable(s: str) -> bool:
    """
    True when a caption-position string asserts no subject.

    Markup is SPLIT ON rather than deleted, because a caption may legitimately
    COMPOSE several canonical placeholders into one annotation --
    `<b>Chart title</b><br><span style='...'>Units / measure description</span>`
    is a title, a line break and a subtitle, none of which name a subject.
    Deleting the tags instead ran the two placeholders together into a string
    that matched nothing, so a correctly-written template was refused; and a tag
    carrying attributes survived deletion entirely and was read as caption text.

    Splitting does not weaken the check: every fragment still has to stand on its
    own, so one subject-specific run anywhere in the string still fails.
    """
    parts = [p for p in (x.strip() for x in _MARKUP.split(s)) if p]
    if not parts:
        return True                      # markup only, no words
    return all(_acceptable_fragment(p) for p in parts)


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
