# ChartGen — Recovery Assessment

**Date:** 2026-09-12
**Supersedes:** the "What's broken → B0" section of `docs/audit-2026-09.md`, and corrects several
findings that depended on it.
**Writes made this session:** two, both authorised — the `CLAUDE.md` relocation (§1) and the
Stage D `requests.patch` error handling (§7). Nothing else was modified.

## Evidence standard

The prior audit inferred project deletion from NXDOMAIN and was wrong. Every claim below is
tagged:

- **[VERIFIED]** — observed directly against a live service this session (SQL against the
  Supabase Postgres instance, HTTP against Supabase Storage, Notion REST API, or a local file
  read), with the observation reproduced in this document.
- **[INFERRED]** — reasoned from verified evidence but not itself observed. Each one names what
  would settle it.

Object inventory was taken by querying `storage.objects` / `storage.buckets` over SQL, then
cross-checked against live HTTP GETs. Reconciliation matched Notion URLs to object keys by exact
string, with case-insensitive and basename fallbacks applied to every miss before calling it a
miss.

---

## 0. Correction to the correction

Your correction is right that the project was not deleted, and the audit's B0 is void as written.
But the reason the audit saw NXDOMAIN is not stale DNS, and it is not resolved by the resume.

**`SUPABASE_URL` in `.env.local` points at a project reference that does not exist.
The live project has a different reference.** **[VERIFIED]**

```
SUPABASE_URL           host = tnzqhmecjcdgfoemhfdq.supabase.co   → NXDOMAIN
                              (confirmed against 8.8.8.8, 1.1.1.1, and the system resolver;
                               db.tnzqhmecjcdgfoemhfdq.supabase.co also NXDOMAIN)
SUPABASE_DB_URL        host = aws-1-us-east-2.pooler.supabase.com → resolves; CONNECTED
                              PostgreSQL 17.4, and the pooler username's tenant is
                              sdpvhujlgakikcizaklw — a different project reference
SUPABASE_DB_URL_DIRECT host = db.tnzqhmecjcdgfoemhfdq.supabase.co → NXDOMAIN
```

Decoding the `ref` claim from each API key (payload only; no key material is reproduced here)
confirms `.env.local` is carrying credentials for **two different Supabase projects**: **[VERIFIED]**

| Variable | Project ref | Role claim | Status |
|---|---|---|---|
| `SUPABASE_URL` | `tnzqhmecjcdgfoemhfdq` | — | **dead ref** |
| `SUPABASE_SERVICE_ROLE_KEY` | `tnzqhmecjcdgfoemhfdq` | `service_role` | key for the dead ref |
| `SUPABASE_DB_URL_DIRECT` | `tnzqhmecjcdgfoemhfdq` | — | **dead ref** |
| `SUPABASE_DB_URL` (pooler) | `sdpvhujlgakikcizaklw` | — | **LIVE** |
| `SUPABASE_ANON_KEY` | `sdpvhujlgakikcizaklw` | `anon` | key for the live ref |
| `NEXT_PUBLIC_SUPABASE_ANON_SECRET` | `sdpvhujlgakikcizaklw` | **`service_role`** | key for the live ref |

`https://sdpvhujlgakikcizaklw.supabase.co` resolves and serves. **[VERIFIED]**

Two consequences:

1. **You verified Postgres through the pooler**, whose hostname is a shared AWS load balancer that
   resolves for every Supabase customer regardless of project state. That check confirmed the
   *live* project is healthy; it could not have detected that `SUPABASE_URL` names a different,
   dead one. Both of us were right about different projects.
2. **The only working `service_role` key for the live project is stored under the name
   `NEXT_PUBLIC_SUPABASE_ANON_SECRET`.** The audit flagged this name as a possible disclosure on
   shape alone; it is now confirmed to be a service-role key under a `NEXT_PUBLIC_` prefix, and it
   is the *only* one that works. Treat as compromised and rotate — but not before §8 step 2,
   because rotating it while `SUPABASE_SERVICE_ROLE_KEY` still holds the dead project's key would
   leave no working credential at all.

**What I cannot determine:** whether `tnzqhmecjcdgfoemhfdq` was an earlier project that was
deleted, or whether the resume issued a new reference. **[INFERRED — leaning "earlier,
separate project"]**, because the live project's bucket was created 2025-08-27 and holds
objects continuously from 2025-09-17 onward, which spans the entire period the dead ref's URLs
were supposedly being minted — yet *no* stored Notion URL anywhere references the dead host
(see §3). Settled by opening the Supabase dashboard and reading the project list.

---

## 1. Housekeeping — instruction context

**Before.** `/Users/paulraymond/Documents/CLAUDE.md` (2,574 bytes) was loaded as project
instructions for every session rooted in `DataViz/`, because Claude Code walks parent directories
for `CLAUDE.md`. Its content is a "SYSTEM: Twitter Intelligence Analyst" prompt with directives
including *"Return ONLY valid JSON"*, *"No explanation. No markdown. No extra text."*, and a
tweet-classification taxonomy with `{{CATEGORIES}}` / `{{TOPICS}}` placeholders left unfilled.

It was in force during the entire audit session. It instructed JSON-only output for a task whose
deliverable was a markdown document — the two directly conflict, and the audit followed your
explicit request over the file.

**Action taken** *(authorised write #1)*:

```
/Users/paulraymond/Documents/CLAUDE.md
  → ~/.claude/orphaned-prompts/twitter-intelligence-analyst-CLAUDE.md
```

Moved rather than deleted, since it is presumably live for its own project. Verified absent from
the original path afterward. **[VERIFIED]**

**After.** Scanned the full hierarchy: **[VERIFIED]**

| Path | State |
|---|---|
| `~/.claude/CLAUDE.md` | absent |
| `~/CLAUDE.md` | absent |
| `~/Documents/CLAUDE.md` | **removed this session** |
| `DataViz/CLAUDE.md` | absent |
| `DataViz/viz_gallery/CLAUDE.md` | present — scoped to `viz_gallery/`, legitimately this project's |

**What changed in my instruction context:** the JSON-only output constraint, the tweet
taxonomy, the importance-scoring rubric, and the retweet/quote-tweet handling rules are all
gone. `viz_gallery/CLAUDE.md` remains and is correct for this repo, though it carries one factual
error worth fixing separately: it maps `NOTION_PROD_DATABASE_ID` to "Viz Asset Library (v2)",
when live that ID is the *Viz library* database — and as §5 shows, that distinction turns out to
matter a great deal.

---

## 2. Storage inventory

Bucket `viz-training-assets` exists in the live project, is marked **public**, and was created
2025-08-27. **1,079 objects, 152,637,949 bytes (146 MiB).** **[VERIFIED via SQL]**

| Prefix | Objects | Bytes | Created | What it is |
|---|---|---|---|---|
| `raw/` | 450 | 149,115,284 | 2025-09-17 | **Source chart images**, original filenames (`Screen Shot 2020-03-18 at 4.11.27 PM.png`) |
| `files/` | 401 | 2,526,855 | 2025-09-25 | Thumbnails, `files/<cid>/<cid>_thumb.jpg` (400 + 1 placeholder) |
| `base_code_templates/` | 220 | 755,268 | 2025-10-02 | Stage C′ output, `<cid>_base_template.py` |
| `datasets/` | 4 | 756 | 2025-09-17 → 10-02 | **3 real CSVs** + 1 placeholder |
| `charts/` | 3 | 239,786 | 2025-09-17 → 09-23 | **2 real PNG renders** + 1 placeholder |
| `code/` | 1 | 0 | 2025-09-25 | **`.emptyFolderPlaceholder` only — no code objects at all** |

There is no `renders/` prefix. The rendered-output path in the code is `charts/`.

### Reconciliation against the 2,349 Notion asset URLs

The audit counted 2,349 `Asset URL` + `Thumbnail` values. Including `Base Code URL`, the full
population is **3,073 Supabase URLs across the three databases**. Matching each to an object key:
**[VERIFIED]**

| Database | Property | Count | Mode | Key shape | Object |
|---|---|---|---|---|---|
| PROD | `Asset URL` | 399 | public | `raw/<original name>` | **PRESENT** |
| PROD | `Thumbnail` | 399 | public | `files/<cid>/<cid>_thumb.jpg` | **PRESENT** |
| CodeTemplates | `Base Code URL` | 217 | signed → 2030 | `base_code_templates/<cid>_base_template.py` | **PRESENT** |
| CodeTemplates | `Base Code URL` | 507 | public | `code/<cid>/<cid>_base.py` | **MISSING** |
| CodeTemplates | `Thumbnail` | 253 | signed → 2026-09 | `files/<cid>/<cid>_thumb.jpg` | **MISSING** |
| Assets(v2) | `Asset URL` | 449 | signed → 2026-09 | `files/<cid>/<cid>_source.png` | **MISSING** |
| Assets(v2) | `Asset URL` | 100 | public | `raw/<cid>/<cid>_thumb_<hash>.png` | **MISSING** |
| Assets(v2) | `Asset URL` | 100 | mixed | `charts/…` (assorted) | **MISSING** |
| Assets(v2) | `Thumbnail` | 649 | mixed | same four shapes | **MISSING** |

**Totals: 1,015 URLs resolve to a live object. 2,058 are orphaned.** Zero Notion-hosted file
attachments — every asset reference is a Supabase URL. **[VERIFIED]**

### The distinction you asked for

**"URL expired, object present" — re-signable: 0 URLs.** No URL in the catalog is in this
category. The bucket is **public**, so signing is not required at all: a public-mode URL for any
present object returns 200 with no token. Verified by fetching one of each class over HTTP —
PROD `Asset URL` → 200 `image/png`; PROD `Thumbnail` → 200; CodeTemplates signed
`base_code_templates/` → 200, 3,922 bytes; and by direct public-URL fetch of
`charts/CHT-4B4998/CHT-4B4998_chart.png` → 200, 148,167 bytes. **[VERIFIED]**

The 253 `CodeTemplates.Thumbnail` and 449 `Assets(v2).Asset URL` entries carry tokens expiring
this month, but their objects are absent, so expiry is not what ails them.

**"Object missing" — genuinely absent: 2,058 URLs**, spanning three cases:

1. **507 × `code/<cid>/<cid>_base.py`.** Verified 404 over HTTP (`{"statusCode":"404",
   "error":"not_found"}`). Not recoverable from storage, but **not lost** — see §3.
2. **1,298 × Assets(v2) `Asset URL` + `Thumbnail`.** Every one of the 649 rows is orphaned,
   across four mutually incompatible key conventions (`files/<cid>/<cid>_source.png`,
   `raw/<cid>/<cid>_thumb_<hash>.png`, `charts/<cid>/<cid>_thumb_<hash>.png`,
   `charts/<original name>`). The bucket contains **zero** `_source.png` objects. I checked all
   100 `raw/` misses case-insensitively and by basename: 0 matched either way, so these are
   genuine absences rather than encoding or case drift. **[VERIFIED]**
3. **253 × CodeTemplates `Thumbnail`.** Same `files/<cid>/<cid>_thumb.jpg` shape that resolves
   for PROD rows, but for chart IDs that have no thumbnail object.

### What happened to `code/`

Timeline, correlating Notion row creation dates against object creation dates: **[VERIFIED]**

```
2025-09-18   253 CodeTemplates rows created, Base Code URL → code/…      (= the 253 with a
                                                                           Data contract, and
                                                                           the 253 files in
                                                                           generated/plotly/)
2025-09-24   254 more rows created, same code/ prefix                    (→ 507; the 249
                                                                           duplicate chartids)
2025-09-25   code/.emptyFolderPlaceholder created; zero sibling objects
2025-10-02   217 rows created, base_code_templates/ → 220 objects, all still present
```

Supabase writes `.emptyFolderPlaceholder` when a folder is created with no contents. A
placeholder dated *after* two runs that wrote into that prefix, with nothing beside it, reads as
a delete-then-recreate. **[INFERRED]** — the 507 rows demonstrably had URLs minted, and
`upload_code_to_supabase` mints a URL only after an upload call returns, so the objects almost
certainly existed on 2025-09-18 and 2025-09-24. Settled by checking the Supabase dashboard's
storage logs, if retention covers it.

Either way the outcome is verified and the loss is nil: everything that was under `code/` exists
in two other places (§3).

---

## 3. Source images — the audit's central error

The audit called the source images "the critical loss … no local copy and not recoverable."
**That was wrong.** They are the single best-preserved asset in the project. **[VERIFIED]**

| Category | Count | Location | State |
|---|---|---|---|
| Source chart images in the bucket | **450** | `raw/<original filename>`, 149 MB | **live, public, fetched 200** |
| Thumbnails in the bucket | **400** | `files/<cid>/<cid>_thumb.jpg` | **live, public, fetched 200** |
| PROD rows whose `Asset URL` resolves to a source image | **399 of 400** | → `raw/` | **100% intact** |
| PROD rows whose `Thumbnail` resolves | **399 of 400** | → `files/` | **100% intact** |
| Assets(v2) rows whose image resolves | **0 of 649** | four dead conventions | **fully orphaned** |
| Images attached to Notion pages as file objects | **0** | — | none exist |
| External (non-Supabase) image URLs | **0** | — | none exist |

The Production database — the one the pipeline is actually supposed to run on — has **complete,
live, publicly-fetchable source imagery for every row**. Stage C can re-run against it today
without restoring anything.

The 649-row Assets(v2) database is a superseded predecessor whose assets were migrated or
re-keyed and whose old references were never updated. Its orphaning is cosmetic, not a loss:
its content lives on in PROD.

### Generated code is also not lost

The 507 orphaned `code/` URLs correspond to templates that survive in **two** independent places:
**[VERIFIED]**

- **253 local files** in `generated/plotly/`, one per chart ID with a `Data contract`
- **507 Notion page `code` child blocks** holding the full untruncated script (2.3–5.3 KB each,
  versus the 1,800-char `Source code` property)

Cross-check: the 253 local chart IDs are exactly the 253 with a populated `Data contract`,
and the 254 rows added 2025-09-24 are a re-run of the same set (249 duplicate chart IDs + 5).
Nothing unique sits behind a dead URL.

---

## 4. Connectivity

| Check | Result |
|---|---|
| Live project hostname `sdpvhujlgakikcizaklw.supabase.co` | resolves (172.64.149.246), serves 200 **[VERIFIED]** |
| `SUPABASE_URL` hostname `tnzqhmecjcdgfoemhfdq.supabase.co` | **NXDOMAIN on three independent resolvers [VERIFIED]** |
| Host referenced by stored Notion URLs | **`sdpvhujlgakikcizaklw.supabase.co` — all 3,073 of them [VERIFIED]** |
| Postgres via pooler | connected, PostgreSQL 17.4, 45 tables **[VERIFIED]** |
| Postgres via `SUPABASE_DB_URL_DIRECT` | fails, NXDOMAIN **[VERIFIED]** |
| Public object fetch | 200 **[VERIFIED]** |
| Signed object fetch (2030 TTL) | 200 **[VERIFIED]** |

**Saying it loudly, as asked — but it is the opposite of the feared direction:** the hostname did
not change. **Every URL stored in Notion already points at the live host.** The stale reference
exists in exactly one place: `.env.local`. The catalog is correct and the configuration is wrong.

This inverts the audit's §3.1 claim that stored URLs were dead. They were never dead; the audit
tested the wrong hostname because it took `SUPABASE_URL` as authoritative and never compared it
to the URLs in the catalog. Fixing three lines of `.env.local` restores every script's ability to
reach storage — no re-signing, no re-pointing, no backfill.

Confirmed intact in Postgres, per your note: `nfl_weekly_report`, `station_daily`, `line_daily`,
`national_state_view`, plus `target_districts_view`, `nfl_game_actives`,
`nfl_game_actives_latest`. **[VERIFIED]** None of these belong to ChartGen — ChartGen uses
Postgres only as a *query* source for Stage D datasets, so its health matters but its schema
does not.

---

## 5. Has Stage D ever written anything?

**To storage: three times, the last one incomplete. To Notion: never.** **[VERIFIED]**

Every Stage C/D artifact in the bucket, exhaustively:

```
charts/CHT-4B4998/CHT-4B4998_chart.png     148,167 B   2025-09-23 22:52
charts/CHT-F3152E/CHT-F3152E_chart.png      91,619 B   2025-09-23 23:11
datasets/CHT-4B4998/CHT-4B4998.csv             383 B   2025-09-22 23:03
datasets/CHT-F3152E/CHT-F3152E.csv             217 B   2025-09-23 23:11
datasets/CHT-00DB0F/CHT-00DB0F.csv             156 B   2025-10-02 17:18
code/.emptyFolderPlaceholder                     0 B   2025-09-25 13:21
```

Tracing those three chart IDs into the Production database: **[VERIFIED]**

| Chart ID | In PROD? | Status | Dataset URL | Final Code URL | Chart Image | Code Preview |
|---|---|---|---|---|---|---|
| `CHT-4B4998` | **not found** | — | — | — | — | — |
| `CHT-F3152E` | **not found** | — | — | — | — | — |
| `CHT-00DB0F` | yes | `3. Needs hydration` | — | — | — | — |

And across all 400 PROD rows: **0 have `Dataset URL`, 0 have `Final Code URL`, 0 have
`Chart Image`, 0 have `Code Preview`.** Status distribution is 397 × `2. In progress`,
2 × `1. Intake`, 1 × `3. Needs hydration`. **[VERIFIED]**

### Reading

- **The two complete runs (2025-09-23) predate the PROD pipeline.** Neither chart ID exists in
  PROD; they came from the earlier `hydrate_viz_library_v2.py` era. They are the only two
  rendered charts this project has ever produced — and both are live and fetchable right now.
- **The one PROD-era attempt (2025-10-02, `CHT-00DB0F`) got as far as uploading a dataset and
  then stopped.** No chart PNG, no final code object, no Notion write-back. Its row is the single
  row still sitting at `3. Needs hydration` that the audit noticed.
- **`4. Complete` never landed, and could not have.** It is not among the Status property's
  options (`1. Intake`, `2. In progress`, `3. Needs hydration`, `4. Hydrated`, `Needs Review`,
  `5. Complete`). Notion `status` properties — unlike `select` — will not create options via the
  API, so the value is rejected rather than silently added. **[VERIFIED that the option is absent
  and that no row carries it; INFERRED that the API rejects rather than creates — this is
  documented Notion behaviour, and it is confirmed indirectly by the fact that 507 runs of the
  Stage C code, which uses a `select` property, *did* create a new `Draft` option.]**

### Were the success logs lying? Yes — and here is the mechanism

Notion validates a `PATCH /pages/{id}` **atomically**. Stage D sends `Dataset URL`,
`Final Code URL`, `Code Preview`, `Chart Image`, and `Status` in **one** request. An invalid
`Status` option rejects the entire payload — so all five fields fail together, not just the
status.

The response was discarded, so the script printed `UPDATED {chartid}: Status set to
'4. Complete'` and incremented its success counter on a rejected write. That is precisely the
shape of the evidence: a dataset object physically present in storage for `CHT-00DB0F`, and a
PROD row with every output field empty.

**[INFERRED — strongly.]** The atomic-rejection mechanism explains all-five-fields-empty better
than any alternative, and it is consistent with every observation. It is not *proven*, because
proving it requires sending the bad PATCH and reading the 400, which is a write and out of scope
this session. One line confirms it once writes are permitted.

This matters beyond Stage D: the PRD's "built and working" list was partly assembled from logs
that reported success on rejected writes. **Any claim in that list sourced from console output
rather than from an inspected artifact should be treated as unverified.** The two things that
genuinely worked — 220 base-code templates and 2 rendered charts — are visible as objects, not
as log lines.

---

## 6. Corrections to `docs/audit-2026-09.md`

| Audit claim | Corrected |
|---|---|
| **B0** — Supabase project deleted or reaped; every asset gone | **Void.** Project is live. `SUPABASE_URL` names a *different, non-existent* project reference; the live project holds the bucket with 1,079 objects. |
| Notion's stored URLs are dead | **Wrong.** All 3,073 already point at the live host. 1,015 resolve to present objects. The bad hostname exists only in `.env.local`. |
| "Source chart images have no local copy and are not recoverable" | **Wrong, and it was the audit's worst call.** 450 source images live in `raw/` (149 MB), 400 thumbnails in `files/`, and 399/400 PROD rows resolve to them. |
| "All 2,349 asset URLs taken down" | 1,015 of 3,073 resolve. 2,058 are orphaned — but 1,298 of those belong to the superseded Assets(v2) DB and 507 point at code that survives locally and in Notion. |
| "No renders exist anywhere" | **2 renders exist** (`charts/`, 2025-09-23) and both fetch 200. |
| "Zero datasets" | **3 datasets exist.** |
| **B3** — 1,151 image URLs expiring this month is a live risk | Moot twice over: those objects are already absent, and the bucket is **public**, so no URL needs a token. |
| **R2 / "decide between public bucket, signed URLs, or a proxy"** | Already decided — the bucket is public. The open task is deleting the signed-URL code path, not choosing a strategy. |
| `NEXT_PUBLIC_SUPABASE_ANON_SECRET` "shape suggests service-role" | **Confirmed** `service_role`, and it is the **only working key** for the live project. |
| Two rival Stage C scripts, `generate_base_code.py` the better one | **Inverted.** `generate_base_code.py` reads `NOTION_DATABASE_ID` = **Assets(v2), the fully-orphaned DB** — it cannot fetch a single source image. `generate_base_code_v2.py` reads PROD, whose imagery is 100% live, and its 220 objects are the only surviving Stage C output. |
| B7 — 249 duplicates from a swallowed exception in `target_page_exists()` | Mechanism unchanged, but the cohorts are now dated: 253 rows (09-18) + 254 rows (09-24) into `code/`, then 217 (10-02) into `base_code_templates/`. |

**What the audit got right and still stands:** every Claude model string is retired (B1);
rendering is not a stub and kaleido works (B2) — now corroborated by two real PNGs in storage;
the `"Base code URL"` property-name mismatch (B4); the Stage C/D database disconnect (B5) and
the invalid status option, both now confirmed by their fingerprints in the data; the
`export_images_to_storage.py` `NameError` (B6); duplicates (B7); the `data_contract` deletion in
the working tree (B8); no CI (B9).

---

## 7. Stage D error handling *(authorised write #2)*

`Scripts/hydrate_viz_library_v3.py`, the live Stage D. Error handling only; no other behaviour
changed.

```python
            if not dry_run:
                resp = requests.patch(f"{NOTION_BASE_URL}/pages/{lib_row['id']}", headers=get_notion_headers(), data=json.dumps({"properties": update_properties}))
                if resp.status_code >= 400:
                    # Notion validates the whole PATCH atomically: one bad property
                    # (e.g. a Status option that does not exist in the schema) rejects
                    # every field in this update. Never report success on a 4xx/5xx.
                    raise RuntimeError(
                        f"Notion write-back failed for {chartid}: HTTP {resp.status_code} — {resp.text[:500]}"
                    )

            print(f"UPDATED {chartid}: Status set to '{STATUS_COMPLETE}'")
            processed += 1
```

`RuntimeError` is caught by the existing per-row `except Exception`, which prints
`FATAL ERROR processing {chartid}: …` including Notion's own message naming the offending
property. The row is **not** counted in `processed` and `UPDATED` is **not** printed. Compiles
clean (`py_compile`). The file is untracked in git, so there is no diff to show against `HEAD`.

Two notes, neither actioned:

- `Scripts/hydrate_viz_library_v2.py:297` has the identical discarded-response defect. Left
  alone — you scoped this to Stage D's live script, and v2 is superseded. Flagging it so it
  isn't rediscovered later.
- `hydrate_viz_library_v3.py:243` (`requests.get(base_code_url).text`) is also unchecked and will
  silently inject a 404 body as "base code" into the LLM prompt. Not a `patch`, so out of scope,
  but it is the second-most likely source of a false success.

---

## 8. Calling it

### The call: **repair, and a small one.** Not a rebuild.

The pipeline is not broken in the ways the audit concluded. What survived:

- **Postgres** — live, healthy, all named tables intact **[VERIFIED by you and re-confirmed here]**
- **Storage** — live, public, 1,079 objects, 146 MiB **[VERIFIED]**
- **450 source chart images** — the irreplaceable input, 100% present **[VERIFIED]**
- **A complete, coherent production catalog** — 400 PROD rows, every image and thumbnail
  resolving **[VERIFIED]**
- **220 base-code templates** in storage + **253 more** in `generated/plotly/` + **507** in Notion
  code blocks **[VERIFIED]**
- **253 data contracts, 2,305 caveat lines** in Notion **[VERIFIED, prior session]**
- **2 rendered charts and 3 datasets** — proof the render path executes end to end **[VERIFIED]**

Nothing irreplaceable is missing. The orphaned 2,058 URLs are a superseded database (1,298) plus
code that exists in two other places (507) plus thumbnails that can be regenerated (253).

### But the honest second half of the call

**The pipeline has never worked end to end — not once, and not because of infrastructure.**

The two rendered charts came from a superseded script against a superseded database in September
2025. The current-generation path has produced, in total, one CSV. Every blocker standing between
here and a working run is a **configuration or wiring defect**, and all of them were introduced by
editing, not by dormancy:

1. `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` name a dead project — no script can reach storage
2. `generate_base_code.py` reads the orphaned Assets(v2) DB — no script run from it can fetch an image
3. Stage C writes `Base Code URL` into CodeTemplates; Stage D reads it from PROD, where 0/400 have it
4. Stage D writes a Status option that does not exist, poisoning the entire write-back
5. Every Claude model string is retired

Five defects. Four are one-line fixes. **None of them is a rebuild, and none of them is storage.**

That is the real lesson of the dormancy: **nothing decayed.** The project stopped because it was
mis-wired and the failures were invisible — which is exactly what §7 addresses.

### Cheapest next action

**Fix three lines of `.env.local` and run Stage C′ against two rows.** Roughly ten minutes:

```
SUPABASE_URL=https://sdpvhujlgakikcizaklw.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<the value currently in NEXT_PUBLIC_SUPABASE_ANON_SECRET>
CLAUDE_MODEL=claude-opus-5
```

Then:

```
python Scripts/generate_base_code_v2.py --limit 2 --overwrite
```

`generate_base_code_v2.py` — not `generate_base_code.py` — because it reads the PROD database
whose imagery is 100% live, it writes to the storage prefix whose objects all survive, and it is
the only Stage C script with anything to show for itself. It needs no code change beyond the
model string.

**Success looks like:** two new objects under `base_code_templates/`, two Code Templates rows
updated, and two public URLs returning 200. That is the first verified end-to-end Stage C run
this project has had, and it costs one config edit and two LLM calls.

Do **not** start with `generate_base_code.py`. It reads a database with zero resolvable images;
it will fail on every row regardless of what else is fixed. The audit's recommendation to keep it
and fold v2 into it was based on flag surface and the `data_contract` model — both real
advantages, but they are worth nothing against a dead input. Port those two things *into* v2
later; run v2 now.

### Revised Phase 0

Gate step 0.1 from the audit ("determine whether the project exists") is **closed** — it exists,
and the answer sized Phase 0 downward, exactly as intended.

| # | Action | Cost | Was in audit? |
|---|---|---|---|
| 1 | Repoint `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` at `sdpvhujlgakikcizaklw` | 2 lines | no — audit had "restore storage" |
| 2 | Rotate the live service-role key; remove the `NEXT_PUBLIC_`-named copy | dashboard | yes, reframed |
| 3 | `CLAUDE_MODEL=claude-opus-5`; fix the retired fallback and the `claude-3.5-sonnet` typo | 3 lines | yes |
| 4 | Run `generate_base_code_v2.py --limit 2 --overwrite`; confirm 200s | 10 min | **new — this is the cheapest proof** |
| 5 | `STATUS_COMPLETE` → `4. Hydrated` in `hydrate_viz_library_v3.py:45` | 1 line | yes |
| 6 | Join Stage C → Stage D (`Base Code URL` into PROD, or lookup by `chartid`) | small | yes |
| 7 | Run `hydrate_viz_library_v3.py --limit 1`; confirm a third render | — | yes |
| 8 | Back up all three Notion DBs **including page child blocks** | 1 script | yes — still worth doing |
| 9 | Decide Assets(v2)'s fate: archive it, or re-key its 649 rows against PROD | decision | **new** |
| 10 | Delete the signed-URL code path — the bucket is public | cleanup | **new, replaces R2** |
| 11 | Commit. 764 lines of pipeline rewrite are still uncommitted against one commit | — | yes |

Steps 1, 3, and 4 together are the whole of "is this project alive?" — under fifteen minutes, and
worth doing before anything else on the list.

### Still open, deliberately not investigated

- Whether `tnzqhmecjcdgfoemhfdq` was a separate deleted project or a prior reference for this one
  (§0) — needs the dashboard
- Whether `code/`'s contents were deleted on 2025-09-25 (§2) — needs storage logs
- Whether Notion rejects rather than creates the bad status option (§5) — needs one write
- Why Assets(v2) accumulated four key conventions — history, not blocking
