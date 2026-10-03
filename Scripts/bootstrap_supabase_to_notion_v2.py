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
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=90)
        response.raise_for_status()
        
        result = response.json()
        json_text = result["candidates"][0]["content"]["parts"][0]["text"]
        
        metadata = json.loads(json_text)
        if why: print(f"  - Gemini analysis successful: {metadata.get('title')}")
        return metadata
    except Exception as e:
        print(f"  - ERROR: Gemini analysis failed. {e}")
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
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        results = response.json().get("results", [])
        return results[0]["id"] if results else None
    except Exception as e:
        print(f"  - ERROR: Could not query Notion to check for existing chart. {e}")
        return None

def create_notion_page(chartid: str, asset_url: str, thumbnail_url: Optional[str], metadata: Dict[str, str], why: bool = False) -> None:
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
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        if why: print("  - Notion page created successfully.")
    except Exception as e:
        print(f"  - ERROR: Failed to create Notion page. Response: {e.response.text if hasattr(e, 'response') else e}")

# --- MAIN WORKFLOW ---
def main(dry_run: bool, why: bool, limit: Optional[int]):
    """Main function to execute the bootstrap process."""
    if not supa:
        print("ERROR: Supabase client is not initialized. Check your .env.local file.")
        return

    print(f"Scanning Supabase bucket '{SA_BUCKET}' in folder '{SA_INPUT_FOLDER}'...")
    
    files = storage_list_files(SA_BUCKET, SA_INPUT_FOLDER, why=why)
    image_files = [f for f in files if any(f["name"].lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp"])]
    
    if not image_files:
        print("No new image files found to process.")
        return

    print(f"Found {len(image_files)} potential chart images to process.")
    
    processed = 0
    for file_info in image_files:
        if limit and processed >= limit:
            print(f"Limit of {limit} reached. Stopping.")
            break
            
        file_key = f"{SA_INPUT_FOLDER}/{file_info['name']}"
        print(f"\nProcessing file: {file_key}")
        
        chartid = generate_chartid(file_key)
        
        if check_if_chart_exists(chartid):
            if why: print(f"  - SKIP: Chart ID {chartid} already exists in Notion.")
            continue
            
        # Download image from Supabase
        try:
            img_bytes = supa.storage.from_(SA_BUCKET).download(file_key)
            if not img_bytes:
                if why: print("  - SKIP: Failed to download image from Supabase.")
                continue
        except Exception as e:
            if why: print(f"  - SKIP: Error downloading image: {e}")
            continue

        # Get AI-powered metadata
        metadata = analyze_image_with_gemini(img_bytes, why=why)
        if not metadata:
            if why: print("  - SKIP: Could not generate metadata from Gemini.")
            continue

        # Create and upload thumbnail
        thumbnail_url = None
        thumb_bytes = create_thumbnail(img_bytes, why=why)
        if thumb_bytes:
            thumbnail_url = upload_thumbnail_and_get_url(chartid, thumb_bytes, why=why)

        # Get public URL for the original image
        asset_url = supa.storage.from_(SA_BUCKET).get_public_url(file_key)
        
        # Create Notion page
        if not dry_run:
            create_notion_page(chartid, asset_url, thumbnail_url, metadata, why=why)
        else:
            print(f"  - DRY RUN: Would create Notion page for {chartid} with title: '{metadata.get('title')}'")
            if thumbnail_url:
                print(f"  - DRY RUN: Would include thumbnail URL.")

        processed += 1
        time.sleep(1) # Be respectful to APIs

    print(f"\nDone. Processed {processed} new images.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap Notion DB with chart images from Supabase, enriched with AI metadata.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate the process without writing to Notion.")
    parser.add_argument("--why", action="store_true", help="Enable verbose logging.")
    parser.add_argument("--limit", type=int, help="Maximum number of new images to process.")
    args = parser.parse_args()
    
    main(dry_run=args.dry_run, why=args.why, limit=args.limit)

