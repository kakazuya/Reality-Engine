# Three tests from the Fable review (design, 10 Nov 2026)

Owner: Eagle (Fable 5.2). Status: DESIGN, waiting for Shivam's OK to run. Nothing here has been run.
Source: Fable's review of `docs/FABLE_REVIEW_BRIEF.md` (section 10 there) and Shivam's replies the same night.
Tickets: T-177 (reference pages + completeness report), T-178 (first-build re-key test), T-179 (raw SQL test),
T-180 (free-model transcription test).

Each test states a hypothesis, what would prove it wrong, and the decision that follows. No test result is
reported from a worker's own grade.

## Pending, in order (written 11 Nov 2026, after T-179 and the 60-page run)

Done so far: review written (brief section 10); T-179 first look (null result, below); T-177 tool merged and the 60
pages transcribed by three free readers. Nothing is running. Each item names who does it and what closes it.

| # | Ticket | What | Who | Model calls | Closes when |
|---|---|---|---|---|---|
| 1 | T-177 | Reconcile by value and column position, not label text (two readers agree on only 24% of cells because row labels differ); re-run on the saved outputs of all three readers, majority of three settles a cell | Eagle, script | none | agreed share reported per page; cells settled by script counted |
| 2 | T-177 | Read the disputes and the 6 pages with no reconciled cell by hand; Shivam spot-checks 6 pages; write `reference_cells.csv` with `settled_by` | Eagle in session + Shivam | none | 30 dev + 30 frozen pages have settled cells; frozen copy under `frozen/` |
| 3 | T-177 | Completeness report `reality_engine/v2/completeness.py` (number coverage, grid check, arithmetic closure, cross-source, unread pages) with a build gate, scored against the reference pages | DeepSeek code worker (Beam dies near 192k input tokens), separate grader | none | runs on u8 in under 10 minutes; calibration table in this file |
| 4 | T-178 | First-build re-key: script cells r10 vs `deck_figures`/`ar_facts` facts as stored vs verified + label map + period engine vs union, on the reference pages; fiscal-year error rate on 200 annual reports | Eagle, script | none | four-arm table on dev and frozen pages; salvage decision recorded |
| 5 | T-180 | Reader bake-off on the reference pages: recall, precision before and after the script check, run-to-run agreement, seconds per page, for Dots, Nemotron Super VL, Nemotron Ultra, Nemotron Nano Omni (text; Dots also image) against the r10 script. The 60-page outputs already held are run 1; one more run gives consistency | Eagle, script | free Kilo only | one row per reader; decision: model-in-build for tables, or scripts with the completeness gate |
| 6 | T-179 | Formatted answer report (xlsx + csv) from `D:/RealityEngine/t179/` with `answer_run_report --call-log` | Eagle, script | none | files in `D:/RealityEngine/reports/` |
| 7 | new | Answer-path test 2: one answer-ready fact lookup (preferred value, period, basis, unit, source in one reply) against today's tools; same 60 questions, two runs per arm; stricter grader brief (lists each figure it re-looked-up) | DeepSeek worker builds the lookup; DeepSeek answers; graders | DeepSeek, off-peak | right, lookups and seconds per answer per arm against the same-arm noise |
| 8 | new | Document-integrity gate before extraction: one-page link-notice transcripts, sha256 duplicates, misdated calls (latest year in text more than a year before filing), mistyped documents; report per store, then a build gate | DeepSeek code worker, separate grader | none | counts per store for u8, q12, p20; gate refuses a store with new defects |
| 9 | T-163, T-132 | Segments r8 and table cells r13: held until item 5 decides | - | - | decision of item 5 |
| 10 | STATE items | Rebuild p20/u8/q12 so T-161..T-166 go live; CHOLAFIN KPI branch comparison; s10 store, frozen split (T-172) and timed baseline (T-170); `extract_deck_figures.py` still lists Step 5 entries and a paid default second reader | as in `tasks/STATE.md` | - | - |

Order rule: 1 -> 2 -> 4 and 5 (both need settled reference cells); 3, 6, 8 are independent and can run alongside;
7 needs DeepSeek off-peak (not 06:30-09:30 or 11:30-15:30 IST on weekdays).

Standing limits learned on 10-11 Nov: Beam workers end at about 192k input tokens, so Beam is for short jobs only;
LongCat 2.5 and Step 5 do not answer on OpenCode Go; free readers that work are on Kilo (Dots, Nemotron family);
the DeepSeek grader is lenient against Opus (28 of 50 Opus-not-right answers called right).

## 0. What the first build is (inspected 10 Nov, read-only)

| Store | Holds | Measured |
|---|---|---|
| `reality_engine/data/ar_facts.db` (21.9 GB) | model-read annual reports: `ar_facts` (item, value, unit, period, basis, page, quote, model) | 33,268 reports done, 4,898 companies, 5.02 M pages, FY19-FY26; ~33 M facts; random sample of 19,609 facts: 81% value found on the cited page, 17% prose, 0.3% not found; 99.6% carry a quote |
| `reality_engine/data/deck_figures.db` (10.6 GB) | vision-model-read decks: `facts` (metric, period, raw_number, value, unit), `pages` (text_numbers, primary_recall), `outputs` (raw model output) | 26,511 decks, 2,225 companies, 627,251 pages, 11.8 M facts, Jan 2021 - Sep 2026; pages with >= 10 numbers: 146,204 at recall >= 0.9, 90,635 at 0.7-0.9, 53,388 at 0.4-0.7, 41,278 below 0.4 |
| `reality_engine/data/concall_facts.db` (0.8 GB) | model-read calls: `cc_items` in 12 lists (key_numbers, guidance, capex, ...), `cc_item_checks` | 7,504 calls, 1,264 companies, 720,692 items; value found in its quote on 259,398 of 646,563 checked items |

Why it answered poorly (one Infosys report read in full, 2,559 facts; a hypothesis until T-178 measures it):
the values are mostly right, but nothing is keyed. 2,071 distinct item names, 304 categories, 66 unit spellings and
40 period spellings in one report; 94% of reports take their fiscal year from a filing-month rule (the sampled
"2026" report holds FY22 figures); the same year appears three times for one company. A question could only reach
a fact by fuzzy text search over 33 M rows. The pieces built since then (label map, period engine, preferred
figure, document identity, `known_at`) are exactly what it lacked.

Not salvageable as facts under the 7 Nov ruling: `cc_items.signal`, `direction`, `firmness`, `statement` and
`deck_figures.chart_trends` are model interpretation. Their verbatim `quote` is usable where the script finds it in
the page text.

## 1. T-177: reference pages and the completeness report (shared by all three tests)

**Why first:** every test below needs ground truth for a whole page (what the page prints), not a sample of what an
extractor chose to output. The existing samples (`D:/RealityEngine/v2/review/samples/f*_*.csv`) measure precision
only; they cannot see a dropped column.

- **Pages:** 60, drawn by script with a fixed seed from p20, u8 and q12 documents (pilot10 excluded: it is the
  tuning set). 30 deck pages (preferring decks whose sha256 is in `deck_figures.pages`), 20 results pages, 10
  annual-report pages. Strata: ruled table, unruled deck panel, two-level header, multi-period fact sheet, numbers
  in words or scale words, chart-only page.
- **Split:** 30 dev pages (workers may see them), 30 frozen pages (only the scoring script and the reviewer read
  them; stored outside the repo at `D:/RealityEngine/v2/reference_pages/frozen/`).
- **How the truth is made:** two different free models each transcribe the page into a grid (row label, column
  header, value as printed, unit). A script accepts a cell when both agree, the value is verbatim in the text layer
  and printed totals recompute. Disagreements and chart pages are read by Claude in session; Shivam spot-checks 6
  pages. Every reference cell carries who settled it.
- **Completeness report** (`reality_engine/v2/completeness.py`, new; one row per page in a `page_coverage` table):
  1. number coverage: printed value-numbers that reached a stored cell (number words and scale words converted;
     dates, page numbers, note references excluded);
  2. grid check: printed rows x columns against stored cells;
  3. arithmetic closure: stored parts add up to the printed total;
  4. cross-source agreement: the same figure in XBRL and in the deck;
  5. unread pages: no text layer or chart-only, counted as not read.
- **Gate:** a build is refused when any page's coverage falls against the previous build.
- **Calibration:** each automatic check is scored against the 60 reference pages (how often it flags a page that is
  truly incomplete, and how often it misses one).
- **Accept:** reference set written with the split; `completeness` runs on u8 in under 10 minutes; calibration
  table in the report.

**Tool built (11 Nov 2026, T-177 round 3):** sample/transcribe/reconcile in
`reality_engine/v2/reference_pages.py`, test `reality_engine/tests/test_v2_reference_pages.py` (3 passed in 0.43 s),
commands and file columns in `docs/V2_SCHEMA_CONTRACT.md` section 12. `sample` writes the 60 pages (30 deck / 20
results / 10 annual report, 30 dev / 30 frozen) deterministically: two runs of seed 20261110 gave byte-identical
`pages.csv` (60 rows, SHA-256 `BEED9B07D7274D24...`, 36.8 s / 40.2 s). Live check on the 8 dev pages actually used
(4 deck, 2 results, 2 annual report; free readers only, no paid call):

| Reader (free) | Input | Pages with rows | Rows | Verbatim share | Mean s/page | Errors |
|---|---|---|---|---|---|---|
| `dots-studio/dots-3-note-preview:free` | text | 8/8 | 233 | 0.987 | 15.5 | 0 |
| `dots-studio/dots-3-note-preview:free` | image | 8/8 | 225 | 0.956 | 15.9 | 0 |
| `nvidia/nemotron-3.5-super-vl:free` | text | 8/8 | 228 | 0.987 | 11.6 | 0 |
| `nvidia/nemotron-3.5-super-vl:free` | image | 6/8 | 367 | 0.608 | 22.5 | 0 |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | text | 8/8 | 189 | 0.984 | 16.1 | 0 |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | image | 3/8 | 41 | 0.244 | 5.8 | 0 |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | text | 8/8 | 229 | 0.987 | 26.1 | 0 |
| `nvidia/nemotron-3.5-lightning:free` | text | 8/8 | 320 | 0.678 | 28.5 | 0 |
| `longcat-2.5-preview-free` (Go) | text | 0/1 | 0 | - | 0.4 | HTTP 400 Model is unavailable |

Two free readers clear the 6-of-8 bar with room to spare (Dots on both inputs, all four Nemotrons on text). The
round-1 empty replies were the model's own `[]` (`out_tok` 2), not the parser: the JSON-Lines prompt with an example
fixed it. Reconciling the best two distinct readers (Dots text + `nemotron-3.5-super-vl` text) gives 277 cells, 128
agreed (0.462), 275 verbatim (0.993), 126 settled by script (0.455); agreement is limited by the readers keying the
same values to different table titles and row labels, and `verbatim` alone does not prove cell ownership. Pages
`p012` (chart-only, no text layer) and `p041` (auditor's review in prose) are not table pages. The frozen split is
sampled but not transcribed.

**Vote of three readers (pending item 1, 11 Nov 2026).** `reality_engine/v2/reference_vote.py` (tests
`reality_engine/tests/test_v2_reference_vote.py`) settles a cell when two or more readers give the same value under
the same row label (label reduced to letters and digits, leading "(a)" / "1." dropped; reply order ignored) and the
value is printed in the page text. Run on the saved outputs of Dots, Nemotron 3.5 Super VL and Nemotron 3 Ultra
(text input) for the 60 pages, no new model call:

| | Cells |
|---|---|
| Candidate cells (union of three readers; a value under two labels counts twice) | 4,143 |
| Value printed on the page | 4,094 (98.8%) |
| Settled by script (two or more readers, same label, printed) | 2,063 |
| Label disputes (same value and column, different row label between readers) | 1,048 |
| Not settled in all | 2,080 |

By type, settled: annual report 336 of 604, deck 839 of 1,708, results 888 of 1,831. Three pages have no cell (chart
or no text layer). The old exact-text reconcile settled 835; outputs of it are kept in `reference_pages/v1/`.

Reading: the free readers copy numbers almost perfectly, but on deck panels, two-level headers and wide results
tables they often disagree on WHICH ROW a number belongs to (p031 196 candidate cells, 7 settled, 85 label
disputes). A number in the wrong row is a wrong fact, and the verbatim check cannot see it. So the model-in-build
idea needs a row check from page geometry (the label printed on the value's own line), not only a verbatim check.
Next for item 2: arbitrate label disputes by word positions in the text layer, then read by hand only what is left.

## 2. T-178: can the first build be salvaged by re-keying? (no new model calls)

- **Hypothesis:** first-build facts, once verified against the text layer and passed through the v2 label map
  (`reality_engine/v2/label_map.py`) and period engine (`reality_engine/v2/periods.py`), give more complete rows
  than the round-10 script extractor (`reality_engine/v2/table_cells.py`) on the same pages.
- **Arms, on the 30 deck and 10 annual-report reference pages:** (a) script cells r10; (b) first-build facts as
  stored; (c) first-build facts verified + re-keyed; (d) union of (a) and (c) with conflicts flagged.
- **Measured per arm:** recall against reference cells, precision, share keyed to a metric, share with a resolved
  period, share verified verbatim. Reported on dev and frozen pages separately.
- **Wrong if:** arm (c) recall is below arm (a), or its precision after verification is below 95%.
- **Decision:** if (c) or (d) wins, the first build becomes a candidate layer for the whole universe (re-key job,
  no re-reading); rows enter the store only with `verified` status. If it loses, keep it as an audit source only.
- **Also measured:** share of `ar_docs` whose fiscal year is wrong (re-derive from the text, 200 random reports),
  because a salvaged fact with the wrong year is worse than no fact.
- **Accept:** `D:/RealityEngine/reports/2026-11-11_t178_first_build_rekey.xlsx` with the four arms and the decision.

## 3. T-179: does removing raw SQL from the answering model help?

- **Hypothesis:** without `pilot3_sql` the cheap model reads the preferred figure from the typed tools and makes
  fewer misreads and sums errors, with fewer calls.
- **Questions:** 120, drawn by script with a fixed seed: 60 from the pilot10 600 (20 right, 40 partly on 5 Nov) and
  60 from u8 + q12 (30 right, 30 not right). The existing hand grade of each is kept as a reference.
- **Arms:** A = all tools as today; B = `pilot3_sql` absent (switch `REALITY_DATA_NO_PILOT3_SQL=1` in
  `plugins/reality-data/server/server.py`; the tool is not registered and the server text does not name it).
  Same model (DeepSeek V4.1 Flash, max effort), same stores, same brief. Each arm runs twice: 480 answers.
- **Logged per answer:** tool calls by tool, seconds, tokens, tools that returned the figure used
  (from the worker event log; `reality_engine/pilot3/answer_run_report.py` gains the columns).
- **Grading:** a separate read-only grader, blind to the arm, arithmetic redone. Before grading the test it grades
  100 answers that already carry an Opus hand grade; its agreement is reported with the result. A "not disclosed"
  answer is right only when a text search of the held pages finds nothing, and is reported as its own line.
- **Read-out:** paired comparison of A against B on the same questions; the difference between the two runs of the
  same arm is the noise floor. A difference inside that floor is "no effect".
- **Wrong if:** B is not better than A beyond the noise floor, or B's "cannot answer" share rises by more than its
  gain in right answers.
- **Decision:** B wins: remove raw SQL from the answering tool set (kept for development). B loses on questions that
  needed SQL: list the missing typed lookups; those become the next tool work.
- **Accept:** `D:/RealityEngine/reports/2026-11-11_t179_sql_ab.xlsx` + csv (per-run report rule).

**Harness built (T-179, merged 11 Nov; worker's p3ask rewrite replaced by Eagle with a minimal change).**
`reality_engine/scripts/p3ask.py` logs calls (`--qid`/`--log` or `P3ASK_QID`/`P3ASK_LOG`, given BEFORE the tool name)
and honours `P3ASK_NO_SQL=1`; `plugins/reality-data/server/server.py` honours `REALITY_DATA_NO_PILOT3_SQL=1`;
`reality_engine/scripts/sql_ab_sample.py` draws the questions (`--quotas`, `--max-per-company`);
`reality_engine/scripts/answer_run_report.py` gained `--call-log`.
- First look (Shivam, 10 Nov night: results by morning): 60 questions, two arms, two runs each = 240 answers:
  `python -m reality_engine.scripts.sql_ab_sample --out <dir> --quotas 10,20,15,15 --max-per-company 6`.
  The other 60 run only if the result is borderline.
- Arm A (SQL available): `python -m reality_engine.scripts.p3ask --db <store.db> --qid <qid> --log <run>.jsonl <tool> k=v`.
- Arm B (no SQL): the same with `P3ASK_NO_SQL=1` in the worker's environment.
- Report: `python -m reality_engine.scripts.answer_run_report --run <graded.jsonl> --name t179_sql_ab --call-log <run>.jsonl`
  (adds calls, calls_by_tool, sql_calls, tool_seconds, wall_seconds per answer).
- `p3ask page doc_key=<key> page=<n> [to_page=<n>]` (added 11 Nov) reads page text without raw SQL; both arms have it,
  so arm B can still open the page a row cites. Without it arm B would have lost page reading, not only SQL.
- Answer runs: questions `D:/RealityEngine/t179/questions.json`; briefs `tasks/handoff/T-179_answers_{A1,A2,B1,B2}_brief.md`;
  workers use p3ask only (MCP data tools are uncounted and forbidden); time per answer = recorder start to answer.
- The one earlier timing on record: 37 answers in 41 minutes by one DeepSeek worker (9 Nov), about 1.1 minutes each.

### T-179 first look: result (11 Nov 2026, 60 questions, 240 answers)

Scored by `D:/RealityEngine/t179/score.py` from `D:/RealityEngine/t179/` (answers and call logs per run, grades in
`grades/`, key in `grade_key_do_not_open/`). Graders: five read-only DeepSeek workers, blind to the arm, 68 items each
(Beam graders died at about 192k input tokens, so the free model failed first).

| Run | Right | Partly | Wrong | Median s / answer | Lookups (mean) | Answers with <= 2 lookups |
|---|---|---|---|---|---|---|
| A1 (SQL) | 50 | 5 | 5 | 50 | 8.7 | 7 |
| A2 (SQL) | 46 | 12 | 2 | 34 | 6.4 | 10 |
| B1 (no SQL) | 50 | 10 | 0 | 56 | 8.7 | 8 |
| B2 (no SQL) | 44 | 12 | 4 | 48 | 8.5 | 10 |

- **No measurable effect of removing raw SQL at this size.** Pooled right: SQL 96/120 (80.0%), no SQL 94/120 (78.3%).
  Two runs of the SAME arm disagree on 14 (A1 vs A2) and 16 (B1 vs B2) of 60 questions; the arms disagree on 16
  (A1 vs B1, A2 vs B2). The arm difference is inside the run-to-run noise.
- By set (right of 30): pilot10 A 28, 28 against B 23, 24; u8+q12 A 22, 18 against B 27, 20. Opposite signs, both small.
- Both B runs: 0 served sql calls. A runs: 83 and 119 sql calls.
- **The grader is lenient.** On the 100 answers with an Opus hand grade: of 50 Opus-right it called 45 right; of 50
  Opus-not-right it called 28 right. Exact agreement 64/100. So the 78-80% above overstates; the arm comparison is
  still fair because both arms pass through the same grader. Treat absolute levels as an upper bound.
- **Time:** median 34-56 s per answer, 90th percentile 74-126 s; 0 to 1 of 60 answers under 10 s. Time inside the
  tools is 1.2-1.6 s per answer: the rest is the model. Lookups: mean 6.4-8.7; 7-10 of 60 answers used two or fewer.
- "Not disclosed" claims: 11-21 of 60 answers per run made one; the grader found the figure printed in held pages
  for roughly half of them (attrition/utilisation, quarterly ARPU, block deals, fuel cost per ASK, shareholding rows).

Decision: raw SQL stays for now; removing it is not the lever. The target (one or two lookups, under 10 s) is missed by
the model's own reading time and lookup count, not by tool speed, so the next test is fewer, answer-ready lookups
(one fact tool returning the preferred value) rather than tool removal. The other 60 questions are not run: the result
is not borderline, it is null.

## 4. T-180: free models transcribing tables, checked by script

- **Hypothesis:** a model that only copies a page's tables into rows, with every row checked by script, beats the
  rule-based extractor on completeness at equal or better verified precision.
- **Counter-evidence already held:** the first build's deck readers averaged 0.54-0.68 recall. Its prompt asked for
  "facts", not a full grid, so it is not the same test; the result may still repeat.
- **Readers:** Beam and LongCat 2.5 (OpenCode Go, free), every free model the Kilo Gateway lists on the day (Dots,
  Step and others; the list is recorded), and the r10 script as baseline. No paid model.
- **Inputs:** (i) the page's text layer in reading order with word positions; (ii) the page image, for models that
  take images. Each model is run on the inputs it supports.
- **Prompt:** full grid only: table title, row label, column header as printed, value as printed, unit as printed.
  No summaries, no computed values, no interpretation.
- **Script check on every row:** value verbatim in the text layer (or, for image-only pages, agreed by two models);
  totals, margins and growth columns recompute; row and column counts match the grid check. Failing rows are stored
  as `unverified` and never served.
- **Measured on the 60 reference pages, dev and frozen separately:** recall, precision before and after the check,
  verified share, agreement between two runs of the same model (consistency), seconds and tokens per page, failure
  and refusal rate.
- **Wrong if:** no reader reaches verified precision >= 98% with recall at least 15 points above the script, or
  two runs of the best reader agree on fewer than 95% of cells.
- **Decision:** a reader wins: pilot it on u8 + q12 decks behind the completeness gate, then a frozen-set answer
  run. No reader wins: tables stay with scripts, and T-132 resumes with the completeness gate instead of 60-row
  samples.
- **Accept:** `D:/RealityEngine/reports/2026-11-12_t180_reader_bakeoff.xlsx` with one row per reader and input.

## 5. Order and load

1. T-177 reference pages (needed by T-178 and T-180). T-179 is independent and runs alongside.
2. T-178 (no model calls beyond T-177's).
3. T-180, shaped by what T-178 shows.

**Model rule (Shivam, 10 Nov night): free models first, DeepSeek only where a free model fails at the job.** Page
reading and transcription use free models only (Beam, LongCat 2.5, Kilo free models); DeepSeek is never a page reader.
Code workers and graders run on Beam; a DeepSeek worker is used only after a Beam round fails its independent
grade, and the review log says so. The one planned DeepSeek use is the answering model in T-179 (480 answers,
off-peak): the target is defined on that model, so swapping it would change the test. One heavy build at a time (RAM). Each ticket: a code worker, a separate read-only
grader, Claude's own sample before any result is quoted.
