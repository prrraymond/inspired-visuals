#!/usr/bin/env python3
"""
Annotate Notion chart rows using Gemini 2.5 Pro.

Environment (.env):
  NOTION_API_KEY=
  NOTION_DATABASE_ID=

  # Property names (match your DB exactly)
  NOTION_PROP_TITLE=Asset name
  NOTION_PROP_CHARTID=chartid
  NOTION_PROP_ASSET_URL=Asset URL
  NOTION_PROP_THUMB_URL=Thumbnail
  NOTION_PROP_VIZ_TYPE=Viz type
  NOTION_PROP_STANDARD=Standard
  NOTION_PROP_SUBPLOT=Subplot
  NOTION_PROP_TIMESERIES=Time Series
  NOTION_PROP_MULTICOLOR=Multi-color series
  NOTION_PROP_ASSET_NOTE=Asset note
  NOTION_PROP_CUSTOMIZATION=Customization

  # Gemini
  GOOGLE_API_KEY=
  GEMINI_MODEL=gemini-2.5-pro
  GEMINI_TIMEOUT=45
"""

import os, re, io, json, base64, argparse, requests
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
from notion_client import Client as Notion
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import google.generativeai as genai

load_dotenv(dotenv_path=".env.local")

# ---------- ENV ----------
NOTION_API_KEY   = os.getenv("NOTION_API_KEY")
DATABASE_ID      = os.getenv("NOTION_DATABASE_ID")

P_TITLE          = os.getenv("NOTION_PROP_TITLE", "Asset name")               # title
P_CHARTID        = os.getenv("NOTION_PROP_CHARTID", "chartid")                # rich_text
P_ASSET          = os.getenv("NOTION_PROP_ASSET_URL", "Asset URL")            # url
P_THUMB          = os.getenv("NOTION_PROP_THUMB_URL", "Thumbnail")            # files

P_VIZ_TYPE       = os.getenv("NOTION_PROP_VIZ_TYPE", "Viz type")              # multi_select
P_STANDARD       = os.getenv("NOTION_PROP_STANDARD", "Standard")              # checkbox
P_SUBPLOT        = os.getenv("NOTION_PROP_SUBPLOT", "Subplot")                # checkbox
P_TIMESERIES     = os.getenv("NOTION_PROP_TIMESERIES", "Time Series")         # checkbox
P_MULTICOLOR     = os.getenv("NOTION_PROP_MULTICOLOR", "Multi-color series")  # checkbox
P_ASSET_NOTE     = os.getenv("NOTION_PROP_ASSET_NOTE", "Asset note")          # rich_text
P_CUSTOMIZATION  = os.getenv("NOTION_PROP_CUSTOMIZATION", "Customization")     # rich_text

GOOGLE_API_KEY   = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL     = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
GEMINI_TIMEOUT   = int(os.getenv("GEMINI_TIMEOUT") or "45")

if not (NOTION_API_KEY and DATABASE_ID and GOOGLE_API_KEY):
    raise SystemExit("Missing env: NOTION_API_KEY, NOTION_DATABASE_ID, or GOOGLE_API_KEY")

notion = Notion(auth=NOTION_API_KEY)
genai.configure(api_key=GOOGLE_API_KEY)

from urllib.parse import urlparse, unquote

from supabase import create_client

SUPABASE_URL   = os.getenv("SUPABASE_URL")               # e.g. https://xxxx.supabase.co
SUPABASE_KEY   = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
SUPABASE_BUCKET= os.getenv("SUPABASE_BUCKET", "viz-training-assets")

supa = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

def _sb_bucket_key_from_object_url(url: str):
    """
    Accepts:
      https://<proj>.supabase.co/storage/v1/object/public/<bucket>/<key...>
      https://<proj>.supabase.co/storage/v1/object/sign/<bucket>/<key...>?...
    Returns (bucket, key) or (None, None)
    """
    try:
        p = urlparse(url)
        parts = [x for x in p.path.split("/") if x]
        i = parts.index("object")
        # .../object/<scope>/<bucket>/<key...>
        bucket = parts[i+2]
        key = "/".join(parts[i+3:])
        return bucket, unquote(key)
    except Exception:
        return None, None
    
if SUPABASE_URL and SUPABASE_KEY:
    supa = create_client(SUPABASE_URL, SUPABASE_KEY)


# ---------- helpers ----------
def read_rich_text(prop: Dict[str, Any]) -> str:
    if not prop or "rich_text" not in prop: return ""
    return "".join((r.get("text", {}) or {}).get("content","") for r in prop["rich_text"]).strip()

def read_checkbox(prop: Dict[str, Any]) -> Optional[bool]:
    if not prop or "checkbox" not in prop: return None
    return bool(prop["checkbox"])

def read_multi_select_names(prop: Dict[str, Any]) -> List[str]:
    if not prop or "multi_select" not in prop: return []
    return [opt.get("name","") for opt in prop["multi_select"] if opt.get("name")]

def get_first_url(prop: Dict[str, Any]) -> Optional[str]:
    """Try to extract a usable URL from url/files/rich_text fields."""
    if not prop: return None
    # direct URL
    if "url" in prop and prop["url"]:
        return prop["url"]
    # files (external or Notion file link)
    if "files" in prop:
        for f in prop["files"]:
            if f.get("type") == "external":
                u = f["external"].get("url")
                if u: return u
            if f.get("type") == "file":
                u = f["file"].get("url")
                if u: return u
    # rich_text fallback
    if "rich_text" in prop:
        for block in prop["rich_text"]:
            href = block.get("href")
            if href and href.startswith(("http://","https://")):
                return href
            txt = ((block.get("text") or {}).get("content") or "")
            m = re.search(r'(https?://\S+)', txt)
            if m: return m.group(1)
    return None

def supabase_signed_url_for(url: str, expires=3600) -> str | None:
    """
    Enhanced signed URL generation with better error handling
    """
    if not (supa and url and ".supabase.co" in url and "/storage/v1/object/" in url):
        print("Skipping signed URL: missing client or not a Supabase URL")
        return None
        
    b, k = _sb_bucket_key_from_object_url(url)
    if not b or not k:
        print(f"Failed to parse bucket/key from URL: {url}")
        return None
        
    bucket_use = SUPABASE_BUCKET or b
    print(f"Generating signed URL for bucket='{bucket_use}', key='{k}'")
    
    try:
        res = supa.storage.from_(bucket_use).create_signed_url(k, expires_in=expires)
        print(f"Supabase response type: {type(res)}, content: {res}")
        
        if isinstance(res, str):
            return res
        if isinstance(res, dict):
            return res.get("signedUrl") or res.get("signedURL")
        
        print(f"Unexpected response format: {res}")
        return None
        
    except Exception as e:
        print(f"Error generating signed URL: {e}")
        return None

def supabase_signed_from_public(url: str, expires=60*60) -> Optional[str]:
    """
    If url looks like a Supabase /object/public/ URL, derive the storage key and mint a signed URL.
    Works even if the bucket is private.
    """
    if not (supa and url and ".supabase.co" in url and "/storage/v1/object/" in url):
        return None
    try:
        u = urlparse(url)
        # path like: /storage/v1/object/public/<bucket>/<key...>
        parts = [p for p in u.path.split("/") if p]
        # find "object" index, then expect ["storage","v1","object","public",bucket, *key_parts]
        if "object" not in parts:
            return None
        i = parts.index("object")
        # allow either "public" or "sign" segment after "object"
        if i+1 >= len(parts):
            return None
        scope = parts[i+1]  # "public" or "sign"
        # bucket at i+2, then key after
        if i+2 >= len(parts):
            return None
        bucket = parts[i+2]
        key_parts = parts[i+3:]
        key = "/".join(key_parts)
        key = unquote(key)
        # Prebyr env bucket if explicitly set
        bucket_use = SUPABASE_BUCKET or bucket
        signed = supa.storage.from_(bucket_use).create_signed_url(key, expires_in=expires)
        if isinstance(signed, str):
            return signed
        if isinstance(signed, dict):
            return signed.get("signedUrl") or signed.get("signedURL")
    except Exception:
        return None
    return None

def fetch_bytes(img_url: str, timeout: int) -> bytes:
    """
    Enhanced fetch_bytes with better error handling and debugging
    """
    print(f"Attempting to fetch: {img_url}")
    
    # If this looks like a Supabase storage path, try signed URL first
    if ".supabase.co" in img_url and "/storage/v1/object/" in img_url:
        print("Detected Supabase URL, attempting signed URL...")
        alt = supabase_signed_url_for(img_url, expires=3600)
        if alt:
            print(f"Generated signed URL: {alt[:100]}...")
            try:
                r = requests.get(alt, timeout=timeout)
                r.raise_for_status()
                print("✓ Signed URL fetch successful")
                return r.content
            except Exception as e:
                print(f"✗ Signed URL fetch failed: {e}")
        else:
            print("✗ Failed to generate signed URL")
    
    # Try the original URL
    print("Attempting direct URL access...")
    try:
        r = requests.get(img_url, timeout=timeout)
        if r.status_code == 200:
            print("✓ Direct URL access successful")
            return r.content
        else:
            print(f"✗ Direct URL returned {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"✗ Direct URL failed: {e}")
    
    # Try with encoded spaces
    if " " in img_url:
        encoded_url = img_url.replace(" ", "%20")
        print(f"Trying with encoded spaces: {encoded_url}")
        try:
            r = requests.get(encoded_url, timeout=timeout)
            r.raise_for_status()
            print("✓ Encoded URL successful")
            return r.content
        except Exception as e:
            print(f"✗ Encoded URL failed: {e}")
    
    # All methods failed
    raise Exception(f"All fetch methods failed for URL: {img_url}")


def fetch_bytes_with_supabase_fallback(img_url: str, timeout: int) -> bytes:
    # try as-is first
    r = requests.get(img_url, timeout=timeout)
    if r.status_code == 200:
        return r.content
    # try minted signed URL if this is a supabase storage URL
    alt = supabase_signed_from_public(img_url, expires=60*60)
    if alt:
        r2 = requests.get(alt, timeout=timeout)
        r2.raise_for_status()
        return r2.content
    # as a last attempt, try encoding spaces (safety)
    if " " in img_url:
        r3 = requests.get(img_url.replace(" ", "%20"), timeout=timeout)
        r3.raise_for_status()
        return r3.content
    r.raise_for_status()


def pick_image_url(page: Dict[str, Any]) -> Optional[str]:
    props = page["properties"]
    return get_first_url(props.get(P_ASSET)) or get_first_url(props.get(P_THUMB))

def rt(s: str) -> Dict[str, Any]:
    return {"rich_text":[{"text":{"content": s[:2000]}}]}  # trim long

def as_checkbox(val: Optional[bool]) -> Dict[str, Any]:
    return {"checkbox": bool(val)}

def as_multiselect(items: List[str]) -> Dict[str, Any]:
    clean = []
    for t in items or []:
        t = (t or "").strip().lower()
        if not t: continue
        # normalize a few common aliases
        alias = {
            "dotplot": "dot plot",
            "bubble": "bubble (scatter size)",
            "choropleth": "choropleth",
            "timeline": "timeline",
            "gantt": "gantt",
            "density": "density",
            "hexbin": "hexbin",
            "violin": "violin",
            "area": "area",
            "line": "line",
            "bar": "bar",
            "scatter": "scatter",
            "heatmap": "heatmap",
            "box": "box",
            "pie": "pie",
            "treemap": "treemap",
            "sunburst": "sunburst",
            "sankey": "sankey",
            "funnel": "funnel",
            "waterfall": "waterfall",
            "candlestick": "candlestick",
            "map": "map",
            "contour": "contour",
            "histogram": "histogram",
            "radar": "radar",
            "table": "table",
            "bullet": "bullet",
        }.get(t, t)
        if alias not in clean:
            clean.append(alias)
    return {"multi_select": [{"name": s} for s in clean]}

def discover_schema() -> Dict[str, Any]:
    db = notion.databases.retrieve(DATABASE_ID)
    return db["properties"]

def nonempty(prop: Dict[str, Any]) -> bool:
    """True if the notion property already has a value."""
    if not prop: return False
    t = prop.get("type")
    if t == "checkbox":
        return prop.get("checkbox") is True or prop.get("checkbox") is False
    if t == "multi_select":
        return bool(prop.get("multi_select"))
    if t == "url":
        return bool(prop.get("url"))
    if t == "files":
        return bool(prop.get("files"))
    if t in ("rich_text","title"):
        return bool(read_rich_text(prop)) if t=="rich_text" else bool(prop.get("title"))
    return False

def _extract_bucket_key_from_public(url: str):
    """
    Accepts:
      https://<proj>.supabase.co/storage/v1/object/public/<bucket>/<key...>
      https://<proj>.supabase.co/storage/v1/object/sign/<bucket>/<key...>?...  (works too)
    Returns (bucket, key) or (None, None)
    """
    try:
        u = urlparse(url)
        parts = [p for p in u.path.split("/") if p]
        # .../storage/v1/object/<scope>/<bucket>/<key...>
        i = parts.index("object")
        scope = parts[i+1]            # "public" or "sign"
        bucket = parts[i+2]
        key = "/".join(parts[i+3:])
        return bucket, unquote(key)
    except Exception:
        return None, None

# ---------- Gemini ----------
GEMINI_PROMPT = """You are a chart analyst. Given a chart image, respond with ONLY a JSON object with these keys:

- type: array of chart type labels (choose from: line, bar, scatter, area, heatmap, histogram, box, violin, dotplot, bubble, choropleth, treemap, sunburst, sankey, waterfall, funnel, candlestick, contour, density, hexbin, radar, table, map, timeline, gantt)
- title: concise descriptive title (do NOT mention colors)
- standard: boolean, True if a standard Plotly graph_objects chart without heavy data reshaping or bespoke transforms
- customization: short text listing extra code requirements (e.g., dual-axis, stacked groups, log scale, annotations, reference lines, category order, secondary y, custom legend, multi-panel layout)
- asset_note: short text of fragile/nuanced aspects to preserve (axis units, sorting rules, binning, tick formatting, date parsing, margins, spacing)
- timeseries: boolean, whether x-axis is a date/datetime
- subplot: boolean, whether multiple panels/facets/subplots exist
- multicolor: boolean, whether multiple distinct series/colors appear

Return ONLY JSON. No prose.
"""

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
def gemini_analyze(img_url: str) -> Dict[str, Any]:
    blob = fetch_bytes(img_url, timeout=GEMINI_TIMEOUT)
    b64  = base64.b64encode(blob).decode("utf-8")
    # Remove this redundant request - we already have the image data!
    # r = requests.get(img_url, timeout=GEMINI_TIMEOUT)
    # r.raise_for_status()

    model = genai.GenerativeModel(GEMINI_MODEL)
    resp = model.generate_content(
        contents=[{"role": "user", "parts": [
            {"text": GEMINI_PROMPT},
            {"inline_data": {"mime_type": "image/png", "data": b64}}
        ]}],
        request_options={"timeout": GEMINI_TIMEOUT}
    )
    txt = resp.text or ""
    i, j = txt.find("{"), txt.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("Gemini did not return JSON.")
    data = json.loads(txt[i:j+1])

    # normalize
    data["type"] = [str(x).strip().lower() for x in (data.get("type") or []) if str(x).strip()]
    for k in ("title","customization","asset_note"):
        if k in data and isinstance(data[k], str):
            data[k] = data[k].strip()
    return data

def make_payload(schema: Dict[str, Any], existing: Dict[str, Any], result: Dict[str, Any], only_missing: bool, update_title: bool) -> Dict[str, Any]:
    props = {}

    # Title (optional, only if update_title flag)
    if update_title and P_TITLE in schema and schema[P_TITLE]["type"] == "title":
        if not only_missing or not existing[P_TITLE].get("title"):
            if result.get("title"):
                props[P_TITLE] = {"title": [{"text": {"content": result["title"][:250]}}]}

    # Multi-select type
    if P_VIZ_TYPE in schema and schema[P_VIZ_TYPE]["type"] == "multi_select":
        if not only_missing or not read_multi_select_names(existing.get(P_VIZ_TYPE, {})):
            props[P_VIZ_TYPE] = as_multiselect(result.get("type") or [])

    # Checkboxes
    if P_STANDARD in schema and schema[P_STANDARD]["type"] == "checkbox":
        if not only_missing or read_checkbox(existing.get(P_STANDARD)) is None:
            props[P_STANDARD] = as_checkbox(bool(result.get("standard")))
    if P_SUBPLOT in schema and schema[P_SUBPLOT]["type"] == "checkbox":
        if not only_missing or read_checkbox(existing.get(P_SUBPLOT)) is None:
            props[P_SUBPLOT] = as_checkbox(bool(result.get("subplot")))
    if P_TIMESERIES in schema and schema[P_TIMESERIES]["type"] == "checkbox":
        if not only_missing or read_checkbox(existing.get(P_TIMESERIES)) is None:
            props[P_TIMESERIES] = as_checkbox(bool(result.get("timeseries")))
    if P_MULTICOLOR in schema and schema[P_MULTICOLOR]["type"] == "checkbox":
        if not only_missing or read_checkbox(existing.get(P_MULTICOLOR)) is None:
            props[P_MULTICOLOR] = as_checkbox(bool(result.get("multicolor")))

    # Rich text fields
    if P_ASSET_NOTE in schema and schema[P_ASSET_NOTE]["type"] == "rich_text":
        if not only_missing or not read_rich_text(existing.get(P_ASSET_NOTE, {})):
            props[P_ASSET_NOTE] = rt(result.get("asset_note") or "")
    if P_CUSTOMIZATION in schema and schema[P_CUSTOMIZATION]["type"] == "rich_text":
        if not only_missing or not read_rich_text(existing.get(P_CUSTOMIZATION, {})):
            props[P_CUSTOMIZATION] = rt(result.get("customization") or "")

    return props

# ---------- Main ----------
def main(limit: Optional[int], dry_run: bool, why: bool, mode: str, only_missing: bool, update_title: bool):
    schema = discover_schema()
    # basic checks
    if P_CHARTID not in schema or schema[P_CHARTID]["type"] != "rich_text":
        raise SystemExit(f"Notion DB must have rich_text '{P_CHARTID}'.")
    if P_TITLE not in schema or schema[P_TITLE]["type"] != "title":
        print(f"Warning: Title property '{P_TITLE}' not usable as 'title' (will skip updating title).")

    processed = 0
    cursor = None

    while True:
        resp = notion.databases.query(database_id=DATABASE_ID, start_cursor=cursor, page_size=50)
        for page in resp["results"]:
            props = page["properties"]
            cid = read_rich_text(props.get(P_CHARTID, {}))

            if mode == "present" and not cid:
                if why: print(f"SKIP {page['id']} — chartid empty and mode=present")
                continue
            if mode == "empty" and cid:
                if why: print(f"SKIP {page['id']} — chartid present ({cid}) and mode=empty")
                continue

            img_url = pick_image_url(page)
            if why:
                print(f"{page['id']} | chartid={cid or '(empty)'} | img={'(none)' if not img_url else img_url}")

            if not img_url:
                if why: print(f"SKIP {page['id']} — no usable image URL ({P_ASSET}/{P_THUMB})")
                continue

            if dry_run:
                print(f"[DRY RUN] Would analyze {page['id']} ({cid or '(no-id)'})")
                processed += 1
                if limit and processed >= limit: break
                continue

            # analyze
            try:
                result = gemini_analyze(img_url)
            except Exception as e:
                print(f"Error analyzing {page['id']}: {e}")
                continue

            payload = make_payload(schema, props, result, only_missing=only_missing, update_title=update_title)
            if not payload:
                if why: print(f"SKIP {page['id']} — nothing to update (only_missing=True or schema mismatch)")
                continue

            try:
                notion.pages.update(page_id=page["id"], properties=payload)
                print(f"Annotated {page['id']} ({cid or 'no-id'})")
                processed += 1
            except Exception as e:
                print(f"Error updating {page['id']}: {e}")

            if limit and processed >= limit:
                break

        if limit and processed >= limit:
            break
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

    print(f"Done. Processed: {processed}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Annotate Notion chart rows using Gemini 2.5 Pro.")
    ap.add_argument("--limit", type=int, default=None, help="Max pages to process")
    ap.add_argument("--dry-run", action="store_true", help="Do not call Gemini or write to Notion")
    ap.add_argument("--why", action="store_true", help="Verbose reasons for skips/decisions")
    ap.add_argument("--mode", choices=["present","empty"], default="present",
                    help="present=rows where chartid is present; empty=rows where chartid is empty")
    ap.add_argument("--only-missing", action="store_true",
                    help="Only write properties that are currently empty (no overwrites)")
    ap.add_argument("--update-title", action="store_true",
                    help="Also update the 'Asset name' title using Gemini's suggested title")
    args = ap.parse_args()
    main(limit=args.limit, dry_run=args.dry_run, why=args.why, mode=args.mode,
         only_missing=args.only_missing, update_title=args.update_title)
