# ChartGen — Repair and First Verified Stage C Run

**Date:** 2026-09-12
**Follows:** `docs/recovery-2026-09.md` (call: repair, not rebuild — **the call holds**)
**Scope:** Steps 1–3 as instructed. No Stage C/D database fix, no status-value fix, no key
rotation, no batch beyond `--limit 2`.

**Headline:** Stage C now works end to end, and the path runs all the way to a rendered PNG —
the first PROD-era render this project has produced. But verifying the output against *real* data
surfaced a blocker deeper than anything in the previous two documents: **395 of 396 catalog rows
carry SQL that queries tables which do not exist.**

---

## Verification standard

Everything below was checked independently of the script's own console output, because that
output is exactly what lied before. Bucket state came from SQL against `storage.objects`, not
from the client library. Notion state came from re-reading rows through the API after the run.
Generated code was parsed, executed, and rendered locally. **[VERIFIED]** / **[INFERRED]** tags
carry the same meaning as in the recovery doc.

---

## Step 1 — Config repair

Three lines changed in `.env.local`; prior values retained as labelled comments. Backup taken
first. **[VERIFIED]**

| Variable | Now | Prior value |
|---|---|---|
| `SUPABASE_URL` | `https://sdpvhujlgakikcizaklw.supabase.co` | commented `# [DEAD PROJECT REF tnzqhmecjcdgfoemhfdq — NXDOMAIN]` |
| `SUPABASE_SERVICE_ROLE_KEY` | live-project key (copied from `NEXT_PUBLIC_SUPABASE_ANON_SECRET`) | commented `# [DEAD PROJECT REF …]` |
| `CLAUDE_MODEL` | `claude-opus-5` | commented `# [RETIRED MODEL — retired 2026-02-19]` |

`NEXT_PUBLIC_SUPABASE_ANON_SECRET` left in place as instructed. `SUPABASE_DB_URL_DIRECT` still
points at the dead ref — out of scope, still broken, noted here so it isn't forgotten.

### Verification **[VERIFIED]**

| Check | Result |
|---|---|
| `.env.local` parses | 67 keys, unchanged count |
| `SUPABASE_SERVICE_ROLE_KEY` `ref` claim | `sdpvhujlgakikcizaklw`, role `service_role` |
| `GET /storage/v1/bucket` | **200** — `viz-training-assets`, `public=True` |
| `POST /storage/v1/object/list` (authenticated) | **200**, real objects returned |
| `supabase-py .list()` — the path the scripts use | **OK** |
| `claude-opus-5` reachable | **OK**, `stop_reason: end_turn` |

### Two blockers the config change exposed

Swapping the model surfaced two incompatibilities that no static reading had caught. Both
**[VERIFIED]** against the live API, both authorised and fixed:

1. **Thinking blocks precede text.** `response.content` is `['thinking', 'text']`, so
   `content[0].text` raises `AttributeError`.
   - `generate_base_code_v2.py:109` → `"".join(b.text for b in response.content if b.type == "text")`
   - `hydrate_viz_library_v3.py:180` → same
2. **`temperature` is rejected.** `400 — '\`temperature\` is deprecated for this model.'`
   - `hydrate_viz_library_v3.py:174` → parameter removed

`generate_base_code.py` guards with `hasattr(block, 'text')` and needed neither change — one of
the few respects in which the older script is more robust than its successor.

---

## Step 2 — Stage C reconciliation (no changes made)

Three designs exist, not two. **The uncommitted rewrite landed in `generate_base_code.py`**;
`generate_base_code_v2.py` never had a `data_contract` to lose.

| | `generate_base_code.py` @HEAD | `generate_base_code.py` working tree | `generate_base_code_v2.py` |
|---|---|---|---|
| Source DB | Assets(v2) — **0/649 images resolve** | Assets(v2) — **dead** | **PROD — 400/400 resolve** |
| Prompt | "complete inline pandas DataFrame … ~20–50 rows" | "**Do NOT** create an inline pandas DataFrame" | "**MUST NOT** contain hard-coded data" |
| Output form | runnable script, `fig.show()` | abstract `build_figure(df)` | abstract `build_figure(df)` |
| Return format | strict JSON, 5 keys | strict JSON, 4 keys | **raw Python, no JSON** |
| `data_contract` | **requested + persisted** | **deleted** | never existed |
| `caveats` / `notes` | yes | yes | **neither** |
| `Source code` + code block | yes | yes | **no** |
| `Status` | `draft` | `draft` | **no** |
| Notion props written | 6 + code block | 6 + code block | **3** |
| Storage path | `code/<cid>/<cid>_base.py` | same | `base_code_templates/<cid>_base_template.py` |
| URL TTL | signed 1 yr | public w/ signed fallback | **signed 5 yr** |
| Artifacts in evidence | 507 rows, objects **deleted** | **none ever** | **220 objects, all live** |

Your direction, recorded: the abstract prompt is correct, and `data_contract` should be **derived
from the real dataset with pandas** rather than authored by the model — which dissolves the
conflict flagged as option 3 in the recovery doc. Caveats and notes are the real loss and come
back from HEAD after the smoke test. Nothing was resolved this session.

---

## Step 3 — First run

```
python Scripts/generate_base_code_v2.py --limit 2 --overwrite
```

Targets, determined by replicating v2's selection logic **before** the run: **[VERIFIED]**

| Chart ID | PROD page | Pre-run object | Pre-run size / mtime |
|---|---|---|---|
| `CHT-DACCAB` | `279e89d6…bb58` | `base_code_templates/CHT-DACCAB_base_template.py` | 2,303 B / 2025-10-02 19:20:57 |
| `CHT-6FBD47` | `279e89d6…4e5c` | `base_code_templates/CHT-6FBD47_base_template.py` | 3,581 B / 2025-10-02 19:21:19 |

**The script reported:** `SUCCESS` for both, `Done. Processed 2 charts.`

### A. Did objects actually land? **[VERIFIED — SQL against `storage.objects`]**

| Chart ID | Size | Modified | Verdict |
|---|---|---|---|
| `CHT-DACCAB` | 2,303 → **7,581 B** | 2025-10-02 → **2026-09-12 18:17:04** | **rewritten** |
| `CHT-6FBD47` | 3,581 → **6,428 B** | 2025-10-02 → **2026-09-12 18:17:30** | **rewritten** |

Bucket total stayed 1,079 — correct, since `--overwrite` upserts in place. Both objects fetch
**HTTP 200** at their public URLs, at the new byte counts.

### B. Did Notion actually receive the fields? **[VERIFIED — re-read after the run]**

| Chart ID | `last_edited` | `Base Code URL` | URL resolves |
|---|---|---|---|
| `CHT-DACCAB` | **2026-09-12T18:17:00Z** | signed | **200, 7,581 B** |
| `CHT-6FBD47` | **2026-09-12T18:17:00Z** | signed | **200, 6,428 B** |

The URL Notion holds resolves to the object the run produced, at matching size. That is the
round trip the catalog has never previously closed.

`Caveats`, `Data contract`, `Source code`, `Status`, `QA notes` are all empty — v2's known
lossiness, expected, not a failure. **This run did not lie.** v2's
`create_or_update_code_db_entry()` calls `response.raise_for_status()`, so its Notion write is
actually checked — unlike Stage D's.

### C. Does the generated code parse and execute? **[VERIFIED]**

| Chart ID | `ast.parse` | `exec` | `build_figure` |
|---|---|---|---|
| `CHT-DACCAB` | OK, 7,581 B, defs `_curved_points`, `build_figure` | OK | callable |
| `CHT-6FBD47` | OK, 6,428 B, defs `_assign_categories`, `build_figure` | OK | callable |

Both are well-structured: module docstrings, named placeholder constants, helper functions,
inline guidance on remapping columns. Quality is markedly higher than the September 2025 output.

### D. Does `build_figure(df)` run against the chart's **real** dataset?

**No — because there is no real dataset.** **[VERIFIED]**

Each PROD row carries a `SQL` property that Stage D executes to build the chart's data. Running
them:

```
CHT-DACCAB  SELECT 'signing_document' AS next_action FROM political_events
            WHERE current_action = 'rally_speech' AND actor = 'Donald Trump';
            -> UndefinedTable: relation "political_events" does not exist

CHT-6FBD47  SELECT state, percent_increase_arrests FROM arrests_data;
            -> UndefinedTable: relation "arrests_data" does not exist
```

Tables actually in `public`: `line_daily`, `national_state_view`, `nfl_game_actives`,
`nfl_game_actives_latest`, `nfl_weekly_report`, `station_daily`, `target_districts_view`.

Neither table exists. Nor, as §4 shows, do 307 others.

### E. Does the code work when given data matching its own contract? **[VERIFIED]**

Separating code quality from data availability — a synthetic frame using each template's own
declared placeholder columns:

| Chart ID | `build_figure(df)` | PNG | SVG |
|---|---|---|---|
| `CHT-6FBD47` | **Figure, 4 traces** | **114,149 B** | **129,029 B** |
| `CHT-DACCAB` | **ValueError** | — | — |

**`CHT-6FBD47` is a complete success**, and the rendered PNG is a genuine US choropleth: correct
state geometry, three-bin discrete colouring, per-state annotations (`Texas +31%`, `Fla. +45%`),
muted palette, legend. **This is the first PROD-era rendered chart this project has ever
produced**, and it exercised the entire path — Notion → Claude → storage → fetch → exec →
kaleido → PNG *and* SVG.

One cosmetic defect: the title overlaps the legend.

**`CHT-DACCAB` fails at render with a genuine codegen bug:**

```
ValueError: Invalid value of type 'builtins.str' received for the
'axref' property of layout.annotation.  Received value: 'paper'
    The 'axref' property is an enumeration that may be specified as:
      - One of the following enumeration values: ['pixel']
```

The model emitted `axref="paper"`, which Plotly does not accept — `axref` takes `'pixel'` or an
axis reference. Syntactically perfect, executes fine, **fails only at figure construction.**
Neither parsing nor linting would catch it. This is precisely the class of defect a render gate
exists to catch, and it argues for making a successful render a precondition of `reviewed`
status (PRD R6).

Worth noting: `CHT-DACCAB` is not a chart at all. Its source image is a picture-flow diagram, and
the template faithfully reproduces that — image cards joined by a dotted Bezier arrow. The
library's taxonomy problem (PRD R7) is visible here in miniature.

### F. Column names would not have matched anyway **[VERIFIED]**

Even with `arrests_data` existing, the template would fail:

```
SQL returns      : ['state', 'percent_increase_arrests']
template expects : ['location_column', 'value_column', 'category_column', 'label_column']
-> KeyError: 'value_column'
```

This is the R10 mapping problem — *inside the library*, before any user data arrives. It is also
direct support for your call that `data_contract` should be derived from the dataset rather than
authored by the model: a model-authored contract would have described the placeholders, not the
data, and this mismatch would still be invisible.

---

## Finding: the catalog's SQL is hallucinated

Extracting every table referenced in `FROM` / `JOIN` across all PROD rows and checking each
against the live schema: **[VERIFIED]**

| | Count |
|---|---|
| PROD rows | 400 |
| …with SQL | 396 |
| …whose referenced tables **all exist** | **1** |
| …referencing at least one **missing** table | **395** |
| Distinct table names referenced | **309** |
| Tables that actually exist | **7** |

Most-referenced, none of which exist: `survey_results` (5), `covid_cases` (5), `companies` (4),
`covid_statistics` (4), `covid_stats` (4), `presidential_approval_ratings` (3),
`election_results` (3), `stock_prices` (3), `teen_social_media_usage` (3), `products` (3).

The near-duplicates — `covid_cases` / `covid_statistics` / `covid_stats`, `survey_results` /
`survey_responses`, `presidential_polls` / `presidential_approval_ratings` — are the signature of
per-row generation with no shared schema. Stage B (Gemini) looked at each chart image and invented
plausible SQL against an imaginary warehouse. Nothing ever reconciled it against a real one.
**[INFERRED — the pattern is unmistakable, but I did not read Stage B's prompt to confirm it
never supplied a schema. One read of `notion_chart_annotator_vizlib_v2.py`'s prompt settles it.]**

**Consequence:** Stage D is not blocked by wiring. Fixing the status value and joining Stage C to
Stage D — items 5 and 6 on the recovery doc's Phase 0 list — would leave it failing on 99.7% of
the catalog at `execute_sql_to_csv()`. The two 2025-09-23 renders and the one 2025-10-02 dataset
were presumably the handful of rows whose SQL happened to be satisfiable at the time.

This does not overturn "repair, not rebuild" — Stage C is repaired and demonstrably works. But it
relocates the real work: **Stage D's input needs to be rebuilt**, and that is a data-sourcing
problem, not a code problem.

---

## Finding: the rewrite systematically removed error surfacing

You asked whether `coerce_prop_names()`, the discarded `PATCH` response, and the hardcoded
property names are instances of one pattern. **They are, and there are more.** Counting across
the uncommitted rewrite of `generate_base_code.py` (−551 / +213 lines): **[VERIFIED]**

| Measure | HEAD | Working tree |
|---|---|---|
| `raise_for_status` calls | **3** | **0** |
| `except` blocks | 7 | **11** |
| Function definitions | 28 | 19 |

Every HTTP status check was removed, and exception handlers increased. The full inventory:

| # | Removed / changed | What it surfaced | Consequence |
|---|---|---|---|
| 1 | **`coerce_prop_names()`** deleted | Validated property names against the live schema, mapping via `NAME_FALLBACKS` | Literal names hardcoded → the `"Base code URL"` vs `Base Code URL` bug (B4) |
| 2 | **`get_target_properties()`** deleted | Retrieved and printed the live schema: `[DBG] Target DB properties: …` | No visibility into schema drift at all |
| 3 | **`fetch_bytes()`** → **`_http_get()`** | Had 3 × `raise_for_status()` | Returns `None` on any failure. A 404 image is indistinguishable from a missing URL |
| 4 | **`_sb_upload()`** deleted | `raise RuntimeError("Supabase client not initialized")` | Replaced by `supa_upload_code()` with no client check |
| 5 | **`ensure_storage_scaffold()`** deleted | Pre-flight storage verification | No check that storage is writable before spending an LLM call |
| 6 | **`page_has_base_code()`** deleted | Idempotency guard | Existence now decided solely by `target_page_exists()`, which swallows all exceptions → the 249 duplicates (B7) |
| 7 | `upload_code_to_supabase()` | — | Two `except Exception: pass` around URL minting (`:264`, `:271`); a URL can be returned for an upload that failed |
| 8 | `prepare_image_for_llm()` | — | `except Exception` returns raw bytes labelled `image/jpeg` regardless of actual type |
| 9 | `parse_json_safe()` | — | Returns `None` on malformed JSON; the caller cannot distinguish "no JSON" from "bad JSON" |
| 10 | `target_page_exists()` | — | `except Exception: return None` — a transient Notion error reads as "does not exist" |
| 11 | `main()` per-row handler | — | Bare `except Exception`, prints, continues; run still exits 0 |
| 12 | **`data_contract`** removed from `ClaudeOut` | Pydantic validated its presence | The one field that could have been checked against reality is gone |

**And the same pattern outside that file** — the rewrite is where it is densest, not where it
started:

| # | Location | Issue |
|---|---|---|
| 13 | `hydrate_viz_library_v3.py:285` | Discarded `PATCH` response — **fixed last session** |
| 14 | `hydrate_viz_library_v2.py:297` | Identical discarded `PATCH`, still unfixed |
| 15 | `hydrate_viz_library_v3.py:243` | `requests.get(base_code_url).text` unchecked — a 404 body is injected into the LLM prompt as "base code" |
| 16 | `hydrate_viz_library_v3.py:169-181` | `call_claude_for_code` catches every exception and returns `None`; caller reads it as "LLM returned empty code" |
| 17 | `export_images_to_storage.py:62` | `NameError` on `SUPABASE_PUBLIC_BASE` — unreachable under `--dry-run`, which is why it survived |

Seventeen sites, one pattern: **failures were converted into falsy return values and success
messages.** That is why seven months of work produced 507 catalog rows pointing at objects that
do not exist, 249 duplicates, and a "built and working" list assembled from logs that were
reporting success on rejected writes.

The counter-example is instructive. `generate_base_code_v2.py` — the one script with artifacts to
its name — calls `response.raise_for_status()` on its Notion write. It is the least sophisticated
script in the repo and the only one that has ever reliably produced anything.

---

## Where this leaves Phase 0

**Repair still holds, and Stage C is now repaired and verified.** What changed:

| Recovery-doc item | Status |
|---|---|
| 1. Repoint `SUPABASE_URL` / service key | **DONE, verified** |
| 3. `CLAUDE_MODEL` → `claude-opus-5` | **DONE, verified** (plus two model-compat fixes) |
| 4. Run Stage C′ on 2 rows, confirm 200s | **DONE — objects rewritten, Notion round trip closed, one full render** |
| 5. `STATUS_COMPLETE` → `4. Hydrated` | not started — **and now known to be insufficient on its own** |
| 6. Join Stage C → Stage D | not started — **and now known to be insufficient on its own** |
| 2. Rotate keys | not started — **urgency raised, see below** |

**Newly discovered, not on any prior list:**

- **395/396 rows have unsatisfiable SQL.** Stage D cannot run at catalog scale regardless of
  wiring. Needs a decision: source real datasets, restrict the library to charts with real data,
  or change Stage D's input model entirely.
- **Render-time codegen defects are real and invisible to static checks** (`axref="paper"`).
  A successful render should gate `reviewed`.
- **Model-compat fixes are needed anywhere `content[0].text` or `temperature` appears.**
  `generate_base_code.py:222` still passes `temperature=0.0` and will 400 if run.

### Cheapest next action

**Restore caveats and notes into v2** — your stated next step, and now clearly the right one.
It is additive, it does not touch the Stage D question, and it converts v2 from "produces 3
Notion properties" into the library's actual value. The HEAD prompt's caveats section and
`ClaudeOut`'s `caveats` / `notes` fields port directly; v2 needs the JSON return format the
working-tree prompt already specifies.

Defer the Stage D items (5, 6) until the SQL question has an answer. Fixing them now would buy a
pipeline that runs correctly and then fails on 99.7% of its input.

### Security — escalated

While reviewing the edited `.env.local` this session I used a redaction pattern that did not
match, and **live values for `NOTION_API_KEY`, `CLAUDE_API_KEY`, `GOOGLE_API_KEY`, both Supabase
JWTs, both Postgres passwords, `CENSUS_API_KEY`, `HUGGING_FACE_TOKEN`, and the NYC keys were
printed into the session transcript.** They were already in `.env.local`; the new exposure is
that they now also exist in conversation history. Rotation was explicitly out of scope and was
not performed — but this raises its priority and widens it well beyond the Supabase key.

---

## Artifacts

In the session scratchpad, not the repo:

| File | What |
|---|---|
| `env.local.backup-20260912-140812` | pre-edit `.env.local` |
| `pre_CHT-DACCAB.py`, `pre_CHT-6FBD47.py` | templates as they existed 2025-10-02 |
| `post_CHT-DACCAB.py`, `post_CHT-6FBD47.py` | templates generated this run |
| `render_CHT-6FBD47.png` | **the first PROD-era rendered chart** (114 KB) |
| `run1.log` | script console output |
| `targets.json` | target rows + their SQL |

## Open, deliberately not investigated

- Whether Stage B's prompt ever supplied a real schema (would confirm the SQL-hallucination
  mechanism) — one read of `notion_chart_annotator_vizlib_v2.py`
- Whether the 1 row with satisfiable SQL renders end to end through Stage D
- Whether `CHT-DACCAB`'s `axref` bug is systematic across the 220 existing templates — a
  render sweep would quantify it
- Your two unanswered questions from last session: whether `tnzqhmecjcdgfoemhfdq` exists under
  your account, and whether `NEXT_PUBLIC_SUPABASE_ANON_SECRET` was ever consumed by a Next.js build
