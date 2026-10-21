# H01 downside wall and when stocks fell — provisional

Run `34f00e71-a320-4d97-88df-36ff8d2e3cee`. Eight declared guard tests;224 tests in BH including all216 prior tests. Evidence2021–2025 only.

## Original book failure

First entry:2022-04-13; first5% sleeve drawdown:2022-04-19; kill:2022-05-02.
B5 gross previous-close proxy over first entry through kill:-4.33%.
The sleeve initially invested almost entirely in one issuer. Market weakness and individual-stock losses overlapped; this is price evidence, not a verified news-causality claim.

| Stock label | Net P&L INR through liquidation | Fees INR | Tax INR |
|---|---:|---:|---:|
| TCS (INE467B) | -32062 | 2996 | 0 |
| TATACOMM (INE151A) | -13969 | 481 | 0 |
| LTM (INE214T) | -12715 | 579 | 0 |
| TTML (INE517B) | -5449 | 157 | 0 |
| ABREL (INE055A) | -4708 | 283 | 0 |
| INFY (INE009A) | -4706 | 727 | 0 |
| KPITTECH (INE04I4) | -4081 | 157 | 0 |
| ORIENTHOT (INE750A) | -2560 | 727 | 53 |
| LTTS (INE010V) | -1968 | 359 | 11 |
| SNOWMAN (INE734N) | -1812 | 199 | 0 |

## When the180-session opportunities fell

All4285 original positive-PAT180 events are retained. Threshold dates are retrospective audit labels; guard orders use only each actual EOD observation.

| Fall | 0–5 sessions | 6–20 | 21–60 | 61–120 | 121–180 | Never | Eventually positive excess despite fall |
|---|---:|---:|---:|---:|---:|---:|---:|
| loss5 | 1593 | 777 | 586 | 257 | 121 | 951 | 1554 |
| loss8 | 850 | 768 | 795 | 336 | 187 | 1349 | 1264 |
| trail8 | 962 | 1416 | 1488 | 335 | 58 | 26 | 2268 |

loss5/loss8 are close declines from entry open; trail8 is close drawdown from the running close high, seeded by entry open. Full stock/date rows and extrema are in H01_falls.csv.gz.

## Guard books

| Guard | Sleeve CAGR | B5 excess CAGR | Max DD | Kill | Mean cash | Costs INR | Tax INR | EOD exit decisions | Monthly BH q | Block placebo p | Max-T p |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | -1.70% | -13.72% | 8.45% | 2022-05-02 | 99.03% | 10568 | 4022 | 0 | 0.359 | 0.933 | 0.174 |
| cap10 | -2.14% | -14.16% | 10.23% | 2022-05-06 | 99.10% | 7597 | 3184 | 0 | 0.34 | 0.94 | 0.148 |
| cap10_stop5 | -2.16% | -14.18% | 10.32% | 2022-05-06 | 99.15% | 9152 | 3537 | 31 | 0.34 | 0.94 | 0.146 |
| cap10_trail8 | -2.08% | -14.10% | 9.97% | 2022-05-06 | 99.10% | 8361 | 3552 | 19 | 0.34 | 0.937 | 0.149 |
| cap10_sma50 | -1.92% | -13.94% | 9.22% | 2022-05-06 | 99.28% | 7987 | 4106 | 15 | 0.347 | 0.935 | 0.151 |
| cap10_market200 | -1.62% | -13.64% | 10.78% | 2022-12-23 | 91.24% | 17989 | 25636 | 36 | 0.383 | 0.926 | 0.171 |
| cap10_trail8_market200 | -1.86% | -13.88% | 9.81% | 2023-01-27 | 90.68% | 35001 | 40225 | 553 | 0.368 | 0.936 | 0.157 |
| cap10_stop5_market200 | -1.62% | -13.64% | 9.39% | 2022-12-23 | 91.92% | 23181 | 28606 | 393 | 0.383 | 0.928 | 0.169 |

cap10 limits each issuer to10% of pre-trade sleeve NAV at open, with excess capacity in cash. fixed5 uses FIFO weighted cost. trail8 uses the observed high water mark. SMA50 vetoes admissions below the prior completed stock average and exits on an EOD breach. Market200 uses the index already selected by B5 for that month.
Every risk decision fills at the next actual open; stock gaps and missing quotes can overshoot. Scheduled exits remain close fills. The unchanged8% strategy kill can still trigger. These are whole-book results including cash; the event-return averages in earlier reports are different quantities.

## Audit and inference

Baseline matches its earlier saved NAV:True; maximum daily issuer-P&L reconciliation error:3.53e-10 INR.
Monthly p=max(simple monthly t-test p,9-month HAC p).999 coherent9-month circular block draws calibrate centered monthly excess and the current8-test maximum absolute statistic. All earlier tests remain in BH.

- caps checked against sleeve NAV at open before trading fees; price drift can breach between checks
- EOD exits execute at next real open; no intraday stop fills or guaranteed stop price
- no automatic restart after strategy kill; killed sleeves remain cash
- current names may differ from historical company names; issuer/actual ISIN anchors retained
- B5 previous-close proxy, derived BSE TRI, snapshot base capital-gains tax and incomplete coverage
- guard grid motivated by observed earlier startup concentration; exploratory; all prior tests retained

Tests:107 passed. Snapshot read-only/unchanged:True. Runtime:33.8s. No2026 outcomes or deployment.
Reproduce:`python -m reality_engine.harness.run_h01_wall`; independent check:`python -m reality_engine.harness.verify_h01_wall`.
