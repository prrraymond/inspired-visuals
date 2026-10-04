#!/usr/bin/env python3
"""
One place that turns (template, data, text, settings) into a figure.

Both the library previews and the workspace go through here, so a card and the
chart it opens can never disagree about what the template does.

On applying parameters without pretending they were reviewed
------------------------------------------------------------
Some templates need a value the data does not carry -- the boundaries of the value
ranges a choropleth colours by, the baseline a diverging bar chart grows from.
Those are derived from the real distribution and applied IMMEDIATELY, so a chart
is on screen the moment a template is opened. They are recorded as what they are:
`status=selected, review=unreviewed` -- chosen by automation, no person has looked.
Nothing about having been used to draw a chart makes a value reviewed, and the UI
says "chosen automatically" rather than anything that reads as endorsement.

The one thing automation still may not do is select a proposal the guard flagged
unreliable. That refusal is kept: the workspace shows the reason and asks for
boundaries instead of drawing a chart nobody stands behind.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "Scripts", "lib"))

import catalog
from data_contract import derive_contract
from demo_data import demo_frame
from input_check import check_input
import tabular
from render_guard import (AUTOMATION, HUMAN, SelectionRefused, band_labels,
                          derive_parameters, is_reviewed, manual_proposal,
                          propose_parameters, review_label, select_parameters)
from render_guard import ContractViolation
from render_local import RenderRefused, render as _render
from template_iface import read_interface


class SettingsNeeded(Exception):
    """Automation declined to choose, and the chart cannot be drawn until a person does."""

    def __init__(self, column: str, message: str, suggestion: list):
        self.column = column
        self.message = message
        self.suggestion = suggestion
        super().__init__(message)


def occupancy(series: pd.Series, edges: list) -> list:
    s = pd.to_numeric(series, errors="coerce").dropna().astype(float)
    cut = pd.cut(s, bins=[-np.inf] + list(edges) + [np.inf], labels=False)
    return cut.value_counts().reindex(range(len(edges) + 1), fill_value=0).tolist()


def needs_parameters(template_src: str, spec: dict) -> bool:
    """Does anything this template draws actually depend on a derived parameter?"""
    consts = read_interface(template_src)["constants"]
    return bool(spec.get("derive")) or "BASELINE" in consts


def build_proposal(contract: dict, df: pd.DataFrame, column: str,
                   settings: dict | None) -> dict:
    """
    The settled parameter for `column`.

    With no user settings this is the derived proposal, selected by automation and
    marked unreviewed. With user settings it is a *different* proposal, authored by
    a person -- not an edit of the machine's, which stays visible underneath it.
    """
    settings = settings or {}
    edges = settings.get("edges")

    if edges:
        edges = sorted({round(float(e), 6) for e in edges})
        p = manual_proposal(contract, column, edges=edges,
                            occupancy=occupancy(df[column], edges),
                            baseline=settings.get("baseline"),
                            supersedes=_derived(contract, df, column))
        return select_parameters(p, by="you", actor_type=HUMAN)

    p = _derived(contract, df, column)
    try:
        return select_parameters(p, by="chartgen", actor_type=AUTOMATION)
    except SelectionRefused as exc:
        raise SettingsNeeded(column, str(exc),
                             [e for e in p["edges"] if math.isfinite(e)]) from None


def _derived(contract: dict, df: pd.DataFrame, column: str) -> dict:
    d = derive_parameters(contract, column)
    edges = [e for e in d["edges"] if math.isfinite(e)]
    return propose_parameters(contract, column, occupancy=occupancy(df[column], edges))


def build(chartid: str, template_src: str, df: pd.DataFrame, *,
          captions: dict | None = None, settings: dict | None = None,
          formats: tuple = ()) -> dict:
    """
    Draw `df` with the stored template. Returns render_local's result dict plus
    the contract and the settled proposals, so a caller can show both.

    Raises RenderRefused (the chart could not be drawn) or SettingsNeeded (a person
    has to choose a parameter first). Neither is a crash.
    """
    spec = catalog.entry(chartid) or {}
    contract = derive_contract(df, name=chartid)

    proposals: dict = {}
    if needs_parameters(template_src, spec):
        measure = spec.get("measure")
        if measure and measure in df.columns:
            proposals[measure] = build_proposal(contract, df, measure, settings)

    mapping = dict(spec.get("mapping") or {})
    mapping["_derive"] = dict(spec.get("derive") or {})

    constants, described = resolve_controls(chartid, df, settings)
    # Constants the catalog pins for this chart: values a template exposes that
    # are neither data nor user-editable, such as the labels on a reference line.
    # Applied first, so an actual control still wins.
    constants = {**(spec.get("constants") or {}), **constants}
    result = _render(template_src, df, contract, mapping, proposals,
                     {**(spec.get("captions") or {}), **(captions or {})},
                     formats=formats, constants=constants,
                     report=tuple(d["const"] for d in described))
    result["contract"] = contract
    result["proposals"] = proposals
    # A control with no value of its own shows what the template settled on.
    for d in described:
        if d["value"] == "":
            spec_c = next((c for c in (spec.get("controls") or [])
                           if c["const"] == d["const"]), {})
            d["value"] = _display(result["constants"].get(d["const"]), spec_c.get("kind", "text"))
    result["controls"] = described
    return result


# --------------------------------------------------------------------------- #
# template controls
# --------------------------------------------------------------------------- #
# A template carries constants that change the chart but that nothing exposes --
# where a before/after chart splits, how far a reference gridline sits from the
# baseline. Left alone they are decided by a rule the reader cannot see, which is
# exactly the question "how is the shading set here?" was asking. A control makes
# the value visible, says how it was arrived at, and lets a person change it.
def _midpoint(df, column: str):
    """
    The value a before/after template splits at when nothing says otherwise.

    Mirrors the template's own rule -- sort, drop gaps, take the middle row. It is
    computed here so the number can be SHOWN, and then passed in explicitly, so
    the template's internal branch never runs and the two cannot drift apart.
    """
    if column not in df.columns:
        return None
    s = df[column].dropna().sort_values()
    return s.iloc[len(s) // 2] if len(s) else None


def _coerce_control(raw, kind: str):
    """A control's value comes off a text input. Give it the type the chart needs."""
    if raw is None or raw == "":
        return None
    if kind == "number":
        return float(raw)
    if kind == "date":
        ts = pd.to_datetime(raw, errors="coerce")
        return None if pd.isna(ts) else ts
    return raw


def resolve_controls(chartid: str, df, settings: dict | None) -> tuple[dict, list]:
    """
    (constants to push into the template, descriptors for the panel).

    A control the person has not touched still gets its automatic value pushed in
    explicitly -- so the panel can print the actual breakpoint rather than the word
    "automatic" -- while still reading as chosen automatically, never as reviewed.
    """
    spec = catalog.entry(chartid) or {}
    chosen = ((settings or {}).get("controls") or {})
    constants, described = {}, []

    for c in spec.get("controls") or []:
        name = c["const"]
        raw = chosen.get(name)
        problem = None
        value = None
        try:
            value = _coerce_control(raw, c["kind"])
        except (TypeError, ValueError):
            problem = f"“{raw}” is not a number."
        if value is None and raw not in (None, ""):
            problem = problem or f"“{raw}” could not be read as a {c['kind']}."

        by_person = value is not None and problem is None
        if not by_person and c.get("auto") == "midpoint":
            value = _midpoint(df, c.get("column"))
        if value is not None and problem is None:
            constants[name] = value

        described.append({
            "const": name, "label": c["label"], "kind": c["kind"],
            "help": c.get("help"), "value": _display(value, c["kind"]),
            "by_person": by_person, "problem": problem,
        })
    return constants, described


def _display(value, kind: str):
    if value is None:
        return ""
    if kind == "date":
        ts = pd.Timestamp(value)
        return ts.strftime("%Y-%m-%d") if ts.normalize() == ts else ts.isoformat(sep=" ")
    if kind == "number":
        f = float(value)
        return int(f) if f.is_integer() else round(f, 6)
    return str(value)


# --------------------------------------------------------------------------- #
# what the workspace needs to draw itself
# --------------------------------------------------------------------------- #
def _ranges(edges: list) -> list[str]:
    """The band names, from the same function the legend uses."""
    return band_labels(edges)


_NOT_NUMERIC = re.compile(r"'(?P<col>[^']+)' is (?:categorical|temporal), not numeric")


def _plain_violation(problem: str) -> str:
    """Say what the guard refused in the reader's terms, not the contract's."""
    m = _NOT_NUMERIC.search(problem)
    if m:
        return f"“{m.group('col')}” has to hold numbers, but its values are text."
    return problem


def settings_spec(chartid: str, template_src: str, proposals: dict) -> list[dict]:
    """
    Describe the values that were chosen for the user, in the terms the UI shows
    them. `reviewed` is the honest bit: a value chosen by automation reads as
    chosen by automation no matter how many charts it has already drawn.
    """
    spec = catalog.entry(chartid) or {}
    consts = read_interface(template_src)["constants"]
    out = []
    for name, prop in proposals.items():
        edges = [e for e in prop.get("edges", []) if math.isfinite(e)]
        out.append({
            "column": name,
            "uses_edges": bool(spec.get("derive")),
            "uses_baseline": "BASELINE" in consts,
            "edges": edges,
            "ranges": _ranges(edges),
            "occupancy": prop.get("occupancy"),
            "baseline": prop.get("baseline"),
            "reviewed": is_reviewed(prop),
            "provenance": review_label(prop),
            "warnings": prop.get("warnings") or [],
        })
    return out


def state(chartid: str, template_src: str, df, *, captions: dict | None = None,
          settings: dict | None = None) -> dict:
    """
    Everything one workspace render produces: the figure, the table behind it, the
    text slots the template can actually take, and the settings that were applied.

    Never raises for a chart that will not draw -- a refusal is a state the page
    shows, not an exception the browser has to interpret.
    """
    spec = catalog.entry(chartid) or {}
    out = {
        "chartid": chartid,
        "grid": tabular.to_grid(df),
        "captions": {**(spec.get("captions") or {}), **(captions or {})},
        "figure": None, "ok": False, "problems": [], "stage": None,
        "caption_slots": [], "settings": [], "controls": [], "log": [],
    }
    try:
        result = build(chartid, template_src, df, captions=captions, settings=settings)
    except RenderRefused as exc:
        out["problems"] = list(exc.problems)
        out["stage"] = exc.stage
        return out
    except ContractViolation as exc:
        # The guard refusing is the system working. It reaches here whenever the
        # data cannot support a parameter the template needs -- a text column
        # where a measure belongs, most often -- and it is a sentence for the
        # page, never a 500.
        out["problems"] = [_plain_violation(pr) for pr in exc.problems]
        out["stage"] = "data"
        return out
    except SettingsNeeded as exc:
        out["problems"] = [exc.message]
        out["stage"] = "settings"
        out["settings"] = [{"column": exc.column, "uses_edges": True, "uses_baseline": False,
                            "edges": exc.suggestion, "ranges": _ranges(exc.suggestion),
                            "occupancy": None, "baseline": None, "reviewed": False,
                            "provenance": "not chosen -- automation declined",
                            "warnings": [exc.message]}]
        return out
    except Exception as exc:                       # a template can raise anything
        out["problems"] = [f"{type(exc).__name__}: {exc}"]
        out["stage"] = "unexpected"
        return out

    out.update(ok=True, log=result["log"],
               figure=json.loads(result["figure"].to_json()),
               caption_slots=sorted(result.get("caption_slots") or []),
               controls=result.get("controls") or [],
               settings=settings_spec(chartid, template_src, result["proposals"]))
    return out


# --------------------------------------------------------------------------- #
# checking a person's data, in their words
# --------------------------------------------------------------------------- #
# The checker's own messages are precise and were written for whoever was
# debugging the pipeline: "the template bins it", "expected, not found". The facts
# are right; the vocabulary is ours, not the reader's. This rewrites each one as a
# sentence about their spreadsheet, keeping the original available for the
# developer view rather than throwing it away.
_PLAIN = {
    "missing": lambda f, c: (f"This chart needs a column called “{c}”. "
                             f"Your data doesn’t have one."),
    "name_mismatch": lambda f, c: f"Your column is named differently — it should be “{c}”.",
    "ambiguous": lambda f, c: f"More than one of your columns could be “{c}”. Rename the one you mean.",
    "not_numeric": lambda f, c: f"“{c}” has to hold numbers, but some of its values are text.",
    "all_null": lambda f, c: f"“{c}” is empty in every row.",
    "nulls": lambda f, c: None,          # kept, but stated by the checker well enough
    "extra": lambda f, c: None,
    "empty": lambda f, c: "There are no rows to draw.",
}

_HINT = {
    "missing": "Rename one of your columns, or add it.",
    "name_mismatch": "One click fixes this.",
    "not_numeric": "Remove the text values, or the symbols around the numbers.",
    "all_null": "Fill it in, or use a different column.",
}


def optional_columns(chartid: str, template_src: str) -> set:
    """
    Demo columns the template can do without.

    The template guards these -- `if lat_column in df.columns` -- so their absence
    is a feature it skips, not data that is wrong. Without this, every paste of a
    two-column table reports four errors for columns nobody was asked for.
    """
    spec = catalog.entry(chartid) or {}
    mapping = spec.get("mapping") or {}
    iface = read_interface(template_src)
    return {mapping[p.var] for p in iface["placeholders"]
            if p.optional and p.var in mapping}


def check_against_demo(chartid: str, df, template_src: str | None = None) -> list[dict]:
    """
    Compare a person's data against the demo dataset for this template.

    The DEMO is the reference, not the entry's stored contract: the stored one
    describes the dataset the original chart's SQL returned, which is a different
    subject with different columns. The demo is the shape this template is being
    offered under, and it is on screen -- so the thing the user is measured against
    is the thing they can see.
    """
    demo = demo_frame(chartid)
    if demo is None or df is None:
        return []
    optional = optional_columns(chartid, template_src) if template_src else set()
    reference = derive_contract(demo, name=chartid)
    out = []
    for f in check_input(df, reference):
        level, message, hint = f.level, None, _HINT.get(f.code)
        if f.column in optional:
            # Optional means optional. An absent one is information, and a broken
            # one is worth saying but never a reason to refuse the chart.
            level = "info" if f.code == "missing" else "warning"
            if f.code == "missing":
                message = (f"“{f.column}” isn’t there. It’s optional — this chart "
                           f"will draw without it.")
                hint = None
        if message is None:
            message = _PLAIN.get(f.code, lambda *_: None)(f, f.column)
        out.append({
            "level": level,
            "code": f.code,
            "column": f.column,
            "message": message or f.message,
            "detail": f.message if message else None,
            "hint": hint,
            "fix": f.fix,
        })
    rank = {"error": 0, "warning": 1, "info": 2}
    return sorted(out, key=lambda n: rank.get(n["level"], 3))


def blocking_notes(notes: list[dict]) -> list[dict]:
    return [n for n in notes if n["level"] == "error"]
