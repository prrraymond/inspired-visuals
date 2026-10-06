#!/usr/bin/env python3
"""
A self-contained copy of everything the gallery needs to serve the library.

Built by `Scripts/build_bundle.py`, committed, and preferred over the live
sources whenever it is present.

Why this exists
---------------
Deployed, the app must not hold a Supabase service-role key, must not depend on
Notion being reachable on the request path, and must not fetch and execute a
template that nobody has read. Freezing the reviewed templates into the repo
answers all three at once: the deployment has no credentials to leak, no network
call between a click and a chart, and `exec()` runs only code that was reviewed
before it was committed.

It is deliberately dumb -- files on disk, read at import. The live path in
`previews.py` still refreshes from storage for local work; this is what ships.
"""
from __future__ import annotations

import json
import pathlib

DIR = pathlib.Path(__file__).parent / "bundle"
TEMPLATES = DIR / "templates"
PREVIEWS = DIR / "previews"
ENTRIES = DIR / "entries.json"
VENDOR = DIR / "vendor"


def available() -> bool:
    """True when a complete bundle is present."""
    return ENTRIES.exists() and TEMPLATES.is_dir()


def entries() -> dict:
    """{chartid: {title, status, caveats, viz_types}} -- what the UI displays."""
    if not ENTRIES.exists():
        return {}
    return json.loads(ENTRIES.read_text())


def template(chartid: str) -> str | None:
    path = TEMPLATES / f"{chartid}.py"
    return path.read_text() if path.exists() else None


def preview(chartid: str) -> pathlib.Path | None:
    path = PREVIEWS / f"{chartid}.png"
    return path if path.exists() else None


class Entry:
    """
    The subset of a library Entry the deployed UI reads.

    Not the full dataclass: the bundle carries no SQL, no provenance and no
    contract, because the deployed app shows none of them and shipping them
    would mean shipping the source chart's subject along with the template.
    """

    def __init__(self, chartid: str, data: dict):
        self.chartid = chartid
        self.title = data.get("title") or chartid
        self.status = data.get("status")
        self.caveats = data.get("caveats") or []
        self.viz_types = data.get("viz_types") or []


def vendored(name: str) -> pathlib.Path | None:
    """A static asset frozen into the bundle, such as the map geometry."""
    path = VENDOR / name
    return path if path.exists() else None
