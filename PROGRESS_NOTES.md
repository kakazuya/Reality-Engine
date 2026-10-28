# Progress notes — T2 pilot chunk store

- 2026-10-28 21:45 IST — chunker_v3 fixes landed: `_split_long` extends to the next sentence
  end within +15% of MAX_CHARS and marks continuations (`note_cont`, `(cont.)` in section/header);
  `forward_looking` now needs a forward verb **and** a future/target anchor; tag rules tightened
  (LODR boilerplate, retirement benefits, land acquired, pricing power, prose "notes").
  `test_chunker_v3` 26 tests OK, `test_chunker_v2` 14 OK.
- 2026-10-28 21:46 IST — next: full pilot build (`.tmp/pilot/chunks_v3_pilot.db`) from the D:
  originals, then the 50-chunk hand check, coverage report and the bench before/after.
  Blockers: none. (DSH_WORKER_PROGRESS_NOTES was empty in this session; notes kept in the
  worktree root.)
- 2026-10-28 22:20 IST — pilot DB built: 690 docs / 37,705 chunks (AR 24,205, concall 8,295,
  deck 5,080, announcement 125); known_at 20/20 match against the filing records.
- 2026-10-28 22:45 IST — boundary fixes (date/table-cell headings, sentence-end extension) and
  tag fixes (exchange-rate USD, award ceremony, resignation clause, safe-harbour risk,
  opening-remarks speaker role). 50-chunk hand check: boundary 50/50, tags 133/133.
- 2026-10-28 23:05 IST — EVIDENCE planner now reads chunks_v3 (FTS-first, filters pushed into
  SQL); measured 50 ms company query, 147 ms with tag+doc_type. Bench before: 59 pilot cases,
  1 ANSWERED / 44 PARTIAL / 11 BLOCKED_SCHEMA / 3 BLOCKED_TOOL, EVIDENCE p50 1.63 s p95 4.34 s.
  Next: final rebuild (mixed known_at check), bench after, REPORT.md.
- 2026-10-28 23:45 IST — final store: 784 docs / 38,762 chunks (AR 24,205; concall 8,295;
  deck 5,080; announcement 1,182), 190 MB. BSE material announcements now join their filing
  record by attachment UUID, NSE rows keep the canonical pilot ISIN. Independent known_at
  check 20/20 across all four types.
- 2026-10-29 00:05 IST — final hand check: boundary 49/50 (LB 0.895, one table-header cut),
  tags 144/145 (LB 0.962, one OCR "12% August" percent). Bench after: 2 ANSWERED / 42 PARTIAL
  / 12 BLOCKED_SCHEMA / 3 BLOCKED_TOOL; EVIDENCE p50 0.022 s, p95 1.144 s. REPORT.md written;
  test_chunker_v3 37 tests pass. Done.
