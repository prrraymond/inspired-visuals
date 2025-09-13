#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NYC Subway Ridership ETL 
------------------------
Supports both hourly ridership (recommended) and legacy turnstile data processing.

What it does
- Downloads only *new* weekly turnstile files from MTA (turnstile_YYMMDD.txt)
- Cleans cumulative counters -> deltas; filters resets/anomalies
- Aggregates to station-day and line-day totals
- Computes time-series seasonal components (weekday pattern, STL trend/seasonal)
- Saves tidy history to Parquet for reuse

Outputs (in ./data/)
- turnstile_station_daily.parquet   # station-day entries
- turnstile_line_daily.parquet      # line-day entries
- features_station_daily.parquet    # decomposed features per station (optional)
- features_line_daily.parquet       # decomposed features per line (optional)
- last_processed_saturday.txt       # state

Optional:
- Pull station metadata from NY Open Data (dataset 39hk-dx4f) to get services/complex IDs.
- Pull hourly ridership (dataset wujg-7c2s) instead of turnstiles (set USE_HOURLY=True).

Run
- python nyc_turnstile_weekly.py        # processes new weeks up to last Saturday
- python nyc_turnstile_weekly.py --since 2023-01-01

Cron (runs every Monday 6am)
- 0 6 * * 1 /usr/bin/python3 /path/nyc_turnstile_weekly.py >> /path/turnstile.log 2>&1
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import textwrap
import time
import math
from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional

import numpy as np
import pandas as pd
import requests

# Optional seasonal decomposition
try:
    from statsmodels.tsa.seasonal import STL
    HAS_STL = True
except Exception:
    HAS_STL = False

# Optional Supabase publishing
try:
    from supabase import create_client
except Exception:
    create_client = None

# Optional .env file loading
try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False

DATA_DIR = "/Users/paulraymond/Documents/DataViz/data/NYC"
os.makedirs(DATA_DIR, exist_ok=True)

STATE_FILE = os.path.join(DATA_DIR, "last_processed_saturday.txt")
STATION_DAILY = os.path.join(DATA_DIR, "turnstile_station_daily.parquet")
LINE_DAILY = os.path.join(DATA_DIR, "turnstile_line_daily.parquet")

FEATURES_STATION = os.path.join(DATA_DIR, "features_station_daily.parquet")
FEATURES_LINE = os.path.join(DATA_DIR, "features_line_daily.parquet")

STATION_DAILY_CSV = os.path.join(DATA_DIR, "turnstile_station_daily.csv")
LINE_DAILY_CSV = os.path.join(DATA_DIR, "turnstile_line_daily.csv")
FEATURES_STATION_CSV = os.path.join(DATA_DIR, "features_station_daily.csv")
FEATURES_LINE_CSV = os.path.join(DATA_DIR, "features_line_daily.csv")

# ---- Config ----
MTA_TURNSTILE_BASE = "https://web.mta.info/developers/data/nyct/turnstile"

# NY Open Data (Socrata) for station metadata and hourly ridership
SODA_BASE = "https://data.ny.gov/resource"
DATASET_STATIONS = "39hk-dx4f"      # MTA Subway Stations
DATASET_HOURLY_2020_2024 = "wujg-7c2s"  # Hourly ridership 2020-12-01 .. 2024-12-31
DATASET_HOURLY_2025_PLUS = "5wq4-mkjj"  # Hourly ridership 2025-01-01 .. present

def _soda_headers():
    """Get headers for NY Open Data API requests"""
    tok = os.getenv("SODA_APP_TOKEN") or os.getenv("NYC_TOKEN")
    return {"X-App-Token": tok} if tok else {}

# --------------------------- Helpers ---------------------------

def last_saturday(today: Optional[date] = None) -> date:
    if today is None:
        today = date.today()
    return today - timedelta(days=(today.weekday() + 2) % 7 + 1)

def saturday_range(start_saturday: date, end_saturday: date) -> List[date]:
    cur = start_saturday
    out = []
    while cur <= end_saturday:
        if cur.weekday() == 5:
            out.append(cur)
        cur += timedelta(days=7)
    return out

def mta_week_url(sat: date) -> str:
    yy = str(sat.year)[2:]
    mm = f"{sat.month:02d}"
    dd = f"{sat.day:02d}"
    return f"{MTA_TURNSTILE_BASE}/turnstile_{yy}{mm}{dd}.txt"

def read_state_date() -> Optional[date]:
    if not os.path.exists(STATE_FILE):
        return None
    txt = open(STATE_FILE).read().strip()
    try:
        return date.fromisoformat(txt)
    except Exception:
        return None

def write_state_date(sat: date) -> None:
    with open(STATE_FILE, "w") as f:
        f.write(sat.isoformat())

def fetch_week_csv(sat: date) -> pd.DataFrame:
    url = mta_week_url(sat)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    # Normalize columns
    df.columns = [c.strip().upper() for c in df.columns]
    df["DATETIME"] = pd.to_datetime(df["DATE"].astype(str) + " " + df["TIME"].astype(str))
    return df

def compute_deltas(df: pd.DataFrame) -> pd.DataFrame:
    # Sort to compute deltas per turnstile
    sort_cols = ["C/A", "UNIT", "SCP", "STATION", "LINENAME", "DATETIME"]
    df = df.sort_values(sort_cols)
    # group per physical counter
    grp = df.groupby(["C/A", "UNIT", "SCP", "STATION", "LINENAME"], sort=False, group_keys=False)
    for col in ["ENTRIES", "EXITS"]:
        df[f"{col}_DELTA"] = grp[col].diff()
        # Handle counter resets/rollovers/negatives/huge jumps
        df.loc[(df[f"{col}_DELTA"] < 0) | (df[f"{col}_DELTA"] > 50000) | (df[f"{col}_DELTA"].isna()), f"{col}_DELTA"] = 0
    # Sum to daily per station
    df["SERVICE_DATE"] = df["DATETIME"].dt.date
    daily = (
        df.groupby(["STATION", "LINENAME", "SERVICE_DATE"], as_index=False)[["ENTRIES_DELTA", "EXITS_DELTA"]]
          .sum()
          .rename(columns={"ENTRIES_DELTA": "entries", "EXITS_DELTA": "exits"})
    )
    # Clean station names/lines
    daily["station"] = daily["STATION"].str.title()
    daily["lines"] = daily["LINENAME"].str.upper()
    daily = daily.drop(columns=["STATION", "LINENAME"]).rename(columns={"SERVICE_DATE": "date"})
    daily["ridership_proxy"] = daily["entries"]
    return daily

def upsert_parquet(path: str, new_df: pd.DataFrame, keys: List[str]) -> None:
    if os.path.exists(path):
        base = pd.read_parquet(path)
        merged = (
            pd.concat([base, new_df], ignore_index=True)
              .drop_duplicates(subset=keys, keep="last")
        )
    else:
        merged = new_df
    merged = merged.sort_values(keys)
    merged.to_parquet(path, index=False)

def add_weekday_and_rolling(df: pd.DataFrame, group_cols: List[str]) -> pd.DataFrame:
    out = df.copy()
    out["weekday"] = pd.to_datetime(out["date"]).dt.day_name()
    out["dow"] = pd.to_datetime(out["date"]).dt.weekday
    out = out.sort_values(group_cols + ["date"])
    out["entries_7d_avg"] = out.groupby(group_cols)["entries"].transform(lambda s: s.rolling(7, min_periods=1).mean())
    return out

def stl_decompose(df: pd.DataFrame, group_cols: List[str], value_col: str = "entries") -> pd.DataFrame:
    if not HAS_STL:
        return pd.DataFrame()
    frames = []
    for keys, g in df.sort_values("date").groupby(group_cols):
        g2 = g.set_index(pd.to_datetime(g["date"])).asfreq("D")
        series = g2[value_col].fillna(0.0)
        if len(series) < 60:
            continue
        res = STL(series, period=7, robust=True).fit()
        comp = pd.DataFrame({
            "date": series.index.date,
            value_col: series.values,
            "trend": res.trend.values,
            "seasonal_weekly": res.seasonal.values,
            "remainder": res.resid.values
        })
        if isinstance(keys, tuple):
            for col, val in zip(group_cols, keys):
                comp[col] = val
        else:
            comp[group_cols[0]] = keys
        frames.append(comp.reset_index(drop=True))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

# ===== Hourly ridership functions =====

def _month_ends(start_d: date, end_d: date):
    """Yield (win_start, win_end) inclusive for month windows covering [start_d, end_d]."""
    cur = date(start_d.year, start_d.month, 1)
    if start_d.day != 1:
        cur = date(start_d.year, start_d.month, 1)
    while cur <= end_d:
        next_month = date(cur.year + (cur.month // 12), ((cur.month % 12) + 1), 1)
        last_of_month = next_month - timedelta(days=1)
        win_start = max(cur, start_d)
        win_end = min(last_of_month, end_d)
        yield (win_start, win_end)
        cur = next_month

def _retry_get(url, params, max_tries=5, base_sleep=1.5):
    for i in range(max_tries):
        r = requests.get(url, params=params, headers=_soda_headers(), timeout=120)
        if r.status_code < 500 and r.status_code != 429:
            r.raise_for_status()
            return r
        sleep = base_sleep * (2 ** i) * (1 + 0.1 * i)
        time.sleep(sleep)
    r.raise_for_status()
    return r

def fetch_hourly_since(since_date: str, until: Optional[str] = None, debug: bool = False) -> pd.DataFrame:
    """
    Robust pull of hourly ridership aggregated to station-day, across both datasets.
    """
    since_d = pd.to_datetime(since_date).date()
    until_d = pd.to_datetime(until, errors="coerce").date() if until else date.today()
    cutoff = date(2024, 12, 31)

    def month_windows(start_d: date, end_d: date):
        cur = date(start_d.year, start_d.month, 1)
        if start_d.day != 1:
            cur = date(start_d.year, start_d.month, 1)
        while cur <= end_d:
            nxt = date(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1)
            last = nxt - timedelta(days=1)
            yield max(cur, start_d), min(last, end_d)
            cur = nxt

    def fetch_window(dataset_id: str, win_start: date, win_end: date) -> pd.DataFrame:
        url = f"{SODA_BASE}/{dataset_id}.json"
        end_exclusive = (win_end + timedelta(days=1)).isoformat()
        where = (
            f"transit_timestamp >= '{win_start.isoformat()}T00:00:00' "
            f"AND transit_timestamp < '{end_exclusive}T00:00:00'"
        )
        limit = 20000
        offset = 0
        frames = []
        tries = 0
        
        while True:
            params = {
                "$select": "station_complex, station_complex_id, borough, "
                           "date_trunc_ymd(transit_timestamp) as date, sum(ridership) as entries",
                "$where": where,
                "$group": "station_complex, station_complex_id, borough, date_trunc_ymd(transit_timestamp)",
                "$order": "date, station_complex",
                "$limit": limit,
                "$offset": offset,
            }
            r = requests.get(url, params=params, headers=_soda_headers(), timeout=120)
            if r.status_code in (429, 500, 502, 503, 504) and tries < 4:
                tries += 1
                time.sleep(1.5 * (2 ** tries))
                continue
            r.raise_for_status()
            js = r.json()
            if not js:
                break
            df = pd.DataFrame(js)
            if df.empty:
                break
                
            # DEBUG: Print what we're getting from API
            if debug and offset == 0 and len(frames) == 0:  # First batch only
                print(f"DEBUG - API returned columns: {df.columns.tolist()}")
                if not df.empty:
                    print(f"DEBUG - Sample API row: {df.iloc[0].to_dict()}")
            
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df["entries"] = df["entries"].astype(float)
            df = df.rename(columns={"station_complex": "station", "station_complex_id": "complex_id"})
            frames.append(df[["date", "station", "complex_id", "borough", "entries"]])
            if len(df) < limit:
                break
            offset += limit
            
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
            columns=["date","station","complex_id","borough","entries"]
        )

    all_frames = []

    # Part A: 2020–2024 dataset
    if since_d <= cutoff:
        a_start, a_end = since_d, min(until_d, cutoff)
        for ws, we in month_windows(a_start, a_end):
            part = fetch_window(DATASET_HOURLY_2020_2024, ws, we)
            if not part.empty:
                all_frames.append(part)

    # Part B: 2025+ dataset
    if until_d > cutoff:
        b_start, b_end = max(since_d, cutoff + timedelta(days=1)), until_d
        for ws, we in month_windows(b_start, b_end):
            part = fetch_window(DATASET_HOURLY_2025_PLUS, ws, we)
            if not part.empty:
                all_frames.append(part)

    if not all_frames:
        return pd.DataFrame(columns=["date","station","complex_id","borough","entries"])

    out = pd.concat(all_frames, ignore_index=True)
    out = out.drop_duplicates(subset=["station","date"], keep="last")
    
    # DEBUG: Print final data info
    print(f"DEBUG - Final columns: {out.columns.tolist()}")
    if not out.empty:
        print(f"DEBUG - Sample final row: {out.iloc[0].to_dict()}")
        print(f"DEBUG - Borough null count: {out['borough'].isna().sum()}/{len(out)}")
        print(f"DEBUG - Complex_id null count: {out['complex_id'].isna().sum()}/{len(out)}")
    
    return out

# -------- Station metadata --------

def fetch_station_metadata(limit: int = 5000) -> pd.DataFrame:
    url = f"{SODA_BASE}/{DATASET_STATIONS}.json"
    params = {"$limit": limit}
    r = requests.get(url, params=params, headers=_soda_headers(), timeout=60)
    r.raise_for_status()
    js = r.json()
    if not js:
        return pd.DataFrame()
    df = pd.DataFrame(js)
    rename = {
        "station_name": "station_name",
        "gtfs_stop_id": "gtfs_stop_id",
        "complex_id": "complex_id",
        "services": "services",
        "borough": "borough",
        "the_geom": "the_geom"
    }
    cols = [c for c in rename if c in df.columns]
    return df[cols].rename(columns=rename)

def save_csv(df: pd.DataFrame, path: str, sort_cols: list[str]):
    tmp = df.sort_values(sort_cols)
    tmp.to_csv(path, index=False)

# ===== Supabase publishing =====

def publish_csv_to_supabase(csv_path: str, table: str, pk_cols: list[str], include_columns: list[str] = None) -> None:
    """
    Upsert a CSV view into Supabase (Postgres) via the Supabase Python client.
    """
    if create_client is None:
        print("Supabase client not installed; skipping publish.")
        return

    # Load environment variables from .env.local file
    if HAS_DOTENV:
        load_dotenv(".env.local")

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not (url and key):
        print("Supabase env not set; skipping publish.")
        return

    df = pd.read_csv(csv_path)
    if df.empty:
        print(f"No rows to publish for {table}.")
        return

    # Filter columns if specified
    if include_columns:
        available_cols = [col for col in include_columns if col in df.columns]
        missing_cols = [col for col in include_columns if col not in df.columns]
        if missing_cols:
            print(f"Warning: Missing columns in data: {missing_cols}")
        df = df[available_cols]
        print(f"Using columns: {list(df.columns)}")

    # Clean the data to make it JSON compliant
    df = df.copy()
    
    # Replace NaN values with None (which becomes null in JSON)
    df = df.where(pd.notnull(df), None)
    
    # Handle infinite values
    df = df.replace([np.inf, -np.inf], None)
    
    # Convert numeric columns to appropriate types
    for col in df.columns:
        if col in ['entries', 'exits', 'complex_id']:
            # Convert float to integer for count/ID columns
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
        elif df[col].dtype == 'object' and 'date' in col.lower():
            df[col] = df[col].astype(str)
        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime('%Y-%m-%d')

    supa = create_client(url, key)
    # Upsert in manageable chunks
    chunk = 2000
    for i in range(0, len(df), chunk):
        batch_df = df.iloc[i:i+chunk]
        payload = batch_df.to_dict(orient="records")
        
        # Double-check: clean up any remaining problematic values
        for record in payload:
            for key, value in record.items():
                if pd.isna(value) or value in [np.inf, -np.inf]:
                    record[key] = None
                elif isinstance(value, np.integer):
                    record[key] = int(value)
                elif isinstance(value, np.floating):
                    if np.isfinite(value):
                        record[key] = float(value)
                    else:
                        record[key] = None
        
        try:
            resp = supa.table(table).upsert(payload, on_conflict=",".join(pk_cols)).execute()
            if getattr(resp, "error", None):
                raise RuntimeError(f"Supabase upsert error: {resp.error}")
        except Exception as e:
            print(f"Error uploading batch {i//chunk + 1}: {e}")
            print(f"Sample records from batch: {payload[:2]}")
            raise
            
    print(f"Published {len(df)} rows to {table}.")

# --------------------------- Main ETL ---------------------------

def run(since: Optional[str] = None,
        use_hourly: bool = False,
        build_features: bool = True) -> None:

    if use_hourly:
        if since is None:
            prev = read_state_date()
            since = (prev or date(2022, 2, 1)).isoformat()

        hourly = fetch_hourly_since(since, date.today().isoformat())
        if hourly.empty:
            print("No hourly data returned; nothing to do.")
            return

        hourly["lines"] = np.nan  # not in hourly dataset; join later if desired
        upsert_parquet(STATION_DAILY, hourly, ["station", "date"])

        # Write CSV view
        sd = pd.read_parquet(STATION_DAILY)
        save_csv(sd, STATION_DAILY_CSV, ["station", "date"])

        # Publish to Supabase if requested
        if args.publish:
            print(f"[publish] reading {STATION_DAILY_CSV}")
            publish_csv_to_supabase(
                STATION_DAILY_CSV,
                os.getenv("SUPABASE_STATION_TABLE", "station_daily"),
                ["station", "date"],
                include_columns=["station", "date", "entries", "lines", "borough", "complex_id"]  # ← Added these
            )

        write_state_date(last_saturday())
        print(f"Hourly ETL complete: {sd['date'].min()} → {sd['date'].max()}")
        return

    # ---- Turnstile (raw weekly) path ----
    end_sat = last_saturday()
    if since:
        start = pd.to_datetime(since).date()
        start_sat = start + timedelta(days=(5 - start.weekday()) % 7)
    else:
        prev = read_state_date()
        start_sat = (prev + timedelta(days=7)) if prev else date(2010, 1, 2)
    
    weeks = saturday_range(start_sat, end_sat)
    if not weeks:
        print("No new weeks to process.")
        return

    all_station_daily = []
    for sat in weeks:
        try:
            raw = fetch_week_csv(sat)
        except Exception as e:
            print(f"Skipping {sat}: {e}")
            continue
        daily = compute_deltas(raw)
        all_station_daily.append(daily)

    if not all_station_daily:
        print("No weekly files processed.")
        return

    station_daily = pd.concat(all_station_daily, ignore_index=True)
    
    # Upsert station-day
    upsert_parquet(STATION_DAILY, station_daily, ["station", "lines", "date"])
    sd = pd.read_parquet(STATION_DAILY)
    save_csv(sd, STATION_DAILY_CSV, ["station", "date"])

    # Build line-day from station-day
    exploded = (sd.assign(line_list=sd["lines"].fillna("").apply(lambda s: list(str(s)))))
    exploded = exploded.explode("line_list")
    exploded = exploded[exploded["line_list"].str.len() > 0]
    line_daily = (exploded.groupby(["line_list", "date"], as_index=False)["entries"].sum()
                           .rename(columns={"line_list": "line"}))
    upsert_parquet(LINE_DAILY, line_daily, ["line", "date"])
    ld = pd.read_parquet(LINE_DAILY)
    save_csv(ld, LINE_DAILY_CSV, ["line", "date"])

    # Optional: seasonal features
    if build_features and HAS_STL:
        sd2 = add_weekday_and_rolling(sd, ["station"])
        stl_s = stl_decompose(sd2, ["station"])
        if not stl_s.empty:
            stl_s.to_parquet(FEATURES_STATION, index=False)
            save_csv(stl_s, FEATURES_STATION_CSV, ["station", "date"])

        ld2 = add_weekday_and_rolling(line_daily, ["line"])
        stl_l = stl_decompose(ld2, ["line"])
        if not stl_l.empty:
            stl_l.to_parquet(FEATURES_LINE, index=False)
            save_csv(stl_l, FEATURES_LINE_CSV, ["line", "date"])

    # Publish to Supabase if requested
#     if args.publish:
#         print(f"[publish] reading {STATION_DAILY_CSV}")
#         publish_csv_to_supabase(
#             STATION_DAILY_CSV,
#             os.getenv("SUPABASE_STATION_TABLE", "station_daily"),
#             ["station", "date"],
#             include_columns=["station", "date", "entries", "lines", "borough", "complex_id"]  # ← Added these
# )
        
#         if os.getenv("SUPABASE_LINE_TABLE"):
#             print(f"[publish] reading {LINE_DAILY_CSV}")
#             publish_csv_to_supabase(
#                 LINE_DAILY_CSV,
#                 os.getenv("SUPABASE_LINE_TABLE", "line_daily"),
#                 ["line", "date"],
#                 include_columns=["line", "date", "entries"]
#             )

    write_state_date(end_sat)
    print(f"Processed {len(weeks)} week(s): {weeks[0]} → {weeks[-1]}")
    print(f"Station daily saved: {STATION_DAILY}")
    print(f"Line daily saved:    {LINE_DAILY}")
    if build_features and HAS_STL:
        print(f"Features saved: {FEATURES_STATION}, {FEATURES_LINE}")

    # At end of turnstile processing, before write_state_date():
    print(f"Station CSV: {len(pd.read_csv(STATION_DAILY_CSV))} rows")
    print(f"Line CSV: {len(pd.read_csv(LINE_DAILY_CSV))} rows") 
    print(f"Date range: {sd['date'].min()} → {sd['date'].max()}")
    print(f"Lines found: {sorted(ld['line'].unique())}")

        # At end of run() turnstile section:
    if args.psycopg:
        import subprocess
        subprocess.run(["python", "turnstile_agg_to_supabase.py"])


# --------------------------- CLI ---------------------------

def parse_args():
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(__doc__)
    )
    p.add_argument("--since", help="Earliest date to (re)process, e.g., 2019-01-01. If omitted, continues after last processed Saturday.")
    p.add_argument("--hourly", action="store_true", help="Use NY Open Data hourly ridership (post-2022) instead of raw turnstiles.")
    p.add_argument("--no-features", action="store_true", help="Skip STL/feature generation.")
    p.add_argument("--publish", action="store_true", help="Upsert CSV views to Supabase after local writes.")
    p.add_argument("--psycopg", action="store_true", help="Run psycopg bulk loader after CSV generation.")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(since=args.since, use_hourly=args.hourly, build_features=not args.no_features)