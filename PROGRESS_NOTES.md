# T-057 loop 3 — printed comparative columns (worker notes)

- Done: `reality_engine/pilot3/comparatives.py` (new, part `comparatives`), `lexicon/results_lines.yaml` (new),
  `fin_quarter_printed` in `schema.py` (+ `schema.ensure`, index), `build.py` dispatch/choices/`all`-under-profile,
  `ratios.py` (merged quarters, printed YoY, QoQ formulas, TTM printed, printed FY), MCP `lookups_pilot3.fin`
  fallback + `pilot3_sql` table list + `catalog` description, 13 new tests, 1 new plugin test.
- Verified on `D:\RealityEngine\pilot10\scratch\w_cmp.db` (backup of `l3_base.db`): 5,587 rows / 10 companies,
  12/12 expected cells, A1 680/898 (baseline 651), pe days up for 6 companies, guards pass, checkpages 145.
- Docs: PILOT3_BLUEPRINT 9b + schema row, DEVELOPER_GUIDE O10 loop-3 bullet, STATE.md.
- Next: controller merge review; extend `fin_quarter_xbrl`'s window if the 90% checked target matters.
