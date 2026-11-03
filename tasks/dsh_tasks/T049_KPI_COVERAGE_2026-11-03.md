Goal: the answer check (`reality_engine/pilot3/answer_check.py`, guide O5) shows `kpi_series` is the biggest hole: 2 matches out of 62 KPI questions. Fix the extractor `reality_engine/pilot3/kpi.py` (and its lexicons in `reality_engine/pilot3/lexicon/`) so that:
1. Recent decks and results reach the table. Bajaj Finance AUM, new loans booked, cost of funds, customer franchise and customers added stop around FY24; Hindalco shipments (kt) and EBITDA per tonne have no FY26 or Q1FY27 rows. Find why the FY25-FY27 investor decks and results presentations in `D:\RealityEngine\pilot3\pages.db` (read-only) are not producing rows: are they read at all (doc types, the `KPI_DOC_TYPES` filter, pages.db documents vs sandbox docs), do the labels match, are table rows parsed. Report per company the decks of FY25-FY27 found vs read vs yielding rows, before and after.
2. Period labels are right. Example: KEC's order book of 36,267 crore at 31 March 2026 is stored as `fiscal_period='FY25'`; it is FY26 (Indian fiscal year ends 31 March: 31 Mar 2026 = FY26 end, Q4FY26). Find the rule that shifts it and fix it for every KPI, with a test on that exact case.
3. Transcript numbers must not be stored as the deck KPI: "1,600 / 2,000 crore" from a call sits next to the deck's order book. Keep call-sourced values as their own rows with a source type the reader can filter, at the lower confidence tier.
Run on a copy only: `copy reality_engine\data\pilot3\pilot3.db .tmp\`, then `python -m reality_engine.pilot3.build --out .tmp\pilot3.db --part extract` and `python -m reality_engine.pilot3.answer_check --db .tmp\pilot3.db --out .tmp\A.xlsx --html .tmp\A.html`. Report the KPI-tool counts before and after (match / partial / mismatch / empty).
No model calls, no network, no AI OCR. Do not write to reality_engine/data or D:\RealityEngine.
Files: reality_engine/pilot3/kpi.py, reality_engine/pilot3/lexicon/*.yaml, reality_engine/tests/test_pilot3_kpi.py, docs/DEVELOPER_GUIDE.md (sections O2 and O4)
Accept: python -m pytest reality_engine/tests/test_pilot3_kpi.py -q
Stop if: the FY25-FY27 decks are not in pages.db at all; report the doc counts by type and year per company instead.
Budget: 160 tool calls.
Ticket: T-049
Report: changed files, test output, the before/after table, the per-company deck table, and `Docs updated: <files>`.
