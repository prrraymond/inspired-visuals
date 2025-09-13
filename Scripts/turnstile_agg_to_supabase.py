#!/usr/bin/env python3
"""
Enhanced bulk loader for NYC subway data using psycopg COPY (much faster than Supabase client)
"""
import psycopg
import pandas as pd
import os
from dotenv import load_dotenv

load_dotenv(".env.local")

# Database connection from env vars
DATABASE_URL = os.getenv("DATABASE_URL")  # or construct from SUPABASE_* vars
if not DATABASE_URL:
    host = os.getenv("SUPABASE_HOST", "").replace("https://", "").replace("http://", "")
    user = os.getenv("SUPABASE_USER", "postgres") 
    password = os.getenv("SUPABASE_PASSWORD", "")
    port = os.getenv("SUPABASE_PORT", "5432")
    database = os.getenv("SUPABASE_DB", "postgres")
    DATABASE_URL = f"postgresql://{user}:{password}@{host}:{port}/{database}"

def load_station_daily(csv_path: str, table_name: str = "station_daily"):
    """Load station daily data with proper upserts"""
    df = pd.read_csv(csv_path)
    print(f"Loading {len(df)} rows to {table_name}")
    
    with psycopg.connect(DATABASE_URL) as con:
        with con.cursor() as cur:
            # Create temp staging table
            cur.execute(f"CREATE TEMP TABLE stg_{table_name} (LIKE public.{table_name} INCLUDING ALL) ON COMMIT DROP;")
            
            # Bulk load to staging via COPY (super fast)
            with cur.copy(f"COPY stg_{table_name} FROM STDIN WITH (FORMAT CSV, HEADER TRUE)") as copy:
                df.to_csv(copy, index=False)
            
            # Upsert from staging to main table
            cur.execute(f"""
            INSERT INTO public.{table_name} AS t (station, date, entries, exits, lines, ridership_proxy, borough, complex_id)
            SELECT 
                station, 
                date::date, 
                entries::bigint, 
                NULLIF(exits, 'NaN')::bigint,  -- Handle NaN strings
                NULLIF(lines, 'nan'),
                NULLIF(ridership_proxy, 'NaN')::bigint,
                NULLIF(borough, 'nan'),
                NULLIF(complex_id, 'nan')
            FROM stg_{table_name}
            ON CONFLICT (station, date)
            DO UPDATE SET
                entries = EXCLUDED.entries,
                exits = COALESCE(EXCLUDED.exits, t.exits),
                lines = COALESCE(EXCLUDED.lines, t.lines),
                ridership_proxy = EXCLUDED.ridership_proxy,
                borough = COALESCE(EXCLUDED.borough, t.borough),
                complex_id = COALESCE(EXCLUDED.complex_id, t.complex_id);
            """)
            print(f"Upserted {cur.rowcount} rows")
            con.commit()

def load_line_daily(csv_path: str, table_name: str = "line_daily"):
    """Load line daily data"""
    if not os.path.exists(csv_path):
        print(f"No line daily file found at {csv_path}")
        return
        
    df = pd.read_csv(csv_path)
    print(f"Loading {len(df)} rows to {table_name}")
    
    with psycopg.connect(DATABASE_URL) as con:
        with con.cursor() as cur:
            cur.execute(f"CREATE TEMP TABLE stg_{table_name} (LIKE public.{table_name} INCLUDING ALL) ON COMMIT DROP;")
            
            with cur.copy(f"COPY stg_{table_name} FROM STDIN WITH (FORMAT CSV, HEADER TRUE)") as copy:
                df.to_csv(copy, index=False)
            
            cur.execute(f"""
            INSERT INTO public.{table_name} AS t (line, date, entries)
            SELECT line, date::date, entries::bigint
            FROM stg_{table_name}
            ON CONFLICT (line, date)
            DO UPDATE SET entries = EXCLUDED.entries;
            """)
            print(f"Upserted {cur.rowcount} rows")
            con.commit()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--station-csv", default="data/NYC/turnstile_station_daily.csv")
    parser.add_argument("--line-csv", default="data/NYC/turnstile_line_daily.csv") 
    parser.add_argument("--station-table", default="station_daily")
    parser.add_argument("--line-table", default="line_daily")
    
    args = parser.parse_args()
    
    # Load both datasets
    load_station_daily(args.station_csv, args.station_table)
    load_line_daily(args.line_csv, args.line_table)
