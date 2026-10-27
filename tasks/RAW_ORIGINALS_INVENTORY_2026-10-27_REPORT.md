# Raw originals inventory — 2026-10-27

Read-only census of every document type in the v3 re-chunk list: what fraction of the documents we
need has a readable original on this laptop, on `D:`, or on Google Drive, and what must be re-fetched.

- Data root: `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data` (2026-10-27, live SQLite)
- Code: worktree `C:\Users\warri\Downloads\IDM-worktrees\20261027T002828Z-095da489`, census scripts in `.tmp/`
- Network used: `rclone lsf -R --files-only gdrive_ro:InfoDiffusion_archive/<folder>` only. rclone worked
  (it printed a harmless "failed to save config" error because the sandbox denies `%APPDATA%` writes).
- Nothing written outside this worktree. No DB writes, no downloads, no commit.

Scope rules applied (Shivam, 2026-10-27): company docs counted by BSE dissemination date
(`corporate_documents.bse_dissem_ts` / `bse_announcements.ann.DissemDT` / `ar_docs.filed_at`), window
`known_at >= 2024-04-01`; macro/government docs counted at all dates; quarterly-results PDFs reported
read-only from `results_notes.db`; decks measured per filing; BSE rate taken as 40 PDFs/min with the
76/min time alongside.

---

## 1. The table

`needed` = registry rows in the FY25+ window (`known_at >= 2024-04-01`) for company documents, all dates
for macro. `held` = a file exists somewhere (each document counted once even if it is on D *and* Drive).
Macro rows carry no text-only column because the original is the PDF itself.

| # | Document type | Registry | needed | on D: | on Drive | held | missing | text-only (casing) | non-documents (200-row sample) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Annual reports | `ar_facts.ar_docs` | **13,978** | 4,294 | 11,133 | **11,133 (79.6%)** | 2,845 | 324 have chunks; 41.5% of sampled docs are lowercased | 0% |
| 2 | Investor decks (filing level) | `bse_announcements.ann` IP filings | **13,028** | 11,610 | 11,608 | **11,611 (89.1%)** | 1,417 | deck text is not lowercased (0.5%) | 0% |
| 3 | Quarterly results PDFs | `results_notes.db:docs` | **17,007** | 6,385 | 14,465 | **16,680 (98.1%)** | 327 | job in flight; skipped per scope | n/a |
| 4 | Material announcements | `corporate_documents` ANNOUNCEMENT | **15,250** | 0 | 2 | **2 (0.01%)** | 15,248 | no text held (41 docs / 368 FTS chunks total) | 44% |
| 5 | PIB releases | `pib_releases` + `raw_documents` | **75,361** | 0 | 0 | 0 file originals (HTML text held) | 11,343 have no body | chunk copy 98.0% lowercased; stored body is not | 0% |
| 6 | Union budgets | `raw_documents` Union_Budget | **35** | 0 | 35 | **35 (100%)** | 0 | 94.3% lowercased | 0% |
| 6b | State budgets | `raw_documents` State_Budget_* | **211** (29 states + a duplicate `State_Budget_UP` key) | 0 | 211 | **211 (100%)** | 0 | 95.8% lowercased | 0% |
| 7 | RBI documents | `raw_documents` RBI_* | **215** | 0 | 107 | **107 (49.8%)** | 108 | 99.5% lowercased | 0% |
| 8 | Economic Survey | `raw_documents` Economic_Survey | **19** | 0 | 19 | **19 (100%)** | 0 | 89.5% lowercased | 0% |
| 9 | Offer documents | `raw_documents` OFFER_DOCUMENT | **909** | 0 | 388 | **388 (42.7%)** | 521 | 48.0% lowercased | 11.5% (addenda/corrigenda) |

Notes on the numbers:

- **Annual reports.** The 13,978 is the literal window (ARs filed on/after 2024-04-01, i.e. FY24 ARs filed
  Aug-2024 plus FY25 and FY26). The strict fiscal-year reading of "FY25+" (FY2025 + FY2026 ARs) is
  **9,642 needed, 7,848 held (81.4%), 1,794 missing**, same held rate. 2019+ (all of `ar_docs`) is
  33,705 needed / 25,324 held (75.1%) / 8,381 missing. Only 4,294 are on the laptop's `D:`; the other
  6,839 are Drive-only.
- **Decks.** 13,028 BSE `Investor Presentation` filings (1,697 companies) in the window; 12,959 are in
  `deck_figures.deck_sources` (69 never harvested, 3 in `error`), 11,611 have a file. All-dates is
  25,687 filings / 1,839 companies / 21,420 held (83.4%) / 4,267 short, of which 2,078 were never
  harvested into `deck_sources` at all.
- **Announcements.** `corporate_documents` has 16,085 ANNOUNCEMENT rows, 15,260 carry a `bse_dissem_ts`
  (2019+), 15,250 in the window. All 15,250 window rows carry a `source_url`; 14 rows carry a
  `local_file_path` and only 2 resolve to an actual file. There is no announcement text corpus: only
  `raw_documents` ANNOUNCEMENT (41 docs) is chunked, giving 368 `intelligence_fts` rows.
- **PIB.** 75,361 releases held in `pib_releases` (2021-01-01..2026-10-24), 64,018 with a body; 11,690 are
  indexed as `raw_documents` with a sha256; 8,816 regional-language releases. PIB is HTML, not PDF — there
  is no file original anywhere, by design; the body text we hold is **not** lowercased.
- **Offer documents.** 909 `raw_documents` FROM 2021-01-20; `corporate_documents` also has 904
  OFFER_DOCUMENT and 409 ANNUAL_REPORT_DEBT_ISSUER rows (debt-issuer ARs) that are not in the 909.

### 2019+ counts (per scope item 1)

| Type | 2019+ needed | held | rate |
|---|---|---|---|
| Annual reports | 33,705 | 25,324 | 75.1% |
| Investor decks (BSE IP filings) | 25,687 | 21,420 | 83.4% |
| Results XBRL filings (`results_xbrl.filings`) | 106,613 | n/a (XBRL only) | — |
| Material announcements | 15,260 | 2 | 0.01% |
| Offer documents | 909 (all 2021+) | 388 | 42.7% |
| Macro (PIB/budgets/RBI/ES) | all dates (~76k rows) | see above | — |

---

## 2. Decks at the filing level — does 97% / 1,413 hold?

Measured directly: every BSE announcement with `SUBCATNAME='Investor Presentation'`, joined by `NEWSID`
to `deck_figures.deck_sources.source_id`, then each row tested for a file at its `local_path`
(Drive `decks/<rel>`) or its sha256 (`D:\RealityEngine\raw\decks_full\<xx>\<sha>.pdf`).

| Window | Filings | Companies | In deck store | Original held | Filings short | Companies with ≥1 original |
|---|---|---|---|---|---|---|
| FY25+ (`DissemDT >= 2024-04-01`) | 13,028 | 1,697 | 12,959 | 11,611 (89.1%) | **1,417** | **1,647 = 97.1%** |
| FY26+ (`>= 2025-04-01`) | 8,425 | 1,616 | 8,356 | 7,262 (86.2%) | 1,163 | 1,554 = 96.2% |
| All dates (BSE feed starts 2019-12-31) | 25,687 | 1,839 | 23,609 | 21,420 (83.4%) | 4,267 | 1,765 = 96.0% |

**Verdict: the 97% of companies is confirmed (97.1%), and the "~1,413 filings short" is confirmed to
within 4 filings (today 1,417).** The shortfall is not evenly spread: 979 of the 1,417 are 2026 filings
(the deck harvester is behind on the current year), 254 are 2025, 184 are 2024. Composition of the 1,417:
1,345 have a `deck_sources` row but the file is absent, 69 were never put in the store, 3 are in `error`.

NSE deck side: `deck_sources` has 1,713 NSE rows, 1,606 with an original (93.8%) — not part of the
1,417 (that number is BSE-filing based).

---

## 3. Quarterly results PDFs (scope item 3 — read-only, job still running)

`reality_engine/data/results_notes.db` (do not touch; another job is writing it):

| `filed_quarter_end` | docs | original held (by sha) | on D: | on Drive | missing |
|---|---|---|---|---|---|
| 2025-09-30 | 4,330 | 4,017 | 2,216 | 1,802 | 313 |
| 2025-12-31 | 3,908 | 3,905 | 1 | 3,905 | 3 |
| 2026-03-31 | 4,602 | 4,591 | 2 | 4,591 | 11 |
| 2026-06-30 | 4,005 | 4,005 | 4,005 | 4,005 | 0 |
| 2026-09-30 | 162 | 162 | 161 | 162 | 0 |
| **total** | **17,007** | **16,680 (98.1%)** | 6,385 | 14,465 | **327** |

The 2025-09-30 quarter is still short 313; everything else is essentially complete.
`results_xbrl.db` separately holds 106,613 filings (41,886 with `period_end >= 2024-04-01`, 38,128 with a
`dissem_ts`) — XBRL only, no PDFs; not part of the PDF re-fetch.

---

## 4. NSE-only companies (scope item 6)

`master_companies` rows with an NSE symbol and no BSE code: **874, of which 322 are `is_active=1`** (the
brief's ~322 is confirmed). 869 of the 874 also have no BSE code in `security_master` — i.e. they really
are NSE-only, not stale master rows.

What we hold for those 322/874 ISINs, and from which source:

| Store | Rows | Source |
|---|---|---|
| `deck_figures.deck_sources` | 557 | `source='nse'` only |
| `results_xbrl.filings` | 3,063 | NSE XBRL (no PDF original) |
| `corporate_documents` | 13 ANNOUNCEMENT, 11 ANNUAL_REPORT, 2 CONCALL, 3 OFFER_DOCUMENT, 9 OTHER_FILING | 22 `bse_official` / 13 `nse_official` / 3 null |
| `raw_documents` | 21 ANNUAL_REPORT, 58 CONCALL, 4 INVESTOR_PRESENTATION, 6 OFFER_DOCUMENT | NSE/BSE URLs |
| `ar_facts.ar_docs` | 9 | BSE-style AR paths (not on NSE-only companies' own sites) |

Practical reading: for NSE-only companies the only systematic document coverage is NSE decks (557) and
results XBRL (3,063). ARs (9) and announcements (13) are effectively absent, so any announcement/AR
target for this group has to be re-fetched from NSE, not BSE.

---

## 5. Casing sample (200 documents per type, `document_chunks` text)

Metric: share of alphabetic characters that are uppercase. "Lowercased" = < 5% uppercase letters, i.e.
the text demonstrably went through a `.lower()` pass.

| Type | docs sampled | median upper share | % docs < 5% | % docs < 10% | verdict |
|---|---|---|---|---|---|
| PIB (chunked copy) | 200 | 0.008 | **98.0%** | 100% | lowercased — matches "99%" |
| RBI | 214 | 0.008 | **99.5%** | 99.5% | lowercased |
| Union Budget | 35 | 0.006 | **94.3%** | 100% | lowercased — matches "100%" |
| State budgets | 200 docs / 600 chunks | 0.009 | **95.8%** | 100% | lowercased |
| Economic Survey | 19 | 0.029 | **89.5%** | 89.5% | mostly lowercased |
| Offer documents | 200 | 0.160 | **48.0%** | 48.5% | half lowercased (bimodal) |
| Annual reports | 200 | 0.089 | **41.5%** | 60.5% | mixed; brief said 67% — see drift |
| Investor decks | 200 | 0.163 | 0.5% | 9.5% | **not** lowercased |
| Announcements (41 docs) | 41 | 0.116 | 0.0% | 17.1% | not lowercased (tiny corpus) |
| PIB **stored body** (`pib_releases.body`) | 200 | 0.080 | 7.5% | — | **case intact** — see finding |

Finding worth acting on: `pib_releases.body` still has original case while the chunked copy is
lowercased. PIB does not need a re-fetch to restore case, it needs a re-chunk from `pib_releases.body`
(64,018 releases have a body). Same pattern is likely for other text fetched by the same low-level
ingest path — check before spending download time.

Drift vs the brief: annual reports measure 41.5% lowercased at document level (brief said 67%). My sample
counts a document as lowercased only when < 5% of its letters are uppercase; the brief's 67% may have
used a different threshold or counted the FY26 batch only. Decks/announcements match the brief.

---

## 6. Non-document sample (200 rows per type, title heuristic)

Heuristic patterns: intimation / covering letter / newspaper publication / weblink / compliance
certificate / scrutinizer / postal ballot / demat / loss of share / corrigendum / addendum / photograph.

| Type | Heuristic non-doc | Examples |
|---|---|---|
| Material announcements | **88/200 = 44%** | "Compliances-Certificate under Reg. 74(5)", "Announcement under Regulation 30 (LODR)-Newspaper Publication", "Shareholder Meeting / Postal Ballot-Scrutinizer's Report", "Analyst / Investor Meet - Intimation" |
| Offer documents | 23/200 = 11.5% | "Addendum to DRHP", "Corrigendum to DRHP" |
| Annual reports | 0/200 | — |
| PIB / budgets / RBI / ES / decks | 0/200 each | — |

Applied to the window: roughly **6,710 of the 15,250 announcements are procedural rather than material**,
so the announcement re-fetch is ~8,540 PDFs, not 15,250 (see §8). Top announcement titles in the window
are newspaper publication 2,736, press release 719, investor-meet intimation 643, investor-meet outcome
572, change in management 533, "Reg. 34(1) Annual Report" 531.

---

## 7. Orphans — raw folders and files no registry points at

Registered vs present (canonical path match against `raw_documents`, `corporate_documents`, `ar_docs`,
`results_notes`):

| Location | Files | Registered | Extra / orphan |
|---|---|---|---|
| `D:\RealityEngine\pdfs` (all ANNUAL_REPORT) | 5,364 | 5,364 | **0** |
| `D:\RealityEngine\raw\decks_full` (sha-named) | 23,321 | 23,321 | **0** |
| `gdrive:.../decks` | 23,596 | 23,596 | **0** |
| `gdrive:.../pdfs` | 10,362 | 9,753 | **609** (extra AR copies) |
| `gdrive:.../D_pdfs` | 19,608 | 19,352 | **256** |
| `gdrive:.../macro_pdfs` | 493 | 373 | **120** (108 RBI PDFs, 4 budget, 2 survey, states, manifest) |
| `D:\RealityEngine\raw\results_pdfs` | 6,279 | sha-referenced by results_notes | ~0 |
| `gdrive:.../results_pdfs` | 14,169 | sha-referenced | ~0 |

Folders with **no registry at all** (worth registering or deleting):

- `D:\RealityEngine\raw\user_research` — 3,181 files incl. 124 PDFs (broker/research reports: "CPPLUS
  Q3FY26 Report", "nuvama.pdf", "CCL Product Q4 FY25 Highlighted", "Water Infrastructure").
- `D:\RealityEngine\raw\user_research_drive` — 237 files incl. 38 PDFs (PhillipCapital initiating coverage,
  Tips Music deep-dive, commodity data 2022).
- `D:\RealityEngine\raw\deck_real_pilot` (49) and `deck_real_test300` (289) — test decks with
  `date_uuid` names, not the sha-named production copies.
- `D:\RealityEngine\raw\concall_pdfs_probe` (773) — probe downloads (concalls; other worker's area).
- `D:\RealityEngine\raw\deck_page_text` (48) — derived page text, not originals.
- `gdrive:.../telegram_media` (156 files, 14 MB) — TG media; `TG_BigOrders` chunks come from
  `telegram_posts`, these files are not referenced by any document row.
- `gdrive:.../work_files` (3 files, 663 MB) — no registry match found.
- Non-document infra on Drive: `db_backups` (25, 22.5 GB), `snapshots` (1 DB, 9.1 GB), `lancedb`,
  `vector_index*`, `embed_test`, `bhavcopy`, `raw_market` — expected, listed only for completeness.

---

## 8. Prioritised re-fetch list (Shivam's order)

Measured BSE rate used: **40 PDFs/min** (with the 76/min time in brackets). Volumes are measured where
possible: decks 2.9 MB/file (mean `Fld_Attachsize` of the 1,417 missing), announcements 2.78 MB/file,
ARs 8.69 MB/file (mean of the 5,364 ARs on D), offer docs 9.02 MB/file, RBI 0.45 MB/file.

| Priority | Re-fetch | Count | Volume | Time @40/min | Time @76/min | Source |
|---|---|---|---|---|---|---|
| 1 | Investor decks — BSE IP filings FY25+ | 1,417 | 4.1 GB | 35 min | 19 min | BSE `AnnPdfOpen.aspx` via NEWSID (69 need the announcement row first) |
| — | Concalls (other worker; not mine) | 13,330 of 15,619 | — | — | — | — |
| 2 | Material announcements FY25+ | 15,250 (≈8,540 material) | 42.4 GB (≈23.7 GB) | 6 h 21 m (3 h 34 m) | 3 h 21 m (1 h 52 m) | `corporate_documents.source_url` |
| 3 | Annual reports — FY25+ window | 2,845 (1,794 if strict FY2025/26) | 24.7 GB (15.6 GB) | 71 min (45 min) | 37 min (24 min) | BSE AR endpoint; 2,827 of 2,845 have a `(scripcode, year)` key in `bse_annual_reports` |
| 3b | Annual reports — 2019+ backlog (optional) | 8,381 | 72.9 GB | 210 min | 110 min | same |
| 4 | PIB | 11,343 releases with no body (+ 0 budget files missing) | HTML | HTML re-crawl, not comparable to the PDF rate | — | pib.gov.in by PRID; budgets already 35/35 + 211/211 |
| 5 | RBI | 108 | 49 MB | 3 min | 1.5 min | `raw_documents.source_url` |
| — | Offer documents (not in the priority list, flagged) | 521 | 4.7 GB | 13 min | 7 min | `source_url` |
| — | Results notes | 327 | 1.6 GB | 8 min | 4 min | already being fetched by the running job |

Totals for the ordered PDF work (decks + announcements + ARs + RBI): **18,569 PDFs ≈ 62 GB, 464 min
(7 h 44 m) at 40/min, 244 min (4 h 04 m) at 76/min.** If announcements are filtered to the ~56% material
subset first: 11,859 PDFs ≈ 43 GB, 297 min (4 h 57 m) at 40/min, 156 min (2 h 36 m) at 76/min.

The 1,794 strict-FY25+ ARs are a better first AR tranche than the 2,845 window rows: it is the current
corpus and halves the volume.

---

## 9. Queries and listings run (traceability)

Files/scripts: `.tmp/index_files.py` (disk walk), `.tmp/census.py`, `.tmp/final_pass.py`,
`.tmp/roundup.py`, `.tmp/orphans3.py`, `.tmp/samples.py`, `.tmp/q*.py`; outputs `.tmp/*_out.json`,
`.tmp/local_files.tsv`, `.tmp/drive_*.txt`.

Key SQL (all via `reality_engine.db.readonly.connect_ro`, read-only):

```sql
-- registries
select doc_type, count(*), count(distinct sha256_hash), sum(bse_dissem_ts is not null and date(bse_dissem_ts)>='2024-04-01')
from corporate_documents group by 1;
select source_type, count(*), sum(local_file_path is not null), sum(sha256_hash is not null), sum(source_url is not null)
from raw_documents group by 1;
select doc_id, isin, symbol, fiscal_year, filed_at, sha256, path from ar_docs;               -- ar_facts.db
select source_id, symbol, known_at, local_path, sha256, status from deck_sources;          -- deck_figures.db
select count(*) from ann where SUBCATNAME='Investor Presentation' and DissemDT>='2024-04-01'; -- bse_announcements.db
select count(*), min(release_date), max(release_date) from pib_releases;
select filed_quarter_end, count(*), sum(local_path is not null), sum(drive_path is not null) from docs group by 1; -- results_notes.db
select count(*), sum(local_path is not null) from raw_documents where source_type='CONCALL_TRANSCRIPT';
-- NSE-only
select isin, nse_symbol, bse_code, is_active from master_companies
where nse_symbol is not null and nse_symbol<>'' and (bse_code is null or bse_code='');
-- casing / non-document samples: 200 random docs per source_type from raw_documents, up to 4 chunks each;
--   200 random titles per type; uppercase-letter share and keyword regex as documented in §5-§6.
```

Listings:

```powershell
rclone lsf -R --files-only gdrive_ro:InfoDiffusion_archive/pdfs          # 10,362
rclone lsf -R --files-only gdrive_ro:InfoDiffusion_archive/decks         # 23,596
rclone lsf -R --files-only gdrive_ro:InfoDiffusion_archive/macro_pdfs    # 493
rclone lsf -R --files-only gdrive_ro:InfoDiffusion_archive/results_pdfs  # 14,169
rclone lsf -R --files-only gdrive_ro:InfoDiffusion_archive/D_pdfs        # 19,608
rclone size --json gdrive_ro:InfoDiffusion_archive/<folder>              # all other Drive folders
# local: os.walk over D:\RealityEngine\pdfs (5,364), D:\RealityEngine\raw (38,574), data root (4,423)
```

---

## 10. Drift from the brief and open problems

1. **`DSH_WORKER_PROGRESS_NOTES` was not set** in this worker environment, so the progress log is at
   `PROGRESS_NOTES.md` in this worktree root instead of a job directory.
2. The brief lists `D:\RealityEngine\pdfs` as 5,364 AR PDFs — confirmed (5,364). The 2026-10-25 migration
   JSON only records a 1,538-file batch; the rest arrived after it.
3. `data\pdfs\` and `data\macro_pdfs\` on the laptop are now empty; every registry path still points at
   them. Path resolution has to strip `reality_engine\data\` and re-root to `D:\RealityEngine\pdfs` /
   `gdrive:.../macro_pdfs`. That is why the macro documents are "held" but not on local disk.
4. **PIB casing**: the brief says PIB is 99% lowercased; that is true of the chunked copy but not of
   `pib_releases.body`, which keeps case. Re-chunk before re-fetching PIB.
5. **AR casing** measures 41.5% lowercased at document level, not 67%.
6. Announcement text does not exist in the corpus (368 chunks total). Any announcement "text" work needs
   the PDFs first; the 44% non-document rate means the material subset should be selected before fetch.
7. The 1,417 deck shortfall is concentrated in 2026 (979). Re-running the deck harvester over 2026 before
   any manual fetch may close most of it.
8. Nothing in this census verified PDF *readability* (text layer / OCR need). The 70 known garbled-font
   FY26 ARs and any scanned offer documents still need a text-layer gate at re-chunk time.
