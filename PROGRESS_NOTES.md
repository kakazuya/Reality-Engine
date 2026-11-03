# T-051 progress

- Done: `gap_loop/loop.py` `bank_questions` + `accept_answers` rejects a qid that is neither a unit question nor in the company bank (invalid map, nothing stored); test in `test_gap_loop.py`.
- Done: `pilot3/ratios.py` F_NIM (`nim_pct`, lenders) annualised NII over the average opening/closing loan book, is_derived=1, input_refs filled; fixture tests for NIM, BVPS/ROCE FY25+FY26, shp old-ISIN copy and category mapping in `test_pilot3_core.py`.
- Verified: `python -m pytest reality_engine/tests/test_gap_loop.py reality_engine/tests/test_pilot3_core.py -q` -> 57 passed, 3 errors (all 3 use pytest `tmp_path`; the sandbox's `pytest-of-SYSTEM` temp dir is ACL-denied, pre-existing, not code).
- Data checked (read-only): shp_category promoter/public 23/20/22 quarters, MF/FPI 11/9/11, old ISINs present; BVPS FY25+FY26 all three, ROCE KEC+HINDALCO only (lender has no EBIT); kpi_series aum newest known_at 2024-01-29 (stale), so NIM uses fin_annual_line.loans (FY25/FY26/H1FY26 present).
- Next: rebuild `.tmp/pilot3.db` to prove nim_pct rows, then the one-query-per-item report; docs (DEVELOPER_GUIDE N+O, STATE) are edited.
- Blockers: none; the real `reality_engine/data/pilot3/pilot3.db` rebuild (`--part ratios`) and the `HINDALCO029b` delete in `D:\RealityEngine` are the controller's.
