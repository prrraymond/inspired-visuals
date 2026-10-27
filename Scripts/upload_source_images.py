#!/usr/bin/env python3
"""
Put the source screenshots into the bucket, so Stage A has something to read.

    python3 Scripts/upload_source_images.py --dry-run
    python3 Scripts/upload_source_images.py

Stage A's input is `raw/` inside the Supabase bucket -- it lists that prefix and
works through whatever it finds. The screenshots live in several folders on disk
and some folders are byte-identical copies of each other, so this deduplicates by
content hash before uploading: the same image under two names would otherwise
become two catalog rows describing one chart.

Every upload is verified against the object listing afterwards. The pipeline has
a history of recording URLs for objects that never landed -- 507 rows once
pointed at objects under `code/` that do not exist -- so "the API did not raise"
is not accepted as proof that a file is there.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import mimetypes
import os
import pathlib
import sys

from dotenv import load_dotenv
from supabase import create_client

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "Scripts" / "lib"))
load_dotenv(dotenv_path=_ROOT / ".env.local")

import supabase_config  # noqa: E402

BUCKET = os.getenv("SUPABASE_BUCKET", "viz-training-assets")
PREFIX = os.getenv("SUPABASE_FOLDER", "raw")
EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# Where the screenshots live. Order matters only for which name a duplicate keeps.
SOURCES = [
    pathlib.Path.home() / "Desktop" / "design examples",
    pathlib.Path.home() / "Desktop" / "designs25",
    pathlib.Path.home() / "Desktop" / "DesignFeb26",
    pathlib.Path.home() / "Downloads" / "Design ideas 4",
    pathlib.Path.home() / "Downloads" / "Design ideas 4 2",
]


def collect(sources: list[pathlib.Path]) -> tuple[dict, dict]:
    """(sha -> path) keeping the first name seen, and a per-folder tally."""
    chosen: dict[str, pathlib.Path] = {}
    tally: dict[str, list[int]] = {}
    for root in sources:
        kept = dupes = 0
        if not root.exists():
            print(f"  ! {root} does not exist — skipped")
            continue
        for f in sorted(root.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in EXTS:
                continue
            sha = hashlib.sha256(f.read_bytes()).hexdigest()
            if sha in chosen:
                dupes += 1
            else:
                chosen[sha] = f
                kept += 1
        tally[str(root)] = [kept, dupes]
    return chosen, tally


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="list what would be uploaded")
    ap.add_argument("--limit", type=int, help="stop after this many uploads")
    ap.add_argument("--why", action="store_true", help="name every file")
    args = ap.parse_args()

    problems = supabase_config.problems()
    if problems:
        print("Refusing to upload — the Supabase configuration is inconsistent:")
        for p in problems:
            print(f"  - {p}")
        return 1
    ref = supabase_config.project_ref()
    print(f"Target: {ref} / {BUCKET} / {PREFIX}/\n")

    chosen, tally = collect(SOURCES)
    for folder, (kept, dupes) in tally.items():
        print(f"  {kept:>5} new, {dupes:>5} duplicate   {folder}")
    files = sorted(chosen.values(), key=lambda p: p.name)
    if args.limit:
        files = files[: args.limit]
    total_mb = sum(f.stat().st_size for f in files) / 1e6
    print(f"\n  {len(files)} unique images, {total_mb:.0f} MB")

    names = collections.Counter(f.name for f in files)
    clashes = [n for n, c in names.items() if c > 1]
    if clashes:
        # Same name, different bytes: one would silently overwrite the other.
        print(f"  ! {len(clashes)} filename collision(s) across folders; "
              f"these would overwrite each other: {clashes[:5]}")
        return 1

    if args.dry_run:
        if args.why:
            for f in files:
                print(f"    {f.name}")
        print("\n  --dry-run: nothing uploaded")
        return 0

    supa = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    store = supa.storage.from_(BUCKET)

    uploaded, failed = 0, []
    for i, f in enumerate(files, 1):
        key = f"{PREFIX}/{f.name}"
        ctype = mimetypes.guess_type(f.name)[0] or "image/png"
        try:
            store.upload(key, f.read_bytes(), {"content-type": ctype, "upsert": "true"})
            uploaded += 1
        except Exception as exc:
            failed.append(f"{f.name}: {type(exc).__name__}: {exc}")
        if sys.stdout.isatty() or i % 100 == 0 or i == len(files):
            end = "\r" if sys.stdout.isatty() else "\n"
            print(f"  uploaded {i}/{len(files)}", end=end, flush=True)
    if sys.stdout.isatty():
        print()

    # Verify against the listing rather than trusting the calls that just ran.
    listed, offset = set(), 0
    while True:
        page = store.list(PREFIX, {"limit": 100, "offset": offset})
        if not page:
            break
        listed.update(o["name"] for o in page)
        offset += len(page)
    missing = [f.name for f in files if f.name not in listed]

    print(f"\n  upload calls succeeded: {uploaded}/{len(files)}")
    print(f"  objects now under {PREFIX}/: {len(listed)}")
    print(f"  expected files not in the listing: {len(missing)}")
    for line in failed[:10]:
        print(f"    ! {line}")
    for name in missing[:10]:
        print(f"    ! missing after upload: {name}")
    return 1 if (failed or missing) else 0


if __name__ == "__main__":
    sys.exit(main())
