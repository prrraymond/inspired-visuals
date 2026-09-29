#!/usr/bin/env python3
"""
Read-only data access for the gallery.

Everything here reads. Nothing writes to Notion or Supabase.

Design note: a library entry is currently TWO things sharing one Notion row --
a reverse-engineered *reference* (curated title, asset note, original SQL, the
Stage-B styling metadata, the source screenshot) and a runnable *template*
(abstract code, Final SQL, derived contract, accepted parameters). Once SQL is
repointed at a real table the two describe different subjects. This module keeps
them separate so the UI can show the divergence rather than blend it.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env.local")

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
PROD_DB = os.getenv("NOTION_PROD_DATABASE_ID")
SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
BUCKET = os.getenv("SUPABASE_BUCKET", "viz-training-assets")
PUBLIC = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/"

NOTION = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


class ConfigError(RuntimeError):
    pass


def check_credentials() -> list[str]:
    """Return a list of problems. Names only -- never values."""
    problems = []
    for name, val in [("NOTION_API_KEY", NOTION_API_KEY), ("NOTION_PROD_DATABASE_ID", PROD_DB),
                      ("SUPABASE_URL", SUPABASE_URL)]:
        if not val:
            problems.append(f"{name} is not set")
    # A key issued for a different project than SUPABASE_URL names is provable,
    # not a judgement call -- and going unnoticed is what pointed 801 catalog
    # URLs at a project the workstream had already left.
    problems.extend(supabase_config.problems())
    return problems


# --------------------------------------------------------------------------- #
# Notion property readers
# --------------------------------------------------------------------------- #
def _rt(prop: Optional[dict]) -> str:
    return "".join(x.get("plain_text", "") for x in (prop or {}).get("rich_text", [])).strip()


def _title(prop: Optional[dict]) -> str:
    return "".join(x.get("plain_text", "") for x in (prop or {}).get("title", [])).strip()


def _url(prop: Optional[dict]) -> Optional[str]:
    return (prop or {}).get("url") or None


def _files(prop: Optional[dict]) -> list[str]:
    out = []
    for f in (prop or {}).get("files", []):
        u = (f.get("external") or {}).get("url") or (f.get("file") or {}).get("url")
        if u:
            out.append(u)
    return out


def _multi(prop: Optional[dict]) -> list[str]:
    return [x["name"] for x in (prop or {}).get("multi_select", [])]


def _status(prop: Optional[dict]) -> Optional[str]:
    return ((prop or {}).get("status") or {}).get("name")


def _check(prop: Optional[dict]) -> bool:
    return bool((prop or {}).get("checkbox"))


def _maybe_json(raw: str) -> tuple[Optional[Any], Optional[str]]:
    """Parse JSON, returning (value, error). Never raises -- the UI shows the error."""
    if not raw:
        return None, None
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return None, f"stored value is not valid JSON ({exc.msg} at position {exc.pos})"


# --------------------------------------------------------------------------- #
# Entry model
# --------------------------------------------------------------------------- #
@dataclass
class Asset:
    """A remote file, with its availability actually checked rather than assumed."""
    label: str
    url: Optional[str]
    status: Optional[int] = None
    content_type: Optional[str] = None
    error: Optional[str] = None

    @property
    def missing(self) -> bool:
        return not self.url

    @property
    def ok(self) -> bool:
        return self.status == 200

    @property
    def state(self) -> str:
        if self.missing:
            return "absent"
        if self.error:
            return "unreachable"
        return "ok" if self.ok else "broken"


@dataclass
class Entry:
    chartid: str
    page_id: str
    # --- provenance: describes the SOURCE chart that was reverse-engineered ---
    title: str
    asset_note: str
    original_sql: str
    source_image: Asset
    thumbnail: Asset
    # --- template: describes what this entry NOW produces ---
    subject: str
    slug: str
    viz_types: list[str]
    status: Optional[str]
    flags: dict
    final_sql: str
    template_url: Optional[str]
    caveats: list[str]
    qa_notes: str
    contract: Optional[dict]
    contract_error: Optional[str]
    render: Asset
    source_styling: list = field(default_factory=list)
    last_edited: Optional[str] = None
    _code: Optional[str] = field(default=None, repr=False)

    provenance_recorded: Optional[str] = None

    @property
    def provenance_state(self) -> str:
        return resolve_state(self.original_sql, self.final_sql, self.provenance_recorded)[0]

    @property
    def provenance_disagreement(self) -> Optional[str]:
        return resolve_state(self.original_sql, self.final_sql, self.provenance_recorded)[1]

    @property
    def sql_repointed(self) -> bool:
        return self.provenance_state == REPOINTED

    @property
    def styling_has_stale(self) -> bool:
        """Open the provenance panel by default when it contradicts the contract."""
        return any(f.get("stale") for f in self.source_styling)

    @property
    def proposals(self) -> list[dict]:
        return (self.contract or {}).get("suggested_parameters", []) or []


# Stage-B (Gemini) output. These describe the SOURCE chart and are consumed by
# Stage D's prompt -- they are provenance, never properties of what this entry now
# renders. Order is display order.
STYLING_FIELDS = [
    ("Add Text", "Add Text"),
    ("Add Line", "Add Line"),
    ("Highlight Map", "Highlight Map"),
    ("Layout Options", "Layout Options"),
    ("Axis Formatting", "Axis Formatting"),
    ("Default Color", "Default Color"),
    ("Sort By", "Sort By"),
    ("Data Filter", "Data Filter"),
]


def _styling(props: dict, contract: Optional[dict], repointed: bool) -> list[dict]:
    """
    Collect the Stage-B styling fields for display as provenance.

    Marks a field stale when it names categories that the current dataset cannot
    produce -- CHT-6FBD47's Highlight Map is keyed on arrest bands while its
    contract describes pupil-teacher ratios. Divergence is shown, not hidden, and
    never presented as a claim about the render.
    """
    contract_cols = {c.get("name", "").lower() for c in (contract or {}).get("columns", [])}
    out = []
    for key, label in STYLING_FIELDS:
        raw = _rt(props.get(key))
        if not raw or raw in ("[]", "{}"):
            continue
        parsed, _ = _maybe_json(raw)
        pretty = json.dumps(parsed, indent=1) if parsed not in (None, [], {}) else None
        stale = None
        if repointed and key == "Highlight Map" and isinstance(parsed, dict) and parsed:
            keys = list(parsed)
            if not any(k.lower() in contract_cols for k in keys):
                stale = (f"Keys ({', '.join(keys[:3])}"
                         f"{'…' if len(keys) > 3 else ''}) come from the source chart's "
                         f"categories. The current dataset does not produce them.")
        out.append({"key": key, "label": label, "value": raw,
                    "pretty": pretty, "stale": stale})
    return out


# Provenance state comes from Scripts/lib/provenance.py, the same module Stage D
# uses. Two implementations of "has this been repointed?" would eventually
# disagree, which is the exact failure the concept exists to describe.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "Scripts", "lib"))
import supabase_config  # noqa: E402
from provenance import resolve_state, REPOINTED  # noqa: E402


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
def _probe(label: str, url: Optional[str], session: requests.Session) -> Asset:
    """
    Check that an asset is actually there.

    R9: a gallery that renders a broken <img> is the same silent-failure class the
    pipeline spent a year producing. Absent, unreachable and broken are distinct
    states and the UI says which.
    """
    if not url:
        return Asset(label, None)
    try:
        r = session.get(url, timeout=12, stream=True)
        return Asset(label, url, status=r.status_code,
                     content_type=(r.headers.get("content-type") or "").split(";")[0])
    except requests.RequestException as exc:
        return Asset(label, url, error=type(exc).__name__)


def _entry_from_page(page: dict, session: requests.Session, probe: bool = True) -> Entry:
    p = page["properties"]
    contract_raw = _rt(p.get("Data contract"))
    contract, contract_error = _maybe_json(contract_raw)

    chartid = _rt(p.get("chartid"))
    source_url = _url(p.get("Asset URL"))
    thumb_url = next(iter(_files(p.get("Thumbnail"))), None)
    render_url = next(iter(_files(p.get("Chart Image"))), None)

    mk = (lambda lbl, u: _probe(lbl, u, session)) if probe else (lambda lbl, u: Asset(lbl, u))

    return Entry(
        chartid=chartid,
        page_id=page["id"],
        title=_title(p.get("Asset name")) or chartid,
        asset_note=_rt(p.get("Asset note")),
        original_sql=_rt(p.get("SQL")),
        source_image=mk("Source image", source_url),
        thumbnail=mk("Thumbnail", thumb_url),
        subject=_rt(p.get("Subject")),
        provenance_recorded=((p.get("Provenance") or {}).get("select") or {}).get("name"),
        slug=_rt(p.get("Title")),
        viz_types=_multi(p.get("Viz type")),
        status=_status(p.get("Status")),
        flags={
            "Standard": _check(p.get("Standard")),
            "Subplot": _check(p.get("Subplot")),
            "Time series": _check(p.get("Time Series")),
            "Multi-color series": _check(p.get("Multi-color series")),
        },
        final_sql=_rt(p.get("Final SQL")),
        template_url=_url(p.get("Base Code URL")),
        caveats=[l.strip() for l in _rt(p.get("Caveats")).split("\n") if l.strip()],
        qa_notes=_rt(p.get("QA notes")),
        contract=contract,
        contract_error=contract_error,
        render=mk("Render", render_url),
        last_edited=page.get("last_edited_time"),
    )


def _attach_styling(entry: "Entry", props: dict) -> None:
    entry.source_styling = _styling(props, entry.contract, entry.sql_repointed)


def _query(payload: dict, session: requests.Session) -> list[dict]:
    out, cursor = [], None
    while True:
        body = dict(payload)
        if cursor:
            body["start_cursor"] = cursor
        r = session.post(f"{NOTION}/databases/{PROD_DB}/query", headers=HEADERS,
                         data=json.dumps(body), timeout=45)
        r.raise_for_status()          # R9: never swallow
        data = r.json()
        out.extend(data.get("results", []))
        if not data.get("has_more"):
            return out
        cursor = data["next_cursor"]


def list_entries(only_with_template: bool = True) -> list[Entry]:
    """Index view. Probes thumbnails only -- one request per card, not four."""
    session = requests.Session()
    payload: dict = {"page_size": 100}
    if only_with_template:
        payload["filter"] = {"property": "Base Code URL", "url": {"is_not_empty": True}}
    pages = _query(payload, session)
    entries = []
    for page in pages:
        e = _entry_from_page(page, session, probe=False)
        e.thumbnail = _probe("Thumbnail", e.thumbnail.url, session)
        e.render = _probe("Render", e.render.url, session)
        entries.append(e)
    return sorted(entries, key=lambda e: e.chartid)


def get_entry(chartid: str) -> Optional[Entry]:
    session = requests.Session()
    pages = _query({"page_size": 1,
                    "filter": {"property": "chartid", "rich_text": {"equals": chartid}}}, session)
    if not pages:
        return None
    entry = _entry_from_page(pages[0], session)
    _attach_styling(entry, pages[0]["properties"])
    entry._code = fetch_template(entry.template_url, session)
    return entry


def fetch_template(url: Optional[str], session: Optional[requests.Session] = None) -> Optional[str]:
    """Return the template source, or None. The caller distinguishes None from ''."""
    if not url:
        return None
    session = session or requests.Session()
    try:
        r = session.get(url, timeout=20)
        if r.status_code != 200:
            return None
        return r.text
    except requests.RequestException:
        return None
