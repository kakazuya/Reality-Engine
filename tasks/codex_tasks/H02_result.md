H02 and the H01×H02 combination are complete. **No promotion. Alpha does not increase** when H01 is combined with H02.

## Stage 1 — H02 in isolation

| Definition | Hold | Events | Mean net excess | Median | HAC p | BH q | Date placebo p | Label placebo p | Book kill | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| M1 broad institution | 20 | 1,329 | −0.32% | −0.87% | .485 | .898 | .874 | 1.00 | 25-Mar-2021 | fail |
| M1 broad institution | 60 | 1,281 | −0.01% | −1.61% | .605 | 1.00 | .396 | 1.00 | 18-Mar-2021 | fail |
| M2 repeat clients | 20 | 241 | −4.91% | −7.86% | .00033 | .0506 | .990 | .012 | 22-Jan-2021 | fail |
| M2 repeat clients | 60 | 240 | −6.68% | −12.58% | .070 | .198 | .998 | .138 | 22-Jan-2021 | fail |

M1 has no positive edge. M2 is significantly **negative**; its small p is underperformance, not a long signal. All four long books hit the 8% kill. The next-open gap is positive on average (M1 +2.51%, median +1.56%), so buyers pay above the deal print.

## Stage 2 — H01 × H02

| Test | Events | Mean / contrast | p | BH q | Placebo p | Status |
|---|---:|---:|---:|---:|---:|---|
| C1 M1 confirm, 180d | 78 | +7.91% | .025 | .170 | 1.00 | fail |
| C2 M2 confirm, 180d | 8 | +1.16% | .944 | 1.00 | 1.00 | fail |
| C3 M1 confirmed minus unconfirmed, 180d | 4,285 | **−0.87%** | .806 | 1.00 | 1.00 | fail |
| C4 union book | 5,954 | killed 28-Jan-2021; max DD 8.51% vs H01 8.45% | — | 1.00 | — | fail |
| C5 top minus bottom score, 180d | 52 | +7.43% | .475 | .854 | .926 | fail |
| C6 M1 confirm, 60d | 78 | +2.16% | .371 | .688 | 1.00 | fail |

The decisive **C3 contrast is negative** (−0.87 pp; confirmed 7.91% vs unconfirmed 8.78%). Only 78 H01 events had an M1 deal in the declared [−20,+5] window; C2 had 8. C5's top-bottom spread is not significant and its placebo p is .926. C4's declared union book is dominated by the early 2021 M1 leg and kills before H01 events begin; an exploratory common-period union book is also worse than the H01 leg alone.

**Alpha increases: `False`.**

## Proof and verification

- 88 harness tests pass: 18 new H02 tests + 70 existing H01 tests.
- Independent verification: **H02 9/9 checks**, **H01×H02 11/11 checks**. Recomputed sampled deal nets, entry/exit prices, tax, B5, event means, BH q, and FIFO book fills.
- Ledger: **234 rows** — 224 prior H01 rows retained, 4 H02, 6 H01×H02; append-only.
- Run IDs: Stage 1 `7c7e2d58-0d88-4f42-a8a9-05d21e2e70a3`; Stage 2 `b6afc336-8e2c-4ca5-87e1-91a189482b46`.

## Runtime and snapshot

- Stage 1: **72.6 s** (499 date + 499 label draws).
- Stage 2: **104.7 s** (499 draws).
- Total compute ~3 minutes, plus verification.
- Snapshot `truth_2026-10-19.duckdb`: **unchanged** — 9,130,225,664 bytes, mtime 2026-10-19 21:03:01, SHA256 `0B8A4AFF9A320D39B5F7890D67A94F6F7C0B3CFCFD3D512BD68586C01586A810`. Read-only throughout; no 2026 outcomes loaded.

## Key deviations / limits

1. Deal feeds are end-of-day; entry is t+1 open. Block/bulk prints are negotiated prices, not executable market prices; the next-open gap is reported.
2. NSE maps only via date-valid `symbol_isin_history`; BSE via `security_master.bse_code` (multi-issuer codes refused). 2,641 unmatched rows (₹153,668 crore, 2019–2025) are reported by year.
3. Dedupe removed 29 cross-exchange and 2,267 BULK/BLOCK duplicate pairs one-for-one; same-exchange same-type repeats are retained because they may be separate trades.
4. Promoter/insider exclusion is company-specific using PIT insider names + a `PROMOTER` token; 4,161 rows (₹807,794 crore, 2019–2025) removed. 8,486 NSE insider rows and 759 BSE insider rows had no usable company mapping and are a coverage gap. Family trusts not disclosed as insiders can remain.
5. M2 is the fixed 2021 repeat-client list. It is dominated by proprietary/HFT firms; only the four declared broker/prop tokens were excluded, so this is a defined but weak “marquee” proxy.
6. B5 uses the previous-session TRI close proxy; BSE total-return series are derived; tax is the snapshot base capital-gains model. Full data-completeness gate remains unmet.
7. C3 mixes the later confirmed entry with the original unconfirmed entry — that is the declared test. C4's full union starts with the first event of either leg; the common-period version is exploratory only. No weight/window/horizon search was done.

## Artifacts

`tasks/backtests/H02_report.md`, `H02_results.json`, `H02_events.csv.gz`, `H02_book_fills.csv.gz`, `H02_verification.json`, `H02_preregistration.md`; `H01xH02_report.md`, `H01xH02_results.json`, `H01xH02_book_fills.csv.gz`, `H01xH02_verification.json`, `H01xH02_preregistration.md`; progress in `H02_progress.md`. No commits, pushes, uploads, or paid worker calls.