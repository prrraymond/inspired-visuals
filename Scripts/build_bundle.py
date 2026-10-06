#!/usr/bin/env python3
"""
Freeze the catalogued templates, their previews and their metadata into the repo.

    python3 Scripts/build_bundle.py

Run this locally, where Notion, Supabase and kaleido are all available. It writes
`gallery/bundle/`, which is committed and is what a deployment serves. Nothing in
the deployed app reaches for a credential or a network service to draw a chart.

Every template is re-checked against the caption gate before it is written: a
template that ships a subject must not be frozen into a release.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "gallery"))
sys.path.insert(0, str(_ROOT / "Scripts" / "lib"))

import catalog                                                  # noqa: E402
import chartgen                                                 # noqa: E402
import library                                                  # noqa: E402
import previews                                                 # noqa: E402
from caption_gate import check_captions, CaptionViolation       # noqa: E402
from demo_data import demo_frame                                # noqa: E402

OUT = _ROOT / "gallery" / "bundle"


def vendor_lib() -> int:
    """
    Copy Scripts/lib into the bundle.

    The app imports data_contract, render_guard, template_iface, caption_gate,
    input_check and provenance as top-level modules. Leaving them outside the
    bundle meant the deployment depended on an ignore rule keeping one directory
    out of a wholesale exclusion -- and on `*` not crossing `/`, which differs
    between implementations. Vendoring removes the question: the bundle carries
    everything it needs, and the deployment ships no Scripts/ at all.
    """
    dest = OUT / "lib"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    n = 0
    for src in sorted((_ROOT / "Scripts" / "lib").glob("*.py")):
        shutil.copy2(src, dest / src.name)
        n += 1
    print(f"vendored {n} library modules into {dest.relative_to(_ROOT)}")
    return n


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "templates").mkdir(exist_ok=True)
    (OUT / "previews").mkdir(exist_ok=True)
    vendor_lib()

    entries, failed = {}, []
    for chartid in catalog.ORDER:
        print(f"\n{chartid}")
        try:
            live = library.get_entry(chartid)
        except Exception as exc:
            print(f"  ! Notion unreachable: {type(exc).__name__}")
            failed.append(chartid)
            continue
        if live is None:
            print("  ! no such row")
            failed.append(chartid)
            continue

        src = previews.template_source(chartid, live.template_url)
        if not src:
            print("  ! no template source")
            failed.append(chartid)
            continue
        try:
            check_captions(src)
        except CaptionViolation as exc:
            # A template that names a subject must not ship. This is the last
            # gate before it becomes a release artefact.
            print(f"  ! REFUSED, template carries a caption: {str(exc).splitlines()[0]}")
            failed.append(chartid)
            continue
        (OUT / "templates" / f"{chartid}.py").write_text(src)
        print(f"  template {len(src)}B")

        try:
            result = chartgen.build(chartid, src, demo_frame(chartid), formats=("png",))
        except Exception as exc:
            print(f"  ! will not render: {type(exc).__name__}: {exc}")
            failed.append(chartid)
            continue
        (OUT / "previews" / f"{chartid}.png").write_bytes(result["images"]["png"])
        print(f"  preview {len(result['images']['png']):,}B")

        entries[chartid] = {
            "title": live.title,
            "status": live.status,
            "caveats": live.caveats,
            "viz_types": live.viz_types,
        }

    (OUT / "entries.json").write_text(json.dumps(entries, indent=1, sort_keys=True))
    print(f"\nWrote {len(entries)} entries to {OUT.relative_to(_ROOT)}")
    if failed:
        print(f"FAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
