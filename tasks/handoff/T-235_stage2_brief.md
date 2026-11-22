# T-235 stage 2 brief: audit stage 1, then rerun the capital-flow study over 2010-2026

Ticket: T-235 (Shivam 22 Nov 2026). Reviewer: Wolf (Opus). You did not write stage 1: you are its independent checker.

Goal: stage 1 (merged d037f578; `reality_engine/research/flow_signals.py`, `flow_events.py`,
`docs/research/T-235_capital_flow.md`) found 1,201 of 3,791 cells passing BH and several backwards-looking signs:
"delivery spike on a down day" (distribution) +1.05% vs placebo +0.08% at 5 sessions; promoter selling +1.16% at 20
sessions; bad quarter +1.16% at 5 sessions. Before anyone trusts it: find whether these are real (short-term reversal,
liquidity premium) or construction artefacts. Then rerun over 2010-2026 now that T-236 loaded 2010-2018
(`mkt_nse_eq_daily` 2010-01.., `mkt_bse_delivery_daily`, `mkt_nse_bulk/block`, `mkt_nse_insider` 2015-11..,
`mkt_fii_dii_cash` and `mkt_nsdl_fpi_daily` 2010-01..; corporate actions in `corporate_actions`).

Evidence: stage-1 outputs `.tmp/t235/` in the MAIN checkout `C:/Users/warri/Downloads/Info_Diffusion_Model`
(copy what you need); DB path `reality_engine` config `cfg.DB_PATH` (read-only); snapshot builder
`reality_engine/scripts/build_truth_snapshot.py` (px_daily adjusted + TRI, 2019+ today).

Steps:
1. Audit (write `docs/research/T-235_audit.md`): for the 5 most surprising cells, recompute 30 random events by hand
   from raw prices (adjusted for splits/bonus): event date vs date_known, entry price (next session open/close?), exit,
   benchmark. Check: look-ahead in date_known; survivorship; corporate-action jumps inside windows; winsorisation;
   placebo design (same stock same year random dates - does it remove a small-cap drift?); overlapping events from one
   stock dominating; NW lags. State per cell: real / artefact (which) / unclear.
2. Fix any artefact found (tests first), rerun stage 1 on 2019+ and report what changed.
3. Extend the price series to 2010: build adjusted daily prices + Nifty 500 / Nifty 50 TRI proxy for 2010-2018 from
   the loaded tables (reuse build_truth_snapshot logic; write a new snapshot under `.tmp/t235/` if D: is denied; keep
   RAM < 4 GB, stream by year). Signals available pre-2019: delivery, volume, bulk/block, FII/DII, insider from
   2015-11; shareholding/results only where held (say which).
4. Rerun the full study 2010-2026: per-year and per-phase tables (index vs 200-session mean x 12m return sign); call out
   2011, 2015-16, 2018-2020 consolidation, 2020 crash, 2021-24 rally; fading/strengthening and lead-time trend.
5. Tests for every fix; docs: update T-235_capital_flow.md (round 2 section) + audit doc + DEVELOPER_GUIDE line.

Files: `reality_engine/research/flow_signals.py`, `flow_events.py`, `reality_engine/tests/test_flow_signals.py`, the
two docs, DEVELOPER_GUIDE. Do not edit tasks/STATE.md.

Pitfalls: 2010-2011 NSE bhavcopy has no ISIN column (join by symbol + series with the symbol-change history); BSE
delivery was found corrupt in stage 1 - say whether 2010-2018 BSE delivery is usable before using it; a deck reader
job writes `.tmp/t232read/` all day - never touch it.

Accept: tests pass; audit doc with per-cell verdict and recomputed examples; round-2 tables with counts behind every
percentage; report under 25 lines.

Stop if: an artefact invalidates most of stage 1 (report before rerunning); RAM > 6 GB.

Budget: about 4 hours, DeepSeek max effort.
