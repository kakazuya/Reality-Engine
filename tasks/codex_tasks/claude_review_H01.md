# Claude (advisor) review of H01 run — 2026-10-20 23:40 IST

Reviewed: `tasks/backtests/H01_report.md`, `H01_events.csv` (22,868 event rows), snapshot spot checks.
Verdict: **do not read the H01 numbers yet.** One clear bug and one design choice need fixing first.

## 1. BUG: special trading sessions turn into -100% returns
- 98 distinct ISINs (~1% of events, 18-33 per variant) have `exit_missing_loss_bound = True`, booked as -100% gross.
- Their exit dates are **2023-11-12 (Sunday, Diwali Muhurat session)** and **2024-03-02 (Saturday, NSE special
  DR-drill session)**. The harness calendar includes these one-off sessions, but `px_daily` has no price for most
  stocks that day. Examples: INFY, LICHSGFIN, INDIGO, ENGINERSIN. All trade normally and still have prices up to 2026-10-19.
- Effect: it drags every variant's mean down by about 0.5-1.0 pp. Without those rows, PAT+ 60d goes from +0.24% to
  +1.07% and PAT+ 20d from -1.36% to -0.82%.
- Fix: build the trading calendar only from normal sessions (drop Muhurat/special sessions, or require a session
  where most of U1 has a price). Exit at the stock's own next available close. Keep the -100% bound only for a real
  delisting or suspension with no later quote, and list those cases by name. Check the B5 series uses the same calendar.

## 2. Design: ~70% of events are rejected because XBRL came after the BSE PDF
- Event gates: 21,248 BSE-triggered events, but `current_xbrl_after_bse_trigger` = 20,818 and only 6,111 pass.
  So the test runs mostly on issuers whose XBRL arrived before the next open. That is a selection, and it may
  differ in size and quality from the rest.
- No look-ahead requires rejecting them. Enter at the next open **after the later of** the BSE dissemination and the
  XBRL `known_at` (the numbers are then known for sure). Report the lag distribution and run both variants:
  (a) "XBRL-known before t+1" (current) and (b) "enter after max(BSE, XBRL)". Both go in the ledger and the BH family.

## 3. Smaller checks
- Placebo p is two-sided on absolute means (report line 58). Fine, but also give the one-sided placebo p for the
  claimed direction (+ for positive surprise). The table reads oddly otherwise (p=.002 on a negative mean).
- B5 enters at the previous close while stocks enter at the open (Deviation 3). Measure how big that gap is on
  average (index open vs previous close is unknown, so use the Nifty 50/500 overnight gap from any source in the
  snapshot, or report the stock-side overnight gap) so we know the bias direction.
- All four books hit the 8% kill on 2022-05-02. Re-run the book after fix 1; the -100% rows probably caused part of it.
- The ledger keeps both earlier runs: good. Mark the runs before this fix as `superseded_by_bugfix` rather than
  deleting them, and keep them in the BH count.

Coverage and the late-XBRL issue mean H01 stays provisional whatever the rerun shows.
