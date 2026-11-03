Goal: `reality_engine/pilot3/answer_check.py` (guide O5) classes 111 of 300 questions as `mismatch`, mostly because the loop's `numbers[]` are the inputs of a derived answer (revenue growth cites two revenues) while the lookup returns the ratio. Make the check grade the answer, not the inputs:
1. For a question whose oracle answer is derived (growth, share, margin, ratio, difference, sum, CAGR; detect from the oracle row's method / formula fields and the question text), compute the derived value from the oracle's inputs and compare it with the derived value the lookup returns (`pilot3_ratio`, `queries.kpi_growth` / `kpi_share` / `kpi_mix` / `kpi_fy_sum`, see `pilot3/queries.py`); if the lookup returns the inputs instead, compute the derived value from them. Class `match` when the derived values agree within the `gap_loop/checks.py` tolerance, plus a new column `compared_on` = `derived` or `cited`.
2. Keep the old cited-number comparison as a second column so nothing is hidden; never loosen the tolerance.
3. Topic tags: `pilot3_statements(topic="price")` returns nothing because the tagger emits no `price` topic; map the question to `terms` instead when the topic is not in the tagger's list (read `pilot3/lexicon/topics.yaml`).
4. HINDALCO085 ("4 trading sessions after its Q1 FY27 results"): resolve the results date from `pilot3_docs` (results filing `known_at`), then the price rule.
Tests: extend `reality_engine/tests/test_pilot3_answer_check.py` (a growth question whose oracle cites two revenues and whose lookup returns the growth %; a share question; the topic fallback; the results-date rule).
Run on a copy only (`.tmp\pilot3.db` copied from `reality_engine\data\pilot3\pilot3.db`, reports under `.tmp\`) and report the class counts before and after, per company.
Docs: guide O5 (class meanings, `compared_on`).
Files: reality_engine/pilot3/answer_check.py, reality_engine/tests/test_pilot3_answer_check.py, docs/DEVELOPER_GUIDE.md
Accept: python -m pytest reality_engine/tests/test_pilot3_answer_check.py -q
Stop if: the oracle rows carry no method or formula field to tell derived answers apart and the question text is ambiguous for more than 30 rows; report 10 examples.
Budget: 140 tool calls.
Ticket: T-049
Report: changed files, test output, before/after counts, 5 examples that moved from mismatch to match with both values, and `Docs updated: <files>`.
