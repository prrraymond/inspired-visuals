# ChartGen PRD

**Version 3.1 — September 13, 2026**
Supersedes v3.0 (same day). Changes are confined to the caveat taxonomy (R5,
largely resolved), a new requirement for the analytical-intent layer (R10), and
current-state additions from the analysis-workflow reconciliation. Everything
else carries forward unchanged.

Grounded in five verification documents: `audit-2026-09.md`,
`recovery-2026-09.md`, `first-run-2026-09.md`, `restore-2026-09.md`, and
`analysis-workflow-2026-09.md`. Where this document states a fact, it was
verified against a live service unless marked otherwise.

---

## Changes in 3.1

| Section | 3.0 said | 3.1 says |
|---|---|---|
| R5 (caveats) | Open. 97% singleton rate unsolved; proposed a three-way split | Largely resolved. Stage C's caveats *are* the structural vocabulary — terms recur verbatim across charts. The singleton rate was a property of the September corpus, not the method |
| Analysis workflow | Not mentioned | New R10. A second, independent taxonomy on the analytical-intent axis. Complementary, not redundant — 0 of 26 caveat lines reach its dimensions |
| Current state | `viz_gallery/` unexamined | Contains an analysis orchestrator, never run, pointed at the dead database. Notion MCP is configured |
| Gemini | Assumed superseded by Claude vision | Still live in Stages A and B. Claude vision is Stage C only. Both are in the run path |

---

## What v2 got wrong

| v2 claim | Reality |
|---|---|
| Rendering is "the project" — kaleido blocker, `generate_chart_image()` a stub | The stub was archived code. The live script worked and kaleido worked all along |
| Signed URLs expiring 2026-09-24 would break reading | Bucket is public. No token needed |
| Model string `claude-3-5-sonnet-20250106` in the repo | Never existed. It was a *suggestion from a past chat* filed as an observation |
| Supabase project deleted (NXDOMAIN) | Live the whole time. `.env.local` held credentials for two projects |
| Source images unrecoverable | 450 intact in `raw/`. The best-preserved asset in the project |
| `data_contract` should be formalized from the model's output | Inverted. Derived from the real dataset with pandas |
| Review must be manual | Automatable — renders plus contract validation |

The pattern: **every wrong claim in v2 came from reasoning about state rather
than querying it.** Three came from treating a past assistant's suggestion or
inference as an observation.

---

## TL;DR

ChartGen is a curated library of production-grade chart templates. Each is
reverse-engineered from a real published visualization into abstract Plotly code
(`build_figure(df)`, no hard-coded data), paired with a data contract derived
from its actual dataset, and gated by a validator that refuses to render when
the data can't support the template's parameters.

The library is the asset. The pipeline feeds it. The app is a surface on it.

**The constraint is not code. It is data.** 395 of 396 catalog rows query tables
that don't exist yet. The SQL was written deliberately, ahead of the tables, as a
spec. The pace of the library is the pace of building those tables.

---

## Architecture

**Build time** (operator-run, offline, no latency budget)
Source image → vision call → abstract template + caveats + notes →
human-reviewable artifacts in Supabase and Notion.

**Run time** (data-bound, no LLM in the path)
Template + SQL → real dataset → derived contract → validator gate → render.

No model call at run time. This retires v2's top-listed technical risk and is why
rendering is fast and deterministic while generation is neither.

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
  std, quartiles, and nine deciles.
- **Render guard.** `Scripts/lib/render_guard.py`. Refuses missing required
  columns, empty result sets, all-null columns, out-of-range bin edges and
  baselines. A precondition of render, not a report after.
- **Parameter derivation.** Tested across five distributions, three tables, skew
  −2.1 to +5.7, n from 10 to 1,256. Beat naive equal-width on all five and beat
  a hand pick on occupancy balance.
- **Acceptance policy.** Proposals stay `proposed` until accepted, with actor
  identity and type recorded. Automation cannot accept an unreliable proposal;
  the override is human-only and requires a recorded reason.
- **Non-determinism guard.** `--overwrite` refuses any row at or past review
  status without `--force`, and reports what it refused.
- **Error surfacing, partially restored.** `coerce_prop_names()`,
  `fetch_bytes()`, upload verification.

### Assets

- Bucket `viz-training-assets`: public, 1,079 objects, 146 MiB. `raw/` holds 450
  source images; `files/` holds 400 thumbnails, 399 of 400 PROD rows resolving.
- Notion: three databases. **Viz library** (PROD, 400 rows, 38 properties) is the
  system of record — the quickest tell is that it has `SQL` and `Final SQL`.
  **Visualization Code Templates** (724 rows) holds the orphaned September
  corpus. **Viz Asset Library (v2)** (649 rows) is superseded; its imagery is
  entirely dead and it has no `Status` property at all.
- Postgres: seven real tables. `national_state_view` (2,142 rows, state × year,
  1986–2023) and `station_daily` (111,664 rows) carry usable data.
- **Vision is split by stage.** Gemini remains live in Stages A and B
  (`bootstrap_supabase_to_notion_v2.py`,
  `notion_chart_annotator_vizlib_v2.py`, `discover_chart_schema.py`). Claude
  vision is Stage C only.

### The analysis workflow

`viz_gallery/` holds a `/viz-library-analysis` orchestrator with three skills:
`analyze-viz-image`, `synthesize-viz-library`, `write-visual-cases`. Built
2026-04-08 in a single six-minute sitting, untracked in git, and **never run** —
`analysis-outputs/` holds only `.gitkeep`.

It is hardcoded to Viz Asset Library (v2), whose Asset URLs return HTTP 400
(0 of 6 spot-checked resolve, against 3 of 3 on PROD), and its Stage 0 offers a
status filter on a database with no `Status` property. Notion MCP *is* configured
both globally and per-project. It would authorize, then fail at every fetch —
degrading to `STATUS: ERROR` per chart rather than producing wrong analysis,
because the skill's own sub-1KB guard catches the error body.

### Known broken or unresolved

- **Stage C/D database disconnect.** Deferred — it serves a batch that can't run
  until the data exists.
- **`line_daily` is empty.** Zero rows; queries succeed and return nothing.
- **`station_daily`** — `exits`, `ridership_proxy`, and `lines` are 100% null.
- **Template non-determinism.** The same source image produced templates with
  different required columns on different runs.
- **One title/SQL mismatch.** CHT-00DB0F. Population of one today; the risk grows
  as SQL is repointed at real tables.
- **`OPENAI_API_KEY` absent** and blocking wherever it's read.
- **Credentials.** Nine-plus live values exposed in session transcripts. The
  Supabase `service_role` key has never been rotated. Outstanding.

---

## Requirements

### Retired

**R1 (fix rendering)** — void. Rendering worked all along.
**R2 (stabilize asset URLs)** — void. Public bucket; signed URLs are a code path
to delete.
**R3 (update model config)** — done. It surfaced two blockers no static reading
would have caught: `content[0]` is a `ThinkingBlock`, and `temperature` returns
400.

### R4 — Contracts, derived

The contract is derived from the dataset the chart's SQL actually returns. Not
authored by the model, not inferred from the image.

Settled empirically. CHT-85FB02 rendered cleanly and was semantically dead — six
panels of identical bars, because the template shipped `BASELINE = 100` against
values spanning 12.5–17.7. It passed every structural check. **Only the contract
caught it.**

The contract must carry enough to support derivation, not just documentation.
Deciles were added because quartiles alone couldn't express skew. Record
generously while it's cheap: the contract's contents determine which derivations
are possible at all.

### R5 — Structural caveats (largely resolved)

**Stage C's caveats are the structural vocabulary.** Terms recur verbatim across
the three completed charts — annotation-dependent, reversed y-axis order,
small-multiple faceting. The 97% singleton rate that made this look intractable
was a property of the September corpus, generated by a model that no longer
exists, not a property of the method.

Of 26 caveat lines across the three charts: 10 describe chart structure, 16 are
implementation detail. Both are useful; they describe *how to rebuild the chart*.

**What remains open** is the narrower question of whether to separate data
requirements (needs lat/long for in-map labels, requires a pre-binned category
column) from cosmetics (legend placement, colorbar suppression). Data
requirements are the same class of information the contract carries, arrived at
from the image rather than the data — and a mismatch between the two should fail
the review gate. That reconciliation is worth building; the rest can stay free
text.

Not blocking. Worth resolving before the corpus grows past a few dozen charts.

### R6 — Review gate, automatable

A template is `reviewed` when it renders and passes contract validation against
its own SQL's output. A machine can run that gate; v2 assumed it couldn't.

What stays human: accepting an unreliable parameter proposal, and any judgment
the data can't supply.

### R7 — Data availability (the real constraint)

395 of 396 catalog rows reference tables that don't exist. The SQL is a spec
written ahead of the tables, being worked through progressively.

- Rewritten SQL goes to `Final SQL`; the original stays untouched as the spec.
- Near-duplicate table names (`covid_cases` / `covid_statistics` / `covid_stats`)
  are drift from per-row authoring. Maintain a canonical name map as tables are
  built so the eventual rewrite is mechanical.
- A chart is servable when its table exists, its columns match the template's
  requirements, **and** its distribution supports the template's parameters. All
  three, not just the first.

### R8 — Parameter scope (open)

Derivation fires on every numeric column. On CHT-85FB02 it proposed bin edges for
`year` — mechanically correct, semantically meaningless, and flagged
`reliable: true` because the distribution is well-behaved. Nothing consumes it.

The natural-breaks problem in a new place: a judgment the data cannot supply.
Two options, undecided — the contract names a measure column, or proposals are
requested per column rather than generated for all.

### R9 — Error surfacing

The uncommitted rewrite removed error handling at 17 sites: `raise_for_status`
3 → 0, functions 28 → 19, six deleted defensive helpers, plus
`except Exception: pass` around URL minting. Combined with a discarded PATCH
response, the pipeline reported success while writing nothing for a year.

The counter-example: `generate_base_code_v2.py` was the least sophisticated
script in the repo, called `raise_for_status()` on its Notion write, and is the
only one that ever reliably produced anything.

**Standing rule: a verification routine that can fail silently is worse than no
verification.** Two instances surfaced this week — a `.list()` call that paged at
100 against a 220-object prefix and reported a successful upload as missing, and
a rounding function that moved a threshold by 67% while staying inside the
accepted range.

### R10 — Analytical intent (new)

A second taxonomy, orthogonal to R5. Where caveats say *how to rebuild a chart*,
this says *whether it was worth building*: the message conveyed, communication
strengths, communication gaps, and a standard-versus-unique classification.

The two barely overlap. Of 26 caveat lines across three charts, **zero** reach
message, does-well, lacks, or STANDARD/UNIQUE. Treating this as an alternative to
R5 would conflate two taxonomies that should both exist.

To make the existing workflow usable:

- **Repoint at PROD.** It is hardcoded to the dead database.
- **Delete the two redundant dimensions.** `visual_type_primary` duplicates the
  curated `Viz type` more coarsely ("map" vs Choropleth Map), and STANDARD/UNIQUE
  duplicates the `Standard` checkbox, already set correctly by hand. Read those
  fields instead. Having an LLM re-derive a classification you set by hand and
  then weight synthesis 1.5× on its own answer launders a guess into a fact.
- **Keep its output out of `Caveats`.** Different axis, different property.
- **Aim it at the render, not the source screenshot.** "What it lacks" pointed at
  someone else's published chart is a critique of them. Pointed at
  `charts/<cid>/<cid>_chart.png`, it's quality control on your library — and it
  closes a loop nothing else does, since the render gate checks that a chart is
  valid but nothing checks whether it's any good.

That last point sets its position in the sequence: **it needs renders to
analyze**, so it queues behind Stage D over servable charts, which queues behind
the tables.

---

## Success metrics

### Library health

- Templates at `reviewed` (renders + passes contract validation)
- Servable charts: table exists, columns match, distribution supports parameters
- Contract coverage and proposal acceptance rate, split human vs. automation
- Unreliable-proposal rate — the signal for where derivation needs work

### Derivation quality

- Bin occupancy against an even split
- Baseline error against the true median (currently ≤3% across five
  distributions, down from 67% before the rounding fix)
- Guard rejection rate, and how many rejections were real defects

### Not yet set

Business metrics. There is no product to convert anyone into.

---

## Sequencing

Dependency-ordered. No dates.

**Phase 0 — complete.** Config repaired, Stage C proven, three charts end to end,
contract and guard load-bearing.

**Phase 0.5 — housekeeping.** Rotate credentials. `viz_gallery/CLAUDE.md` is
rewritten and current.

**Phase 1 — data.** Build tables against the SQL spec, consolidating
near-duplicate names. Each new table unlocks a cohort of charts. This phase sets
the pace of everything downstream.

**Phase 2 — scale the library.** Batch Stage C over servable charts. Resolve the
remaining R5 reconciliation and R8 before the corpus grows. Fix the Stage C/D
disconnect when a batch actually needs it.

**Phase 3 — surface.** Read-only gallery first: it forces a decision about what a
library entry *is*, while there are three charts to restructure rather than 150.
Bring-your-own-data comes later and needs sandboxed execution — `exec()` of
generated code is acceptable for a single trusted operator and is not acceptable
the moment user data drives it.

**Phase 4 — analytical intent.** Repoint and run the analysis workflow against
rendered charts.

**Phase 5 — business.** Scoped on evidence from Phase 3.

**Team.** One person.

---

## Standing cautions

- **Templates are not reproducible.** Regeneration can change required columns. A
  reviewed template, its validated SQL, and its derived contract are a matched
  set. The `--force` guard protects this; don't route around it.
- **Structurally valid and semantically dead is the recurring failure.**
  CHT-85FB02's flat bars, the 67% baseline error, the `year` proposal, the empty
  `line_daily`. Every one passed the checks that existed. Design new checks
  adversarially.
- **Four auto-accepts are not evidence the review path works.** All four
  proposals to date came back reliable and automation accepted all four. The
  human gate has never bound.
- **Don't let a model re-derive what you curated by hand.** `Viz type` and
  `Standard` are yours. Read them.
- **Verify against live services, not against reasoning.** Every wrong claim in
  v2 came from the latter.
