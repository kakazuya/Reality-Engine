# T-242 brief: AR gates r4 (entity scope, JV/associate, junk) + deck unlabelled-value gate

Goal: annual-report rows only verify when their entity is backed by the page (JV/associate named, subsidiary/parent named), boilerplate durations and edition ordinals are dropped, and deck values with no printed label tie stay unverified.
Files: reality_engine/v2/observations.py, reality_engine/tests/test_ar_sections.py (or test_observations.py), reality_engine/tests/test_deck_guards.py, docs/DEVELOPER_GUIDE.md, docs/V2_SCHEMA_CONTRACT.md (entity_scope values)
Accept: python -m pytest -q reality_engine/tests/test_observations.py ; python -m pytest -q reality_engine/tests/test_ar_sections.py ; python -m pytest -q reality_engine/tests/test_deck_guards.py ; python -m pytest -q reality_engine/tests/test_results_gates.py  (all pass)
Evidence: C:/RealityEngine/t242/ar_grade_r3/fix.md (grade 45R/8P/5W/2J, every W/J with id, symbol, page, observation_id) and pack C:/RealityEngine/t242/ar_grade_r3/pack.jsonl (rows + page_text). Deck: D:/RealityEngine/t242/grades/decks_wide_ckpt0004_25c4b17f.md W rows 11 and 56, pack C:/RealityEngine/t242/decks_wide_ckpt4/pack.jsonl.
Stop if: a rule changes > 3% of verified rows on the measure copy; any graded-R row of the last passing grades changes status (AR: C:/RealityEngine/t242/ar_grade_r3 R rows; deck: C:/RealityEngine/t242/audit_deck1 + decks_wide_ckpt4 R rows); a rule is per-company.
Budget: ~110 tool calls
Ticket: T-242

## Steps
1. entity_scope gains 'jv' and 'associate'. A row on a page/section headed "joint venture", "associate", "interest in joint venture entities", "share of profit of associates" etc. (page or previous page) gets that scope; never verified unless the JV/associate is named in printed_label or segment. Add unnamed jv/associate to `gate_not_company`'s never-verified set (keep industry/country/peer/customer).
2. entity_scope 'subsidiary' or 'parent' from the model is kept only when the page (or previous page) prints a subsidiary/parent/holding-company name or heading near the figure; otherwise set 'company' and, if the row was verified on that scope, keep it unverified with reason `scope_unbacked: ...`.
3. Junk gate (AR and deck): drop a value that is an ordinal tied to "Annual Report"/"AGM"/"edition"/"years of" celebration, or a tenure echoed from appointment boilerplate ("term of N years", "consecutive term", "for a period of N years") when the measure is not a tenure KPI.
4. Deck: a chart/matrix value whose printed_label, period or series cannot be tied on the page (no label within the same row/series; unlabelled bars; cohort matrix with detached axes) stays unverified (`deck_untied_value`). Deck ckpt-4 W rows 11 and 56 are the examples.
5. Measure on COPIES only (read-only originals): copy C:/RealityEngine/t242/ar_recheck/ar_r3.db and D:/RealityEngine/hy4_out/obs_decks_fy27.db to a scratch dir under your worktree .tmp, run the gates there via recheck_db or a scratch script; report per rule: rows changed, share of verified, graded-R rows changed (must be 0), 20 random changed rows (seed 7) with label/value/page.
6. Tests for each rule (synthetic rows); docs updated.

## Limits
Never write live DBs (D:/RealityEngine/hy4_out, C:/RealityEngine/tg_build) or the t242 originals. Never kill processes by name. pytest per file. Report: file:line changes, measure table, tests, docs.
