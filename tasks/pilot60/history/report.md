# Pilot-60 history chunk store (2019-01-01 .. 2024-03-31 filing window)

- store: `.tmp\pilot60\chunks_v3_history.db` (1.04 GB)
- documents: 18,031; chunks: 212,276; tags: 527,851
- seconds/file (workers): 0.15; peak RAM: 548 MB; no text layer: 4.41%
- shards: 4

## Manifest accounting (every row has exactly one outcome)

| bucket | chunked | needs_ocr | duplicate | failed | total |
|---|---|---|---|---|---|
| all manifest rows | 17,235 | 796 | 1,911 | 11,567 | 31,509 |
| held (status ok) | 17,235 | 796 | 1,911 | 0 | 19,942 |

Non-held manifest rows (routine skips, text-only announcements, HTTP failures) are recorded as `failed` with their manifest status as the reason, so the four counts still sum to the manifest total.

## Failed by reason

| reason | rows |
|---|---|
| skipped | 10,313 |
| no_file | 1,253 |
| error | 1 |

## FTS timings (10 terms)

| term | hits | ms |
|---|---|---|
| order book | 1,168 | 1.6 |
| capacity expansion | 732 | 0.9 |
| margin | 7,602 | 0.5 |
| guidance | 4,201 | 0.4 |
| promoter | 7,545 | 0.6 |
| dividend | 15,648 | 0.9 |
| capex | 3,101 | 0.2 |
| debt | 14,342 | 0.8 |
| revenue | 25,511 | 1.4 |
| risk | 17,436 | 0.9 |

## 30-chunk hand check

- checked 30; all three checks passed 26; text failures 0; page-number failures 4; known_at failures 0; read errors 0
- page_from=0 chunks in the whole store: 6,585 of 212,276 (chunker does not assign a page for some announcement/concall texts)
- details and the failures found: `audit_30.md`

## Files

- `coverage_by_company_type_fy.csv` — company x doc type x fiscal year
- `coverage_history.md` — same, aggregated
- `known_at_check.md` — first 20 rows beside the manifest
- `fts_queries.md`, `audit_30.md`, `report.json`

