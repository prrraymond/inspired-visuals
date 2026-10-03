#!/usr/bin/env python3
"""
Check that the catalog's assets are actually there.

    python3 Scripts/check_assets.py                 # config + a sample sweep
    python3 Scripts/check_assets.py --all           # every asset URL in the catalog
    python3 Scripts/check_assets.py --why           # show each failure

Two separate questions, asked in order, because the second is meaningless if the
first fails:

  1. Does the configuration describe ONE project?  `SUPABASE_URL`, the two JWTs
     and `SUPABASE_DB_URL` can drift apart -- they have, twice -- and when they
     do, every symptom points at the wrong place. The JWT carries the project ref
     it was issued for, so this is checkable rather than a matter of belief.

  2. Is each asset URL in the catalog reachable?  A row that points at an object
     that is not there is the failure this whole project keeps re-learning, and
     it is invisible until someone opens the page.

Exits non-zero when anything is wrong, so it can gate a pipeline run.
Never prints a credential -- only the public project ref a JWT names.
"""
from __future__ import annotations

import argparse
import base64
import collections
import json
import os
import re
import socket
import sys

import requests
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gallery"))
sys.path.insert(0, os.path.join(_ROOT, "Scripts", "lib"))
load_dotenv(dotenv_path=".env.local")

import supabase_config  # noqa: E402

ASSET_PROPS = ("Asset URL", "Thumbnail", "Chart Image", "Base Code URL")


# --------------------------------------------------------------------------- #
# 1. configuration
# --------------------------------------------------------------------------- #
def _host(url: str | None) -> str | None:
    m = re.match(r"^\w+://(?:[^@/]*@)?([^:/?]+)", url or "")
    return m.group(1) if m else None


def check_config(why: bool) -> list[str]:
    refs = supabase_config.refs()
    print("Configuration")
    for name, r in refs.items():
        print(f"  {name:<28} {supabase_config.describe(r)}")

    problems = supabase_config.problems()
    for p in problems:
        print(f"\n  ! {p}")

    ref = supabase_config.project_ref()
    if not ref:
        return problems + ["SUPABASE_URL is not set"]

    host = f"{ref}.supabase.co"
    print(f"\nProject {ref}")
    try:
        socket.getaddrinfo(host, 443)
        print(f"  {host:<40} resolves")
    except socket.gaierror:
        # A paused project and a removed one look exactly the same from here:
        # both lose the DNS record. This says what was observed and stops.
        print(f"  {host:<40} NO DNS RECORD")
        problems.append(
            f"{host} has no DNS record. A Supabase project that is PAUSED and one "
            f"that has been removed are indistinguishable from outside -- check the "
            f"project's state in the Supabase dashboard. If it is paused, resuming "
            f"it restores the storage objects and every URL below.")
        return problems

    try:
        r = requests.get(f"https://{host}/storage/v1/bucket", timeout=15, headers={
            "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')}"})
        if r.status_code == 200:
            names = [b.get("name") for b in r.json()]
            print(f"  storage                                  {len(names)} bucket(s): "
                  f"{', '.join(names)}")
            want = os.getenv("SUPABASE_BUCKET", "viz-training-assets")
            if want not in names:
                problems.append(f"bucket {want!r} does not exist in this project")
        else:
            problems.append(f"storage API returned HTTP {r.status_code}")
            if why:
                print(f"  storage API body: {r.text[:200]}")
    except requests.RequestException as exc:
        problems.append(f"storage API unreachable: {type(exc).__name__}")
    return problems


# --------------------------------------------------------------------------- #
# 2. the catalog's asset URLs
# --------------------------------------------------------------------------- #
def catalog_assets() -> list[tuple[str, str, str]]:
    """[(chartid, property, url)] for every asset URL the catalog holds."""
    import library
    session = requests.Session()
    out = []
    for page in library._query({"page_size": 100}, session):
        props = page["properties"]
        cid = library._rt(props.get("chartid")) or page["id"][:8]
        for name in ASSET_PROPS:
            prop = props.get(name)
            if prop is None:
                continue
            urls = ([library._url(prop)] if prop.get("type") == "url"
                    else library._files(prop))
            out.extend((cid, name, u) for u in urls if u)
    return out


def sweep(assets, why: bool) -> list[str]:
    session = requests.Session()
    states = collections.Counter()
    failures = []

    print(f"\nAssets  ({len(assets)} URL(s))")
    for cid, name, url in assets:
        try:
            r = session.get(url, timeout=20, stream=True)
            state = "ok" if r.status_code == 200 else f"HTTP {r.status_code}"
            r.close()
        except requests.RequestException as exc:
            state = type(exc).__name__
        states[state] += 1
        if state != "ok":
            failures.append(f"{cid} · {name} · {state}")
        print(f"\r  checked {sum(states.values())}/{len(assets)}", end="", flush=True)
    print()

    for state, n in states.most_common():
        print(f"  {n:>5}  {state}")
    if why:
        for f in failures[:40]:
            print(f"    {f}")
        if len(failures) > 40:
            print(f"    … and {len(failures) - 40} more")
    return ([f"{len(failures)} of {len(assets)} asset URLs are not reachable"]
            if failures else [])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="check every asset, not a sample")
    ap.add_argument("--limit", type=int, default=12, help="sample size (default 12)")
    ap.add_argument("--why", action="store_true", help="list the individual failures")
    args = ap.parse_args()

    problems = check_config(args.why)
    if problems:
        # No point sweeping hundreds of URLs on a host that is not answering.
        print("\nPROBLEMS")
        for p in problems:
            print(f"  - {p}")
        return 1

    assets = catalog_assets()
    if not args.all:
        assets = assets[: args.limit]
        print(f"\n  (sample of {len(assets)}; use --all for every asset)")
    problems = sweep(assets, args.why)

    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
