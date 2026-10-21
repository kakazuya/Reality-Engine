# H01 downside wall and fall chronology — declared before guard results

Shivam: "Tighten the wall with figuring out when did the stocks fell." Interpretation: trace drawdowns and test downside controls. Peak-time Codex implements; check timing again before additional implementation if work reaches15:30 IST.

Initial forensic read of the existing saved books: broad both-known positivePAT180 placed almost the full Rs10lakh sleeve into TCS on13-Apr-2022, reached -5.23% on19-Apr and crossed8% drawdown on2-May. The strong/trend version also started concentrated in INFY. This motivates concentration control; no future fall dates will be used to define execution decisions.

## Fall chronology, descriptive only

Use read-only truth_2026-10-19 snapshot; regular-session calendar, evidence2021–2025 only. Reconcile the original broad both-knownPAT180 book's daily and issuer P&L, fees/taxes, peak/start dates, first5%/8% drawdown dates and next-open liquidation. Name the largest loss contributors and show the market path alongside it without asserting a news cause.

For all original4285 positivePAT180 event opportunities, record first close below entry, first -5%/-8% from entry, first8% drawdown from the running close peak, maximum adverse excursion/date, worst peak-to-trough/date and final return. Summarize when those falls occur (0–5,6–20,21–60,61–120,121–180 sessions), by year, and how many eventual positive-excess events first suffered those declines. This is an audit of the registered cohort, not a fitted stop scan.

## Frozen guard grid: eight tests

Same both-known PAT positive, nonzero surprise,180-session scheduled exit. No threshold/horizon/surprise tuning.

1. Existing baseline: equal weight on admissions; liquidity cap only.
2. Max10% of current strategy-sleeve NAV per issuer; unused capacity cash.
3. Cap10% +5% fixed EOD loss from live FIFO weighted cost basis.
4. Cap10% +8% trailing EOD loss from maximum observed close (initial entry open seeds the high water mark).
5. Cap10% + stock50-session SMA admission/exit rule.
6. Cap10% + market200-session SMA gate.
7. Cap10% + trailing8% + market200 gate.
8. Cap10% + fixed5% + market200 gate.

Stock50 admits only when the prior completed close is above its trailing50-session SMA, and requests exit when an actual closing quote is below the current50-session SMA. Missing history refuses admission.

Market200 uses the index selected by B5 for the current month, known before that month. Prior-close index TRI must be above its trailing200 normal-session mean to admit. An EOD failure requests exit for existing holdings; next session's known selected-index gate governs admissions. Missing history fails closed. No index open or future index winner is used.

All stock/market EOD stop decisions fill at the next actual positive open, never the signal close or the ideal stop price. Gaps can overshoot. Missing opens retain a pending liquidation. No re-entry on the same session as a risk exit; new future filing events may be admitted normally. Every decision/fill retains its date and reason. Scheduled exits remain close fills. Existing8% strategy/5%–8% portfolio limits,10% capital allocation and10%-of-lagged-ADTV cap remain unchanged. No automatic revival of a killed sleeve.

## Evidence and outputs

Compare all eight books over2021–2025, including cash and kills, after30bp round-trip cost and snapshot tax. Show sleeve/total-capital CAGR, B5 excess, drawdown, exposure, costs, taxes, fills, stop overshoot and winners truncated. Keep all216 prior ledger tests; append all8 guard tests, including failures, for initial BH family224.

Infer on the60 monthly book-excess observations with max(simple month t-test p,9-lag monthly HAC p), plus999 coherent9-month circular block bootstraps of centered monthly excess and current8-grid max-T. Report descriptive improvement over the baseline separately. These portfolio tests are not equivalent to event means; no special early-start cutoff or altered risk limit is fitted. Data coverage/B5 proxy/tax limits remain; no deployment without proof.

Create separate fall-audit, guard report/results, compressed paths/fills/decisions, tests and independent verification. Preserve all earlier artifacts. No2026 outcomes, live/source DB writes, commit, push, upload, secret access or paid call during peak.
