# T-214 fix A: shareholding rows lost when shp_index.isin is NULL

Ticket: T-214
Goal: a company whose `shp_index` rows carry a NULL isin still gets its `shp_category` rows in a pilot3 store.
Files: `reality_engine/pilot3/prepare.py` (shp_index spec near lines 68-80, filter `isin IN (...)`), `reality_engine/pilot3/stores.py` (~838, the shp fetch), tests under `reality_engine/tests/test_pilot3_*`. Source DB read-only: `reality_engine/data/equity_intelligence.db` (`shp_index`: 1,654 rows / 78 symbols with NULL isin).
Steps: 1) failing test first: a fixture shp_index with rows (symbol=X, isin NULL) must reach shp_category. 2) Extend the spec so rows match on `isin IN (...) OR (isin IS NULL AND symbol = ?)`; the symbol must be the company's own symbol at that date (no other company's rows). 3) Rebuild only the stores part on a COPY of `D:/RealityEngine/tg_build/measure10/c07/c07.db` (copy into your worktree `.tmp/`, use the c07 profile) and show shp_category goes 0 -> >0. 4) Run `python -m reality_engine.scripts.store_diff` between the original and rebuilt copy of c01 (a store that already has shp rows): 0 rows removed or changed. 5) DEVELOPER_GUIDE line.
Accept: `python -m pytest -q reality_engine/tests -k "shp and pilot3"` passes; c07 copy has shp_category rows; c01 diff shows 0 removed/changed.
Evidence: read-only diagnosis 15 Nov: c07 has 37 shp_index rows, all with promoter_pct, 0 with isin; filter returns 0. PRIVATE: call stores c01/c07 only, no symbol or company name in any repo file.
Pitfalls: `schema.create` DROPS tables: use the part's per-symbol path on a copy only. Never write to D:. Do not backfill `shp_index.isin` in the source DB (separate data job).
Stop if: the same symbol maps to two ISINs in `shp_index` history for any of the 78 symbols (report the list, do not guess).
Budget: 90 minutes.
