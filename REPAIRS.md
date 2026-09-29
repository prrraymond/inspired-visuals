# Repairs

A running log of defects found and what was done about them. Newest first.
Each entry says what was wrong, what changed, and how it was checked — so a
later reader can tell a fix from a story about a fix.

---

## 2026-09-29 — product review notes

Source: *Plotshift GH Issues* (Google Doc), five review notes taken while
clicking through the workspace. All five are fixed and verified in a browser.

### 1. Small multiples drew "Above baseline" underneath "Below baseline"

**Was:** `CHT-85FB02` reversed its y-axis, so values *above* the baseline
pointed down and the two annotations sat on the wrong sides of the chart. The
reversal came from the source chart, whose measure was one where lower was
better — a subject assumption a reusable template must not carry.

**Now:** the axis runs the conventional way (`y_range = [lo - pad, hi + pad]`).
Above-baseline bars point up and the labels follow, with no change to the
annotation code — they were already positioned relative to the data.

**Checked:** `layout.yaxis.range` is ascending; "Above baseline" resolves to
y≈+21.8 and "Below baseline" to y≈−23.7.

### 2. Table headers floated away from their values

**Was:** every grid header was left-aligned while numeric cells were
right-aligned, so across a wide column the heading and its numbers looked
unrelated.

**Now:** the header carries the column's own kind class and numeric headers are
right-aligned with their values. Kind labels also read as English
(`yes / no` rather than `boolean`).

**Checked:** every `th.k-number` computes `text-align: right`; asserted in
`tests/acceptance_flow.py`.

### 3. The second grey line was unexplained

**Was:** the baseline and a reference gridline one step above it were drawn as
identical grey rules, and the only clue was a bare tick reading `115`.

**Now:** the baseline is solid and stronger (`COLOR_BASE`, width 1.4); the
reference line is dotted and light. The step is a named, editable
**Gridline step** control that says what it is for.

**Checked:** changing it to `20` moves the tick text from `105 / 115` to
`105 / 125`.

### 4. Nothing said how the background shading was set

**Was:** `CHT-678195` shades a "before" and an "after" band either side of
`SPLIT_X`, which defaulted to `None` — the template then silently split at the
middle row. The single most important parameter of the chart was invisible.

**Now:** a **Breakpoint** control. It shows the date the chart was actually
drawn with, explains that the bands change there, and moving it moves the
shading. This is the first use of a general mechanism — `controls` in
`gallery/catalog.py`, resolved by `chartgen.resolve_controls`, applied by
`render_local.render(constants=...)` — for template constants that change the
chart but that nothing exposed.

The automatic value is computed here and then passed in *explicitly*, so the
template's own fallback branch never runs and the number on screen cannot drift
from the number used.

**Checked:** default shows `2024-01-01` and the band boundary is
`2024-01-01`; setting `2023-07-01` moves the boundary to match; unparseable
input falls back to the automatic value and says why.

### 5. "What is the column called object?"

**Was:** the entry page printed the pandas storage dtype raw, so a column of
state codes was labelled `object` — which reads as a column *called* object.

**Now:** `contract_view.plain_dtype` maps storage types to what the column
holds (`object`/`category`/`string` → text, `int64`/`float64` → number,
`datetime64[ns]` → date, `bool` → yes / no). The raw dtype is still shown, in
developer view, where it is useful.

**Checked:** `object` appears zero times on the entry page and once with
`?dev=1`; asserted in `tests/acceptance_flow.py`.

### 6. `git push` worked but `gh` refused the repository

**Was:** the `origin` URL was `https:///github.com/prrraymond/inspired-visuals.git`
— three slashes, so the host was empty. Git tolerated it by following a
redirect; `gh` could not parse it and reported "none of the git remotes
configured for this repository point to a known GitHub host".

**Now:** `origin` is `https://github.com/prrraymond/inspired-visuals.git`.

### 7. The acceptance test was flaky, and one check tested the wrong page

**Was:** two problems in `tests/acceptance_flow.py`, both found while verifying
the fixes above.

Edits are debounced before they are sent, so waiting on "is a request in
flight?" could return before one had even started — the title check passed or
failed depending on timing. And the check for finding 5 ran on the *workspace*,
which never printed storage types; the bug was on the entry page, so it would
have passed without testing anything.

**Now:** every assertion polls the outcome it is asserting, with a timeout, so
a failure is a real failure. The dtype check runs on the entry page, and also
asserts the raw dtype is *still* shown in developer view.

**Checked:** three consecutive clean runs, 42 checks each.

### Not fixed, and why

- **The fixed `CHT-85FB02` template is not in Supabase storage.**
  `sdpvhujlgakikcizaklw.supabase.co` has no DNS record today; every other host
  resolves. The project was *paused* rather than deleted once before, and
  nothing here distinguishes the two, so no conclusion is drawn. The fix is in
  the Notion code block and the `Source code` property, and in
  `gallery/cache/templates/`. **Re-upload to storage when the host answers** —
  until then `Base Code URL` serves the pre-review template to anything that
  isn't using the local cache.

---

## 2026-09-29 (later) — Supabase project not serving

**Reported:** images missing in Notion; public storage URLs broken.

**Not a pipeline problem, and not fixable by re-running it.** Verified:

| Check | Result |
|---|---|
| `sdpvhujlgakikcizaklw.supabase.co` | **no DNS record** |
| Pooler, with the project's own credentials | `FATAL (ENOTFOUND) tenant/user postgres.sdpvhujlgakikcizaklw not found` |
| `SUPABASE_URL` / both JWTs / `SUPABASE_DB_URL` | all four name the same project — no drift |
| The one other ref in the config (`SUPABASE_DB_URL_DIRECT`) | a different project; resolves, but has no `viz-training-assets` bucket (HTTP 400 on three known object paths) |
| Catalog exposure | **801 asset URLs across all 400 rows** point at the unreachable project; every one |
| Recoverable from Notion instead | `Source code` 3/400 · `Final SQL` 4/400 · `Data contract` 3/400 |
| Local copies of the source images | 11 image files in the whole repo, against ~220 objects in the bucket |

**Why re-running the pipeline cannot help.** Stage A reads the source images
*from* `viz-training-assets/raw/`. The bucket is the pipeline's **input**, not
only its output. With the project unreachable there is nothing to read, and no
local corpus to re-upload from.

**A paused project and a removed one are indistinguishable from outside** —
both lose the DNS record and both drop out of the pooler's tenant routing. This
project was paused once before and the state was wrongly read as deletion, so
no conclusion is drawn here. The state has to be read from the Supabase
dashboard. If it is paused, resuming restores the objects and all 801 URLs at
once, with no pipeline run and no API spend.

**Added:** `Scripts/check_assets.py` — checks that the configuration names one
project (the drift that has bitten twice is now a checkable fact, since a
Supabase JWT carries the ref it was issued for), that the project answers, and
that each catalog asset URL resolves. Exits non-zero, so it can gate a pipeline
run. It reports today's outage correctly.

---

## 2026-09-24 — course correction: library and workspace

Reframed the prototype around choosing and making a chart rather than around
what the pipeline knows. Library cards show the template rendered against its
own demo data; the detail page became a workspace (chart, data grid, chart
text, settings). Full account in the session notes under `docs/`.

Defects found and fixed along the way:

- **A guard refusal returned an HTML 500**, so the browser reported
  `Unexpected token '<'` instead of the accurate message behind it.
  `ContractViolation` is now a refusal the page renders, and `/api/*` never
  returns HTML.
- **Widening the colour bins turned the highest-valued state grey.** The
  template hard-codes three colours; a fourth band fell through to the
  "no data" grey. The ramp is resampled to the band count, preserving the
  template's own colours exactly at three.
- **The legend read "Category A / B / C"**, which does not decode a map. Bands
  are named by their range, from one function
  (`render_guard.band_labels`) that the legend and the settings panel share.
- **`CHT-85FB02` shipped `PROFIT` / `LOSS` / `RATIO`** — subject-specific
  strings in a reusable template. Replaced with canonical placeholders; all
  three templates now pass the caption gate.
- **Preview PNGs went stale** when the render pipeline changed, because only
  the template and the data were fingerprinted. The pipeline's own source is
  part of the fingerprint now.
