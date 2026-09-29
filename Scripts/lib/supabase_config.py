#!/usr/bin/env python3
"""
Establish which Supabase project the configuration actually describes.

This exists because the answer was wrong for weeks and nothing said so. The
workstream moved to a new project; `SUPABASE_URL` and all three JWTs kept
naming the old one; the pipeline went on writing to the old one and every asset
URL in the catalog followed it there. When that project was paused, 801 URLs
broke at once and the first visible symptom was a missing image in Notion.

The check is mechanical, not a matter of care: a Supabase JWT carries the
project ref it was issued for, as a public claim. A key that does not match
`SUPABASE_URL` is a configuration error that can be *proved*, so it should never
again be something a person has to notice.

Nothing here prints a credential. A project ref is a public identifier -- it is
in every storage URL -- and is the only part of a key this module reveals.
"""
from __future__ import annotations

import base64
import json
import os
import re

# Variables that must all describe the same project, and how to read the ref out.
URL_VARS = ("SUPABASE_URL",)
JWT_VARS = ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ANON_KEY")
DB_VARS = ("SUPABASE_DB_URL",)


def ref_of_jwt(token: str | None) -> str | None:
    """The `ref` claim of a Supabase JWT, or None. Decodes only; never verifies."""
    if not token or token.count(".") != 2:
        return None
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload)).get("ref")
    except Exception:
        return None


def ref_of_url(url: str | None) -> str | None:
    m = re.match(r"^https?://([a-z0-9]+)\.supabase\.(?:co|com)", url or "")
    return m.group(1) if m else None


def ref_of_db_url(url: str | None) -> str | None:
    """Pooler URLs carry the ref in the username: postgres.<ref>."""
    m = re.search(r"://([^:@/]+)", url or "")
    if m:
        got = re.search(r"postgres\.([a-z0-9]+)", m.group(1))
        if got:
            return got.group(1)
    return ref_of_url(url)


def refs(env: dict | None = None) -> dict[str, str | None]:
    """{variable name: project ref} for every variable that names a project."""
    env = env if env is not None else os.environ
    out: dict[str, str | None] = {}
    for name in URL_VARS:
        out[name] = ref_of_url(env.get(name))
    for name in JWT_VARS:
        out[name] = ref_of_jwt(env.get(name))
    for name in DB_VARS:
        out[name] = ref_of_db_url(env.get(name))
    return out


def project_ref(env: dict | None = None) -> str | None:
    """The project the app should be talking to: whatever SUPABASE_URL names."""
    env = env if env is not None else os.environ
    return ref_of_url(env.get("SUPABASE_URL"))


def problems(env: dict | None = None) -> list[str]:
    """
    What is wrong with the Supabase configuration, in words a banner can show.

    Returns [] when every variable that names a project names the same one.
    """
    env = env if env is not None else os.environ
    found = refs(env)
    out: list[str] = []

    missing = [n for n, r in found.items() if env.get(n) and r is None]
    for name in missing:
        out.append(f"{name} is set but does not name a Supabase project")

    named = {n: r for n, r in found.items() if r}
    if not named:
        return out + ["no Supabase project is configured"]

    distinct = set(named.values())
    if len(distinct) > 1:
        expected = found.get("SUPABASE_URL")
        odd = sorted(n for n, r in named.items() if r != expected) if expected else []
        detail = (f"SUPABASE_URL names {expected}, but "
                  + ", ".join(f"{n} names {named[n]}" for n in odd)
                  if expected and odd else
                  "; ".join(f"{n} names {r}" for n, r in sorted(named.items())))
        out.append(
            "the Supabase variables name more than one project — " + detail
            + ". Credentials issued for one project do not work against another, "
              "and writes will land wherever SUPABASE_URL points.")
    return out
