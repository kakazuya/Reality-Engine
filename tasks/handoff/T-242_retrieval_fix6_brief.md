# T-242 brief: retrieval fix 6 (audit 6 causes C1-C3, the one W, call-date display)

Goal: the reality-data lookups stop hiding held guidance, resolve "profit after tax" and printed period labels in every store, rank the asked sentence first inside a named call, and show the printed call date on each statement row.
Files: plugins/reality-data/server/lookups_pilot3.py, plugins/reality-data/server/server.py (tool descriptions only if behaviour changes), plugins/reality-data/tests/test_retrieval_fix6.py (new), docs/DEVELOPER_GUIDE.md, machines/MSI_LAPTOP.md
Accept: python -m pytest -q plugins/reality-data/tests/test_retrieval_fix6.py plugins/reality-data/tests/test_retrieval_fix5.py plugins/reality-data/tests/test_retrieval_fix4.py plugins/reality-data/tests/test_retrieval_fix3.py plugins/reality-data/tests/test_retrieval_fix2.py plugins/reality-data/tests/test_lookups_pilot3.py passes; replay of the 12 non-R audit-6 rows (list below, stores pinned, mode=ro) turns >= 8 into R with 0 audit-6 R rows lost (replay all 48).
Evidence: C:/RealityEngine/t242/retrieval_audit6/report.md (48 rows with exact calls, stores c346 c75 c317 c12 c347 c1718 c783 c500 under C:/RealityEngine/tg_build/universe_fy27/).
Stop if: a change needs a store schema change or a rebuild; any fix would be per-company; replay loses an R row and you cannot fix it in 2 tries.
Budget: ~120 tool calls.
Ticket: T-242

## Causes (from audit 6, each re-checked in page text by the auditor)
C1 guidance held but invisible (rows 45, 46, 47): `guidance()` returns found=false when the only rows are quarantined (CHOLAFIN `opex_to_nti FY27 3.0-3.1%` p12, ARVINDFASN `revenue_growth FY27`), and never reads `obs_fact` guidance (ICICIGI motor loss ratio 65-67% p15, record_type guidance, guidance table empty).
Fix: (a) when no served row matches, return the quarantined matches as a labelled `held_quarantined` block (same pattern as the fact path's `_fact_held_quarantined`), never as the answer; (b) fall back to verified/unverified `obs_fact` rows with record_type='guidance' (labelled `source: obs_fact`) when the guidance table has no match.

C2 metric/period resolution (rows 7, 20): CHOLAFIN `fact("profit after tax","Q2 FY27")` -> found=false, names_matched [] while `fact("PAT", ...)` -> 1,630.34 cr. ARDEE `fact("installed capacity","As on 30th Sept, 2026")` -> found=false; without period -> 156,950 MTPA.
Fix: one alias map used by every route of `fact` (profit after tax <-> PAT <-> net profit; find where 5PAISA resolves it and why CHOLAFIN does not); parse printed as-on period labels ("As on 30th Sept, 2026", "as at 30 June 2026", "30.09.2026") to a date and match point-in-time rows by that date.

C3 same-call ranking (rows 28, 33, 34, 35, 39; mean rank 4.6, worst 10): inside a named call the asked sentence is present but not first. Example ICICIGI 2026-10-14 `statements("industry growth")` -> asked "growth of industry ... 26.9% vs 16.0%" at rank 10 of 25.
Fix: primary sort = sentence contains ALL ask words (topic/terms/rank_terms tokens, stemmed lightly), then count of ask words in the sentence (not the whole answer turn), then existing order. Keep fix-3 exact mode and the 25-row/<19 kB window.

W (row 11): 5PAISA `fact("profit after tax","Q4 FY26")` served 44.3 cr (FY26 total, obs_fact transcript p4 mis-tagged Q4) with no alternative; press release prints Q4FY26 PAT 10.8 cr. Fix structurally: when an obs_fact number from a transcript and a filed results/press-release value for the same measure+period differ by > 20%, serve the filed value first and list the transcript one as an alternative with `conflict: true` (calls are unverified until a filing matches within 1%: Shivam's 24 Nov ruling).

Display: each named-call statement row shows `call_date` = the filing date (AEGISVOPAK 2026-11-03 call shows 2026-11-10). Add `call_date_printed` (transcript_statement.call_date for that doc) beside `filed` so a model quotes the right date.

## Limits / pitfalls
- Read stores only (mode=ro). No model calls. Do not touch hy4 readers, D:/RealityEngine/hy4_out or the stores.
- Never kill processes by name. pytest per file.
- Tests use small synthetic sqlite stores like test_retrieval_fix5.py does.
- Report: changed file:line, test output, replay table (48 rows before/after grade), docs updated.
