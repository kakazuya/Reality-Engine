# T-230 stage G brief: expand the KPI measure dictionary before more deck reading

Ticket: T-230 (Shivam 21 Nov 2026). Reviewer: Wolf (Opus). Shivam: grow the KPI dictionary first, so more figures get
the right label when the next decks are read.

Goal: the dictionary in `reality_engine/v2/observations.py` (measure_dict 120 ids, `measure_alias` 18, each with a
node in the T-228 driver tree) labels deck figures. Unmapped labels end as proposals and stay unverified. Expand it
with sector KPI sets, then re-tag the stored rows without any model call.

Evidence: (real; read-only)
- `D:/RealityEngine/t230/obs_91.db`: 102k observations; `measure_proposal` (600 proposals, 21 with a measure);
  unmapped labels such as count.banking_outlets 543, count.atms 229, roe 180, gnpa 169; near-duplicate ids
  (order_book_growth_yoy vs order.book_growth_yoy). Schema `docs/V2_SCHEMA_CONTRACT.md` section 17.
- Old flat deck facts `reality_engine/data/deck_figures.db` table facts(metric, unit, ...): 12.0M facts, 2,225
  companies - a vocabulary source (metric strings and frequency).
- Sector field: `D:/RealityEngine/tg_build/build_list_800_20000cr.csv` column sector; stores' company tables.

Steps:
1. Mine labels: printed_label and proposals from obs_91, metric strings from deck_figures.facts; normalise (case,
   punctuation, units stripped); count by sector.
2. Propose canonical measures for the labels covering >= 90% of label occurrences in obs_91 plus the top 500
   deck_figures metrics: id, name, unit family, stock/flow, driver-tree node, sector set. Sector sets at least:
   banking/NBFC (gnpa, nnpa, pcr, casa, nim, cost_of_funds, aum, disbursement, branches, atms, customers);
   EPC/infra (order_book, order_inflow, bid_pipeline); manufacturing (capacity, utilisation, production and sales
   volume, realisation per unit, ebitda per tonne); pharma (anda filed/approved, launches, r&d share);
   retail/consumer (stores, area, same-store growth, distribution reach); IT (deal tcv, headcount, attrition);
   power/renewables (MW installed / under construction, PLF); real estate (pre-sales, collections, area); generic
   (market share, customers, employees). Every alias must be an observed label (cite its count). No measure without
   a node or an explicit reason for none.
3. Write `.tmp/t230g/dictionary_proposal.csv`, report, and STOP: wait for Wolf's followup. Do not apply yet.
4. On Wolf's go: add entries + aliases to the code tables; `--recheck` a copy of obs_91 into
   `.tmp/t230g/obs_91_g.db` (no model); report verified rows by measure before/after and proposals mapped. Tests for
   alias resolution, and that no previously verified row changes measure without an alias reason.

Files: `reality_engine/v2/observations.py`, `reality_engine/tests/test_observations.py`, `docs/V2_SCHEMA_CONTRACT.md`
(section 17, stage G). No other file; do not edit tasks/STATE.md. Stage F edits observations.py in another worktree:
keep your change to the dictionary tables and the recheck path so the merge stays clean.

Accept: tests pass; typecheck clean; proposal csv, then the recheck report.

Stop if: an alias maps labels with different unit families to one measure; more than 5% of verified rows would
change measure.

Budget: about 2 hours, DeepSeek max effort. No model API calls.
