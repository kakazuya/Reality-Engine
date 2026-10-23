# H01 x H02 — declared combination test (Stage 2), provisional

No combination is promoted. Stage 1 H02 is a separate isolation test.

Run `b6afc336-8e2c-4ca5-87e1-91a189482b46`. Snapshot `truth_2026-10-19.duckdb`, read-only. Evidence 2021–2025. Runtime 104.7s.

Pre-registration: `H01xH02_preregistration.md`, SHA256 `541e00d96e5c0a825a38789d012a802801d795619ddcfa61c902ddea46908d26`.

H01 lead: 4285 positive-PAT 180-session events, mean H01 net excess 8.78%.

## Six declared tests

| Test | Definition | Events | Mean / contrast | t | p | BH q | Placebo p | Status |
|---|---|---:|---:|---:|---:|---:|---:|---|
| C1 | M1 180 | 78 | 7.91% | 2.441 | 0.02463 | 0.1701 | 1 | fail |
| C2 | M2 180 | 8 | 1.16% | 0.07442 | 0.9436 | 1 | 1 | fail |
| C6 | M1 60 | 78 | 2.16% | 0.9156 | 0.3713 | 0.6875 | 1 | fail |
| C3 | M1 180 | 4285 | -0.87% | -0.2489 | 0.8061 | 1 | 1 | fail |
| C4 | union 180/60 | 5954 | 6.40% | — | 1 | 1 | — | fail |
| C5 | M1 180 | 52 | 7.43% | 0.7429 | 0.4746 | 0.8543 | 0.926 | fail |

C1/C2/C6 are confirm cohorts, not standalone signals. C1 and C6 have only 78 confirmed H01 events; C2 has 8. Their positive means are not incremental evidence because the decisive C3 contrast is negative and every combination date-placebo p is far above 0.05. The confirmed sample is small because M1/M2 deal-days rarely fall in the same stock's [-20,+5] earnings window.

## Confirmation entry delay

| Test | n | Mean delay (sessions) | Median | p90 | Share entering after H01 |
|---|---:|---:|---:|---:|---:|
| C1 | 78 | 0.8718 | 0 | 4 | 26.92% |
| C2 | 8 | 1.125 | 0.5 | 2.9 | 50.00% |
| C6 | 78 | 0.8718 | 0 | 4 | 26.92% |

A deal after the H01 entry delays the combined entry to the deal's t+1 open. A deal before it keeps the H01 entry. This is the declared rule.

## C3 — the decisive contrast

| Group | Events | Mean 180d net excess |
|---|---:|---:|
| M1-confirmed | 78 | 7.91% |
| Unconfirmed | 4207 | 8.78% |
| Contrast | | -0.87% |

Cluster p `0.8061`, BH q `1`, directional placebo p `1`. The contrast mixes the later confirmed entry with the original unconfirmed entry; that is the declared test.

## C5 — fixed 0.5/0.5 score

Top tercile 11.35% (26 events), middle 8.46% (26), bottom 3.92% (26). Top minus bottom 7.43%, p `0.4746`.

## C4 — union book versus each leg

| Book | Events | Sleeve CAGR | Max sleeve DD | Portfolio DD | B5 CAGR | Excess CAGR | Kill | Fills |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| H01_180 | 4285 | -1.70% | 8.45% | 0.85% | 12.02% | -13.72% | 2022-05-02 | 169 |
| M1_60 | 1680 | -1.57% | 8.51% | 0.86% | 12.02% | -13.60% | 2021-01-28 | 27 |
| union | 5965 | -1.57% | 8.51% | 0.86% | 12.02% | -13.60% | 2021-01-28 | 27 |

Union drawdown no worse than H01 leg: `False`. Kill no worse: `False`.

The C4 ledger row's 6.40% is the descriptive pooled event excess of the H01 and M1 events; it is not the union book's CAGR and it is not a book p-value. C4's ledger p is conservatively 1.0 because its declared criterion is drawdown and kill, not an event-mean test. The union book itself lost money and killed.

The declared union book starts with the first event of either leg. Because the M1 leg starts in 2021 and the H01 leg in 2022, the early M1 book can kill the union before any H01 event is admitted. The full union is the declared C4 test.

### Exploratory only — common-period books (both legs coexist from the first H01 entry)

| Book | Events | Sleeve CAGR | Max sleeve DD | B5 CAGR | Excess CAGR | Kill | Fills |
|---|---:|---:|---:|---:|---:|---|---:|
| M1_60_common | 1403 | -1.93% | 9.76% | 12.02% | -13.96% | 2022-05-11 | 39 |
| union_common | 5688 | -2.04% | 10.43% | 12.02% | -14.07% | 2022-05-04 | 277 |

Common-period results are descriptive and excluded from the declared C4 proof and BH.

## Verdict

**Alpha increases: `False`.** The only declared test is C3 contrast > 0 with BH q < .05 and placebo p < .05, plus C4 drawdown/kill no worse than the H01 leg alone. No other comparison is a promotion criterion.

## Placebo

499 draws. Deal dates were permuted within stock-year; C1/C2/C3/C5/C6 were rebuilt; max-T is across the current combination grid.

## Deviations and limits

1. C1/C2/C6 confirm only on M1/M2 net-buy events in [-20,+5] sessions around the H01 decision; the latest t+1 open among qualifying deals sets the combined entry. This is a declared rule, not a search.
2. A confirmed H01 event whose combined entry has no 180/60-session room before 2025-12-31 is excluded from that combination; unconfirmed H01 events keep their original entry and 180-session outcome.
3. C3 compares confirmed events from their combined entry with unconfirmed H01 events from their original entry. This mixes an entry-timing difference into the contrast; it is the declared test, not a pure stock-selection contrast.
4. C5 uses raw net deal value (not market-cap scaled) and cross-sectional z-scores of PAT surprise and log net value with fixed 0.5/0.5 weights. Terciles are equal-count by rank; ties split deterministically by order, which is disclosed as a limitation.
5. C4 uses one cash book with equal weights on admissions, 10% of lagged ADTV, 10% strategy allocation and the unchanged 8% kill. Overlapping same-issuer admissions are suppressed. The union book's CAGR/drawdown/kill is compared with each leg alone. Its ledger p is conservatively 1.0 because the declared C4 criterion is drawdown/kill, not an event-mean p; the pooled event mean is reported only as description.
6. No weight search, window search, horizon search, industry/size control or 2026 outcome is used.
7. B5 uses the previous-session TRI close as its entry proxy; BSE total returns are derived. Event and book B5 pay the same 30 bp and sell-date tax conventions.
8. Tax is the snapshot base capital-gains model; personal cess, surcharge and dividend tax are not modelled. Full data completeness remains unmet.

## B5 residual risk

Both stages price excess return against the same `B5Path`: a monthly choice among five total-return indices, entered at the previous session's TRI close because the snapshot has no index opens, with every index switch charged 30 bp and the snapshot sell-date tax. Stage 2's 11/11 pass used the corrected `independent_b5` from the Stage 1 checker, so the chain arithmetic is independently verified. Four things around it are not:

- **The monthly selection is taken as given.** The checker replays returns from `benchmark_choices` in the results file and never re-runs `select_month`. A wrong index in any month — from the trailing-return ranking, the one-year lookback or the seven-day staleness gate — would pass the run and the check alike.
- **Book B5 is not recomputed.** C4's 12.02% B5 CAGR and its excess CAGR come from `B5Path.book_nav`, with its own fee and shared annual-exemption treatment. The checker replays the strategy book's fills and closing cash, not the benchmark NAV.
- **The entry proxy is a declared convention.** The benchmark buys at the previous close while the stock buys at the next open, so every excess level, including H01's 8.78%, carries a one-session mismatch. It applies to both arms of C3, so the contrast largely cancels it; the levels do not.
- **Coverage is sampled.** Each card recomputes 30 events. C3's unconfirmed arm is H01's stored `net_excess`, not recomputed here. And 34 of the 60 monthly choices are BSE series (15 BSE IPO, 15 BSE Sensex, 4 BSE 250 SmallCap) whose total-return adjustment is derived in-snapshot.

The first is the one to watch on a rerun: if `select_month` changes, every B5 number in both stages moves together and the check would still pass.

## Tests

88 tests passed. All prior ledger rows and the Stage 1 H02 rows remain in the BH family.

## Reproduction

`python -m reality_engine.harness.run_h01xh02 --placebo-draws 499`

Git HEAD `1dedba8016152cba45b5e693abce327ee33cc661`. No 2026 outcomes, paid worker, commit, push or upload.

