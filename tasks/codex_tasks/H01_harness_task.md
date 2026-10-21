# Codex task: shared backtest harness v1 + H01 PEAD (first run)

You are working in the repo `C:\Users\warri\Downloads\Info_Diffusion_Model` on the laptop `Sumit`
(Windows 11, Python 3.14, duckdb 1.5.6, pandas installed). Claude orchestrates and will review your work
by meaning (look-ahead, joins, cost/tax maths), not only by whether tests pass.

## Read first (authority order)
1. `tasks/FRAMEWORK.md`: the authority. Rules for trading, costs, tax, benchmark, risk and proof.
2. `tasks/HYPOTHESIS_REGISTER.md` §1 (fixed rules F1-F4, B5 benchmark, universes U1-U3, evidence window,
   data-completeness gate) and the card **H01 · Card B — Earnings-surprise conditioning (PEAD)** (§3, Part A).
   The card's signal, PIT trigger and fooling risks are the spec. Follow them exactly.
3. Reuse, do not redefine: tax/cost stack in `reality_engine/processing/sip_backtest.py` (only where it agrees
   with FRAMEWORK: costs here are a fixed 0.30% round trip, and tax comes from the snapshot's `tax_rules` table by
   sell date); event-study conventions in `analysis/diffusion_study/common.py` and `02_event_engine.py`
   (FRAMEWORK §6 says the harness starts from the diffusion-study code).

## Data
- Only source: `reality_engine/data/snapshots/truth_2026-10-19.duckdb`. **Open it read-only.**
  Tables you will need: `results_key`, `results_filings`, `bse_ann`, `security_master`, `px_daily`
  (adjusted + total-return), `px_nse`/`px_bse` (raw close for the ₹10 penny rule), `index_tri`, `tax_rules`,
  `symbol_isin_history`, `snapshot_meta`, `truth_report`, `unexplained_jumps`. Inspect schemas yourself
  (`describe`) before writing joins. Do not assume column names from this brief.
- Do not open or write any other database. No network access is needed; do not install packages.

## Build
1. **`reality_engine/harness/`**: a small shared package every hypothesis card will reuse:
   - `data.py`: snapshot loader (read-only), trading calendar, prices as of t.
   - `universe.py`: U1 as defined in the register (all NSE+BSE equities incl. SME and **delisted names** from
     `security_master`; raw close ≥ ₹10 on signal date; 20-day median traded value ≥ ₹50 lakh, threshold a parameter
     and logged; exclude quarantine if present in the snapshot).
   - `execution.py`: entry at **t+1 open** after the PIT trigger (if no open column exists, say so and use the
     t+1 close, flagged); exit at the close N trading days later; position ≤ 10% of 20-day ADTV.
   - `costs_tax.py`: 30 bp round trip; after-tax return using `tax_rules` at the sell date (STCG/LTCG by holding).
   - `benchmark.py`: B5. At the start of each month pick the index with the best trailing 12-month total return among
     the five named in FRAMEWORK §3, using only data before that month starts. Log the chosen index and method per period.
   - `stats.py`: Benjamini-Hochberg FDR across the **full** variant grid, placebo (shuffled filing dates within the
     same calendar month, many draws, report the placebo distribution), per-year and up/down-market regime split.
   - `ledger.py`: one append-only ledger, `reality_engine/data/backtests/ledger.duckdb` (new file), with one row per
     variant tested (pass or fail): card id, variant params, n events, mean/median net excess, t-stat, p, BH q,
     placebo p, per-year signs, coverage, code git hash, snapshot name, run timestamp.
2. **`reality_engine/harness/cards/h01_pead.py`**: H01 exactly as the card says. PIT trigger = earliest
   `bse_ann.DissemDT` (Financial Results, NEWSSUB parsed to the same period end) with the card's fallback, never
   `period_end` and never `results_filings.known_at_utc` alone (see the TITAGARH example in the card). Use
   `results_filings.trading_isin`, never `filings.isin`. Surprise = YoY PAT change / std of the prior 8 YoY changes
   (only data known before the trigger). Revenue variant as the card says (banks: InterestEarned).
   Variant grid: 2 horizons (20, 60) × 2 measures (PAT, revenue) × sign (positive vs negative surprise), plus
   surprise quintiles as a descriptive table. Every variant goes into the ledger.
3. **Evidence window: 2021-01-01 → 2025-12-31 only.** Do not report 2026 results (2026 is the live period).
   2019-2020 only for lookbacks.
4. A simple book on top of the event results: ₹1 cr capital, 10% allocation to the strategy, equal weight across
   concurrent positions, liquidity cap, strategy kill at 8% drawdown on its allocation. Report CAGR, max drawdown and
   excess vs B5, after tax and costs.
5. **Tests**: `reality_engine/tests/test_harness_h01.py` (unittest, small synthetic fixtures, no snapshot needed):
   no trigger before dissemination, period-end parse from NEWSSUB, surprise uses only prior data, B5 pick uses only
   prior data, BH-FDR on a known example, cost and tax maths, t+1 entry. Run them and the existing
   `python -m unittest reality_engine.tests.test_horizon_excess` to make sure nothing broke.
6. **Run H01 once** on the snapshot and write `tasks/backtests/H01_report.md` (+ `H01_results.json`): coverage table
   (covered ISINs vs U1 per year, as the register's data-completeness gate requires; label results **provisional**),
   the variant table with BH q and placebo p, per-year signs, the book stats, B5 choices per month (summary), and a
   short "what could still be fooling us" section. Plain English, short sentences.

## Rules
- New files only. Do not edit FRAMEWORK.md, HYPOTHESIS_REGISTER.md, STATE.md, AGENTS.md or existing modules
  (if a fix in an existing module is truly needed, describe it in the report instead).
- No `git commit`, no push, no `git stash`. Claude reviews, then commits.
- If something in the card cannot be done with the snapshot (missing column, ambiguous join), do not guess silently:
  pick the most conservative option, flag it in the report under "Deviations", and continue.
- Final message (it is saved to a file): files created, test results (counts), H01 headline table, deviations,
  run time. Keep it under 60 lines.
