# ChartGen PRD

**Version 3.3 — October 25, 2026**
Supersedes v3.2 (Sept 15). Phase 3's workspace has been tested by hand, and this
version records what that testing changed: the user can now format the chart as
well as caption it, columns are bound by **position** instead of by name, the
figure fits its own text on screen and in the download, and every template
carries a slot for its designer credit. Adds R13–R16. Everything not listed
below carries forward from v3.2 unchanged.

---

## Changes in 3.3

| Section | 3.2 said | 3.3 says |
|---|---|---|
| Positioning | The library supplies the encoding | The library supplies the encoding **and its defaults**. Colour, font and background are defaults a person may override, the same way they own the captions |
| Column binding | Implicit: the template finds its data by column name, and a near-miss name gets a "Rename" suggestion | New R14. Columns are bound by **order and type**. Header names are the user's and never need to match the sample |
| Chart format | Not addressed | New R13. A collapsible **Chart format** section: series colours, label colour, gridline colour, background, font family, font size |
| Fit | Not addressed. Templates fix height and margins; a longer subtitle ran off the chart | New R15. The figure grows to fit its own text. Nothing is cut off on screen or in the download |
| Export | Server-side PNG/SVG for the operator's run flow only | R15. A **Download** in the workspace: PNG (2×) and SVG, at the size drawn on screen |
| Attribution | Not addressed | New R16. Every template carries a designer credit and a reference link. **Placeholder until sourced** |
| Phase 3 | Read-only gallery built; bring-your-own-data remaining | The workspace is built and in testing. Formatting, binding, fit and export are Phase 3 work |

---

## Positioning — amended

v3.2's division of labour stands, with one row clarified:

| The library's job | The user's job |
|---|---|
| The chart form | What the numbers are |
| The encoding — and **a default look for it** | What they mean |
| Validated parameters | The title, subtitle, legend wording, source credit |
| Caveats | Whether the claim is worth making |
| | **Colour, font and background, if the default doesn't suit** |

Formatting is the user's in the same sense captions are: it is **passed in at
render time and never written into the stored template**. The template stays
reusable, and a template's defaults stay visible as defaults — "Reset" returns
to them.

What formatting must not do is change what the encoding *means*. Where colour
carries meaning — gains against losses, a highlighted category against the rest
— the control is per role ("Above zero", "Below zero"), never one colour for
everything. A template whose meaning lives in the contrast between two colours
gets two pickers, not one.

---

## Requirements — new in 3.3

### R13 — Chart format

A **Chart format** section in the workspace sidebar, collapsed by default.

| Control | Applies to |
|---|---|
| Series colours | One picker per colour role the template declares (bars; above/below zero; first/second share; highlighted line). Named by role, not by hex |
| Label colour | Text drawn at the data: value labels on bars, endpoint call-outs |
| Gridline colour | Every axis gridline |
| Background | Figure and plot area (and the map's background, for maps) |
| Font family | Every text element. A short list of fonts that render identically in the browser and in the download |
| Font size | Base size. Every text element scales from it, so the template's hierarchy (title larger than tick labels) survives |

**How it is applied.**

- **Colour roles** are declared per template in the catalog and map to the
  template's own constants (`BAR_COLOR`, `POSITIVE_COLOR`, `PALETTE`, …). They
  are set the way chart settings already are: as constants applied before
  `build_figure` runs, so the template's own logic — which bar gets which colour
  — is what uses them.
- **Everything else** is applied to the built figure, after captions. It does
  not require the template to expose anything, so it works on every template
  without regenerating one.
- **The defaults shown are the template's own values**, read from the figure it
  drew, not a second copy kept in the UI that could drift from it.
- **Formatting never reaches the stored template.** It travels with the render
  request, like the data and captions.

### R14 — Columns bound by position and type

**Before:** a template found its data by column name. A paste whose first row
was data — no header at all — had its first row silently eaten as column names,
and every name that didn't match the sample was an error with a "Rename"
suggestion.

**Now:**

- **The order of columns is the contract.** The template's roles are listed in
  order under *What this chart needs* — "1. Groups (text) · 2. Values (number)" —
  and the first column fills the first role, the second the second. The user
  arranges their columns to match; they never rename them.
- **Header names are the user's.** They appear in the grid as pasted and are
  never compared to the sample's.
- **Header detection.** If the first row looks like data — a number in a column
  whose other values are numbers — it is read as data, and the columns are named
  *Column 1, Column 2, …*. Otherwise it is read as column names.
- **A notice after "Use this data"** says exactly what was decided: which column
  is being used for which role, whether the first row was read as names or as
  data, and any extra columns the chart will ignore. It carries one action: flip
  the header decision. Everything else is fixed by reordering the data.
- **Type checks stay, and name the user's column.** "Column 2, ‘Pct’, should
  hold numbers" — position and the user's own name, never the sample's.
- **Optional roles come last.** A template's optional columns (map labels,
  label coordinates) sit at the end of the order, so a short paste simply omits
  them.
- **Retired:** the name-mismatch finding and its Rename button.

This is a deliberate trade. Binding by name let columns arrive in any order but
demanded names nobody but this tool uses; binding by position demands an order
but accepts any names. Order is visible on screen in both the needs list and the
grid, and the notice states the binding every time, so a wrong order is caught
on the first draw rather than inferred from a refusal.

### R15 — Fit and export

**Fit.** Templates fix a width, a height and margins so their PNG export is
deterministic. In the workspace the width follows the panel, and Plotly does not
wrap text — so a longer subtitle ran off the right edge, and a second line ran
into the plot. **Structurally valid, visibly broken: the recurring failure.**

The figure is fitted after every draw, by measuring what was actually rendered:

1. Any title or annotation line wider than the space it has is wrapped at a word
   boundary.
2. If text then extends above the figure, below it, or into the plot, the
   margin on that side grows and the figure grows with it. The plot area keeps
   its size; the figure gets taller.
3. Repeated until nothing overflows, with a bound on passes.

Fitting is to the **text**, not to the row count — the goal is that nothing is
cut off, not that the chart resizes itself around the data.

**Export.** A Download control in the chart panel: **PNG** at 2× and **SVG**,
drawn from the fitted figure at the size shown on screen. What is downloaded is
what was on screen — same wrap, same margins, same formatting. No preset sizes
for now.

**Acceptance:** for every template, a title, subtitle and source each three
times their sample length draw with every text element inside the figure and
no text overlapping the plot, on screen and in the PNG.

### R16 — Designer attribution

Every template is reverse-engineered from someone's published chart. The
library owes that designer a credit.

- Each catalog entry carries `attribution: {designer, url}`. Shown on the
  library card and in the workspace header as **"Design adapted from …"**,
  linking to the original.
- **Placeholder until sourced.** Neither the designer nor the original article
  URL is recorded anywhere today — the Notion row's `Asset URL` points at the
  screenshot in storage, not the publication. Until each is filled in, the line
  reads *"Design adapted from: original designer (credit to be added)"* so its
  purpose is clear.
- **Not drawn on the chart or the download.** The figure's source line belongs to
  the user (R11). Attribution is the library's statement about where the form
  came from; it lives in the library's UI.
- **To source later:** two Notion properties, `Original URL` (url) and
  `Designer credit` (text), authored by hand. No derivation — like `Subject`,
  only a person can say it, and a model guessing a byline is R11's failure in a
  new place.

---

## Also fixed

- **"Use this template" on library cards** was drawn as a full-size dark button:
  a second `.cta` rule meant for the upload page overrode the card's. Renamed so
  each keeps its own style.

---

## Sequencing — Phase 3, amended

**Phase 3 — surface.** Gallery built. Workspace built and in testing; R13–R16
are its current work. Remaining after them: sourcing R16's credits, and
sandboxed execution before user data drives `exec()` beyond a single trusted
operator (unchanged from v3.2).

---

## Standing cautions — added

- **Fit is checked by measurement, not by estimate.** Character-count wrapping
  looks right on the sample and breaks on the first wide font. Measure the
  rendered text.
- **Positional binding moves the failure, it doesn't remove it.** Columns in the
  wrong order with compatible types — two number columns swapped — draw a valid,
  wrong chart. The notice stating the binding is the only defence; it must appear
  on every replace, not only when something is wrong.
