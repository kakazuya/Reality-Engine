# Pilot-60 document history chunk store — build report

Built 2026-10-31 on the HP OmniBook (Windows 11 ARM64), checkout
`C:\RE\jobs\hp-20261031T052058-f95970\repo`.

- Manifest: `C:\RE\data\pilot\pilot60_history_manifest.db` (31,509 rows)
- PDFs: `C:\RE\raw\pilot60_history` (env `REALITY_HISTORY_RAW` / `--root`)
- Store: `.tmp/pilot60/chunks_v3_history.db` — **1,036,664,832 bytes (1.04 GB)**
- Schema: same as `chunks_v3_pilot.db` (`tasks/arch_v3/SCHEMA_V3.sql` §A) plus
  `doc.needs_ocr` and the additive `history_outcome` ledger.

## Manifest accounting

| scope | chunked | needs_ocr | duplicate | failed | total |
|---|---|---|---|---|---|
| all manifest rows | 17,235 | 796 | 1,911 | 11,567 | **31,509** |
| held (`status='ok'`) | 17,235 | 796 | 1,911 | 0 | **19,942** |

`failed` includes the manifest's own non-fetched rows, by design, so the four
outcomes cover every row: 10,313 routine skips, 1,253 text-only announcements
(no attachment), 1 HTTP 404. Held-row failures are zero.

Store contents: 18,031 docs (17,235 chunked + 796 needs_ocr; duplicates are not
written), 212,276 chunks, 527,851 tags, 32 tag-vocab rows. Date range of
`known_at`: 2019-01-01T10:26:07 .. 2024-03-31T23:37:28, every value copied from
the manifest `dissem_ts`. 1,911 duplicate rows = 1,484 content-hash groups
(18,031 distinct sha256).

## Pilot (200 stratified files)

- Sample: 29 strata (5 doc types x 6 filing years), 200 selected.
- Parsed: 181 files; 19 of the selections were content-hash duplicates (not parsed).
- Time: **179.55 s = 0.99 s/file** (median 0.249 s, p95 4.82 s) on a machine
  already ~53% busy with other jobs. An earlier identical run took 68.8 s
  (0.38 s/file), so the file cost is ~0.4-1.0 s depending on contention.
- By type (final run): annual_report 4.30 s, results_notes 0.38 s,
  concall 0.35 s, deck 0.23 s, announcement 0.03 s.
- Peak RAM: **318 MB** (`psutil.peak_wset`).
- No text layer: **1/181 = 0.55%** (grade C + `needs_ocr=1`).
- `known_at`: **0 mismatches / 20** first rows printed beside the manifest
  (`tasks/pilot_t2/known_at_check.md`); the full build refuses to
  start when the pilot recorded a mismatch.

## Full run

- 4 shards (free RAM was 4.13 GB at the check; the builder drops to 2 under 3 GB).
- 666-694 s per shard; aggregate **0.15 s/file**, peak worker RAM **548 MB**.
- Chunked fraction 86.4%, needs_ocr 4.0%, duplicate 9.6% of held rows.
- No text layer: 796/18,031 docs = **4.41%** (higher than the pilot because the
  corpus is dominated by small announcements, while the pilot over-samples ARs).

## Coverage

- `tasks/pilot60/history/coverage_by_company_type_fy.csv` — 2,450 rows, 60
  companies x doc type x fiscal period; counters sum exactly to 31,509 manifest
  rows and 212,276 chunks.
- `tasks/pilot60/history/coverage_history.md` — same, aggregated by doc type and
  fiscal year, then company and doc type.
- Fiscal labels follow `HISTORY_COVERAGE_2026-10-30.md`: annual reports use the
  headline `2018-19` label (else filing year), quarterly results/concalls use the
  filing-month quarter, other buckets use the filing year. FY19..FY24 and
  Q3FY19..Q4FY23 are populated; no FY24 annual reports exist in the window.

## 30-chunk hand check

`tasks/pilot60/history/audit_30.md` (fixed seed 42, random chunk ids; each chunk's
PDF is re-opened, its page text re-extracted, and its `known_at` re-compared to
the manifest):

- text found: **30/30**
- `known_at` matches manifest: **30/30**
- page number correct: **26/30**

Failures found and reported:

| chunk | symbol | type | issue |
|---|---|---|---|
| 154795 | TEJASNET | announcement | `page_from=0` (unknown); text is on PDF page 1 |
| 110605 | ASHIANA | announcement | `page_from=0` (unknown); text is on PDF page 1 |
| 7812 | PIDILITIND | announcement | `page_from=0` (unknown); text is on PDF page 1 |
| 187701 | GRASIM | deck | declared page 30, text found on page 29 (printed slide number vs PDF page) |

Store-wide, **6,585 of 212,276 chunks (3.1%) have `page_from=0`**: 6,503
announcements and 82 concalls. This is chunker behaviour, not a missing PDF: the
audit found the text on page 1 for the sampled cases. A separate 30-deck probe
found 24 exact, 2 off-by-one (declared page = PDF page + 1) and 4 snippets that
cross a page boundary (the audit's window check handles those; the probe did not).

## FTS (10 terms)

From `tasks/pilot60/history/fts_queries.md` (warm cache):

| term | hits | ms |
|---|---|---|
| order book | 1,168 | 1.6 |
| capacity expansion | 732 | 0.9 |
| margin | 7,602 | 0.6 |
| guidance | 4,201 | 0.4 |
| promoter | 7,545 | 0.6 |
| dividend | 15,648 | 0.9 |
| capex | 3,101 | 0.2 |
| debt | 14,342 | 0.8 |
| revenue | 25,511 | 1.4 |
| risk | 17,436 | 0.9 |

## Resume

- Unit test: `process_row()` twice on the same row -> doc/chunk/ledger counts unchanged.
- Real-shard integration: copied `history_shards/shard_0.db`, deleted one ledger
  row, ran the worker in `--resume`; it re-processed exactly that row and the
  counts stayed `(4508 docs, 50787 chunks, 4508 outcomes)` — `PASS`.

## Provenance / drift

- All **19,942/19,942** held manifest `local_path`s resolve under
  `C:\RE\raw\pilot60_history`; zero missing PDFs.
- The tree has 19,978 files: the 36 extras are 35 fetch logs and `manifest.csv`
  (17.5 MB), not documents. No PDF is unaccounted for.
- Duplicate content is skipped by manifest sha256 (no file re-hash needed);
  `size_mismatch=0` on all 18,031 parsed files, so the copied bytes match the
  fetched bytes.
- `chunk_entity` is empty because `REALITY_DATA_ROOT=C:\RE\data` holds only the
  pilot DBs and no `equity_intelligence.db` master table. Chunking and search
  are unaffected; entity tagging will populate when built with the full data root.

## Reproduce

```bash
python tasks/pilot60/build_chunks60.py --history --pilot
python tasks/pilot60/build_chunks60.py --history --full --shards 4
python tasks/pilot60/build_chunks60.py --history --report-only
python -m pytest reality_engine/tests/test_pilot60_history_chunks.py -q
```

`build_chunks60_all.py --history ...` delegates to the same module. The live
`chunks_v3_pilot.db` was never read for writing or merged into.

## Files

- `tasks/pilot60/build_chunks60_history.py` — new history mode (manifest loader,
  ledger, sharding/merge, reports, audit, FTS).
- `tasks/pilot60/build_chunks60.py` — `--history` delegation.
- `tasks/pilot60/build_chunks60_all.py` — `--history` delegation.
- `reality_engine/tests/test_pilot60_history_chunks.py` — 8 tests.
- `tasks/pilot60/history/` — report, coverage CSV/MD, known_at check, FTS,
  audit, worker JSON/logs.
- `tasks/pilot60/history_pilot/` — pilot report and known_at check.

## Cost / calls

- Tool calls before the first task edit: **35** (first builder write was call 36).
- Code-intel calls: 5 (1 symbols, 1 references, 3 diagnostics).
- Total tool calls in this session: 166 at the final check (session event log).
