# Loop 2 worker, fix round: segment names wrongly merged in `xbrl_segments._canonical`

Goal: two different segments of one filing never share a `dimension`, and a misspelt name in one filing does not become the company's name for that segment. Everything else in your branch stays as it is.

Evidence:
- Review of your branch `Eagle-sonnet-l2segments` (2462d5f), on `D:\RealityEngine\pilot10\scratch\w_segments.db`.
- Defect 1, wrong rows: SBILIFE Q2FY27 `segment_revenue` has `dimension='non_participating_pension'` twice, with values 1366330000 and 67017000. "Participating Pension" and "Non Participating Pension" are separate segments of the same filing, and `difflib` ratio on the normalised names is about 0.91, above `NAME_RATIO` 0.85, so `_canonical` merges them. The same risk applies to `participating_life` / `non_participating_life`, and `participating_vip` / `non_participating_vip`. An investor asking for one segment would get another's number.
- Defect 2: INFY `dimension` is `fiancial_services` and `retails` on every quarter, because the latest filing has those typos. Other filings have `Financial Services` and `Retail`.
- Defect 3, small: HINDALCO's standalone `single_segment` rows have `raw_label='NA'` (`DescriptionOfSingleSegment` is 'NA'). Use the existing fallback text "Single segment" when the description is 'NA' or empty.
- Where: `reality_engine/pilot3/xbrl_segments.py`, `_canonical` (input `names_by_file`: list of (sort key, names in that filing)), `single_rows` for the label.
- Wanted rule in `_canonical`:
  1. Names that occur together in any one filing are different segments and are never merged, whatever the ratio.
  2. Among names that do merge (ratio >= `NAME_RATIO` and never together), the canonical spelling is the one in the most filings; a tie goes to the latest filing.
  3. `raw_label` keeps the name as filed.
  Decided, do not reopen: no spell-check dictionary, no company literals.
- Checks: `python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part segments --out D:\RealityEngine\pilot10\scratch\w_segments.db` takes about 1 s and replaces the segment rows. Env as in your first brief: `loop_02_worker_segments.md`. Never write `D:\RealityEngine\pilot10\pilot10.db`.

Files: `reality_engine/pilot3/xbrl_segments.py`, `reality_engine/tests/test_pilot3_xbrl_segments.py` (new tests only), and in `docs/DEVELOPER_GUIDE.md` section O11 and `docs/PILOT3_BLUEPRINT.md` the sentence describing name mapping, if the rule is stated there. Do not touch anything else. You are on the same worktree; commit on the same branch.

Accept:
1. For every company, period, basis and metric on the rebuilt copy, `SELECT symbol, metric, fiscal_period, basis, dimension, count(*) FROM kpi_series WHERE source_type='xbrl_segment' GROUP BY 1,2,3,4,5 HAVING count(*)>1` returns no rows. Print the count.
2. SBILIFE Q2FY27 `segment_revenue` has 14 distinct dimensions, including both `participating_pension` and `non_participating_pension`; print them with values.
3. INFY dimensions: print the list, with how many filings used each spelling. `financial_services` and `retail` are the names if they are the majority; say so if the counts say otherwise.
4. HINDUNILVR still merges `Home care` / `Home Care`, `Beauty & wellbeing` / `Beauty & Wellbeing`, `Personal care` / `Personal Care`, and HINDALCO `(a) Novelis` / `Novelis`: print their dimension lists.
5. New tests: the participating / non-participating case and the typo-majority case. `pytest reality_engine/tests/test_pilot3_xbrl_segments.py -q` passes.
6. A1 on the copy (`answerable`, command in the first brief) is still at or above 601/898, no company lower than your first run; print per company.

Stop if: rule 1 leaves a name unmerged that accept 4 expects merged; report it, do not loosen rule 1.

Budget: first edit within 3 tool calls; 20 tool calls in total; 20 minutes; no paid calls, no network.

No-ticket: night loop 2 fix round; the wrapper assigns the ticket at merge.

Report as in `tasks/worker_context/BRIEF_TEMPLATE.md`, with a `Docs updated:` line.
