# The `/viz-library-analysis` Workflow — Reconciled Against Stage C

**Date:** 2026-09-13
**Question:** is the `viz_gallery/` analysis workflow redundant with Stage C's caveats, or
complementary to them? This bears on the open R5 question in the PRD.
**Scope:** read-only. The orchestrator was not run and nothing was regenerated.
**Verification:** **[VERIFIED]** = observed against the live system this session.
**[INFERRED]** = reasoned from verified evidence.

**Answer up front:** **complementary on substance, redundant on two fields, and currently
inoperable.** It answers a question Stage C never asks — *should this chart exist in this form?* —
but it re-derives two classifications the catalog already holds by hand, and it points at a
database whose images are all dead.

---

## 1. Has it ever run?

**No.** **[VERIFIED]**

- `viz_gallery/analysis-outputs/` contains exactly one file: `.gitkeep`, 0 bytes. The workflow
  writes `01-analyze-*.md`, `02-synthesize-full.md`, and `03-visual-cases-full.md`. None exist.
- Every file in `viz_gallery/` was written on **2026-04-08 between 13:07 and 13:13** — six
  minutes end to end, in this order: the three skills, the orchestrator, `CLAUDE.md`,
  `.gitkeep`, then `settings.local.json` at 13:12. Built in one sitting and never used since.
- **No git history.** `viz_gallery/` is untracked (`?? viz_gallery/`), so there are no commits to
  read. The mtimes above are the only record.
- `settings.local.json` corroborates it: its allowlist is the `mkdir` commands that created the
  skill directories, plus `npx -y @notionhq/notion-mcp-server --version|--help`. Those are
  setup-time permissions. Nothing in it reflects a run.

## 2. What does it produce?

There are no outputs to show, so what follows is the template from
`analyze-viz-image/SKILL.md`, not a sample. Flagged as such because you asked for the real thing
and it does not exist.

Per chart, `01-analyze-[chartid].md` with YAML frontmatter (`chartid`, `asset_name`, `page_id`,
`asset_url`, `analyzed_at`, `classification`, `visual_type_primary`, `visual_type_secondary`) and
six sections:

| # | Section | What it captures |
|---|---|---|
| 1 | What is it? | chart type, layout, series count, data density |
| 2 | **Message Conveyed** | the one-sentence insight claim, plus explicit vs implied |
| 3 | Visual Type | one of ~11 taxonomy values, plus an optional secondary |
| 4 | **What It Does Well** | 2–4 communication strengths |
| 5 | **What It Lacks** | 1–3 honest gaps — missing baselines, chart-type mismatch, accessibility |
| 6 | Classification | `STANDARD` or `UNIQUE`, with a one-sentence justification |
| — | **Recommendation Signal** | a forward-looking lesson: when to use this type |

Stage 2 groups these by visual type, weights `STANDARD` at 1.5× and `UNIQUE` at 1.0× "to lean
into simplicity," and aggregates strengths, gaps and message patterns. Stage 3 turns the
synthesis into prescriptive "Visual Cases" — *Best for* / *When to choose this* / *Why it works* /
*Where it breaks down*.

The pipeline is: image → judgement about communication → reusable guidance about format choice.

## 3. Which database does it read, and does it resolve?

**It reads Viz Asset Library (v2), and its imagery is entirely dead.** **[VERIFIED]**

`viz-library-analysis.md` line 34 hardcodes `25ce89d6bdbe80f288c7dad00e0fa813`. Resolved live,
that is **Viz Asset Library (v2)** — 649 rows, 17 properties, the superseded predecessor. Not
`Viz library` (PROD).

Spot-checking the `Asset URL` values the workflow would `curl`:

```
Viz Asset Library (v2):  HTTP 400  ×6 of 6 sampled   ("Object not found")
Viz library (PROD):      HTTP 200  ×3 of 3 sampled   (raw/Screenshot ….png)
```

Consistent with the audit's full reconciliation: **0 of 649** Assets(v2) image URLs resolve, and
399 of 400 PROD ones do.

Two further problems in the same file:

- Its Stage 0 offers "Filter by status — only pages with a specific Status value (e.g.
  `4. Complete`)". **Viz Asset Library (v2) has no `Status` property at all** **[VERIFIED]**, and
  `4. Complete` is not a valid option on PROD's either.
- `viz_gallery/CLAUDE.md` labelled that same ID as `NOTION_PROD_DATABASE_ID`. Corrected this
  session.

## 4. Would it run?

**It would start and then fail at the first download.** **[INFERRED — not executed, as scoped]**

The Notion MCP server **is** configured — `~/.claude.json` has `notion` globally
(`https://mcp.notion.com/mcp`) and again under the `DataViz` project
(`https://mcp.notion.com/sse`). So its stated prerequisite is met, contrary to what the stale
guide implied. **[VERIFIED]** In this session only `mcp__notion__authenticate` and
`mcp__notion__complete_authentication` are surfaced, so an interactive authorization would be
needed first. **[VERIFIED that those are the only tools exposed; INFERRED that authorizing is all
that stands in the way.]**

Past that, the expected sequence:

1. Stage 0 prompts for scope. The "filter by status" branch cannot work — no such property.
2. Stage 1 queries the database and gets 649 rows with `chartid` and `Asset URL`.
3. Each subagent runs `curl -sL "[ASSET_URL]" -o /tmp/viz-[CHARTID].png`. **Every URL returns
   HTTP 400 with a JSON error body.** `curl -sL` exits 0 and writes that body to the file, so the
   skill's own guard — *"non-zero exit, empty file, or file < 1KB"* — catches it on size (~88 bytes).
4. Each subagent writes `STATUS: ERROR / REASON: Could not download image`.
5. Stage 2 parses those, flags every entry as ERROR, and skips them from synthesis — producing an
   empty synthesis.
6. Stage 3 writes Visual Cases from nothing.

So it fails safely and loudly rather than producing wrong analysis. The single-line fix is to
repoint the orchestrator at `NOTION_PROD_DATABASE_ID`, whose images resolve — but see §5 before
doing that.

## 5. The substantive comparison

Stage C caveats for the three completed charts, against what `analyze-viz-image` would produce.

### The two vocabularies

**Stage C caveats — implementation-facing.** From `CHT-6FBD47`:

```
choropleth map (USA-states locationmode, Albers USA projection)
categorical/binned colour encoding rather than a continuous colorbar
one trace per category to produce a discrete legend (colorbar suppressed)
horizontal legend placed above the plot area
selective in-map text annotations via a text-only Scattergeo layer
annotation-dependent: labels depend on lat/lon and a boolean flag column
custom categorical ordering of the legend bins
paper-referenced source credit annotation
```

Every line names a Plotly construct or an encoding decision. These tell you **how the chart is
built** and **what the data must supply** — `Scattergeo`, `vrect`, `locationmode`, "one trace per
category", "depends on lat/lon and a boolean flag column". They are reproduction instructions.

**Analysis workflow — reader-facing.** *Message Conveyed*, *What It Does Well*, *What It Lacks*,
*Recommendation Signal*. These tell you **whether the chart communicates** and **when to reach for
the type**. They are editorial judgement.

### Overlap, measured

Classifying all **26** caveat lines across the three charts by which analysis dimension they could
populate: **[VERIFIED]**

| Analysis dimension | Caveat lines that could fill it |
|---|---|
| 1 — What is it? (structure) | **10** |
| 3 — Visual type | 0 (the type is named inside dimension-1 lines, not separately) |
| 2 — Message conveyed | **0** |
| 4 — What it does well | **0** |
| 5 — What it lacks | **0** |
| 6 — STANDARD / UNIQUE | **0** |
| No analysis dimension — pure implementation detail | **16** |

So ~38% of caveat content maps onto one of six analysis dimensions, and **none of it reaches the
four that carry the workflow's actual value**. Conversely, nothing in the analysis output would
tell you that the legend is built from one trace per category.

**They are not the same information.** Stage C says *how to rebuild it*; the workflow says
*whether it was worth building*.

### Where it genuinely is redundant

Two of the six dimensions duplicate fields the catalog **already holds, curated by hand**:
**[VERIFIED]**

| Analysis output | Existing PROD property | The three charts |
|---|---|---|
| `visual_type_primary` (~11-value taxonomy) | `Viz type` (multi_select, 163 curated options) | `Choropleth Map` · `Small Multiples Bar Chart` · `Line Chart` |
| `STANDARD` / `UNIQUE` classification | `Standard` (checkbox) | `True` · `False` · `True` |

PROD's `Standard` checkbox **is** the STANDARD/UNIQUE classification, already set. The workflow
would re-derive it by LLM and then weight synthesis 1.5×/1.0× on its own derived value rather than
on the operator's. Its taxonomy is also coarser than `Viz type` — "map" against `Choropleth Map`.

That is the redundancy, and it is narrow: **2 of 6 dimensions**, both re-deriving what a human
already decided.

### What it adds that nothing else in the system has

- **The message.** No property anywhere holds the insight claim. `Asset name` is a title
  ("Increase in Arrests by U.S. State"), not a finding.
- **Strengths and gaps.** Nothing captures *this chart hides its baseline* or *the colour encoding
  is the only cue*. The caveats state that a legend is suppressed; they never judge whether
  suppressing it was right.
- **Forward-looking guidance.** *Recommendation Signal* and the Visual Cases are the only part of
  the system that answers "which format should I use for this insight?" — which is the original
  stated purpose of the whole project.

### Bearing on R5

R5 asks for `caveats` as a controlled vocabulary — "dual-axis, log scale, percent stacking,
cumulative sum, faceting, Cleveland layout, annotation-dependent". **Stage C's caveats already are
that axis**, and the three charts show it working: `annotation-dependent`, `reversed y-axis
order`, `small-multiple faceting`, `categorical/binned colour encoding`, `diverging bars around a
non-zero baseline`. The 2,305-line legacy corpus is the same axis, unnormalized.

The analysis workflow is a **second, orthogonal axis** — analytical intent and communication
quality — which is closer to PRD **R7** (categorize by analytical intent: "show composition over
time", "compare ranked categories") than to R5. Reading it as an R5 alternative conflates two
taxonomies that should both exist.

**Recommendation: keep both, feed one into the other, and drop the two redundant fields.**

1. **Do not retire it.** It is the only source of message, strengths, gaps, and format guidance,
   and it is the only piece aimed at the original product goal.
2. **Repoint it at `NOTION_PROD_DATABASE_ID`.** One line in `viz-library-analysis.md`. Its current
   target cannot yield a single image.
3. **Drop dimensions 3 and 6 from the skill; read them instead.** `Viz type` and `Standard` are
   already curated per row. Consuming them rather than re-deriving them removes the redundancy,
   removes a disagreement risk, and makes the 1.5× weighting reflect the operator's judgement.
4. **Keep the outputs separate from `Caveats`.** Different axis, different consumer. A `Message`
   or `Visual case` property is the natural home; overwriting `Caveats` would destroy the
   structural vocabulary R5 needs.
5. **Feed direction: Stage C → analysis, not the reverse.** Stage C already resolves what a chart
   *is*; the workflow should start from that and spend its judgement on whether it *works*.

One caution worth recording: the workflow analyzes the **source screenshot**, not the rendered
output. Once Stage D produces `charts/<cid>/<cid>_chart.png`, "what it lacks" becomes far more
useful pointed at what the library actually renders than at the original a chart was copied from.

## Summary

| Question | Answer |
|---|---|
| Ever run? | **No.** Empty `analysis-outputs/`; all files written 2026-04-08 in six minutes; untracked in git |
| Produces? | 6-dimension per-chart analysis → weighted synthesis → prescriptive Visual Cases |
| Reads? | **Viz Asset Library (v2)** — 0 of 649 images resolve |
| Runs today? | Notion MCP **is** configured; would need authorization, then fail at every download, writing `STATUS: ERROR` per chart |
| Redundant? | **2 of 6 dimensions** (`visual_type_primary`, STANDARD/UNIQUE) duplicate curated `Viz type` and `Standard` |
| Complementary? | **Yes** — message, strengths, gaps and format guidance exist nowhere else; 0 of 26 caveat lines touch them |
| R5? | Stage C's caveats *are* the R5 structural vocabulary. This workflow is **R7** — analytical intent — not an R5 alternative |
