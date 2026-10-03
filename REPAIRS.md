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

## 2026-10-03 — old catalog archived; Stage A proven on two rows; full run started

**Archived all 400 old rows** after re-verifying the backup matched them
(400 rows, 396 with SQL, every live row present in the backup). 400 archived,
0 failed, 0 live rows remaining. Reversible from Notion's trash for 30 days.

**Switched to Flash** at the user's prompting — `gemini-2.5-pro` was only ever
the value in `.env.local`, and a title plus a type plus one sentence per image
is a Flash task. First attempt failed usefully: `gemini-2.5-flash` is in the
model listing but answers **404 "no longer available to new users"** on a real
call. Google's own error names `gemini-3.8-flash`; it is pinned explicitly so
runs are reproducible, and it answers a vision call.

**The preflight trusted the listing, which was wrong.** `--check` now makes a
real `generateContent` call against the configured model instead of looking it
up — the listing and the truth disagreed on the very first try.

**Smoke test:** `--limit 2 --why` → 2 created, 0 failed. Both rows verified in
Notion: status `1. Intake`, source image serving `image/png`, thumbnail
`image/jpeg`. One title is "Blank Image" because `baseball.png` is a clip-art
icon, not a chart — the triage pass in Notion is what removes those.

---

## 2026-10-03 — Stage A hardened before the 746-image run

Three ways `bootstrap_supabase_to_notion_v2.py` could fail without saying so,
all fixed before it is pointed at the full corpus:

- **A failed Notion write exited 0.** `create_notion_page` caught every
  exception and printed it. The run would finish "successfully" having written
  nothing. It raises now, the failure is counted, and the process exits
  non-zero if any image failed.
- **A failed duplicate check created duplicates.** `check_if_chart_exists`
  returned `None` on any Notion error — indistinguishable from "no such row" —
  so a transient 5xx mid-run would have created a second row for an image that
  already had one. It raises now and stops the run; re-running is safe because
  existing rows are skipped by chart ID.
- **No retry on rate limits.** 746 sequential Gemini calls will meet a 429 or a
  503. Those are retried with backoff, four attempts; any other status is
  reported with its body and the image is counted as failed.

Also added `--check`: runs the preflight — Supabase config consistency, Gemini
key and model availability, Notion database reachability — and exits. Against
the current dead key it fails in 2.6 seconds instead of after the first
download, and it names the target database (`Viz library`) so the wrong-DB
mistake made twice before is visible before any write.

---

## 2026-10-03 — corpus uploaded; three findings before Stage A can run

**Done:** 746 unique screenshots uploaded to `raw/` in the current project,
every one verified against the object listing. `backups/viz-library-*.json`
holds the 400 Notion rows as read before any overwrite.

### 1. Every PNG was stored as `text/plain`

All four live scripts passed `{"contentType": ...}` to `storage3`, which reads
the key `"content-type"`. The unknown key was dropped without a word and the
default applied. Fixed in the four scripts on the current path; the archived
v1 scripts still carry it and are left alone.

Re-uploading with the right key corrected the stored type (746 × `image/png`)
but not the edge cache: Supabase's CDN kept `text/plain` for objects that had
been fetched before the fix, and neither `upsert` nor delete-and-recreate
purged it. **The blast radius is three objects** — the ones probed by hand
before the re-upload. A random sample of 12 untouched objects all served
`image/png` on a cache MISS. Those three will refresh on the CDN's schedule;
the bytes behind every URL are correct PNGs regardless.

### 2. Chart IDs collide by design, so the old rows must be archived first

`generate_chartid` is SHA-256 of `raw/<filename>`, and all 400 existing rows
regenerate to their stored ID exactly. Stage A skips an image whose ID already
exists in Notion. Run as-is, the 206 images that match an old filename would be
**skipped** and left pointing at the paused project. Archiving the 400 rows is
therefore a precondition, not just a preference.

### 3. The Gemini key is rejected

`GOOGLE_API_KEY` is well-formed (39 chars, `AIza` prefix) but
`generativelanguage.googleapis.com` answers `API key not valid`. Not a paste
error — revoked, rotated, or issued for a different Google project. Stage A's
only Gemini use is a title, a chart type and a one-sentence description per
image. The Anthropic key authenticates (`claude-opus-5` listed), and Stage C
already uses it for vision, so the same job can be done there.

**Not done, deliberately:** the archive. The database is not being emptied
until the refill path is confirmed working.

---

## 2026-10-03 — the AWS step was skipped; where the images actually are

**Question raised:** was an S3 bucket also in play?

**No.** `Scripts/export_images_to_storage.py` carries an `S3Driver`, but its
three configuration lines are **commented out** (`AWS_REGION`, `S3_BUCKET`,
`S3_PUBLIC_BASE`), so `S3Driver.__init__` raises `NameError` before it reaches
`boto3`. There are no AWS variables in `.env.local` and no other `boto3` usage
in the repo. `STORAGE_PROVIDER` defaults to `supabase`. Everything went to
Supabase, as the user recalled.

Two further latent faults in that same script, not fixed (it is not on the
current path):

- `SupabaseDriver.upload_png` returns `SUPABASE_PUBLIC_BASE`, which is also
  commented out — `NameError` on every *successful* upload.
- It authenticates with `SUPABASE_ANON_KEY`; storage writes need `service_role`.

**`Scripts/hydrate_viz_library_v3.py` reviewed.** It is Stage D and never reads
source images. The "multiple folders" are prefixes *inside the one bucket*:

| Prefix | Written by | Holds |
|---|---|---|
| `raw/` | Stage A input | the source screenshots |
| `files/<cid>/<cid>_thumb.jpg` | Stage A | thumbnails |
| `base_code_templates/` | Stage C | abstract templates |
| `datasets/<cid>/<cid>.csv` | Stage D | the dataset Final SQL returned |
| `code/<cid>/<cid>_final.py` | Stage D | hydrated code |
| `charts/<cid>/<cid>_chart.png` | Stage D | the rendered chart |

### The source corpus is on disk after all

**746 unique images** across four folders (verified by SHA-256; `Design ideas 4`
and `Design ideas 4 2` are byte-identical copies of each other):

| Folder | Images | Match a catalog row by filename |
|---|---|---|
| `~/Downloads/Design ideas 4` | 459 | 0 |
| `~/Desktop/design examples` | 119 | 117 |
| `~/Desktop/designs25` | 117 | 89 |
| `~/Desktop/DesignFeb26` | 51 | 0 |

**206 of the 399** catalog source images are recoverable by exact filename; 193
are not. Sampled content from the largest folder: published editorial charts —
the same kind of material the catalog was built from.

---

## 2026-10-03 (resolved) — config repointed to the current project

All four variables now name `tnzqhmecjcdgfoemhfdq`, and it is verified end to
end rather than assumed:

| Check | Result |
|---|---|
| `service_role` → `/storage/v1/bucket` | **HTTP 200**, `viz-training-assets`, `public=true` |
| `SUPABASE_DB_URL` → Postgres | connects; 9 public tables; `311_daily` 984,848 rows |
| `tnzqhmecjcdgfoemhfdq.supabase.co` | resolves |
| 801 catalog asset URLs | all unreachable — **expected**, they still point at the old project |

`SUPABASE_DB_URL` was set by copying `SUPABASE_DB_URL_DIRECT`, which was already
correct. `.env.local` was backed up first and only that one line changed. The
pooler host already in the config (`aws-1-us-east-2`) belongs to the old project
and answers `FATAL (ENOTFOUND) tenant/user` for this one — pooler hostnames are
region-specific, so the direct host is used instead.

### Two bugs in the preflight itself, found by using it

- **`ref_of_db_url` only understood the pooler shape.** A direct connection
  string puts the ref in the second host label (`db.<ref>.supabase.co`) rather
  than in the username (`postgres.<ref>`), so a correct URL was reported as
  "not a recognisable Supabase key or URL". That is the same false-alarm failure
  the new-key-format handling was added to avoid, in a second place. Both shapes
  are parsed now, and a non-Supabase URL still returns nothing.
- **The progress counter used `\r` unconditionally**, so piping the output
  printed 801 lines and buried the summary. It now only animates on a terminal.

### Still outstanding

The 801 asset URLs point at the paused project and will stay broken until
re-intake replaces them. Nothing in Notion has been deleted. Scope is still
undecided — against the current warehouse only 4 of 400 rows reference tables
that exist.

---

## 2026-10-03 (later) — why the wrong key looked like the right one

The credentials in `.env.local` were reported as matching the current project's
dashboard. They do not. Settled empirically rather than by reading claims — the
keys were sent to `tnzqhmecjcdgfoemhfdq` and rejected:

```
service_role -> /storage/v1/bucket   403  signature verification failed
anon         -> /rest/v1/            401  Invalid API key
```

"Signature verification failed" is conclusive: the token was signed with a
different project's secret.

**Why comparing them by eye cannot work.** The `anon` and `service_role` keys in
`.env.local` share their **first 110 characters** with each other, and any
Supabase JWT shares that opening with any other. The header is identical across
all projects and the `ref` sits in the payload past the point anyone reads. Two
keys from different projects are indistinguishable at a glance.

**Added:** `Scripts/check_assets.py --identify-key`. Reads a key with `getpass`
— not echoed, not in shell history — and prints only its project, role, length
and a short SHA-256 fingerprint, then compares it against `SUPABASE_URL`. Lets a
key be checked *before* it is pasted into `.env.local`, and gives a fingerprint
that can be compared against the dashboard without reading 200 characters.

---

## 2026-10-03 — still no keys for the current project, and a scope finding

**Checked `.env.local` again** (modified today 13:50). The Supabase credentials
are unchanged: every key is still issued for the **old, paused** project.

| Variable | Kind | Project |
|---|---|---|
| `SUPABASE_URL` | URL | old |
| `SUPABASE_SERVICE_ROLE_KEY` | JWT (service_role) | old |
| `SUPABASE_ANON_KEY` | JWT (anon) | old |
| `NEXT_PUBLIC_SUPABASE_ANON_SECRET` | JWT (service_role) | old |
| `SUPABASE_DB_URL` | URL | old |
| `SUPABASE_DB_URL_DIRECT` | URL | **current** |

Keys issued for `tnzqhmecjcdgfoemhfdq`: **none.** The file looks complete —
nothing is empty — which is precisely why this went unnoticed for weeks. A
`service_role` JWT is signed by one project and does not authenticate against
another; the only way to tell is the `ref` claim inside it.

### Scope finding: the catalog cannot hydrate against the current warehouse

Ran every catalog row's SQL against the current project's `public` schema:

- **396 of 400** rows carry SQL
- **308** distinct tables referenced; **3** of them exist
- **4 rows** reference tables that all exist

This is the known shape of the catalog — the SQL is a spec written ahead of the
tables, not broken code — but it means re-intaking 400 rows into the current
project would produce 396 entries that cannot be hydrated. Worth settling what
"start clean" should cover before any intake run.

---

## 2026-09-29 (later still) — the pipeline was pointed at the wrong project

**Established with the user:** `sdpvhujlgakikcizaklw` is an **old project that is
paused**. The current workstream lives in `tnzqhmecjcdgfoemhfdq`, which holds the
real warehouse — `311_daily` (984,848 rows), `acs_b25013_tenure_edu`,
`government_spending_nipa`, `nfl_game_actives`.

So the broken images were not an outage. The pipeline had been writing to a
project the workstream had already left, and nothing said so.

### What the configuration actually described

| Variable | Project named |
|---|---|
| `SUPABASE_URL` | old |
| `SUPABASE_SERVICE_ROLE_KEY` | old |
| `SUPABASE_ANON_KEY` | old |
| `NEXT_PUBLIC_SUPABASE_ANON_SECRET` | old (and it is a **service_role** key despite the name) |
| `SUPABASE_DB_URL` | old |
| `SUPABASE_DB_URL_DIRECT` | **current** |

One variable out of six named the current project, and it was the only one the
viz pipeline does not read.

### Done

- **Bucket made public.** `viz-training-assets` exists in the current project
  (created 2025-08-27) but was private, while `library.PUBLIC` builds
  `/object/public/` URLs and Notion must fetch images without auth. Set via
  `storage.buckets` on the direct connection. Verified: the endpoint now answers
  `NoSuchKey` (bucket reachable, object absent) rather than `NoSuchBucket`.
- **`Scripts/lib/supabase_config.py`** — a Supabase JWT carries its project `ref`
  as a public claim, so "do the keys match `SUPABASE_URL`?" is provable rather
  than something a person has to notice. Runs in `library.check_credentials()`,
  so the gallery shows it as a banner, and in `Scripts/check_assets.py`. Verified
  against a synthetic half-migrated config: it names the offending variable and
  both projects.
- **`viz_gallery/CLAUDE.md`** now documents both projects, which is current, and
  what each holds.

### Blocked on credentials

There are **no API keys for the current project** anywhere in `.env.local` — all
three JWTs were issued for the old one, and a key from one project never
authenticates against another. Storage uploads cannot be done over the direct
Postgres connection: `storage.objects` is metadata; the bytes go through the
storage API, which needs a key.

Needed in `.env.local` (from Supabase dashboard → Project Settings → API for
`tnzqhmecjcdgfoemhfdq`):

```
SUPABASE_URL=https://tnzqhmecjcdgfoemhfdq.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service_role key for tnzqhmecjcdgfoemhfdq>
SUPABASE_ANON_KEY=<anon key for tnzqhmecjcdgfoemhfdq>
SUPABASE_DB_URL=<pooler URL for tnzqhmecjcdgfoemhfdq>
```

`Scripts/check_assets.py` will confirm all four agree before anything writes.

### Decided: start clean

The ~220 source screenshots exist only in the paused project and are **not**
being migrated. The current project's catalog will be re-intaken from source
images chosen later. The 400 existing Notion rows keep their now-dead asset
links until re-intake replaces them — **nothing in Notion has been deleted.**

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
