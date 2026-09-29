#!/usr/bin/env python3
"""
Read a template's interface, and apply captions to a rendered figure.

A template declares nothing about itself. It carries module-level
`<role>_column = "<default>"` assignments that build_figure() reads, and a set of
caption constants holding placeholders. There is no manifest, so this module
recovers the interface by parsing the source -- which is the honest description of
the situation, not a design.

Captions are applied at RENDER TIME and never written back into the stored
template: the constants are set in the executing namespace, and the returned
figure is swept for canonical placeholder strings. The file in storage is
untouched either way.
"""
from __future__ import annotations

import ast
import re
from typing import Any, Optional

try:
    from caption_gate import CANONICAL, find_captions
except ImportError:                                    # pragma: no cover
    from .caption_gate import CANONICAL, find_captions  # type: ignore


# --- caption roles -------------------------------------------------------- #
# Mapped by CONSTANT NAME, not by inspecting data. A template that follows the
# canonical vocabulary needs none of this; these cover the ones generated before
# the vocabulary existed.
CAPTION_CONSTANTS = {
    "title":    ("TITLE_TEXT", "TITLE", "CHART_TITLE", "HEADLINE"),
    "subtitle": ("SUBTITLE_TEXT", "SUBTITLE", "UNITS_TEXT"),
    "units":    ("AXIS_LABEL", "VALUE_AXIS_TITLE", "UNIT_LABEL", "Y_AXIS_TITLE"),
    "source":   ("SOURCE_TEXT", "SOURCE", "CREDIT", "SOURCE_LINE"),
    "above":    ("POS_LABEL", "ABOVE_LABEL", "POSITIVE_LABEL"),
    "below":    ("NEG_LABEL", "BELOW_LABEL", "NEGATIVE_LABEL"),
}

# Placeholder strings a rendered figure may carry, by the role they stand in for.
PLACEHOLDER_ROLE = {
    "chart title": "title",
    "units / measure description": "subtitle",
    "axis label": "units",
    "value": "units",
    "source / credit": "source",
    "source line": "source",
    "source: example source": "source",
    "annotation text": "title",
    "above baseline": "above",
    "below baseline": "below",
}

DEFAULT_CAPTIONS = {
    "title": "", "subtitle": "", "units": "", "source": "",
    "above": "Above baseline", "below": "Below baseline",
}


class Placeholder:
    """One `<role>_column` slot a template reads from the dataframe."""

    def __init__(self, var: str, default: str, comment: str, optional: bool):
        self.var = var                        # e.g. "state_column"
        self.role = var[:-7] if var.endswith("_column") else var
        self.default = default                # e.g. "state_code"
        self.comment = comment
        self.optional = optional

    def __repr__(self):
        return f"<Placeholder {self.var}={self.default!r} optional={self.optional}>"


def _guarded_vars(src: str) -> set[str]:
    """
    Variables the template checks for before using -- `x in df.columns`,
    `needed.issubset(df.columns)`. Those columns are optional.

    Best-effort: a template states its requirements nowhere, so this reads the
    guards it happens to have. The render is still the real gate.
    """
    out: set[str] = set()
    for m in re.finditer(r"(\w+)\s+in\s+\w+\.columns", src):
        out.add(m.group(1))
    for m in re.finditer(r"issubset\(\s*\w+\.columns\s*\)", src):
        pass
    # `needed = {a, b, c}` … `needed.issubset(df.columns)`
    for m in re.finditer(r"(\w+)\s*=\s*\{([^}]*)\}\s*\n(?:.*\n)?.*\1\.issubset\(\s*\w+\.columns", src):
        for part in m.group(2).split(","):
            name = part.strip()
            if re.fullmatch(r"\w+", name):
                out.add(name)
    return out


def read_interface(src: str) -> dict:
    """Return {'placeholders': [Placeholder], 'constants': {name: value}}."""
    tree = ast.parse(src)
    lines = src.splitlines()
    guarded = _guarded_vars(src)

    placeholders, constants = [], {}
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        name = node.targets[0].id
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            continue
        comment = ""
        m = re.search(r"#\s*(.*)$", lines[node.lineno - 1] if node.lineno <= len(lines) else "")
        if m:
            comment = m.group(1).strip()
        if name.endswith("_column") and isinstance(value, str):
            optional = name in guarded or "optional" in comment.lower()
            placeholders.append(Placeholder(name, value, comment, optional))
        else:
            constants[name] = value
    return {"placeholders": placeholders, "constants": constants}


def caption_constants(constants: dict) -> dict[str, str]:
    """Which caption roles this template exposes as a settable constant."""
    out = {}
    for role, names in CAPTION_CONSTANTS.items():
        for n in names:
            if n in constants:
                out[role] = n
                break
    return out


# --- applying captions ---------------------------------------------------- #
def _replace(text: Optional[str], captions: dict) -> Optional[str]:
    """
    The user's words for this slot, or None to leave the placeholder alone.

    An unfilled caption LEAVES the placeholder standing rather than blanking it.
    A visible "Source / credit" is an empty slot the reader can see and fill; a
    blank is indistinguishable from a chart that never had one.
    """
    if not isinstance(text, str):
        return None
    role = PLACEHOLDER_ROLE.get(text.strip().lower())
    if role is None:
        return None
    word = (captions.get(role) or "").strip()
    return word or None


def apply_captions(fig, captions: dict, satisfied: Optional[set] = None) -> list[str]:
    """
    Sweep a built figure for caption placeholders and substitute the user's words.

    `satisfied` names roles already delivered by setting a template constant before
    the build. Without it this function would add a layout title to a template that
    already drew the same words as an annotation -- which it did, once, and the
    chart carried its title twice.

    Returns the list of changes made, for the run log.
    """
    changes: list[str] = []
    satisfied = satisfied or set()
    cap = {**DEFAULT_CAPTIONS, **{k: v for k, v in captions.items() if v}}

    def visit(container, attr, label):
        cur = getattr(container, attr, None)
        new = _replace(cur, cap)
        if new is not None and new != cur:
            setattr(container, attr, new)
            changes.append(f"{label}: {cur!r} -> {new!r}")

    lay = fig.layout
    if lay.title is not None:
        visit(lay.title, "text", "layout.title")
    for axis_name in ("xaxis", "yaxis"):
        ax = getattr(lay, axis_name, None)
        if ax is not None and getattr(ax, "title", None) is not None:
            visit(ax.title, "text", f"{axis_name}.title")
    for i, ann in enumerate(lay.annotations or ()):
        visit(ann, "text", f"annotation[{i}]")

    # A template whose title is empty gets the user's title as a real title --
    # unless the template already drew it from a constant we set.
    if cap.get("title") and "title" not in satisfied and not (lay.title and lay.title.text):
        already = any("layout.title" in c for c in changes)
        if not already:
            fig.update_layout(title=dict(text=cap["title"], x=0.0, xanchor="left",
                                         y=0.985, yanchor="top"))
            # A template that never had a title reserved no room for one; without
            # this the injected title lands on top of the first subplot heading.
            top = (fig.layout.margin.t if fig.layout.margin is not None
                   and fig.layout.margin.t is not None else 0)
            fig.update_layout(margin=dict(t=max(top, 96)))
            changes.append(f"layout.title: set to {cap['title']!r} (top margin {max(top, 96)})")
    return changes


def figure_caption_slots(fig) -> set:
    """
    Which caption roles this built figure actually has a place for.

    Called BEFORE apply_captions, while the canonical placeholders are still
    standing -- afterwards they have been replaced and there is nothing left to
    find. The point is to offer the user a text field only when the words they
    type will land somewhere; a "Subtitle" box on a template that draws no
    subtitle is a promise the chart cannot keep.
    """
    found = set()
    lay = fig.layout

    def note(text):
        if isinstance(text, str):
            role = PLACEHOLDER_ROLE.get(text.strip().lower())
            if role:
                found.add(role)

    if lay.title is not None:
        note(lay.title.text)
    for axis_name in ("xaxis", "yaxis"):
        ax = getattr(lay, axis_name, None)
        if ax is not None and getattr(ax, "title", None) is not None:
            note(ax.title.text)
    for ann in (lay.annotations or ()):
        note(getattr(ann, "text", None))
    return found


def residual_captions(fig) -> list[str]:
    """
    Caption-position strings still present after substitution that assert a
    subject. Surfaced rather than silently tolerated.
    """
    out = []
    lay = fig.layout
    texts = []
    if lay.title is not None and lay.title.text:
        texts.append(("layout.title", lay.title.text))
    for i, ann in enumerate(lay.annotations or ()):
        if getattr(ann, "text", None):
            texts.append((f"annotation[{i}]", ann.text))
    for axis_name in ("xaxis", "yaxis"):
        ax = getattr(lay, axis_name, None)
        if ax is not None and getattr(ax, "title", None) is not None and ax.title.text:
            texts.append((f"{axis_name}.title", ax.title.text))
    for where, text in texts:
        probe = f'x = "{text}"\n'
        try:
            if find_captions(f"title = {text!r}\n"):
                out.append(f"{where}: {text!r}")
        except Exception:
            pass
    return out


def suggest_mapping(placeholders: list, df_columns: list, contract: dict) -> dict:
    """
    Pre-fill template role -> user column.

    Matching is by NAME first (the placeholder's default is the column name the
    template was written against), then by KIND from the contract. Nothing is
    inferred from what a column appears to mean -- a suggestion the user can see
    and change, never a decision.
    """
    kinds = {c.get("name"): c.get("kind") for c in (contract.get("columns") or [])}
    taken: set[str] = set()
    out: dict[str, str] = {}

    def norm(s):
        return re.sub(r"[^a-z0-9]", "", str(s).lower())

    by_norm = {}
    for c in df_columns:
        by_norm.setdefault(norm(c), c)

    for p in placeholders:                       # exact / normalised name
        hit = by_norm.get(norm(p.default))
        if hit and hit not in taken:
            out[p.var] = hit
            taken.add(hit)

    # Kind-based fallback, but ONLY when it is unambiguous. Two numeric columns and
    # one numeric role is not a suggestion, it is a coin toss -- and picking the
    # first would have mapped `year` onto the measure of a small-multiples chart.
    # Which of several numeric columns is the measure is exactly what the contract
    # cannot say (see the `role` note in docs/flow-2026-09.md).
    unfilled = [p for p in placeholders if p.var not in out and not p.optional]
    for p in unfilled:
        want_numeric = p.role in ("value", "y")
        pool = [c for c in df_columns
                if c not in taken and ((kinds.get(c) == "numeric") == want_numeric)]
        if len(pool) == 1:
            out[p.var] = pool[0]
            taken.add(pool[0])
    return out
