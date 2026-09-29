# DataViz — Claude Code Project Guide

## Project Purpose
Build a curated library of production-grade Plotly chart templates, each reverse-engineered
from a real published visualization and annotated with structural caveats and a data contract
derived from its real dataset. Notion is the catalog; Supabase holds assets and the Postgres
warehouse; the Python pipeline in `Scripts/` does the work.

`viz_gallery/` additionally holds a Claude Code analysis workflow that reads chart images and
writes communication-focused "Visual Case" guidance. It is separate from the codegen pipeline —
see **Analysis workflow** below.

## Directory Structure
```
DataViz/                    ← git root; repo CWD
├── Scripts/                ← Python pipeline
│   ├── lib/                ← data_contract.py, render_guard.py, supabase_config.py,
│   │                         caption_gate.py, input_check.py, template_iface.py
│   ├── archive/            ← superseded script versions
│   ├── education/ mta/ nfl_actives/ nfl_weekly_archive/   ← unrelated workstreams
│   └── *.py                ← pipeline stages (see below)
├── gallery/                ← the Flask app: library, workspace, render path
├── viz_gallery/            ← analysis workflow (this file's directory)
│   ├── .claude/skills/     ← analyze-viz-image, synthesize-viz-library, write-visual-cases
│   ├── .claude/commands/   ← viz-library-analysis orchestrator
│   └── analysis-outputs/   ← per-run skill outputs (currently empty — never run)
├── docs/                   ← audit / recovery / restore / first-run reports
├── PRD/                    ← product requirements
├── generated/plotly/       ← 253 legacy generated templates (Sept 2025)
├── data/ outputs/ test_data/ tests/
└── .env.local              ← all credentials (gitignored, never committed)
```

## Tech Stack
| Layer | Tool |
|---|---|
| Catalog / CMS | Notion REST API v1 (`2022-06-28`) |
| Chart→code vision | **Claude** (Anthropic SDK) — Stage C |
| Image metadata / annotation | **Gemini** — Stages A and B only |
| Alt text | OpenAI `gpt-4o-mini` — `alt_text_generate.py`, not wired in |
| Storage | Supabase Storage, bucket `viz-training-assets` (**public**) |
| Warehouse | Supabase Postgres (psycopg v3, via the connection pooler) |
| Rendering | Plotly + Kaleido (`kaleido<1.0`; 1.0 removes `pio.kaleido.scope`) |
| Env config | `.env.local` in the repo root |

> **Two Supabase projects exist and only one is current.** See *Supabase projects*
> below before running anything that writes.

Both Claude and Gemini are in use. Stage C's vision call is Claude; Gemini is used by
`bootstrap_supabase_to_notion_v2.py`, `notion_chart_annotator_vizlib_v2.py`, and
`discover_chart_schema.py`.

## Notion Databases
Three databases exist and are easy to confuse. **Check the title before making schema changes.**

| Env var | Title | Rows | Role |
|---|---|---|---|
| `NOTION_PROD_DATABASE_ID` | **Viz library** | 400 | **The live catalog.** Source and target for the pipeline. |
| `NOTION_DATABASE_ID` | Viz Asset Library (v2) | 649 | Superseded predecessor. **All 649 image URLs are dead.** |
| `NOTION_TARGET_DATABASE_ID` | Visualization Code Templates | 724 | Legacy code store. Not written to any more. |

**Viz library** is the one with `SQL` and `Final SQL`; Viz Asset Library (v2) has neither and has
no `Status` property at all. That is the quickest way to tell them apart.

Chart IDs are disjoint between Viz library and Viz Asset Library (v2) — they were regenerated,
so nothing links a row in one to a row in the other.

### Viz library — key properties
`chartid`, `Asset name` (title — **the curated chart name; never overwrite**), `Asset URL`,
`Thumbnail`, `SQL`, `Final SQL`, `Status`, `Viz type` (multi_select), `Standard` / `Subplot` /
`Time Series` / `Multi-color series` (checkboxes), `Base Code URL`, `Source code`, `Caveats`,
`QA notes`, `Data contract`, `Title` (rich_text — holds the generated filename slug),
`Dataset URL`, `Final Code URL`, `Chart Image`, `Code Preview`, plus styling fields
(`Layout Options`, `Highlight Map`, `Add Text`, `Add Line`, `Default Color`, `Sort By`,
`Data Filter`, `Axis Formatting`, `Theme`).

### Status values
`Status` is a Notion **status** property, so options cannot be created through the API — they
must be added by hand in the UI. The valid options are:

`1. Intake` · `2. In progress` · `3. Needs hydration` · `4. Hydrated` · `Needs Review` · `5. Complete`

There is no `4. Complete`. Stage D writes `4. Hydrated`.

## Pipeline Stages
| Stage | Script | Reads | Writes |
|---|---|---|---|
| A. Intake | `bootstrap_supabase_to_notion_v2.py` | Supabase bucket images | Viz library rows at `1. Intake`, thumbnails (Gemini) |
| B. Annotate | `notion_chart_annotator_vizlib_v2.py` | Viz library by status | structured params (Gemini) |
| — | human review / SQL authoring | | `2. In progress` |
| C. Base codegen | `generate_base_code_v2.py` | Viz library + chart image | template → storage; `Base Code URL`, `Source code`, `Caveats`, `QA notes`, `Title`, `Status = 3. Needs hydration`, full code block on the page (Claude vision) |
| D. Hydrate | `hydrate_viz_library_v3.py` | rows at `3. Needs hydration` | runs `Final SQL` → dataset CSV, final code, rendered PNG, `Data contract`, `Status = 4. Hydrated` |

Storage layout in `viz-training-assets`: `raw/<original filename>` (source images),
`files/<cid>/<cid>_thumb.jpg`, `base_code_templates/<cid>_base_template.py`,
`datasets/<cid>/<cid>.csv`, `charts/<cid>/<cid>_chart.png`.

`generate_base_code.py` (no `_v2`) reads Viz Asset Library (v2) and therefore cannot fetch a
working image. Use `generate_base_code_v2.py`.

## Data contracts and the render guard
`Scripts/lib/data_contract.py` derives a contract from the **real dataframe** — per column:
dtype, non-null/null counts, distinct, `all_null`; per numeric column: min/max/mean/std,
quartiles and deciles; per categorical: cardinality and values when low. It is never authored
by the model.

`Scripts/lib/render_guard.py` turns that contract into preconditions:
- `check_render(...)` / `render_guarded(...)` — required columns, all-null columns, bin edges
  and baselines against the real range, facet counts. Raises `ContractViolation` **before**
  `build_figure` runs.
- `check_dataset()` / `check_figure()` — Stage D gates around the `exec`: refuse an empty result
  set or an all-NULL column, and refuse a Figure with no traces or no points.
- `derive_parameters()` / `propose_parameters()` — propose bin edges from quantiles and a
  baseline from the median, with reasoning attached. Proposals carry `status: "proposed"` and a
  `reliable` flag.
- `accept_proposal(by=..., actor_type=...)` — acceptance requires an identity **and** a kind
  (`human` / `automation`). Automation may never accept a proposal flagged unreliable; a human
  may only with `override_unreliable=True` and a recorded reason.

## Environment Variables (`.env.local`)
Names only — never print values from this file.

**Required by the pipeline:** `NOTION_API_KEY`, `NOTION_PROD_DATABASE_ID`, `NOTION_DATABASE_ID`,
`CLAUDE_API_KEY`, `CLAUDE_MODEL`, `GOOGLE_API_KEY`, `GEMINI_MODEL`, `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`, `SUPABASE_DB_URL`.

**Read with a code default, absent from `.env.local`:** `NOTION_TARGET_DATABASE_ID`
(hardcoded fallback), `SUPABASE_BUCKET` (`viz-training-assets`), `SIGNED_URL_TTL`,
`NOTION_STATUS_READY_FOR_GENERATION`, `NOTION_STATUS_COMPLETE`,
`NOTION_STATUS_AFTER_BASE_CODE`, `NOTION_PROTECTED_STATUSES`, `STORAGE_PROVIDER`,
`CLAUDE_TIMEOUT`, `LLM_MAX_SIDE`, `NOTION_VERSION`, the `NOTION_PROP_*` / `SRC_PROP_*` /
`TGT_PROP_*` families.

**Not present — the script needing it cannot run:** `OPENAI_API_KEY` (`alt_text_generate.py`).

`.env.local` also carries credentials for unrelated workstreams (NFL, MTA/NYC, Census, BEA,
HuggingFace).

## Supabase projects
Two projects exist. Confusing them is not a hypothetical — it has already cost the catalog
every one of its asset URLs.

| Ref | State | Role |
|---|---|---|
| `tnzqhmecjcdgfoemhfdq` | **current** | The live warehouse: `311_daily` (~985k rows), `acs_b25013_tenure_edu`, `government_spending_nipa`, `nfl_game_actives`, and the `viz-training-assets` bucket (made public 2026-09-29, currently empty). |
| `sdpvhujlgakikcizaklw` | **old, paused** | Where the pipeline wrote until 2026-09. Holds the ~220 source screenshots and thumbnails. Paused, so its subdomain does not resolve and its pooler tenant is gone. |

As of 2026-09-29 `SUPABASE_URL` and all three JWTs still name the **old** project, while
`SUPABASE_DB_URL_DIRECT` names the current one. Repointing needs API keys issued for
`tnzqhmecjcdgfoemhfdq` — a key from one project never works against another.

**A Supabase JWT carries its project `ref` as a public claim**, so a mismatch between
`SUPABASE_URL` and the keys is provable rather than something to notice.
`Scripts/lib/supabase_config.py` does that check; it runs in `library.check_credentials()`
(the gallery shows it as a banner) and in `Scripts/check_assets.py`:

```
python3 Scripts/check_assets.py --all --why    # config + every catalog asset URL
```

A paused project and a removed one are **indistinguishable from outside** — both lose the
DNS record and drop out of the pooler's tenant routing. Read the state from the dashboard;
do not infer it. That inference was drawn wrongly once already (see `docs/recovery-2026-09.md`).

## Analysis workflow (`/viz-library-analysis`)
A separate Claude Code workflow that analyzes chart *images* for communication quality, not code.

| Stage | Skill | Mode | Output |
|---|---|---|---|
| 1 | `analyze-viz-image` | parallel, one subagent per chart | `01-analyze-[chartid].md` |
| — | CHECKPOINT 1 | user review | |
| 2 | `synthesize-viz-library` | sequential | `02-synthesize-full.md` |
| — | CHECKPOINT 2 | user review | |
| 3 | `write-visual-cases` | sequential | `03-visual-cases-full.md` |

**Status: never run.** `analysis-outputs/` holds only `.gitkeep`. It targets Viz Asset Library
(v2), whose images are all dead, so it would fail at the download step. See
`docs/analysis-workflow-2026-09.md` before using it.

Requires the Notion MCP server, which is configured for this project.

## Code Conventions
- `argparse` with `--dry-run`, `--why` (verbose), `--limit`; Stage C adds `--only`, `--overwrite`,
  `--force`.
- **Fail loudly.** Check every HTTP status; never return `None` on error where a raise is
  possible; never let a bare `except` convert a failure into a success message. A run that hits
  errors must exit non-zero.
- Resolve Notion property names against the live schema (`coerce_prop_names`) rather than
  trusting literals — names are case-sensitive and a mismatch rejects the whole PATCH.
- Notion validates a PATCH atomically: one bad property rejects every field in that update.
- Notion rich_text elements cap at 2000 chars — chunk at 1800.
- Current Claude models reject `temperature` and return thinking blocks before text; extract with
  `"".join(b.text for b in response.content if b.type == "text")`.
- Pin `kaleido<1.0`.

## Working Notes
- `Asset name` in Viz library holds the curated chart title. Stage C deliberately does not write
  it; generated slugs go to `Title`.
- Most rows' `SQL` references tables that do not exist yet — it is a **spec** written ahead of the
  data, progressively being built out. Treat it as intent, not as broken code.
- `station_daily.exits`, `.ridership_proxy` and `.lines` are 100% NULL; use `entries`.
  `line_daily` is empty.
- `.env.local` has never been committed and must stay that way.
