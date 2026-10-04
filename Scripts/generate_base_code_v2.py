#!/usr/bin/env python3
"""
generate_base_code.py (Batch Processing Version)

- Acts as the "toolmaker" for the chart generation pipeline. This script is run to
  bulk-create or update the abstract base code templates for your entire library.
- It scans the main "Viz Library" for all charts.
- For each chart, it uses an LLM to analyze its reference image and generate a
  generic, reusable, abstract Plotly template.
- It uploads the new template to Supabase and creates/updates a corresponding entry
  in the "Code" database, making it available for the downstream `hydrate` script.
"""
from __future__ import annotations
import os
import io
import json
import argparse
import textwrap
import base64

import requests
import sys
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from caption_gate import check_captions, CaptionViolation   # noqa: E402

from dotenv import load_dotenv
from pydantic import BaseModel
from supabase import create_client, Client
from anthropic import Anthropic

# --- CONFIGURATION & CLIENTS ---
load_dotenv(dotenv_path=".env.local")

# --- API Keys & Secrets ---
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
ANTHROPIC_API_KEY = os.getenv("CLAUDE_API_KEY")

# --- Notion Database IDs ---
VIZ_LIBRARY_DB_ID = os.getenv("NOTION_PROD_DATABASE_ID")
CODE_DB_ID = os.getenv("NOTION_TARGET_DATABASE_ID", "25ae89d6bdbe807fbe99eb951671ab8c")

# --- AI Configuration ---
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20240620")

# --- Supabase Configuration ---
BUCKET = os.getenv("SUPABASE_BUCKET", "viz-training-assets")
BASE_CODE_PREFIX = "base_code_templates"
SIGNED_URL_TTL = 31536000 * 5  # 5 years

# --- Notion Property Names ---
PROPS = {
    "chartid": "chartid",
    "asset_url": "Asset URL",
    "base_code_url": "Base Code URL",
}

# Stage C produces base code; the row is then ready for Stage D to hydrate.
# Must be an existing option on PROD's Status property (type `status`, which the
# API cannot extend).
STATUS_AFTER_STAGE_C = os.getenv("NOTION_STATUS_AFTER_BASE_CODE", "3. Needs hydration")

# Statuses at or past review. A reviewed template, the SQL validated against it, and
# the contract derived from that SQL's result are a MATCHED SET: regenerating the
# template silently breaks the pairing, and regeneration is not deterministic --
# the same chart image has produced templates with different required columns on
# different runs. --overwrite alone must not touch these; --force is required.
PROTECTED_STATUSES = {
    s.strip() for s in os.getenv(
        "NOTION_PROTECTED_STATUSES", "4. Hydrated,Needs Review,5. Complete"
    ).split(",") if s.strip()
}

# --- Validation ---
if not all([NOTION_API_KEY, VIZ_LIBRARY_DB_ID, CODE_DB_ID, SUPABASE_URL, SUPABASE_KEY, ANTHROPIC_API_KEY]):
    raise SystemExit("ERROR: Missing one or more required API Keys or DB IDs in .env.local")

# --- CLIENTS ---
supa: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
anth: Anthropic = Anthropic(api_key=ANTHROPIC_API_KEY)

# --- AI PROMPT ---
# Abstract-template requirements are unchanged from the version that produced the
# 220 surviving templates. What is restored, from the pre-rewrite generate_base_code.py,
# is structured JSON output carrying `caveats` and `notes` -- the vision-derived
# judgement that only the model can produce, and the library's actual differentiator.
#
# `data_contract` is deliberately NOT requested: it is derived from the real dataset
# with pandas, not authored by the model.
TEMPLATE_PROMPT = """
You are generating reusable, ABSTRACT Plotly (Python) templates from chart screenshots.

Return JSON ONLY with these keys:
- plotly_code: A string of Python code -- a generic, reusable template.
- filename_suggestion: A short kebab-case base name (e.g. "grouped-bar-timeseries").
- notes: 1-3 sentences on how to adapt the template for real data.
- caveats: A list of strings naming the important STRUCTURAL features of the chart
  (e.g. "dual y-axes", "log scale", "percent stacking", "cumulative sum", "faceting",
  "Cleveland dot layout", "custom categorical ordering", "annotation-dependent",
  "reversed y-axis order", "horizontal bar orientation"). Prefer these established
  terms where they apply. Describe structure and encoding decisions, not colours or
  font sizes.

ANALYSIS REQUIREMENTS
1. Identify the fundamental chart type (bar, line, scatter, etc.) and structure (grouped, stacked, subplots).
2. Note special features: dual axes, log scales, annotations, specific layouts (like a Cleveland dot plot).
3. Replicate the general styling and layout (titles, axis labels, legend placement) but use generic text.

CODE GENERATION REQUIREMENTS
- CRITICAL: Do NOT create an inline pandas DataFrame or use hard-coded data. The template must be abstract.
- Use placeholder variables for column names (e.g. `x_column`, `y_column`, `color_column`).
- Add comments explaining what kind of data should be mapped to each placeholder variable.
- The code must define a `build_figure(df)` function that takes a DataFrame and returns a go.Figure.
- Use ONLY `plotly.graph_objects` (no `plotly.express`).
- Implement the structural features you detected (e.g. `secondary_y`, `barmode='group'`, `make_subplots`).
- Every property you set must be valid Plotly; the template will be executed and rendered.
- Keep the code clean, modular, and focused on reusability.

CAPTIONS -- THE LIBRARY DOES NOT NAME THE SUBJECT
The person who supplies the data says what it means. Never write a caption that
describes the chart's subject, even if the source image shows one, and even if it
would be accurate. Use exactly these placeholders:

  title                 "Chart title"
  subtitle / units      "Units / measure description"
  any axis title        "Axis label"
  series / trace name   "Series 1", "Series 2", ...
  category / bin label  "Category A", "Category B", ...
  diverging labels      "Above baseline" / "Below baseline"
  source or credit      "Source / credit"
  free annotation       "Annotation text"

Do NOT emit the source chart's title, its legend wording, its axis wording, its
credit line, or its category names. "PROFIT"/"LOSS" and "RATIO" are subject
claims; "Above baseline"/"Below baseline" and "Axis label" are not. Column
identifiers (e.g. `x_column = "state_code"`) are not captions and are unaffected.

OUTPUT FORMAT
Return JSON ONLY. No markdown fences, no prose.
- Keys: plotly_code, filename_suggestion, notes, caveats.
- plotly_code is a string; caveats is a list of strings; notes is 1-3 sentences.
"""

# --- PROPERTY-NAME RESOLUTION -------------------------------------------------
# Ported from the pre-rewrite generate_base_code.py, which validated every
# property name against the live Notion schema instead of trusting a literal.
# Dropping its coerce step is what produced the "Base code URL" vs "Base Code URL"
# bug: Notion property names are case-sensitive and a mismatch rejects the write.
#
# Deliberate change from the original: the HEAD version ended with
# "# else: drop silently", which is the same silent-failure class this port
# exists to remove. This version raises instead.

NAME_FALLBACKS = {
    "Base Code URL": ["Base code URL", "Code URL"],
    "Source code":   ["Source Code", "Code Preview"],
    "Source path":   ["Source Path"],
    "Caveats":       ["Chart notes", "Asset note"],
    "QA notes":      ["Chart notes", "Description"],
    "Dataset URL":   ["Dataset Url"],
    "Status":        ["Status"],
    # NOTE: 'Title' deliberately has NO fallback to 'Asset name'. On PROD, 'Asset name'
    # is the title-type property holding the curated chart name ("Increase in Arrests
    # by U.S. State"); falling back to it would overwrite 400 hand-written titles with
    # generated slugs. If 'Title' is ever absent, this must fail loudly instead.
}


def get_db_properties(database_id: str) -> dict:
    """Return {property_name: property_type} for a live Notion database."""
    r = requests.get(f"https://api.notion.com/v1/databases/{database_id}", headers=get_notion_headers())
    r.raise_for_status()
    return {name: p.get("type") for name, p in r.json()["properties"].items()}


def coerce_target(name: str, valid: dict, fallbacks: dict, lowered: dict):
    """Resolve one intended property name to its target name, or None."""
    if name in valid:
        return name
    hit = next((alt for alt in fallbacks.get(name, []) if alt in valid), None)
    return hit or lowered.get(name.lower())


def coerce_prop_names(props: dict, valid: dict, fallbacks: dict = NAME_FALLBACKS) -> dict:
    """
    Map intended property names onto names that actually exist in the target DB.

    Unlike the HEAD original, an unresolvable property is a hard error: writing a
    subset of the intended fields and reporting success is exactly the failure
    mode this function was reintroduced to prevent.
    """
    lowered = {name.lower(): name for name in valid}
    out, unresolved = {}, []
    for k, v in props.items():
        if k in valid:
            out[k] = v
            continue
        hit = next((alt for alt in fallbacks.get(k, []) if alt in valid), None)
        if hit is None and k.lower() in lowered:
            # Case drift only -- e.g. "Base code URL" vs "Base Code URL" (B4).
            # Resolve it, but say so; Notion names are case-sensitive.
            hit = lowered[k.lower()]
        if hit:
            print(f"  - [schema] '{k}' not in target DB; writing to '{hit}' instead.")
            out[hit] = v
        else:
            unresolved.append(k)
    collisions = [n for n in set(out) if sum(1 for kk in props if coerce_target(kk, valid, fallbacks, lowered) == n) > 1]
    if collisions:
        raise KeyError(
            f"Two or more intended properties resolve to the same target property {collisions}; "
            f"one would silently overwrite the other."
        )
    if unresolved:
        raise KeyError(
            f"Property names not present in the target Notion database and with no usable "
            f"fallback: {unresolved}. Available: {sorted(valid)}"
        )
    return out


# --- HELPER FUNCTIONS ---
def get_notion_headers() -> dict:
    return {"Authorization": f"Bearer {NOTION_API_KEY}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

def get_all_pages_from_db(database_id: str) -> list[dict]:
    """Fetches all pages from a Notion database, handling pagination."""
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    all_results = []
    has_more = True
    start_cursor = None
    while has_more:
        payload = {"page_size": 100}
        if start_cursor:
            payload["start_cursor"] = start_cursor
        response = requests.post(url, headers=get_notion_headers(), data=json.dumps(payload))
        response.raise_for_status()
        data = response.json()
        all_results.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")
    return all_results

def fetch_bytes(url: str, timeout: int = 60) -> bytes:
    """
    Fetch a URL, raising on any non-200. Ported from HEAD's fetch_bytes, which the
    rewrite replaced with a `return None` on failure -- making a 404 image
    indistinguishable from a missing URL, and letting a failed fetch travel
    silently into the LLM call.
    """
    r = requests.get(url, timeout=timeout)
    if r.status_code == 200 and r.content:
        return r.content
    if " " in url:                      # unencoded spaces in raw/ filenames
        r2 = requests.get(url.replace(" ", "%20"), timeout=timeout)
        r2.raise_for_status()
        if r2.content:
            return r2.content
    r.raise_for_status()
    raise RuntimeError(f"Fetched {url!r} but the body was empty (HTTP {r.status_code}).")


class TemplateOut(BaseModel):
    """Structured Stage C output. No data_contract by design -- see TEMPLATE_PROMPT."""
    plotly_code: str
    filename_suggestion: Optional[str] = None
    notes: Optional[str] = None
    caveats: Optional[List[str]] = None


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
    return s.strip()


def parse_json_strict(s: str) -> dict:
    """
    Parse the model's JSON, falling back to the outermost brace pair. Raises rather
    than returning None: the rewrite's `return None` made 'no JSON' and 'bad JSON'
    indistinguishable to the caller.
    """
    s = _strip_fences(s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j > i:
            return json.loads(s[i:j + 1])
        raise ValueError(f"Model did not return valid JSON (first 200 chars: {s[:200]!r})")


# Asking the model to hand-write JSON with a Python module embedded in a string
# field is fragile: one unescaped character, or a response that stops mid-string,
# and the whole result is unparseable. Two charts failed that way at different
# offsets, which is the signature of truncation rather than a malformed escape --
# thinking tokens share the max_tokens budget, so a long chart can exhaust it
# before the code is finished. A tool call moves JSON assembly to the API, which
# emits validated structure or nothing.
TEMPLATE_TOOL = {
    "name": "emit_template",
    "description": "Return the generated Plotly template and its metadata.",
    "input_schema": {
        "type": "object",
        "properties": {
            "plotly_code": {"type": "string",
                            "description": "The complete Python module source for the template."},
            "filename_suggestion": {"type": "string"},
            "notes": {"type": "string"},
            "caveats": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["plotly_code"],
    },
}


def generate_abstract_code(image_url: str) -> TemplateOut:
    print("  - Analyzing reference image with AI...")
    image_data = base64.b64encode(fetch_bytes(image_url)).decode("utf-8")
    # Streamed, because the request is long enough to exceed the SDK's default
    # non-streaming timeout: a 16k-token ceiling with thinking enabled ran past
    # ten minutes and the SDK then retried the whole thing in silence, three
    # times, with nothing on screen to say so.
    with anth.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=16384,
        tools=[TEMPLATE_TOOL],
        tool_choice={"type": "tool", "name": "emit_template"},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": TEMPLATE_PROMPT},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_data}},
        ]}],
    ) as stream:
        response = stream.get_final_message()
    # A truncated response is the failure this function used to report as bad
    # JSON. Say what actually happened.
    if response.stop_reason == "max_tokens":
        raise ValueError(
            f"Model hit the {16384}-token ceiling before finishing the template "
            f"(thinking tokens share that budget). Raise max_tokens or simplify the chart.")
    block = next((b for b in response.content if b.type == "tool_use"), None)
    if block is None:
        kinds = ", ".join(sorted({b.type for b in response.content})) or "nothing"
        raise ValueError(f"Model returned {kinds}, not the expected tool call "
                         f"(stop_reason={response.stop_reason}).")
    data = dict(block.input)
    if "error" in data:
        raise ValueError(f"Model returned an error payload: {data['error']}")
    result = TemplateOut(**data)
    code = _strip_fences(result.plotly_code)
    if code.startswith("python"):
        code = code[6:].lstrip()
    result.plotly_code = code.strip()
    if not result.plotly_code:
        raise ValueError("Model returned an empty plotly_code string.")

    # The library supplies the template and the encoding; the user supplies the data
    # and says what it means. A template that ships a real caption has taken the
    # second job by guessing, so it does not enter the library. Mechanical check --
    # a correct guess is still a guess.
    check_captions(result.plotly_code)
    print(f"  - Model returned {len(result.plotly_code)}B of code, "
          f"{len(result.caveats or [])} caveats, notes={'yes' if result.notes else 'no'}.")
    return result

def upload_to_storage(key: str, data: bytes) -> str:
    """
    Upload, then confirm the object exists at the expected size before minting a
    URL for it. The pre-rewrite code wrapped URL minting in `except Exception: pass`,
    so a URL could be -- and was -- returned for an upload that never landed; that is
    how 507 catalog rows came to point at objects under code/ that do not exist.
    """
    print(f"  - Uploading template to Supabase at '{key}'...")
    supa.storage.from_(BUCKET).upload(key, data, {"content-type": "text/plain", "upsert": "true"})

    folder, _, leaf = key.rpartition("/")
    # NB: .list() pages at 100 by default. Listing the whole folder and checking
    # membership gives a false "missing" once a prefix exceeds one page, so search
    # for the single object instead of scanning the folder.
    listed = {o["name"]: o for o in
              supa.storage.from_(BUCKET).list(folder, {"search": leaf, "limit": 100})}
    if leaf not in listed:
        raise RuntimeError(f"Upload reported success but no object exists at '{key}'.")
    size = (listed[leaf].get("metadata") or {}).get("size")
    if size is not None and int(size) != len(data):
        raise RuntimeError(f"Object at '{key}' is {size}B but {len(data)}B were uploaded.")
    print(f"  - Verified object at '{key}' ({size}B).")

    return supa.storage.from_(BUCKET).create_signed_url(key, SIGNED_URL_TTL)["signedURL"]

def rt_chunks(text: str, chunk: int = 1800) -> list:
    """Notion caps a single rich_text element at 2000 chars; split below that."""
    if not text:
        return []
    return [{"type": "text", "text": {"content": text[i:i + chunk]}} for i in range(0, len(text), chunk)]


def build_row_properties(chartid: str, base_code_url: str, result: TemplateOut, valid_props: dict) -> dict:
    """
    Assemble the PROD row update. Every name goes through coerce_prop_names, so a
    schema drift raises here rather than being silently dropped.

    Deliberately NOT written:
      - 'Asset name' (PROD's title property) holds the curated chart title, e.g.
        "Increase in Arrests by U.S. State". Writing a generated name would destroy it.
      - 'chartid' is the row's existing identity and is never rewritten.
      - 'Data contract' is derived from the real dataset with pandas, not the model.
    """
    props = {
        PROPS["base_code_url"]: {"url": base_code_url},
        "Source code": {"rich_text": rt_chunks(result.plotly_code[:1800])},
        "Status": {"status": {"name": STATUS_AFTER_STAGE_C}},
    }
    if result.caveats:
        props["Caveats"] = {"rich_text": rt_chunks("\n".join(result.caveats))}
    if result.notes:
        props["QA notes"] = {"rich_text": rt_chunks(f"Auto-generated by Stage C. {result.notes}")}
    if result.filename_suggestion:
        # PROD's 'Title' (rich_text) is empty on every row; the suggestion was
        # previously discarded entirely, so this gives it a home.
        props["Title"] = {"rich_text": [{"text": {"content": result.filename_suggestion}}]}
    return coerce_prop_names(props, valid_props)


CODE_BLOCK_MARKER = "stage-c:generated"


def _existing_stage_c_blocks(page_id: str) -> list:
    """Return ids of python code blocks on the page (paginating through children)."""
    ids, cursor = [], None
    while True:
        url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
        if cursor:
            url += f"&start_cursor={cursor}"
        r = requests.get(url, headers=get_notion_headers())
        r.raise_for_status()
        data = r.json()
        for b in data.get("results", []):
            if b.get("type") == "code" and b["code"].get("language") == "python":
                ids.append(b["id"])
        if not data.get("has_more"):
            return ids
        cursor = data.get("next_cursor")


def write_code_block(page_id: str, code_text: str) -> None:
    """
    Replace the page's Stage C code block with the current template.

    Idempotent by design: --overwrite re-runs would otherwise stack a second and
    third copy of the code on the page. Existing python code blocks are deleted
    first, and the count is printed rather than done silently.

    The full, untruncated template lives here because the 'Source code' property
    only holds 1800 chars -- this is what made the September templates recoverable
    from Notion after their storage objects went missing.
    """
    stale = _existing_stage_c_blocks(page_id)
    for bid in stale:
        d = requests.delete(f"https://api.notion.com/v1/blocks/{bid}", headers=get_notion_headers())
        d.raise_for_status()
    if stale:
        print(f"  - Removed {len(stale)} existing code block(s) before rewriting.")

    body = {"children": [{"object": "block", "type": "code",
                          "code": {"language": "python",
                                   "caption": [{"type": "text", "text": {"content": CODE_BLOCK_MARKER}}],
                                   "rich_text": rt_chunks(code_text)}}]}
    r = requests.patch(f"https://api.notion.com/v1/blocks/{page_id}/children",
                       headers=get_notion_headers(), data=json.dumps(body))
    r.raise_for_status()

    remaining = _existing_stage_c_blocks(page_id)
    if len(remaining) != 1:
        raise RuntimeError(f"Expected exactly 1 code block on {page_id} after write, found {len(remaining)}.")


def update_prod_row(page_id: str, chartid: str, base_code_url: str, result: TemplateOut, valid_props: dict):
    print(f"  - Updating PROD row for {chartid}...")
    properties = build_row_properties(chartid, base_code_url, result, valid_props)
    r = requests.patch(f"https://api.notion.com/v1/pages/{page_id}",
                       headers=get_notion_headers(), data=json.dumps({"properties": properties}))
    if r.status_code >= 400:
        raise RuntimeError(f"Notion rejected the update for {chartid}: HTTP {r.status_code} — {r.text[:400]}")
    write_code_block(page_id, result.plotly_code)
    print(f"  - Wrote {len(properties)} properties + full code block.")

# --- MAIN WORKFLOW ---
def main(limit: int | None, overwrite: bool, only_chartids: set[str] | None = None, force: bool = False):
    print("Starting batch generation of base code templates...")
    
    # 0. Read the live target schema up front, so a property-name mismatch fails
    #    here rather than after an LLM call has already been paid for.
    valid_props = get_db_properties(VIZ_LIBRARY_DB_ID)
    print(f"  - [schema] target DB exposes {len(valid_props)} properties.")
    missing = [p for p in ("Caveats", "QA notes", "Source code") if p not in valid_props]
    if missing:
        raise SystemExit(f"ERROR: PROD is missing required properties {missing}. Add them as Text (rich_text).")
    if STATUS_AFTER_STAGE_C not in [o["name"] for o in
                                    requests.get(f"https://api.notion.com/v1/databases/{VIZ_LIBRARY_DB_ID}",
                                                 headers=get_notion_headers()).json()["properties"]["Status"]["status"]["options"]]:
        raise SystemExit(f"ERROR: '{STATUS_AFTER_STAGE_C}' is not an option on PROD's Status property.")

    # 1. PROD is both source and target -- one database, no cross-DB join.
    print("  - Fetching pages from the Viz library (PROD)...")
    viz_library_pages = get_all_pages_from_db(VIZ_LIBRARY_DB_ID)
    print(f"  - Found {len(viz_library_pages)} charts.")

    processed = 0
    failed = 0
    refused: list[tuple[str, str]] = []
    for page in viz_library_pages:
        if limit and processed >= limit:
            print(f"\nLimit of {limit} reached. Stopping.")
            break

        try:
            chartid_prop = page["properties"].get(PROPS["chartid"], {}).get("rich_text", [])
            if not chartid_prop:
                print(f"  - SKIP: Page {page.get('id', 'N/A')} is missing a chartid.")
                continue
            chartid = chartid_prop[0]["plain_text"]
            print(f"\nProcessing chart: {chartid}")

            # 2a. Refuse to regenerate anything at or past review, unless forced.
            status = ((page["properties"].get("Status") or {}).get("status") or {}).get("name")
            if status in PROTECTED_STATUSES and not force:
                print(f"  - REFUSED: status is '{status}', at or past review. Its template, SQL "
                      f"and contract are a matched set; regenerating breaks the pairing. "
                      f"Pass --force to override.")
                refused.append((chartid, status))
                continue

            # 2b. Decide whether to skip or process. The row's own Base Code URL is
            #     the marker now -- there is no second database to consult.
            if not overwrite and (page["properties"].get(PROPS["base_code_url"]) or {}).get("url"):
                print("  - SKIP: Base code already present. Use --overwrite to regenerate.")
                continue

            if only_chartids and chartid not in only_chartids:
                continue

            image_url = page["properties"].get(PROPS["asset_url"], {}).get("url")
            if not image_url:
                print("  - SKIP: No Asset URL found for this chart.")
                continue

            # 3. Generate, Upload, and Update
            result = generate_abstract_code(image_url)
            file_key = f"{BASE_CODE_PREFIX}/{chartid}_base_template.py"
            base_code_url = upload_to_storage(file_key, result.plotly_code.encode("utf-8"))
            update_prod_row(page["id"], chartid, base_code_url, result, valid_props)

            print(f"  -> SUCCESS: Generated and saved template for {chartid}.")
            processed += 1

        except Exception as e:
            failed += 1
            page_id = page.get('id', 'N/A')
            print(f"  - ERROR processing page {page_id}: {type(e).__name__}: {e}")
            continue

    if refused:
        print(f"\nREFUSED {len(refused)} chart(s) at or past review (use --force to override):")
        for cid, st in refused:
            print(f"   {cid:14} status={st!r}")

    print(f"\nDone. Processed {processed} charts, {failed} failed, {len(refused)} refused.")
    if failed:
        raise SystemExit(f"{failed} chart(s) failed — exiting non-zero so this cannot read as success.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generates abstract base code templates for all charts in the Viz Library."
    )
    parser.add_argument("--limit", type=int, help="The maximum number of charts to process.")
    parser.add_argument("--overwrite", action="store_true", help="Regenerate templates even for charts that already have one.")
    parser.add_argument("--only", type=str, help="Comma-separated chartids to process, e.g. CHT-6FBD47,CHT-AE2C1E.")
    parser.add_argument("--force", action="store_true",
                        help="Also regenerate rows at or past review status. Breaks the "
                             "template/SQL/contract pairing -- use deliberately.")
    args = parser.parse_args()
    only = {c.strip().upper() for c in args.only.split(",")} if args.only else None
    main(args.limit, args.overwrite, only, args.force)

