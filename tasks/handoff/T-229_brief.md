# T-229 brief: factor study on the 91 Telegram stores (stage A only)

Ticket: T-229 (Shivam 21 Nov 2026). Reviewer: Wolf (Opus). Do ONLY stage A, then stop and report. Stage B arrives as
a follow-up message after Wolf reads stage A.

Goal: Shivam's ultimate goal is predicting a stock 6 months to 2 years ahead from reliably held facts. The universe
factor study (T-118/T-207/T-210, `docs/research/T-210_factor_deep_study.md`, code `reality_engine/research/`) ran on the
XBRL truth snapshot. Now run the same idea on the 91 company stores we built properly, from the stores' own rows,
point in time. Stage A builds and validates the panel; no IC is computed in stage A.

Evidence: (real, read these)
- Stores: `D:/RealityEngine/tg_build/measure10/cNN/cNN.db`, 91 of them (skip `c40_crash_*`), read-only (`mode=ro`).
  Company list with selection fields: `D:/RealityEngine/tg_build/build_queue.csv` (tier, symbol, pead_score, fwd_pe,
  order_win_60d, mcap_cr): these 91 were PICKED in Nov 2026 on recent results strength, so any result on them carries
  selection bias; stage B measures it with a control set.
- Tables per store (c17 checked): `fin_quarter_current` view (one preferred line per symbol, fiscal_period, basis,
  line_item; known_at 2024-05-27 .. 2026-10-28; the quarter tables' `preferred_from`/`preferred_to` elect the figure as
  of any past day - use them, never a hand sum), `valuation_daily` (market_cap, trailing_pat, net_debt, trailing_ebitda),
  `shp_category` (quarter_end, category, pct), `price_delivery` (2019-01-01 .. 2026-11-09, close, volume, value_inr),
  `index_price`, `kpi_series` (order book etc.), `guidance` (low/high/unit/direction/revision_of, known_at),
  `script_cell` (status verified/unverified, line_item, fiscal_period; only `verified` may be used).
- Reuse, do not modify: `reality_engine/research/factor_weights.py` (`pit_sessions`, `spearman_ic`,
  `newey_west_tstat`, `attach_asof`, `winsor_z`, `default_snapshot()` = truth_2026-11-04.duckdb) and the factor
  names/definitions T-207/T-210 use, so the two studies line up name for name.

Steps (stage A):
1. `reality_engine/research/factor_store91.py`: for every month-end from 2024-06-28 to the last session, every store
   company: compute factors using only rows with known_at <= that month-end (as in pit_sessions: a filing after 15:30
   IST counts from the next session). Factors, same names as T-207 where one exists: q_rev_yoy, q_pat_yoy, ttm_rev_yoy,
   ttm_pat_yoy, op_margin, op_margin_chg, earnings_yield, sales_yield, fin_cost_to_rev, net_debt_chg_4q,
   promoter_chg_1q, promoter_chg_4q, fpi_chg_4q, mf_chg_4q, pledge_pct, delivery_3m, mom_12_1, vol_12m, size; and new
   store-only ones: guidance_rev (latest guidance raised +1 / cut -1 / none 0, from revision_of), guidance_growth
   (latest revenue-growth guidance midpoint minus trailing growth), order_cover (order book / TTM revenue, kpi_series).
   Targets: forward 3m, 6m, 12m returns from `price_delivery` close, minus the equal-weight mean of the 91 that month
   (excess), with NaN where the window has not closed.
2. Validation against the truth panel: for the same company-months, compute the T-207 factors from the truth snapshot
   (factor_weights panel builder, read-only) and report per factor: overlap count, Spearman rho store vs panel,
   share within 5% relative, and the 10 worst disagreements with both values and the store row's source doc/page.
3. Coverage table: per factor, companies with a value per month-end (min / median / max), and month-ends with >= 20
   names and a realised 3m / 6m / 12m target.
4. Tests `reality_engine/tests/test_factor_store91.py` (synthetic): a fact with known_at after the month-end is never
   used (after-15:30 rule included); preferred_from/preferred_to election; excess return arithmetic; guidance_rev sign.
5. Doc `docs/research/T-229_factor_store91.md`: data, factor definitions, PIT rule, validation and coverage results.
6. Output under `.tmp/t229/` (panel parquet, validation csv, coverage csv). Report: under 50 lines, tables first.

Files: new `reality_engine/research/factor_store91.py`, `reality_engine/tests/test_factor_store91.py`,
`docs/research/T-229_factor_store91.md`. No other file edits (do not edit tasks/STATE.md; Wolf owns it).

Accept: `python -m pytest -q reality_engine/tests/test_factor_store91.py` passes; typecheck clean on the new .py files;
the panel, validation and coverage files exist and the report gives the numbers.

Limits and pitfalls:
- Read-only on every store and on the truth snapshot. Writes only in your worktree.
- No model calls at all; this is pure computation.
- Do not compute ICs, rankings or any return claim in stage A.
- Peak RAM under 2 GB (T-210 hit 3.7 GB before streaming; another job is using most of the CPU right now).
- Run pytest per file.
- known_at must come from the store row; never from the fiscal period end.

Stop if:
- More than 5% of panel facts would need a known_at the row does not have: stop, report examples.
- Fewer than 15 month-ends have >= 20 names with a realised 6m target: report and stop.

Budget: about 2 hours, DeepSeek max effort.
