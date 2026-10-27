# Sector-label accuracy pilot — NSE vs BSE on small and micro caps

Run: 2026-10-28 · worktree `20261027T184539Z-fce4cff9` · seed **20261028** · sample drawn and written to
`sample.json` **before** any evidence text was read (only evidence *existence* and segment-row counts were checked, as the
brief requires for the 2+ segment over-sampling).

The question this answers: decision 8 of `BACKWARD_REQUIREMENTS_AUDIT_2026-10-27` (G4 / F2-F5, F8) — can the BSE label fill
the 2,177 companies with no sector, and can either exchange label be trusted for small caps?

## 1. Sample

| stratum | n | SMALL | MICRO | notes |
|---|---|---|---|---|
| A — has an NSE `company_industry` label | 150 | 77 | 73 | 28 distinct NSE sectors; 57 with 2+ reported segments (>= 40 required) |
| B — BSE-only / unlabelled (no `company_industry` row) | 50 | 13 | 37 | all have a BSE scrip code |
| **total** | **200** | 90 | 110 | 200 unique ISINs |

- Cap tier: `company_forensic_health.market_cap_inr_cr` buckets (LARGE >= 50,000 cr, MID 10,000-50,000, SMALL 1,000-10,000,
  MICRO < 1,000) at the 2026-10-19 vintage; `master_companies.market_cap_tier` fallback. Active companies only.
- Six draws had no locally-held FY2024-25 business evidence and were replaced by the next draw of the same stratum
  (`replacements.csv`): ANNU, MADRASFERT, ARDEE + 3 unnamed BSE-only ISINs -> BLKASHYAP, MANALIPETC, SADBHIN, ASHOKAMET,
  VALIANTORG, RCCL.
- BSE headers: project client `reality_engine/ingestion/bse_fundamentals_client.py` -> `ComHeadernew/w?scripcode=`, raw JSON
  in `.tmp/bse_header/<code>.json`. **206 sample codes fetched (200 initial + 6 replacements), 206 OK, 0 failures**, plus one
  availability probe (ABB 500002) outside the sample. `.tmp/bse_header/` holds 221 files because an aborted earlier draw
  (killed when the sample frame was corrected) left cached responses for codes that are not in the final 200. Pacing:
  client floor 1-2 s + 2.5 s wrapper = ~13-15 requests/min (limit 20/min). The bulk `ListofScripData` endpoint was not touched.

## 2. Ground truth and grading rubric

Per company, from locally-held FY2024-25..FY2025-26 evidence only: AR segment revenue (`ar_facts.db/ar_facts`,
category `segment`), the newest annual-report business text (`equity_intelligence.db/document_chunks`), AR business
quotes, deck facts (`deck_figures.db`). Revenue share by segment is computed where a revenue segment table exists
(52 rows); otherwise the business is taken from the "engaged in / manufactures / provides" sentences and the AR's
industry sections (142 rows); 5 rows had no usable business signal (`cannot_tell` + 6 A rows too thin = 11).

Each label is graded at two levels — sector and industry/basic industry:

- **correct** — names the dominant business (or a co-dominant segment >= 40% of segment revenue);
- **partly** — right sector/wrong industry, a label for a minor segment, or a too-generic label
  ("Diversified", "Industrial Products", "Other Textile Products", "Commercial Services & Supplies");
- **wrong** — no support in the FY2024-25 evidence;
- **stale** — fits a discontinued line and not the current business (0 triggered this pilot; the closest case is EUROTEXIND,
  graded `partly`: Realty label, textile plant shut since 2019, the segment table still prints a dormant yarn segment);
- **cannot_tell** — evidence too thin to establish the business.

NSE level 1 = `company_industry.sector`; level 2 = `company_industry.industry` (with `basic_industry` recorded).
BSE level 1 = header `sector` (BSE macro: Industrials / Commodities / Consumer Discretionary / ...);
level 2 = header `industry` (e.g. "Heavy Electrical Equipment"); BSE `industry_new` is reported separately because it sits
between the two in granularity. NSE's sector taxonomy is coarser than its industry taxonomy, and BSE's `sector` is coarser
than NSE's, so sector-level accuracy is **not** directly comparable across exchanges; the `industry_new` column is the
fairer NSE-sector comparison.

Taxonomy mappings (NSE 28 sectors / 64 industries, BSE sector + ~75 BSE industry strings, ~30 business families) are in
`taxonomy.py`; two rows carry documented manual adjudications (`overrides.json`). Accuracy = `correct / (correct+partly+
wrong+stale)`, with `cannot_tell` excluded and reported.

## 3. Accuracy

All 200 rows; NSE columns are graded only for the 150 A rows (`n/a` for B).

| group | level | correct | partly | wrong | stale | cannot_tell | n graded | accuracy |
|---|---|---|---|---|---|---|---|---|
| all 200 | NSE sector | 136 | 6 | 2 | 0 | 6 | 144 | **94.4%** |
| all 200 | NSE industry | 110 | 27 | 7 | 0 | 6 | 144 | **76.4%** |
| all 200 | BSE sector (macro) | 160 | 6 | 23 | 0 | 11 | 189 | **84.7%** |
| all 200 | BSE industry | 142 | 33 | 14 | 0 | 11 | 189 | **75.1%** |
| all 200 | BSE industry_new (sector granularity) | 161 | 11 | 17 | 0 | 11 | 189 | **85.2%** |
| A (NSE-labelled) | NSE sector | 136 | 6 | 2 | 0 | 6 | 144 | **94.4%** |
| A (NSE-labelled) | NSE industry | 110 | 27 | 7 | 0 | 6 | 144 | **76.4%** |
| A (NSE-labelled) | BSE sector | 129 | 3 | 12 | 0 | 6 | 144 | **89.6%** |
| A (NSE-labelled) | BSE industry | 118 | 23 | 3 | 0 | 6 | 144 | **81.9%** |
| A (NSE-labelled) | BSE industry_new (sector granularity) | 130 | 10 | 4 | 0 | 6 | 144 | **90.3%** |
| B (unlabelled) | BSE sector | 31 | 3 | 11 | 0 | 5 | 45 | **68.9%** |
| B (unlabelled) | BSE industry_new (sector granularity) | 31 | 1 | 13 | 0 | 5 | 45 | **68.9%** |
| B (unlabelled) | BSE industry | 24 | 10 | 11 | 0 | 5 | 45 | **53.3%** |

Split of the NSE-labelled 150 (multi-segment = 2+ segment names extracted from the newest AR; `n` = rows with a grade,
`cannot_tell` excluded):

| group | n | NSE sector | NSE industry | BSE sector | BSE industry | BSE industry_new |
|---|---|---|---|---|---|---|
| single-segment | 87 | 95.4% | 78.2% | 90.8% | 83.9% | 90.8% |
| multi-segment | 57 | 93.0% | 73.7% | 87.7% | 78.9% | 89.5% |
| SMALL cap | 76 | 96.1% | 78.9% | 86.8% | 86.8% | 89.5% |
| MICRO cap | 68 | 92.6% | 73.5% | 92.6% | 76.5% | 91.2% |

Reading:

- **NSE's sector label is reliable (94.4%); its industry label is not (76.4%).** 27 of 144 rows are only `partly`
  precisely because NSE's industry is generic ("Other Utilities" x5, "Commercial Services & Supplies" x4,
  "Industrial Products" x4, "Industrial Manufacturing" x3, "Other Construction Materials" x2).
- **BSE is about the same as NSE at industry level when both exist (BSE industry 81.9% on the A rows; BSE
  `industry_new` 90.3% at sector granularity vs NSE 94.4%), but it degrades on the tail** — the BSE-only names it is
  supposed to fill are the ones where BSE's own industry field is weak.
- Multi-segment companies are harder for both exchanges at industry level (NSE 73.7%, BSE 78.9%) — the label picks one
  segment and the other(s) disappear. Micro caps are worse than small caps at industry level (NSE 73.5% vs 78.9%).
- `cannot_tell`: 11/200 (5.5%), well under the 15% cap — 6 A rows (AVROIND, BAJAJCON, AUGMONT, PRIORITY, INFOMEDIA and one
  ISIN without an NSE symbol `INE070C01037`) and 5 B rows (SBECSUG, AMFORG, SHINDL, VINYOFL, INE706A01022). The missing
  evidence is the same in every case: the newest AR has no segment revenue table and its business-description chunks were
  either absent or boilerplate (e-voting/AGM notices).

## 4. Error types

Rows can carry more than one error (one per level), so the per-source counts sum above the 75 rows with at least one
non-correct grade.

| error type | NSE rows | BSE rows | what it means |
|---|---|---|---|
| too-generic label | 18 | 28 | "Industrial Products", "Other Textile Products", "Commercial Services & Supplies", "Other Utilities" — right-ish but useless for peers/similarity |
| plainly wrong | 9 | 37 | evidence gives no support for the label (e.g. SEZ developer labelled Auto Components) |
| mixed business | 7 | 9 | label names one leg of a genuinely multi-business company; other legs not represented |
| minor segment | 1 | 0 | label names a segment that is < 40% of revenue |
| conglomerate | 1 | 0 | 3+ segments, no majority; label picks one |
| pivot / stale | 0 | 0 | no row met the strict stale test; EUROTEXIND is the near miss (see above) |

The single biggest defect is **generic labels**, and it is BSE-side: "Other Textile Products" alone is the BSE industry
for 11 of the 200 companies (all genuine textile names — technically right, operationally useless), "Industrial Products"
for 6 more, "Trading & Distributors" for 3. On the NSE side the same disease at a smaller dose: "Other Utilities" (5),
"Commercial Services & Supplies" (4), "Industrial Products" (4), "Industrial Manufacturing" (3).

## 5. The unlabelled group — can BSE fill the 2,177?

For the 50 BSE-only/unlabelled companies (45 with a usable BSE header + evidence):

| BSE field | correct | partly | wrong | cannot_tell | accuracy |
|---|---|---|---|---|---|
| `sector` (macro) | 31 | 3 | 11 | 5 | **68.9%** |
| `industry_new` (mid) | 31 | 1 | 13 | 5 | **68.9%** |
| `industry` (specific) | 24 | 10 | 11 | 5 | **53.3%** (75.6% correct-or-partly) |

So BSE can give a defensible **coarse sector** for about two names in three, and an exact **industry** for only about
one in two. It is materially weaker here than on the 150 NSE-labelled names (BSE industry 81.9%, industry_new 90.3%),
which is exactly the population the fill is supposed to serve. Worst observed patterns: a shipyard labelled
"Petrochemicals", an aluminium trader labelled "Logistics Solution Provider", a synthetic-leather maker labelled
"Gems, Jewellery And Watches", an investment holding company labelled "Industrial Products".

## 6. Recommendation

Do **not** use the BSE `industry` string as a wholesale filler for the 2,177 unlabelled names. A mix, in this order:

1. **Derive our own label from segment revenue** where the AR gives a usable segment table (52/200 = 26% here; higher for
   larger names). Store `label_source='segment_revenue'`, the top segment, its share, and the doc/page or chunk id. This is
   the only source that is actually about the company rather than about a directory entry, and it is the one that survives
   a business pivot.
2. **Keep BSE as a separate, provenance-stamped column** — `bse_sector`, `bse_industry_new`, `bse_industry`,
   `bse_header_fetched_at`, never overwriting `master_companies.industry`. Use `industry_new` (85.2% at sector granularity)
   rather than `industry` (75.1%) for coarse bucketing, and treat "Other X" / "Industrial Products" / "Trading &
   Distributors" as *no label*, not as a label (34 of 200 BSE industry labels here were generic).
3. **Build the BSE->NSE crosswalk only on unambiguous pairs**, measured on the A strata where both labels exist
   (`bse_industry_new` -> NSE sector agrees ~90% of the time; `bse_industry` -> NSE industry ~82% on A, ~53% on B). Then
   auto-fill a sector for B-only names only when the crosswalk row is unique, BSE agrees with the segment evidence when the
   latter exists, and the name is not in the generic set. Expect ~2/3 of the 2,177 to get a coarse sector this way.
4. **Review queue for the rest**: B-only names with no segment table and a generic or missing BSE industry — about one in
   three of the tail. That is a few hundred names, not 2,177; a reader or a human can clear them.
5. **Fix the master placeholder separately**: 1,556 of the 3,733 "General Diversified" placeholders already have an NSE
   classification (audit 2026-10-27). Copying those is free and better than any BSE fill — but note NSE's industry is only
   76.4% right, so copy the *sector* freely and keep the industry behind the review flag.

Net: BSE is a usable **coarse-sector** source with a confidence flag and a crosswalk, not an industry oracle. Segment
revenue is the label of record where it exists; BSE is a fallback column; neither exchange's industry string should be
copied into the master without provenance.

## 7. Ten worked examples

1. **ISTLTD** (INE684B01029, MICRO) — NSE `Automobile and Auto Components / Auto Components`, BSE `Auto Components &
   Equipments`. AR segments: **SEZ 75%, Manufacturing 25%**; the business text says "development and operating IT/ITES SEZ".
   Both labels **wrong** — the company's main revenue is a special economic zone, not auto parts.
2. **SAICAPI** (INE531X01018, MICRO) — NSE `Services / Commercial Services & Supplies`, BSE `Diversified Commercial
   Services`. AR note: "engaged in business of buying, selling or otherwise dealing in shares, debentures and securities" —
   an investment company. Both **partly** (generic label hiding a financial business).
3. **GANESHBE** (INE388A01029, MICRO) — NSE `Oil Gas & Consumable Fuels / Oil / Oil Storage & Transportation`.
   Segments: **Chemicals 46%, Liquid Storage Terminals 54%**. **Partly** — the label names only the storage half.
4. **MINALIND** (INE097E01028, MICRO) — NSE `Services / Commercial Services & Supplies / Trading & Distributors`, BSE
   `Trading & Distributors`. AR: "single reportable segment: manufacturing and trading of gems and jewellery". **Partly** —
   the label names the trading channel, not the manufacturing business.
5. **SWANCORP** (INE665A01038, SMALL, BSE-only) — BSE `Commodities / Chemicals / Petrochemicals`. AR segments:
   **Shipyard 100%** ("Swan Defence and Heavy Industries"). **Wrong**.
6. **CONTAINER** (INE319U01022, MICRO, BSE-only) — BSE `Services / Services / Logistics Solution Provider`. AR: "the
   company operates in only one segment — trading of aluminium products"; 28 aluminium/metal hits in the business text.
   **Wrong**.
7. **MAYUR** (INE799E01011, MICRO, BSE-only) — BSE `Consumer Discretionary / Consumer Durables / Gems, Jewellery And
   Watches`. The AR text is about the **leather / leather-products** industry (synthetic leather). **Wrong**.
8. **HERCULES** (INE688E01024, MICRO, BSE-only) — BSE `Industrials / Capital Goods / Industrial Products`. AR: "holding
   strategic investments, predominantly in group companies" — an investment holding company. **Partly** (generic label).
9. **AEROPLANE** (INE05TO01019, SMALL) — BSE `Fast Moving Consumer Goods / Other Agricultural Products`, NSE
   `Agricultural Food & other Products`. Segments: **Rice 99%**. NSE sector correct, BSE **partly** — "Other Agricultural
   Products" is a true but too-generic label.
10. **RRIL** (INE951M01037, MICRO) — BSE `Consumer Discretionary / Textiles / Other Textile Products`; 40 textile signals
    in the AR text. **Partly** — BSE's mid-level industry for textile small caps is routinely "Other Textile Products"
    (11 of the 200), which is unusable for peer grouping.

## 8. Limits / caveats

- 200-company, seed-fixed sample of **small and micro caps only**; results should not be extrapolated to large caps.
- Labels are **current snapshots** (`company_industry.fetched_at` 2026-10-19; BSE header fetched 2026-10-28). Neither store
  has `valid_from`, so "stale label" can only be inferred from the evidence, not from label history; the strict
  pivot/stale test found 0 rows.
- Ground truth is evidence-derived: 52 rows have a revenue segment table; 142 are classified from AR business text.
  A keyword family taxonomy plus acceptance sets is a judgement instrument, not a legal classification; the 2 manual
  adjudications are in `overrides.json`, and 11 rows are honestly `cannot_tell`.
- `multi_segment` is the sampling flag from AR segment-name extraction, not a verified count of Ind-AS segments.
- Excluded from the target population: 6 replaced draws whose newest AR had no usable business text, and names with no
  BSE scrip code (not part of the 2,177 question).
- The BSE header request count is 207 (206 sample codes + 1 probe); six codes that were in the pre-replacement list were
  fetched and are cached but are not in the final 200.

## 9. Files

- `sample.json` / `sample.csv` — the fixed 200-row draw (seed, strata, replacements).
- `replacements.csv` — the six evidence-driven swaps.
- `sector_label_pilot.csv` — **deliverable**: one row per company, labels, segment split, main business, evidence refs,
  four grades with reasons (+ BSE `industry_new` grade, evidence size).
- `evidence.json` — the per-company evidence bundle actually used.
- `grades.json`, `REPORT.md` (this file).
- Tooling: `sampling.py`, `evidence.py`, `grade.py`, `taxonomy.py`, `replace.py`, `fetch_bse.py`, `fetch_missing.py`,
  `stats.py`, `review.py`, `review_bse.py`, `diag.py`.
- Raw BSE responses: `.tmp/bse_header/<scripcode>.json`; results summary `.tmp/bse_header_results.json`.
