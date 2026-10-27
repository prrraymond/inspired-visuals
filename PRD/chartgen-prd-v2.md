# ChartGen PRD

**Version 2.0 — September 12, 2026**
Supersedes v1 (undated, ~mid-2025). Rewritten after a build audit to reconcile the
document with what was actually built between Aug 2025 and Jan 2026.

---

## Changelog from v1

| Area | v1 said | Reality | v2 does |
|---|---|---|---|
| Core asset | User-facing chart generator | A curated library of annotated Plotly templates | Makes the library the product spine |
| Notion | User copy-paste import path | Internal catalog / CMS, accessed via API | Reframes Notion as the system of record |
| Pipeline | Live per-request generation, <5s | Offline batch: image → template → storage | Splits build-time vs. run-time explicitly |
| `data_contract` | Not mentioned | Built, core to the pipeline | Promoted to a first-class requirement |
| `caveats` | Not mentioned | Built, the real design IP | Promoted to a first-class requirement |
| Accounts / tokens / Stripe | Highest-priority V1 | Not started | Deferred to Phase 3, unscoped until library proves out |
| PNG/SVG export | Highest-priority V1 | Stubbed, never working | Named as the top open blocker |
| Timeline | 4–6 weeks to launch | ~5 months of pipeline work, then dormant | Replaced with phased, dependency-ordered plan |

---

## TL;DR

ChartGen is a curated library of production-grade chart templates, each one
reverse-engineered from a real published visualization into clean, reusable
Plotly code — and each one annotated with an explicit data contract and a set of
design caveats explaining *why* the chart is built the way it is.

The library is the asset. Everything else is a delivery surface for it.

This matters because the thing v1 described — paste data, an LLM makes you a
chart — has been commoditized by general-purpose assistants that users already
pay for. A library of human-reviewed, caveat-annotated templates is not
commoditized, compounds with every template added, and gets *more* valuable as
generic generation gets cheaper, because the scarce input becomes judgment about
which chart is correct, not the ability to render one.

---

## Goals

### Product Goals

- Build a library of 150+ reviewed templates spanning the standard chart
  vocabulary plus the harder forms (Cleveland dot, slope, small multiples,
  dual-axis, percent-stacked, cumulative).
- Every template ships with a machine-readable `data_contract` and a human-readable
  `caveats` list. No template enters the library without both.
- Make a template reusable end to end: a user supplies conforming data and gets a
  correct chart without editing code.
- Reach reliable rendered output (PNG + SVG) for 100% of library templates.

### Business Goals

Deliberately unset for Phase 1. v1's targets — 1,000 charts, 200 signups, 20%
conversion, $1,000 gross — were set before there was a product to convert anyone
into, and they don't reconcile with each other (200 signups × 5 free tokens
consumes most of the 1,000-chart target for free, and no price was ever named).

Revenue targets get set in Phase 3, after the library exists and pricing has a
basis. Setting them now would be theater.

### Non-Goals

- Live LLM generation at user request time. Codegen is a build-time activity,
  run by the operator, with human review before anything enters the library.
- Arbitrary user-defined visualizations or chart scripting.
- Dashboards, stateful workflows, collaboration, or SaaS admin surface.
- Any integration beyond Notion and Supabase until Phase 3.

---

## Architecture: build time vs. run time

v1's central error was collapsing these into one pipeline. They are separate
systems with different latency budgets, cost profiles, and failure modes.

**Build time (operator-run, offline, no latency budget)**
Source chart image → Claude API vision call → structured JSON
(`plotly_code`, `data_contract`, `caveats`, `notes`, `filename_suggestion`) →
human review → Supabase storage → Notion catalog entry.

Cost per template is a one-time LLM call plus review minutes. Failures are
retried or discarded; nothing user-facing is affected.

**Run time (user-facing, latency-bound, no LLM in the path)**
User picks a template → supplies data → data validated against that template's
`data_contract` → stored Plotly code executes → PNG/SVG rendered → delivered.

No model call happens here. This is the single most important change from v1.
It removes model-response reliability from the user-facing path entirely,
retiring v1's top-listed technical risk, and makes sub-second rendering plausible
where v1 promised an optimistic <5s that included a live LLM round trip.

---

## Current state (as of this rewrite)

### Built and working

- **Codegen pipeline.** Chart image → Claude API → structured JSON. Prompt is
  mature: enforces `plotly.graph_objects` only (never `plotly.express`), demands
  complete inline sample data with realistic column names and ~20–50 rows,
  requires modular sections (data stub / traces / layout), and returns JSON with
  no prose or markdown fences.
- **Structured output schema.** `ClaudeOut` Pydantic model with `plotly_code`,
  `filename_suggestion`, `notes`, `data_contract`, `caveats`.
- **Asset storage.** Supabase bucket `viz-training-assets`, keyed by chart ID
  (`CHT-XXXXXX` format): `code/{chartid}/base.py`,
  `code/{chartid}/{chartid}_final.py`, `datasets/{chartid}/{chartid}.csv`.
  Version-safe upload wrapper handles both old and new Supabase SDK signatures.
- **Notion catalog.** Source and target databases via API. Properties include
  `Asset name`, `chartid`, `Asset URL`, `Thumbnail`, `Base code file`,
  `Base code URL`, `Base code notes`, `Dataset URL`, `Final Code URL`,
  `Code Preview`.
- **Scripts.** `Scripts/generate_base_code.py`,
  `Scripts/export_images_to_storage.py`, plus a bootstrap script. Flags for
  `--why`, `--dry-run`, `--force`, `--limit`.
- **Repo and CI.** `inspired-visuals` on GitHub, Actions configured, secrets
  moved out of git history and into encrypted repo secrets.

### Built but broken or stale

- **Chart image rendering is a stub.** `generate_chart_image()` returns `None`
  with a note that kaleido configuration is needed. This has never worked. It is
  the single largest gap between the pipeline and a usable product — the library
  currently has code but no rendered output.
- **Model strings are a year out of date.** Scripts reference
  `claude-3-7-sonnet-latest` and `claude-3-5-sonnet-20250106`. These calls may
  fail outright. Needs a current model and a single configured constant rather
  than scattered literals.
- **Signed URLs are expiring.** Asset URLs stored in Notion were generated
  Sept 24, 2025 with a one-year TTL, expiring Sept 24, 2026 — within two weeks
  of this document. If Notion holds signed links as canonical references, a
  portion of the catalog goes dead imminently.

### Never started

Visualization picker, data input UI, preview/tweak panel, user accounts, token
system, chart history, Stripe, per-chart pricing, onboarding, support surface.
All of v1's Account/Payment sections and most of its Core Chart Workflow.

---

## Functional Requirements

### P0 — Unblock the library

**R1. Fix rendered output.** Resolve the kaleido dependency and render every
library template to PNG and SVG. Store alongside code and dataset under the same
chart ID. Without this there is no deliverable, only source code.

**R2. Stabilize asset URLs.** Decide between a public bucket, long-lived signed
URLs with a documented rotation job, or a proxy endpoint. Backfill existing
Notion entries. Whatever is chosen must not silently expire again.

**R3. Update the model configuration.** Single constant, current model, tested
end to end against the existing prompt.

### P1 — Make the library a real asset

**R4. Data contract as a schema.** `data_contract` is currently descriptive
prose-ish JSON. Formalize it: column names, dtypes, required vs. optional,
grouping keys, cardinality expectations, approximate row count. It must be
executable as validation, because it is the mechanism by which a user's data is
checked against a template before rendering.

**R5. Caveats as structured metadata.** `caveats` is currently a free-text list.
Convert to a controlled vocabulary — dual-axis, log scale, percent stacking,
cumulative sum, faceting, custom categorical ordering, Cleveland layout,
annotation-dependent — so caveats become filterable and explainable in the UI
rather than a blob. This is the library's differentiator and should be treated
as structured data, not notes.

**R6. Review workflow.** A template is `draft` until a human confirms the code
runs, the render matches the source intent, and the contract and caveats are
accurate. Add explicit status to the Notion schema. Nothing reaches a user in
`draft`.

**R7. Taxonomy and coverage tracking.** Categorize by chart family and by
analytical intent ("show composition over time", "compare ranked categories").
Track coverage so gaps are visible.

### P2 — First delivery surface

**R8. Browsable gallery.** Read-only. Rendered previews, filterable by family,
intent, and caveat. This is the smallest thing that makes the library visible to
anyone but you, and it's shippable well before any account system exists.

**R9. Template detail view.** Render, code, data contract in readable form,
caveats with plain-language explanation of why each matters.

**R10. Bring-your-own-data render.** User supplies CSV or paste, validated
against the template's `data_contract` with specific errors ("column `region`
expected, found `Region`"), then rendered. No login. No payment. The goal here is
learning whether the contract-validation flow actually holds up against real
messy data, which is the highest-uncertainty assumption in the whole design.

### P3 — Monetization (unscoped until P2 ships)

Accounts, usage limits, payment. Deferred deliberately. v1 specified a 5-token
trial and per-chart Stripe pricing without ever naming a price, and priced a
product whose free-tier competition has since become very strong. Pricing model
should be chosen on evidence from P2 usage, not re-inherited from v1.

---

## Users

The v1 personas — Marie the manager, James the consultant — assumed the user's
problem is *rendering* a chart. That problem is now largely solved for free.
Revised:

**The practitioner who knows the chart is wrong but not why.** Analyst,
consultant, or operator who can get any tool to produce a bar chart but cannot
easily tell whether a dual-axis comparison is misleading, whether their stacked
percentages hide the thing that matters, or whether a Cleveland dot plot would
read better than the grouped bars they defaulted to. Values the caveats more than
the code.

**The practitioner who needs consistency across a deliverable.** Producing a
20-chart report where every figure must share conventions. Generic per-chart
generation actively works against this; a template library is built for it.

**Operator (you).** Runs the pipeline, reviews templates, curates the taxonomy.
A real user of the system with real requirements — batch tooling, review queue,
coverage visibility — which v1 never acknowledged.

---

## Success Metrics

### Phase 1 — Library health

- Templates at `reviewed` status (target: 150+)
- Percentage with a working render in both PNG and SVG (target: 100%)
- Percentage with a validated, executable data contract (target: 100%)
- Caveat coverage: share of templates with at least one structured caveat
- Coverage gaps by chart family and analytical intent
- Codegen cost and review time per template

### Phase 2 — Surface validation

- Gallery sessions and templates viewed per session
- Bring-your-own-data attempts, and **contract validation pass rate on first try**
  — the key learning metric; a low rate means the contracts are too strict or too
  vague, and that's a design problem worth finding early
- Render success rate on user data
- Repeat usage

### Phase 3 — Business

Set after Phase 2. Not guessed now.

### Technical

- Render time at run time, p95 (no LLM in path; this should be fast)
- Render failure rate on conforming data (<1%)
- Pipeline batch throughput and failure rate at build time

---

## Technical Considerations

**Stack in place:** Python, Plotly (`graph_objects` only), Anthropic API,
Supabase (storage), Notion (catalog), GitHub Actions.

**Storage.** Supabase `viz-training-assets`, chart-ID-keyed. Extend the existing
path convention to renders: `renders/{chartid}/{chartid}.png` and `.svg`.

**Catalog.** Notion remains the system of record through Phase 2. It is a
reasonable CMS for a single operator and a few hundred rows. It will not survive
Phase 3 with user accounts and per-user data attached — plan the migration to
Postgres (Supabase already provides it) as a Phase 3 dependency rather than an
emergency.

**Execution safety.** The pipeline currently `exec()`s LLM-generated code. That
is acceptable when you are the only operator running trusted output. It is not
acceptable the moment user-supplied data drives execution on a server. Sandboxing
is a hard prerequisite for R10, not a nice-to-have.

**Secrets.** Already moved to GitHub Actions secrets. Note that signed URLs with
embedded tokens have appeared in terminal output and chat logs; treat any URL
that has been pasted anywhere as compromised and rotate on the next pass.

### Risks

- **Rendering stays hard.** Kaleido has been the blocker for a year. If it
  resists again, evaluate alternatives (headless browser export, Plotly's
  JS-side export) rather than deferring a second time. This risk is the project.
- **Contracts too rigid for real data.** Users' columns won't match. Mitigation
  is a mapping step, not stricter validation.
- **Curation doesn't scale.** Review is manual by design — that's the moat — but
  if per-template review time stays high, coverage targets slip. Measure it from
  the first batch.
- **Sustained solo effort.** The build went dormant for seven months. Phasing
  here is deliberately ordered so each phase produces something usable on its
  own, rather than requiring a 4–6 week continuous sprint as v1 assumed.

---

## Sequencing

Phases are dependency-ordered, not calendar-ordered. v1's "4–6 weeks from alpha
to launch" did not survive contact with reality and no replacement estimate is
offered here in its place.

**Phase 0 — Restart.** Rotate credentials, update model config, verify the
pipeline runs end to end on two templates, resolve the signed-URL expiry.
*Exit: `generate_base_code.py --limit 2` completes cleanly and the catalog's
existing links resolve.*

**Phase 1 — Library.** Fix rendering. Formalize contracts and caveats. Add review
status. Build out coverage.
*Exit: 150+ reviewed templates, each with code, dataset, render, contract, and
caveats.*

**Phase 2 — Surface.** Gallery, detail view, bring-your-own-data render with
sandboxed execution.
*Exit: someone other than you renders a chart from their own data.*

**Phase 3 — Business.** Accounts, pricing, payment — scoped on Phase 2 evidence.

**Team.** One person. v1 assumed 2–3 with an optional designer; that was never
the reality and the plan should stop pretending otherwise.
