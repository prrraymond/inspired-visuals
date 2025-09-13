#!/usr/bin/env python3
import csv
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
import urllib.request
import argparse

# --------------------------
# Env loading (local.env)
# --------------------------
# --------------------------
# Env loading (local.env / .env)
# --------------------------
# --- BEGIN .env.local loader + config (project-root) ---
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception as e:
    raise SystemExit("python-dotenv is required. Run: pip install python-dotenv") from e

# Resolve project root (DataViz/) and load DataViz/.env.local
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env.local"
if not ENV_PATH.exists():
    raise SystemExit(f"Missing {ENV_PATH}. Create it with your Supabase vars.")

# This is the exact pattern you used elsewhere
load_dotenv(dotenv_path=ENV_PATH)

# --- Supabase (write path) ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
# Prefer service role; fall back to anon if you really want read-only
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE", "nfl_game_actives")
UPLOAD_TO_SUPABASE = (os.getenv("UPLOAD_TO_SUPABASE", "true").lower() in {"1","true","yes"})

# Optional: loud status (doesn't print secrets)
print(
    f"[env] .env.local loaded from {ENV_PATH} | upload={UPLOAD_TO_SUPABASE} "
    f"url={'set' if bool(SUPABASE_URL) else 'missing'} "
    f"key={'set' if bool(SUPABASE_KEY) else 'missing'} "
    f"table={SUPABASE_TABLE}"
)

# Small guard for upload mode
if UPLOAD_TO_SUPABASE and (not SUPABASE_URL or not SUPABASE_KEY):
    raise SystemExit("UPLOAD_TO_SUPABASE=true but SUPABASE_URL or SUPABASE_*KEY is missing in .env.local")
# --- END .env.local loader + config ---


# --------------------------
# CLI args
# --------------------------
def parse_args():
    p = argparse.ArgumentParser(description="NFL game-day actives for a weekly window.")
    p.add_argument("--mode", choices=["previous", "rolling"], default="previous",
                   help="previous = last Thu→Mon ending before today; rolling = last Thu→coming Tue")
    p.add_argument("--today", help="Simulate today's date (YYYY-MM-DD) for testing")
    return p.parse_args()

ARGS = parse_args()

# --------------------------
# Time zone
# --------------------------
try:
    import zoneinfo  # py3.9+
    TZ = zoneinfo.ZoneInfo("America/New_York")
except Exception:
    TZ = None

def today_local() -> dt.date:
    if ARGS.today:
        return dt.datetime.strptime(ARGS.today, "%Y-%m-%d").date()
    if TZ is not None:
        return dt.datetime.now(TZ).date()
    return dt.datetime.now().date()

# --------------------------
# HTTP config/helpers
# --------------------------
USER_AGENT = "Mozilla/5.0 (compatible; WeeklyNFLActives/1.4)"
REQUEST_DELAY_SEC = 0.25

SCOREBOARD_RANGE_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
    "?limit=1000&dates={start}-{end}"
)
EVENT_ROSTER_URL = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
    "events/{event_id}/competitions/{competition_id}/competitors/{team_id}/roster"
)
TEAM_ROSTER_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/roster"
)

def http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)

def safe_get(d: dict, path: Iterable[str], default=None):
    cur = d
    for key in path:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return default
    return cur if cur is not None else default

# --------------------------
# Window selection
# --------------------------
def last_thu_before(date_: dt.date) -> dt.date:
    # Mon=0..Sun=6; Thu=3
    delta = (date_.weekday() - 3) % 7
    return date_ - dt.timedelta(days=delta)

def window_previous(today: dt.date) -> Tuple[dt.date, dt.date]:
    """Most recent Thu→Mon window that ended BEFORE 'today'."""
    weekday = today.weekday()  # Mon=0..Sun=6
    days_since_mon = (weekday - 0) % 7
    end_mon = today - dt.timedelta(days=7 if days_since_mon == 0 else days_since_mon)
    start_thu = end_mon - dt.timedelta(days=4)
    return start_thu, end_mon

def window_rolling(today: dt.date) -> Tuple[dt.date, dt.date]:
    """Rolling Thu→Tue window covering the current football weekend.
       Start = last Thursday on/before today; End = start + 5 days (Tuesday)."""
    start_thu = last_thu_before(today)
    end_tue = start_thu + dt.timedelta(days=5)
    return start_thu, end_tue

def choose_window(mode: str, today: dt.date) -> Tuple[dt.date, dt.date]:
    if mode == "rolling":
        return window_rolling(today)
    return window_previous(today)

# --------------------------
# ESPN fetchers/normalizers
# --------------------------
def parse_events_from_scoreboard(start: dt.date, end: dt.date) -> List[dict]:
    url = SCOREBOARD_RANGE_URL.format(
        start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d")
    )
    data = http_get_json(url)
    return data.get("events", [])

def fetch_event_roster(event_id: str, competition_id: str, team_id: str) -> List[dict]:
    url = EVENT_ROSTER_URL.format(
        event_id=event_id, competition_id=competition_id, team_id=team_id
    )
    try:
        data = http_get_json(url)
        items = data.get("items", [])
        athletes = []
        for item in items:
            href = item.get("$ref") or item.get("href")
            if not href:
                continue
            time.sleep(REQUEST_DELAY_SEC / 2)
            athletes.append(http_get_json(href))
        return athletes
    except (HTTPError, URLError, TimeoutError, ValueError):
        return []

def fetch_team_roster(team_id: str) -> List[dict]:
    url = TEAM_ROSTER_URL.format(team_id=team_id)
    try:
        data = http_get_json(url)
        groups = data.get("athletes", [])
        athletes = []
        for grp in groups:
            for it in grp.get("items", []):
                athletes.append(it)
        return athletes
    except (HTTPError, URLError, TimeoutError, ValueError):
        return []

def parse_hometown_fields(hometown_raw):
    city = state = country = None
    if isinstance(hometown_raw, dict):
        city = hometown_raw.get("city")
        state = hometown_raw.get("state")
        country = hometown_raw.get("country")
    elif isinstance(hometown_raw, str):
        parts = [p.strip() for p in hometown_raw.split(",") if p and p.strip()]
        if len(parts) == 1:
            city = parts[0]
        elif len(parts) == 2:
            city, state = parts
        elif len(parts) >= 3:
            city, state, country = parts[0], parts[1], parts[2]
    city_state = f"{city}, {state}" if city and state else (city or state)
    return city, state, country, city_state

def normalize_player(record: dict) -> Dict[str, Optional[str]]:
    player_id = str(
        safe_get(record, ["athlete", "id"])
        or safe_get(record, ["id"])
        or safe_get(record, ["$ref"], "unknown").split("/")[-1]
    )
    name = (
        safe_get(record, ["athlete", "displayName"])
        or safe_get(record, ["displayName"])
        or safe_get(record, ["fullName"])
        or safe_get(record, ["name"])
    )
    position = (
        safe_get(record, ["position", "abbreviation"])
        or safe_get(record, ["athlete", "position", "abbreviation"])
        or safe_get(record, ["position", "displayName"])
    )
    college = (
        safe_get(record, ["college", "name"])
        or safe_get(record, ["athlete", "college", "name"])
        or safe_get(record, ["college"])
        or None
    )

    hometown_raw = (
        safe_get(record, ["birthPlace"])
        or safe_get(record, ["athlete", "birthPlace"])
        or None
    )
    if hometown_raw is None:
        maybe_city = safe_get(record, ["birthCity"])
        maybe_state = safe_get(record, ["birthState"])
        maybe_country = safe_get(record, ["birthCountry"])
        if any([maybe_city, maybe_state, maybe_country]):
            hometown_raw = {"city": maybe_city, "state": maybe_state, "country": maybe_country}

    city, state, country, city_state = parse_hometown_fields(hometown_raw)

    years_exp = (
        safe_get(record, ["experience", "years"])
        or safe_get(record, ["athlete", "experience", "years"])
    )
    try:
        years_exp = int(years_exp) if years_exp is not None else None
    except Exception:
        years_exp = None

    return {
        "player_id": player_id,
        "player_name": name,
        "position": position,
        "college": college,
        "hometown": hometown_raw,
        "hometown_city": city,
        "hometown_state": state,
        "hometown_country": country,
        "hometown_city_state": city_state,
        "years_experience": years_exp,
    }

# --------------------------
# Supabase upload (optional)
# --------------------------
def supabase_upsert(rows: List[dict]) -> None:
    url_base = SUPABASE_URL
    service_key = SUPABASE_KEY
    table = SUPABASE_TABLE

    if not url_base or not service_key:
        print("Skip Supabase upload: URL or service role key missing.", file=sys.stderr)
        return

    try:
        import requests
    except Exception as e:
        raise RuntimeError("requests not installed. `pip install requests`") from e

    endpoint = f"{url_base}/rest/v1/{table}"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    params = {"on_conflict": "event_id,team_id,player_id"}

    CHUNK = 500
    total = len(rows)
    for i in range(0, total, CHUNK):
        chunk = rows[i:i+CHUNK]
        r = requests.post(endpoint, headers=headers, params=params, json=chunk, timeout=60)
        if not r.ok:
            print(f"Supabase upsert failed [{r.status_code}]: {r.text[:300]}", file=sys.stderr)
            r.raise_for_status()
        else:
            print(f"Upserted {len(chunk)} rows to Supabase ({i+len(chunk)}/{total})", file=sys.stderr)

# --------------------------
# Main
# --------------------------
def main() -> int:
    today = today_local()
    start, end = choose_window(ARGS.mode, today)
    print(f"Window: {start} to {end}")

    events = parse_events_from_scoreboard(start, end)
    if not events:
        print("No NFL events found for window.")
    rows: List[Dict[str, Optional[str]]] = []

    for ev in events:
        event_id = str(ev.get("id"))
        event_date = ev.get("date")
        competitions = ev.get("competitions", [])
        if not competitions:
            continue
        comp = competitions[0]
        competition_id = str(comp.get("id") or event_id)

        # home/away context
        home_team = away_team = home_id = away_id = None
        for c in comp.get("competitors", []):
            tid = safe_get(c, ["team", "id"])
            tname = safe_get(c, ["team", "displayName"])
            if c.get("homeAway") == "home":
                home_team, home_id = tname, tid
            else:
                away_team, away_id = tname, tid

        # roster per competitor
        for c in comp.get("competitors", []):
            team_id = safe_get(c, ["team", "id"])
            team_name = safe_get(c, ["team", "displayName"])
            if not team_id:
                continue

            time.sleep(REQUEST_DELAY_SEC)
            roster = fetch_event_roster(event_id, competition_id, team_id)
            if not roster:
                time.sleep(REQUEST_DELAY_SEC)
                roster = fetch_team_roster(team_id)

            for athlete in roster:
                p = normalize_player(athlete)
                rows.append(
                    {
                        "week_window_start": start.isoformat(),
                        "week_window_end": end.isoformat(),
                        "event_id": event_id,
                        "event_date": event_date,
                        "home_team_id": home_id,
                        "home_team": home_team,
                        "away_team_id": away_id,
                        "away_team": away_team,
                        "team_id": team_id,
                        "team_name": team_name,
                        **p,
                    }
                )

    # Dedup by (event_id, team_id, player_id)
    seen = set()
    deduped_rows = []
    for r in rows:
        key = (r["event_id"], r["team_id"], r["player_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped_rows.append(r)

    # Write CSV
    out_dir = os.path.join("data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(
        out_dir, f"nfl_actives_{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}.csv"
    )
    fieldnames = [
        "week_window_start","week_window_end",
        "event_id","event_date",
        "home_team_id","home_team","away_team_id","away_team",
        "team_id","team_name",
        "player_id","player_name","position","college",
        "hometown","hometown_city","hometown_state","hometown_country","hometown_city_state",
        "years_experience",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(deduped_rows)

    print(f"Wrote {len(deduped_rows)} rows -> {out_path}")

    if UPLOAD_TO_SUPABASE and deduped_rows:
        supabase_upsert(deduped_rows)

    return 0

if __name__ == "__main__":
    sys.exit(main())

