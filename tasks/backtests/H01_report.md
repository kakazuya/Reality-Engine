# H01 PEAD — corrected calendar and timing comparison, provisional

No variant is promoted. Coverage is incomplete. The benchmark entry uses a close proxy.

Snapshot: `truth_2026-10-19.duckdb`, read-only. Evidence: 2021–2025. Warm-up: 2019–2020.
Run: `4d3bf641-0f00-4502-9321-8a4c10326ada`. 16 variants were appended to the shared ledger.

BH family: 32 tests, including 16 prior ledger rows. Defective earlier runs are annotated superseded_by_bugfix and retained.

## Coverage report

| Timing | Year | U1 ISINs | Results + BSE + U1 | Prior-history covered | Values by entry | Results / U1 |
|---|---|---:|---:|---:|---:|---:|
| bse_next_open | 2021 | 1833 | 1200 | 0 | 0 | 65.47% |
| bse_next_open | 2022 | 2004 | 1218 | 659 | 492 | 60.78% |
| bse_next_open | 2023 | 2108 | 1303 | 674 | 588 | 61.81% |
| bse_next_open | 2024 | 2669 | 1528 | 817 | 737 | 57.25% |
| bse_next_open | 2025 | 2573 | 1489 | 988 | 954 | 57.87% |
| both_known_next_open | 2021 | 1833 | 1210 | 0 | 0 | 66.01% |
| both_known_next_open | 2022 | 2004 | 1220 | 660 | 660 | 60.88% |
| both_known_next_open | 2023 | 2108 | 1314 | 675 | 675 | 62.33% |
| both_known_next_open | 2024 | 2669 | 1531 | 816 | 816 | 57.36% |
| both_known_next_open | 2025 | 2573 | 1498 | 984 | 983 | 58.22% |

U1 counts each actual ISIN eligible on any session in the year. Delisted names remain.
Coverage uses filing-trigger year. The final column is not full AR/concall/deck coverage.
Twelve prior quarterly values are needed for eight prior YoY changes. No pre-2019 warm-up is used.

## All 16 variants

bse_next_open: next regular session after BSE, only if XBRL values are known before that open.
both_known_next_open: next regular session after the later of BSE and XBRL. This is a timing sensitivity, not a new signal.

Returns are after 30 bp round trip and base capital-gains tax. Excess subtracts after-tax/cost B5.
Negative surprise is an avoid cohort. Its return is not reversed into a short profit.

| Timing | Measure | Sign | Days | Events | Mean excess | Median excess | t | p | BH q | Placebo p | Directional p | Max-T p | 2021/22/23/24/25 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| bse_next_open | PAT | positive | 20 | 4006 | -0.93% | -1.68% | -1.41 | 0.166 | 0.381 | 0.002 | 1 | 1 | NA/+/+/-/- |
| bse_next_open | PAT | negative | 20 | 2505 | -0.86% | -1.30% | -1.14 | 0.263 | 0.4 | 1 | 1 | 1 | NA/+/+/-/- |
| bse_next_open | revenue | positive | 20 | 4799 | -0.88% | -1.37% | -1.37 | 0.18 | 0.381 | 0.002 | 1 | 1 | NA/+/+/-/- |
| bse_next_open | revenue | negative | 20 | 1727 | -0.99% | -1.84% | -1.15 | 0.259 | 0.4 | 1 | 1 | 1 | NA/+/+/-/- |
| bse_next_open | PAT | positive | 60 | 3546 | 0.97% | -1.19% | 1.51 | 0.139 | 0.381 | 1 | 1 | 1 | NA/+/+/+/- |
| bse_next_open | PAT | negative | 60 | 2217 | -0.20% | -1.75% | -0.264 | 0.793 | 0.847 | 1 | 1 | 1 | NA/+/+/+/- |
| bse_next_open | revenue | positive | 60 | 4242 | 0.91% | -0.92% | 1.39 | 0.174 | 0.381 | 1 | 1 | 1 | NA/+/+/+/- |
| bse_next_open | revenue | negative | 60 | 1528 | -0.69% | -2.76% | -0.866 | 0.393 | 0.503 | 0.988 | 0.988 | 1 | NA/-/+/-/- |
| both_known_next_open | PAT | positive | 20 | 5527 | -0.52% | -1.33% | -0.928 | 0.359 | 0.479 | 0.188 | 1 | 1 | NA/+/+/-/- |
| both_known_next_open | PAT | negative | 20 | 3491 | -0.79% | -1.34% | -1.23 | 0.224 | 0.4 | 1 | 1 | 1 | NA/+/-/-/- |
| both_known_next_open | revenue | positive | 20 | 6602 | -0.56% | -1.17% | -1.02 | 0.313 | 0.435 | 0.002 | 1 | 1 | NA/+/+/-/- |
| both_known_next_open | revenue | negative | 20 | 2429 | -0.78% | -1.74% | -1.1 | 0.279 | 0.406 | 1 | 1 | 1 | NA/+/-/-/- |
| both_known_next_open | PAT | positive | 60 | 5041 | 1.59% | -0.69% | 2.65 | 0.0118 | 0.379 | 1 | 1 | 1 | NA/+/+/+/- |
| both_known_next_open | PAT | negative | 60 | 3188 | -0.00% | -2.01% | -0.00255 | 0.998 | 0.998 | 1 | 1 | 1 | NA/+/+/+/- |
| both_known_next_open | revenue | positive | 60 | 6014 | 1.34% | -0.64% | 2.24 | 0.0309 | 0.381 | 1 | 1 | 1 | NA/+/+/+/- |
| both_known_next_open | revenue | negative | 60 | 2220 | -0.09% | -2.76% | -0.128 | 0.899 | 0.928 | 1 | 1 | 1 | NA/+/+/+/- |

## Placebo and regimes

499 within-month filing-date permutations. Seed 20261020.
The same evaluator recomputes availability, liquidity, entry and returns in each draw.
The JSON retains every placebo mean, event count and full-grid maximum absolute t.

| Variant | Placebo mean | Placebo 2.5% / median / 97.5% | Up-market mean (n) | Down-market mean (n) |
|---|---:|---|---|---|
| bse_next_open PAT positive 20 | 0.25% | 0.08% / 0.25% / 0.43% | -0.80% (2982) | -1.31% (1024) |
| bse_next_open PAT negative 20 | -1.55% | -1.75% / -1.55% / -1.36% | -0.77% (1812) | -1.10% (693) |
| bse_next_open revenue positive 20 | -0.03% | -0.20% / -0.03% / 0.12% | -0.77% (3519) | -1.16% (1280) |
| bse_next_open revenue negative 20 | -1.59% | -1.85% / -1.59% / -1.34% | -0.82% (1289) | -1.47% (438) |
| bse_next_open PAT positive 60 | 2.33% | 2.08% / 2.32% / 2.56% | 1.37% (2526) | -0.02% (1020) |
| bse_next_open PAT negative 60 | -0.94% | -1.24% / -0.94% / -0.66% | 0.09% (1526) | -0.84% (691) |
| bse_next_open revenue positive 60 | 1.84% | 1.61% / 1.84% / 2.08% | 1.37% (2970) | -0.17% (1272) |
| bse_next_open revenue negative 60 | -1.11% | -1.51% / -1.11% / -0.72% | -0.53% (1091) | -1.10% (437) |
| both_known_next_open PAT positive 20 | 0.45% | 0.32% / 0.45% / 0.59% | -0.37% (4067) | -0.92% (1460) |
| both_known_next_open PAT negative 20 | -1.46% | -1.61% / -1.47% / -1.31% | -0.65% (2519) | -1.13% (972) |
| both_known_next_open revenue positive 20 | 0.12% | -0.00% / 0.13% / 0.24% | -0.41% (4795) | -0.97% (1807) |
| both_known_next_open revenue negative 20 | -1.42% | -1.62% / -1.42% / -1.21% | -0.66% (1799) | -1.12% (630) |
| both_known_next_open PAT positive 60 | 2.68% | 2.51% / 2.68% / 2.85% | 1.79% (3585) | 1.10% (1456) |
| both_known_next_open PAT negative 60 | -0.80% | -0.99% / -0.80% / -0.63% | -0.00% (2218) | -0.00% (970) |
| both_known_next_open revenue positive 60 | 2.12% | 1.96% / 2.12% / 2.26% | 1.58% (4215) | 0.78% (1799) |
| both_known_next_open revenue negative 60 | -0.85% | -1.09% / -0.86% / -0.63% | -0.21% (1591) | 0.21% (629) |

Up/down means the selected index rose/fell over 63 sessions ending before entry.
Placebo p compares absolute observed mean excess with absolute shuffled means. It can be small for harmful effects.
Directional p uses the claimed sign: positive excess for positive surprises and negative excess for the avoid cohort.
Max-T p compares the absolute cluster t with the shuffled maximum absolute cluster t across all 16 current variants.
Month-clustered t statistics are descriptive. Historical variants remain in BH; max-T covers this current grid.
Promotion also needs four years with the expected sign, both regimes, and a surviving book.
The full data gate is unmet regardless of those checks.

## Long-only books

Each positive variant gets its own Rs 10 lakh sleeve inside Rs 1 crore. They are alternatives, not added together.
The other Rs 90 lakh stays in cash. Negative cohorts do not trade.

| Variant | Sleeve CAGR | Total-capital CAGR | Max sleeve DD | Max portfolio DD | B5 CAGR | Excess CAGR | Kill |
|---|---:|---:|---:|---:|---:|---:|---|
| bse_next_open_PAT_positive_20 | -1.48% | -0.14% | 8.67% | 0.87% | 12.02% | -13.51% | 2022-05-02 |
| bse_next_open_revenue_positive_20 | -1.65% | -0.16% | 8.41% | 0.84% | 12.02% | -13.68% | 2022-05-02 |
| bse_next_open_PAT_positive_60 | -1.48% | -0.14% | 8.67% | 0.87% | 12.02% | -13.51% | 2022-05-02 |
| bse_next_open_revenue_positive_60 | -1.65% | -0.16% | 8.41% | 0.84% | 12.02% | -13.68% | 2022-05-02 |
| both_known_next_open_PAT_positive_20 | -1.70% | -0.16% | 8.45% | 0.85% | 12.02% | -13.72% | 2022-05-02 |
| both_known_next_open_revenue_positive_20 | -1.96% | -0.19% | 9.44% | 0.94% | 12.02% | -13.99% | 2022-04-29 |
| both_known_next_open_PAT_positive_60 | -1.70% | -0.16% | 8.45% | 0.85% | 12.02% | -13.72% | 2022-05-02 |
| both_known_next_open_revenue_positive_60 | -1.96% | -0.19% | 9.44% | 0.94% | 12.02% | -13.99% | 2022-04-29 |

A killed sleeve stays in cash for the rest of the evidence window. Kill timing uses no future close.
Daily NAV, fees, taxes, skipped admissions and fills are in the JSON.

## B5 monthly choices

The winner uses only TRI observations before each month. Lookback is 12 calendar months.
The first session uses the chosen index’s own prior close. Index levels are never spliced.
All 60 choices, source methods, as-of dates and lookback returns are in `H01_b5_monthly.csv` and JSON.

| Year | Chosen index: months |
|---|---|
| 2021 | BSE 250 SmallCap: 1; BSE IPO: 8; Nifty Smallcap 250: 3 |
| 2022 | BSE Sensex: 3; Nifty Midcap 150: 4; Nifty Smallcap 250: 5 |
| 2023 | BSE 250 SmallCap: 3; BSE Sensex: 3; Nifty Midcap 150: 3; Nifty Smallcap 250: 3 |
| 2024 | BSE IPO: 6; Nifty Smallcap 250: 6 |
| 2025 | BSE IPO: 1; BSE Sensex: 9; Nifty Midcap 150: 2 |

## Surprise quintiles

These use ex-post ranks for description. They are not traded thresholds.

| Timing | Measure | Days | Quintile | n | Mean excess |
|---|---|---:|---:|---:|---:|
| bse_next_open | PAT | 20 | 1 | 1302 | -0.90% |
| bse_next_open | PAT | 20 | 2 | 1303 | -0.88% |
| bse_next_open | PAT | 20 | 3 | 1303 | -1.34% |
| bse_next_open | PAT | 20 | 4 | 1303 | -1.12% |
| bse_next_open | PAT | 20 | 5 | 1303 | -0.29% |
| bse_next_open | revenue | 20 | 1 | 1307 | -1.23% |
| bse_next_open | revenue | 20 | 2 | 1307 | -1.01% |
| bse_next_open | revenue | 20 | 3 | 1308 | -1.38% |
| bse_next_open | revenue | 20 | 4 | 1307 | -0.56% |
| bse_next_open | revenue | 20 | 5 | 1308 | -0.36% |
| bse_next_open | PAT | 60 | 1 | 1153 | -0.83% |
| bse_next_open | PAT | 60 | 2 | 1153 | 0.51% |
| bse_next_open | PAT | 60 | 3 | 1153 | -0.06% |
| bse_next_open | PAT | 60 | 4 | 1153 | 0.94% |
| bse_next_open | PAT | 60 | 5 | 1153 | 2.02% |
| bse_next_open | revenue | 60 | 1 | 1156 | -1.18% |
| bse_next_open | revenue | 60 | 2 | 1156 | 0.11% |
| bse_next_open | revenue | 60 | 3 | 1156 | 0.16% |
| bse_next_open | revenue | 60 | 4 | 1156 | 1.90% |
| bse_next_open | revenue | 60 | 5 | 1157 | 1.53% |
| both_known_next_open | PAT | 20 | 1 | 1804 | -0.93% |
| both_known_next_open | PAT | 20 | 2 | 1804 | -0.68% |
| both_known_next_open | PAT | 20 | 3 | 1804 | -0.68% |
| both_known_next_open | PAT | 20 | 4 | 1804 | -0.77% |
| both_known_next_open | PAT | 20 | 5 | 1805 | -0.05% |
| both_known_next_open | revenue | 20 | 1 | 1810 | -0.84% |
| both_known_next_open | revenue | 20 | 2 | 1810 | -1.03% |
| both_known_next_open | revenue | 20 | 3 | 1810 | -1.07% |
| both_known_next_open | revenue | 20 | 4 | 1810 | -0.21% |
| both_known_next_open | revenue | 20 | 5 | 1811 | 0.03% |
| both_known_next_open | PAT | 60 | 1 | 1646 | -0.44% |
| both_known_next_open | PAT | 60 | 2 | 1646 | 0.43% |
| both_known_next_open | PAT | 60 | 3 | 1646 | 1.21% |
| both_known_next_open | PAT | 60 | 4 | 1646 | 1.46% |
| both_known_next_open | PAT | 60 | 5 | 1647 | 2.20% |
| both_known_next_open | revenue | 60 | 1 | 1650 | -0.33% |
| both_known_next_open | revenue | 60 | 2 | 1651 | 0.20% |
| both_known_next_open | revenue | 60 | 3 | 1651 | 0.88% |
| both_known_next_open | revenue | 60 | 4 | 1651 | 2.16% |
| both_known_next_open | revenue | 60 | 5 | 1651 | 1.92% |

## Timing and data checks

Filing audit: `{"ann_ambiguous_or_unmapped_code": 162, "joined_quarter_candidates": 86611, "non_quarter_duration": 3667, "later_duplicate_or_revision_discarded": 1303, "missing_or_unvalidated_pat": 984, "bank_classification_carried_from_prior_filing": 193, "basis_Consolidated": 34551, "trigger_missing": 11589, "trigger_period_parsed": 13824, "basis_Non-Consolidated": 11398, "trigger_within_100_days_unparsed": 22164, "basis_Standalone": 1628, "normalized_periods": 47577}`.

Event gates: `{"bse_next_open": {"bse_pat_u1_events": 22070, "insufficient_or_late_history": 13019, "current_values_after_next_open": 2512, "known_history_and_current_before_open": 6538, "missing_entry_open": 1, "current_xbrl_after_bse_trigger": 21632}, "both_known_next_open": {"bse_pat_u1_events": 22118, "insufficient_or_late_history": 13062, "current_values_after_next_open": 0, "known_history_and_current_before_open": 9055, "missing_entry_open": 1, "current_xbrl_after_bse_trigger": 21680}}`.

Price panel: `{"price_rows": 6297998, "issuer_count": 5929, "raw_missing_or_ambiguous": 0, "quarantine_table_present": false, "quarantine_keys": 0, "has_open": true, "calendar_method": "Nifty 50 dates, weekdays only; special weekend sessions omitted", "excluded_special_sessions": ["2019-10-27", "2020-02-01", "2020-11-14", "2023-11-12", "2024-01-20", "2024-03-02", "2024-05-18", "2025-02-01"]}`.

| Variant | Delayed exits filled | Unresolved loss bounds | Truth jump flags | Mean stock entry gap |
|---|---:|---:|---:|---:|
| bse_next_open PAT positive 20 | 0 | 0 | 0 | 1.29% |
| bse_next_open PAT negative 20 | 1 | 0 | 0 | -1.52% |
| bse_next_open revenue positive 20 | 1 | 0 | 0 | 0.72% |
| bse_next_open revenue negative 20 | 0 | 0 | 0 | -1.22% |
| bse_next_open PAT positive 60 | 0 | 0 | 1 | 1.30% |
| bse_next_open PAT negative 60 | 0 | 0 | 0 | -1.51% |
| bse_next_open revenue positive 60 | 0 | 0 | 1 | 0.73% |
| bse_next_open revenue negative 60 | 0 | 0 | 0 | -1.20% |
| both_known_next_open PAT positive 20 | 0 | 0 | 0 | 1.07% |
| both_known_next_open PAT negative 20 | 1 | 0 | 0 | -0.98% |
| both_known_next_open revenue positive 20 | 1 | 0 | 0 | 0.66% |
| both_known_next_open revenue negative 20 | 0 | 0 | 0 | -0.74% |
| both_known_next_open PAT positive 60 | 0 | 0 | 1 | 1.07% |
| both_known_next_open PAT negative 60 | 0 | 0 | 0 | -0.93% |
| both_known_next_open revenue positive 60 | 0 | 0 | 1 | 0.65% |
| both_known_next_open revenue negative 60 | 0 | 0 | 0 | -0.68% |

The stock gap is adjusted entry open / previous regular-session close minus one. It is a scale check, not the unobserved index overnight gap or an estimate of its bias.

### BSE-to-XBRL and admission lag

| Timing | Qualified events | XBRL later than BSE | XBRL lag hours p50 / p90 / p99 | Entry delay sessions p50 / p90 / p99 |
|---|---:|---:|---|---|
| bse_next_open | 6538 | 6355 | 2.4 / 12.3 / 25 | 0 / 0 / 0 |
| both_known_next_open | 9055 | 8872 | 4.04 / 23.3 / 167 | 0 / 1 / 4.46 |

JSON also gives lag distributions before history and entry gates, to expose the selection. Lag is floored at zero when XBRL preceded BSE.

### Unresolved exits

None. Every missing scheduled close had a later quote within the evidence window.

TITAGARH Q3 FY25: BSE `2025-02-13 20:32:16.483000` IST; XBRL `2025-02-14 15:12:48` IST. Timing checks: `{"bse_next_open": {"decision_trigger": "2025-02-13T20:32:16.483000", "next_open": "2025-02-14 09:15 IST", "eligible_with_values_by_open": false}, "both_known_next_open": {"decision_trigger": "2025-02-14T15:12:48.000000", "next_open": "2025-02-17 09:15 IST", "eligible_with_values_by_open": false}}`.

## Deviations

1. Original BSE PDF values are not present as dated facts. bse_next_open requires values before the next BSE-triggered open; both_known_next_open waits until the next regular session after max(BSE, XBRL). Historical comparators must precede each policy decision trigger. No XBRL values are backdated to the PDF.
2. Consolidated is preferred per issuer/quarter. First XBRL per basis is frozen; later duplicate/revised files are discarded. A missing consolidated PAT does not authorize standalone substitution. Standalone and Non-Consolidated are the same historical basis family.
3. No index opens exist. B5 uses previous-session TRI close as its entry/switch proxy, including the entry-day gap while stocks enter at open. This unavoidable timing mismatch prevents a clean investable benchmark claim.
4. BSE TRI method is derived, not official. Actual method is logged each month. Both event and book B5 pay the same 30 bp round-trip cost and sell-date capital-gains tax; actual index changes realize gains.
5. Prices are joined across ISIN changes through security_master issuer, after resolving each filing by its trading_isin. Actual historical entry ISIN is logged. Current listing/active status never filters the universe. Ambiguous code/issuer mappings are rejected.
6. U1 uses 20 complete prior exchange sessions. A pre-15:30 filing uses the previous completed close for the raw Rs10 test. Non-trading-day filings use the last session. Threshold is Rs50 lakh median; cap is 10% of lagged 20-session mean value. No zero imputation.
7. Signal and taxable returns use total-return-adjusted stock units. Dividend income is conservatively included in the gains proxy. Full personal dividend tax, cess and income-dependent surcharge are not modeled; cess source coverage is incomplete in tax_rules. These are base capital-gains-tax results.
8. The common calendar omits all weekend special sessions, including real budget/drill sessions. Missing scheduled closes exit at the stock's next actual regular-session close; tax and B5 use that actual date. Only no later quote through 2025 gets a terminal zero-recovery bound. This is an unresolved evidence-boundary case, not proof of delisting. Names are listed. Books retain holdings and retry actual exits; terminal unresolved holdings prevent promotion.
9. Book targets equal weights on admissions, charges rebalancing trades, keeps spare capacity in zero-interest cash, suppresses overlapping same-issuer admissions, and uses fractional adjusted units. EOD kills fill next executable session and may overshoot 8%.
10. No technical confirmation overlay is invented for this card. H06 is separate. Coverage and this missing deployment overlay prevent promotion even if statistical gates pass.
11. P-values use entry-month clustered standard errors. Sixty-session overlaps cross months; full-grid within-month filing-date permutation and max-absolute-t calibration are also reported. These nulls preserve filing season and availability lags, but are not independent event draws.
12. Quarter duration is 80-100 days, with calendar quarter ends. Semiannual SME filings are excluded from H01, while SME remains in U1. Warm-up uses no pre-2019 facts; no 2026 prices or outcomes are loaded.
13. Bank status carries forward from earlier BANKING filings when the taxonomy becomes INTEGRATED. It never uses a future bank label. Earlier runs, including the bank-label correction and defective calendar runs, remain in the ledger/BH family with append-only superseded_by_bugfix notes. Both timing policies are tested together; no horizon or signal threshold was selected from their performance.

## Tests

86 tests passed: 49 harness tests and 37 existing horizon tests.
Synthetic fixtures do not need the snapshot. Adapter tests use only an in-memory fixture database.
The existing horizon suite uses its own temporary synthetic databases. No other source database was opened.

## What could still be fooling us

This is a liquid XBRL-filer subset. Strict late-XBRL rejection selects different issuers; waiting changes the entry price and exposure.
Unparsed announcement fallback can match the wrong results document. Basis preference can omit earlier standalone data.
The snapshot cannot prove the first PDF and later XBRL have identical values.
Results cluster. Horizons overlap. BSE total returns are estimates. Index opens are unavailable.
Split mappings, inferred adjustments and unexplained jumps can still contaminate returns.
A cohort edge can disappear after sizing, idle cash, rebalancing and a drawdown kill.

## Reproduction

`python -m reality_engine.harness.run_h01 --placebo-draws 499`

Git HEAD `c9803142b84cda5b673bb3c4811c383103d0a8fd`. New source files are uncommitted; their SHA256 hashes are in JSON.
Compute runtime: 71.2 seconds. No 2026 results. No commit, push or stash.
