"""
Generate alt text for chart images stored in a Notion database and write it to an adjacent property.

Usage:
  export NOTION_API_KEY=...
  export OPENAI_API_KEY=...
  python notion_chart_alt_text_generator.py \
      --database-id YOUR_DB_ID \
      --image-prop Image \
      --alt-prop Alt Text \
      [--overwrite]

Notes:
- Supports Notion properties of type Files or URL for the image column.
- Writes alt text to a Rich Text property.
- Skips rows that already have alt text unless --overwrite is provided.
- Uses OpenAI Vision (gpt-4o-mini) to caption charts concisely and accessibly.
"""

import os
import time
import argparse
from typing import Optional, Dict, Any, List

from notion_client import Client as NotionClient
from openai import OpenAI

# -----------------------------
# OpenAI captioning
# -----------------------------

def generate_alt_text(image_url: str, page_title: str = "") -> str:
    """Call OpenAI to generate concise, accessible alt text for a data viz.

    The prompt asks for: chart type + what it shows + timeframe (if visible) + key trend/insight,
    kept under ~200 characters, no extra commentary.
    """
    client = OpenAI()

    system = (
        "You are an accessibility expert creating alt text for data visualizations. "
        "Write one sentence (<=200 characters). Mention the chart type, subject, and the most salient trend. "
        "Avoid speculative language and numbers not visible. No preambles like 'Image of'."
    )

    user_text = (
        f"Provide alt text for this chart image. If helpful, the page title is: '{page_title}'.\n"
        "Return only the alt text sentence."
    )

    # Use Chat Completions w/ image_url content
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
    )

    return completion.choices[0].message.content.strip()


# -----------------------------
# Notion helpers
# -----------------------------

def get_title_from_props(props: Dict[str, Any]) -> str:
    for key, val in props.items():
        if val.get("type") == "title":
            parts = val.get("title", [])
            if parts:
                return "".join([p.get("plain_text", "") for p in parts]).strip()
    return ""


def extract_image_url(props: Dict[str, Any], image_prop: str) -> Optional[str]:
    if image_prop not in props:
        return None
    p = props[image_prop]
    tp = p.get("type")

    if tp == "files":
        files: List[Dict[str, Any]] = p.get("files", [])
        if not files:
            return None
        f0 = files[0]
        if "file" in f0 and f0["file"].get("url"):
            return f0["file"]["url"]  # expiring signed URL
        if "external" in f0 and f0["external"].get("url"):
            return f0["external"]["url"]
        return None

    if tp == "url":
        return p.get("url")

    # Could extend to cover 'rich_text' with links, but not implemented here.
    return None


def read_alt_text(props: Dict[str, Any], alt_prop: str) -> str:
    if alt_prop not in props:
        return ""
    p = props[alt_prop]
    if p.get("type") == "rich_text":
        parts = p.get("rich_text", [])
        return "".join([s.get("plain_text", "") for s in parts]).strip()
    return ""


def write_alt_text(notion: NotionClient, page_id: str, alt_prop: str, text: str) -> None:
    notion.pages.update(
        page_id=page_id,
        properties={
            alt_prop: {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": text[:200]},
                    }
                ]
            }
        },
    )


# -----------------------------
# Main job
# -----------------------------

def process_database(database_id: str, image_prop: str, alt_prop: str, overwrite: bool, rate_limit_s: float = 0.6) -> None:
    notion = NotionClient(auth=os.environ["NOTION_API_KEY"]) 

    cursor = None
    total = 0
    updated = 0

    while True:
        resp = notion.databases.query(database_id=database_id, start_cursor=cursor)
        results = resp.get("results", [])
        cursor = resp.get("next_cursor")

        for page in results:
            total += 1
            page_id = page["id"]
            props = page.get("properties", {})

            existing = read_alt_text(props, alt_prop)
            if existing and not overwrite:
                continue

            img_url = extract_image_url(props, image_prop)
            if not img_url:
                continue

            title = get_title_from_props(props)

            try:
                alt = generate_alt_text(img_url, page_title=title)
            except Exception as e:
                print(f"[WARN] Alt text generation failed for {page_id}: {e}")
                continue

            try:
                write_alt_text(notion, page_id, alt_prop, alt)
                updated += 1
                print(f"Updated {page_id}: {alt}")
            except Exception as e:
                print(f"[WARN] Notion update failed for {page_id}: {e}")
                continue

            time.sleep(rate_limit_s)

        if not resp.get("has_more"):
            break

    print(f"Done. Scanned {total} pages; updated {updated}.")


def main():
    parser = argparse.ArgumentParser(description="Generate alt text for chart images in a Notion database.")
    parser.add_argument("--database-id", required=True, help="Notion database ID")
    parser.add_argument("--image-prop", required=True, help="Name of the Notion property that contains the image (Files or URL)")
    parser.add_argument("--alt-prop", required=True, help="Name of the Rich Text property to write alt text into")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing alt text")
    args = parser.parse_args()

    missing_env = [k for k in ("NOTION_API_KEY", "OPENAI_API_KEY") if not os.environ.get(k)]
    if missing_env:
        raise SystemExit(f"Missing env vars: {', '.join(missing_env)}")

    process_database(
        database_id=args.database_id,
        image_prop=args.image_prop,
        alt_prop=args.alt_prop,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
