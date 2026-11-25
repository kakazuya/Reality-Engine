# T-242 brief: retrieval fix 7b - win back the one lost R (BMW operations tie) with zero R lost

Goal: on top of fix 7 (branch dsh/20261125T204732Z-bbfe7d15, head 518e7df2), audit-7 row #26 (BMW, named-call statement "operations") is rank 1 again while every other audit-6 and audit-7 R row stays R.
Files: plugins/reality-data/server/lookups_pilot3.py, plugins/reality-data/tests/test_retrieval_fix7.py, docs/DEVELOPER_GUIDE.md
Accept: python -m pytest -q plugins/reality-data/tests/test_retrieval_fix7.py plugins/reality-data/tests/test_retrieval_fix6.py plugins/reality-data/tests/test_retrieval_fix5.py plugins/reality-data/tests/test_retrieval_fix4.py plugins/reality-data/tests/test_retrieval_fix3.py plugins/reality-data/tests/test_retrieval_fix2.py plugins/reality-data/tests/test_lookups_pilot3.py passes; replay of BOTH audits (96 rows): audit 7 >= 38 R (37 + #26), audit 6 >= 45 R, 0 R lost against the fix-6 baseline.
Evidence: fix-7 report (dsh 20261125T204732Z-bbfe7d15 result.md): #26 BMW is a score tie between "the facility has yet to commence full operations" and "first quarter of operations ... full capacity", resolved by evidence order; length/density tie-breaks broke 2-6 other R rows. Reports C:/RealityEngine/t242/retrieval_audit6/report.md and retrieval_audit7/report.md; replay script in that worktree .tmp/replay.py (copy it).
Stop if: no STRUCTURAL tie-break (e.g. prefer the sentence where the ask word is the grammatical head / closest to a figure or date / in management's answer over the analyst's question) wins #26 without losing another R within ~40 tool calls. Then stop and report the best candidate and what it breaks - do not force it.
Budget: ~50 tool calls
Ticket: T-242

## Limits
Start from the fix-7 branch (base given at launch). Stores read-only (mode=ro), no model calls, no per-company rule, pytest per file, never kill processes by name.
