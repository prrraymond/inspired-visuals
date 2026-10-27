#!/usr/bin/env python3
"""
The look of a chart, as the person drawing it wants it.

Formatting is passed in at render time and never written into the stored
template -- the same rule captions follow (PRD R11, R13). There are two ways in,
because templates are not uniform:

  * Colour ROLES -- the bars, the above-zero colour, the highlighted group -- are
    template constants, named per chart in the catalog. They are set before
    build_figure runs, so the template's own logic decides which mark gets which.
  * Everything else -- background, gridlines, label colour, font -- is applied to
    the built figure, so it works on every template without regenerating one.

The defaults shown on screen are read from what the template actually drew, not
kept as a second copy here that could drift from it.
"""
from __future__ import annotations

import re

# Fonts that look the same in the browser and in a downloaded SVG/PNG. A font the
# viewer does not have falls back silently, and the download would not match.
FONTS = [
    ("Arial", "Arial, Helvetica, sans-serif"),
    ("Helvetica", "Helvetica, Arial, sans-serif"),
    ("Verdana", "Verdana, Geneva, sans-serif"),
    ("Trebuchet MS", "'Trebuchet MS', Helvetica, sans-serif"),
    ("Georgia", "Georgia, 'Times New Roman', serif"),
    ("Times New Roman", "'Times New Roman', Times, serif"),
    ("Courier New", "'Courier New', Courier, monospace"),
]
_FONT_STACKS = dict(FONTS)

_NAMED = {"white": "#ffffff", "black": "#000000", "transparent": "#ffffff"}
_FONT_KEYS = ("font", "textfont", "tickfont", "insidetextfont", "outsidetextfont")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_PX = re.compile(r"font-size\s*:\s*(\d+(?:\.\d+)?)px")


def to_hex(value, fallback: str = "#000000") -> str:
    """A colour as #rrggbb, which is all an <input type=color> will take."""
    if not isinstance(value, str):
        return fallback
    v = value.strip().lower()
    if v in _NAMED:
        return _NAMED[v]
    if re.fullmatch(r"#[0-9a-f]{3}", v):
        return "#" + "".join(ch * 2 for ch in v[1:])
    if _HEX.match(v):
        return v
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+).*\)", v)
    if m:
        return "#" + "".join(f"{int(x):02x}" for x in m.groups())
    return fallback


def _valid_hex(value) -> str | None:
    return value.lower() if isinstance(value, str) and _HEX.match(value) else None


# --------------------------------------------------------------------------- #
# colour roles -> template constants
# --------------------------------------------------------------------------- #
def color_roles(spec: dict, template_constants: dict) -> list[dict]:
    """The colour pickers a chart offers, each with the template's own default."""
    out = []
    for i, role in enumerate(spec.get("colors") or []):
        value = template_constants.get(role["const"])
        if "index" in role:
            value = value[role["index"]] if isinstance(value, (list, tuple)) \
                and len(value) > role["index"] else None
        if value is None:
            continue
        out.append({"key": f"color_{i}", "label": role["label"],
                    "default": to_hex(value)})
    return out


def color_constants(spec: dict, template_constants: dict, fmt: dict | None) -> dict:
    """The template constants a person's colour choices translate to."""
    chosen = (fmt or {}).get("colors") or {}
    out: dict = {}
    for i, role in enumerate(spec.get("colors") or []):
        value = _valid_hex(chosen.get(f"color_{i}"))
        if value is None:
            continue
        const = role["const"]
        if "index" in role:
            base = list(out.get(const) or template_constants.get(const) or [])
            if len(base) <= role["index"]:
                continue
            base[role["index"]] = value
            out[const] = base
        else:
            out[const] = value
    return out


# --------------------------------------------------------------------------- #
# reading what the template drew
# --------------------------------------------------------------------------- #
def _axes(layout: dict):
    for k, v in layout.items():
        if re.fullmatch(r"[xy]axis\d*", k) and isinstance(v, dict):
            yield v


def _label_fonts(fig: dict):
    """Fonts of text drawn AT the data: trace text and data-anchored annotations."""
    for t in fig.get("data") or []:
        if t.get("text") is not None or t.get("texttemplate") is not None:
            yield t.setdefault("textfont", {})
    for a in (fig.get("layout") or {}).get("annotations") or []:
        if not str(a.get("xref", "x")).startswith("paper") and \
                not str(a.get("yref", "y")).startswith("paper"):
            yield a.setdefault("font", {})


def _first_color(fonts) -> str | None:
    for f in fonts:
        c = f.get("color")
        if isinstance(c, list):
            c = c[0] if c else None
        if isinstance(c, str):
            return c
    return None


def defaults(fig: dict) -> dict:
    """What the template drew, as the starting value of every format control."""
    layout = fig.get("layout") or {}
    font = layout.get("font") or {}
    template_layout = ((layout.get("template") or {}).get("layout") or {})
    theme_axis = template_layout.get("yaxis") or template_layout.get("xaxis") or {}
    grid = next((a.get("gridcolor") for a in _axes(layout) if a.get("gridcolor")),
                theme_axis.get("gridcolor"))
    # A chart with no cartesian axes (a map) or with every grid switched off has
    # nothing for a gridline colour to change, and should not offer one.
    cartesian = any(t.get("type", "scatter") in ("bar", "scatter", "scattergl", "histogram",
                                                  "box", "violin", "heatmap")
                    for t in fig.get("data") or [])
    has_grid = cartesian and any(a.get("showgrid") is not False for a in _axes(layout))
    labels = _first_color(_label_fonts({"data": [dict(t) for t in fig.get("data") or []],
                                        "layout": {"annotations": [dict(a) for a in
                                                   layout.get("annotations") or []]}}))
    family = font.get("family") or (template_layout.get("font") or {}).get("family") or ""
    return {
        "background": to_hex(layout.get("paper_bgcolor"), "#ffffff"),
        "grid_color": to_hex(grid, "#e5e5e5") if has_grid else None,
        "label_color": to_hex(labels, "#333333") if labels else None,
        "font_family": _font_name(family),
        "font_size": float(font.get("size") or 12),
    }


def _font_name(family: str) -> str:
    """The FONTS entry a CSS font stack starts with, or Arial."""
    head = (family or "").split(",")[0].strip().strip("'\"").lower()
    for name, _ in FONTS:
        if name.lower() == head:
            return name
    return "Arial"


# --------------------------------------------------------------------------- #
# applying it
# --------------------------------------------------------------------------- #
def _walk_fonts(node, fn):
    """Call fn on every font dict anywhere in a figure."""
    if isinstance(node, dict):
        for k, v in list(node.items()):
            if k in _FONT_KEYS and isinstance(v, dict):
                fn(v)
            if isinstance(v, (dict, list)):
                _walk_fonts(v, fn)
    elif isinstance(node, list):
        for v in node:
            _walk_fonts(v, fn)


def _scale_markup(text, factor: float):
    if not isinstance(text, str):
        return text
    return _PX.sub(lambda m: f"font-size:{round(float(m.group(1)) * factor, 1):g}px", text)


def apply(fig: dict, fmt: dict | None, base: dict) -> list[str]:
    """
    Apply a person's format choices to a built figure (as JSON), in place.

    `base` is defaults() of the same figure -- the template's own look -- so a
    font size is applied as a ratio and the template's hierarchy (a title larger
    than tick labels) survives. Returns a log line per change.
    """
    fmt = fmt or {}
    layout = fig.setdefault("layout", {})
    log = []

    bg = _valid_hex(fmt.get("background"))
    if bg:
        layout["paper_bgcolor"] = layout["plot_bgcolor"] = bg
        for k, v in layout.items():
            if re.fullmatch(r"geo\d*", k) and isinstance(v, dict):
                v["bgcolor"] = bg
        log.append(f"background = {bg}")

    grid = _valid_hex(fmt.get("grid_color"))
    if grid:
        layout.setdefault("xaxis", {})
        layout.setdefault("yaxis", {})
        for ax in _axes(layout):
            ax["gridcolor"] = grid
        log.append(f"gridlines = {grid}")

    label = _valid_hex(fmt.get("label_color"))
    if label:
        for f in _label_fonts(fig):
            f["color"] = label
        log.append(f"labels = {label}")

    family = _FONT_STACKS.get(fmt.get("font_family") or "")
    if family:
        layout.setdefault("font", {})
        _walk_fonts(fig, lambda f: f.__setitem__("family", family))
        log.append(f"font = {fmt['font_family']}")

    try:
        size = float(fmt.get("font_size")) if fmt.get("font_size") not in (None, "") else None
    except (TypeError, ValueError):
        size = None
    if size and 6 <= size <= 48 and size != base.get("font_size"):
        factor = size / float(base.get("font_size") or 12)
        layout.setdefault("font", {}).setdefault("size", base.get("font_size") or 12)

        def scale(f):
            s = f.get("size")
            if isinstance(s, (int, float)):
                f["size"] = round(s * factor, 1)
            elif isinstance(s, list):
                f["size"] = [round(x * factor, 1) if isinstance(x, (int, float)) else x
                             for x in s]
        _walk_fonts(fig, scale)
        title = layout.get("title")
        if isinstance(title, dict):
            title["text"] = _scale_markup(title.get("text"), factor)
        for a in layout.get("annotations") or []:
            a["text"] = _scale_markup(a.get("text"), factor)
        log.append(f"font size = {size:g} (×{factor:.2f})")
    return log
