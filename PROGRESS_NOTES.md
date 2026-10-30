# WP2a progress — fact view + entity sets

- 2026-10-31: read the context pack, V4_COMMON, §B/§H.2, the atom registry; mapped all 43 held
  atoms onto the actual pilot60 tables (the pack documents the live DBs, not the pilot files).
  Found the design's `metric_state.company_metric_series` lives in `facts_pilot.db` and the
  targeted extraction store is the `metric_state` alias — noted as pack/design drift.
- 2026-10-31: wrote `reality_engine/query/v4/fact_view.sql` (materialised `fact`, 33 branches,
  WITHOUT ROWID key (entity, atom, dims, period_start, period_end)) and `build_membership.py`
  (build driver, coverage, 31-row hand check, timings).
- 2026-10-31: pilot build OK: 7,930,235 fact rows / 31 atoms with rows / 10 atoms with no pilot
  source / 2 branches empty. membership 10,895 rows, 1,888 ISINs, 124 index sets, 2,022 rows
  pit_known=0 (snapshot backcasts truncated to the attested day, never to 2019). sector rows 0
  (left to the §B.6 sector worker).
- 2026-10-31: hand check 31/31 rows match source value and known_at; lookup median 0.05 ms,
  p90 1.56 ms, n=171. `pytest reality_engine/tests/test_v4_fact_view.py -q` → 11 passed.
- Next (controller): install `.tmp/fact_v4_pilot.db` (2.4 GB; ~2 GB is the F&O OI branch) into
  the data root, or rebuild with `python -m reality_engine.query.v4.build_membership`.
- Blocker: none for WP2a. `claim` (WP2b), `own_estimate` (WP2b) and the PIT sector labels (§B.6)
  are other workers' rows in the same table.
