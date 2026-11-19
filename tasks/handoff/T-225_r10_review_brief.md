# T-225 round 10 review brief (read-only reviewer, DeepSeek)

Ticket: T-225
Goal: adversarially review checker round 10 on branch Eagle-t225-r10 (commits 07eb9e7d, 1e0b0785, 29eb64bd; diff vs main:
`git diff main...Eagle-t225-r10 -- reality_engine/v2/reference_geom.py reality_engine/v2/truth_score.py`). The checker
(`settle_page`) may mark a reader's cell verified ONLY when the printed page puts that value on that row AND under that
column. A wrong cell verified is the worst defect; a right cell lost is the second.
Files: reality_engine/v2/reference_geom.py (new: `_period_atoms`, `_overridden`, `_atom_key`, `_unfinished`,
`_full_dates`, `decimal_split`, `Page._headed`, `Page._stack_columns`, `Page._over`, `Page._leaf_rows`, `Page._aligned`, changes in
`_band_state`), reality_engine/v2/truth_score.py (`_keep_last_blank`), tests in
reality_engine/tests/test_v2_reference_geom.py (last 6 tests) and test_v2_truth_score.py (last test). Rules explained in
docs/V2_SCHEMA_CONTRACT.md, paragraph starting "Round 10 (19 Nov, Eagle; the column model)".
Evidence (Eagle's measurements): wrong cells verified on the 30 hand-read truth pages 9 -> 0; dev half unchanged;
frozen Dots 464 -> 459; 60 dev reference pages 2,139 -> 2,077. Score commands (run from the repo root, PYTHONPATH=.):
  python -m reality_engine.v2.truth_score --truth D:/RealityEngine/t225_split/dev/truth --pdf-pages D:/RealityEngine/v2/reference_pages_frozen2/pdf_pages --runs D:/RealityEngine/v2/reference_pages_frozen2/run_dots_imggrid D:/RealityEngine/v2/reference_pages_frozen2/run_hy4_imggrid --ocr-words D:/RealityEngine/v2/reference_pages_frozen2/ocr_textrec --out <your .tmp csv>
  Do NOT score or open D:/RealityEngine/t225_split/frozen (the frozen half is never used to drive fixes).
  The 60 unlabelled dev pages: D:/RealityEngine/v2/reference_pages/{pdf_pages,ocr_words,run_dots_imggrid}.
Steps:
1. Read the diff and the doc paragraph. For each of rules (1)-(6) write the precondition under which it can VERIFY a
   wrong cell or REFUSE a right one; build a minimal synthetic word layout (see the `_w` helper in the test file) that
   triggers it, and run it. Especially: `_leaf_rows` mis-detecting a group label as a leaf row (a group label printed
   over exactly one column, e.g. two-column groups "Standalone | Consolidated" with leaf rows under each); `_overridden`
   dropping a true year (a stack whose lowest phrase names a different year kind on purpose, e.g. "FY26" group over
   "Q1 FY25 restated"?); `_full_dates` misparsing ("30.09.2025" vs "30,09.2025", two-digit years, "Mar-25", "31st
   March 2025", "1.4.2024 to 31.3.2025" ranges); the duplicate-stack `blocked` rule with an empty or generic stack; `decimal_split` on a legitimate page (".5" printed alone).
2. Run the existing tests: python -m pytest reality_engine/tests/test_v2_reference_geom.py reality_engine/tests/test_v2_truth_score.py -q
3. Report each finding as: rule, minimal layout (code), observed vs expected, severity (wrong-verified / right-lost).
Accept: a findings list (may be empty) with a runnable reproduction for each finding; no code changes.
Stop if: 60 minutes pass, or you have 6 confirmed findings.
Budget: 60 minutes, read-only; scratch files only under your .tmp.
Pitfalls: `python -m` puts the repo root first on sys.path, so always run from the checkout you mean to test (check out
the branch in your workspace, or `git worktree add` it under .tmp). Never edit reference_geom.py.
