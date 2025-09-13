#!/usr/bin/env python3
"""
NFL Weekly Report (v1, Notion-ready — FULL)
------------------------------------------
Generates a weekly NFL performance package for **Notion** with:
  - Header placeholders (still + caption/link)
  - **My Faves** table (headshots, weekly composite score, 4-week trend arrows)
  - **Top QBs** table (QBR vs Passer Rating)
  - **Top WRs** table
  - **Geo breakdown** bar chart by player hometown city (with Miami callout)
  - Master page `report_notion.md`

**Import** the entire output folder into Notion via **File → Import → Markdown & CSV** so images upload.

Data Source (unofficial ESPN JSON):
  - Scoreboard: https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
  - Summary:    https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=<EVENT_ID>

USAGE
-----
pip install requests pandas numpy pillow matplotlib

python nfl_weekly_report_v1.py \
  --favorites "Patrick Mahomes, Tyreek Hill, Josh Allen" \
  --outdir weekly_report \
  --miami "Miami, FL" \
  --hometowns_csv /path/to/actives_with_hometowns.csv \
  --dump-one
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
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
# Helpers
# -----------------------------


def _sfloat(x):
    try:
        return float(x)
    except Exception:
        return None




def zscore(x: pd.Series) -> pd.Series:
    if len(x) < 2 or x.std(ddof=0) == 0:
        return pd.Series([0]*len(x), index=x.index)
    return (x - x.mean()) / x.std(ddof=0)

# -----------------------------
# Parsing helpers
# -----------------------------

def leaders_qbr_lookup(summary: Dict[str, Any]) -> Dict[str, float]:
    out = {}
    for side in summary.get("leaders", []) or []:
        for cat in side.get("leaders", []) or []:
            name = (cat.get("category") or "").lower()
            if "qbr" in name:
                for leader in cat.get("leaders", []) or []:
                    a = leader.get("athlete", {})
                    out[a.get("id")] = _sfloat(leader.get("value"))
    return out


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
                        "headshot": (a.get("headshot") or {}).get("href"),
                        "player_id": a.get("id"),
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
                        "headshot": (a.get("headshot") or {}).get("href"),
                        "player_id": a.get("id"),
                    })
    return wrs


def dedupe(rows: List[Dict[str, Any]], key_fields: Tuple[str, ...]) -> List[Dict[str, Any]]:
    best: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for r in rows:
        k = tuple(r.get(f) for f in key_fields)
        if k not in best:
            best[k] = r
        else:
            a = best[k]
            a_score = ((a.get("attempts") or 0), (a.get("pass_yards") or 0), (a.get("receptions") or 0), (a.get("rec_yards") or 0))
            b_score = ((r.get("attempts") or 0), (r.get("pass_yards") or 0), (r.get("receptions") or 0), (r.get("rec_yards") or 0))
            if b_score > a_score:
                best[k] = r
    return list(best.values())

# -----------------------------
# Output helpers
# -----------------------------

def md_table(rows: List[Dict[str, Any]], cols: List[str], headers: List[str]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"]*len(headers)) + "|"]
    for r in rows:
        row = ["" if r.get(c) is None else str(r.get(c)) for c in cols]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def write_csv(path: Path, rows: List[Dict[str, Any]], cols: List[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c) for c in cols})
    print(f"Wrote {path} ({len(rows)} rows)")

# -----------------------------
# Favorites: composites & trends
# -----------------------------

def zscore_series(x: pd.Series) -> pd.Series:
    x = pd.to_numeric(x, errors="coerce").fillna(0)
    if len(x) < 2 or x.std(ddof=0) == 0:
        return pd.Series([0]*len(x), index=x.index)
    return (x - x.mean())/x.std(ddof=0)


def compute_composites(faves_df: pd.DataFrame) -> pd.DataFrame:
    df = faves_df.copy()
    is_qb = df["position"].eq("QB")
    is_wr = df["position"].eq("WR")
    # QB: 45% QBR, 35% PasserRating, 20% (TD-INT)
    qb = df[is_qb].copy()
    if not qb.empty:
        qb["_z_qbr"] = zscore_series(qb["qbr"])
        qb["_z_pr"] = zscore_series(qb["passer_rating"])
        qb["_z_tdint"] = zscore_series(pd.to_numeric(qb["pass_tds"], errors="coerce").fillna(0) - pd.to_numeric(qb["ints"], errors="coerce").fillna(0))
        df.loc[is_qb, "composite_raw"] = 45*qb._z_qbr + 35*qb._z_pr + 20*qb._z_tdint
    # WR: 60% yards, 25% receptions, 15% TDs
    wr = df[is_wr].copy()
    if not wr.empty:
        wr["_z_yds"] = zscore_series(wr["rec_yards"])
        wr["_z_rec"] = zscore_series(wr["receptions"])
        wr["_z_td"] = zscore_series(wr["rec_tds"])
        df.loc[is_wr, "composite_raw"] = 60*wr._z_yds + 25*wr._z_rec + 15*wr._z_td
    # Scale within faves to 0..100
    c = pd.to_numeric(df["composite_raw"], errors="coerce").fillna(0)
    if c.max() != c.min():
        df["composite"] = (c - c.min())/(c.max()-c.min())*100
    else:
        df["composite"] = 50
    return df


def update_trends(outdir: Path, week: int, year: int, df: pd.DataFrame) -> pd.DataFrame:
    hist_path = outdir/"history_composites.csv"
    cols = ["player_id","player","position","week","year","composite"]
    if hist_path.exists():
        hist = pd.read_csv(hist_path)
    else:
        hist = pd.DataFrame(columns=cols)
    cur = df[cols].copy()
    trends = []
    for _, r in cur.iterrows():
        prev = hist[hist.player_id == r["player_id"]].tail(3)
        if prev.empty:
            delta = 0
        else:
            delta = r["composite"] - prev["composite"].mean()
        arrow = "↑" if delta >= 8 else ("↓" if delta <= -8 else "→")
        trends.append(arrow)
    df["trend"] = trends
    hist = pd.concat([hist, cur], ignore_index=True)
    hist.to_csv(hist_path, index=False)
    return df


def download_headshot(url: Optional[str], dest: Path) -> Optional[Path]:
    if not url:
        return None
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest)
        return dest
    except Exception:
        return None


def write_faves_md(faves_df: pd.DataFrame, head_dir: Path, out_md: Path) -> None:
    lines = ["|  | Name | Pos | Team | Week Performance | Score | Trend |",
             "|---|---|---:|---:|---|---:|---:|"]
    for _, r in faves_df.iterrows():
        img_md = ""
        if pd.notna(r.get("headshot_file")) and r.get("headshot_file"):
            rel = head_dir.name + "/" + Path(r["headshot_file"]).name
            img_md = f"![]({rel})"
        if r["position"] == "QB":
            week_line = f"{int(r.get('pass_yards') or 0)}y | {int(r.get('pass_tds') or 0)}TD | {int(r.get('ints') or 0)}INT | QBR {r.get('qbr') or ''} | PR {r.get('passer_rating') or ''}"
        else:
            week_line = f"{int(r.get('receptions') or 0)}rec | {int(r.get('rec_yards') or 0)}y | {int(r.get('rec_tds') or 0)}TD | YPR {r.get('ypr') or ''}"
        lines.append(
            f"| {img_md} | {r.get('player') or ''} | {r.get('position') or ''} | {r.get('team') or ''} | {week_line} | {round(float(r.get('composite') or 0),1)} | {r.get('trend') or '→'} |"
        )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_md}")

# -----------------------------
# Geo breakdown
# -----------------------------

def parse_hometowns(hometowns_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(hometowns_csv)
    if {"city","state"}.issubset(df.columns):
        pass
    elif "hometown" in df.columns:
        cities, states = [], []
        for v in df["hometown"].astype(str):
            m_city = re.search(r"'city':\s*'([^']+)'", v)
            m_state = re.search(r"'state':\s*'([^']+)'", v)
            cities.append(m_city.group(1) if m_city else None)
            states.append(m_state.group(1) if m_state else None)
        df["city"], df["state"] = cities, states
    else:
        raise ValueError("Expected columns city,state or a 'hometown' column")
    grp = df.groupby(["city","state"], dropna=True).size().reset_index(name="players")
    return grp


def make_geo_bar(top_cities: pd.DataFrame, out_png: Path, miami_label: str) -> None:
    top = top_cities.sort_values("players", ascending=False).head(10)
    labels = top.apply(lambda r: f"{r['city']}, {r['state']}", axis=1)
    vals = top["players"].values
    plt.figure(figsize=(9,5))
    bars = plt.barh(range(len(vals)), vals)
    plt.yticks(range(len(vals)), labels)
    plt.gca().invert_yaxis()
    plt.xlabel("Players (season)")
    plt.title("Top 10 Cities with NFL Players")
    # Simple highlight via edge for Miami
    try:
        idx = labels.tolist().index(miami_label)
        bars[idx].set_linewidth(2)
        bars[idx].set_edgecolor("black")
    except ValueError:
        pass
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout(); plt.savefig(out_png, dpi=150); plt.close()
    print(f"Wrote {out_png}")

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


    # Favorites (hard-coded)
    favorites = [
        "lamar jackson",
        "josh allen",
        "joe burrow",
        "aaron rodgers",
        "jamar chase",
        "amon-ra st.brown",
        "saquan barkley",
        "ashton jeanty"
    ]


    fav_rows = []
    for r in qbs + wrs:
        if r.get("player") and any(f in r.get("player","" ).lower() for f in favorites):
            fav_rows.append(r)
    if fav_rows:
        df = pd.DataFrame(fav_rows)
        df["position"] = df.apply(lambda r: "QB" if "qbr" in r and pd.notna(r["qbr"]) else "WR", axis=1)
        # Composite scores
        qb_mask = df["position"] == "QB"
        wr_mask = df["position"] == "WR"
        df.loc[qb_mask, "composite"] = 0.45*zscore(df.loc[qb_mask,"qbr"]) + 0.35*zscore(df.loc[qb_mask,"passer_rating"]) + 0.20*zscore(df.loc[qb_mask,"pass_tds"] - df.loc[qb_mask,"ints"])
        df.loc[wr_mask, "composite"] = 0.60*zscore(df.loc[wr_mask,"rec_yards"]) + 0.25*zscore(df.loc[wr_mask,"receptions"]) + 0.15*zscore(df.loc[wr_mask,"rec_tds"])
        df["composite_scaled"] = (df["composite"] - df["composite"].min())/(df["composite"].max()-df["composite"].min()+1e-9)*100
        df["trend"] = "→"


    # Download headshots
        head_dir = outdir/"faves_headshots"
        head_dir.mkdir(parents=True, exist_ok=True)
        img_tags = []
        for _, row in df.iterrows():
            pid = row.get("player_id") or re.sub(r"[^a-z0-9]+","_", row.get("player","" ).lower())
            dest = head_dir/f"{pid}.png"
            if row.get("headshot") and not dest.exists():
                try:
                    r = requests.get(row["headshot"], timeout=15)
                    r.raise_for_status()
                    with open(dest,"wb") as f:
                        f.write(r.content)
                except Exception:
                    pass
            if dest.exists():
                img_tags.append(f"![](faves_headshots/{dest.name})")
            else:
                img_tags.append("")
        df["img"] = img_tags


        lines = ["| | Player | Pos | Team | Week Performance | Score | Trend |",
            "|---|---|---|---|---|---|---|"]
        for _, r in df.iterrows():
            if r["position"] == "QB":
                perf = f"{int(r.get('pass_yards') or 0)}y / {int(r.get('pass_tds') or 0)}TD / {int(r.get('ints') or 0)}INT"
            else:
                perf = f"{int(r.get('receptions') or 0)}rec / {int(r.get('rec_yards') or 0)}y / {int(r.get('rec_tds') or 0)}TD"
            lines.append(f"| {r['img']} | {r['player']} | {r['position']} | {r['team']} | {perf} | {round(r['composite_scaled'],1)} | {r['trend']} |")
        (outdir/"faves_table.md").write_text("\n".join(lines), encoding="utf-8")
    else:
        (outdir/"faves_table.md").write_text("(No favorites matched)", encoding="utf-8")


    make_report_index_notion(outdir, week, year)


if __name__ == "__main__":
    main()
