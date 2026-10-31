# Pilot-60 history chunk store (2019-01-01 .. 2024-03-31 filing window)

- store: `.tmp\pilot60\chunks_v3_history_pilot.db` (0.06 GB)
- documents: 181; chunks: 13,531; tags: 34,627
- seconds/file (workers): None; peak RAM: 0 MB; no text layer: 0.00%
- shards: None

## Manifest accounting (every row has exactly one outcome)

| bucket | chunked | needs_ocr | duplicate | failed | total |
|---|---|---|---|---|---|
| all manifest rows | 180 | 1 | 19 | 0 | 200 |
| held (status ok) | 180 | 1 | 19 | 0 | 200 |

Non-held manifest rows (routine skips, text-only announcements, HTTP failures) are recorded as `failed` with their manifest status as the reason, so the four counts still sum to the manifest total.

## Failed by reason

| reason | rows |
|---|---|

## FTS timings (10 terms)

| term | hits | ms |
|---|---|---|
| order book | 48 | 2.0 |
| capacity expansion | 38 | 0.3 |
| margin | 433 | 0.1 |
| guidance | 337 | 0.1 |
| promoter | 248 | 0.2 |
| dividend | 1,007 | 0.2 |
| capex | 148 | 0.1 |
| debt | 886 | 0.2 |
| revenue | 1,350 | 0.2 |
| risk | 1,451 | 0.2 |

## 30-chunk hand check

- checked 30; all three checks passed 30; page failures 0; known_at failures 0; read errors 0
- details: `audit_30.md`

## Files

- `coverage_by_company_type_fy.csv` — company x doc type x fiscal year
- `coverage_history.md` — same, aggregated
- `known_at_check.md` — first 20 rows beside the manifest
- `fts_queries.md`, `audit_30.md`, `report.json`

