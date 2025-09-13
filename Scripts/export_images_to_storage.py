#!/usr/bin/env python3
import os, io, re, json, hashlib, argparse, time
from typing import Optional, Dict, Any
from dataclasses import dataclass
from dotenv import load_dotenv
from notion_client import Client as Notion
from tenacity import retry, wait_exponential, stop_after_attempt
import requests
from PIL import Image, ImageOps, ImageEnhance, ImageChops

# ====== ENV ======
load_dotenv(dotenv_path=".env.local")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
SOURCE_DB_ID   = os.getenv("NOTION_DATABASE_ID")
IMAGE_PROP     = os.getenv("NOTION_IMAGE_PROP") or "Thumbnail"
CHARTID_PROP   = os.getenv("NOTION_CHARTID_PROP") or "chartid"
ASSET_URL_PROP = os.getenv("NOTION_ASSET_URL_PROP") or "Asset URL"
FALLBACK_PROP  = os.getenv("NOTION_IMAGE_FALLBACK_PROP")  # optional

STORAGE_PROVIDER = (os.getenv("STORAGE_PROVIDER") or "supabase").lower()

# Supabase
SUPABASE_URL       = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY  = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
SUPABASE_BUCKET    = "viz-training-assets"
# SUPABASE_PUBLIC_BASE = os.getenv("SUPABASE_PUBLIC_BASE")  # optional CDN base

# S3
# AWS_REGION = os.getenv("AWS_REGION")
# S3_BUCKET  = os.getenv("S3_BUCKET")
# S3_PUBLIC_BASE = os.getenv("S3_PUBLIC_BASE")  # optional CloudFront

# Fetch caps
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES") or "8000000")
CONNECT_TIMEOUT = 5
READ_TIMEOUT    = 10
TOTAL_BUDGET    = 15  # seconds per image

UA = "DataViz-ImageExporter/1.0"

if not (NOTION_API_KEY and SOURCE_DB_ID):
    raise SystemExit("Missing NOTION_API_KEY or NOTION_SOURCE_DB_ID in env.")

notion = Notion(auth=NOTION_API_KEY)

# ====== STORAGE DRIVERS ======
class StorageDriver:
    def upload_png(self, key: str, data: bytes) -> str:
        raise NotImplementedError

class SupabaseDriver(StorageDriver):
    def __init__(self):
        from supabase import create_client
        if not (SUPABASE_URL and SUPABASE_ANON_KEY and SUPABASE_BUCKET):
            raise SystemExit("Supabase env missing.")
        self.client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        self.bucket = SUPABASE_BUCKET

    def upload_png(self, key: str, data: bytes) -> str:
        # upsert behaves like overwrite
        self.client.storage.from_(self.bucket).upload(path=key, file=data, file_options={"contentType":"image/png", "upsert": True})
        if SUPABASE_PUBLIC_BASE:
            return f"{SUPABASE_PUBLIC_BASE.rstrip('/')}/{key}"
        # get_public_url works for public buckets
        return self.client.storage.from_(self.bucket).get_public_url(key).get("publicUrl")

class S3Driver(StorageDriver):
    def __init__(self):
        import boto3
        if not (AWS_REGION and S3_BUCKET):
            raise SystemExit("S3 env missing.")
        self.s3 = boto3.client("s3", region_name=AWS_REGION)
        self.bucket = S3_BUCKET

    def upload_png(self, key: str, data: bytes) -> str:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType="image/png", ACL="public-read")
        if S3_PUBLIC_BASE:
            return f"{S3_PUBLIC_BASE.rstrip('/')}/{key}"
        return f"https://{self.bucket}.s3.{AWS_REGION}.amazonaws.com/{key}"

def get_driver() -> StorageDriver:
    if STORAGE_PROVIDER == "supabase":
        return SupabaseDriver()
    if STORAGE_PROVIDER == "s3":
        return S3Driver()
    raise SystemExit("STORAGE_PROVIDER must be 'supabase' or 's3'.")

# ====== NOTION HELPERS ======
def read_rich_text(prop: Dict[str,Any]) -> str:
    if not prop or "rich_text" not in prop: return ""
    return "".join((r.get("text", {}) or {}).get("content","") for r in prop["rich_text"]).strip()

def read_title(prop: Dict[str,Any]) -> str:
    if not prop or "title" not in prop: return ""
    return "".join((r.get("text", {}) or {}).get("content","") for r in prop["title"]).strip()

def is_chartid_empty(prop: Dict[str,Any]) -> bool:
    if not prop or "rich_text" not in prop: return True
    return len(read_rich_text(prop)) == 0

def get_first_image_url(prop: Dict[str,Any]) -> Optional[str]:
    if not prop: return None
    if "files" in prop:
        for f in prop["files"]:
            if f.get("type") == "external":
                return f["external"]["url"]
            if f.get("type") == "file":
                return f["file"]["url"]
    if "url" in prop and prop["url"]:
        return prop["url"]
    # rich_text URLs
    if "rich_text" in prop:
        for block in prop["rich_text"]:
            href = block.get("href")
            if href and href.startswith(("http://","https://")):
                return href
            txt = ((block.get("text") or {}).get("content") or "")
            m = re.search(r'(https?://\S+)', txt)
            if m: return m.group(1)
    return None

def page_cover_url(page_obj: dict) -> Optional[str]:
    cover = page_obj.get("cover")
    if not cover: return None
    if cover.get("type") == "external":
        return cover["external"].get("url")
    if cover.get("type") == "file":
        return cover["file"].get("url")
    return None

# ====== FETCH & NORMALIZE ======
def _head_ok(url: str) -> bool:
    try:
        h = requests.head(url, allow_redirects=True, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), headers={"User-Agent": UA})
        ctype = h.headers.get("Content-Type","").lower()
        if "image" not in ctype:
            return False
        length = h.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > MAX_IMAGE_BYTES:
            return False
        return True
    except Exception:
        return True  # some servers disallow HEAD; try GET
def _fetch_bytes(url: str) -> Optional[bytes]:
    if not _head_ok(url):
        return None
    try:
        with requests.get(url, stream=True, allow_redirects=True, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), headers={"User-Agent": UA}) as r:
            r.raise_for_status()
            buf = io.BytesIO()
            total = 0
            start = time.time()
            for chunk in r.iter_content(64*1024):
                if not chunk: continue
                buf.write(chunk)
                total += len(chunk)
                if total > MAX_IMAGE_BYTES or (time.time()-start) > TOTAL_BUDGET:
                    return None
            return buf.getvalue()
    except Exception:
        return None

def normalize_png(data: bytes) -> Optional[bytes]:
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img = ImageOps.exif_transpose(img)
        # trim white border
        bg = Image.new(img.mode, img.size, (255,255,255))
        diff = ImageChops.difference(img, bg)
        bbox = diff.getbbox()
        if bbox: img = img.crop(bbox)
        # mild enhance
        img = ImageEnhance.Contrast(img).enhance(1.12)
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return None

def fetch_normalized_png(url: str) -> Optional[bytes]:
    data = _fetch_bytes(url)
    if not data:
        # quick retry
        data = _fetch_bytes(url)
        if not data: return None
    return normalize_png(data)

# ====== WORKFLOW ======
def pick_image_url(page: dict) -> Optional[str]:
    props = page["properties"]
    # 1) primary
    img = get_first_image_url(props.get(IMAGE_PROP))
    if img: return img
    # 2) fallback column
    if FALLBACK_PROP and FALLBACK_PROP in props:
        img = get_first_image_url(props.get(FALLBACK_PROP))
        if img: return img
    # 3) page cover
    try:
        live = notion.pages.retrieve(page_id=page["id"])
        img = page_cover_url(live)
        if img: return img
    except Exception:
        pass
    # 4) any URL in any property
    for val in props.values():
        img = get_first_image_url(val)
        if img: return img
    return None

def sha8(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:8]

def storage_key(chartid: str, png_bytes: bytes) -> str:
    return f"charts/{chartid}/{chartid}_source_{sha8(png_bytes)}.png"

def notion_update_asset_url(page_id: str, url: str):
    notion.pages.update(page_id=page_id, properties={ASSET_URL_PROP: {"url": url} if ASSET_URL_PROP else {"rich_text":[{"text":{"content":url}}]}})

def iterate_source_pages(limit=None):
    count, cursor = 0, None
    while True:
        resp = notion.databases.query(
            database_id=SOURCE_DB_ID,
            page_size=100,
            filter={"property": CHARTID_PROP, "rich_text": {"is_not_empty": True}}
        )
        for p in resp["results"]:
            if limit and count >= limit: return
            yield p
            count += 1
        if not resp.get("has_more"): break
        cursor = resp.get("next_cursor")

# ====== MAIN ======
def main(limit: Optional[int], dry_run: bool, why: bool, force: bool):
    driver = get_driver()
    processed = 0
    for page in iterate_source_pages(limit=limit):
        props = page["properties"]
        chartid = read_rich_text(props.get(CHARTID_PROP))
        title   = read_title(next(v for k,v in props.items() if v.get("type")=="title"))
        existing_url = props.get(ASSET_URL_PROP, {}).get("url") if ASSET_URL_PROP in props else ""

        if existing_url and not force:
            if why: print(f"SKIP {chartid} — already has Asset URL")
            continue

        img_url = pick_image_url(page)
        if not img_url:
            if why: print(f"SKIP {chartid} — no image found (Thumbnail/fallback/cover empty)")
            continue

        if dry_run:
            print(f"[DRY RUN] Would fetch & upload for {chartid}: {img_url}")
            processed += 1
            continue

        png = fetch_normalized_png(img_url)
        if not png:
            if why: print(f"SKIP {chartid} — fetch/normalize failed: {img_url}")
            continue

        key = storage_key(chartid, png)
        public_url = driver.upload_png(key, png)

        notion_update_asset_url(page["id"], public_url)
        print(f"Uploaded {chartid} → {public_url}")
        processed += 1

    print(f"Done. Uploaded: {processed}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Export Notion chart images to Supabase/S3 and write back permanent URL.")
    ap.add_argument("--limit", type=int, default=None, help="Max rows")
    ap.add_argument("--dry-run", action="store_true", help="Don’t download/upload, just print actions")
    ap.add_argument("--why", action="store_true", help="Verbose skip reasons")
    ap.add_argument("--force", action="store_true", help="Overwrite Asset URL even if already present")
    args = ap.parse_args()
    main(limit=args.limit, dry_run=args.dry_run, why=args.why, force=args.force)
