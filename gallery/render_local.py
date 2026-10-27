#!/usr/bin/env python3
"""
Execute a stored template against user data and draw it.

    ############################################################################
    ##  LOCAL ONLY.  THIS MODULE exec()s GENERATED CODE WITH USER DATA.       ##
    ##                                                                        ##
    ##  It is acceptable here because the app binds to 127.0.0.1, there is    ##
    ##  no auth, and the operator is the only user -- the same trust model    ##
    ##  the build-time pipeline already runs under.                           ##
    ##                                                                        ##
    ##  IT MUST NOT SURVIVE INTO ANYTHING DEPLOYED WITHOUT SANDBOXING.        ##
    ##  Whoever wires this behind a network listener owns that decision;      ##
    ##  the moment user-supplied data drives exec() on a shared host, this    ##
    ##  file is a remote code execution path. Replace it with an isolated     ##
    ##  worker (separate process, no network, no filesystem, hard timeout)    ##
    ##  before that happens. See PRD Phase 3.                                 ##
    ############################################################################
"""
from __future__ import annotations

import math
import os
import re
import sys
from typing import Any, Optional

import numpy as np
import pandas as pd
from plotly.graph_objects import Figure

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "Scripts", "lib"))
from caption_gate import check_captions, CaptionViolation          # noqa: E402
from render_guard import (check_dataset, check_figure, band_labels,  # noqa: E402
                          ContractViolation)
from template_iface import (read_interface, caption_constants, apply_captions,  # noqa: E402
                            figure_caption_slots)

EXEC_IS_LOCAL_ONLY = True          # grep-able marker; see the banner above


class RenderRefused(Exception):
    """The chart was not drawn, and why. Distinct from a crash."""

    def __init__(self, stage: str, problems: list[str]):
        self.stage = stage
        self.problems = problems
        super().__init__(f"{stage}: " + "; ".join(problems))


def _nice_step(lo: float, hi: float) -> float:
    span = abs(hi - lo) or 1.0
    raw = span / 4.0
    mag = 10 ** math.floor(math.log10(raw))
    for mult in (1, 2, 2.5, 5, 10):
        if raw <= mag * mult:
            step = mag * mult
            return round(step, 4) if step < 1 else round(step)
    return round(raw)


def _hex(c: str) -> tuple:
    c = c.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _resample_ramp(colors: list, n: int) -> list:
    """`n` colours along the path through `colors`. Identity when the count matches."""
    stops = [_hex(c) for c in colors if isinstance(c, str) and c.startswith("#")]
    if not stops:
        return list(colors)[:n]
    if n == len(stops):
        return list(colors)
    if n == 1:
        return [colors[-1]]
    out = []
    for i in range(n):
        pos = i * (len(stops) - 1) / (n - 1)
        lo = int(math.floor(pos))
        hi = min(lo + 1, len(stops) - 1)
        t = pos - lo
        rgb = tuple(round(stops[lo][k] + (stops[hi][k] - stops[lo][k]) * t) for k in range(3))
        out.append("#%02x%02x%02x" % rgb)
    return out


def apply_parameters(ns: dict, iface: dict, df: pd.DataFrame, mapping: dict,
                     accepted: dict, log: list[str]) -> pd.DataFrame:
    """
    Push accepted parameters into the executing namespace, and build any column
    the template needs that the data does not carry.

    The only column synthesised is one the user explicitly asked for on the
    mapping screen ("derive it from the bins"); nothing is inferred from a name.
    """
    consts = iface["constants"]
    df = df.copy()

    # A binned-category column is a PRODUCT of the accepted parameter, not an input.
    for role, source_col in (mapping.get("_derive") or {}).items():
        prop = accepted.get(source_col)
        if not prop:
            # Almost always the measure column simply is not in the data. Saying
            # "no parameter has been settled" describes our plumbing; saying which
            # column is missing describes their spreadsheet.
            if source_col not in df.columns:
                raise RenderRefused("render", [
                    f"this chart needs a column called “{source_col}”, and your data "
                    f"doesn’t have it."])
            raise RenderRefused("parameters", [
                f"the value ranges for “{source_col}” have not been settled, so the "
                f"groups this chart colours by cannot be worked out"])
        edges = [e for e in prop["edges"] if math.isfinite(e)]
        labels = band_labels(edges)
        target = f"__{role}"
        df[target] = pd.cut(pd.to_numeric(df[source_col], errors="coerce"),
                            bins=[-np.inf] + edges + [np.inf], labels=labels)
        df[target] = df[target].astype(object)
        mapping[f"{role}_column"] = target
        log.append(f"derived {role!r} column from the accepted bins of {source_col!r} "
                   f"at {edges}")
        if "CATEGORY_ORDER" in consts:
            ns["CATEGORY_ORDER"] = list(labels)
            log.append(f"CATEGORY_ORDER set to {list(labels)}")
        # A template hard-codes a colour per band because it was written against a
        # fixed number of them. Change the boundaries and the extra band falls off
        # the end of the map and is drawn in the "no data" grey -- which is how the
        # highest-valued state came out looking like a missing one. The ramp is
        # resampled to however many bands there now are, keeping the template's own
        # colours, and its endpoints, exactly.
        if "CATEGORY_COLORS" in consts and isinstance(consts["CATEGORY_COLORS"], dict):
            ramp = _resample_ramp(list(consts["CATEGORY_COLORS"].values()), len(labels))
            ns["CATEGORY_COLORS"] = dict(zip(labels, ramp))
            log.append(f"CATEGORY_COLORS resampled to {len(labels)} band(s)")

    # Column placeholders.
    for p in iface["placeholders"]:
        user_col = mapping.get(p.var)
        if user_col:
            ns[p.var] = user_col
            log.append(f"{p.var} = {user_col!r}")
        elif not p.optional:
            raise RenderRefused("mapping", [
                f"{p.var} is required by this template and has not been mapped"])

    # Scalar parameters that a proposal settles.
    value_col = mapping.get("value_column") or mapping.get("y_column")
    prop = accepted.get(value_col) if value_col else None
    if prop and "BASELINE" in consts:
        base = prop.get("baseline")
        if base is not None:
            ns["BASELINE"] = float(base)
            log.append(f"BASELINE = {base} (accepted parameter)")
            if "GRID_STEP" in consts:
                series = pd.to_numeric(df[value_col], errors="coerce").dropna()
                step = _nice_step(float(base), float(series.max()))
                ns["GRID_STEP"] = step
                log.append(f"GRID_STEP = {step} (app default from the data spread; "
                           f"no proposal covers it)")
    return df


def apply_caption_constants(ns: dict, iface: dict, captions: dict, log: list[str]) -> set:
    """
    Set the template's caption constants before it runs.

    This is the caption being PASSED IN at render time. The stored template is
    never modified -- these assignments live and die with this execution.
    """
    satisfied = set()
    for role, const in caption_constants(iface["constants"]).items():
        val = (captions or {}).get(role)
        if val:
            ns[const] = val
            satisfied.add(role)
            log.append(f"{const} = {val!r} (your caption)")
    return satisfied


def render(template_src: str, df: pd.DataFrame, contract: dict, mapping: dict,
           accepted: dict, captions: Optional[dict] = None,
           formats: tuple = ("png", "svg"), constants: Optional[dict] = None,
           report: tuple = ()) -> dict:
    """
    Draw the chart. Returns {"images": {fmt: bytes}, "log": [...], "figure": fig}.
    Raises RenderRefused with the stage that refused and why.

    `constants` are template constants a person set on screen -- a breakpoint, a
    gridline step. They are applied AFTER the derived parameters, so a value
    someone chose always beats one the app worked out. `report` names constants
    whose effective value the caller wants back, so a control can show the number
    the chart was actually drawn with rather than a separate guess at it.
    """
    log: list[str] = []
    captions = captions or {}

    # 1. the template must not caption the chart (the pipeline's gate, here too)
    try:
        check_captions(template_src)
        log.append("caption gate: template ships no subject-specific caption")
    except CaptionViolation as exc:
        log.append(f"caption gate: {len(exc.findings)} finding(s) — substituted at render")

    # 2. the data must be able to support a chart at all
    try:
        check_dataset(contract)
        log.append(f"dataset gate: {contract['row_count']} rows, no empty columns")
    except ContractViolation as exc:
        raise RenderRefused("dataset", exc.problems) from None

    # 3. execute the template  ### LOCAL ONLY -- see module banner ###
    iface = read_interface(template_src)
    ns: dict[str, Any] = {}
    try:
        exec(compile(template_src, "<template>", "exec"), ns)      # noqa: S102
    except Exception as exc:
        raise RenderRefused("template", [f"{type(exc).__name__}: {exc}"]) from None
    if not callable(ns.get("build_figure")):
        raise RenderRefused("template", ["no build_figure(df) in the template"])

    df = apply_parameters(ns, iface, df, mapping, accepted, log)

    for name, value in (constants or {}).items():
        if name in iface["constants"]:
            ns[name] = value
            log.append(f"{name} = {value!r} (chart setting)")

    satisfied = apply_caption_constants(ns, iface, captions, log)

    # 4. draw
    try:
        fig = ns["build_figure"](df)
    except KeyError as exc:
        missing = re.findall(r"'([^']+)'", str(exc)) or [str(exc)]
        raise RenderRefused("render", [
            "this chart needs " + ", ".join(f"a column called “{m}”" for m in missing)
            + ", and your data doesn’t have "
            + ("it." if len(missing) == 1 else "them.")]) from None
    except Exception as exc:
        raise RenderRefused("render", [f"{type(exc).__name__}: {exc}"]) from None

    if not isinstance(fig, Figure):
        raise RenderRefused("render", [
            f"build_figure returned {type(fig).__name__}, not a plotly Figure"])

    # 5. a successful render of nothing is a failure
    try:
        check_figure(fig)
        log.append(f"figure gate: {len(fig.data)} trace(s) carrying data")
    except ContractViolation as exc:
        raise RenderRefused("figure", exc.problems) from None

    # 6. captions, applied to the built figure
    # Slots are read first: after substitution the placeholders are gone, and the
    # UI would have nothing left to tell it which text fields are real.
    slots = figure_caption_slots(fig) | set(caption_constants(iface["constants"])) | {"title"}
    for change in apply_captions(fig, captions, satisfied=satisfied):
        log.append(f"caption: {change}")

    images = {}
    for fmt in formats:
        try:
            images[fmt] = fig.to_image(format=fmt, scale=2 if fmt == "png" else 1)
        except Exception as exc:
            log.append(f"{fmt} export failed: {type(exc).__name__}: {exc}")
    # Only a requested format can fail. The workspace asks for none -- it ships the
    # figure as JSON and lets the browser draw it -- and must not be told that a
    # raster export it never wanted did not happen.
    if "png" in formats and "png" not in images:
        raise RenderRefused("export", ["the figure built but PNG export failed"])
    if images:
        log.append("exported " + ", ".join(f"{k} {len(v):,}B" for k, v in images.items()))
    return {"images": images, "log": log, "figure": fig, "caption_slots": slots,
            "constants": {n: ns.get(n) for n in report}}
