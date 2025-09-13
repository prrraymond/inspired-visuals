#!/usr/bin/env python3
"""
NFL Weekly Report (v1)
---------------------------------
Generates a NotebookLM-ready weekly NFL performance package with:
  - Header (manual still + caption/link placeholders)
  - "My Faves" table (with headshots, weekly composite score, 4-week trend arrows)
  - Top QBs table (QBR vs Passer Rating)
  - Top WRs table
  - Geo breakdown bar chart by player hometown city (with Miami callout)
  - A master `report_index.md` that stitches everything together

Data Source: ESPN internal JSON endpoints (no official API keys required):
  - Scoreboard: https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
  - Summary:    https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=<EVENT_ID>

USAGE
-----
python nfl_weekly_report_v1.py \
  --favorites "Patrick Mahomes, Tyreek Hill, CeeDee Lamb, Josh Allen" \
  --outdir weekly_report \
  [--miami "Miami, FL"] \
  [--hometowns_csv /path/to/actives_with_hometowns.csv] \
  [--week 1 --year 2025] \
  [--dump-one]

NOTES
-----
- QBR is proprietary to ESPN. It is usually present in the summary JSON but can occasionally be missing.
- Passer Rating (RTG) is from passing stats in the box score.
- Headshots come from athlete metadata in the summary payload; cached under outdir/faves_headshots/.
- Trend arrows (↑ → ↓) are computed from a local history file: outdir/history_composites.csv (auto-created).
- Geo breakdown requires a CSV with hometown data (or skip this section if unavailable). See `--hometowns_csv`.
- This script is defensive to minor JSON shape changes but ESPN can shift fields without notice.

DEPENDENCIES
------------
Python 3.9+
requests, pandas, numpy, pillow (PIL), matplotlib

pip install requests pandas numpy pillow matplotlib
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from PIL import Image
from io import BytesIO
import matplotlib.pyplot as plt

BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"


# Load local.env sitting next to the script (adjust path if needed)
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).with_name("local.env")
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
except Exception:
    pass  # still okay if dotenv isn't installed

def _get_env(primary, *aliases, default=None):
    """Return the first found env var among primary or aliases."""
    for key in (primary, *aliases):
        val = os.getenv(key)
        if val:
            return val
    return default

# Map YOUR keys to what the uploader expects
SUPABASE_URL          = _get_env("SUPABASE_URL")
SUPABASE_SERVICE_ROLE = _get_env("SUPABASE_SERVICE_ROLE", "SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_TABLE        = _get_env("SUPABASE_TABLE", default="nfl_game_actives")
SUPABASE_SCHEMA       = _get_env("SUPABASE_SCHEMA", default="public")
UPLOAD_TO_SUPABASE    = (_get_env("UPLOAD_TO_SUPABASE", default="true").lower() in {"1","true","yes"})

# Optional: sanity print (comment out in CI)
print(f"[env] URL={bool(SUPABASE_URL)} SR={bool(SUPABASE_SERVICE_ROLE)} TABLE={SUPABASE_TABLE} UPLOAD={UPLOAD_TO_SUPABASE}")


# -----------------------------
# Helpers
# -----------------------------

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except (ValueError, TypeError):
        return None


def _safe_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        return int(x)
    except (ValueError, TypeError):
        return None


# -----------------------------
# ESPN fetchers
# -----------------------------

def get_scoreboard(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fetch the current (or parameterized) scoreboard."""
    url = f"{BASE}/scoreboard"
    r = requests.get(url, params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def get_week_info(board: Dict[str, Any]) -> Tuple[int, int]:
    season = board.get("season", {})
    year = season.get("year") or dt.datetime.now().year
    week = (board.get("week") or {}).get("number") or 1
    return week, year


def get_event_ids(board: Dict[str, Any]) -> List[str]:
    events = board.get("events", []) or []
    return [e.get("id") for e in events if e.get("id")]


def get_summary(event_id: str) -> Dict[str, Any]:
    url = f"{BASE}/summary"
    r = requests.get(url, params={"event": event_id}, timeout=30)
    r.raise_for_status()
    return r.json()


# -----------------------------
# Parsing box score → QB/WR rows
# -----------------------------

def parse_qb_wr_from_summary(summary: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (qbs, wrs) lists of dicts from an ESPN game summary JSON."""
    qbs: List[Dict[str, Any]] = []
    wrs: List[Dict[str, Any]] = []

    # Build opponent mapping from header.competitions
    header = summary.get("header", {})
    competitions = header.get("competitions", []) or []
    comp = competitions[0] if competitions else {}
    competitors = comp.get("competitors", []) or []
    opp_by_teamid: Dict[str, str] = {}
    team_abbr_by_id: Dict[str, str] = {}
    if len(competitors) == 2:
        t0, t1 = competitors[0], competitors[1]
        a0 = t0.get("team", {}).get("abbreviation")
        a1 = t1.get("team", {}).get("abbreviation")
        id0 = t0.get("id")
        id1 = t1.get("id")
        if id0 and id1:
            opp_by_teamid[id0] = a1
            opp_by_teamid[id1] = a0
            team_abbr_by_id[id0] = a0
            team_abbr_by_id[id1] = a1

    # leaders may expose QBR values per athlete
    qbr_lookup: Dict[str, Optional[float]] = {}
    for side in summary.get("leaders", []) or []:
        for cat in side.get("leaders", []) or []:
            name = (cat.get("category") or "").lower()
            if "qbr" in name:
                for leader in cat.get("leaders", []) or []:
                    athlete = leader.get("athlete", {})
                    if athlete.get("id"):
                        qbr_lookup[athlete["id"]] = _safe_float(leader.get("value"))

    players_blocks = summary.get("boxscore", {}).get("players", []) or []

    for block in players_blocks:
        team = block.get("team", {})
        team_id = team.get("id")
        team_abbr = team.get("abbreviation") or team_abbr_by_id.get(team_id)
        opponent = opp_by_teamid.get(team_id)

        for group in block.get("statistics", []) or []:
            gname = (group.get("name") or "").lower()

            # ---------------- QB passing ----------------
            if gname == "passing":
                for ath in group.get("athletes", []) or []:
                    a = ath.get("athlete", {})
                    aid = a.get("id")
                    name = a.get("displayName")
                    headshot = (a.get("headshot") or {}).get("href")

                    stats_list = ath.get("stats", []) or []
                    stat_map = { (s.get("name") or "").lower(): s.get("value") for s in ath.get("athleteStats", []) or [] }

                    # Common sequence: CMP-ATT, YDS, AVG, TD, INT, SACKS, QBR, RTG
                    cmp_att = stats_list[0] if len(stats_list) > 0 else ""
                    yds     = _safe_float(stat_map.get("yds") or (stats_list[1] if len(stats_list) > 1 else None))
                    td      = _safe_float(stat_map.get("td")  or (stats_list[3] if len(stats_list) > 3 else None))
                    itc     = _safe_float(stat_map.get("int") or (stats_list[4] if len(stats_list) > 4 else None))
                    qbr     = _safe_float(stat_map.get("qbr") or (stats_list[6] if len(stats_list) > 6 else None) )
                    rtg     = _safe_float(stat_map.get("rtg") or (stats_list[7] if len(stats_list) > 7 else None) )

                    comp, att = None, None
                    if isinstance(cmp_att, str) and "-" in cmp_att:
                        parts = cmp_att.split("-")
                        if len(parts) == 2:
                            comp = _safe_float(parts[0])
                            att  = _safe_float(parts[1])

                    # Prefer leaders QBR if present
                    if aid and aid in qbr_lookup and qbr_lookup[aid] is not None:
                        qbr = qbr_lookup[aid]

                    # Skip non-throwers (att==0) unless rating present
                    if (att is None or att == 0) and not (rtg or qbr or yds):
                        continue

                    qbs.append({
                        "player": name,
                        "player_id": aid,
                        "team": team_abbr,
                        "opponent": opponent,
                        "completions": comp,
                        "attempts": att,
                        "pass_yards": yds,
                        "pass_tds": td,
                        "ints": itc,
                        "passer_rating": rtg,
                        "qbr": qbr,
                        "headshot": headshot,
                        "position": "QB",
                    })

            # --------------- WR receiving ---------------
            if gname == "receiving":
                for ath in group.get("athletes", []) or []:
                    a = ath.get("athlete", {})
                    aid = a.get("id")
                    name = a.get("displayName")
                    headshot = (a.get("headshot") or {}).get("href")

                    stats_list = ath.get("stats", []) or []
                    stat_map = { (s.get("name") or "").lower(): s.get("value") for s in ath.get("athleteStats", []) or [] }

                    rec = _safe_float(stat_map.get("rec") or (stats_list[0] if len(stats_list) > 0 else None))
                    yds = _safe_float(stat_map.get("yds") or (stats_list[1] if len(stats_list) > 1 else None))
                    avg = _safe_float(stat_map.get("avg") or (stats_list[2] if len(stats_list) > 2 else None))
                    td  = _safe_float(stat_map.get("td")  or (stats_list[3] if len(stats_list) > 3 else None))
                    lng = _safe_float(stat_map.get("lng") or (stats_list[4] if len(stats_list) > 4 else None))

                    # Skip if no receptions & no yards
                    if not rec and not yds:
                        continue

                    wrs.append({
                        "player": name,
                        "player_id": aid,
                        "team": team_abbr,
                        "opponent": opponent,
                        "receptions": rec,
                        "rec_yards": yds,
                        "rec_tds": td,
                        "ypr": avg,
                        "long": lng,
                        "headshot": headshot,
                        "position": "WR",
                    })

    return qbs, wrs


def dedupe_best_attempts(rows: List[Dict[str, Any]], key_fields: Tuple[str, ...]) -> List[Dict[str, Any]]:
    best: Dict[Tuple[Any, ...], Tuple[Tuple[float, float], Dict[str, Any]]] = {}
    for r in rows:
        k = tuple(r.get(f) for f in key_fields)
        score = (
            float(r.get("attempts") or 0 if "attempts" in r else r.get("receptions") or 0),
            float(r.get("pass_yards") or r.get("rec_yards") or 0),
        )
        if k not in best or score > best[k][0]:
            best[k] = (score, r)
    return [v[1] for v in best.values()]


# -----------------------------
# Headshots cache
# -----------------------------

def cache_headshot(url: Optional[str], dest: Path) -> Optional[Path]:
    if not url:
        return None
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGB")
        ensure_dir(dest.parent)
        img.save(dest, format="PNG")
        return dest
    except Exception:
        return None


# -----------------------------
# Composites & Trends
# -----------------------------

def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def zscore(series: pd.Series) -> pd.Series:
    s = series.astype(float)
    mu, sigma = s.mean(), s.std(ddof=0)
    if sigma == 0 or np.isnan(sigma):
        return pd.Series([0.0] * len(s), index=s.index)
    return (s - mu) / sigma


def composite_qb(df: pd.DataFrame) -> pd.Series:
    # df has columns: qbr, passer_rating, pass_tds, ints, attempts
    td_int_pa = (df["pass_tds"].fillna(0) - df["ints"].fillna(0)) / df["attempts"].replace(0, np.nan)
    td_int_pa = td_int_pa.fillna(0)
    comp = 0.45 * zscore(df["qbr"].fillna(0)) + \
           0.35 * zscore(df["passer_rating"].fillna(0)) + \
           0.20 * zscore(td_int_pa)
    # Map to 0..100 via percentile-ish CDF
    pct = (comp.rank(pct=True) * 100).round(1)
    return pct


def composite_wr(df: pd.DataFrame) -> pd.Series:
    comp = 0.60 * zscore(df["rec_yards"].fillna(0)) + \
           0.25 * zscore(df["receptions"].fillna(0)) + \
           0.15 * zscore(df["rec_tds"].fillna(0))
    pct = (comp.rank(pct=True) * 100).round(1)
    return pct


def update_history_and_trend(outdir: Path, week_key: str, faves_df: pd.DataFrame) -> pd.DataFrame:
    """Maintain a history CSV of composites to compute trend arrows.
    Returns faves_df with `trend` column added.
    """
    hist_path = outdir / "history_composites.csv"
    key_cols = ["player_id", "player", "position"]

    # Current week snapshot to append
    snap = faves_df[key_cols + ["composite"]].copy()
    snap["week_key"] = week_key

    if hist_path.exists():
        hist = pd.read_csv(hist_path)
        hist = pd.concat([hist, snap], ignore_index=True)
    else:
        hist = snap

    # Keep only last ~12 weeks per player to control size
    hist["week_order"] = hist.groupby("player_id")["week_key"].rank(method="first")
    # Not precise ordering, but sufficient within a season when appended in order
    hist.to_csv(hist_path, index=False)

    # Compute trend for faves: compare latest vs mean of previous up to 3 weeks
    trends = []
    for _, row in faves_df.iterrows():
        pid = row["player_id"]
        subset = hist[hist["player_id"] == pid].sort_values("week_key")
        latest = row["composite"]
        prev = subset[subset["week_key"] < week_key]["composite"].tail(3)
        if prev.empty:
            trends.append("→")
        else:
            delta = latest - prev.mean()
            if delta >= 8:
                trends.append("↑")
            elif delta <= -8:
                trends.append("↓")
            else:
                trends.append("→")
    faves_df["trend"] = trends
    return faves_df


# -----------------------------
# Geo breakdown
# -----------------------------

def load_hometowns(hometowns_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(hometowns_csv)
    # Try common shapes: either hometown dict-string or explicit city/state columns
    if "hometown" in df.columns and df["hometown"].astype(str).str.startswith("{").any():
        # Attempt to parse JSON-like dict
        def parse_ht(x: Any) -> Tuple[str, str]:
            try:
                d = json.loads(str(x).replace("'", '"'))
                return (d.get("city") or "", d.get("state") or "")
            except Exception:
                return ("", "")
        cs = df["hometown"].apply(parse_ht)
        df["city"] = [a for a, _ in cs]
        df["state"] = [b for _, b in cs]
    # Normalize
    df["city"] = df.get("city", pd.Series([None]*len(df))).fillna("").astype(str).str.strip().str.title()
    df["state"] = df.get("state", pd.Series([None]*len(df))).fillna("").astype(str).str.strip().str.upper()
    return df


def city_counts_chart(df: pd.DataFrame, out_png: Path, miami_label: str = "Miami, FL", top_n: int = 10) -> Tuple[pd.DataFrame, Optional[str]]:
    if df.empty or "city" not in df.columns:
        return pd.DataFrame(), None

    df["city_state"] = (df["city"].fillna("") + ", " + df["state"].fillna("")).str.strip(", ")
    grp = (
        df.assign(player_id=df.get("player_id") or df.get("player") or np.arange(len(df)))
          .groupby("city_state", as_index=False)["player_id"].nunique()
          .rename(columns={"player_id": "players"})
          .sort_values("players", ascending=False)
    )

    top = grp.head(top_n).copy()

    # Plot
    ensure_dir(out_png.parent)
    plt.figure(figsize=(8, 5))
    y = np.arange(len(top))
    labels = list(top["city_state"])
    values = list(top["players"])

    # Miami highlighting
    miami_idx = None
    for i, lbl in enumerate(labels):
        if lbl.lower() == miami_label.lower():
            miami_idx = i
            break

    bars = plt.barh(y, values)
    if miami_idx is not None:
        bars[miami_idx].set_edgecolor("black")
        bars[miami_idx].set_linewidth(2.0)
    plt.yticks(y, labels)
    plt.xlabel("Players")
    plt.title("Top Cities by NFL Players (Season)")
    plt.gca().invert_yaxis()
    plt.tight_layout()
    plt.savefig(out_png, dpi=160)
    plt.close()

    callout = None
    if miami_idx is None:
        # Compute Miami summary if exists outside top list
        miami_row = grp[grp["city_state"].str.lower() == miami_label.lower()]
        if not miami_row.empty:
            callout = f"Miami (not in top {top_n}): {int(miami_row.iloc[0]['players'])} players active this season."
    return top, callout

def supabase_upsert(rows):
    import requests, sys, os
    url_base = SUPABASE_URL
    service_key = SUPABASE_SERVICE_ROLE
    table = SUPABASE_TABLE

    if not url_base or not service_key:
        print("Skip upload: SUPABASE_URL or SERVICE_ROLE missing.", file=sys.stderr)
        return

    endpoint = f"{url_base}/rest/v1/{table}"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    params = {"on_conflict": "event_id,team_id,player_id"}

    CHUNK = 500
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i:i+CHUNK]
        r = requests.post(endpoint, headers=headers, params=params, json=chunk, timeout=60)
        if not r.ok:
            print(f"Supabase upsert failed [{r.status_code}]: {r.text[:300]}", file=sys.stderr)
            r.raise_for_status()
        else:
            print(f"Upserted {len(chunk)} rows ({i+len(chunk)}/{len(rows)})", file=sys.stderr)



# -----------------------------
# Markdown renderers
# -----------------------------

def md_table(df: pd.DataFrame, cols: List[str], header_map: Dict[str, str] | None = None) -> str:
    header_map = header_map or {}
    headers = [header_map.get(c, c) for c in cols]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        row = [r.get(c, "") for c in cols]
        row = ["" if (pd.isna(x) or x is None) else (str(int(x)) if isinstance(x, (float, int)) and float(x).is_integer() else str(x)) for x in row]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def make_report_index_notion(outdir: Path, week: int, year: int) -> None:
    parts = []
    parts.append(f"# Weekly NFL Performance — Week {week}, {year}\n")
    parts.append("\n## Header — Favorite QB→WR Clip\n")
    parts.append("(Insert header_still.png and add caption/link here)\n\n")

    parts.append("## My Faves\n")
    parts.append((outdir/"faves_table.md").read_text(encoding="utf-8"))
    parts.append("\n\n")

    parts.append("## Top QBs (QBR vs Passer Rating)\n")
    parts.append((outdir/"top_qbs.md").read_text(encoding="utf-8"))
    parts.append("\n\n")

    parts.append("## Top WRs\n")
    parts.append((outdir/"top_wrs.md").read_text(encoding="utf-8"))
    parts.append("\n\n")

    parts.append("## Geo Breakdown — Top Cities (Season)\n")
    parts.append("(Insert geo_bar.png here)\n\n")
    gcp = outdir/"geo_callout.md"
    if gcp.exists():
        parts.append(gcp.read_text(encoding="utf-8"))

    idx_path = outdir/"report_notion.md"
    idx_path.write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote {idx_path}\n")
    print("➡ To publish: In Notion, go to File → Import → Markdown & CSV, and select the entire output folder. This will bring in the page and all images.")



# -----------------------------
# Main
# -----------------------------

def main():
    ap = argparse.ArgumentParser(description="NFL Weekly Report v1 (NotebookLM bundle)")
    ap.add_argument("--favorites", type=str, default="", help="Comma-separated player names to track across positions (exact or close match)")
    ap.add_argument("--outdir", type=str, default="weekly_report", help="Output directory for the weekly bundle")
    ap.add_argument("--miami", type=str, default="Miami, FL", help="City, ST label to highlight in geo chart")
    ap.add_argument("--hometowns_csv", type=str, default="", help="CSV with player hometowns (columns 'city','state' or a JSON-like 'hometown')")
    ap.add_argument("--week", type=int, default=None, help="Optional explicit NFL week override for scoreboard query (may not always be honored by ESPN)")
    ap.add_argument("--year", type=int, default=None, help="Optional season year override for scoreboard query (may not always be honored by ESPN)")
    ap.add_argument("--dump-one", action="store_true", help="Dump the first summary JSON for inspection")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    ensure_dir(outdir)

    # Placeholder header files (you can overwrite each week)
    (outdir / "header_caption.txt").write_text("Add a one-line note about the QB→WR play here.", encoding="utf-8")
    (outdir / "header_link.txt").write_text("https://", encoding="utf-8")
    if not (outdir / "header_still.png").exists():
        # create a tiny placeholder image
        img = Image.new("RGB", (800, 200), color=(240, 240, 240))
        img.save(outdir / "header_still.png", format="PNG")

    # Scoreboard (optional params — ESPN may ignore some)
    params = {}
    if args.week is not None:
        params["week"] = args.week
    if args.year is not None:
        params["year"] = args.year
    board = get_scoreboard(params=params)
    week, year = get_week_info(board)
    event_ids = get_event_ids(board)
    if not event_ids:
        print("No events found on scoreboard; exiting.")
        sys.exit(0)

    all_qbs: List[Dict[str, Any]] = []
    all_wrs: List[Dict[str, Any]] = []

    dumped = False
    for eid in event_ids:
        summary = get_summary(eid)
        if args.dump_one and not dumped:
            (outdir / "sample_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            print(f"Wrote {outdir / 'sample_summary.json'} for debugging.")
            dumped = True
        qbs, wrs = parse_qb_wr_from_summary(summary)
        all_qbs.extend(qbs)
        all_wrs.extend(wrs)

    # Dedupe
    all_qbs = dedupe_best_attempts(all_qbs, ("player_id", "team", "opponent"))
    all_wrs = dedupe_best_attempts(all_wrs, ("player_id", "team", "opponent"))

    # Persist raw tables
    qbs_df = pd.DataFrame(all_qbs)
    wrs_df = pd.DataFrame(all_wrs)

    qbs_csv = outdir / f"top_qbs_week_{week}_{year}.csv"
    wrs_csv = outdir / f"top_wrs_week_{week}_{year}.csv"
    qbs_df.to_csv(qbs_csv, index=False)
    wrs_df.to_csv(wrs_csv, index=False)
    print(f"Wrote {qbs_csv} ({len(qbs_df)} rows)")
    print(f"Wrote {wrs_csv} ({len(wrs_df)} rows)")

    # Leaderboards (Top 10)
    qbs_ranked = qbs_df.copy()
    qbs_ranked["qbr"] = pd.to_numeric(qbs_ranked["qbr"], errors="coerce")
    qbs_ranked["passer_rating"] = pd.to_numeric(qbs_ranked["passer_rating"], errors="coerce")
    qbs_ranked["pass_yards"] = pd.to_numeric(qbs_ranked["pass_yards"], errors="coerce")
    qbs_ranked["pass_tds"] = pd.to_numeric(qbs_ranked["pass_tds"], errors="coerce")
    qbs_ranked["ints"] = pd.to_numeric(qbs_ranked["ints"], errors="coerce")
    qbs_ranked = qbs_ranked.sort_values(["qbr", "passer_rating"], ascending=False).head(10)

    qbs_md = md_table(qbs_ranked[["player","team","qbr","passer_rating","pass_yards","pass_tds","ints"]],
                      ["player","team","qbr","passer_rating","pass_yards","pass_tds","ints"],
                      {"qbr": "QBR", "passer_rating": "Passer Rating", "pass_yards": "Yds", "pass_tds": "TD", "ints": "INT"})
    (outdir / "top_qbs.md").write_text(qbs_md, encoding="utf-8")

    wrs_ranked = wrs_df.copy()
    for c in ["receptions","rec_yards","rec_tds","ypr"]:
        wrs_ranked[c] = pd.to_numeric(wrs_ranked[c], errors="coerce")
    wrs_ranked = wrs_ranked.sort_values(["rec_yards","receptions","rec_tds"], ascending=False).head(10)

    wrs_md = md_table(wrs_ranked[["player","team","receptions","rec_yards","rec_tds","ypr"]],
                      ["player","team","receptions","rec_yards","rec_tds","ypr"],
                      {"receptions": "Rec", "rec_yards": "Yds", "rec_tds": "TD", "ypr": "YPR"})
    (outdir / "top_wrs.md").write_text(wrs_md, encoding="utf-8")

    # Favorites table (across QB/WR):
    fav_names = [s.strip().lower() for s in args.favorites.split(",") if s.strip()]
    if fav_names:
        # Merge QB+WR frames
        both = pd.concat([
            qbs_df[["player","player_id","team","position","qbr","passer_rating","pass_yards","pass_tds","ints","headshot"]].copy(),
            wrs_df[["player","player_id","team","position","receptions","rec_yards","rec_tds","ypr","headshot"]].copy(),
        ], ignore_index=True)

        # Loosen matching: case-insensitive contains on name tokens
        def is_fav(name: str) -> bool:
            nm = (name or "").lower()
            return any(f in nm for f in fav_names)
        fav_df = both[both["player"].apply(is_fav)].copy()

        # Compute composites per position
        qb_mask = fav_df["position"] == "QB"
        wr_mask = fav_df["position"] == "WR"
        if qb_mask.any():
            fav_df.loc[qb_mask, "composite"] = composite_qb(fav_df[qb_mask].assign(
                attempts=pd.to_numeric(fav_df[qb_mask]["player_id"].map(
                    dict(zip(qbs_df["player_id"], pd.to_numeric(qbs_df["attempts"], errors="coerce")))
                ), errors="coerce").fillna(0),
                pass_tds=pd.to_numeric(fav_df[qb_mask]["player_id"].map(
                    dict(zip(qbs_df["player_id"], pd.to_numeric(qbs_df["pass_tds"], errors="coerce")))
                ), errors="coerce"),
                ints=pd.to_numeric(fav_df[qb_mask]["player_id"].map(
                    dict(zip(qbs_df["player_id"], pd.to_numeric(qbs_df["ints"], errors="coerce")))
                ), errors="coerce"),
            ).rename(columns={})
        if wr_mask.any():
            fav_df.loc[wr_mask, "composite"] = composite_wr(fav_df[wr_mask].rename(columns={}))

        fav_df["composite"] = pd.to_numeric(fav_df["composite"], errors="coerce").round(1)

        # Headshots cache
        hs_dir = outdir / "faves_headshots"
        ensure_dir(hs_dir)
        fav_df["headshot_path"] = None
        for i, row in fav_df.iterrows():
            pid = row.get("player_id") or f"name_{re.sub('[^a-z0-9]+','_', (row.get('player') or '').lower())}"
            dest = hs_dir / f"{pid}.png"
            if not dest.exists():
                cache_headshot(row.get("headshot"), dest)
            if dest.exists():
                fav_df.at[i, "headshot_path"] = dest.name

        # Update history & trend
        week_key = f"{year}-W{week:02d}"
        fav_df = update_history_and_trend(outdir, week_key, fav_df)

        # Build display columns per position
        display_rows = []
        for _, r in fav_df.iterrows():
            if r["position"] == "QB":
                week_perf = f"{int(r.get('pass_yards') or 0)}y / {int(r.get('pass_tds') or 0)}TD / {int(r.get('ints') or 0)}INT | QBR {r.get('qbr') or ''} | PR {r.get('passer_rating') or ''}"
            else:
                week_perf = f"{int(r.get('receptions') or 0)}rec / {int(r.get('rec_yards') or 0)}y / {int(r.get('rec_tds') or 0)}TD | YPR {r.get('ypr') or ''}"
            display_rows.append({
                "headshot": f"![img](faves_headshots/{r.get('headshot_path')})" if r.get("headshot_path") else "",
                "name": r.get("player"),
                "pos": r.get("position"),
                "team": r.get("team"),
                "week_performance": week_perf,
                "composite": r.get("composite"),
                "trend": r.get("trend", "→"),
            })
        faves_display = pd.DataFrame(display_rows)
        faves_cols = ["headshot","name","pos","team","week_performance","composite","trend"]
        (outdir / "faves_week.csv").write_text(faves_display.to_csv(index=False), encoding="utf-8")

        faves_md = md_table(faves_display, faves_cols,
                            {"headshot":"","name":"Name","pos":"Pos","team":"Team","week_performance":"Week Performance","composite":"Score","trend":"Trend"})
        (outdir / "faves_table.md").write_text(faves_md, encoding="utf-8")
    else:
        # Write empty faves_table.md so index generator succeeds
        (outdir / "faves_table.md").write_text("*(Add favorites via --favorites to populate this section.)*", encoding="utf-8")

    # Geo breakdown (optional)
    if args.hometowns_csv:
        try:
            htdf = load_hometowns(Path(args.hometowns_csv))
            top_cities, callout = city_counts_chart(htdf, outdir / "geo_bar.png", args.miami, top_n=10)
            top_cities.to_csv(outdir / "city_counts.csv", index=False)
            if callout:
                (outdir / "geo_callout.md").write_text(callout, encoding="utf-8")
            else:
                (outdir / "geo_callout.md").write_text("", encoding="utf-8")
        except Exception as e:
            print(f"Geo breakdown skipped due to error: {e}")
            (outdir / "geo_callout.md").write_text("", encoding="utf-8")
            # also create a tiny blank image placeholder
            img = Image.new("RGB", (800, 200), color=(255, 255, 255))
            img.save(outdir / "geo_bar.png", format="PNG")
    else:
        # No hometowns provided; create placeholder
        (outdir / "geo_callout.md").write_text("*(Geo breakdown requires --hometowns_csv.)*", encoding="utf-8")
        img = Image.new("RGB", (800, 200), color=(255, 255, 255))
        img.save(outdir / "geo_bar.png", format="PNG")

    # Build top tables markdown files were already written. Ensure they exist.
    if not (outdir / "top_qbs.md").exists():
        (outdir / "top_qbs.md").write_text("(No QB data)", encoding="utf-8")
    if not (outdir / "top_wrs.md").exists():
        (outdir / "top_wrs.md").write_text("(No WR data)", encoding="utf-8")

    # Create master index
    make_report_index_notion(outdir, week, year)

if __name__ == "__main__":
    main()


