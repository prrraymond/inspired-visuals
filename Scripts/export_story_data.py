#!/usr/bin/env python3
"""
Snapshot the data behind each story chart into gallery/stories/data/.

    python3 Scripts/export_story_data.py

A story chart opens with real data, not a placeholder dataset, and a deployment
reads no database -- so the data a story opens with is frozen into the repo, the
same way the bundle freezes templates. Run this to refresh it, then rebuild the
bundle (Scripts/build_bundle.py) so the previews match.

The queries are the ones in viz_code_v20261025.ipynb, reshaped to the tidy form
each story template reads. Long daily series are averaged by week: the workspace
sends the whole table back on every edit and draws up to 5,000 rows, and a
seven-day average sampled weekly is the same line the notebook drew from a daily
rolling mean.
"""
from __future__ import annotations

import os
import pathlib
import sys
from decimal import Decimal

import pandas as pd
import psycopg
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "gallery" / "stories" / "data"

load_dotenv(ROOT / ".env.local")
sys.path.insert(0, str(ROOT / "Scripts" / "lib"))
from supabase_config import problems  # noqa: E402


def q(conn, sql: str) -> pd.DataFrame:
    cur = conn.execute(sql)
    df = pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])
    # numeric columns arrive as Decimal, which pandas treats as text
    for c in df.columns:
        first = df[c].dropna().head(1)
        if len(first) and isinstance(first.iat[0], Decimal):
            df[c] = df[c].astype(float)
    return df


def weekly_mean(df: pd.DataFrame, date: str, group: str, value: str) -> pd.DataFrame:
    """Average daily value per group per week (weeks ending Sunday), full weeks only."""
    d = df.copy()
    d[date] = pd.to_datetime(d[date])
    g = d.set_index(date).groupby(group)[value]
    out = pd.concat([g.resample("W-SUN").mean().rename(value),
                     g.resample("W-SUN").count().rename("_days")], axis=1).reset_index()
    out = out[out["_days"] == 7].drop(columns="_days")
    out[value] = out[value].round(0).astype(int)
    return out[[date, group, value]].sort_values([date, group])


def stories(conn) -> dict[str, pd.DataFrame]:
    out = {}

    msa = q(conn, """select month, sp500_close, consumer_sentiment, approval_pct
                     from market_sentiment_approval_monthly
                     where month >= '1980-01-01' order by month""")
    long = msa.melt(id_vars="month", var_name="series", value_name="value").dropna()
    long["series"] = long["series"].map({"sp500_close": "S&P 500",
                                         "consumer_sentiment": "Consumer sentiment",
                                         "approval_pct": "Presidential approval"})
    # Series order is colour order: the S&P takes the first, darkest colour.
    long["_order"] = long["series"].map({"S&P 500": 0, "Consumer sentiment": 1,
                                         "Presidential approval": 2})
    out["story-stocks-vs-mood"] = (long.sort_values(["_order", "month"])
                                   [["month", "series", "value"]])

    sp = q(conn, """select day as date, close from sp500_daily
                    where day > (select max(day) from sp500_daily) - interval '1 year'
                    order by day""")
    out["story-sp500-year"] = sp

    mta = q(conn, "select date, entries from mta_system_daily order by date")
    mta["system"] = "All"
    out["story-subway-recovery"] = (weekly_mean(mta, "date", "system", "entries")
                                    .drop(columns="system")
                                    .rename(columns={"entries": "entries_daily_avg"}))

    boro = q(conn, """select date, borough, sum(entries) as entries from station_daily
                      where date >= (select max(date) from station_daily) - interval '2 years'
                      group by 1, 2""")
    out["story-subway-boroughs"] = weekly_mean(boro, "date", "borough", "entries")

    d311 = q(conn, """select date, initcap(borough) as borough, sum(request_count) as requests
                      from "311_daily" where borough not in ('Unspecified', 'Unknown')
                      group by 1, 2 order by 1, 2""")
    weekly_311 = weekly_mean(d311, "date", "borough", "requests")
    out["story-311-boroughs"] = weekly_311
    out["story-311-share"] = weekly_311.copy()
    d311["date"] = pd.to_datetime(d311["date"])
    last = d311["date"].max()
    week = d311[d311["date"] > last - pd.Timedelta(days=7)]
    out["story-311-week"] = (week.groupby("borough", as_index=False)["requests"].sum()
                             .sort_values("requests", ascending=False))

    scf = q(conn, """select year, income_group, share_of_stock_owners
                     from scf_stock_by_income order by year, group_order""")
    out["story-stock-ownership"] = scf

    edu = q(conn, """select name, education, level_order, share_pct
                     from educational_attainment_share
                     where year = (select max(year) from educational_attainment_share)
                       and (geo_level = 'us' or state_code in
                            ('MA', 'CO', 'NY', 'CA', 'FL', 'TX', 'MS', 'WV'))""")
    # Nation first, then states by share with a bachelor's or more.
    ba = (edu[edu["education"].isin(["Bachelor's degree", "Graduate or professional"])]
          .groupby("name")["share_pct"].sum())
    order = ["United States"] + [n for n in ba.sort_values(ascending=False).index
                                 if n != "United States"]
    edu["_row"] = edu["name"].map({n: i for i, n in enumerate(order)})
    edu = edu.sort_values(["_row", "level_order"])
    edu["share_pct"] = edu["share_pct"].round(1)
    out["story-education-states"] = edu[["name", "education", "share_pct"]]

    tenure = q(conn, """select education, level_order, tenure, estimate
                        from tenure_education_share
                        where geo_level = 'us'
                          and year = (select max(year) from tenure_education_share)""")
    tenure = tenure.sort_values(["level_order", "tenure"])
    tenure["education"] = tenure["education"].map({
        "<HS": "Less than HS", "HS/GED": "HS/GED",
        "Some college/AA": "Some college/AA", "BA+": "BA+"}).fillna(tenure["education"])
    out["story-owner-renter"] = tenure[["education", "tenure", "estimate"]]

    nfl = q(conn, """select state_code, players_per_million, state_name
                     from nfl_actives_by_state
                     where season = (select max(season) from nfl_actives_by_state)
                     order by state_code""")
    nfl["players_per_million"] = nfl["players_per_million"].astype(float).round(2)
    out["story-nfl-home-states"] = nfl
    return out


def main() -> int:
    issues = problems()
    if issues:
        raise SystemExit("Supabase config problem:\n  " + "\n  ".join(issues))
    OUT.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(os.environ["SUPABASE_DB_URL"]) as conn:
        frames = stories(conn)
    for name, df in frames.items():
        path = OUT / f"{name}.csv"
        df.to_csv(path, index=False)
        print(f"{name:28s} {len(df):>5,} rows  {list(df.columns)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
