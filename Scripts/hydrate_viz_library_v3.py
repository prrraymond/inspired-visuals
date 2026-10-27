#!/usr/bin/env python3
"""
hydrate_viz_library_v2.py (Unified Pipeline Version)

- Acts as the final stage in the chart production pipeline.
- Queries the unified Notion DB for entries with a specific status (e.g., '3. Needs hydration').
- Reads all structured parameters (SQL, styling, layout, attributes) from the Notion page.
- Generates the final, data-driven Plotly code and chart image.
- Uploads all final assets and updates the Notion page with output links and a final status.
"""
from __future__ import annotations
import os
import sys
import io
import csv
import json
import time
import argparse
import re
import textwrap
from typing import Dict, Any, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from supabase import create_client, Client
from anthropic import Anthropic, BadRequestError, NotFoundError, RateLimitError, APIError
import plotly.io as pio
from plotly.graph_objects import Figure

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from data_contract import derive_contract                      # noqa: E402
from render_guard import (                                     # noqa: E402
    check_dataset, check_figure, propose_parameters, attach_proposal, ContractViolation,
)
from provenance import strip_provenance, resolve_state, REPOINTED   # noqa: E402

# --- INITIALIZATION ---
pio.kaleido.scope.default_engine = "kaleido"
load_dotenv(dotenv_path=".env.local")

# --- LOAD SECRETS FROM .env.local ---
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
ANTHROPIC_API_KEY = os.getenv("CLAUDE_API_KEY")
DB_URL = os.getenv("SUPABASE_DB_URL") # For SQL execution

# --------------------------------------------------------------------------
# --- SCRIPT CONFIGURATION ---
# --------------------------------------------------------------------------
NOTION_DB_ID = os.getenv("NOTION_PROD_DATABASE_ID")
STATUS_READY = os.getenv("NOTION_STATUS_READY_FOR_GENERATION", "3. Needs hydration")
# "4. Complete" was never an option on the Viz library Status property, so every
# write-back Notion received was rejected wholesale (the PATCH is validated
# atomically, taking Dataset URL / Final Code URL / Code Preview down with it).
# "4. Hydrated" is what this stage actually produces; "5. Complete" stays free
# for reviewed-and-done.
STATUS_COMPLETE = os.getenv("NOTION_STATUS_COMPLETE", "4. Hydrated")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20240620")
# --------------------------------------------------------------------------

# --- CONSTANTS ---
NOTION_BASE_URL = "https://api.notion.com/v1"
BUCKET = os.getenv("SUPABASE_BUCKET", "viz-training-assets")
DATASETS_PREFIX = "datasets"
CODE_PREFIX = "code"
IMAGE_PREFIX = "charts"
SIGNED_URL_TTL = 31536000  # 1 year

# --- Property names in your Unified DB ---
# This master dictionary maps all properties required by the script.
ALL_PROPS = {
    "status": "Status", "asset_name": "Asset name", "chartid": "chartid", "asset_url": "Asset URL",
    "sql": "SQL", "final_sql": "Final SQL", "base_code_url": "Base Code URL",
    "data_filter": "Data Filter", "sort_by": "Sort By",
    "highlight_map": "Highlight Map", "default_color": "Default Color",
    "add_text": "Add Text", "add_line": "Add Line", "layout_options": "Layout Options",
    "is_standard": "Standard", "is_subplot": "Subplot",
    "is_time_series": "Time Series", "is_multi_color": "Multi-color series",
    "dataset_url": "Dataset URL", "final_code_url": "Final Code URL",
    "code_preview": "Code Preview", "chart_image": "Chart Image",
    "provenance": "Provenance",
}

# Written by this stage, never read back into the prompt. Reading it made the
# contract 54.6% of the parameters block, and on a re-hydration the value read
# would be the PREVIOUS run's contract -- describing data this run has not
# fetched yet. The prompt already receives the live column list.
WRITE_ONLY_PROPS = {"data_contract": "Data contract"}

# --- VALIDATION ---
if not all([NOTION_API_KEY, NOTION_DB_ID, SUPABASE_URL, SUPABASE_KEY, ANTHROPIC_API_KEY, DB_URL]):
    raise SystemExit("ERROR: Missing one or more required API Keys or IDs in .env.local")

# --- CLIENTS ---
supa: Optional[Client] = create_client(SUPABASE_URL, SUPABASE_KEY)
anth: Optional[Anthropic] = Anthropic(api_key=ANTHROPIC_API_KEY)

psycopg = None
try:
    import psycopg
except ImportError:
    print("WARNING: psycopg (v3) not found. This may cause issues.")

# --- NOTION HELPERS ---
def get_notion_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {NOTION_API_KEY}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

def query_notion_for_status(status_name: str, why: bool = False) -> List[dict]:
    if why: print(f"Querying Notion for pages with status: '{status_name}'...")
    url = f"{NOTION_BASE_URL}/databases/{NOTION_DB_ID}/query"
    payload = {"filter": {"property": ALL_PROPS["status"], "status": {"equals": status_name}}}
    try:
        response = requests.post(url, headers=get_notion_headers(), data=json.dumps(payload))
        response.raise_for_status()
        return response.json().get("results", [])
    except Exception as e:
        print(f"ERROR: Failed to query Notion. {e}")
        return []

def extract_property_value(prop: dict) -> Any:
    if not prop: return None
    prop_type = prop.get("type")
    if prop_type == "title":
        return "".join(item.get("plain_text", "") for item in prop.get("title", [])).strip()
    if prop_type == "rich_text":
        return "".join(item.get("plain_text", "") for item in prop.get("rich_text", [])).strip()
    if prop_type == "url":
        return prop.get("url")
    if prop_type == "checkbox":
        return prop.get("checkbox")
    if prop_type == "select":
        return (prop.get("select") or {}).get("name")
    if prop_type == "status":
        return (prop.get("status") or {}).get("name")
    return None

# --- STORAGE & DATABASE HELPERS ---
def upload_to_storage(key: str, data: bytes, content_type: str, dry=False):
    if dry: return
    supa.storage.from_(BUCKET).upload(key, data, {"content-type": content_type, "upsert": "true"})

def get_storage_url(key: str) -> str:
    return supa.storage.from_(BUCKET).create_signed_url(key, SIGNED_URL_TTL)["signedURL"]

def execute_sql_to_csv(sql: str) -> bytes:
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.strip().rstrip(";"))
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")

# --- CORE LOGIC: PROMPT BUILDING ---
def build_final_code_prompt(base_code: str, dataset_url: str, parameters: dict, column_names: list,
                            *, repointed: bool = False, why: bool = False) -> str:
    # An entry whose SQL has been repointed no longer renders its source subject.
    # Its provenance fields -- the source title, note, original SQL, and the eight
    # Stage-B styling fields -- describe a different chart, and this prompt calls
    # everything in <parameters> a strict requirement. Left in, they produce a
    # chart of one subject labelled as another: valid code, valid figure, false
    # meaning, and every existing gate passes it.
    parameters, dropped = strip_provenance(parameters, repointed=repointed)
    if dropped and why:
        print(f"  [prompt] repointed entry — dropped {len(dropped)} provenance field(s): "
              f"{', '.join(sorted(dropped))}")

    params_for_prompt = {}
    for key, value in parameters.items():
        # Identity, not equality: `value in [None, "", False]` also discards a
        # legitimate False and, because 0 == False in Python, a legitimate 0.
        # `is_subplot: False` is a real statement and never reached the prompt.
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if isinstance(value, str) and value.startswith(("{", "[")):
            try:
                params_for_prompt[key] = json.loads(value)
            except json.JSONDecodeError:
                params_for_prompt[key] = value
        else:
            params_for_prompt[key] = value

    params_json_str = json.dumps(params_for_prompt, indent=2)

    return textwrap.dedent(f"""
        You are a senior Plotly engineer tasked with generating a production-ready, self-contained Python script.
        You MUST follow all instructions in the <parameters> section. They are strict requirements.
        The dataset has the following columns: {column_names}. You MUST ONLY use column names from this list.

        <parameters>
        {params_json_str}
        </parameters>

        Use the following abstract base code as a structural reference.

        <base_code>
        {base_code}
        </base_code>

        Dataset URL: {dataset_url}
        Return ONLY the final, complete Python code.
    """).strip()

# --- CORE LOGIC: CODE GENERATION & EXECUTION ---
def call_claude_for_code(prompt: str, why=False, dry=False) -> Optional[str]:
    if dry: return "# DRY RUN: Code would be generated here."
    if why: print(f"  [LLM] using model: {CLAUDE_MODEL}")
    try:
        response = anth.messages.create(
            model=CLAUDE_MODEL, max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        # `temperature` is rejected (400) on current models, and thinking blocks
        # precede the text block, so content[0] is not necessarily the answer.
        return "".join(b.text for b in response.content if b.type == "text")
    except Exception as e:
        if why: print(f"  [LLM] error: {e}")
        return None

def generate_chart_image(chartid: str, final_code: str, dataset_url: str, dry=False,
                         contract: Optional[dict] = None) -> Optional[str]:
    """
    Execute the generated script and render it.

    Two gates bracket the exec, because this was the last point in the pipeline
    where a semantic failure could pass as success:

      PRE  -- check_dataset() refuses an empty result set or an all-NULL column.
              Either renders a blank chart rather than raising.
      POST -- check_figure() refuses a Figure with no traces or no points. A
              successful render of nothing is the exact shape of failure that has
              been reported as success here before.
    """
    if dry: return f"https://example.com/charts/{chartid}_dry_run.png"

    if contract is not None:
        check_dataset(contract)          # raises ContractViolation

    ns = {"dataset_url": dataset_url}
    helper = textwrap.dedent("""
        import io, pandas as pd, requests
        def load_csv(url):
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            return pd.read_csv(io.BytesIO(r.content))
    """)
    exec(compile(helper + "\n" + final_code, f"<final_code:{chartid}>", "exec"), ns)
    fig = next((v for v in ns.values() if isinstance(v, Figure)), None)
    if fig is None: raise RuntimeError("Script executed, but no Plotly Figure object was found.")

    check_figure(fig, chart=chartid)     # raises ContractViolation

    png_bytes = fig.to_image(format="png", scale=2)
    key = f"{IMAGE_PREFIX}/{chartid}/{chartid}_chart.png"
    upload_to_storage(key, png_bytes, "image/png")
    return get_storage_url(key)

# --- MAIN WORKFLOW ---
def main(dry_run=False, why=False, limit: Optional[int] = None, rerun_status: Optional[str] = None):
    status_to_query = rerun_status if rerun_status else STATUS_READY
    pages_to_process = query_notion_for_status(status_to_query, why=why)
    
    if not pages_to_process:
        print(f"No pages found with '{status_to_query}' status. Nothing to do.")
        return

    processed = 0
    for lib_row in pages_to_process:
        if limit and processed >= limit: break
        
        props = lib_row["properties"]
        chartid = extract_property_value(props.get(ALL_PROPS["chartid"]))
        if not chartid: continue
        
        print(f"Processing {chartid}...")
        
        try:
            parameters = {key: extract_property_value(props.get(prop_name)) for key, prop_name in ALL_PROPS.items()}
            
            # --- INTELLIGENT SQL SELECTION ---
            # Prioritize 'Final SQL' if it exists, otherwise fall back to 'SQL'.
            dataset_sql = parameters.get("final_sql") or parameters.get("sql", "")
            if not dataset_sql:
                if why: print(f"  SKIP {chartid}: No 'Final SQL' or 'SQL' property found.")
                continue
            
            csv_bytes = execute_sql_to_csv(dataset_sql)
            dataset_key = f"{DATASETS_PREFIX}/{chartid}/{chartid}.csv"
            upload_to_storage(dataset_key, csv_bytes, "text/csv", dry=dry_run)
            dataset_url = get_storage_url(dataset_key)
            if why: print(f"  Dataset: {dataset_url} ({len(csv_bytes)} bytes)")

            header_line = csv_bytes.split(b'\n', 1)[0].decode('utf-8')
            column_names = [name.strip() for name in header_line.split(',')]

            # --- DATA CONTRACT -------------------------------------------------
            # Derived from the real result set, never authored by the model. Written
            # as a matter of course so every hydrated row carries one.
            import pandas as _pd, io as _io
            _df = _pd.read_csv(_io.BytesIO(csv_bytes))
            contract = derive_contract(_df, name=chartid)
            for _c in contract["columns"]:
                if _c["kind"] == "numeric" and not _c["all_null"]:
                    _p = propose_parameters(contract, _c["name"])
                    attach_proposal(contract, _p)          # status="proposed", never applied
            if why:
                _dead = [c["name"] for c in contract["columns"] if c["all_null"]]
                print(f"  Contract: {contract['row_count']} rows x {contract['column_count']} cols"
                      f"{'  ALL-NULL: ' + str(_dead) if _dead else ''}"
                      f"  proposals={len(contract.get('suggested_parameters', []))}")

            prov_state, prov_disagreement = resolve_state(
                parameters.get("sql"), parameters.get("final_sql"), parameters.get("provenance"))
            repointed = prov_state == REPOINTED
            if why:
                print(f"  Provenance: {prov_state}"
                      + (f"  [!] {prov_disagreement}" if prov_disagreement else ""))

            base_code_url = parameters.get("base_code_url")
            if not base_code_url:
                if why: print(f"  WARN {chartid}: No base code URL found.")
                base_code = "# No base code provided."
            else:
                base_code = requests.get(base_code_url).text

            final_code, chart_image_url = None, None
            last_error = ""
            for attempt in range(3):
                prompt = build_final_code_prompt(base_code, dataset_url, parameters, column_names,
                                                 repointed=repointed, why=why)
                if attempt > 0:
                    if why: print(f"  Attempt {attempt + 1}/3: Retrying with error feedback...")
                    prompt += f"\n\nThe previous attempt failed. Re-analyze the <parameters> and provide a corrected script.\nERROR: {last_error}"

                generated_code = call_claude_for_code(prompt, why=why, dry=dry_run)
                if not generated_code:
                    last_error = "LLM returned empty code."
                    continue
                
                try:
                    chart_image_url = generate_chart_image(chartid, generated_code, dataset_url, dry=dry_run, contract=contract)
                    final_code = generated_code
                    if why: print(f"  SUCCESS on attempt {attempt + 1}!")
                    break
                except Exception as e:
                    last_error = f"{type(e).__name__}: {e}"
                    if why: print(f"  Caught error on attempt {attempt + 1}: {last_error}")

            if not final_code:
                print(f"  ERROR: Failed to generate valid code for {chartid} after 3 attempts.")
                continue

            final_code_key = f"{CODE_PREFIX}/{chartid}/{chartid}_final.py"
            upload_to_storage(final_code_key, final_code.encode("utf-8"), "text/x-python", dry=dry_run)
            final_code_url = get_storage_url(final_code_key)

            update_properties = {
                ALL_PROPS["dataset_url"]: {"url": dataset_url},
                ALL_PROPS["final_code_url"]: {"url": final_code_url},
                ALL_PROPS["code_preview"]: {"rich_text": [{"text": {"content": final_code[:1800]}}]},
                ALL_PROPS["status"]: {"status": {"name": STATUS_COMPLETE}},
                WRITE_ONLY_PROPS["data_contract"]: {"rich_text": [
                    {"text": {"content": chunk}} for chunk in
                    [json.dumps(contract, separators=(",", ":"))[i:i + 1800]
                     for i in range(0, len(json.dumps(contract, separators=(",", ":"))), 1800)]
                ]},
            }
            if chart_image_url:
                update_properties[ALL_PROPS["chart_image"]] = {"files": [{"type": "external", "name": f"{chartid}_chart.png", "external": {"url": chart_image_url}}]}

            if not dry_run:
                resp = requests.patch(f"{NOTION_BASE_URL}/pages/{lib_row['id']}", headers=get_notion_headers(), data=json.dumps({"properties": update_properties}))
                if resp.status_code >= 400:
                    # Notion validates the whole PATCH atomically: one bad property
                    # (e.g. a Status option that does not exist in the schema) rejects
                    # every field in this update. Never report success on a 4xx/5xx.
                    raise RuntimeError(
                        f"Notion write-back failed for {chartid}: HTTP {resp.status_code} — {resp.text[:500]}"
                    )

            print(f"UPDATED {chartid}: Status set to '{STATUS_COMPLETE}'")
            processed += 1

        except Exception as e:
            print(f"FATAL ERROR processing {chartid}: {e}")
            if why: import traceback; traceback.print_exc()

    print(f"\nDone. Processed: {processed}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generates final chart code using a structured Notion schema.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--why", action="store_true", help="Enable verbose logging.")
    parser.add_argument("--limit", type=int, help="Max number of items to process.")
    parser.add_argument("--rerun-status", type=str, help=f"Target a specific status for processing (e.g., '{STATUS_COMPLETE}'). Defaults to '{STATUS_READY}'.")
    args = parser.parse_args()
    main(dry_run=args.dry_run, why=args.why, limit=args.limit, rerun_status=args.rerun_status)

