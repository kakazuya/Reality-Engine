# T-242: deck gates r8b - segment_unstated must not fire on financial-statement line items (agy Hydrogen high, 26 Nov 2026, Eagle)

Ticket: T-242

Goal: the r7+r8 recheck copy C:/RealityEngine/t242/deck_recheck_r8/decks_r8.db cannot be swapped in. It loses 8 of
the 52 rows graded R in C:/RealityEngine/t242/audit_deck1 (pack.jsonl + grades.csv):
- 7 R rows go unverified with `segment_unstated: subset figure lacks a readable qualifier` (ids 22, 27, 28, 36, 39,
  40, 45: Deferred Tax Liabilities, Non-current assets, Current Assets, Intangible assets under development);
- id 16 (AARVI) has entity_scope changed from company to subsidiary.

Across the copy, segment_unstated downgrades 4,965 of the 68,513 rows verified in the live
D:/RealityEngine/hy4_out/obs_decks_fy27.db (7.2%). Most are standard statement lines. Top labels: equity share capital
160, revenue from operations 150, current assets 147, non-current assets 106, deferred tax liabilities (net) 104, share
capital 93, profit before tax 88. Fix the rule structurally so statement lines are never treated as subsets. Keep
every case r8 was written for (its tests in reality_engine/tests/test_deck_guards.py).

Files: reality_engine/v2/observations.py (`_deck_segment_update`, `_deck_broader_total`, and the r7
`_deck_scope_update` for id 16), reality_engine/tests/test_deck_guards.py, docs/DEVELOPER_GUIDE.md (deck gates entry).

Evidence:
- r8 code is observations.py around line 6700, `_deck_segment_update`;
- the 9 rows above, with live vs r8 status, are reproducible by observation_id from audit_deck1/pack.jsonl;
- the page text for each row is in the store DB doc_page (C:/RealityEngine/tg_build/universe_fy27/<store>/<store>.db,
  read-only).

Steps:
1. A row is a financial-statement line item, never a subset, when either:
   - its printed_label (or measure) is a standard statement line (balance sheet, P&L or cash-flow line: share capital,
     equity share capital, current/non-current assets/liabilities, deferred tax assets/liabilities, borrowings, lease
     liabilities, intangible assets (under development), revenue from operations, other income, total income,
     PBT/PAT, EBITDA, interest income, fee-based income, treasury income, operating expenses, ...);
   - or the page is a statement table (statement heading or `_DECK_STMT_BLOCK_RE` in the 45 lines above).

   Prefer the existing measure dictionary or canonical measures over a new word list where possible. For such rows a
   section total ("Total Assets", "Total Equity and Liabilities") is NOT a broader total of the row. Skip the
   segment_unstated downgrade.
2. id 16: find why r7 changed AARVI's scope company->subsidiary. A subsidiary must be a different named entity
   heading, not the company's own name or a group word. Fix it structurally.
3. Tests: each of the 9 evidence shapes stays verified with its live fields (quote the page lines), plus r8's own
   tests still pass. Add a counter-test: a product/region split row beside a printed slide total still goes
   segment_unstated.
4. Measure on a NEW copy only: `--recheck` a fresh copy of the live obs_decks_fy27.db into
   C:/RealityEngine/t242/deck_recheck_r8b/decks_r8b.db (never write D:/RealityEngine/hy4_out). Report:
   - graded R rows changed in audit_deck1 (target 0) and in deckfy27_surprise1 (grades in
     D:/RealityEngine/t242/grades/deckfy27_surprise1_6428abac.md);
   - verified -> not counts by reason, vs live;
   - the segment_unstated count and 20 random rows it still downgrades (seed 7), quoted.

Accept: tests pass (per file); 0 graded R rows changed in audit_deck1; segment_unstated downgrades at most 1.5% of live
verified rows; every r8 test still passes.
Stop if: a graded R row still changes after two attempts, or segment_unstated stays above 3%.
Budget: about 2 hours. Write scope: your worktree plus C:/RealityEngine/t242/deck_recheck_r8b/ only.
