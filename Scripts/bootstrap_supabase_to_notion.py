#!/usr/bin/env python3
import os, io, re, argparse, hashlib, pathlib, secrets
from typing import Dict, Any, Optional, Iterable
from dotenv import load_dotenv
from notion_client import Client as Notion
from supabase import create_client, Client as Supa
from PIL import Image, ImageOps, ImageEnhance, ImageChops

load_dotenv(dotenv_path=".env.local")

# ---------- ENV ----------
NOTION_API_KEY       = os.getenv("NOTION_API_KEY")
DATABASE_ID          = os.getenv("NOTION_DATABASE_ID")

P_TITLE              = os.getenv("NOTION_PROP_TITLE", "Name")
P_CHARTID            = os.getenv("NOTION_PROP_CHARTID", "chartid")
P_ASSET              = os.getenv("NOTION_PROP_ASSET_URL", "Asset URL")
P_THUMB              = os.getenv("NOTION_PROP_THUMB_URL", "Thumbnail")

SUPABASE_URL         = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # preferred for private buckets
SUPABASE_ANON_KEY    = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_BUCKET      = os.getenv("SUPABASE_BUCKET", "viz-training-assets")
SUPABASE_FOLDER      = (os.getenv("SUPABASE_FOLDER") or "charts").strip("/")
SUPABASE_PUBLIC_BASE = os.getenv("SUPABASE_PUBLIC_BASE")

THUMB_WIDTH          = int(os.getenv("THUMB_WIDTH") or "800")
OVERWRITE            = (os.getenv("OVERWRITE", "false").lower() == "true")

if not (NOTION_API_KEY and DATABASE_ID and SUPABASE_URL and (SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY)):
    raise SystemExit("Missing required env vars. Check NOTION_API_KEY, NOTION_DATABASE_ID, SUPABASE_URL, SUPABASE_*_KEY.")

# ---------- Clients ----------
notion: Notion = Notion(auth=NOTION_API_KEY)
SUPABASE_KEY = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY
supa: Supa = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- Helpers ----------
IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
CHARTID_RE = re.compile(r"CHT-[0-9A-F]{6}", re.IGNORECASE)

def new_chartid() -> str:
    return "CHT-" + secrets.token_hex(3).upper()

def title_from_filename(name: str) -> str:
    stem = pathlib.Path(name).stem
    return re.sub(r"[_\-]+", " ", stem).strip() or "Untitled"

def supa_upload_png(key: str, data: bytes, upsert: bool = True):
    """
    Version-safe Storage upload:
    - Prefer newer signature upload(path, file, file_options=..., upsert=True)
    - Fallback to older signature where upsert must be inside file_options,
      and all header-like values must be strings.
    """
    try:
        # Newer SDKs accept `upsert` as a top-level kwarg
        return supa.storage.from_(SUPABASE_BUCKET).upload(
            path=key,
            file=data,
            file_options={"contentType": "image/png"},
            upsert=upsert,  # bool OK here on newer SDKs
        )
    except TypeError:
        # Older SDKs – put upsert into file_options as a STRING, not bool
        return supa.storage.from_(SUPABASE_BUCKET).upload(
            path=key,
            file=data,
            file_options={
                "contentType": "image/png",
                "upsert": "true" if upsert else "false",
                # Optional: "cacheControl": "3600"
            },
        )


def supa_public_url(key: str) -> str:
    """
    Resolve a stable public URL for a Supabase storage object.
    Priority:
      1. Use SUPABASE_PUBLIC_BASE if explicitly set
      2. Fall back to get_public_url()
      3. Fall back to signed URL (1 year expiry)
      4. Fallback: construct public URL manually
    """

    # 1. Explicit base override
    if SUPABASE_PUBLIC_BASE:
        return f"{SUPABASE_PUBLIC_BASE.rstrip('/')}/{key}".rstrip("?")

    # 2. Try get_public_url()
    try:
        url = supa.storage.from_(SUPABASE_BUCKET).get_public_url(key)
        if isinstance(url, str):
            return url.rstrip("?")
        if isinstance(url, dict):
            for k in ("publicUrl", "public_url", "signedUrl", "signedURL"):
                if k in url and url[k]:
                    return url[k].rstrip("?")
    except Exception:
        pass

    # 3. Try signed URL (1 year)
    try:
        signed = supa.storage.from_(SUPABASE_BUCKET).create_signed_url(key, expires_in=60*60*24*365)
        if isinstance(signed, str):
            return signed.rstrip("?")
        if isinstance(signed, dict):
            for k in ("signedUrl", "signedURL"):
                if k in signed and signed[k]:
                    return signed[k].rstrip("?")
    except Exception:
        pass

    # 4. Last resort: construct manually
    return f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{SUPABASE_BUCKET}/{key}".rstrip("?")



def storage_list(path: str):
    # version-safe: do not pass kwargs like limit/sort_by (older SDKs reject)
    return supa.storage.from_(SUPABASE_BUCKET).list(path or "")

def list_supabase_recursive(prefix: str):
    prefix = (prefix or "").strip("/")
    queue = [prefix] if prefix else [""]
    while queue:
        base = queue.pop(0)
        entries = storage_list(base)
        for e in entries:
            name = (e.get("name") or "").strip("/")
            is_folder = not (e.get("id") or e.get("created_at") or e.get("metadata"))
            if is_folder:
                sub = f"{base}/{name}".strip("/")
                queue.append(sub)
            else:
                e["_prefix"] = base
                yield e

def to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def normalize_source(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img.convert("RGB"))
    bg = Image.new(img.mode, img.size, (255,255,255))
    diff = ImageChops.difference(img, bg)
    bbox = diff.getbbox()
    if bbox: img = img.crop(bbox)
    img = ImageEnhance.Contrast(img).enhance(1.08)
    img = ImageEnhance.Sharpness(img).enhance(1.05)
    return img

def make_thumb(img: Image.Image, width: int) -> Image.Image:
    if img.width <= width:
        return img.copy()
    h = int(img.height * (width / img.width))
    return img.resize((width, h), Image.LANCZOS)

def sha8(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:8]

def discover_schema():
    db = notion.databases.retrieve(DATABASE_ID)
    props = db["properties"]

    title_name = os.getenv("NOTION_PROP_TITLE")
    if not title_name:
        # auto-detect title prop if not provided
        title_name = next((k for k, v in props.items() if v["type"] == "title"), None)

    def p(name): return props.get(name)

    return {
        "raw": props,
        "title": title_name,
        "title_ok": bool(title_name and p(title_name) and p(title_name)["type"] == "title"),
        "chartid_ok": bool(p(P_CHARTID) and p(P_CHARTID)["type"] == "rich_text"),
        "asset_type": p(P_ASSET)["type"] if p(P_ASSET) else None,   # "url" or "files"
        "thumb_type": p(P_THUMB)["type"] if p(P_THUMB) else None,   # "url" or "files"
    }


def find_page_by_chartid(chartid: str) -> Optional[Dict[str, Any]]:
    try:
        resp = notion.databases.query(
            database_id=DATABASE_ID,
            filter={"property": P_CHARTID, "rich_text": {"equals": chartid}},
            page_size=1
        )
        return resp["results"][0] if resp["results"] else None
    except Exception:
        return None

def upsert_row(title_prop: str, title: str, chartid: str, asset_url: str, thumb_url: str, dry_run: bool, schema=None) -> str:
    schema = schema or discover_schema()
    propspec = {}

    # Title
    propspec[title_prop] = {"title": [{"text": {"content": title}}]}

    # chartid (rich_text)
    propspec[P_CHARTID] = {"rich_text": [{"text": {"content": chartid}}]}

    # Asset: URL vs Files
    if schema["asset_type"] == "url":
        propspec[P_ASSET] = {"url": asset_url}
    elif schema["asset_type"] == "files":
        propspec[P_ASSET] = {
            "files": [
                {"name": os.path.basename(asset_url) or "asset",
                 "external": {"url": asset_url}}
            ]
        }

    # Thumbnail: URL vs Files
    if schema["thumb_type"] == "url":
        propspec[P_THUMB] = {"url": thumb_url}
    elif schema["thumb_type"] == "files":
        propspec[P_THUMB] = {
            "files": [
                {"name": os.path.basename(thumb_url) or "thumb",
                 "external": {"url": thumb_url}}
            ]
        }

    existing = find_page_by_chartid(chartid)
    if dry_run:
        print(f"[DRY RUN] {'Update' if existing else 'Create'} row → {chartid} | {title}")
        return existing["id"] if existing else "(dry-run-new-page)"

    if existing:
        notion.pages.update(page_id=existing["id"], properties=propspec)
        return existing["id"]
    page = notion.pages.create(parent={"database_id": DATABASE_ID}, properties=propspec)
    return page["id"]


# ---------- Main ----------
def main(dry_run: bool, why: bool, limit: Optional[int]):
    schema = discover_schema()
    if not schema["title_ok"]:
        raise SystemExit(f"Notion DB title property mismatch. Detected title='{schema['title']}'. "
                        f"Set NOTION_PROP_TITLE to your exact title property (e.g. 'Asset name').")
    if not schema["chartid_ok"]:
        raise SystemExit(f"Notion DB must have rich_text '{P_CHARTID}'.")

    # preflight storage listing (clear error if key/policy mismatch)
    try:
        _probe = storage_list(SUPABASE_FOLDER)
        print(f"OK: listed {len(_probe)} entries under {SUPABASE_BUCKET}/{SUPABASE_FOLDER}")
    except Exception as e:
        raise SystemExit(
            "Failed to list Supabase storage.\n"
            "• Ensure SUPABASE_URL and your key are from the SAME project\n"
            "• Use SUPABASE_SERVICE_ROLE_KEY (private) OR make bucket public OR add RLS select policy\n"
            f"Details: {e}"
        )

    print(f"Scanning Supabase recursively: bucket='{SUPABASE_BUCKET}', folder='{SUPABASE_FOLDER or '/'}'")
    processed = 0

    for obj in list_supabase_recursive(SUPABASE_FOLDER):
        name = obj["name"]
        ext = pathlib.Path(name).suffix.lower()
        if ext not in IMG_EXTS:
            continue

        key = f"{obj['_prefix']}/{name}".strip("/")
        asset_url = supa_public_url(key)

        # download the image to create a thumbnail
        try:
            data = supa.storage.from_(SUPABASE_BUCKET).download(key)
        except Exception as e:
            if why: print(f"SKIP {key} — cannot download: {e}")
            continue

        try:
            img = Image.open(io.BytesIO(data))
        except Exception as e:
            if why: print(f"SKIP {key} — open failed: {e}")
            continue

        src_img = normalize_source(img)
        thb_img = make_thumb(src_img, THUMB_WIDTH)
        thb_bytes = to_png_bytes(thb_img)
        thash = sha8(thb_bytes)

        # chartid: reuse from filename if present, else generate
        m = CHARTID_RE.search(name.upper())
        chartid = m.group(0).upper() if m else new_chartid()
        title = title_from_filename(name)

        # store thumb under {folder}/{chartid}/
        chart_dir = f"{SUPABASE_FOLDER}/{chartid}".strip("/")
        thumb_key = f"{chart_dir}/{chartid}_thumb_{thash}.png"
        thumb_url = supa_public_url(thumb_key)

        if dry_run:
            print(f"[DRY RUN] Would upload thumb {thumb_key}")
        else:
            supa_upload_png(thumb_key, thb_bytes, upsert=True)

        # if page exists and both URLs present and not OVERWRITE → skip update
        existing = find_page_by_chartid(chartid)
        if existing and not OVERWRITE:
            props = existing["properties"]
            if props.get(P_ASSET, {}).get("url") and props.get(P_THUMB, {}).get("url"):
                if why: print(f"SKIP {chartid} — Notion already has Asset+Thumb (set OVERWRITE=true to replace)")
                processed += 1
                if limit and processed >= limit: break
                continue

        upsert_row(schema["title"], title, chartid, asset_url, thumb_url, dry_run=dry_run)
        if why:
            print(f"{'[DRY RUN] ' if dry_run else ''}Linked {chartid} → {asset_url}")

        processed += 1
        if limit and processed >= limit:
            break

    print(f"Done. Processed: {processed}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Bootstrap a Notion DB from a Supabase folder of images.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--why", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    main(dry_run=args.dry_run, why=args.why, limit=args.limit)
