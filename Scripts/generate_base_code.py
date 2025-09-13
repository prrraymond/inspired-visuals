#!/usr/bin/env python3
import os, io, re, json, base64, argparse, pathlib, textwrap, requests
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from tenacity import retry, stop_after_attempt, wait_exponential
from anthropic import Anthropic, APIStatusError
from dotenv import load_dotenv
from notion_client import Client as Notion
from pydantic import BaseModel, Field
from PIL import Image, ImageOps, ImageEnhance, ImageChops
from datetime import datetime
from urllib.parse import urlparse, unquote
from supabase import create_client

# =========================
# ENV / CLIENTS
# =========================
load_dotenv(dotenv_path=".env.local")

# Database configuration - separate source and target
SOURCE_DB_ID = os.getenv("NOTION_DATABASE_ID")  # Annotated database with images
TARGET_DB_ID = os.getenv("NOTION_TARGET_DATABASE_ID", "25ae89d6bdbe807fbe99eb951671ab8c")  # Staging database
NOTION_API_KEY = os.getenv("NOTION_API_KEY")

ANTHROPIC_API_KEY = os.getenv("CLAUDE_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-7-sonnet-latest")
CLAUDE_TIMEOUT = int(os.getenv("CLAUDE_TIMEOUT") or "60")

if not (NOTION_API_KEY and SOURCE_DB_ID and TARGET_DB_ID and ANTHROPIC_API_KEY):
    raise SystemExit("Missing NOTION_API_KEY, NOTION_DATABASE_ID, NOTION_TARGET_DATABASE_ID, or ANTHROPIC_API_KEY in env.")

# Fixed: use consistent variable name
anth = Anthropic(api_key=ANTHROPIC_API_KEY)
notion = Notion(auth=NOTION_API_KEY)

# Notion properties - simplified and consistent
P_TITLE = os.getenv("NOTION_PROP_TITLE", "Asset name")
P_CHARTID = os.getenv("NOTION_PROP_CHARTID", "chartid")
P_ASSET = os.getenv("NOTION_PROP_ASSET_URL", "Asset URL")
P_THUMB = os.getenv("NOTION_PROP_THUMB_URL", "Thumbnail")
P_CODE_FILE = os.getenv("NOTION_PROP_CODE_FILE", "Base code file")
P_CODE_URL = os.getenv("NOTION_PROP_CODE_URL", "Base code URL")
P_DATASET_URL = os.getenv("NOTION_PROP_DATASET_URL","Dataset URL")     # url
P_CODE_NOTES = os.getenv("NOTION_PROP_CODE_NOTES", "Base code notes")

# Notion property names (override via env if yours differ)
NOTION_PROP_CODE_URL    = os.getenv("NOTION_PROP_CODE_URL", "Base code URL")
NOTION_PROP_CODE_FILE   = os.getenv("NOTION_PROP_CODE_FILE", "Base code file")
# Optional: if you want a short preview text, set this env to that property name (or leave empty)
NOTION_PROP_CODE_PREVIEW = os.getenv("NOTION_PROP_CODE_PREVIEW", "")  # e.g., "Source code (preview)"


# Supabase setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "viz-training-assets")
supa = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

# =========================
# CONFIG
# =========================
OUT_DIR = pathlib.Path("generated/plotly")
OUT_DIR.mkdir(parents=True, exist_ok=True)

ENHANCE_IMAGE = True
MAX_IMAGE_WIDTH_PX = 1600
CONTRAST_FACTOR = 1.20
SHARPNESS_FACTOR = 1.10

# =========================
# PROMPT
# =========================
PROMPT_TEXT = """
You are generating reusable Plotly (Python) templates from chart screenshots.

GOAL
Return JSON ONLY with these keys:
- plotly_code: string, complete and runnable Python using plotly.graph_objects ONLY (no plotly.express).
- filename_suggestion: short-kebab-case base name (no extension), e.g. "grouped-bar-by-region".
- notes: 1-3 sentences on assumptions and how to adapt.
- data_contract: JSON object describing sample data you created (columns with name & dtype, approx row count, and any grouping keys).
- caveats: list of important chart caveats (e.g., dual y-axes, log scale, % stacking, cumulative sum, faceting, Cleveland dot layout, custom sorting, annotations).

ANALYSIS REQUIREMENTS
1) Identify chart type(s) and overall structure (bar/stacked/grouped, line, scatter/dot/strip, heatmap, subplots/facets, etc.).
2) Note special features: dual axes, log scales, percentage stacking, cumulative sum, annotations/callouts, categorical ordering, multi-color series, subplots/facets.
3) Identify titles, axis labels, tick formats, units, and obvious formatting patterns.
4) Styling: replicate essential layout cues (gridlines, legend placement, margins, title weight/size). Avoid brand-specific colors; use neutral defaults.

CODE GENERATION REQUIREMENTS
- Use ONLY plotly.graph_objects (no plotly.express).
- Create a minimal but complete inline pandas DataFrame with realistic column names and ~20-50 rows (no external I/O).
- Make the code runnable as-is: imports, DataFrame construction, figure creation, traces, layout, show.
- Include comments for TODOs where real data columns should map (x, y, color, facet, group, aggregation).
- Implement special features you detected (e.g., secondary_y, log axis, % stacking, subplots via make_subplots).
- For dot/Cleveland plots, use go.Scatter(mode="markers") and mention "Cleveland dot plot" in caveats if applicable.
- Keep code modular/readable (sections: data stub, traces, layout).

OUTPUT FORMAT
Return JSON ONLY with these keys. Do not include Markdown fences, backticks, or extra text.

STRICT VALIDATION RULES:
- JSON must be syntactically valid.
- Keys: plotly_code, filename_suggestion, notes, data_contract, caveats.
- Values: 
  - plotly_code is a string containing complete runnable Python using plotly.graph_objects only.
  - filename_suggestion is a short kebab-case string.
  - notes is 1–3 sentences.
  - data_contract is a JSON object.
  - caveats is a list of strings.
- No other text or formatting allowed.
- If unable to comply, return {"error": "generation_failed"}.


"""

# =========================
# MODELS
# =========================
class ClaudeOut(BaseModel):
    plotly_code: str
    filename_suggestion: Optional[str] = None
    notes: Optional[str] = None
    data_contract: Optional[Dict[str, Any]] = None
    caveats: Optional[List[str]] = None


def update_target_row_code_links(page_id: str, code_url: str, code_text: str | None = None) -> None:
    """
    Update a Notion page with links to the generated base code.
    - Writes URL into a 'url' property (e.g., "Base code URL").
    - Writes an external file into a 'files' property (e.g., "Base code file").
    - Optionally writes a short preview (<= 1800 chars) to a rich_text property,
      if NOTION_PROP_CODE_PREVIEW is set (env).
    """
    props: dict[str, dict] = {
        NOTION_PROP_CODE_URL: {"url": code_url},
        NOTION_PROP_CODE_FILE: {
            "files": [
                {
                    "type": "external",
                    "name": "base.py",
                    "external": {"url": code_url},
                }
            ]
        },
    }

    # Optional short preview (avoid 2k char limit problems)
    if NOTION_PROP_CODE_PREVIEW and code_text:
        preview = (code_text[:1800] + "…") if len(code_text) > 1800 else code_text
        props[NOTION_PROP_CODE_PREVIEW] = {
            "rich_text": [
                {"type": "text", "text": {"content": preview}}
            ]
        }

    update_target_row_code_links(page_id, code_url, code_text)  # code_text optional



# =========================
# UTILS - Fixed duplicates and inconsistencies
# =========================
def slugify(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    s = re.sub(r"[-\s]+", "-", s)
    return s or "chart"

def read_rich_text(prop: Dict[str, Any]) -> str:
    """Single implementation of rich_text reading"""
    if not prop or "rich_text" not in prop:
        return ""
    return "".join((r.get("text", {}) or {}).get("content","") for r in prop["rich_text"]).strip()

def read_title(prop: Dict[str, Any]) -> str:
    if not prop or "title" not in prop:
        return ""
    return "".join((r.get("text", {}) or {}).get("content","") for r in prop["title"]).strip()

def get_first_url(prop: Dict[str, Any]) -> Optional[str]:
    """Single implementation of URL extraction"""
    if not prop: 
        return None
    
    # Direct URL
    if prop.get("url"): 
        return prop["url"]
    
    # Files (external or Notion file link)
    if "files" in prop:
        for f in prop["files"]:
            if f.get("type") == "external" and f["external"].get("url"): 
                return f["external"]["url"]
            if f.get("type") == "file" and f["file"].get("url"): 
                return f["file"]["url"]
    
    # Rich text with URLs
    if "rich_text" in prop:
        for block in prop["rich_text"]:
            if block.get("href") and block["href"].startswith(("http://","https://")): 
                return block["href"]
            txt = ((block.get("text") or {}).get("content") or "")
            m = re.search(r'(https?://\S+)', txt)
            if m: 
                return m.group(1)
    
    return None

def pick_image_url(page: Dict[str, Any]) -> Optional[str]:
    """Fixed function signature and implementation"""
    props = page["properties"]
    return get_first_url(props.get(P_ASSET)) or get_first_url(props.get(P_THUMB))

def page_has_base_code(props: Dict[str, Any]) -> bool:
    has_url = bool(props.get(P_CODE_URL, {}).get("url"))
    has_file = bool(props.get(P_CODE_FILE, {}).get("files"))
    return has_url or has_file

# ---- Notion rich_text helpers ----
MAX_DB_ITEM = 2000  # Notion hard limit per rich_text item

def _rt(s: str) -> dict:
    return {"type": "text", "text": {"content": s}}

def rt_chunks(text: str, chunk: int = 1800) -> list[dict]:
    """Split long text into multiple rich_text items safely."""
    if not text:
        return []
    return [_rt(text[i:i+chunk]) for i in range(0, len(text), chunk)]

def rt_truncated(text: str, url: str | None = None) -> dict:
    header = f"# [TRUNCATED]\n# Full code: {url}\n\n" if url else ""
    budget = MAX_DB_ITEM - len(header)
    if budget < 0:
        header = header[:MAX_DB_ITEM - 1]
        budget = MAX_DB_ITEM - len(header)
    if len(text) > budget:
        return _rt(header + text[:max(0, budget - 4)] + " ...")
    return _rt(text)


# =========================
# SUPABASE UTILS
# =========================
def _sb_bucket_key_from_object_url(url: str):
    try:
        p = urlparse(url)
        parts = [x for x in p.path.split("/") if x]
        i = parts.index("object")
        bucket = parts[i+2]
        key = "/".join(parts[i+3:])
        return bucket, unquote(key)
    except Exception:
        return None, None

def supabase_signed_url_for(url: str, expires=3600) -> str | None:
    if not (supa and url and ".supabase.co" in url and "/storage/v1/object/" in url):
        return None
    b, k = _sb_bucket_key_from_object_url(url)
    if not b or not k:
        return None
    bucket_use = SUPABASE_BUCKET or b
    res = supa.storage.from_(bucket_use).create_signed_url(k, expires_in=expires)
    if isinstance(res, str):
        return res
    if isinstance(res, dict):
        return res.get("signedUrl") or res.get("signedURL")
    return None

def fetch_bytes(img_url: str, timeout: int) -> bytes:
    if ".supabase.co" in img_url and "/storage/v1/object/" in img_url:
        alt = supabase_signed_url_for(img_url, expires=3600)
        if alt:
            r = requests.get(alt, timeout=timeout)
            r.raise_for_status()
            return r.content
    
    r = requests.get(img_url, timeout=timeout)
    if r.status_code == 200: 
        return r.content
    
    if " " in img_url:
        r2 = requests.get(img_url.replace(" ", "%20"), timeout=timeout)
        r2.raise_for_status()
        return r2.content
    
    r.raise_for_status()

# --- storage scaffold helpers ----------------------------------------------

def _sb_upload(
    key: str,
    data: bytes = b"1",
    content_type: str = "text/plain",
    upsert: bool = True,
) -> str:
    """
    Upload bytes to Supabase Storage and return a fetchable URL.
    Requires globals: supa, SUPABASE_BUCKET, SUPABASE_URL.
    """
    if not supa:
        raise RuntimeError("Supabase client not initialized (check SUPABASE_URL/KEY).")

    # IMPORTANT: httpx headers must be strings, not bools.
    supa.storage.from_(SUPABASE_BUCKET).upload(
        key,
        data,
        {"contentType": content_type, "upsert": "true" if upsert else "false"},
    )

    # 1) Try public URL (works if bucket/object is public)
    try:
        pub = supa.storage.from_(SUPABASE_BUCKET).get_public_url(key)
        if isinstance(pub, str) and pub:
            return pub.rstrip("?")
        if isinstance(pub, dict):
            url = pub.get("publicUrl") or pub.get("public_url") or ""
            if url:
                return url.rstrip("?")
    except Exception:
        pass

    # 2) Signed URL fallback (1 year)
    try:
        signed = supa.storage.from_(SUPABASE_BUCKET).create_signed_url(key, expires_in=60*60*24*365)
        if isinstance(signed, str) and signed:
            return signed.rstrip("?")
        if isinstance(signed, dict):
            url = signed.get("signedUrl") or signed.get("signedURL") or ""
            if url:
                return url.rstrip("?")
    except Exception:
        pass

    # 3) Last-resort deterministic public path (will 403 if object isn’t public)
    return f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{SUPABASE_BUCKET}/{key}"


def ensure_storage_scaffold(chartid: str, touch_latest: bool = True, why: bool = False, dry_run: bool = False):
    """
    Ensure these prefixes exist for a given chartid:
      code/<chartid>/
      charts/<chartid>/
      files/<chartid>/
      datasets/<chartid>/              <-- NEW
    Optionally create empty latest.csv/parquet in datasets/.
    """
    prefixes = [
        f"code/{chartid}/.keep",
        f"charts/{chartid}/.keep",
        f"files/{chartid}/.keep",
        f"datasets/{chartid}/.keep",   # NEW
    ]
    for key in prefixes:
        if dry_run:
            if why: print(f"[DRY RUN] touch {key}")
        else:
            _sb_upload(key)

    if touch_latest:
        lat_csv = f"datasets/{chartid}/latest.csv"
        lat_par = f"datasets/{chartid}/latest.parquet"
        if dry_run:
            if why: print(f"[DRY RUN] touch {lat_csv}, {lat_par}")
        else:
            _sb_upload(lat_csv, b"", content_type="text/csv")
            _sb_upload(lat_par, b"", content_type="application/octet-stream")

    if why:
        print(f"Scaffold ready for {chartid}: code/, charts/, files/, datasets/")


# =========================
# CLAUDE API - Fixed implementation
# =========================
@retry(wait=wait_exponential(multiplier=1, min=2, max=20), stop=stop_after_attempt(3))
def generate_plotly_code_from_image(img_bytes: bytes) -> ClaudeOut:
    """Fixed: Use the correct API client and return structured data"""
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    
    resp = anth.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4000,
        temperature=0.2,
        system="You return JSON only and never use markdown fences.",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT_TEXT},
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": b64}
                }
            ]
        }],
    )
    
    text = "".join([block.text for block in resp.content if hasattr(block, 'text')])
    
    # Extract JSON
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("Claude did not return valid JSON.")
    
    data = json.loads(text[i:j+1])
    return ClaudeOut(**data)

# =========================
# SUPABASE UPLOAD - Version-safe upload
# =========================
def supa_upload_code(key: str, data: bytes, upsert: bool = True):
    """
    Version-safe Storage upload for code files:
    - Prefer newer signature upload(path, file, file_options=..., upsert=True)
    - Fallback to older signature where upsert must be inside file_options as string
    """
    try:
        # Newer SDKs accept `upsert` as a top-level kwarg
        return supa.storage.from_(SUPABASE_BUCKET).upload(
            path=key,
            file=data,
            file_options={"contentType": "text/x-python"},
            upsert=upsert,  # bool OK here on newer SDKs
        )
    except TypeError:
        # Older SDKs — put upsert into file_options as a STRING, not bool
        return supa.storage.from_(SUPABASE_BUCKET).upload(
            path=key,
            file=data,
            file_options={
                "contentType": "text/x-python",
                "upsert": "true" if upsert else "false",
            },
        )

def upload_code_to_supabase(chartid: str, code: str) -> str:
    if not supa:
        raise ValueError("Supabase not configured")
    
    key = f"code/{chartid}/{chartid}_base.py"
    data = code.encode("utf-8")
    
    # Upload file using version-safe method
    supa_upload_code(key, data, upsert=True)
    
    # Get public URL
    url = supa.storage.from_(SUPABASE_BUCKET).get_public_url(key).rstrip("?")
    if isinstance(url, str): 
        return url.rstrip("?")
    if isinstance(url, dict) and url.get("publicUrl"):
        return url["publicUrl"].rstrip("?")
    
    # Fallback to signed URL
    signed = supa.storage.from_(SUPABASE_BUCKET).create_signed_url(key, expires_in=60*60*24*365)
    if isinstance(signed, str): 
        return signed.rstrip("?")
    if isinstance(signed, dict) and signed.get("signedUrl"):
        return signed["signedUrl"].rstrip("?")
    
    raise ValueError("Could not generate URL for uploaded file")

# =========================
# NOTION TARGET DATABASE FUNCTIONS
# =========================

NAME_FALLBACKS = {
    "Code URL": ["Base code URL"],  # if you eventually create one named exactly this
    "Source code": ["Source Code"],
    "Source path": ["Source Path"],
    "Data contract": ["Data Contract", "Schema"],
    "Caveats": ["Caveats"],
    "QA notes": ["QA notes"],
    "Dataset URL": ["Dataset URL"],  # already exists
}

def get_target_properties(notion, db_id):
    db = notion.databases.retrieve(db_id)
    props = set(db["properties"].keys())
    print("[DBG] Target DB properties:", ", ".join(sorted(props)))
    return props

def coerce_prop_names(props, valid, fallbacks=NAME_FALLBACKS):
    out = {}
    for k, v in props.items():
        if k in valid:
            out[k] = v
        elif k in fallbacks:
            for alt in fallbacks[k]:
                if alt in valid:
                    out[alt] = v
                    break
        # else: drop silently
    return out

def append_code_block(notion, page_id: str, code_text: str, lang: str = "python"):
    notion.blocks.children.append(
        block_id=page_id,  # <— correct param name
        children=[{
            "object": "block",
            "type": "code",
            "code": {
                "language": lang,
                "rich_text": rt_chunks(code_text, chunk=1800)
            }
        }]
    )

    # call it:
    append_code_block(notion, page["id"], result.plotly_code, "python")

def create_target_page(source_page_id: str, chartid: str, title: str, result: ClaudeOut, 
                      code_url: str, write_files: bool) -> str:
    """Create a new page in the target database with generated code"""

    properties = {
        # Adjust these property names to match your DB exactly
        "Title":   {"title":     [_rt(title or chartid)]},
        "chartid": {"rich_text": [_rt(chartid)]},
        "Base code URL": {"url": code_url},  # URL property in your DB
        "Source code": {"rich_text": [rt_truncated(result.plotly_code, code_url)]},
        "Source path": {"rich_text": [_rt(f"{chartid}_base.py")]},
        "Data contract": {"rich_text": rt_chunks(json.dumps(result.data_contract, indent=2))} 
                         if getattr(result, "data_contract", None) else {"rich_text": []},
        "Caveats": {"rich_text": rt_chunks("\n".join(result.caveats or []))},
        "Status": {"select": {"name": "draft"}},
        "QA notes": {"rich_text": rt_chunks(
            f"Auto-generated.\nCode file: {code_url}\nNotes: {result.notes or 'None'}"
        )},
    }

    # Optional sanity check to prevent 2k errors:
    first_item = properties["Source code"]["rich_text"][0]["text"]["content"]
    print(f"[DBG] Source code first-item length={len(first_item)} (must be <=2000)")

    valid = get_target_properties(notion, TARGET_DB_ID)
    safe_props = coerce_prop_names(properties, valid)

    page = notion.pages.create(
        parent={"database_id": TARGET_DB_ID},
        properties=safe_props
    )

    # Append full code to page body as a code block
    append_code_block(notion, page["id"], result.plotly_code, "python")

    return page["id"]





def target_page_exists(chartid: str) -> Optional[str]:
    """Check if target page already exists for this chartid"""
    try:
        resp = notion.databases.query(
            database_id=TARGET_DB_ID,
            filter={"property": "chartid", "rich_text": {"equals": chartid}},
            page_size=1
        )
        return resp["results"][0]["id"] if resp["results"] else None
    except Exception:
        return None

def write_local_file(chartid: str, title: str, filename_suggestion: Optional[str], 
                    code: str) -> pathlib.Path:
    base = filename_suggestion or slugify(title) or "chart"
    fname = f"{chartid}_{base}.py"
    path = OUT_DIR / fname
    
    header = textwrap.dedent(f"""\
    # Generated template for {chartid}
    # Title: {title or 'Untitled'}
    # Created: {datetime.utcnow().isoformat()}Z
    # Notes: Auto-generated from a screenshot. Replace placeholder data with real columns.
    """)
    
    with open(path, "w", encoding="utf-8") as f:
        f.write(header.rstrip() + "\n\n")
        f.write(code.strip() + "\n")
    
    return path

MAX_DB_CHARS = 2000
TRUNC_HDR = "# [TRUNCATED]\n# Full code: {url}\n\n"

def code_for_db_property(code_text: str, public_url: str) -> str:
    head = TRUNC_HDR.format(url=public_url)
    if len(code_text) <= MAX_DB_CHARS:
        return code_text
    # Leave room for header
    budget = MAX_DB_CHARS - len(head) - 10  # some room for the ellipsis
    return head + code_text[:max(budget, 0)] + "\n# ... (truncated)"

def split_rich_text(text: str, chunk=1800):
    parts, cur, buf = [], 0, []
    for line in text.splitlines(True):
        if cur + len(line) > chunk:
            parts.append("".join(buf)); buf=[line]; cur=len(line)
        else:
            buf.append(line); cur += len(line)
    if buf: parts.append("".join(buf))
    return [{"type":"text","text":{"content":p}} for p in parts]

def append_code_block(notion, page_id: str, code_text: str, lang: str = "python"):
    notion.blocks.children.append(
        page_id,  # <-- pass the page id as the first positional argument
        children=[{
            "object": "block",
            "type": "code",
            "code": {
                "language": lang,
                "rich_text": [{"type":"text","text":{"content": code_text[i:i+1800]}}
                              for i in range(0, len(code_text), 1800)]
            }
        }]
    )


# =========================
# MAIN - Fixed to implement source → target workflow  
# =========================
def main(limit=None, dry_run=False, why=False, only_missing=True, write_files=False):
    print(f"Reading from SOURCE database: {SOURCE_DB_ID}")
    print(f"Writing to TARGET database: {TARGET_DB_ID}")
    
    processed = 0
    cursor = None
    
    while True:
        # Read from SOURCE database (annotated database with images)
        resp = notion.databases.query(
            database_id=SOURCE_DB_ID,  # READ from source
            start_cursor=cursor, 
            page_size=50,
            filter={"property": P_CHARTID, "rich_text": {"is_not_empty": True}}  # Only rows with chartid
        )
        
        for page in resp["results"]:
            props = page["properties"]
            cid = read_rich_text(props.get(P_CHARTID, {}))
            title = read_title(props.get(P_TITLE, {}))
            
            if not cid:
                if why: print(f"SKIP {page['id']} — no chartid")
                continue
                
            if only_missing and target_page_exists(cid):
                if why: print(f"SKIP {page['id']} ({cid}) — already exists in target database")
                continue

            img_url = pick_image_url(page)
            if not img_url:
                if why: print(f"SKIP {page['id']} ({cid}) — no image URL")
                continue

            if dry_run:
                print(f"[DRY RUN] Would generate code for {cid} from {img_url}")
                processed += 1
                if limit and processed >= limit: break
                continue

            print(f"Processing {cid}: {title}")

            try:
                blob = fetch_bytes(img_url, timeout=45)
                result = generate_plotly_code_from_image(blob)
                code = result.plotly_code
            except Exception as e:
                print(f"Error generating code for {cid}: {e}")
                continue
            # before uploading code/{chartid}/{chartid}_base.py
            ensure_storage_scaffold(cid, touch_latest=True, why=why, dry_run=dry_run)


            try:
                # Upload code to Supabase
                if supa:
                    code_url = upload_code_to_supabase(cid, code)
                    print(f"Uploaded code to: {code_url}")
                else:
                    code_url = "https://example.com/fallback.py"  # Fallback if no Supabase
                
                # Create page in TARGET database
                target_page_id = create_target_page(
                    source_page_id=page["id"],
                    chartid=cid, 
                    title=title,
                    result=result,
                    code_url=code_url,
                    write_files=write_files
                )
                
                print(f"Created target page: {target_page_id}")
                
                # Write local file if requested
                if write_files:
                    path = write_local_file(cid, title, result.filename_suggestion, code)
                    print(f"Wrote local file: {path}")
                    
                processed += 1
                
            except Exception as e:
                print(f"Error storing results for {cid}: {e}")

            if limit and processed >= limit:
                break

        if limit and processed >= limit: break
        if not resp.get("has_more"): break
        cursor = resp.get("next_cursor")

    print(f"Done. Processed: {processed} pages from source to target database.")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Generate Plotly code templates from Notion chart screenshots using Claude."
    )
    ap.add_argument("--limit", type=int, default=None, help="Max number of rows to process")
    ap.add_argument("--dry-run", action="store_true", help="Preview without writing Notion or disk")
    ap.add_argument("--why", action="store_true", help="Verbose skip reasons")
    ap.add_argument("--only-missing", action="store_true", default=True, 
                    help="Skip rows that already have base code")
    ap.add_argument("--write-files", action="store_true", 
                    help="Also write .py files to generated/plotly")
    
    args = ap.parse_args()
    main(
        limit=args.limit, 
        dry_run=args.dry_run, 
        why=args.why, 
        only_missing=args.only_missing,
        write_files=args.write_files
    )