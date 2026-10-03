#!/usr/bin/env python3
"""
Rendered previews for the library page.

A card that shows the screenshot of the chart this template was copied FROM is
showing the wrong chart: the subject is wrong, the data is wrong, and the one
thing a person is trying to judge -- what this template will draw for them -- is
absent. So every card shows the template rendered against its own demo data.

Previews are a browsing surface, not a workspace: a PNG, cached on disk, keyed on
the template source and the demo data that produced it. Nothing initialises a
Plotly runtime to scroll a list. The workspace is where the chart becomes live.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
import threading
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import catalog
import chartgen
from demo_data import demo_frame
from render_local import RenderRefused

CACHE = pathlib.Path(__file__).parent / "cache"
TEMPLATES = CACHE / "templates"
PREVIEWS = CACHE / "previews"
MANIFEST = CACHE / "previews" / "manifest.json"

_LOCK = threading.Lock()


def _ensure_dirs() -> None:
    TEMPLATES.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)


# The render pipeline is part of what a preview depends on. Leaving it out left
# cards showing "Category A/B/C" legends after the labels had been replaced
# everywhere else -- the exact stale-artefact failure this project keeps hitting.
_PIPELINE = [pathlib.Path(__file__).parent / "render_local.py",
             pathlib.Path(__file__).parent / "chartgen.py",
             pathlib.Path(__file__).parent.parent / "Scripts" / "lib" / "render_guard.py",
             pathlib.Path(__file__).parent.parent / "Scripts" / "lib" / "template_iface.py"]


def _pipeline_digest() -> str:
    h = hashlib.sha256()
    for f in _PIPELINE:
        h.update(f.read_bytes() if f.exists() else b"")
    return h.hexdigest()


def _fingerprint(chartid: str, src: str) -> str:
    """What the preview depends on. Change any of it and the PNG is rebuilt."""
    spec = catalog.entry(chartid) or {}
    df = demo_frame(chartid)
    h = hashlib.sha256()
    h.update(src.encode())
    h.update(json.dumps(spec, sort_keys=True, default=str).encode())
    h.update(df.to_csv(index=False).encode() if df is not None else b"")
    h.update(_pipeline_digest().encode())
    return h.hexdigest()[:16]


# --------------------------------------------------------------------------- #
# template source
# --------------------------------------------------------------------------- #
def template_source(chartid: str, url: str | None, *, refresh: bool = True) -> str | None:
    """
    The template, from storage, cached to disk.

    The disk copy is a FALLBACK, not the source of truth -- storage wins whenever
    it answers. Serving a silently stale template is the failure this whole project
    keeps re-learning, so a fetch that fails says so in the log rather than quietly
    handing back yesterday's file.
    """
    _ensure_dirs()
    path = TEMPLATES / f"{chartid}.py"
    if refresh and url:
        import library
        fetched = library.fetch_template(url)
        if fetched:
            if not path.exists() or path.read_text() != fetched:
                path.write_text(fetched)
                print(f"  - {chartid}: template refreshed from storage ({len(fetched)}B)")
            return fetched
        print(f"  - {chartid}: storage did not answer; using the cached copy")
    return path.read_text() if path.exists() else None


# --------------------------------------------------------------------------- #
# previews
# --------------------------------------------------------------------------- #
def _manifest() -> dict:
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_manifest(m: dict) -> None:
    MANIFEST.write_text(json.dumps(m, indent=1, sort_keys=True))


def build(chartid: str, src: str, *, force: bool = False) -> dict:
    """
    Render the demo data to a cached PNG. Returns a status record; never raises --
    a template that will not draw is a card that says so, not a 500.
    """
    _ensure_dirs()
    fp = _fingerprint(chartid, src)
    png = PREVIEWS / f"{chartid}.png"

    with _LOCK:
        man = _manifest()
        cached = man.get(chartid)
        if not force and cached and cached.get("fingerprint") == fp and png.exists():
            return cached

        record = {"fingerprint": fp, "ok": False, "problem": None}
        try:
            df = demo_frame(chartid)
            if df is None:
                raise RenderRefused("demo", ["no demo dataset for this template"])
            result = chartgen.build(chartid, src, df, formats=("png",))
            png.write_bytes(result["images"]["png"])
            record.update(ok=True, rows=int(len(df)),
                          columns=[str(c) for c in df.columns])
        except (RenderRefused, chartgen.SettingsNeeded) as exc:
            record["problem"] = str(exc)
        except Exception as exc:                       # a template can raise anything
            record["problem"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()

        man[chartid] = record
        _save_manifest(man)
        return record


_STATE: dict[str, dict] = {}
_SOURCES: dict[str, str] = {}


def warm(entries: list) -> dict:
    """Build every catalogued preview. Called once at startup."""
    for e in entries:
        if not catalog.has(e.chartid):
            continue
        src = template_source(e.chartid, e.template_url)
        if src is None:
            _STATE[e.chartid] = {"ok": False, "problem": "template source unavailable"}
            continue
        _SOURCES[e.chartid] = src
        _STATE[e.chartid] = build(e.chartid, src)
        state = "ok" if _STATE[e.chartid]["ok"] else _STATE[e.chartid]["problem"]
        print(f"  - {e.chartid}: preview {state}")
    return _STATE


def status(chartid: str) -> dict:
    """What happened when this preview was built. Empty dict if it never was."""
    return _STATE.get(chartid) or _manifest().get(chartid) or {}


def source(chartid: str) -> str | None:
    """The template source warm() loaded, without a second trip to storage."""
    if chartid in _SOURCES:
        return _SOURCES[chartid]
    p = TEMPLATES / f"{chartid}.py"
    return p.read_text() if p.exists() else None


def path(chartid: str) -> pathlib.Path | None:
    p = PREVIEWS / f"{chartid}.png"
    return p if p.exists() else None
