---
description: Curated distilled parameters and derived expansion
---

# lane-code-distill - Curated + derived distilled parameters

> Read `.kilo/LANES.md` first. You own ONLY `reality_engine/processing/distillation_engine.py`, NEW `reality_engine/data/seed/curated_company_parameters.json`, NEW `reality_engine/tests/test_distilled_expansion.py`. **never edit files you do not own; never write DB tables you do not own; worktree-local helper scripts must be deleted before merge or listed in the lane report**

## 1. Discover existing contract

- Read `reality_engine/processing/distillation_engine.py:146` `seed_canonical_company_parameters` to list the 8 already-covered symbols and the exact 5-key schema.
- Read `reality_engine/processing/distillation_engine.py:101` `upsert_parameter` / database persistence path and `reality_engine/db/seed_fundamental.py` for seed pattern.
- Check existing canonical entries copy field names exactly from lines 150-275: `cyclicality_profile`, `business_sensitivities`, `order_book_metrics`, `capital_allocation`, `geopolitical_supply_chain` – do not rename.

## 2. Author curated_company_parameters.json (target 50 total curated)

- Read `reality_engine/processing/distillation_engine.py` lines 150-275 to copy schema verbatim. Each entry has 5 keys:
  - `cyclicality_profile`: is_cyclical, cyclicality_type, cycle_duration_years, cycle_current_stage, key_revenue_drivers, margin_sensitivities, stage_conviction, stage_rationale
  - `business_sensitivities`: key_revenue_drivers, raw_material_sensitivities, pricing_power_assessment, moat_rating
  - `order_book_metrics`: executable_order_book_inr_cr, ttm_revenue_inr_cr, order_book_to_bill_ratio, execution_visibility_years (use None where not applicable)
  - `capital_allocation`: in_progress_capex_inr_cr, expected_commercialization_quarter, deleveraging_trend
  - `geopolitical_supply_chain`: geographic_revenue_split, supply_chain_dependencies, macro_geopolitical_sensitivities, transit_route_risks

- Identify the 8 already-covered symbols in `seed_canonical_company_parameters` (check the canonical_data list – HAL, TITAGARH, KAYNES + 5 more). Do NOT duplicate them.

- Author ~42 NEW curated entries to reach 50 total curated. Prefer list in task: RELIANCE, TCS, HDFCBANK, ICICIBANK, INFY, BHARTIARTL, SBIN, ITC, LT, HINDUNILVR, HCLTECH, BAJFINANCE, MARUTI, SUNPHARMA, KOTAKBANK, M&M, TITAN, ULTRACEMCO, AXISBANK, NESTLEIND, WIPRO, JSWSTEEL, TATASTEEL, HDFCLIFE, GRASIM, TECHM, DRREDDY, CIPLA, EICHERMOT, HEROMOTOCO, BRITANNIA, TATAMOTORS, TATAPOWER, ONGC, HINDALCO, PIDILITIND, VEDL, DLF, APOLLOHOSP, BAJAJFINSV, INDUSINDBK, ADANIPORTS (dedupe against existing 8, top up with other stable large caps like ASIANPAINT, NTPC, COALINDIA, etc. if needed to hit 50).

- Values: realistic public-knowledge FY25/FY26-era, uncertain figures rounded with 'as_of' note in stage_rationale or deleveraging_trend; use bracket approximations where needed.

- Per entry: `confidence` 0.85-0.95, `source_document_ref` = 'Curated_Intelligence_FY26'.

- File path: `reality_engine/data/seed/curated_company_parameters.json`. Allow dict keyed by symbol or list of objects each with `symbol`, `isin`, `parameters` (5 keys) – match pattern caller expects. Ensure isin is plausible INE... (lookup or use placeholder and resolve via master).

- Validation: every entry must have exactly 5 keys listed above, none missing.

### FAN OUT

Use Task tool: 4 parallel sub-agents each authoring 10-11 symbol entries as JSON fragments (write to `C:\Users\warri\AppData\Local\Temp\kilo\curated_batch_*.json` temp). Parent assembles fragments into single `curated_company_parameters.json`, validates 5 keys present per entry, deduplicates, sorts by symbol, runs `python -c "import json; d=json.load(open('reality_engine/data/seed/curated_company_parameters.json')); print(type(d).__name__, len(d))"` – expect 42 entries (or 50 total after merge with existing 8).

## 3. distillation_engine.py – load_curated + derive

### (a) load_curated_company_parameters()

- Resolve isin via `SELECT isin FROM master_companies WHERE nse_symbol=?` when entry provides symbol only; skip entry with warn if missing and log `logger.warning`.
- INSERT path same as `seed_canonical_company_parameters`: loop entries, call `self.upsert_parameter(isin, symbol, key, value, confidence_score=0.85-0.95, source_document_ref='Curated_Intelligence_FY26')` for each of 5 keys.
- Called at end of `seed_canonical_company_parameters()` after canonical_data seeding – add call `self.load_curated_company_parameters()` before return.

### (b) derive_company_parameters(symbol=None, universe="nifty200", limit=None, overwrite_derived=False)

- Build derived 5-key JSON ONLY from DB data:
  - `quarterly_financials` revenue volatility (stddev/mean) -> is_cyclical True if volatility >0.35, stage Cyclical vs Secular, cycle_current_stage derived from recent YoY trend.
  - `annual_financials` roce_pct -> moat_rating proxy: >=18 -> 8, >=12 -> 6, else 4.
  - `annual_financials` opm_pct percentile across universe -> pricing_power_assessment string (e.g. "StrongPricing" if >70th percentile, else "Moderate").
  - `annual_financials` debt_to_equity + operating_cash_flow -> capital_allocation: deleveraging_trend "Deleveraging" if D/E <0.5 and OCF positive else "Levered".
  - `geographic_exposure` -> geographic_revenue_split; else {"IND": 100}.
  - `order_book_metrics`: when unknown -> {"available": false, "note": "Order book not disclosed for this sector"} (keep required keys but mark unavailable).

- Confidence 0.5-0.7 computed from fraction of non-null inputs: `confidence = 0.5 + 0.2 * (non_null / total_inputs)` document formula in code comment.
- source_document_ref = 'Derived_Financials_FY26'.
- Skip symbols already having curated confidence>=0.85 rows unless overwrite_derived=True – check `SELECT confidence_score FROM company_distilled_parameters WHERE symbol=? AND source_document_ref='Curated_Intelligence_FY26'` or confidence>=0.85.
- Implement universe filter: query `master_companies WHERE is_nifty200=1` vs `is_nifty500=1` vs all.
- Limit N.
- Never import from lane-code-cli owned files; keep independent.

Do NOT modify any other file. Keep existing main() entry points exact; new helpers are additive.

## 4. test_distilled_expansion.py

- Use `tests/fixtures.py` isolated pattern: `create_isolated_test_db` or temp `DatabaseManager` with temp dir, never production DB.
- Tests:
  1. curated loader writes 5 keys x N with isin resolved (check company_distilled_parameters count = N*5, source Curated_Intelligence_FY26).
  2. derive writes confidence in [0.3,0.8] + Derived ref, 5 keys present, no crash on missing data.
  3. derive skips curated (seed curated then derive without overwrite -> curated unchanged).
  4. idempotent re-run (second derive returns 0 new rows or same counts).

## 5. Tests to run

```powershell
python -m unittest reality_engine.tests.test_distilled_expansion reality_engine.tests.test_distillation_macro
python -c "import json; d=json.load(open('reality_engine/data/seed/curated_company_parameters.json')); print(type(d).__name__, len(d))"
```

JSON print must show dict or list length 42 (new) or 50 total if counting existing 8 – handle both but document. Tests GREEN.

## 6. Do NOT git commit/merge

Do NOT run `git commit`, `git merge`, or `git stash` (global). Local session integrates; Agent Manager merges (user-driven).

## 7. REPORT

```
REPORT lane-code-distill
- Files changed: reality_engine/processing/distillation_engine.py, reality_engine/data/seed/curated_company_parameters.json, reality_engine/tests/test_distilled_expansion.py
- Tests: test_distilled_expansion GREEN/RED (counts), test_distillation_macro GREEN/RED, JSON len=42/50 OK/FAIL
- Artifacts: curated entries 42 new (50 total), load_curated wired at end of seed_canonical YES/NO, derive confidence range 0.5-0.7 YES/NO, isin resolve skip+warn YES/NO
- Worktree-local helpers deleted or listed: none / [list]
```

Args: `$ARGUMENTS` forwarded to derive if needed.
