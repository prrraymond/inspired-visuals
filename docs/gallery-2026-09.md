# Read-Only Gallery — Build and Findings

**Date:** 2026-09-13
**Against:** `PRD/chartgen-prd-v3.1.md`, Phase 3 — *"Read-only gallery first: it forces a decision
about what a library entry is, while there are three charts to restructure rather than 150."*
**Scope observed:** read-only. No auth, no bring-your-own-data, no editing, no writes to Notion or
Supabase, local dev server only, not deployed.

**The headline finding:** a library entry is not one thing. It is a reverse-engineered
**reference** and a runnable **template** sharing one Notion row, and the moment SQL is repointed
at a real table they describe different subjects. Everything else below follows from that.

---

## 1. Inventory — what an entry actually has

### Notion: 28 / 0 / 10, with no middle

**[VERIFIED]** across all three charts:

| | Count | Fields |
|---|---|---|
| **Populated on all three** | **28** | `chartid`, `Asset name`, `Asset URL`, `Thumbnail`, `Viz type`, `Status`, `Standard`, `Subplot`, `Time Series`, `Multi-color series`, `SQL`, `Final SQL`, `Base Code URL`, `Source code`, `Caveats`, `QA notes`, `Data contract`, `Title`, `Asset note`, `Add Text`, `Add Line`, `Data Filter`, `Default Color`, `Highlight Map`, `Layout Options`, `Sort By`, `Date Added`, `Last edited` |
| **Populated on some** | **0** | — |
| **Empty everywhere** | **10** | `Axis Formatting`, `Chart Image`, `Chart notes`, `Code Preview`, `Customization`, `Dataset`, `Dataset URL`, `Description`, `Final Code URL`, `Theme` |

The absence of a middle bucket is the useful result: the display model needs no per-field
presence logic. Either a field is structurally always there, or it is structurally never there.
That will change the first time a chart is hydrated — `Dataset URL`, `Final Code URL` and
`Chart Image` are Stage D outputs — but today the split is clean.

### Storage and assets

| | CHT-6FBD47 | CHT-85FB02 | CHT-678195 |
|---|---|---|---|
| Source image (`raw/`) | 200, `image/png`, 236 KB | 200, 40 KB | 200, 53 KB |
| Thumbnail (`files/`) | 200 | 200 | 200 |
| Template (`base_code_templates/`) | 200, 5,262 B | 6,326 B | 4,569 B |
| Full code block on the Notion page | 5,262 B | 6,326 B | 4,569 B |
| Contract | 55 × 2, 1 proposal | 66 × 3, 2 proposals | 10 × 2, 1 proposal |
| **Render** | **none** | **none** | **none** |

**No render exists for any entry.** `charts/` contains only the two September 2025 charts
(`CHT-4B4998`, `CHT-F3152E`); `Chart Image` is unset on all three. The PNGs and SVGs produced
during the restore session were local and never uploaded. So the "no render yet" path is not an
edge case to design around — it is the state of **every** entry in the library, which made it the
default path to get right rather than an afterthought.

Two smaller observations: thumbnails and templates are served with `Content-Type: text/plain`
despite being `.jpg` and `.py`. Browsers sniff the images successfully, but it is a latent bug in
the upload path. And `Chart Image` is a Notion `files` property, so a render has to exist in two
places — storage *and* an attachment — which is two chances to diverge.

---

## 2. What was built

`gallery/` — Flask 3.0.3, server-rendered Jinja, no JS build step.

```
gallery/
├── app.py              routes: /  and  /chart/<chartid>
├── library.py          Notion + Supabase reads; the Entry model
├── contract_view.py    contract → human-readable structures
├── templates/          base, index, detail, 404, _asset macros
└── static/style.css
```

**Stack justification, one line:** every credential and both data sources are already wired in
Python in this repo, and a read-only gallery has no client-state problem that would justify a
framework or a build toolchain.

Run with `python3 gallery/app.py` from the repo root — `.env.local` is resolved relative to the
working directory. It refuses to start if a required variable is missing, printing **names only**.

### Verified working **[VERIFIED — live server, all routes exercised]**

| Route | Result |
|---|---|
| `/` | 200, 3 cards, 3 "no render yet" badges |
| `/chart/CHT-6FBD47` | 200, 15,101 B |
| `/chart/CHT-85FB02` | 200, 19,440 B |
| `/chart/CHT-678195` | 200, 14,144 B |
| `/chart/CHT-NOPE` | 404, styled |

### Honest degradation (R9)

An asset is probed, not assumed, and resolves to one of four states — `absent`, `unreachable`,
`broken`, `ok` — each rendered differently:

- **absent** → a hatched panel reading "No render yet / Nothing is recorded for this entry"
- **broken** → "The stored URL returned HTTP 400"
- **unreachable** → "Network error: ConnectionError"
- **fallback in use** → the source image, visibly desaturated, with a `no render yet` pill and
  the sentence "This entry has not been rendered. Showing the source chart it was derived from."

No `<img>` is ever emitted for a URL that has not returned 200. The Assets panel in the sidebar
states every asset's status including content type, so a wrong `text/plain` is visible rather
than merely survivable. `raise_for_status()` on every Notion call; view-level exceptions render a
banner rather than a stack trace or a blank page.

---

## 3. What I wanted that doesn't exist

**A measure column.** The single most-wanted missing field. The contract lists numeric columns but
says nothing about which one the chart is *about*. CHT-85FB02's contract has `year` and `value`,
both numeric, both with an accepted parameter proposal — and the display has no basis for
ordering, emphasising, or de-emphasising either. This is R8 arriving in the UI exactly as
predicted.

It produced a visible artifact: **the gallery displays `baseline 2,018` for the `year` proposal**,
thousands separator and all, because the formatter knows the value is numeric and nothing tells it
the column is a year. I deliberately left that unfixed. Special-casing 1900–2100 would encode
precisely the guess R8 says the data cannot supply, and this project's recurring failure is
inference dressed as observation. A `role` or `semantic_type` per column would fix it properly.

**A render.** Discussed above.

**A one-line summary.** Cards show a curated title and a chart-type tag. What they cannot show is
what the chart *says*. `Asset note` is the closest thing but describes the source chart (see §4).
This is R10's *message conveyed*, and its absence is felt immediately at card size — three cards
already look interchangeable at a glance.

**A reviewed/unreviewed distinction with teeth.** `Status` is a pipeline position, not a quality
statement. All three read `3. Needs hydration`, which tells a browsing human nothing about whether
the entry is any good. R6 defines `reviewed` as renders-plus-passes-validation; nothing records
that verdict yet, so the gallery cannot show it.

**A link from proposal to consumer.** Proposals state edges and a baseline. Nothing connects them
to the template constants they would replace (`CATEGORY_EDGES`, `BASELINE`). The detail view shows
both on one page and leaves the reader to make the connection.

---

## 4. What exists but was useless to display

**The Stage-B styling metadata.** `Add Text`, `Add Line`, `Highlight Map`, `Layout Options`,
`Default Color`, `Sort By`, `Data Filter`, `Axis Formatting` — populated on all three, and I
displayed none of them. They are Gemini-extracted parameters intended as input to Stage D's
prompt, not as reader-facing content:

```
Add Text       [{"text": "The New York Times", "position": "bottom right", "font": {...}}]
Highlight Map  {"Arrests increased": "#f5ebea", "Doubled": "#e4d0ce", "Tripled or more": "#d3b9b7"}
Layout Options {"title": {...}, "legend": {...}, "xaxis": {"gridlines": false, ...}, ...}
Sort By        "Geographical location"
```

Worse than uninteresting, they are **actively misleading now**: `Highlight Map`'s keys are arrest
categories, while the contract describes pupil-teacher ratios. Showing them next to the contract
would assert a relationship that no longer holds.

**`Title`.** Holds the generated filename slug (`categorical-choropleth-usa-labeled`), not a
title. The genuine title lives in `Asset name`. I displayed the slug as monospace secondary text;
the naming is a trap worth renaming at some point.

**Deciles.** Nine per numeric column, essential to derivation, and noise on screen. The display
uses min / q1 / median / q3 / max as a positional bar and drops the rest. They earn their place
in the artifact and not in the view — which is the general shape of the answer to §6.

**`null_fraction`.** Four decimal places of a number that is 0.0 on all three. Collapsed to a
word: `complete` / `n of m rows null` / `empty — every row is null`.

**`all_null`.** Only interesting when `True`, which it never is here. Folded into the same word.

---

## 5. Where the 38-property schema fought me

**It has no notion of an entry's identity.** This is the finding the exercise was meant to force,
and it is sharper than expected. For CHT-6FBD47:

| Field | Subject |
|---|---|
| `Asset name` | "Increase in Arrests by U.S. State" |
| `Asset note` | "…percentage increase in arrests across various U.S. states…" |
| `Highlight Map` | `{"Arrests increased": …, "Doubled": …, "Tripled or more": …}` |
| `SQL` | `SELECT state, percent_increase_arrests FROM arrests_data` |
| **`Final SQL`** | **`SELECT state, pupil_teacher_ratio FROM national_state_view WHERE school_year_start = 2023`** |
| **`Data contract`** | **pupil-teacher ratio, 9.797–22.676, 55 states** |

Everything curated describes the **source chart**. Everything derived describes the **data it now
renders**. These are different subjects, and we created the divergence on all three by repointing
SQL at real tables — the generalisation of the CHT-00DB0F mismatch the PRD records as a
"population of one."

There is no field that says which is primary, no field that marks the divergence, and no field
that records "this template no longer renders its original subject." I could not build a coherent
single-object view, so I stopped trying and made the split explicit: the entry is
**template-primary**, provenance is a labelled sidebar, and a banner states plainly that the page
describes two subjects. Displaying it honestly required inventing a concept the schema does not
have.

**Other friction, smaller:**

- **Two vocabularies for the same idea.** `Viz type` (multi_select, 163 curated options) and
  `Standard` / `Subplot` / `Time Series` / `Multi-color series` (checkboxes) both describe chart
  form. I rendered them as one tag row; the schema keeps them apart for no reason a reader sees.
- **`Status` conflates pipeline position with quality.** A browsing human wants "is this good?";
  the field answers "where is this in the queue?".
- **The contract is a `rich_text` blob.** 1.8–3.2 KB of JSON in a text property. It works, and
  nothing can query into it — filtering the gallery by "has an unreliable proposal" or "has a null
  column" means fetching and parsing every row.
- **`Chart Image` duplicates storage.** Two sources of truth for the same render.
- **Ten dead properties are indistinguishable from ten not-yet-populated ones.** `Theme` and
  `Description` are probably abandoned; `Dataset URL` and `Final Code URL` are pending Stage D.
  The schema does not distinguish them, so the display cannot either.

---

## 6. Does the contract read well to a human?

**Not raw. It needs a rendering, not a second copy.** That is the answer, and I built the
rendering rather than a parallel human-readable artifact.

The contract is a good machine artifact and a poor document, for reasons that are properties of
being a good machine artifact:

| In the artifact | Why it fails on screen | What the view does |
|---|---|---|
| 9 deciles per numeric column | Correct for skew-aware derivation; a wall of numbers to read | Drops them; draws min/q1/median/q3/max as a positional bar |
| `null_fraction: 0.0` | Precision nobody needs at the uninteresting value | One word: `complete` |
| `all_null: false` | Only meaningful when true | Folded into the same word |
| `edges: [13.0, 15.0, Infinity]` | An open interval is not obvious from a sentinel | A bin table: `−∞ – 13`, `13 – 15`, `15 – ∞`, with row counts |
| `occupancy: [16, 19, 20]` | A bare array, disconnected from the bins it counts | A column in that same table, with empty bins highlighted red |
| `reasoning: [...]` | Already prose — the best part of the artifact | Shown verbatim, numbered, expanded by default |

So: **transform, don't duplicate.** A second stored copy would be a second thing to keep in sync,
and the PRD's own record of this project is a list of things that drifted apart. Everything in
`contract_view.py` is computed at request time from the stored artifact; the artifact keeps the
machine's shape.

Two parts of the contract read *better* than expected. The **reasoning lines** are genuinely good
prose and need no transformation at all — storing the justification alongside the value is the
single best decision in the contract design, and it is what makes a derived number defensible on
screen. And **acceptance provenance** displays well, though it exposed something uncomfortable.

### What the display made obvious about acceptance

All four proposals read `accepted`, and all four were accepted by `automation`. Rendered plainly,
"accepted" reads as "reviewed" — which is false. I added an explicit badge, **"never seen by a
person"**, and an amber left border on any proposal accepted by automation.

That is a UI patch over a modelling gap. The PRD's standing caution — *"four auto-accepts are not
evidence the review path works; the human gate has never bound"* — is not merely a process
observation. It has a display consequence: the word `accepted` in the artifact carries a weight it
has not earned, and every surface built on it will have to keep compensating until `reviewed`
exists as a distinct state.

---

## 7. Recommendations

Ordered by how much they unblock.

1. **Decide what an entry is, and record it.** Either the row is template-primary with provenance
   as clearly-labelled history, or a repointed template becomes a new entry that references its
   source. The current state — one row silently describing two subjects — cannot be displayed
   honestly without a banner explaining the contradiction.
2. **Add a semantic role per contract column** (`measure`, `dimension`, `time`, `id`). Fixes R8,
   fixes the `2,018` formatting, and lets any surface order and emphasise columns correctly.
3. **Separate `reviewed` from `Status`.** R6 defines the gate; nothing records its verdict. Until
   it does, `accepted` will keep overclaiming.
4. **Add a one-line message per entry.** R10 has it as *message conveyed*. Cards are
   interchangeable without it — and that is at three entries, not 150.
5. **Upload renders and fix the content types.** Every entry currently falls back. The `text/plain`
   on `.jpg` and `.py` should be corrected in the upload path.
6. **Consider a queryable projection of the contract.** A few extracted columns — row count,
   has-nulls, unreliable-proposal count — would make the gallery filterable without parsing every
   row. Not urgent at three entries; unworkable to retrofit at 150.

---

## Appendix — files and how to run

```
gallery/app.py              Flask app; refuses to start on missing config (names only)
gallery/library.py          Notion + Supabase reads; Entry and Asset models; asset probing
gallery/contract_view.py    contract → display structures (transform, not duplicate)
gallery/templates/          base.html, index.html, detail.html, 404.html, _asset.html
gallery/static/style.css
```

```
python3 gallery/app.py      # from the repo root; http://127.0.0.1:5111
```

Read-only by construction: the module contains no write path to either service.

One bug found and fixed during the build, worth recording because it is the same class the project
keeps hitting: a contract column key named `values` silently resolved to Python's `dict.values`
method in Jinja rather than to the key, producing a 500 on every detail page. Renamed to `sample`.
A template variable that resolves to something plausible but wrong is exactly the failure shape
R9 is about.

---

# Addendum — Acceptance model fixed at the source; styling shown as provenance

**Date:** 2026-09-13

## 1. The acceptance model now carries the distinction

The badge is gone. `accepted` conflated two facts — *a value was chosen* and *a person endorsed
it* — and every surface built on it had to re-derive the second from `accepted_by_type`. The
model now carries both.

### Shape

Two orthogonal fields, and **the word `accepted` is gone entirely** — there is no longer a value
that an automation-only choice could be misread as.

| Field | Answers | Values |
|---|---|---|
| `status` | Has a value been chosen? | `proposed` · `selected` · `rejected` |
| `review` | Has a person endorsed it? | `unreviewed` · `confirmed` · `authored` |

The three states you asked for map cleanly: **[VERIFIED]**

| Path | `status` | `review` | `is_reviewed()` | Label |
|---|---|---|---|---|
| automation chose | `selected` | `unreviewed` | **False** | "chosen by automation, not reviewed" |
| automation chose, person confirmed | `selected` | `confirmed` | **True** | "chosen by automation, confirmed by a person" |
| person chose directly | `selected` | `authored` | **True** | "chosen by a person" |

### API

- `select_parameters(p, by=, actor_type=, reason=, override_unreliable=)` — chooses. Automation
  yields `unreviewed`; a person yields `authored`.
- `confirm_selection(p, by=, reason=)` — the only path from `unreviewed` to reviewed. **It takes
  no `actor_type`**, because automation confirming its own choice is not review. That constraint
  is structural, not policy.
- `reject_proposal(...)` — unchanged in spirit; requires a reason.
- `is_reviewed(p)` / `review_label(p)` — so a surface never re-derives the judgement.
- `selected_parameters(c, col)` — what drives a render.
- `reviewed_parameters(c, col)` — same, but only when a person stands behind it. Use wherever
  *reviewed* is the bar.
- `normalize_proposal(p)` — upgrades an old single-`accepted` artifact. An old `accepted` by
  automation becomes `selected`/`unreviewed`, which is what it always meant and what the old
  shape could not say.
- `SelectionRefused`, aliased as `AcceptanceRefused` for compatibility.

### Policy preserved **[VERIFIED — every path exercised]**

| Attempt | Result |
|---|---|
| automation selects reliable | OK → `unreviewed` |
| **automation selects unreliable** | **refused** |
| **automation selects unreliable with override + reason** | **refused** — the override is human-only, and a script cannot buy its way past it |
| person selects unreliable, normal path | refused |
| person selects unreliable, override, no reason | refused |
| person selects unreliable, override + reason | OK → `authored`, 2 warnings recorded |
| `actor_type="robot"` / empty `by` | refused |
| confirm a `proposed` proposal | refused |
| confirm twice / confirm an `authored` selection | refused |

### Backfill **[VERIFIED by re-read]**

All four live proposals were automation-only and migrated accordingly, with original timestamps
preserved:

```
CHT-6FBD47  ['accepted']             -> [selected/unreviewed]   1,879B
CHT-85FB02  ['accepted','accepted']  -> [selected/unreviewed ×2] 3,353B
CHT-678195  ['accepted']             -> [selected/unreviewed]   1,934B
```

Re-read from Notion: **0 stale keys, no literal `"accepted"` anywhere in any payload.**

### Gallery

Reads `status` and `review` directly; `describe_proposal()` calls `normalize_proposal()` so any
artifact still on the old shape is tolerated rather than silently misread. The badge is replaced
by a state chip carrying `review_label()` and an explicit line:

> **Not reviewed — no person has confirmed this value.**

Section heading changed from "Accepted parameters" to "Parameters", and the hint now states that
chosen and reviewed are separate facts.

---

## 2. Styling fields as provenance

The eight Stage-B fields now appear inside the **Provenance** panel, under
*"Styling extracted from the source chart"*, with a standing note that they describe the original
chart and — when SQL has been repointed — not the data the entry now renders. Empty fields and
`[]`/`{}` are omitted.

**The divergence is marked, not merely displayed.** `Highlight Map` on CHT-6FBD47 carries a
**stale** pill and this note:

> Keys (Arrests increased, Doubled, Tripled or more) come from the source chart's categories.
> The current dataset does not produce them.

The panel opens by default when anything is stale and stays collapsed otherwise, so divergence is
visible without the sidebar becoming noise. Nothing in it is presented as a property of the
template or of the render.

---

## 3. What Stage D does with them — **a live hazard, not cosmetic**

Reconstructed from `hydrate_viz_library_v3.py` without running it or calling a model.
**[VERIFIED — prompt rebuilt from the live row for CHT-6FBD47]**

### Which of the eight feed Stage D

**Seven of eight.**

| Field | In `ALL_PROPS`? | Reaches the prompt |
|---|---|---|
| Add Text, Add Line, Highlight Map, Layout Options, Default Color, Sort By, Data Filter | yes | **yes** |
| **Axis Formatting** | **no** | **never read** — Stage D has no key for it (and it is empty on all three anyway) |

### What the prompt actually says

```
You MUST follow all instructions in the <parameters> section. They are strict requirements.
The dataset has the following columns: ['state_code', 'value']. You MUST ONLY use column
names from this list.
```

The column guard constrains **column names**. The stale content in `Highlight Map` is not column
names — it is *category labels and colours*. Nothing constrains it.

### Does it corrupt the code, or just the styling?

**Neither. It corrupts the meaning, and everything downstream passes.**

The generated script would be valid Python producing a valid Figure. Bin labels are string
literals; a wrong label is not a syntax error. But the parameters block hands the model, as
*strict requirements*, for a chart whose data is now pupil-teacher ratios:

| Parameter | Value | Consequence |
|---|---|---|
| `asset_name` | `"Increase in Arrests by U.S. State"` | the chart gets titled with the wrong subject |
| `highlight_map` | `{"Arrests increased", "Doubled", "Tripled or more"}` | three bins, three colours — and the contract's proposal also has **three** bins, so they align numerically and the labels are taken silently |
| `data_filter` | "States with no significant increase or no data are shown in a neutral color" | an arrests-specific rule implemented against education data |
| `sql` | the original `arrests_data` spec | present alongside `final_sql`, with nothing marking which is authoritative |

The plausible output is a choropleth of teacher ratios, titled *"Increase in Arrests by U.S.
State"*, with a legend reading *Arrests increased / Doubled / Tripled or more*.

**And every existing gate passes it.** `check_dataset` sees 55 rows and no nulls. `check_figure`
sees traces with points. `validate_bins` sees edges inside the range. The render guard inspects
numbers and columns; **nothing inspects label text**. This is the CHT-85FB02 failure class one
step worse: that chart was semantically *dead*, this one would be semantically *false*.

**Verdict: a live hazard for Phase 1.** It fires on exactly the charts the phase produces — every
row whose SQL gets repointed at a newly built table. It is dormant today only because Stage D has
not run since the SQL was rewritten.

Cheapest mitigations, none applied (pipeline left read-only as scoped):

1. **Drop the provenance fields from the prompt when `Final SQL` targets a different table than
   `SQL`.** The divergence is already computable — the gallery computes it.
2. **Never send `asset_name` and `sql` as "strict requirements."** They are provenance; the title
   should come from the data or be left blank.
3. **Extend the review gate to label text** — a rendered title or legend naming a subject absent
   from the contract's columns is the same class of defect as an out-of-range bin edge.

### Two further findings from the reconstruction

**`data_contract` is now 54.6% of the parameters block.** Adding it to `ALL_PROPS` so Stage D
could *write* it also made Stage D *read* it — 2,020 of 5,186 characters. Arguably useful, since
the model gets the real data shape, but unintended, and on a re-hydration it is the *previous*
run's contract, which is a staleness trap of its own.

**Legitimate `False` values are silently dropped.** `build_final_code_prompt` filters with
`if value in [None, "", False]`, so `is_subplot: False` and `is_time_series: False` never reach
the prompt — a chart cannot state that it is *not* a subplot. Because `0 == False` in Python, a
numeric `0` would be dropped too. Sixteen of twenty-three keys survived for CHT-6FBD47; two were
dropped for being legitimately `False`.

---

## Updated recommendations

Superseding §7 where they overlap:

1. ~~Separate `reviewed` from `Status`~~ — **done at the proposal level.** Row-level `reviewed`
   (R6) is still absent; `Status` remains a pipeline position.
2. **Guard Stage D against provenance.** Items 1–3 above. This is the highest-value change on the
   list now, because Phase 1 produces exactly the input that triggers it.
3. **Decide what an entry is** — unchanged and still primary. The stale `Highlight Map` is the
   same problem as the divergent title: one row, two subjects, no field saying which is
   authoritative.
4. **Add a semantic role per contract column** — unchanged. `baseline 2,018` for a year column
   is still displayed as-is, deliberately.
5. **Reconsider `data_contract` in `ALL_PROPS`** — the read was not intended and the payload is
   large and potentially stale.

---

# Addendum 2 — Provenance at the model, and the Stage D hazard closed

**Date:** 2026-09-15

## 1. Schema proposal — two properties

I checked whether an existing empty property could carry the subject, to avoid a hand-added one.
**It can't, safely.** `Description` — the semantically correct name — is already in use on one
row, and that row is `CHT-00DB0F`, the known title/SQL mismatch. The genuinely free properties
across all 400 rows are `Chart notes`, `Customization`, `Axis Formatting`, `Code Preview`,
`Dataset URL`, `Final Code URL`, `Chart Image` **[VERIFIED]** — and repurposing a field whose name
means something else is the trap `Title` already is, holding a filename slug. One of those in the
schema is enough.

| # | Name | Type | Why this one |
|---|---|---|---|
| 1 | **`Subject`** | **Text** | *What the entry renders now*, one line. Nothing in the 38 properties can say it: `Asset name` is the source chart's title, `Asset note` describes the source chart, `Title` holds a slug. It must be authored — no derivation knows what you intend the chart to show. Also closes the gallery's sharpest gap (cards are interchangeable without it) and is R10's *message conveyed*. |
| 2 | **`Provenance`** | **Select** — `Renders source subject` · `Repointed` · `Not yet bound` | The repoint marker. A select rather than a checkbox because the third state is real: **396 of 400 rows have no `Final SQL` at all**, which is not the same as "still original". |

**Why `Provenance` is stored even though it is derivable.** The derivation compares the first
`FROM` table in each statement — a heuristic. It cannot see a repoint that keeps the table and
changes the columns, it takes the first table in a join or CTE, and it cannot see a change of
meaning that leaves the SQL shape intact. Storing the operator's assertion makes the heuristic a
**check against it** rather than the truth — the same assert-vs-derive reconciliation the PRD
proposes for R5 — and makes the state filterable in Notion, which a computed value never is.

`resolve_state()` implements exactly that: a recorded value wins, and a disagreement with the
heuristic is returned rather than silently resolved. The gallery prints it.

Current values, all verified: `CHT-6FBD47`, `CHT-85FB02`, `CHT-678195`, `CHT-00DB0F` →
`Repointed`. The other 396 → `Not yet bound`.

*If you want only one property, take `Subject`.*

## 2. Stage D no longer consumes stale provenance

### The filter

`Scripts/lib/provenance.py` — **one implementation, used by both Stage D and the gallery.** A
second copy would eventually disagree, which is precisely the failure the concept exists to
describe. The gallery's private `_table_of()` was deleted and it now imports the shared module.

`strip_provenance()` removes twelve source-chart keys when an entry is repointed: `asset_name`,
`asset_note`, `asset_url`, `sql`, `data_filter`, `sort_by`, `highlight_map`, `default_color`,
`add_text`, `add_line`, `layout_options`, `axis_formatting`. Dropped keys are printed under
`--why`, never dropped silently.

`asset_url` was added to that list during verification — it points at the source screenshot, and
Stage D renders from data, not from it.

### The identity check

`if value in [None, "", False]` → `if value is None or (isinstance(value, str) and not value.strip())`.

**[VERIFIED]** — `is_subplot: False`, `is_time_series: False` and a numeric `0` now reach the
prompt; `None`, `""` and whitespace-only strings are still dropped. The old form discarded
legitimate `False` because `False == ""` is falsy by membership, and would have discarded `0`
because `0 == False`.

### `data_contract` off the read path

Moved out of `ALL_PROPS` into `WRITE_ONLY_PROPS`. Stage D still writes it; it no longer reads it.

**Did anything need it? No.** It was never referenced by any logic — it was dumped into the
`<parameters>` block and nothing else. The prompt already receives the live column list
(`The dataset has the following columns: [...]`), computed from the CSV this run just fetched,
which is the same information fresh rather than stale. Reading the stored value made the contract
**54.6% of the parameters block**, and on a re-hydration it would be the *previous* run's
contract — describing data this run has not fetched yet.

While wiring this I introduced and fixed one bug worth recording: `extract_property_value()`
handles `title`, `rich_text`, `url` and `checkbox` but not `select`, so the new `Provenance`
property would have read as `None` on every row. `select` and `status` handling added.

## 3. The hazard, closed

Prompt reconstructed from the live rows. **Stage D was not run.** **[VERIFIED]**

| Chart | State | Keys before → after | Chars before → after |
|---|---|---|---|
| CHT-6FBD47 | Repointed | 18 → **8** | 2,025 → **825** |
| CHT-85FB02 | Repointed | 18 → **8** | 2,552 → **889** |
| CHT-678195 | Repointed | 18 → **8** | 1,796 → **744** |

Dropped on every one: `add_line`, `add_text`, `asset_name`, `asset_url`, `data_filter`,
`default_color`, `highlight_map`, `layout_options`, `sort_by`, `sql`.

### What CHT-6FBD47 now sends

```json
{
  "status": "3. Needs hydration",
  "chartid": "CHT-6FBD47",
  "final_sql": "SELECT state AS state_code, pupil_teacher_ratio AS value FROM national_state_view …",
  "base_code_url": "https://…/CHT-6FBD47_base_template.py",
  "is_standard": true,
  "is_subplot": false,
  "is_time_series": false,
  "is_multi_color": true
}
```

Every remaining key is a fact about the template or the data it is bound to. Note `is_subplot`
and `is_time_series` present and `false` — statements the old filter could not make.

### Needles checked directly, all three charts

| Needle | Result |
|---|---|
| `Arrests increased` / `Doubled` / `Tripled or more` | **gone** |
| `Increase in Arrests by U.S. State` | **gone** |
| `arrests_data` (the original spec) | **gone** |
| `The New York Times` (source credit) | **gone** |
| `"row_count"` (the stale contract blob) | **gone** |
| `public_transit_trips`, `Profit and Loss`, `state_finances` | **gone** |

All three: **CLEAN.**

### Non-repointed entries are unaffected

`derive_state(sql, "")` → `Not yet bound` → `repointed=False` → every provenance field retained.
Verified: an unbound entry keeps `asset_name`, `highlight_map`, `chartid`. The filter fires only
where the divergence is real, which matters because 396 of 400 rows are in that state.

## 4. Gallery updated

- Reads `Subject` and `Provenance` when they exist; shows *"No subject recorded — nothing states
  what this entry renders"* when they don't, rather than an empty line.
- The divergence banner now names the resolved state and whether it was **recorded on the row** or
  **derived**, and prints any recorded-vs-derived disagreement.
- Uses the shared `provenance` module; its private copy is gone.

All routes re-verified: index 200, three details 200, unknown 404.

## 5. Left alone, as scoped

The Stage C/D join, batching, and the `exec()` sandboxing question. One thing the fix makes newly
visible and worth queueing: **the review gate still inspects only numbers and columns.** Stripping
provenance removes the known source of false labels, but nothing yet checks that a rendered title
or legend names a subject the contract's columns can support. That check is what would have caught
the hazard from the other side, and it is the natural home for the `Subject` field once it exists.
