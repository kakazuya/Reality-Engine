# T-229 stage C brief: text and deck factors on the 91 stores, and do they add to the hard numbers?

Ticket: T-229 (Shivam 21 Nov 2026). Reviewer: Wolf (Opus). Stages A+B are merged (ab95b574);
read `docs/research/T-229_factor_store91.md` sections 2-3 and 8 first, and reuse
`reality_engine/research/factor_store91.py` / `factor_store91_stageb.py` (panel, PIT rule, IC, NW t, matched control,
placebo, BH, power). Do not change their stage A/B outputs.

Goal: Shivam's plan step 2: text-derived facts must be quantified onto revenue, cost, debt or capital, then tested for
prediction OVER the hard numbers (6m/12m). Two new sources now exist: driver-tree claims widened to annual reports,
press releases and announcements, and deck figures stored with meaning.

Evidence: (real; read-only)
- Claims: `D:/RealityEngine/t228/claims_91.db` (stage 1: transcripts + guidance; 1,159 verified). The widened
  91-store DB is being written now by another worker at
  `C:/Users/warri/Downloads/IDM-worktrees/20261121T002742Z-f52bc83e/.tmp/t228/claims_91_s2.db`; Wolf will copy it to
  `D:/RealityEngine/t228/claims_91_s2.db` when reviewed. Build against claims_91.db and the stage-2b pilot
  `D:/RealityEngine/t228/s2a/claims_s2_pilot.db` (same schema except new columns speaker_scope, dup_of, source_kind);
  make the path a CLI arg. Docs: `docs/research/T-228_driver_claims.md` sections 11-12.
- Deck observations: `D:/RealityEngine/t230/obs_91.db` (63,121 verified of ~102k; ~4% of verified rows wrong on
  Wolf's read; schema `docs/V2_SCHEMA_CONTRACT.md` section 17: measure, value, scale, unit, basis, period,
  period_kind, period_source, entity_scope, stage, series_kind, adjusted, status). known_at is the doc's.
- Open the DBs read-only via a byte copy under --out (stage B did this for WAL reasons).

Steps:
1. Factors (definitions written in the doc BEFORE any IC; verified rows only; only claims/observations with
   known_at <= month-end under the 15:30 IST rule; entity_scope company only for deck rows; speaker_scope company
   only; never `adjusted=1`, never series_kind bridge):
   a. claim_order_inflow_12m: sum of verified revenue.order_book order-win values (inr_cr) announced in the trailing
      12 months / TTM revenue (store).
   b. claim_capex_12m: announced capex.amount (inr_cr, trailing 12m) / market cap.
   c. claim_dilution_12m: announced equity.shares raises (QIP, warrants, preferential, rights; inr_cr) / market cap.
   d. claim_rev_growth (existing definition, now with all sources) and claim_count_12m (existing).
   e. deck_order_cover: latest verified deck order.book (scaled to inr_cr) / TTM revenue; report its agreement with
      kpi_series order_cover where both exist (rho, share within 10%).
   f. deck_capacity_growth: latest verified capacity.add (stage operating/under_construction/approved) / latest
      verified capacity.total of the same unit family and segment; skip when units differ.
   Unit handling: convert only inr_cr / lakh / mn / bn with the stored scale; anything else is skipped and counted.
2. Coverage table as in stage B (companies, months with value, months >= 20 names, per horizon after the window
   closes). The gate stays as in stage B (>= 12 month-ends with >= 20 names and a realised target).
3. ICs, placebo, BH, matched control, power for every factor that passes the gate, exactly as stage B.
4. Incremental test: for each passing text/deck factor, IC after residualising it cross-sectionally each month on the
   stage B survivors (sales_yield, earnings_yield, promoter_chg_4q, delivery_3m, q_pat_yoy, size). Report raw IC,
   residual IC, NW t, placebo p.
5. Run on claims_91.db now; then the same command on `--claims D:/RealityEngine/t228/claims_91_s2.db` when Wolf sends
   the go (STOP and report after the first run; wait for a followup).
6. Tests `reality_engine/tests/test_factor_store91_stagec.py` (synthetic): PIT exclusion of a claim filed after 15:30
   on the month-end, scope/adjusted/bridge filters, unit scaling, residualisation arithmetic.
7. Doc: new section 10 in `docs/research/T-229_factor_store91.md`.

Files: new `reality_engine/research/factor_store91_stagec.py`, `reality_engine/tests/test_factor_store91_stagec.py`;
edit `docs/research/T-229_factor_store91.md`. No other file; do not edit tasks/STATE.md.

Accept: `python -m pytest -q reality_engine/tests/test_factor_store91_stagec.py` passes; typecheck clean; report.

Limits and pitfalls:
- No model calls. Peak RAM under 2 GB. Run pytest per file.
- The 91 were picked in Nov 2026 on recent results strength: every number is conditional on that; keep the control.
- Do not tune factor definitions after seeing ICs. A failed gate is a result; report it.
- Order wins are flows; a deck order book is a stock: never add them.

Stop if: a factor needs a known_at the row does not have (>5% of its rows); fewer than 2 factors pass the gate on
the first run (report coverage and stop).

Budget: about 2 hours, DeepSeek max effort.
