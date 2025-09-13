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

# --------------------------
# Env loading (local.env)
# --------------------------
def _load_env():
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).with_name("local.env")
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
    except Exception:
        pass
_load_env()

def _get_env(primary, *aliases, default=None):
    for key in (primary, *aliases):
        val = os.getenv(key)
        if val:
            return val
    return default

# Supabase
SUPABASE_URL          = _get_env("SUPABASE_URL")
SUPABASE_SERVICE_ROLE = _get_env("SUPABASE_SERVICE_ROLE", "SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_TABLE        = _get_env("SUPABASE_TABLE", default="nfl_game_actives")
UPLOAD_TO_SUPABASE    = (_get_env("UPLOAD_TO_SUPABASE", default="false").lower() in {"1","true","yes"})

# Notion
NOTION_API_KEY        = _get_env("NOTION_API_KEY")
NOTION_DATABASE_ID    = _get_env("NOTION_DATABASE_ID")
UPLOAD_TO_NOTION      = (_get_env("UPLOAD_TO_NOTION", default="false").lower() in {"1","true","yes"})

# --------------------------
# Time zone
# --------------------------
try:
    import zoneinfo  # py3.9+
    TZ = zoneinfo.ZoneInfo("America/New_York")
except Exception:
    TZ = None

def today_local() -> dt.date:
    if TZ is not None:
        return dt.datetime.now(TZ).date()
    return dt.datetime.now().date()

# --------------------------
# HTTP config/helpers
# --------------------------
USER_AGENT = "Mozilla/5.0 (compatible; WeeklyNFLActives/1.3)"
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
def last_thu_to_mon_window(today: Optional[dt.date] = None) -> Tuple[dt.date, dt.date]:
    """Most recent Thu–Mon window that ended BEFORE 'today'."""
    if today is None:
        today = today_local()
    weekday = today.weekday()  # Mon=0..Sun=6
    days_since_mon = (weekday - 0) % 7
    end_mon = today - dt.timedelta(days=7 if days_since_mon == 0 else days_since_mon)
    start_thu = end_mon - dt.timedelta(days=4)
    return start_thu, end_mon

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
    service_key = SUPABASE_SERVICE_ROLE
    table = SUPABASE_TABLE

    if not url_base or not service_key:
        print("Skip Supabase upload: URL or service role missing.", file=sys.stderr)
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
# Notion upsert (optional)
# --------------------------
def _notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

def _notion_rich(text: Optional[str]):
    if not text:
        text = ""
    return [{"type": "text", "text": {"content": text[:2000]}}]

def _notion_date(iso_str: Optional[str]):
    # Accepts "YYYY-MM-DD" or ISO; returns date property dict
    if not iso_str:
        return None
    # Ensure date (not datetime) for week start/end
    try:
        if "T" in iso_str:
            # take date part
            iso_str = iso_str.split("T", 1)[0]
    except Exception:
        pass
    return {"start": iso_str}

def _notion_datetime(iso_str: Optional[str]):
    if not iso_str:
        return None
    return {"start": iso_str}

def notion_upsert(rows: List[dict]) -> None:
    if not (NOTION_API_KEY and NOTION_DATABASE_ID):
        print("Skip Notion upload: NOTION_API_KEY or NOTION_DATABASE_ID missing.", file=sys.stderr)
        return

    import requests

    # Build a lookup of existing pages by composite key to avoid duplicates
    # Notion has no native upsert: we query by filters, then update or create.
    # To reduce API calls, we do a batched approach per unique key.
    BASE = "https://api.notion.com/v1"
    db_query_url = f"{BASE}/databases/{NOTION_DATABASE_ID}/query"
    pages_url = f"{BASE}/pages"

    def page_props(row):
        return {
            "Player": {"title": _notion_rich(row.get("player_name"))},
            "Event ID": {"rich_text": _notion_rich(row.get("event_id"))},
            "Team ID": {"rich_text": _notion_rich(row.get("team_id"))},
            "Player ID": {"rich_text": _notion_rich(row.get("player_id"))},
            "Team": {"rich_text": _notion_rich(row.get("team_name"))},
            "Home Team": {"rich_text": _notion_rich(row.get("home_team"))},
            "Away Team": {"rich_text": _notion_rich(row.get("away_team"))},
            "Position": {"rich_text": _notion_rich(row.get("position"))},
            "College": {"rich_text": _notion_rich(row.get("college"))},
            "Hometown City": {"rich_text": _notion_rich(row.get("hometown_city"))},
            "Hometown State": {"rich_text": _notion_rich(row.get("hometown_state"))},
            "Hometown Country": {"rich_text": _notion_rich(row.get("hometown_country"))},
            "Hometown City, State": {"rich_text": _notion_rich(row.get("hometown_city_state"))},
            "Years Exp": {"number": row.get("years_experience")},
            "Week Start": {"date": _notion_date(row.get("week_window_start"))},
            "Week End": {"date": _notion_date(row.get("week_window_end"))},
            "Event Date": {"date": _notion_datetime(row.get("event_date"))},
        }

    headers = _notion_headers()

    # helper: find existing page id by composite key (event_id+team_id+player_id)
    def find_existing_page_id(ev_id, team_id, player_id):
        # Notion filter: AND of three rich_text contains exacts
        payload = {
            "filter": {
                "and": [
                    {"property": "Event ID", "rich_text": {"equals": ev_id}},
                    {"property": "Team ID", "rich_text": {"equals": team_id}},
                    {"property": "Player ID", "rich_text": {"equals": player_id}},
                ]
            },
            "page_size": 1,
        }
        r = requests.post(db_query_url, headers=headers, json=payload, timeout=60)
        if not r.ok:
            raise RuntimeError(f"Notion query failed: {r.status_code} {r.text[:200]}")
        data = r.json()
        results = data.get("results", [])
        if results:
            return results[0]["id"]
        return None

    # create or update one page
    def upsert_row(row):
        ev = row.get("event_id") or ""
        tm = row.get("team_id") or ""
        pid = row.get("player_id") or ""
        page_id = find_existing_page_id(ev, tm, pid)

        if page_id:
            url = f"{BASE}/pages/{page_id}"
            payload = {"properties": page_props(row)}
            r = requests.patch(url, headers=headers, json=payload, timeout=60)
            if not r.ok:
                raise RuntimeError(f"Notion update failed: {r.status_code} {r.text[:200]}")
        else:
            payload = {
                "parent": {"database_id": NOTION_DATABASE_ID},
                "properties": page_props(row),
            }
            r = requests.post(pages_url, headers=headers, json=payload, timeout=60)
            if not r.ok:
                raise RuntimeError(f"Notion create failed: {r.status_code} {r.text[:200]}")

    # Rate limit protection (3 req/sec typical). We already query then create/update: ~2 calls/row.
    for i, row in enumerate(rows, 1):
        upsert_row(row)
        if i % 3 == 0:
            time.sleep(1.0)
    print(f"Upserted {len(rows)} pages to Notion.", file=sys.stderr)

# --------------------------
# Main
# --------------------------
def main() -> int:
    start, end = last_thu_to_mon_window()
    print(f"[window] {start} -> {end}", file=sys.stderr)

    events = parse_events_from_scoreboard(start, end)
    if not events:
        print("No NFL events found for window.", file=sys.stderr)

    rows: List[Dict[str, Optional[str]]] = []

    for ev in events:
        event_id = str(ev.get("id"))
        event_date = ev.get("date")
        competitions = ev.get("competitions", [])
        if not competitions:
            continue
        comp = competitions[0]
        competition_id = str(comp.get("id") or event_id)

        home_team = away_team = home_id = away_id = None
        for c in comp.get("competitors", []):
            tid = safe_get(c, ["team", "id"])
            tname = safe_get(c, ["team", "displayName"])
            if c.get("homeAway") == "home":
                home_team, home_id = tname, tid
            else:
                away_team, away_id = tname, tid

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

    # Dedup (event_id, team_id, player_id)
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
        "week_window_start","week_window_end","event_id","event_date",
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
    print(f"[csv] wrote {len(deduped_rows)} rows -> {out_path}", file=sys.stderr)

    # Uploads
    if UPLOAD_TO_SUPABASE:
        supabase_upsert(deduped_rows)
    if UPLOAD_TO_NOTION:
        notion_upsert(deduped_rows)

    return 0

if __name__ == "__main__":
    sys.exit(main())



