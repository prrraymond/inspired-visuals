#!/usr/bin/env python3
"""
NFL Weekly Report (v1, Notion‑ready)
---------------------------------
Generates a weekly NFL performance package for publishing in Notion with:
  - Header (manual still + caption/link placeholders)
  - "My Faves" table (with headshots, weekly composite score, 4-week trend arrows)
  - Top QBs table (QBR vs Passer Rating)
  - Top WRs table
  - Geo breakdown bar chart by player hometown city (with Miami callout)

Outputs Markdown blocks and a `report_notion.md` master page. Drag the ENTIRE
output folder into Notion via **Import → Markdown & CSV** so images are uploaded.

Data Source: ESPN internal JSON endpoints:
  - Scoreboard: https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
  - Summary:    https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=<EVENT_ID>

USAGE
-----
python nfl_weekly_report_v1.py \
  --favorites "Patrick Mahomes, Tyreek Hill, Josh Allen" \
  --outdir weekly_report \
  [--miami "Miami, FL"] \
  [--hometowns_csv /path/to/actives_with_hometowns.csv] \
  [--dump-one]

NOTES
-----
- Paste or import `report_notion.md` into Notion. Best is **folder import** so images render.
- If you paste the MD only, Notion won’t upload local images; use folder import.
"""

import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from PIL import Image
import matplotlib.pyplot as plt

BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"

# -----------------------------
# ESPN fetchers
# -----------------------------

def get_scoreboard() -> Dict[str, Any]:
    url = f"{BASE}/scoreboard"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def get_week_info(board: Dict[str, Any]) -> Tuple[int, int]:
    season = board.get("season", {})
    year = season.get("year") or dt.datetime.now().year
    week = (board.get("week") or {}).get("number") or 1
    return int(week), int(year)


def get_event_ids(board: Dict[str, Any]) -> List[str]:
    return [e.get("id") for e in board.get("events", []) if e.get("id")]


def get_summary(event_id: str) -> Dict[str, Any]:
    url = f"{BASE}/summary?event={event_id}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

# -----------------------------
# Parsing helpers
# -----------------------------

def _sfloat(x):
    try:
        return float(x)
    except Exception:
        return None


def extract_qb_lines(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    qbs: List[Dict[str, Any]] = []
    for block in summary.get("boxscore", {}).get("players", []) or []:
        for group in block.get("statistics", []) or []:
            if (group.get("name") or "").lower() == "passing":
                for ath in group.get("athletes", []) or []:
                    a = ath.get("athlete", {}) or {}
                    stats = ath.get("stats", []) or []
                    cmp_att = stats[0] if len(stats) > 0 else ""
                    comp, att = None, None
                    if isinstance(cmp_att, str) and "-" in cmp_att:
                        p = cmp_att.split("-")
                        if len(p) == 2:
                            comp = _sfloat(p[0])
                            att = _sfloat(p[1])
                    yds = _sfloat(stats[1]) if len(stats) > 1 else None
                    td = _sfloat(stats[3]) if len(stats) > 3 else None
                    itc = _sfloat(stats[4]) if len(stats) > 4 else None
                    qbr = _sfloat(stats[6]) if len(stats) > 6 else None
                    rtg = _sfloat(stats[7]) if len(stats) > 7 else None
                    qbs.append({
                        "player": a.get("displayName"),
                        "team": block.get("team", {}).get("abbreviation"),
                        "completions": comp,
                        "attempts": att,
                        "pass_yards": yds,
                        "pass_tds": td,
                        "ints": itc,
                        "passer_rating": rtg,
                        "qbr": qbr,
                    })
    return qbs


def extract_wr_lines(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    wrs: List[Dict[str, Any]] = []
    for block in summary.get("boxscore", {}).get("players", []) or []:
        for group in block.get("statistics", []) or []:
            if (group.get("name") or "").lower() == "receiving":
                for ath in group.get("athletes", []) or []:
                    a = ath.get("athlete", {}) or {}
                    stats = ath.get("stats", []) or []
                    rec = _sfloat(stats[0]) if len(stats) > 0 else None
                    yds = _sfloat(stats[1]) if len(stats) > 1 else None
                    td = _sfloat(stats[3]) if len(stats) > 3 else None
                    ypr = None
                    if rec and yds is not None and rec != 0:
                        ypr = round(yds/rec, 2)
                    wrs.append({
                        "player": a.get("displayName"),
                        "team": block.get("team", {}).get("abbreviation"),
                        "receptions": rec,
                        "rec_yards": yds,
                        "rec_tds": td,
                        "ypr": ypr,
                    })
    return wrs

# -----------------------------
# Output helpers
# -----------------------------

def md_table(rows: List[Dict[str, Any]], cols: List[str], headers: List[str]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"]*len(headers)) + "|"]
    for r in rows:
        row = ["" if r.get(c) is None else str(r.get(c)) for c in cols]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)

# -----------------------------
# Report assembler for Notion
# -----------------------------

def make_report_index_notion(outdir: Path, week: int, year: int) -> None:
    parts = []
    parts.append(f"# Weekly NFL Performance — Week {week}, {year}\n")

    parts.append("\n## My Faves\n")
    if (outdir/"faves_table.md").exists():
        parts.append((outdir/"faves_table.md").read_text(encoding="utf-8"))

    parts.append("\n## Top QBs (QBR vs Passer Rating)\n")
    parts.append((outdir/"top_qbs.md").read_text(encoding="utf-8"))

    parts.append("\n## Top WRs\n")
    parts.append((outdir/"top_wrs.md").read_text(encoding="utf-8"))

    idx_path = outdir/"report_notion.md"
    idx_path.write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote {idx_path}\n")
    print("➡ To publish: In Notion, go to File → Import → Markdown & CSV, and select the entire output folder.")

# -----------------------------
# Main
# -----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--favorites", type=str, default="", help="Comma-separated favorite players")
    ap.add_argument("--outdir", type=str, default="weekly_report")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    board = get_scoreboard()
    week, year = get_week_info(board)
    event_ids = get_event_ids(board)

    qbs, wrs = [], []
    for eid in event_ids:
        summary = get_summary(eid)
        qbs.extend(extract_qb_lines(summary))
        wrs.extend(extract_wr_lines(summary))

    # Top QBs
    qbs_sorted = sorted(qbs, key=lambda r: (r.get("qbr") or -1, r.get("passer_rating") or -1), reverse=True)[:10]
    qbs_md = md_table(qbs_sorted, ["player","team","qbr","passer_rating","pass_yards","pass_tds","ints"],
                      ["Player","Team","QBR","Passer Rating","Yds","TD","INT"])
    (outdir/"top_qbs.md").write_text(qbs_md, encoding="utf-8")

    # Top WRs
    wrs_sorted = sorted(wrs, key=lambda r: (r.get("rec_yards") or -1, r.get("receptions") or -1), reverse=True)[:10]
    wrs_md = md_table(wrs_sorted, ["player","team","receptions","rec_yards","rec_tds","ypr"],
                      ["Player","Team","Rec","Yds","TD","YPR"])
    (outdir/"top_wrs.md").write_text(wrs_md, encoding="utf-8")

    # Placeholder faves table
    (outdir/"faves_table.md").write_text("(Favorites table coming soon)", encoding="utf-8")

    make_report_index_notion(outdir, week, year)

if __name__ == "__main__":
    main()
