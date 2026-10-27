# Progress — BSE wide concall candidates (2026-10-28)

- 22:06 — `--widen` mode added to `reality_engine/scripts/concall_refetch.py` + 12 offline tests. Dry run green:
  5,139 widened candidates (Analyst/Investor Meet 4,268, General 529, Investor Presentation 332,
  Press Release 10); overlap with the 9,390 by (ISIN, quarter) = 2,838, by attachment = 0, fresh = 2,301;
  recall on the pilot's 1,771 = 1,589 (89.7%; 94.2% of the 1,686 in the four subcategories);
  precision 34/40 = 85.0% on 40 staged PDFs. Report: `tasks/concall_refetch/report_widen.md`.
- Tests: `python -m unittest reality_engine.tests.test_concall_refetch` -> 52 passed.
- Next/blockers: no network used, widened fetch NOT run (waits for the 9,390 job). DSH sandbox denies
  writes inside Python-created subdirectories, so the 3 pre-existing `TemporaryDirectory` tests were moved
  to flat `.tmp` files; two empty stray dirs (`tmppbo2tmyc/`, `reality_engine/tests/tmpyxmjwj8a/`) cannot be
  deleted (access denied) and only cause a `git status` warning.
- Note: `DSH_WORKER_PROGRESS_NOTES` is unset in this session, so this file lives at the worktree root.
