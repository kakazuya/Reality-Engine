# T-242 r3b progress - DONE

- Reproduced the six r3 graded-R downgrades (ckpt1 pack rows 1, 3, 7, 22, 32, 55) from the baseline rows and the
  stores' `doc_page` text: duration headers the parser missed ("Vear" for year, "year ending on", a garbled annual
  cash-flow title, a header carried from the page before) and cash-flow ADJUSTMENT lines whose `NEW:` id already
  names the line.
- Fixed in `reality_engine/v2/observations.py`: OCR "Vear" -> "year"; "ended|ending (on)"; previous-page header
  carried for an unresolved date (single-duration only); annual cash-flow bare-31-March columns read as years when
  the title names no duration; `_results_cf_is_statement_line` remaps only dictionary P&L/BS measures and plain
  `NEW:` line names.
- Tests: 7 new in `test_results_gates.py` (39 pass); four acceptance files 294 pass (176 observations, 42 AR
  sections, 37 deck guards) with `.tmp/pt_tmp_plugin.py` (sandbox blocks pytest's tmp_path: a child process cannot
  enumerate a directory it creates; the same five tests pass run directly).
- Full `--recheck` of a fresh copy (`.tmp/r3b/after.db`, 1,858 pages, 681 stores): verified 14,171 -> 11,399
  (r3 10,848); `results_period` 8,788 (r3 9,669), `results_duration_filled` 8,269 (7,419), `results_cash_flow`
  1,842 (2,420), `results_scope_reset` 2,961, `results_dropped` 760. Graded-R rows 68: 0 status changes, 14
  attribute fills (8 durations, 6 bases); the six r3 downgrades stay verified; r2 W/J fixes hold.
- Docs: `docs/DEVELOPER_GUIDE.md` (r3b bullet, r3 test counts), `tasks/t242_results_measure.md` (r3b section with
  the 20-random samples per rule), `tasks/STATE.md` (Now + date). Typecheck: no new errors (10 pre-existing in
  untouched code). Commit requested.
