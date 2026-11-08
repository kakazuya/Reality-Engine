# T-122: a frozen, hand-labelled regression set so a fix for one company never breaks another

Ticket: T-122

Goal: every change to an extractor (`kpi.py`, `guidance.py`, `stores.py`) or to the checker (`row_checks.py`) is
re-scored against every row Opus has ever hand-read, across all companies seen so far, before it merges. A row Opus
read as right must never become quarantined; a row Opus read as wrong must never become verified. Shivam, 8 Nov: "we
fix one company, the other breaks by the same rule; we must catch the tail".

Files (only these): new `reality_engine/pilot3/regression_set.py`, new `tasks/regression/labels.csv` (the frozen set),
new `reality_engine/tests/test_regression_set.py`, `docs/DB_BUILD_GUIDELINES.md` (short section: how to run it, when
it is required), `docs/DEVELOPER_GUIDE.md` (one line).

Evidence (Opus's hand reads, 7-8 Nov; notes and samples, read-only):
- Scratch root `C:/Users/warri/AppData/Local/Temp/claude/12b5f02fd3b7ce95/fa93aa0b-0c04-408d-a8f4-f7630af29fed/scratchpad/`:
  - `ho/opus_read_u6_kpi.md`, `ho/opus_read_u6_kpi_r6.md` (unseen6 reads; db `ho/u6_eval.db`, earlier `ho/unseen6.db`),
  - `ho/opus_read_h6.md` (hold6; db `ho/h6_eval.db`; sample TSVs `ho/h6_report/row_checks_sample.tsv`),
  - `fresh6/opus_read_f6.md` (fresh6; db `fresh6/fresh6.db`; sample `fresh6/rep/row_checks_sample.tsv`),
  - `p10_r9/row_checks_sample.tsv` (pilot10, 30 rows, all right; db `D:/RealityEngine/pilot10/pilot10.db`).
  Each note lists the wrong and partly ids; every other id in the matching sample TSV was read as right.
  The fresh6 note's round-10 addendum: all 22 verified rows after round 10 read 20 right, 2 partly (412 standalone PAT
  with basis not_stated, 1015 'just shy of 30%').
- Row ids change on every rebuild, so a label must key on content, not id: (symbol, metric, dimension, fiscal_period,
  basis, rounded value, unit, doc sha or doc_key, page, first 80 chars of the squashed quote).
- The checker is `python -m reality_engine.pilot3.row_checks --db <db> --out <rc.db> --profile <profile> --tables
  kpi_series,guidance`; profiles: `ho/unseen6_profile.json`, `ho/hold6_profile.json`, `fresh6/fresh6_profile.json`,
  `tasks/night_loop/pilot10_profile.json`.

Steps:
1. Build `labels.csv` from the notes and sample TSVs: one row per hand-read row with the content key, the company set
   (pilot10 / unseen6 / hold6 / fresh6), Opus's label (right / partly / wrong) and the note's reason. Expect about
   250-300 rows. Never invent a label: a sample row not covered by a note is skipped and counted.
2. `regression_set.py score --label tasks/regression/labels.csv --set <name> --db <db> --rc <rc.db>`: finds each
   labelled row in the db by its content key (report rows not found: an extractor change that drops a right row is
   itself a regression), joins its verdict, and prints: right rows now quarantined (FAIL), wrong rows now verified
   (FAIL), partly rows now verified (WARN), not found (WARN), plus counts per company. `score --all` runs the four sets.
   Exit code 1 on any FAIL.
3. Tests on tiny fixtures: key matching survives an id change, a right row quarantined fails, a wrong row verified
   fails, a dropped row is reported.
4. Run `score --all` on today's main and report the table (this is the baseline; it may already show FAILs from
   earlier rounds: list them, do not fix the checker here).
5. Docs: the rule "every extractor or checker change runs `regression_set.py score --all` and shows zero FAIL before
   merge; a new hand read appends to labels.csv". Final answer starts with `Docs updated:`.

Accept: tests pass; `score --all` runs on all four sets and prints the baseline.
Limits: read-only on every database; outputs under `.tmp/`; no model calls; pytest `tmp_path` is unusable in the
sandbox (shadow it with a `.tmp` fixture); the controller applies your diff.
Budget: 100 tool calls, 2 hours.
Stop if: a note's ids cannot be matched to its sample TSV or db: report which and stop.
