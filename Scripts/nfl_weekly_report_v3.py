#!/usr/bin/env python3
import os
import sys
import csv
import time
import json
import argparse
import datetime as dt
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
import urllib.request

# =========================
# 0) CLI: modes + testing date
# =========================
def parse_args():
    p = argparse.ArgumentParser(description="NFL weekly report (CSV + Supabase + Notion).")
    p.add_argument("--mode", choices=["previous", "rolling"], default="previous",
                   help="previous = last Thu→Mon ending before today; rolling = last Thu→coming Tue")
    p.add_argument("--today", help="Simulate today's date YYYY-MM-DD (testing)")
    return p.parse_args()

ARGS = parse_args()

# =========================
# 1) Env (exactly like your other script)
#    DataViz/.env.local
# =========================
try:
    from dotenv import load_dotenv
except Exception as e:
    raise SystemExit("python-dotenv is required. Install with: pip install python-dotenv") from e

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # .../DataViz
ENV_PATH = PROJECT_ROOT / ".env.local"
if not ENV_PATH.exists():
    raise SystemExit(f"Missing {ENV_PATH}. Create it with your keys.")

# load exactly like your other working script
load_dotenv(dotenv_path=ENV_PATH)

# --- Supabase (optional) ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE", "nfl_weekly_report")  # name this table for this script
UPLOAD_TO_SUPABASE = (os.getenv("UPLOAD_TO_SUPABASE", "true").lower() in {"1", "true", "yes"})

# --- Notion (optional) ---
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")  # provide your DB id in .env.local
UPLOAD_TO_NOTION = (os.getenv("UPLOAD_TO_NOTION", "true").lower() in {"1", "true", "yes"})

print(
    f"[env] .env.local loaded | upload_supa={UPLOAD_TO_SUPABASE} "
    f"url={'set' if bool(SUPABASE_URL) else 'missing'} "
    f"key={'set' if bool(SUPABASE_KEY) else 'missing'} "
    f"supa_table={SUPABASE_TABLE} | upload_notion={UPLOAD_TO_NOTION} "
    f"notion={'set' if bool(NOTION_API_KEY) and bool(NOTION_DATABASE_ID) else 'missing'}"
)

if UPLOAD_TO_SUPABASE and (not SUPABASE_URL or not SUPABASE_KEY):
    raise SystemExit("UPLOAD_TO_SUPABASE=true but SUPABASE_URL or SUPABASE_*KEY missing in .env.local")
if UPLOAD_TO_NOTION and (not NOTION_API_KEY or not NOTION_DATABASE_ID):
    raise SystemExit("UPLOAD_TO_NOTION=true but NOTION_API_KEY or NOTION_DATABASE_ID missing in .env.local")

# =========================
# 2) Date windows (rolling / previous)
# =========================
try:
    import zoneinfo  # py3.9+
    TZ = zoneinfo.ZoneInfo("America/New_York")
except Exception:
    TZ = None

def today_local() -> dt.date:
    if ARGS.today:
        return dt.datetime.strptime(ARGS.today, "%Y-%m-%d").date()
    if TZ:
        return dt.datetime.now(TZ).date()
    return dt.datetime.now().date()

def last_thu_before(date_: dt.date) -> dt.date:
    # Mon=0..Sun=6; Thu=3
    delta = (date_.weekday() - 3) % 7
    return date_ - dt.timedelta(days=delta)

def window_previous(today: dt.date) -> Tuple[dt.date, dt.date]:
    """Last Thu→Mon ending strictly before today."""
    weekday = today.weekday()  # Mon=0..Sun=6
    days_since_mon = (weekday - 0) % 7
    end_mon = today - dt.timedelta(days=7 if days_since_mon == 0 else days_since_mon)
    start_thu = end_mon - dt.timedelta(days=4)
    return start_thu, end_mon

def window_rolling(today: dt.date) -> Tuple[dt.date, dt.date]:
    """Rolling Thu→Tue around today (ongoing weekend)."""
    start_thu = last_thu_before(today)
    end_tue = start_thu + dt.timedelta(days=5)
    return start_thu, end_tue

def choose_window(mode: str, today: dt.date) -> Tuple[dt.date, dt.date]:
    return window_rolling(today) if mode == "rolling" else window_previous(today)

# =========================
# 3) ESPN fetchers
# =========================
USER_AGENT = "Mozilla/5.0 (compatible; NFLWeeklyReport/2.0)"
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

# =========================
# 4) Outputs
# =========================
def supabase_upsert(rows: List[dict]) -> None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Skip Supabase upload: missing URL or KEY.", file=sys.stderr)
        return
    try:
        import requests
    except Exception as e:
        raise SystemExit("requests is required for Supabase upload. pip install requests") from e

    endpoint = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
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
        print(f"Upserted {len(chunk)} rows to Supabase ({i+len(chunk)}/{total})", file=sys.stderr)

# Notion upsert: query by composite key (Event ID + Team ID + Player ID), then update/create
def notion_upsert(rows: List[dict]) -> None:
    if not (NOTION_API_KEY and NOTION_DATABASE_ID):
        print("Skip Notion upload: NOTION_API_KEY/NOTION_DATABASE_ID missing.", file=sys.stderr)
        return
    try:
        import requests
    except Exception as e:
        raise SystemExit("requests is required for Notion upload. pip install requests") from e

    BASE = "https://api.notion.com/v1"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    def rt(text: Optional[str]):
        if not text: text = ""
        return [{"type": "text", "text": {"content": text[:2000]}}]

    def date_prop(iso_date: Optional[str]):
        if not iso_date: return None
        # if timestamp, keep start as full ISO; for week dates, send YYYY-MM-DD
        if "T" in iso_date:
            return {"start": iso_date}
        return {"start": iso_date}

    def props(row):
        return {
            "Player": {"title": rt(row.get("player_name"))},  # Title prop
            "Event ID": {"rich_text": rt(row.get("event_id"))},
            "Team ID": {"rich_text": rt(row.get("team_id"))},
            "Player ID": {"rich_text": rt(row.get("player_id"))},
            "Team": {"rich_text": rt(row.get("team_name"))},
            "Home Team": {"rich_text": rt(row.get("home_team"))},
            "Away Team": {"rich_text": rt(row.get("away_team"))},
            "Position": {"rich_text": rt(row.get("position"))},
            "College": {"rich_text": rt(row.get("college"))},
            "Hometown City": {"rich_text": rt(row.get("hometown_city"))},
            "Hometown State": {"rich_text": rt(row.get("hometown_state"))},
            "Hometown Country": {"rich_text": rt(row.get("hometown_country"))},
            "Hometown City, State": {"rich_text": rt(row.get("hometown_city_state"))},
            "Years Exp": {"number": row.get("years_experience")},
            "Week Start": {"date": date_prop(row.get("week_window_start"))},
            "Week End": {"date": date_prop(row.get("week_window_end"))},
            "Event Date": {"date": date_prop(row.get("event_date"))},
        }

    def find_page_id(ev_id, team_id, player_id):
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
        r = requests.post(f"{BASE}/databases/{NOTION_DATABASE_ID}/query", headers=headers, json=payload, timeout=60)
        if not r.ok:
            raise RuntimeError(f"Notion query failed: {r.status_code} {r.text[:200]}")
        data = r.json()
        res = data.get("results", [])
        return res[0]["id"] if res else None

    def upsert_row(row):
        pid = find_page_id(row.get("event_id",""), row.get("team_id",""), row.get("player_id",""))
        if pid:
            r = requests.patch(f"{BASE}/pages/{pid}", headers=headers, json={"properties": props(row)}, timeout=60)
            if not r.ok:
                raise RuntimeError(f"Notion update failed: {r.status_code} {r.text[:200]}")
        else:
            payload = {"parent": {"database_id": NOTION_DATABASE_ID}, "properties": props(row)}
            r = requests.post(f"{BASE}/pages", headers=headers, json=payload, timeout=60)
            if not r.ok:
                raise RuntimeError(f"Notion create failed: {r.status_code} {r.text[:200]}")

    # gentle rate-limiting
    for i, row in enumerate(rows, 1):
        upsert_row(row)
        if i % 3 == 0:
            time.sleep(1.0)
    print(f"Upserted/updated {len(rows)} Notion pages.", file=sys.stderr)

# =========================
# 5) Main
# =========================
def main() -> int:
    today = today_local()
    start, end = choose_window(ARGS.mode, today)
    print(f"[window] {start} -> {end}")

    # 1) Fetch games
    events = parse_events_from_scoreboard(start, end)
    if not events:
        print("No NFL events found for window.")

    # 2) Build rows (actives per game/team, fallback to team roster)
    rows: List[Dict[str, Optional[str]]] = []

    for ev in events:
        event_id = str(ev.get("id"))
        event_date = ev.get("date")  # ISO string
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

    # 3) Deduplicate by (event_id, team_id, player_id)
    seen = set()
    deduped = []
    for r in rows:
        key = (r["event_id"], r["team_id"], r["player_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    # 4) CSV
    out_dir = os.path.join("data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"nfl_actives_{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}.csv")
    fieldnames = [
        "week_window_start","week_window_end","event_id","event_date",
        "home_team_id","home_team","away_team_id","away_team",
        "team_id","team_name",
        "player_id","player_name","position","college",
        "hometown","hometown_city","hometown_state","hometown_country","hometown_city_state",
        "years_experience",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(deduped)
    print(f"[csv] wrote {len(deduped)} rows -> {out_path}")

    # 5) Uploads (optional)
    if UPLOAD_TO_SUPABASE and deduped:
        supabase_upsert(deduped)
    if UPLOAD_TO_NOTION and deduped:
        notion_upsert(deduped)

    return 0

if __name__ == "__main__":
    sys.exit(main())
