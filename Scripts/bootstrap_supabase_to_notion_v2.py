#!/usr/bin/env python3
"""
bootstrap_supabase_to_notion.py (Unified Pipeline Version)

- Scans a Supabase Storage bucket for new chart images.
- Uses Gemini 1.5 Pro for initial metadata analysis.
- Creates a new entry in the SINGLE production Notion DB with 'Status: 1. Intake'.
- Generates and uploads a thumbnail for each new asset.
- Skips images that have already been processed to avoid duplicates.
"""
from __future__ import annotations
import os
import io
import sys
import json
import time
import base64
import argparse
import hashlib
from typing import Dict, Any, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from supabase import create_client, Client
from PIL import Image

# --- CONFIGURATION & CLIENTS ---
load_dotenv(dotenv_path=".env.local")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import supabase_config  # noqa: E402

# Supabase Configuration
SA_URL = os.getenv("SUPABASE_URL")
SA_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SA_BUCKET = os.getenv("SUPABASE_BUCKET", "viz-training-assets")
SA_INPUT_FOLDER = os.getenv("SUPABASE_FOLDER", "raw")
SA_OUTPUT_PREFIX = os.getenv("OUTPUT_FILES_PREFIX", "files")

# --- UNIFIED NOTION CONFIG ---
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DB_ID = os.getenv("NOTION_PROD_DATABASE_ID") # The single source of truth DB
NOTION_BASE_URL = "https://api.notion.com/v1"

# Gemini Configuration
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-1.5-pro-latest")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

STATUS_INTAKE = os.getenv("NOTION_STATUS_INTAKE", "1. Intake")


NOTION_PROPS = {
    "status": "Status",
    "chartid": "chartid",
    "title": "Asset name",
    "asset_url": "Asset URL",
    "viz_type": "Viz type",
    "asset_note": "Asset note",
    "thumbnail": "Thumbnail",
}

if not all([SA_URL, SA_KEY, NOTION_API_KEY, NOTION_DB_ID, GEMINI_API_KEY]):
    raise SystemExit("ERROR: Missing required Supabase, Notion, or Gemini configuration in .env.local")

supa: Optional[Client] = create_client(SA_URL, SA_KEY) if SA_URL and SA_KEY else None

# --- GEMINI AI ANALYSIS ---

GEMINI_PROMPT = """
Analyze the attached chart image. Your task is to extract key metadata.
Return a single, minified JSON object with the following keys and value types:
- "title": string (The main title of the chart. If none, infer a concise title.)
- "viz_type": string (The specific type of chart, e.g., "Vertical Bar Chart", "Line Chart", "Scatter Plot".)
- "description": string (A single, complete sentence describing what the chart shows.)

Example Response:
{"title":"Monthly Subway Entries","viz_type":"Vertical Bar Chart","description":"This chart displays the total number of subway entries per month from December 2024 to September 2025."}
"""

def prepare_image_for_gemini(img_bytes: bytes) -> Tuple[str, str]:
    """Downscales image and converts to JPEG for API reliability."""
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    max_side = 1024
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    
    buffered = io.BytesIO()
    img.save(buffered, format="JPEG")
    return "image/jpeg", base64.b64encode(buffered.getvalue()).decode("utf-8")

def analyze_image_with_gemini(img_bytes: bytes, why: bool = False) -> Optional[Dict[str, str]]:
    """Sends image to Gemini for analysis and returns structured metadata."""
    if why: print("  - Analyzing image with Gemini...")
    
    mime_type, b64_data = prepare_image_for_gemini(img_bytes)
    
    payload = {
        "contents": [{
            "parts": [
                {"text": GEMINI_PROMPT},
                {"inline_data": {"mime_type": mime_type, "data": b64_data}}
            ]
        }],
        "generationConfig": {"response_mime_type": "application/json"}
    }
    
    model_name = GEMINI_MODEL.split('/')[-1]
    url = f"{GEMINI_BASE_URL}/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    # 746 calls in a row will meet a 429 or a 503. Retry those with backoff;
    # anything else is a real answer and is reported, not hidden.
    last = None
    for attempt in range(4):
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=90)
        except requests.RequestException as e:
            last = type(e).__name__
            time.sleep(2 ** attempt)
            continue
        if response.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {response.status_code}"
            time.sleep(min(30, 3 * 2 ** attempt))
            continue
        if response.status_code != 200:
            print(f"  - ERROR: Gemini HTTP {response.status_code}: {response.text[:160]}")
            return None
        try:
            json_text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            metadata = json.loads(json_text)
        except Exception as e:
            print(f"  - ERROR: Gemini returned an unexpected shape: {e}")
            return None
        if why: print(f"  - Gemini analysis successful: {metadata.get('title')}")
        return metadata
    print(f"  - ERROR: Gemini analysis failed after retries ({last})")
    return None

# --- SUPABASE & NOTION HELPERS ---

def storage_list_files(bucket: str, prefix: str, why: bool = False) -> List[Dict[str, Any]]:
    """Lists all files in a given Supabase storage prefix, handling pagination."""
    if not supa:
        print("ERROR: Supabase client not configured.")
        return []

    all_files = []
    offset = 0
    limit = 1000  # Max limit per Supabase API docs, default is 100

    while True:
        try:
            if why: print(f"  - Fetching file list from Supabase... (limit={limit}, offset={offset})")
            
            # Fetch one page of files
            page_of_files = supa.storage.from_(bucket).list(
                prefix,
                {"limit": limit, "offset": offset}
            )
            
            if not page_of_files:
                break  # No more files to fetch

            all_files.extend(page_of_files)

            # If the number of returned files is less than the limit, we're on the last page
            if len(page_of_files) < limit:
                break
            
            # Otherwise, prepare to fetch the next page
            offset += limit
            
        except Exception as e:
            print(f"ERROR: Could not list Supabase files at {bucket}/{prefix}. {e}")
            break # Exit loop on error

    return all_files

def generate_chartid(file_key: str) -> str:
    """Generates a stable, unique chart ID from the file key."""
    hash_object = hashlib.sha256(file_key.encode())
    return f"CHT-{hash_object.hexdigest()[:6].upper()}"

def create_thumbnail(img_bytes: bytes, width: int = 200, why: bool = False) -> Optional[bytes]:
    """Creates a small JPEG thumbnail from image bytes."""
    if why: print("  - Creating thumbnail...")
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        aspect_ratio = img.height / img.width
        new_height = int(width * aspect_ratio)
        img.thumbnail((width, new_height), Image.LANCZOS)
        
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=85)
        return buffered.getvalue()
    except Exception as e:
        print(f"  - ERROR: Could not create thumbnail. {e}")
        return None

def upload_thumbnail_and_get_url(chartid: str, thumb_bytes: bytes, why: bool = False) -> Optional[str]:
    """Uploads thumbnail to Supabase and returns its public URL."""
    if not supa: return None
    thumb_key = f"{SA_OUTPUT_PREFIX}/{chartid}/{chartid}_thumb.jpg"
    if why: print(f"  - Uploading thumbnail to {thumb_key}...")
    try:
        supa.storage.from_(SA_BUCKET).upload(
            thumb_key,
            thumb_bytes,
            {"content-type": "image/jpeg", "upsert": "true"}
        )
        return supa.storage.from_(SA_BUCKET).get_public_url(thumb_key)
    except Exception as e:
        print(f"  - ERROR: Thumbnail upload failed. {e}")
        return None

def check_if_chart_exists(chartid: str) -> Optional[str]:
    """Checks if a page with the given chartid already exists in Notion."""
    url = f"{NOTION_BASE_URL}/databases/{NOTION_DB_ID}/query"
    payload = {"filter": {"property": NOTION_PROPS["chartid"], "rich_text": {"equals": chartid}}}
    headers = {"Authorization": f"Bearer {NOTION_API_KEY}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(f"Notion unreachable while checking {chartid}: {type(e).__name__}") from e
    if response.status_code != 200:
        # Returning None here would read as "no such row" and create a duplicate
        # on every transient Notion error. Stop the run instead; re-running is
        # safe because existing rows are skipped.
        raise RuntimeError(f"Notion refused the duplicate check for {chartid}: "
                           f"HTTP {response.status_code} {response.text[:160]}")
    results = response.json().get("results", [])
    return results[0]["id"] if results else None

def create_notion_page(chartid: str, asset_url: str, thumbnail_url: Optional[str], metadata: Dict[str, str], why: bool = False) -> Optional[str]:
    """Creates a new page in the Notion database with the provided data."""
    if why: print(f"  - Creating new Notion page for {chartid} with status '{STATUS_INTAKE}'...")
    
    url = f"{NOTION_BASE_URL}/pages"
    headers = {"Authorization": f"Bearer {NOTION_API_KEY}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    
    properties = {
        NOTION_PROPS["status"]: {"status": {"name": STATUS_INTAKE}},
        NOTION_PROPS["chartid"]: {"rich_text": [{"text": {"content": chartid}}]},
        NOTION_PROPS["title"]: {"title": [{"text": {"content": metadata.get("title", "Untitled Chart")}}]},
        NOTION_PROPS["asset_url"]: {"url": asset_url},
        NOTION_PROPS["viz_type"]: {"multi_select": [{"name": metadata.get("viz_type", "Unknown")}]},
        NOTION_PROPS["asset_note"]: {"rich_text": [{"text": {"content": metadata.get("description", "No description generated.")}}]},
    }
    
    if thumbnail_url:
        properties[NOTION_PROPS["thumbnail"]] = {"files": [{"type": "external", "name": f"{chartid}_thumb.jpg", "external": {"url": thumbnail_url}}]}
    
    payload = {"parent": {"database_id": NOTION_DB_ID}, "properties": properties}
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(f"Notion unreachable: {type(e).__name__}") from e
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code} {response.text[:200]}")
    if why: print("  - Notion page created successfully.")
    return response.json().get("id")

# --- PREFLIGHT ---
def preflight(why: bool = False) -> List[str]:
    """
    Everything that would make a long run fail late, checked first. A dead API
    key should fail in a second, not after the first image has been downloaded,
    analysed and thumbnailed.
    """
    problems = supabase_config.problems()

    try:
        r = requests.get(f"{GEMINI_BASE_URL}/models?key={GEMINI_API_KEY}&pageSize=200", timeout=30)
        if r.status_code != 200:
            try:
                msg = r.json()["error"]["message"]
            except Exception:
                msg = r.text[:120]
            problems.append(f"Gemini rejected GOOGLE_API_KEY: {msg}")
        else:
            names = {m["name"].split("/")[-1] for m in r.json().get("models", [])
                     if "generateContent" in m.get("supportedGenerationMethods", [])}
            want = GEMINI_MODEL.split("/")[-1]
            if want not in names:
                near = sorted(n for n in names if "gemini" in n)[:8]
                problems.append(f"GEMINI_MODEL={want!r} is not available to this key; "
                                f"available include: {', '.join(near)}")
            else:
                # The listing is not the truth: gemini-2.5-flash was listed and
                # answered 404 "no longer available to new users" on the first
                # real call. Only a real generateContent call proves the model.
                probe = {"contents": [{"parts": [{"text": "Reply with the single word OK."}]}]}
                pr = requests.post(f"{GEMINI_BASE_URL}/models/{want}:generateContent?key={GEMINI_API_KEY}",
                                   json=probe, timeout=60)
                if pr.status_code != 200:
                    try:
                        msg = pr.json()["error"]["message"]
                    except Exception:
                        msg = pr.text[:200]
                    problems.append(f"GEMINI_MODEL={want!r} is listed but refuses calls: "
                                    f"HTTP {pr.status_code} {msg[:220]}")
                elif why:
                    print(f"  - Gemini: key accepted, model {want} answers")
    except requests.RequestException as exc:
        problems.append(f"Gemini unreachable: {type(exc).__name__}")

    try:
        r = requests.get(f"{NOTION_BASE_URL}/databases/{NOTION_DB_ID}", timeout=30,
                         headers={"Authorization": f"Bearer {NOTION_API_KEY}", "Notion-Version": "2022-06-28"})
        if r.status_code != 200:
            problems.append(f"Notion refused the database: HTTP {r.status_code} {r.text[:120]}")
        elif why:
            title = "".join(t.get("plain_text", "") for t in r.json().get("title", []))
            print(f"  - Notion: writing to database {title!r}")
    except requests.RequestException as exc:
        problems.append(f"Notion unreachable: {type(exc).__name__}")
    return problems


# --- MAIN WORKFLOW ---
def main(dry_run: bool, why: bool, limit: Optional[int]) -> int:
    """Returns the number of images that failed. Zero means every image was handled."""
    problems = preflight(why=why)
    if problems:
        print("Refusing to run — preflight found problems:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(f"Scanning Supabase bucket '{SA_BUCKET}' in folder '{SA_INPUT_FOLDER}'...")
    files = storage_list_files(SA_BUCKET, SA_INPUT_FOLDER, why=why)
    image_files = [f for f in files
                   if any(f["name"].lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp"])]
    if not image_files:
        print("No image files found to process.")
        return 0
    print(f"Found {len(image_files)} potential chart images to process.")

    created = skipped = failed = 0
    failures: List[str] = []
    for file_info in image_files:
        if limit and (created + failed) >= limit:
            print(f"Limit of {limit} reached. Stopping.")
            break
        file_key = f"{SA_INPUT_FOLDER}/{file_info['name']}"
        chartid = generate_chartid(file_key)

        if check_if_chart_exists(chartid):
            skipped += 1
            if why: print(f"SKIP {chartid} already in Notion: {file_key}")
            continue
        print(f"\nProcessing {chartid}: {file_key}")

        try:
            img_bytes = supa.storage.from_(SA_BUCKET).download(file_key)
            if not img_bytes:
                raise RuntimeError("download returned no bytes")
        except Exception as e:
            failed += 1
            failures.append(f"{chartid} download: {e}")
            print(f"  - FAIL download: {e}")
            continue

        metadata = analyze_image_with_gemini(img_bytes, why=why)
        if not metadata:
            failed += 1
            failures.append(f"{chartid} analysis failed")
            continue

        thumbnail_url = None
        thumb_bytes = create_thumbnail(img_bytes, why=why)
        if thumb_bytes:
            thumbnail_url = upload_thumbnail_and_get_url(chartid, thumb_bytes, why=why)
        asset_url = supa.storage.from_(SA_BUCKET).get_public_url(file_key)

        if dry_run:
            print(f"  - DRY RUN: would create {chartid} titled {metadata.get('title')!r}"
                  f"{' with thumbnail' if thumbnail_url else ''}")
            created += 1
        else:
            try:
                create_notion_page(chartid, asset_url, thumbnail_url, metadata, why=why)
                created += 1
            except Exception as e:
                failed += 1
                failures.append(f"{chartid} notion: {e}")
                print(f"  - FAIL notion: {e}")
        time.sleep(1)  # be respectful to APIs

    print(f"\nDone. created={created} skipped_existing={skipped} failed={failed}")
    for line in failures[:20]:
        print(f"  ! {line}")
    if len(failures) > 20:
        print(f"  … and {len(failures) - 20} more")
    return failed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bootstrap Notion DB with chart images from Supabase, enriched with AI metadata.")
    parser.add_argument("--dry-run", action="store_true", help="Analyse and thumbnail, but write nothing to Notion.")
    parser.add_argument("--why", action="store_true", help="Enable verbose logging.")
    parser.add_argument("--limit", type=int, help="Maximum number of new images to process.")
    parser.add_argument("--check", action="store_true", help="Run the preflight only and exit.")
    args = parser.parse_args()

    if args.check:
        found = preflight(why=True)
        for p in found:
            print(f"  - {p}")
        print("Preflight: " + ("FAILED" if found else "OK"))
        sys.exit(1 if found else 0)
    sys.exit(1 if main(dry_run=args.dry_run, why=args.why, limit=args.limit) else 0)
