# Sector-label accuracy pilot — NSE vs BSE on small and micro caps (re-graded v2)

Run: 2026-10-28 · worktree `20261027T184539Z-fce4cff9` · seed **20261028** · the 200-company sample is
**unchanged** from v1 (`sample.json`, 200 unique ISINs, drawn before any evidence was read).

Question answered: decision 8 of `BACKWARD_REQUIREMENTS_AUDIT_2026-10-27` (G4 / F2-F5, F8) — can the BSE
label fill the 2,177 companies with no sector, and can either exchange label be trusted for small caps?

## 0. Re-grade v2 — what changed and why

The reviewer rejected v1 because its grades came from **keyword-family counts** ("text signals: finance
(6)"). That was true: 127 of 200 rows had a `segment_split` of the form `text signals: <family> (<count>)`
and their `main_business` was the most frequent keyword family in the text. Boilerplate ("finance cost",
"transport of goods", "securities", industry commentary) therefore decided many rows.

What v2 does instead:

1. **Every row is decided by reading** the AR business description / MD&A, the AR segment revenue table
   (where one exists), and deck or results text. 39 rows are decided from a segment revenue table, 98
   from AR prose, 49 from an AR "business / operations / segment" quote, 1 from a deck, 13 are
   `cannot_tell`. 76 rows carry a revenue split with shares. Every row carries a one-sentence
   `main_business`, the segment split with revenue shares where known, a verbatim quote of at most 25
   words, and the reference of the passage
   (`document_chunks[doc_id=... chunk=...]`, `ar_facts[isin=... category=...]`,
   `ar_facts[isin=... item=...]`, `deck_figures[sha256=...]`).
2. **No word counts anywhere.** `segment_split` never contains a text-signal count; where no revenue table
   exists it says so. The keyword-count taxonomy is no longer used for `main_business`.
3. **Labels are graded by meaning.** A label that names the business or a correct parent of it is
   `correct` (e.g. `Gems, Jewellery And Watches` for a jeweller, `Paints` for a paint maker,
   `Heavy Electrical Equipment` for a generator maker, `Water Supply & Management` for a water-treatment
   company). A too-generic label (`Other X`, `Industrial Products`, `Trading & Distributors`,
   `Diversified` for a single-business company), or one naming only a minor leg, is `partly`. A label
   naming a different business is `wrong`. A label that fits the company's old business while the
   evidence shows a pivot is `stale`.
4. **NSE's industry grade now uses the deepest NSE label held** (the `basic_industry` string when it is
   present and more specific). 30 of the 150 NSE-labelled rows repeat the sector string in the industry
   column, and in 26 of those the basic industry is different and more specific. Grading the repeated
   sector string as if it were an industry is exactly what produced the KDDL/AURUS "wrong" grades: NSE
   says `Consumer Durables / Consumer Durables / Gems Jewellery And Watches`, and the jewellery label is
   the one in play. The CSV now records both: `nse_industry` (as filed) and `nse_industry_graded` (the
   string actually graded). On the same 143 rows the shallow column scores 79.0% (113 correct, 6 wrong,
   24 partly) and the deepest label 87.4% (125 correct, 1 wrong, 17 partly) — the gap is the exchange
   repeating a coarse bucket at industry level, not 26 misclassified businesses.
5. **Every row still graded `wrong` was read a second time** (§6) and kept only where the passage clearly
   contradicts the label. 7 rows remain (v1 had 32 rows carrying `plainly_wrong`).

Three of the reviewer's ten examples need their premise corrected rather than their grade: **CONTAINER**
is Containerway International Ltd (BSE 540597, ISIN `INE319U01022`), *not* Container Corporation of
India, and its AR says it trades aluminium goods; **ASHSI** and **NEWMKTAVE** do carry explicit
principal-activity sentences, not boilerplate. Details in §5.

## 1. Sample and evidence (unchanged from v1)

| stratum | n | SMALL | MICRO |
|---|---|---|---|
| A — has an NSE `company_industry` label | 150 | 77 | 73 |
| B — BSE-only / unlabelled | 50 | 13 | 37 |
| **total** | **200** | **90** | **110** |

Cap tier from `company_forensic_health.market_cap_inr_cr` (2026-10-19 vintage), fallback
`master_companies.market_cap_tier`; active companies only. Six draws without FY2024-25 business evidence
were replaced by the next draw of the same stratum (`replacements.csv`) — the 200 ISINs are identical to
v1. BSE headers are the cached project-client responses in `.tmp/bse_header/` (206 codes fetched, 0
failures); no network was used in this re-grade. All database reads went through
`reality_engine.db.readonly.connect_ro`; nothing was written outside this worktree.

Evidence per company comes from the same `evidence.json` bundle: `ar_facts` segment rows and AR quotes,
`document_chunks` AR text (5 chunks/company), `deck_figures`. 13 rows have no business-bearing text at
all (boilerplate only, no readable text, or a dead business); they are `cannot_tell` and excluded from the
accuracy denominators. Evidence quality is the binding constraint: for 11 rows the bundle is e-voting /
auditor text only.

## 2. Accuracy — v1 next to v2

`correct` is the numerator; `partly`, `wrong` and `stale` count against; `cannot_tell` is excluded and
shown. v1 denominators differ slightly because v2 moved 7 rows into / out of `cannot_tell`.

| group | level | v1 correct | v1 acc | **v2 correct** | **v2 acc** | partly | wrong | stale | cannot_tell | n graded |
|---|---|---|---|---|---|---|---|---|---|---|
| all 200 | NSE sector | 136 | 94.4% | **139** | **97.2%** | 2 | 2 | 0 | 7 | 143 |
| all 200 | NSE industry (deepest label) | 110 | 76.4% | **125** | **87.4%** | 17 | 1 | 0 | 7 | 143 |
| all 200 | BSE sector (macro) | 160 | 84.7% | **174** | **93.0%** | 5 | 5 | 3 | 13 | 187 |
| all 200 | BSE industry (specific) | 142 | 75.1% | **147** | **78.6%** | 32 | 5 | 3 | 13 | 187 |
| all 200 | BSE industry_new (mid/macro) | 161 | 85.2% | **173** | **92.5%** | 5 | 6 | 3 | 13 | 187 |
| A (NSE-labelled 150) | NSE sector | 136 | 94.4% | **139** | **97.2%** | 2 | 2 | 0 | 7 | 143 |
| A (NSE-labelled 150) | NSE industry (deepest) | 110 | 76.4% | **125** | **87.4%** | 17 | 1 | 0 | 7 | 143 |
| A (NSE-labelled 150) | BSE sector | 129 | 89.6% | **137** | **95.8%** | 4 | 1 | 1 | 7 | 143 |
| A (NSE-labelled 150) | BSE industry | 118 | 81.9% | **120** | **83.9%** | 21 | 1 | 1 | 7 | 143 |
| A (NSE-labelled 150) | BSE industry_new | 130 | 90.3% | **136** | **95.1%** | 4 | 2 | 1 | 7 | 143 |
| B (unlabelled 50) | BSE sector | 31 | 68.9% | **37** | **84.1%** | 1 | 4 | 2 | 6 | 44 |
| B (unlabelled 50) | BSE industry | 24 | 53.3% | **27** | **61.4%** | 11 | 4 | 2 | 6 | 44 |
| B (unlabelled 50) | BSE industry_new | 31 | 68.9% | **37** | **84.1%** | 1 | 4 | 2 | 6 | 44 |

NSE-labelled split of the 150 (v1 → v2, deepest NSE industry label):

| group | n graded | NSE sector | NSE industry | BSE sector | BSE industry | BSE industry_new |
|---|---|---|---|---|---|---|
| single-segment | 86 | 96.5% (95.4%) | 87.2% (78.2%) | 95.3% (90.8%) | 83.7% (83.9%) | 95.3% (90.8%) |
| multi-segment | 57 | 98.2% (93.0%) | 87.7% (73.7%) | 96.5% (87.7%) | 84.2% (78.9%) | 94.7% (89.5%) |
| SMALL cap | 76 | 100.0% (96.1%) | 90.8% (78.9%) | 98.7% (86.8%) | 90.8% (86.8%) | 100.0% (89.5%) |
| MICRO cap | 67 | 94.0% (92.6%) | 83.6% (73.5%) | 92.5% (92.6%) | 76.1% (76.5%) | 89.6% (91.2%) |

## 3. How many grades changed, by direction

125 grade cells changed across the five levels, in 63 of 200 rows. At row level (sum of the five grades)
**47 rows improved, 15 worsened, 138 unchanged**. Cell transitions:

| transition | n | of which |
|---|---|---|
| `partly` → `correct` | 38 | generic/adjacent label that does name the business |
| `wrong` → `correct` | 32 | v1 "actual" was a keyword artefact (or shallow-industry artefact) |
| `correct` → `partly` | 20 | the label is generic ("Other Textile Products", "Other Financial Services") or names one leg of a multi-business company |
| `wrong` → `stale` | 6 | old business in the label, evidence shows a pivot |
| `cannot_tell` → `correct` | 6 | business actually stated (e.g. SBECSUG 10,000 TCD, SHINDL shrimp farming) |
| `wrong` → `cannot_tell` | 6 | bundle has no business text; v1 guessed |
| `partly` → `cannot_tell` | 4 | bundle has no business text |
| `correct` → `cannot_tell` | 4 | bundle has no business text (BAJAJCON, SAICAPI) |
| `wrong` → `partly` | 3 | label is a macro umbrella that partially covers the business |
| `correct` → `stale` | 2 | EUROTEXIND (textile plant closed 2019) |
| `partly` → `wrong` | 2 | label names a different business (MINALIND, HERCULES sector) |
| `partly` → `stale` | 1 | PROCLB (line of business changed) |
| `correct` → `wrong` | 1 | GVKPIL: power is 10% of external revenue, not the business |

The 15 worsened rows are the dishonest v1 "corrects" that the reading removed: generic labels
(`Other Textile Products` → `partly` on LAMBODHARA, BASML, RAJRILTD; `Other Financial Services` on HBPOR),
`Diversified` on GILLANDERS/RRIL (a four-business group and a two-business group: `partly`, not `correct`),
`Civil Construction` on SADBHIN (it operates BOT road concessions), and four rows moved to `cannot_tell`
where the bundle has no business text (BAJAJCON, SAICAPI, RCCL and one dead operation).

## 4. Error types, v1 → v2

Counts are rows with at least one level carrying the error; a row can carry more than one.

| error type | v1 | v2 | what it means |
|---|---|---|---|
| too-generic label | 39 | **26** | `Other Textile Products`, `Industrial Products`, `Other Utilities`, `Diversified` for one business, `Civil Construction` for a concessionaire |
| plainly wrong | 32 | **7** | the label names a different business |
| minor segment / mixed business | 1 + 8 | **7** | label names a leg that is not the main business |
| pivot / stale | 0 | **3** | label fits the old business, evidence shows the pivot |
| conglomerate | 1 | **1** | 3+ segments, no majority |
| cannot_tell | 0 | **13** | bundle cannot establish the business (excluded from accuracy) |

The single biggest defect is still **generic labels**, but the count halves (39 → 26) once the grader stops
inventing businesses: 32 of 187 BSE industry strings and 20 of 143 deepest NSE industry labels are
generic. "Plainly wrong" collapses from 32 to 7.

## 5. The ten named examples, re-graded

Grades are `NSE sector / NSE industry / BSE sector / BSE industry / BSE industry_new`
(`n/a` = no NSE label). "Family" is the business family I read (the CSV's `main_business_family`).

| company | actual business (family) | old | new | deciding passage |
|---|---|---|---|---|
| **KDDL** | watch components + watch/accessory retail (jewellery) | c/**w**/c/c/c | **c/c/c/c/c** | "FY25 total segment revenue - Watch, accessories and other luxury items and related services" — watches 77%, precision components 23% (`ar_facts[isin=INE291D01011]`) |
| **AURUS** | diamonds and related activities (jewellery) | c/**w**/c/c/c | **c/c/c/c/c** | "The Company is engaged in the business of diamonds and related activities" (`document_chunks[doc_id=35055 chunk=30]`) |
| **INDIGOPNTS** | decorative paints, construction chemicals, putty | c/**w**/**w**/c/c | **c/c/c/c/c** | "manufacture and sale of decorative paints, construction chemicals, putty and waterproofing products" (`ar_facts[isin=INE09VQ01012 category=business]`) |
| **MEDPLUS** | pharmacy retail chain | c/c/**w**/c/c | **c/c/c/c/c** | "medicines and various products could be sourced directly from manufacturers and efficiently delivered to customers in their local communities" (`document_chunks[doc_id=38835 chunk=1]`) |
| **CONTAINER** | **Containerway International Ltd**, aluminium-goods trading (metals) — *not* Container Corporation | n/a/n/a/w/w/w | **n/a/n/a/w/w/w** | "The company is engaged in the business of trading of Aluminum goods." (`document_chunks[doc_id=35271 chunk=55]`) |
| **IONEXCHANG** | water/wastewater treatment, ion-exchange resins (utilities) | c/**p**/c/**w**/c | **c/c/c/c/c** | "The Chemical segment engineers and supplies one of the broadest portfolios of ion exchange resins, adsorbents, specialty process chemicals, and customised treatment programs" (`document_chunks[doc_id=38453 chunk=38]`) |
| **TDPOWERSYS** | AC generators for captive power plants (capital goods) | n/a/n/a/c/**w**/c | **n/a/n/a/c/c/c** | "Received multiple Captive Power Plant (CPP) orders from a major turbine OEM" (`deck_figures[sha256=5c9a5097917c]`) |
| **VIMTALABS** | contract research / testing (healthcare) | n/a/n/a/**w/w/w** | **n/a/n/a/c/c/c** | "VIMTA believes it is amongst the leaders in the domestic market for GMP analytical services and GLP nonclinical services" (`document_chunks[doc_id=39594 chunk=21]`) |
| **ASHSI** | investments and lending (finance), post-pivot | n/a/n/a/**w/w/w** | **n/a/n/a/stale/stale/stale** | "principal activities comprised investment in shares, securities, bonds and mutual funds and the lending of funds" (`document_chunks[doc_id=39534 chunk=20]`) |
| **NEWMKTAVE** | financial advisory and investment activities (finance) | n/a/n/a/**w/w/w** | **n/a/n/a/w/w/w** | "Single business segment - financial advisory and investment activities; revenue from advisory services and securities trading" (`ar_facts[isin=INE800K01014 item=Single business segment - financial advisory and investment activities]`) |

Notes on the three disagreements with the reviewer's framing:

- **CONTAINER** is a symbol collision. `INE319U01022` / BSE 540597 resolves to *Containerway
  International Limited*, and the AR's own header in the bundle is "INDUS ALUMINIUM RECYCLERS LIMITED
  (Formerly known as CONTAINERWAY INTERNATIONAL LIMITED)". Container Corporation of India is a different
  ISIN and is not in the sample. The BSE labels (`Services / Logistics Solution Provider`) are wrong for
  an aluminium trader; the grade stands. This is a real lesson for the fill: **BSE scrip-code resolution
  must be by ISIN, never by symbol string.**
- **ASHSI** (Ashirwad Steels & Industries): the passage is an MD&A principal-activities sentence, not a
  keyword hit. The company is now an investment/lending vehicle. The BSE steel label is not "wrong" so
  much as **stale**: it fits the old steel business. Graded `stale`, not `wrong`.
- **NEWMKTAVE** (New Markets Avenue, formerly New Markets Advisory): its segment note says "financial
  advisory and investment activities". The BSE `Information Technology / Software Products` label names a
  different business. The grade stays `wrong`; the v1 "actual: finance" happened to be right, for the
  wrong reason.

The remaining v1 errors in this list — KDDL, AURUS, INDIGOPNTS, MEDPLUS, IONEXCHANG, TDPOWERSYS,
VIMTALABS — were all grader errors and are now `correct`.

## 6. Every row still graded `wrong` (7), hand-verified twice

Each was re-read against its full bundle a second time; the quote below is the passage that decides it.

1. **ISTLTD** (`INE684B01029`, MICRO) — NSE `Automobile and Auto Components / Auto Components`, BSE
   `Auto Components & Equipments`; main business: SEZ development (78% of segment revenue) plus precision
   engineering. Quote: *"engaged in the business of development and operating IT / ITES SEZ"*
   (`document_chunks[doc_id=36860 chunk=17]`; segment table `SEZ 78% / manufacturing 22%`). Wrong at NSE
   sector, NSE industry, BSE industry, BSE industry_new.
2. **MINALIND** (`INE097E01028`, MICRO) — NSE `Services / Commercial Services & Supplies`, BSE
   `Services / Trading & Distributors`; main business: diamond-studded gold and silver jewellery
   manufacture/export (exports 93%). Quote: *"primarily engaged in the business of manufacturing and
   export of Diamond Studded Gold & Silver Jewelry"* (`ar_facts[isin=INE097E01028 category=business]`).
   Wrong at NSE sector, BSE sector, BSE industry_new.
3. **SWANCORP** (`INE665A01038`, SMALL) — BSE `Commodities / Petrochemicals`; main business: integrated
   shipyard. Quote: *"Following the successful revival of one of India's largest integrated shipyards,
   FY26 marked SDHI's emergence as a strategic maritime manufacturing platform"*
   (`document_chunks[doc_id=38509 chunk=1]`; shipyard segment revenue Rs 28,214 lakh). Wrong at BSE
   sector, BSE industry, BSE industry_new.
4. **HERCULES** (`INE688E01024`, MICRO) — BSE `Industrials / Industrial Products`; main business:
   investment holding (hoists business demerged; name changed to Hercules Investments). Quote: *"The
   Company is primarily engaged in the business of holding strategic investments, predominantly in group
   companies"* (`document_chunks[doc_id=39088 chunk=13]`). Wrong at BSE sector and BSE industry_new;
   BSE industry is `partly` because `Industrial Products` is generic.
5. **CONTAINER** (`INE319U01022`, MICRO) — BSE `Services / Logistics Solution Provider`; main business:
   aluminium-goods trading. Quote: *"The company is engaged in the business of trading of Aluminum
   goods."* (`document_chunks[doc_id=35271 chunk=55]`). Wrong at BSE sector, BSE industry, BSE
   industry_new.
6. **MAYUR** (`INE799E01011`, MICRO) — BSE `Gems, Jewellery And Watches`; main business: leather and
   leather footwear (it has disposed of most PPE and reports zero revenue). Quote: *"The Company
   foresees significant opportunities in the leather footwear segment"*
   (`document_chunks[doc_id=36564 chunk=38]`). Wrong at BSE industry only; the macro sector
   `Consumer Discretionary` is correct.
7. **NEWMKTAVE** (`INE800K01014`, MICRO) — BSE `Information Technology / Software Products`; main
   business: financial advisory and investments. Quote: *"Single business segment - financial advisory and
   investment activities; revenue from advisory services and securities trading"*
   (`ar_facts[isin=INE800K01014]`). Wrong at BSE sector, BSE industry, BSE industry_new.

Three rows are `stale` rather than `wrong` (they fit the old business, and the evidence shows the pivot):
**EUROTEXIND** (textile plant discontinued 25 March 2019; realty label, no realty revenue yet),
**PROCLB** (line of business changed to consumer-durables marketing; no revenue yet), **ASHSI** (steel →
investments and lending).

## 7. What the numbers now say

- **NSE's sector label is right 97.2% of the time** on this population (139/143, 2 wrong: ISTLTD, and
  MINALIND where "Services" hides a jeweller). v1's 94.4% understated it slightly and included a wrong
  "actual" (GANESHBE was partly, now correct at 55% storage terminals).
- **NSE's industry label is right 87.4%** (125/143), not 76.4%. The 17 `partly` rows are all generic
  labels: `Other Textile Products` ×5, `Industrial Products` ×3, `Other Construction Materials` ×2,
  `Trading & Distributors` ×2, `Power Generation` ×2 (for an EPC contractor), and one each of
  `Other Agricultural Products`, `Other Food Products`, `Other Financial Services`. What v1 scored as
  "wrong industry" was mostly a generic industry string or the repeated sector string; only ISTLTD is
  plainly wrong.
- **BSE's macro (`sector`) and mid (`industry_new`) fields are reliable at sector granularity — 93.0% and
  92.5%** overall, 84.1% on the BSE-only population the fill is for. Only 5 of 187 BSE sector labels are
  plainly wrong plus 3 stale and 5 `partly` (labels that name one leg of a diversified business, or
  `Utilities` for a renewable-EPC contractor).
- **BSE's specific `industry` string remains the weak field: 78.6% correct** overall (32 generic, 5 wrong,
  3 stale, 5 `partly`), and only **61.4%** on the BSE-only names. It is *not* a wholesale filler.
- Multi-segment companies are no longer materially harder for the sector-level labels (NSE 98.2%, BSE
  96.5%) but remain harder at industry level (NSE 87.7%, BSE 84.2%). Micro caps are still worse than
  small caps at industry level (NSE 83.6% vs 90.8%; BSE 76.1% vs 90.8%), and the whole residual is
  generic-label and missing-evidence frequency.
- `cannot_tell` is 13/200 (6.5%), under the 15% cap: 7 A rows (AVROIND, SAICAPI, BAJAJCON, AUGMONT,
  PRIORITY, INFOMEDIA, and one ISIN without an NSE symbol `INE070C01037`) and 6 B rows (RCCL, `INE706A01022`,
  AMFORG, VINYOFL, HEERAISP, RISHDIGA). The missing evidence is the same in every case: the newest AR has
  no segment revenue table and its business chunks are absent, boilerplate (e-voting/AGM), industry
  commentary only, or unreadable (AVROIND's chunks are mojibake).

## 8. Recommendation

Do **not** use the BSE `industry` string as a wholesale filler for the 2,177 unlabelled names; the re-grade
sharpens, not softens, that conclusion. In order:

1. **Derive our own label from segment revenue** where the AR gives a usable segment table (76/200 = 38%
   here have a revenue split with shares; higher for larger names). Store `label_source='segment_revenue'`,
   the top segment, its share, and the doc/chunk ref. This is the only source about the company rather than
   about a directory entry, and it survives a pivot.
2. **Use BSE `sector` and `industry_new` as a coarse bucket with provenance** — 93.0% / 92.5% correct here,
   ~84% on the unlabelled tail. Keep them as separate columns (`bse_sector`, `bse_industry_new`,
   `bse_header_fetched_at`) and never overwrite `master_companies.industry`. Treat "Other X", `Industrial
   Products`, `Trading & Distributors` and `Diversified` as *no label*, not a label (32 of 187 BSE industry
   strings are generic).
3. **Do not use BSE `industry` as the fill value** (78.6% overall, 61.4% on the tail) except inside a
   human approval queue, and never for the multi-business names where it names one leg.
4. **Resolve by ISIN, never by symbol.** The CONTAINER/Containerway case is the standing example: the same
   symbol string belongs to a different company, and every label inherits the error. The 2,177 fill must
   join on `master_companies.isin` (or BSE scrip code) and keep the resolution auditable.
5. **Build the BSE→NSE crosswalk only on unambiguous pairs**, measured on the A strata where both labels
   exist (`bse_industry_new` → NSE sector agrees ~95%; `bse_industry` → NSE industry ~84%). Auto-fill a
   sector only when the crosswalk row is unique, BSE agrees with the segment evidence where the latter
   exists, and the label is not in the generic set. Expect ~4/5 of the 2,177 to get a coarse sector this
   way.
6. **Review queue for the rest**: B-only names with no segment table and a generic or missing BSE industry
   — about one in five of the tail, a few hundred names, not 2,177.
7. **Fix the master placeholder separately**: 1,556 of the 3,733 "General Diversified" placeholders already
   have an NSE classification (audit 2026-10-27). Copy the NSE *sector* freely (97.2% right); keep the NSE
   industry behind a review flag, since 17/143 industry labels are generic (though only 1 is plainly wrong).

Net: segment revenue is the label of record where it exists; BSE's macro/mid fields are a usable coarse
fallback with a confidence flag and an ISIN-keyed crosswalk; BSE's specific industry string is not an
oracle. Neither exchange's industry string should be copied into the master without provenance.

## 9. Limits

- 200-company, seed-fixed sample of **small and micro caps only**; do not extrapolate to large caps.
- Labels are current snapshots (`company_industry.fetched_at` 2026-10-19; BSE header fetched 2026-10-28);
  neither store has `valid_from`, so "stale" is inferred from the evidence, not from label history (3 rows
  met the test).
- Ground truth is evidence-derived and read by one grader; the quote and its reference are stored per row so
  any grade can be re-checked. A segment table is not a legal classification; 13 rows honestly say
  `cannot_tell`.
- The NSE industry comparison uses the deepest NSE label (see §0.4); that is the fair like-for-like
  against BSE's specific industry, but it is not the same string analysts read in the `nse_industry` column.
- 11 rows have only e-voting/AGM/auditor text in the bundle; they are `cannot_tell`, not "no label exists".
- `multi_segment` is the sampling flag from AR segment-name extraction, not a verified Ind-AS segment count.

## 10. Files and checks

- `sector_label_pilot.csv` — **deliverable**: one row per company; labels as filed, `nse_industry_graded`,
  segment split, `main_business` sentence, `main_business_family`, `business_basis`, `evidence_quote`,
  `quote_ref`, five grades with reasons, error types.
- `sector_label_pilot_v1.csv` — frozen v1 deliverable (from git HEAD), used for the change tables.
- `grades.json` — same rows as JSON for `stats.py` / downstream checks.
- `REPORT.md` (this file), `stats.py` (prints v1 vs v2 and the wrong/stale/cannot_tell lists).
- Tooling: `sampling.py`, `evidence.py` (v1 evidence builder, unchanged), `grade2.py` (v2 grader:
  resolves each quote to its source, grades by meaning), `taxonomy.py` (label→family map; no longer used
  for `main_business`), `replace.py`, `fetch_bse.py`, `fetch_missing.py`, `grade.py` (v1 grader, kept for
  provenance).
- The read decisions live in `.tmp/regrade/d1..d4.jsonl` (one JSON line per company: family, secondary
  families, sentence, quote, segment split); `.tmp/regrade/digest.txt` is the evidence digest that was
  read. Scratch `probe*.py` / `diag.py` were moved to `.tmp/regrade/scratch/`.
- Raw BSE responses: `.tmp/bse_header/<scripcode>.json`.

Acceptance: `python -c "import csv;r=list(csv.DictReader(open('sector_label_pilot.csv',encoding='utf-8')));assert len(r)==200 and len({x['isin'] for x in r})==200;assert not any(x['segment_split'].startswith('text signals') for x in r);print('ok')"`
prints `ok`; 0 rows without a `main_business` sentence, quote or reference; 0 quotes longer than 25
words; 7 rows carry a `wrong` grade, all listed in §6 with their quotes.
