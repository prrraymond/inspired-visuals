# ChartGen — Error Surfacing, Library IP, and the First Real-Data Renders

**Date:** 2026-09-12
**Follows:** `docs/first-run-2026-09.md`
**Scope:** Steps 0–4 as instructed. No Stage C/D join work, no batch runs beyond three named charts.

**Headline:** Stage C now writes the library's IP — caveats, notes, source code, status — into a
single database, and three charts have rendered to PNG and SVG from **real Postgres data**. The
pandas-derived `data_contract` works, and it **prevents** rather than documents: it catches both
the bin-threshold class and the all-null-column class before a figure is drawn. Two of three
charts completed end to end; the third is blocked on a false alarm in verification code I wrote
this session, described in full below.

**Verification standard** unchanged: **[VERIFIED]** = observed directly against a live service
this session; **[INFERRED]** = reasoned from verified evidence.

---

## Step 0 — Housekeeping

- `scratchpad/env.local.backup-20260912-140812` **deleted** (4,085 B). Its only unique content —
  the dead-project values — survives as labelled comments in `.env.local`.
- **No scratchpad directory exists inside the repo**; this session's lives at
  `/private/tmp/claude-501/…`. Added `scratchpad/` to `.gitignore` as a guard;
  `git check-ignore -v` confirms the rule registers.
- **`.env.local` has never been committed.** Verified three ways: `git log -- .env.local` empty,
  `git ls-files --error-unmatch` reports it unknown to git, and no `.env*` path appears as an
  addition anywhere in history. **[VERIFIED]**

---

## Step 1 — Error surfacing restored

Ported into `generate_base_code_v2.py`, the script actually in the run path.

### `coerce_prop_names()` + `get_db_properties()`

Reads the live Notion schema and validates every property name before writing. Called once at the
top of `main()`, so a mismatch fails **before** an LLM call is paid for.

Two deliberate departures from the HEAD original:

1. **It raises.** HEAD ended with `# else: drop silently`, which is the same silent-failure class
   the port exists to remove. Writing a subset of intended fields and reporting success is the
   defect, not the remedy.
2. **Collision detection.** Two intended properties resolving to one target now raises rather than
   letting one silently overwrite the other.

Plus a case-insensitive last resort, so case drift auto-corrects loudly instead of hard-failing.

Verified against both live schemas: **[VERIFIED]**

| Case | Result |
|---|---|
| `"Base code URL"` — the literal B4 bug | **auto-corrected → `Base Code URL`, announced** |
| Unknown property | **raises**, listing all available names |
| `Caveats` + `QA notes` → PROD (pre-schema-change) | **raises** — both collapsed to `Chart notes` |

### `fetch_bytes()`

Replaces the unchecked `requests.get(image_url).content`. Raises on non-200 and on empty bodies;
retries once with `%20` for the unencoded spaces in `raw/` filenames. Previously a 404 image was
base64-encoded and shipped to the model as though it were a chart.

### Upload verification

`upload_to_storage()` confirms the object exists at the expected byte count **before** minting a
URL. This is the mechanism that let 507 rows point at `code/` objects that never landed.

*This one bit me — see "A bug I introduced" below.*

### `parse_json_strict()`

Raises rather than returning `None`, so "no JSON" and "malformed JSON" are distinguishable.

### Deliberately left alone

`hydrate_viz_library_v2.py:297` (superseded), `hydrate_viz_library_v3.py:243` and `:169-181`
(Stage D, not run this session), `export_images_to_storage.py:62` (`NameError`, not in the run
path), and all 12 sites in `generate_base_code.py` (reads the orphaned Assets(v2) DB; cannot run).
HEAD's `ensure_storage_scaffold()` and `page_has_base_code()` were not ported — the first is
redundant now that upload self-verifies, the second guards an idempotency path `--overwrite`
deliberately bypasses.

---

## Step 2 — Library IP restored, consolidated on PROD

### The database question, settled

Every Notion database this repo references: **[VERIFIED]**

| Env var / source | Database ID | Title | Rows |
|---|---|---|---|
| `NOTION_DATABASE_ID` | `25ce89d6…0fa813` | **Viz Asset Library (v2)** | 649 |
| `NOTION_PROD_DATABASE_ID` | `276e89d6…5e5546` | **Viz library** ← PROD | 400 |
| `NOTION_TARGET_DATABASE_ID` *(absent from env; hardcoded in 6 files)* | `25ae89d6…71ab8c` | **Visualization Code Templates** | 724 |
| `NOTION_NFL_DATABASE_ID` | `a6980677…153bb1` | Weekly NFL Report — Database | 4,275 |
| `NOTION_NFL_STATS_DATABASE_ID` | `270e89d6…f043de` | Weekly NFL Stats Report | 1,869 |

"Code Templates" and "Assets(v2)" are **different databases**. `viz_gallery/CLAUDE.md` gives the
correct ID and title for Assets(v2) but labels the variable `NOTION_PROD_DATABASE_ID` — the ID and
title agree with each other; the variable name is the error. Its `?v=` value is a saved-view ID,
not a database. **This mislabelling is the likely reason the first schema change landed on the
wrong database.** Worth correcting.

### STANDING FINDING — the caveat corpus is orphaned from its subjects

Chart ID namespaces are **completely disjoint**: **[VERIFIED — literal, case-insensitive, and
stripped comparison all return 0]**

```
PROD ∩ Assets(v2)          =   0
PROD ∩ CodeTemplates       = 217
CodeTemplates ∩ Assets(v2) = 258
```

Code Templates is two disjoint cohorts in one table:

| Cohort | Chart IDs | Caveats | Data contracts | Belongs to |
|---|---|---|---|---|
| Sept 2025 | 258 | **258** | **253** | **Assets(v2)** |
| Oct 2025 | 217 | **0** | **0** | **PROD** |

Of the 217 Code Templates rows whose chartid exists in PROD, **zero** have caveats, data
contracts, or source code. **PROD's 399 charts had never had caveats generated — not once.**

So "restore the IP" could never mean *migrate*; the 253 contracts and 2,305 caveat lines describe
charts that do not exist in PROD, because IDs were regenerated when PROD was created.

**Not a write-off.** The corpus remains re-linkable: both cohorts' charts derive from source
images, and the 450 objects under `raw/` are keyed by original filename. Matching Assets(v2)
chartids to PROD chartids by **image hash or source filename** would reconnect 2,305 human-grade
caveat lines to live charts. Recorded as a deliberate option, not scheduled.

### Schema changes

Added by hand to **Viz library** (PROD), now 37 properties: `Caveats`, `QA notes`, `Source code`,
all `rich_text`. **[VERIFIED]** *(The first attempt landed on Assets(v2), which still carries
three empty stray properties — harmless, removable.)*

`4. Complete` deliberately **not** added. Instead `hydrate_viz_library_v3.py:45` now defaults to
`"4. Hydrated"` — what Stage D actually produces, already an option, leaving `5. Complete` free
for reviewed-and-done. Verified valid against the live Status options. **[VERIFIED]**

### What Stage C now writes

Six properties plus one page code block, every name through the resolver:

| Intended | Target | Type | Content |
|---|---|---|---|
| `Base Code URL` | `Base Code URL` | `url` | signed, 5-year TTL |
| `Source code` | `Source code` | `rich_text` | first 1,800 chars |
| `Status` | `Status` | `status` | `3. Needs hydration` |
| `Caveats` | `Caveats` | `rich_text` | newline-joined list |
| `QA notes` | `QA notes` | `rich_text` | model notes |
| `Title` | `Title` | `rich_text` | `filename_suggestion` |

Plus the **full untruncated template** as a page code block — what made the September work
recoverable when its storage objects vanished.

**A reversal.** `Asset name` was approved as the title target and is **wrong**. That
recommendation assumed v2 was *creating* rows; now that it *updates* existing PROD rows,
`Asset name` holds the curated chart titles (`"Increase in Arrests by U.S. State"`). Writing there
would have destroyed 400 of them. No title is written; `filename_suggestion` goes to `Title`
(`rich_text`, empty on every row, previously discarded). `Asset name` was also **removed from the
`Title` fallback chain**, so a future schema change can't silently redirect onto it.

`data_contract` is **not** requested from the model, per your direction.

### Code-block idempotency

`append_code_block` → `write_code_block`: lists children (paginated), deletes existing python code
blocks, appends one captioned `stage-c:generated`, re-counts, and **raises if the result isn't
exactly 1**. Deletions are printed.

Scratch-page test, three consecutive writes: **[VERIFIED]**

```
initial   0 blocks → write#1  1 → write#2  1 → write#3  1
surviving block: caption='stage-c:generated', content ends '# v3'  (latest)
```

Scratch page archived afterwards.

---

## Step 3 — The four real tables

| Table | Rows | Grain | Notes |
|---|---|---|---|
| `national_state_view` | 2,142 | **state × school year** | 57 states × 38 years (1986–2023); `state` is **2-letter USPS**, matching Plotly `locationmode="USA-states"`; **no lat/lon**; 47 rows with NULL `state` |
| `station_daily` | 111,664 | station × date | 428 stations, 5 boroughs, 2024-12-15 → 2025-09-04 |
| `nfl_weekly_report` | 7,434 | player × week | 2,540 players, 32 teams, 18 positions, 2 weeks; `hometown_state` also 2-letter |
| `line_daily` | **0** | — | **empty** |

### CATALOG-LEVEL FINDING — `station_daily` is three columns emptier than it looks

**[VERIFIED]**

| Column | Non-null |
|---|---|
| `entries` | 111,664 / 111,664 (100%) |
| `borough` | 111,664 / 111,664 (100%) |
| **`exits`** | **0 (0.0%)** |
| **`ridership_proxy`** | **0 (0.0%)** |
| **`lines`** | **0 (0.0%)** |

My first attempt at the transit chart used `SUM(ridership_proxy)` and returned `None` for every
month. `entries` works (Dec 2024 = 52.1M, Jan 2025 = 100.3M, Mar 2025 = 109.9M). Any SQL written
against `exits`, `ridership_proxy`, or `lines` will produce an empty chart, not an error.

### CATALOG-LEVEL FINDING — `line_daily` is empty

0 rows, 3 columns. **Anything routed at `line_daily` is dead until it is loaded.** No chart can be
served from it, and a query against it succeeds while returning nothing — the same silent-failure
shape as the null columns above.

### CATALOG-LEVEL FINDING — SQL/title subject mismatch: population of one

**[VERIFIED]** Exactly **1** of 396 rows has SQL referencing a real table: `CHT-00DB0F`, whose SQL
returns NFL players by hometown city while its title reads *"Mentions of the presidential election
on second-quarter earnings calls."* Running it produces a coherent-looking chart of the wrong
subject. Correctly dropped from the Step 4 picks.

The risk population for this failure is exactly the set of rows whose SQL has been repointed at
available data — currently one. **It will grow as you work through the SQL spec**, so the check is
worth keeping: *does this row's SQL still describe the chart its title names?*

A lexical scan (content-word overlap between title and SQL) flagged 79 rows at zero overlap and 81
at one, but manual review shows most are artifacts — `sp500_index` vs *"S&P 500 this year"* scores
zero and is a perfect match. **The lexical metric does not measure subject agreement and should
not be used as one.** Recorded so the number isn't mistaken for a finding.

### Candidate list, ranked by rewrite cost

| Tier | Chart | Type | Table | Change |
|---|---|---|---|---|
| **0** | ~~CHT-00DB0F~~ | Vertical Bar | `nfl_game_actives` | none — **dropped, subject mismatch** |
| **1** | **CHT-6FBD47** | Choropleth | `national_state_view` | table + column swap |
| **1** | CHT-2AAEE9 | Choropleth | `national_state_view` | identical 2-column shape |
| **1** | **CHT-85FB02** | Small Multiples Bar | `national_state_view` | **grain matches exactly** (year × state × value) |
| **1** | CHT-78D5B8 | Horizontal Bar | `national_state_view` | two measures, filtered |
| **2** | **CHT-678195** | Line Chart | `station_daily` | add `date_trunc` + `SUM` |
| **2** | CHT-39A2C5 | Small Multiples Slope | `national_state_view` | two-year self-join |
| **3** | CHT-57C5CA, CHT-C7F641, CHT-18D5A0, CHT-B2A7D9, CHT-F81196 | — | — | real rewrite |

**Not servable:** `CHT-DC56F1`/`CHT-070C8C` (need a city dimension), `CHT-DF8A7D` (needs income
data), anything routed at `line_daily`.

### Hidden data requirements — the lat/long class generalised

| Chart | Requirement the SQL wouldn't reveal | Verdict |
|---|---|---|
| CHT-412D39, CHT-7DB9E0, CHT-D853CD | Symbol/dot maps need **lat+lon, non-optional** | **exclude — no real table has coordinates** |
| CHT-B2A7D9, CHT-F81196 | Dumbbells need two measures on a **comparable scale**; `teachers_fte_sum` vs `enrollment_sum` differ ~20× | renders, semantically wrong |
| CHT-85FB02, CHT-39A2C5, CHT-18D5A0 | Small multiples need a **bounded panel count**; unfiltered gives 57 | needs explicit filter |
| CHT-FA8898 | Needs a **per-row array**, not scalar rows | structural mismatch |
| CHT-57C5CA | Needs a **pivoted wide frame** | structural mismatch |

Verified for CHT-6FBD47/85FB02/678195 (templates in hand); **[INFERRED]** from chart type for the
rest.

---

## Step 4 — Results per chart

### Verification matrix

| Check | CHT-6FBD47 | CHT-85FB02 | CHT-678195 |
|---|---|---|---|
| Object in storage (**SQL truth**) | 5,262 B @ 19:11:45 | **6,784 B @ 19:13:22** | 4,569 B @ 19:12:28 |
| Public URL fetch | **200** | **200** | **200** |
| Notion row re-read | **6 props + 1 code block** | **NOT WRITTEN** | **6 props + 1 code block** |
| `Base Code URL` resolves | **200** | — not set | **200** |
| `Status` | `3. Needs hydration` | `2. In progress` (unchanged) | `3. Needs hydration` |
| Caveats / QA notes / Source code | 480 B / 476 B / 1,800 B | 0 / 0 / 0 | 555 B / 384 B / 1,800 B |
| `ast.parse` + `exec` | **OK** | **OK** | **OK** |
| SQL executes on real Postgres | **55 rows** | **66 rows** | **10 rows** |
| `build_figure()` on real data | **OK** *(after contract fix)* | **OK** | **OK** |
| PNG / SVG | **162,944 B / 193,150 B** | **72,116 B / 38,254 B** | **65,232 B / 7,711 B** |

Everything in that table was checked independently of the script's console output.

### CHT-6FBD47 — choropleth — **rendered, after the contract caught a defect**

`SELECT state, percent_increase_arrests FROM arrests_data` →
`SELECT state AS state_code, pupil_teacher_ratio AS value FROM national_state_view WHERE school_year_start = 2023`.
Written to `Final SQL`; your original `SQL` left untouched as the spec.

First render attempt **failed**: `KeyError: 'category'`.

**Cause — template non-determinism.** This morning's template declared
`category_column = "category"  # OPTIONAL … derived from value if absent`. The template
regenerated tonight from the *same image* **requires** a pre-binned `category` column and does not
derive it. **Two runs of the same chart produced templates with different data contracts.**
**[VERIFIED — both templates on disk]** That is a significant property of a library built by
regeneration: the data requirement is not stable across runs, which argues for pinning a reviewed
template rather than regenerating it.

The contract caught it — see the validator section. With `category` supplied from the contract's
own quartiles, it rendered: **3 traces, PNG 162,944 B, SVG 193,150 B**, a correct 55-state
choropleth of pupil-teacher ratio.

### CHT-85FB02 — small multiples — **rendered, and semantically dead**

66 rows, 6 states × 11 years, grain matching exactly. Rendered **6 panels, 11 bars each, correct
states and years, PNG 72,116 B**.

**And every bar is identical in height and colour.** The template ships `BASELINE = 100` and
`SECOND_GRIDLINE = 200`; the real values span 12.5–17.7. All 66 bars sit far below the baseline,
so all render "below" (green), on an axis dominated by a 0–200 range where the real variation is
invisible.

**This is the most important result of the session.** It passed every structural check —
SQL executed, columns matched, code parsed, `build_figure` returned a `Figure`, PNG and SVG were
produced at plausible sizes. Nothing short of the contract catches it.

Its Notion row was **not written** (see below), so PROD carries no claim about this chart.

### CHT-678195 — line chart — **rendered cleanly**

`SELECT month, trips FROM public_transit_trips` →
`SELECT date_trunc('month', date)::date AS month, SUM(entries) AS trips FROM station_daily GROUP BY 1`.

10 monthly points, Dec 2024 – Sep 2025. **2 traces, PNG 65,232 B, SVG 7,711 B.** A correct,
well-formed line chart with regime-split shading and `80 million` axis formatting.

One contract-detectable caveat not in the caveats: **the last month is partial.** Sep 2025 holds
4 days, giving 5.8M against a 91M mean — a real outlier that reads as a collapse. A
last-period-completeness check belongs in the contract.

---

## `data_contract` — derived from data, and preventive

`Scripts/lib/data_contract.py`. Per your spec, per column: dtype, non-null, nulls, null fraction,
distinct, and an `all_null` flag; numeric columns get min/max/mean/std and q1/median/q3; temporal
get range; categorical get cardinality plus **actual values at ≤25 distinct**, else a sample; plus
row and column counts.

Example (`CHT-6FBD47`, abridged):

```json
{"name":"CHT-6FBD47","row_count":55,"column_count":2,
 "columns":[
  {"name":"state_code","dtype":"object","kind":"categorical","non_null":55,"nulls":0,
   "distinct":55,"all_null":false,"cardinality":55,
   "sample_values":["AK","AL","AR","AZ","BIE"]},
  {"name":"value","dtype":"float64","kind":"numeric","non_null":55,"nulls":0,
   "distinct":55,"all_null":false,
   "stats":{"min":9.797,"q1":12.686,"median":14.314,"q3":16.371,"max":22.676,"mean":14.757}}]}
```

### Your question: would it have caught `CATEGORY_EDGES = [100, 200, inf]`?

**Yes — and it prevents rather than documents.** **[VERIFIED]**

```
real 'value': min=9.797  q1=12.686  med=14.314  q3=16.371  max=22.676

CATEGORY_EDGES=[100, 200, inf]    REJECTED: every bin edge is above the data maximum (22.676);
                                            all 55 rows collapse into the first bin
                                  REJECTED: the quartile spread lands entirely in one bin —
                                            the chart will be single-coloured
[1, 2, inf]                       REJECTED: every bin edge is below the data minimum
[13, 17, 900, inf]                REJECTED: bin edge 900 falls outside [9.797, 22.676]
                                            and splits nothing
[13, 17, inf]                     OK — bins span the distribution
```

`validate_bins()` returns a list of problems; empty means usable. **A template can call it before
it draws.** That is the difference you named.

It generalises to the null class without modification:

```
validate_bins(station_daily, 'ridership_proxy', …)
   → ["column 'ridership_proxy' exists but is 100% NULL (500 rows)"]
validate_bins(station_daily, 'entries', …)          → []   (no problems)
```

And to the missing-column class, which is what saved CHT-6FBD47:

```
template requires : ['state_code', 'value', 'category']
dataset provides  : ['state_code', 'value']
→ MISSING: ['category']    # prevents the KeyError build_figure raised at render time
```

Applied to CHT-85FB02 with its shipped `BASELINE=100`:

```
REJECTED: every bin edge ([100, 200]) is above the data maximum (17.657);
          all 66 rows collapse into the first bin
REJECTED: the quartile spread lands entirely in one bin —
          the chart will be single-coloured
```

**The contract predicted, from the data alone, the exact visual failure the render produced.**

**Answer to your question:** yes, a rendering template can validate its own parameters against the
contract before drawing. Three checks cover everything seen so far —
`required_columns_present()`, `validate_bins()`, and the `all_null` flag. The natural next step is
to make passing them a precondition of `reviewed` status (PRD R6), so a template cannot enter the
library while its shipped parameters are incompatible with any real dataset.

---

## A bug I introduced

CHT-85FB02's run failed with:

```
RuntimeError: Upload reported success but no object exists at
'base_code_templates/CHT-85FB02_base_template.py'.
```

**The object had uploaded correctly** — 6,784 B at 19:13:22, confirmed by SQL. My Step 1 upload
verification called `supabase-py`'s `.list(folder)`, which **pages at 100 by default**;
`base_code_templates/` holds 220 objects, and `CHT-85FB02` isn't in the first page. `CHT-6FBD47`
and `CHT-678195` happened to be, which is why they passed.

Fixed: the check now searches for the single object rather than scanning the folder. Verified
against objects at both ends of the 220-object prefix, and against a fabricated name that
correctly reports missing. **[VERIFIED]**

Two things worth stating plainly. The failure was in the **safe direction** — a false alarm that
aborted before the Notion write, so PROD carries no false claim about CHT-85FB02, and the run
exited non-zero rather than reporting success. That is the behaviour the whole Step 1 exercise was
for, working correctly on the wrong input. But it is still a defect I added while removing
defects, and the irony is worth recording: **a verification routine that pages silently is the
same failure class it was written to catch.**

**CHT-85FB02's Notion row is therefore unwritten.** Its template is in storage and renders. Per
your standing instruction not to fix-and-retry without telling you first, I have **not** re-run
it. One command completes it:

```
python Scripts/generate_base_code_v2.py --only CHT-85FB02 --overwrite
```

---

## State after this session

| | |
|---|---|
| PROD rows with Stage C output | **2 of 400** (CHT-6FBD47, CHT-678195) |
| Charts rendered from real Postgres data | **3** (PNG + SVG each) |
| Charts with a pandas-derived contract | **3** |
| Cumulative renders ever produced by this project | 2 (Sept 2025) + 1 (this morning) + **3 tonight** |
| Catalog rows with satisfiable SQL | 1 → **4** |

## Open

1. **Re-run CHT-85FB02** — one command, awaiting your go-ahead.
2. **Contract → Notion.** The three contracts are on disk as JSON; nothing writes them to PROD yet.
   PROD has no `Data contract` property (Code Templates does). Adding one as `rich_text` is the
   natural next schema change.
3. **Template non-determinism.** Same image, two runs, different data requirements. Pin reviewed
   templates rather than regenerating them.
4. **`validate_bins` as a review gate** — PRD R6.
5. **Correct `viz_gallery/CLAUDE.md`**, which mislabels the Assets(v2) ID as
   `NOTION_PROD_DATABASE_ID` and probably caused the misdirected schema change.
6. **Re-link the orphaned corpus** by image hash or `raw/` filename — 2,305 caveat lines and 253
   contracts currently describing charts that no longer exist in PROD.
7. **Credential rotation** — still outstanding, still widened by the transcript exposure recorded
   in `first-run-2026-09.md`.

---

# Addendum — CHT-85FB02 completed, and the validator made load-bearing

## CHT-85FB02 — completed

Re-run with the paging fix in place. Verified independently: **[VERIFIED]**

| Check | Result |
|---|---|
| Object in storage (SQL truth) | 6,326 B @ 2026-09-12 20:03:28 |
| Public URL | **HTTP 200**, 6,326 B |
| Notion row | **6 properties**, `Status='3. Needs hydration'`, `Base Code URL` resolves 200 |
| Caveats / QA notes / Source code | 639 B / 442 B / 1,800 B |
| `Title` | `faceted-diverging-bar-small-multiples` |
| Code blocks on page | **exactly 1**, caption `stage-c:generated` |
| Parse / exec | OK, `build_figure` callable |
| Real data | 66 rows × 3 cols |
| Render | **6 traces, PNG 56,625 B, SVG 34,362 B** |

**All three picks are now complete.** PROD holds Stage C output for 3 of 400 rows.

**One unexplained discrepancy, recorded rather than rationalised.** The re-run printed
`Removed 1 existing code block(s)`, but verification an hour earlier reported 0 blocks on that
page, and the first run aborted at upload — before any Notion write. I checked for duplicate
rows: PROD has 400 rows and **399 distinct chartids with zero duplicates**, and each of the three
charts resolves to exactly one page with exactly one code block. The end state is correct and
verified; the intermediate transition is not explained by the evidence I have. Most likely Notion
block-children read consistency, but I did not confirm it and am not asserting it.

---

## 1. Guard against template non-determinism

`--overwrite` now **refuses** rows at or past review. A reviewed template, the SQL validated
against it, and the contract derived from that SQL's result are a matched set; regeneration is not
deterministic, so silently replacing the template breaks the pairing with no signal.

```python
PROTECTED_STATUSES = {"4. Hydrated", "Needs Review", "5. Complete"}   # NOTION_PROTECTED_STATUSES
```

Checked **before** the image fetch and the model call, so a refusal costs nothing. `--force`
overrides. Refusals are collected and printed as a block at the end, not just inline.

Verified by temporarily promoting `CHT-678195` to `5. Complete`: **[VERIFIED]**

```
Processing chart: CHT-678195
  - REFUSED: status is '5. Complete', at or past review. Its template, SQL and contract
    are a matched set; regenerating breaks the pairing. Pass --force to override.

REFUSED 1 chart(s) at or past review (use --force to override):
   CHT-678195     status='5. Complete'
Done. Processed 0 charts, 0 failed, 1 refused.
```

No `Model returned` line — it refused before spending anything. Status restored to
`3. Needs hydration` afterwards.

---

## 2. `Scripts/lib/render_guard.py` — precondition, not report

`check_render(contract, …)` raises `ContractViolation` **before** `build_figure` is called;
`render_guarded(build_figure, df, contract, …)` wraps the pair so the guard cannot be skipped by
accident. All problems are collected before raising, so one run reports every incompatibility
rather than the first.

Checks, each traceable to an observed failure:

| Check | Failure it prevents |
|---|---|
| required columns | `CHT-6FBD47`'s regenerated template needed `category`; raised `KeyError` at render |
| all-null columns | `station_daily.ridership_proxy` renders an empty chart, not an error |
| bin edges vs range | `CATEGORY_EDGES = [100, 200, inf]` against 9.8–22.7 |
| baseline vs range | `BASELINE = 100` against 12.5–17.7 |
| facet count vs layout | small multiples with more panels than the layout supports |

Live results: **[VERIFIED]**

```
CHT-6FBD47   ContractViolation — build_figure never called
   - required column(s) ['category'] absent; dataset provides ['state_code','value']
   - every bin edge ([100, 200]) is above the data maximum (22.676); all 55 rows
     collapse into the first bin
   - the quartile spread lands entirely in one bin — the chart will be single-coloured

CHT-85FB02
   - baseline 100 is above the data maximum (17.657); every value falls on one side
     of it and the chart reads as uniform

station_daily
   - required column 'ridership_proxy' is 100% NULL (300 rows)
```

---

## 3. From veto to derivation

`derive_parameters(contract, value_column, n_bins=3, method=…)` proposes edges from the
contract's quantiles and a baseline from the median, rounded to a human-looking precision.

**A correction made mid-task.** The first rounding implementation targeted ~6 steps across the
range — fine for axis ticks, far too coarse for thresholds. It snapped a quartile of 12.686 to
12.0 and turned a balanced split into 9/39/7. Rewritten to target 8–25 steps, so rounding is
cosmetic rather than semantic.

**A limitation the comparison exposed.** Equal-frequency binning needs the 33rd/67th percentiles,
which the contract did not carry — only q1/median/q3 — so the first version interpolated across
min..max and ignored skew, producing 25/23/7. `data_contract.py` now records **deciles** for every
numeric column, and derivation interpolates between recorded quantiles instead. **The contract's
statistics determine which derivations are possible**, which is an argument for recording more
than the minimum.

### Your question: do derived parameters match what you'd pick by hand?

**They beat the hand pick.** **[VERIFIED]**

**CHT-6FBD47** — n=55, range 9.797–22.676, ideal equal-frequency split ≈ [18, 18, 19]

| Source | Edges | Occupancy |
|---|---|---|
| **derived (quantile)** | **[13.0, 15.0]** | **[16, 19, 20]** |
| derived (quartile) | [13.0, 16.0] | [16, 24, 15] |
| hand-picked earlier this session | [13, 17] | [16, 27, 12] |

The derived lower edge matches the hand pick exactly (13.0); the upper edge differs, and the
derived split is **closer to balanced than the one I chose by eye**.

**CHT-85FB02** — n=66, ideal ≈ [22, 22, 22]

| Source | Edges / baseline | Occupancy |
|---|---|---|
| **derived (quantile)** | **[14.0, 16.0]**, baseline **15.0** | **[18, 27, 21]** |
| derived (quartile) | [14.0, 16.5], baseline 15.0 | [18, 36, 12] |
| template default | [100, 200], baseline 100 | **[66, 0, 0]** |

### Rendered proof

Same chart, same data, same template — only the baseline changed, from the template's shipped
`100` to the derived `15.0`:

| | Before | After |
|---|---|---|
| Baseline / gridline | 100 / 200 | **15.0 / 16.0** |
| Render | 66 identical flat bars, one colour, no readable variation | **AR and SD above the median, CO/KY/MN below, IA at it — with year-over-year movement visible** |
| PNG | 72,116 B | 59,541 B |

`derived_CHT-85FB02.png` in the scratchpad is the comparison. The chart went from structurally
perfect and semantically dead to genuinely informative, with **no change to the template or the
data** — only parameters derived from the contract.

`CHT-6FBD47` likewise renders under the guard with derived edges `[13.0, 15.0]`:
**PNG 162,465 B, SVG 193,150 B**, occupancy 16/19/20.

### What this means for scale

Per-dataset tuning was the manual step standing between 3 charts and 50. On these two it is now
automatic and better than hand-tuning. Two honest caveats before trusting it broadly:

- **n=2.** Both test cases are the same metric from the same table. Skewed, multimodal, or
  small-n distributions have not been tested.
- **Equal-frequency is not always right.** Bins at natural breaks (0, 100%, a policy threshold)
  matter more than balance for some charts. The derivation proposes; it should not be the only
  input.

The guard, by contrast, is safe to apply everywhere now — it only ever refuses, and every refusal
so far corresponded to a real defect.

## Open, updated

1. ~~Re-run CHT-85FB02~~ — **done**.
2. **Write contracts to Notion.** Three exist as JSON on disk; PROD has no `Data contract`
   property yet. Adding one as `rich_text` is the next schema change.
3. **Wire the guard into Stage D**, where `generate_chart_image()` currently `exec()`s and renders
   with no precondition.
4. Correct `viz_gallery/CLAUDE.md`; re-link the orphaned corpus; rotate credentials — all unchanged.

---

# Addendum 2 — Contract in the pipeline, guard in Stage D, derivation stressed

## 1. Contract written as a matter of course

**Property to add to PROD** (`Viz library`, `276e89d6…5e5546`): **`Data contract`**, type **Text**
(`rich_text`). Same name as the property already on Code Templates, so the resolver and the
vocabulary stay consistent. Sizing: the three existing contracts are 531–757 B compact — one
`rich_text` chunk each; a 25-column contract would be ~8 KB across 5 chunks, well inside Notion's
limits.

**Wired into Stage D**, which is the only stage that has the data. `hydrate_viz_library_v3.py`
now, immediately after `execute_sql_to_csv`:

- reads the result set into a DataFrame and calls `derive_contract()`
- calls `propose_parameters()` for every non-null numeric column and attaches each as a
  **proposal**, never as an applied value
- writes the whole contract to `Data contract` in the same atomic PATCH as the rest of the row

So every hydrated row carries a contract derived from its own real result set. No model authorship
anywhere in that path.

## 2. `render_guard` wired into Stage D

`generate_chart_image()` was the last place a semantic failure could pass as success. It now has a
gate at each end of the `exec`:

```python
if contract is not None:
    check_dataset(contract)        # PRE  -- raises ContractViolation
...
exec(compile(helper + final_code, ...), ns)
fig = next((v for v in ns.values() if isinstance(v, Figure)), None)
check_figure(fig, chart=chartid)   # POST -- raises ContractViolation
```

| Gate | Refuses |
|---|---|
| `check_dataset` | an empty result set (`line_daily` has 0 rows) or any 100%-NULL column (`station_daily.exits` / `ridership_proxy` / `lines`) — both render blank rather than raising |
| `check_figure` | a Figure with no traces, or whose every trace carries no points — a successful render of nothing |

## 3. Propose, never decide — made structural

`propose_parameters()` returns a record whose `status` is `"proposed"` and stays that way until
`accept_proposal(proposal, by=...)` is called. It carries its own reasoning and its own caveat:

```json
{"status": "proposed", "value_column": "v", "method": "quantile",
 "edges": [13.0, 15.0], "baseline": 14.0, "reliable": true, "warnings": [],
 "accepted_by": null, "accepted_at": null}
```

```
reasoning:
  - 55 rows; 'v' spans 9.796674 to 22.675998.
  - method=quantile: edges at the n-quantiles, so each bin holds roughly equal row counts.
  - raw edges [13.2861, 15.0446] rounded to [13.0, 15.0] at a precision the 12.8793-wide
    range justifies.
  - baseline 14.0 is the median (14.314) -- the value half the rows sit either side of.
  - resulting bin occupancy [16, 19, 20] against an even split of ~18 each.
caveat: Derived from the distribution alone. Natural breaks -- zero, 100%, a policy
        threshold, a round unit -- beat equal-frequency balance for some charts, and
        nothing in the data reveals which. Review before use.
```

Nothing downstream can mistake a derived default for a reviewed decision.

## 4. Stress test — failure modes first

Five distributions the derivation had not seen, compared against a naive equal-width split.
**[VERIFIED against live Postgres]**

### Failures found

**A. Rounding pushed an edge outside the data, producing an empty bin.**
Entries-per-station (n=428, skew **+5.19**, range 2.5e4–3.4e7): derived edges came out as
**`[0.0, 2000000]`** → occupancy **`[0, 293, 135]`**. Naive equal-width managed `[420, 6, 2]`.
Both are bad; the derivation was *worse on the low end* because the rounding grid, computed from
the range, snapped a low quantile to zero. Same defect on players-per-city: `[0.0, 2.0]`.

**B. The baseline was off by 67%.** Same column: the true median 1.19e6 rounded to **2.0e6**, and
the range check accepted it because 2.0e6 sits inside the data. A grid derived from the *range* is
wrong for a threshold far below it.

**C. Ties make equal-frequency binning impossible.** Players-per-hometown-city: **22 distinct
values across 1,256 rows**, median = 1. No set of edges splits that evenly. Not a rounding bug —
a property of the data.

**D. Integer columns got fractional edges.** After fixing A, the ties case produced edges
`[1.0, 1.67]` on whole-number counts — both inside the range, and the middle bin **empty**.
The range checks cannot see this.

### The safety property that held throughout

**The guard rejected the derivation's own bad output**, every time, before any render:

```
skewed count   guard REJECTS: bin edge(s) [0.0] fall outside the data range
                              [24745.0, 34350168.0] and split nothing
long-tail      guard REJECTS: bin edge(s) [0.0] fall outside the data range [1.0, 34.0]
                              baseline 0.0 is below the data minimum (1.0)
```

Propose-then-veto is self-consistent. A bad proposal cannot reach a render.

### Fixes applied

| Failure | Fix |
|---|---|
| A — edge outside range | rounding falls back to the unrounded value whenever the rounded one leaves `(min, max)` |
| B — baseline error | rounding falls back to 3 significant figures past a 10% shift relative to the threshold's own magnitude |
| C — ties | `warnings` + `reliable: false` when distinct values < 2×bins, or distinct/rows < 0.05 |
| D — empty bin | occupancy checked; any empty bin, or >4:1 imbalance, sets `reliable: false` |

### After the fixes

| Case | n | skew | occupancy (ideal ≈ n/3) | naive | baseline err | reliable |
|---|---|---|---|---|---|---|
| entries per station | 428 | +5.19 | **[143, 150, 135]** (~143) | [420, 6, 2] | 0.3% | true |
| monthly totals | 10 | −2.07 | **[3, 5, 2]** (~3) | [1, 1, 8] | 1.0% | true |
| players per city | 1256 | +5.73 | **[823, 0, 433]** (~419) | [1241, 11, 4] | 0.0% | **false** |
| players per position | 18 | +0.28 | **[6, 6, 6]** (~6) | [8, 7, 3] | 3.0% | true |
| pupil/teacher ratio | 55 | +1.01 | **[16, 19, 20]** (~18) | [25, 24, 6] | 2.2% | true |

Baseline error is now ≤3% everywhere, down from 67%. Derivation beats naive equal-width on **all
five**, including the heavily skewed count it originally failed. The one case it still cannot
serve — heavy ties on an integer count — is **correctly flagged unreliable with two warnings**,
rather than silently proposed.

### What this means for trusting it at scale

**Safe now:** the guard. It only ever refuses, it caught every defect in this session including its
own derivation's, and it is now wired into both Stage C's render path and Stage D's exec path.

**Trustworthy with review:** derivation on continuous columns — ratios, sums, counts with high
cardinality. Five distributions across three tables, spanning skew −2.1 to +5.7 and n from 10 to
1,256, all beat naive.

**Still not solved:** low-cardinality integer counts. Correctly flagged, not fixed. Integer-aware
edge snapping would be the next step; it was not attempted here.

**Structural, not fixed by any of this:** natural breaks. Nothing in a distribution reveals that
zero, 100%, or a policy threshold is the meaningful boundary. That is why proposals stay
`"proposed"`.

## Open, updated

1. **Add `Data contract` to PROD** as Text — the only manual step outstanding.
2. Backfill contracts for the three hydrated charts once the property exists.
3. Integer-aware binning for low-cardinality counts.
4. `viz_gallery/CLAUDE.md` correction; orphaned-corpus re-link; credential rotation — unchanged.
