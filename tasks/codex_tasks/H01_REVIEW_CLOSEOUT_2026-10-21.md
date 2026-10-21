# H01 review and corrected backtest — 21 October 2026

H01 is complete as a provisional historical subset test. **No variant is promoted.** H02 bulk/block deals is next in the register. No 2026 results were used.

Codex implemented during peak time, per Shivam's standing workflow. No DeepSeek call, advisor request, commit, push, upload, or live/source database write was made.

## Review fixes

- One shared weekday-only calendar now excludes the eight special weekend sessions from stock windows, liquidity history, B5 lookbacks and holding horizons. This intentionally omits real Saturday budget/drill sessions too; the deviation is logged.
- A missing scheduled close uses the stock's next actual close. Tax and B5 follow that date. Unresolved evidence-boundary cases retain an explicit pessimistic bound rather than a fictitious sale; the corrected actual sample has **zero unresolved loss bounds**.
- Both timing policies run together: strict BSE-next-open with numbers already public, and next regular open after max(BSE, XBRL). The 2 timings × 2 horizons × 2 measures × 2 signs produce 16 variants.
- Added directional placebo p-values, BSE-to-XBRL/entry-lag distributions, stock-side entry gaps, exit-delay audits and an independent artifact/source checker.
- Earlier report/results/events/verification were archived under tasks/backtests/archive/bcddb18d-843f-417c-a941-cfbc6f19289b. Both prior ledger runs receive append-only superseded_by_bugfix notes. All 16 prior tests remain in BH.

## Outcome

Run: `4d3bf641-0f00-4502-9321-8a4c10326ada`; corrected backtest runtime 71.242 seconds; 499 placebo draws; 59,082 variant-event rows; 16 new ledger rows, 32 total tests in BH.

| Positive surprise | Horizon | Strict BSE mean net excess | Both-known mean net excess |
|---|---:|---:|---:|
| PAT | 20 | -0.93% | -0.52% |
| PAT | 60 | +0.97% | +1.59% |
| Revenue | 20 | -0.88% | -0.56% |
| Revenue | 60 | +0.91% | +1.34% |

The best current unadjusted p is .0118 (both-known PAT60), but BH q is .379. Its directional shuffled-date p and current-grid max-T p are both 1. All eight alternative positive books hit the strategy drawdown kill between 29 April and 2 May 2022. Sleeve CAGR is -1.48% to -1.96%, versus B5 +12.02%. Book results are after the fixed 30bp cost and snapshot base capital-gains tax.

Strict timing qualifies 6,538 issuer-quarter events before horizon/sign selection; waiting for both qualifies 9,055. Qualified XBRL lag p50/p90/p99 is 2.4/12.3/25 hours for strict timing and 4.04/23.3/167 hours for both-known timing. No clean 2021 signal is possible with the required twelve prior quarterly observations and only 2019 onward warm-up.

## Verification and remaining limits

- 86 tests pass: 49 H01 harness, 37 existing horizon tests.
- 27 artifact/source checks pass across all 59,082 rows: source prices, exact entry/exit horizons, first available liquidation, tax, B5 matched actual exit, all XBRL dates, first written rows plus deterministic BSE timestamp sample, counts/means, ledger/BH preservation, cash/drawdown/kill rules and source hashes.
- Snapshot opened read-only; file length and modification timestamp unchanged during the run.
- Full data coverage remains incomplete. Index opens are absent; B5 uses a previous-close proxy. BSE total-return series are estimated. Taxes exclude personal dividend tax, cess and income-dependent surcharge. No technical confirmation overlay was invented for H01.

Artifacts: tasks/backtests/H01_report.md, H01_results.json, H01_events.csv, H01_b5_monthly.csv, H01_tests.json, H01_verification.json. Reproduce with `python -m reality_engine.harness.run_h01 --placebo-draws 499`, then `python -m reality_engine.harness.verify_h01`.
