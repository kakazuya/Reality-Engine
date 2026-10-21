# H01: the falls are early, clustered, and often followed by recovery

The fall audit is complete. Eight predefined guard books were implemented and tested. **None provides a proven downside wall yet.** H01 remains a longer-term selection research lead; no guard or strategy is promoted.

## When the original book broke

The broad positive-PAT180 book first entered on13-Apr-2022, investing almost the entire Rs10lakh sleeve in TCS. It reached5.23% sleeve drawdown on19-Apr,6.66% on25-Apr,7.15% on29-Apr and8.45% on2-May. The next trading-session open was4-May; liquidation left Rs917,881, a net loss of Rs82,119. The selected B5 gross previous-close proxy fell4.33% over first entry through the kill date.

The largest daily losses were25-Apr (-Rs32,938),19-Apr (-Rs19,776) and18-Apr (-Rs18,890). TCS contributed -Rs32,062 to the final loss, TATACOMM -Rs13,969 and issuerINE214T/current labelLTM -Rs12,715. These figures include attributable fees and tax and reconcile to the actual saved book; they are not standalone stock returns.

The stricter surprise/trend book also began almost entirely in Infosys on18-Apr and hit its strategy kill on4-May. Startup concentration is real. The tested10% issuer cap alone did not solve the later correlated losses.

## When individual stocks first crossed a5% close loss

These are path audits from each actual entry open through180 sessions, even where the book liquidated earlier.

| Stock label | Entry | First close loss>=5% | First close loss>=8% |
|---|---|---|---|
| TCS | 13-Apr-2022 | 19-Apr-2022 | 12-May-2022 |
| TATACOMM | 22-Apr-2022 | 25-Apr-2022 | 25-Apr-2022 |
| INE214T/currentLTM | 21-Apr-2022 | 25-Apr-2022 | 26-Apr-2022 |
| INFY | 18-Apr-2022 | 12-May-2022 | 19-May-2022 |

Names are current snapshot labels. Historical issuer keys and filing dates are retained. This audit locates falls; no news cause is asserted.

## How common the falls were

Across all4,285 positive-PAT180 opportunities:

- 55.3% first fell at least5% from entry within20 sessions.37.8% first fell at least8% within20 sessions.
- 3,334 eventually crossed -5%;1,554 of them still finished ahead of after-tax/cost B5 over180 sessions.
- An8% close-to-running-peak drawdown occurred in4,259 events (99.4%). It occurred in2,268 of the2,285 eventual positive-excess events too.
- TATACOMM's April2022 event illustrates the trade-off: it crossed -8% on25-Apr, yet its full180-session excess was+20.89%.

An8% stock trailing stop is therefore inside the observed noise/retracement range of almost every eventual winner in this sample. The portfolio's8% kill is a separate constraint and remains binding.

## What the eight guards did

| Guard | Strategy kill | Maximum sleeve drawdown | Sleeve CAGR |
|---|---|---:|---:|
| Original baseline | 2-May-2022 | 8.45% | -1.70% |
| Issuer cap10% | 6-May-2022 | 10.23% | -2.14% |
| Cap + fixed5% loss exit | 6-May-2022 | 10.32% | -2.16% |
| Cap + trailing8% exit | 6-May-2022 | 9.97% | -2.08% |
| Cap + stockSMA50 | 6-May-2022 | 9.22% | -1.92% |
| Cap + marketSMA200 | 23-Dec-2022 | 10.78% | -1.62% |
| Cap + trailing8% + marketSMA200 | 27-Jan-2023 | 9.81% | -1.86% |
| Cap + fixed5% + marketSMA200 | 23-Dec-2022 | 9.39% | -1.62% |

The market gate postponed failure; it did not pass the risk/return proof. A stop decision uses the close and executes at the next actual open. Drawdown can exceed8% before liquidation. One verified trailing exit filled14.36% below its trigger threshold after the overnight gap. No stop-price fill was invented.

The current research implication is to model stock-specific volatility, correlated portfolio exposure and downside risk before adjusting another fixed percentage. This is a proposed follow-up, not a tested rule or deployment authorization. The eight failed guards remain in the ledger and must not be selected merely because one delayed its kill.

## Implementation and verification

Optional issuer caps and EOD risk policies are available in the shared cash-book engine. Default behavior reproduces the prior baseline exactly. Risk decisions, next-open fills, gaps, missing opens and same-day re-entry exclusions are audited. No live strategy configuration was enabled.

- 107 tests passed, including caps, EOD-to-next-open timing, gaps, missing opens, prior-only SMA gates, monthly benchmark switches and P&L reconciliation.
- 18 independent review checks passed: all 4,285 source fall paths; source fill prices; FIFO costs/tax; full cash/NAV replay; risk thresholds; next available opens; cap/kill/admission rules; all 999 block-bootstrap draws; and all 224 ledger tests/BH.
- Daily issuer P&L reconciles within3.53e-10 INR. Baseline NAV matches the earlier saved book.
- Read-only snapshot unchanged;2019–2020 warm-up,2021–2025 evidence only. No2026 outcomes, paid worker, commit, push or upload. No new resource-waste incident.
- Run34f00e71-a320-4d97-88df-36ff8d2e3cee took33.8seconds. Eight new tests were appended; all216 earlier tests remain.

Details: H01_wall_report.md, H01_wall_results.json, H01_wall_verification.json, H01_wall_books.jsonl.gz, H01_falls.csv.gz and H01_baseline_fall_attribution.csv in this directory. Frozen plan: tasks/codex_tasks/H01_DOWNSIDE_WALL_PLAN_2026-10-21.md.
