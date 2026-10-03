# ChartGen PRD

**Version 3.0 — September 13, 2026**
Supersedes v2 (Sept 12, 2026), which was reconstructed from chat logs and got
several central claims wrong. This version is grounded in four verification
documents produced over two days of direct work against the live systems:
`audit-2026-09.md`, `recovery-2026-09.md`, `first-run-2026-09.md`, and
`restore-2026-09.md`. Where this document states a fact, it was verified
against a live service unless marked otherwise.

---

## What v2 got wrong

| v2 claim | Reality | Source |
|---|---|---|
| Rendering is "the project" — kaleido blocker, `generate_chart_image()` a stub | The stub was archived code. The live script was fully implemented and kaleido worked all along. | audit |
| Signed URLs expiring 2026-09-24 would break reading | Bucket is public. No token needed. The expiring URLs were images, and nothing depended on signing. | recovery |
| Model string `claude-3-5-sonnet-20250106` in the repo | Never existed. It was a *suggestion from a past chat* that I filed as an observation. Six other retired IDs were real. | audit |
| Supabase project deleted or reaped (NXDOMAIN) | Project was live the whole time. `.env.local` held credentials for **two** projects; `SUPABASE_URL` named a dead one while the anon key named the live one. | recovery |
| Source images unrecoverable | 450 source images intact in `raw/`. The best-preserved asset in the project. | recovery |
| `data_contract` should be formalized from the model's output | Inverted. Contracts are derived from the real dataset with pandas. The model's version was never the right artifact. | restore |
| Review must be manual | Automatable. A template is reviewed when it renders and passes contract validation. | restore |

The pattern worth carrying forward: **every wrong claim in v2 came from
reasoning about state rather than querying it.** Three of them came from
treating a past assistant's suggestion or inference as an observation.

---

## TL;DR

ChartGen is a curated library of production-grade chart templates. Each is
reverse-engineered from a real published visualization into abstract Plotly code
(`build_figure(df)`, no hard-coded data), paired with a data contract derived
from its actual dataset, and gated by a validator that refuses to render when
the data can't support the template's parameters.

The library is the asset. The pipeline feeds it. The app, when it exists, is a
surface on it.

**The constraint is not code. It is data.** 395 of 396 catalog rows query tables
that don't exist yet. The SQL was written deliberately, ahead of the tables, as
a spec. The pace of the library is the pace of building those tables.

---

## Architecture

v2 got this right and it's now proven in practice.

**Build time** (operator-run, offline, no latency budget)
Source image → Claude API vision call → abstract template + caveats + notes →
human-reviewable artifacts in Supabase and Notion.

**Run time** (data-bound, no LLM in the path)
Template + SQL → real dataset → derived contract → validator gate → render.

No model call at run time. This retires v2's top-listed technical risk entirely
and is why rendering is fast and deterministic while generation is neither.

---

## Current state — verified

### Working

- **Stage C runs end to end.** Three charts complete: CHT-6FBD47 (choropleth),
  CHT-85FB02 (small multiples), CHT-678195 (line). Each has a template in
  storage, a Notion row with six properties and one code block, real SQL against
  real Postgres, a derived contract, an accepted parameter proposal, and PNG +
  SVG output.
- **Contract derivation.** `Scripts/lib/data_contract.py`. Per column: dtype,
  non-null and null counts, distinct count. Per numeric column: min, max, mean,
  std, quartiles, and nine deciles. The deciles exist because interpolating
  across min–max ignored skew and produced a 25/23/7 split where 18/18/19 was
  correct.
- **Render guard.** `Scripts/lib/render_guard.py`. Refuses missing required
  columns, empty result sets, all-null columns, out-of-range bin edges, and
  out-of-range baselines. Runs as a precondition of render, not a report after.
- **Parameter derivation.** Proposes bin edges from quantiles and baselines from
  the median. Tested across five distributions, three tables, skew −2.1 to +5.7,
  n from 10 to 1,256. Beat naive equal-width on all five and beat a hand pick on
  occupancy balance.
- **Acceptance policy.** Proposals carry `status: proposed` until accepted, with
  actor identity and type recorded. Automation cannot accept an unreliable
  proposal; the override is human-only and requires a recorded reason.
- **Non-determinism guard.** `--overwrite` refuses any row at or past review
  status without `--force`, and reports what it refused.
- **Error surfacing, partially restored.** `coerce_prop_names()` (schema
  validation, with case-insensitive correction and collision detection),
  `fetch_bytes()` (raises on non-200 and empty bodies), upload verification
  (lists and size-checks the object before minting a URL).

### Assets

- Bucket `viz-training-assets`: public, 1,079 objects, 146 MiB. `raw/` holds 450
  source chart images; `files/` holds 400 thumbnails, 399 of 400 PROD rows
  resolving.
- Notion: three databases. **Viz library** (PROD, 400 rows, 38 properties) is
  the system of record. **Visualization Code Templates** (724 rows) holds the
  orphaned September corpus. **Viz Asset Library (v2)** (649 rows) is superseded
  and its imagery is entirely dead.
- Postgres: seven real tables. `national_state_view` (2,142 rows, state × year,
  1986–2023) and `station_daily` (111,664 rows) carry usable data.

### Known broken or unresolved

- **Stage C/D database disconnect.** Stage C writes to PROD; Stage D still
  carries assumptions from the two-database era. Deferred deliberately — it
  serves a batch that can't run until the data exists.
- **`line_daily` is empty.** Zero rows. Queries against it succeed and return
  nothing, which is the silent-failure shape this project keeps producing.
- **`station_daily` is three columns emptier than it looks.** `exits`,
  `ridership_proxy`, and `lines` are 100% null. `entries` and `borough` are
  complete.
- **Template non-determinism.** The same source image produced templates with
  different required columns on different runs — one derived a category column,
  the other demanded it pre-binned. Templates are not reproducible artifacts.
- **One title/SQL mismatch.** CHT-00DB0F's SQL returns NFL players by city while
  its title describes election mentions on earnings calls. Population of one
  today; the risk grows as SQL is repointed at real tables.
- **Credentials.** Nine-plus live values were exposed in session transcripts.
  The Supabase `service_role` key has never been rotated and sat under a
  `NEXT_PUBLIC_`-prefixed name. Rotation is outstanding.

---

## Requirements

### Retired from v2

**R1 (fix rendering)** — void. Rendering worked all along.

**R2 (stabilize asset URLs)** — void. The bucket is public; signed URLs are a
code path to delete, not a strategy to choose.

**R3 (update model config)** — done, and it surfaced two blockers no static
reading would have caught: `content[0]` is a `ThinkingBlock` on current models,
and `temperature` now returns 400.

### R4 — Contracts, derived (was: contracts, formalized)

The contract is derived from the dataset the chart's SQL actually returns. Not
authored by the model, not inferred from the image.

This is the single most important change in v3, and it was settled empirically.
CHT-85FB02 rendered cleanly and was semantically dead — six panels of identical
bars, because the template shipped `BASELINE = 100` against values spanning
12.5–17.7. It passed every structural check: SQL executed, columns matched, code
parsed, a Figure returned, PNG at a plausible size. **Only the contract caught
it.**

The contract must carry enough to support derivation, not just documentation.
Deciles were added because quartiles alone couldn't express skew. The general
rule: record generously while it's cheap, because the contract's contents
determine which derivations are possible at all.

### R5 — Caveats: open

Caveats are generated per chart and stored as free text. The 97% singleton
problem from the September corpus is untouched, and 2,305 caveat lines remain
orphaned from PROD by regenerated chart IDs (re-linkable by image hash — noted
as an option, not scheduled).

**Proposed split, not yet decided.** Looking at CHT-6FBD47's nine caveats, they
fall into three kinds that behave differently:

- *Structural facts* (`locationmode="USA-states"`, one trace per category) —
  derivable from the code itself. A model isn't needed to state what the code
  does.
- *Data requirements* (needs lat/long for in-map labels, requires a pre-binned
  category column, custom categorical ordering) — the same class of information
  the contract carries, but arrived at from the image. This is the category that
  caused a real failure: a regenerated template silently demanded a pre-binned
  column its predecessor derived.
- *Cosmetics* (legend placement, colorbar suppression, annotation styling) —
  descriptive, low stakes, and probably most of the singletons.

If split this way, R5 stops being a taxonomy problem: structural facts derive
from code, data requirements reconcile against the contract with a mismatch
failing the review gate, and only cosmetics stay free text where a high
singleton rate is harmless.

**Undecided and blocking nothing yet.** Worth resolving before the caveat corpus
grows past a few dozen charts.

### R6 — Review gate, automatable (was: manual review)

A template is `reviewed` when it renders and passes contract validation against
its own SQL's output. That is a gate a machine can run, which v2 assumed it
couldn't.

What stays human: accepting an unreliable parameter proposal, and any judgment
the data can't supply.

### R7 — Data availability (new, and the real constraint)

395 of 396 catalog rows reference tables that don't exist. The SQL is a spec
written ahead of the tables, being worked through progressively.

- Rewritten SQL goes to `Final SQL`; the original stays untouched as the spec.
- Near-duplicate table names across rows (`covid_cases` / `covid_statistics` /
  `covid_stats`) are drift from per-row authoring. Maintain a canonical name map
  as tables are built so the eventual SQL rewrite is mechanical.
- A chart is servable when its table exists, its columns match the template's
  requirements, and its distribution supports the template's parameters. All
  three, not just the first.

### R8 — Parameter scope (new, open)

Derivation currently fires on every numeric column. On CHT-85FB02 it proposed
bin edges for `year` — mechanically correct, semantically meaningless, and
flagged `reliable: true` because the distribution is well-behaved. Nothing
consumes it today.

This is the natural-breaks problem in a new place: a judgment the data cannot
supply. Two options, undecided — the contract names a measure column, or
proposals are requested per column rather than generated for all.

### R9 — Error surfacing (new, from a failure that cost a year)

The uncommitted rewrite removed error handling at 17 sites: `raise_for_status`
3 → 0, functions 28 → 19, six deleted defensive helpers, plus
`except Exception: pass` around URL minting. Combined with a discarded PATCH
response, the pipeline reported success while writing nothing for a year.

The counter-example is instructive: `generate_base_code_v2.py` was the least
sophisticated script in the repo, called `raise_for_status()` on its Notion
write, and is the only one that ever reliably produced anything.

**Standing rule: a verification routine that can fail silently is worse than no
verification.** Two instances surfaced during this work — a `.list()` call that
paged at 100 against a 220-object prefix and reported a successful upload as
missing, and a rounding function that moved a threshold by 67% while staying
inside the accepted range.

---

## Success metrics

### Library health

- Templates at `reviewed` (renders + passes contract validation)
- Servable charts: table exists, columns match, distribution supports parameters
- Contract coverage and proposal acceptance rate, split by human vs. automation
- Unreliable-proposal rate — the signal for where derivation needs work

### Derivation quality

- Bin occupancy against an even split
- Baseline error against the true median (currently ≤3% across five
  distributions, down from 67% before the rounding fix)
- Guard rejection rate, and how many rejections were real defects

### Not yet set

Business metrics. There is no product to convert anyone into. Setting revenue
targets now would repeat v1's error.

---

## Sequencing

Dependency-ordered. No dates.

**Phase 0 — complete.** Config repaired, Stage C proven, three charts end to
end, contract and guard load-bearing.

**Phase 0.5 — housekeeping.** Rotate credentials. Fix `viz_gallery/CLAUDE.md`,
which mislabels the Assets(v2) ID as `NOTION_PROD_DATABASE_ID` — likely why the
first schema change landed on the wrong database.

**Phase 1 — data.** Build tables against the SQL spec, consolidating near
-duplicate names. Each new table unlocks a cohort of charts. This phase sets the
pace of everything downstream.

**Phase 2 — scale the library.** Batch Stage C over servable charts. Resolve R5
and R8 before the corpus grows. Fix the Stage C/D disconnect when a batch
actually needs it.

**Phase 3 — surface.** Gallery, detail view, bring-your-own-data with sandboxed
execution. `exec()` of generated code is acceptable for a single trusted
operator and is not acceptable the moment user data drives it.

**Phase 4 — business.** Scoped on Phase 3 evidence.

**Team.** One person.

---

## Standing cautions

- **Templates are not reproducible.** Regeneration can change a template's
  required columns. A reviewed template, its validated SQL, and its derived
  contract are a matched set. The `--force` guard protects this; don't route
  around it.
- **Structurally valid and semantically dead is the recurring failure.**
  CHT-85FB02's flat bars, the 67% baseline error, the `year` proposal, the empty
  `line_daily`. Every one passed the checks that existed. Design new checks
  adversarially.
- **Four auto-accepts are not evidence the review path works.** All four
  proposals to date came back reliable and automation accepted all four. The
  human gate has never bound. Its first real test is still ahead.
- **Verify against live services, not against reasoning.** Every wrong claim in
  v2 came from the latter.
