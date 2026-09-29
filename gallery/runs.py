#!/usr/bin/env python3
"""
In-memory store for a walk through the flow.

LOCAL ONLY, like render_local: a process-global dict, no eviction beyond a cap,
no persistence, no isolation between callers. It is a single-operator scratchpad,
not a session store. Anything multi-user needs a real one.
"""
from __future__ import annotations

import secrets
import threading
from datetime import datetime, timezone

_LOCK = threading.Lock()
_RUNS: dict[str, dict] = {}
_MAX = 40


def new_run(**fields) -> str:
    rid = secrets.token_urlsafe(9)
    with _LOCK:
        if len(_RUNS) >= _MAX:
            for k in sorted(_RUNS, key=lambda k: _RUNS[k]["created"])[: _MAX // 4]:
                _RUNS.pop(k, None)
        _RUNS[rid] = {"id": rid, "created": datetime.now(timezone.utc), **fields}
    return rid


def get(rid: str) -> dict | None:
    with _LOCK:
        return _RUNS.get(rid)


def update(rid: str, **fields) -> dict | None:
    with _LOCK:
        run = _RUNS.get(rid)
        if run is None:
            return None
        run.update(fields)
        return run
