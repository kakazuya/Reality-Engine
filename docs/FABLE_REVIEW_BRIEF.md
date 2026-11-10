# Review brief for Fable 5.2: why we are not yet at 95% answered

Written by Eagle (Claude Opus 5.5) for Shivam, 10 Nov 2026, to hand to Fable 5.2 together with the repository.
Living document: section 7 is updated as tickets merge. Every number here has a source path; where a number
was not measured, this file says so instead of estimating it.

**What we ask you (Fable) to do:** read this brief and the files in section 9, then judge (a) why the system
answers well on companies it was tuned on and much worse on companies it was not, (b) which architectural changes
would close that gap without hand-written company rules, and (c) whether our evaluation method can be trusted, and
how to make it trustworthy. Be blunt; we want the hardest critique, ranked by expected gain.

## 1. The goal and the target

- Product: a searchable store over Indian listed-company disclosures (results, XBRL, decks, call transcripts,
  annual reports, announcements, shareholding, prices) where **every investor question becomes one or two queries**
  through the `reality-data` MCP tools, answered by a cheap model (DeepSeek V4.1 Flash) at Opus quality.
- Target (Shivam): on **any** company, >= 90-95% of investor questions answered right, in one or two tool calls,
  in under about 10 seconds. A number the filings do not print is a formula over extracted inputs, not a gap.
- Ultimate use: 6-month to 2-year price prediction and fundamental backtests, which start only after this target.
- Order of work (AGENTS.md "golden rule"): pilot must reach 95% answered plus a checklist before any full-universe
  build. Scope must scale unchanged to all NSE+BSE companies (about 5,000-6,900): **no company lists in code**.

## 2. The system as built (map)

- **Raw data**: exchange filings since FY24 (`reality_engine/data/bse_announcements.db`, 1.95 M announcement rows;
  `equity_intelligence.db` holds companies, prices from 2019, shareholding, deals). Raw PDFs on Google Drive.
- **Pilot store (current design, "pilot3")**: one SQLite file per company set, built by scripts with no model calls
  (`reality_engine/pilot3/build.py --part <part>`, 37 modules). Tables: `doc`, `doc_page` (+FTS),
  `fin_annual_line`, `fin_quarter_xbrl`, `fin_quarter_printed`, `ratio_panel`/`formula`, `kpi_series`,
  `transcript_statement`, `guidance`, `shp_*`, `valuation_daily`, `segment_line` (in progress), etc. Every row carries
  source document, page, quote and `known_at` (point in time). Schema and methods: `docs/PILOT3_BLUEPRINT.md`
  sections 2-3.
- **Store sets**: pilot10 (10 large caps, the original tuning set), p20 (10 more), u8 (8), q12 (12), n10 (10),
  s10 (10, just approved: 5 sparse-disclosure + 5 mid/small deck filers). Paths `D:/RealityEngine/<set>/`.
- **Answer path**: a DeepSeek worker gets the question and calls the `pilot3_*` MCP tools
  (`plugins/reality-data/server/lookups_pilot3.py`, `server.py`): `pilot3_fin`, `pilot3_ratio`, `pilot3_kpi`,
  `pilot3_guidance`, `pilot3_statements`, `pilot3_holding`, `pilot3_tech`, `pilot3_calc`, `pilot3_search` (bm25),
  `pilot3_semantic` (dense, paid), `pilot3_sql`.
- **v2 redesign (in progress)**: `docs/V2_SCHEMA_CONTRACT.md`. Per-company SQLite, every printed table cell stored
  with header path, period and unit (`reality_engine/v2/table_cells.py`), a label map from printed labels to metrics
  (`v2/label_map.py`), a period engine (`v2/periods.py`) and a calc catalog. Motivation in its section 1: the
  answering model still reads tables and does sums itself, and that is where it fails.
- **Build workforce**: code is written by DeepSeek and Beam workers through `plugins/dsh-worker`; every branch is
  graded by a separate read-only worker and checked by Claude (tests + own sample) before merge. Review log:
  `tasks/efficiency/worker_reviews.jsonl`.

## 3. What we have measured

| Test | Set | Result | Source |
|---|---|---|---|
| Hand-graded answers, 600 fixed dev questions | pilot10 | 480 R / 116 P / 4 W = **80.0%** (5 Nov); re-ask of partials -> **528/600 = 88.0%** (8 Nov) | `docs/PILOT3_BLUEPRINT.md` section 5; `D:/RealityEngine/reports/2026-11-08_t124_reask_136_partials.xlsx` |
| Baseline on 10 new companies, before any fix for them | p20 | 126 R / 102 P / 2 W of 230 = **54.8%** | `D:/RealityEngine/reports/2026-11-09_t143_p20_baseline_answers.csv` |
| Same 230 questions after a day of fixes driven by those questions | p20 | 229 R / 1 P = **99.6%** | `.../2026-11-09_p20_final_230_answers.csv` |
| Answers on u8 (fixes partly informed by p20 work) | u8 | 108 R / 41 P of 149 = **72.5%** | `.../2026-11-09_t130_u8_answers.csv` |
| Answers on q12 | q12 | 72 R / 70 P / 1 W of 143 in scope (13 scope_out) = **50.3%** | `.../2026-11-09_t124_q12_answers.csv` |
| Why u8 + q12 missed (106 non-right in scope, each searched in held page text) | u8+q12 | **82 of 106 (77%) are printed or computable from documents we already hold**; misses by cause: not_extracted 51, tool_routing 15, needs_compute 6, page_never_read 4, label/period/unit/type 6 | `D:/RealityEngine/night_loop/opus/held_audit/summary.md`; `reports/2026-11-10_held_not_queryable_audit.xlsx` |
| Answer misses by cause on pilot10 (600) | pilot10 | worker misread 44-89, worker sums/units 18-31, not held 19-24, store defects 10-21 (5 Nov runs) | blueprint section 5 |
| Cheap model vs Opus on the same store | pilot10 subset | 20 random pairs: Opus 17 right, DeepSeek 11; DeepSeek made more lookups (10.6 vs 8.2), so the gap is reading, not call count; raw SQL was 77 of 126 DeepSeek calls on one question set | blueprint "Model against store: T-084 and T-087" |
| Retrieval, 112 gold questions, top 10 | pilot3 | bm25 35%, bm25+1B 46%, bm25+8B 52% | blueprint section 5 |
| Extractor precision measured today (independent graders, own seeds) | u8/q12/p20 | guidance r4: 0 targets lost, 1 junk of 27 added (merged); statements entities 78.1% / 84.2%, topics 82.0% / 81.4% (r6, sent back); segments u8 90.0%, q12 67.5% (r4, q12 unmeasured on final code); table cells strict 41/60 (r11, sent back) | section 7 |
| Build cost (5 large companies, one process) | unseen5 | `build --part all` 815 s; scale estimate 52 h on 6 processes, 501 GB for 6,940 companies (upper bound) | blueprint section 7a |

## 4. What we have NOT measured

1. **Accuracy on truly unseen companies.** Every set after pilot10 was used to drive fixes before or soon after its
   first answer run. p20's 99.6% is a fit to its own 230 questions; its honest number is the 54.8% baseline.
   n10 has a store but no answer run; s10 is only being fetched.
2. **Seconds per answer and calls per answer.** No timed end-to-end answer run exists. The only latency target is
   T-153 (tool call p95 <= 1 s on pilot20), open. The checklist's "about 20 timed queries" has not been run.
3. **Run-to-run variance at scale.** One measurement: the 5 Nov re-run moved 58 answers to right and 74 to missed
   (a 16-answer gap within about 1.4 standard errors). Single runs per set since then.
4. **Grader agreement.** Hand grades by Opus were the reported score until 10 Nov; Opus headless grading is now
   stopped (Shivam). No inter-grader agreement figure exists for the dsh graders now used.
5. **Sparse-disclosure companies** (no calls, no decks). Every set so far is mostly large caps with calls and decks;
   s10 (approved 10 Nov) is the first test of annual report + results + announcements only.
6. **Fundamental history depth.** Company documents are held from FY24 only (prices from 2019); deferred by Shivam
   until the 95% target is met.

## 5. Where it fails (bottleneck), ranked by evidence

1. **Not extracted (largest).** 51 of the 82 "held but not answered" u8/q12 rows: the fact is printed on a held page
   but no table row carries it. Largest single loss: deck fact-sheet tables print 5-8 periods per page and the store
   keeps one column or none. Sector operating KPIs (airline yield/RASK, hospital ARPOB/occupancy, telecom ARPU,
   steel EBITDA/tonne) exist only where a lexicon word matched (`pilot3/lexicon/*.yaml`, `pilot3/kpi.py`).
2. **The model reads tables and does arithmetic.** pilot10 misses are dominated by worker misreads and worker sums
   (TTM vs FY, standalone vs consolidated, swapped labels, 10x crore slips). A preferred-figure fix inside a tool did
   not reach a model that bypassed it with raw SQL. v2's premise is to store every cell with header, period and unit
   so the model looks up instead of reading; v2's table-cell extractor is at strict 41/60 on its latest round.
3. **Text is held but unfindable.** Statements tagged `other` (about 70-87% before T-164), answers split mid-turn,
   no named-entity tags; misdated old transcripts produce confident wrong answers (Tata Elxsi 2018 "JLR 24%").
4. **Routing.** 15 of 82: the data sits in a table but the tool the model chose never reads it (holding categories,
   KPI rows the model did not ask `pilot3_kpi` for).
5. **Extraction rules generalise slowly.** Every extractor improves fast on the documents it is tuned against and
   regresses or plateaus on new layouts (this week: guidance 4 rounds, statements 7 rounds, segments 5 rounds,
   table cells 12 rounds). The pattern: rule-based parsing of semi-structured PDFs (multi-level headers, deck panels,
   OCR splits) with a precision gate per round.

## 6. Our evaluation method and its weaknesses

What we run:
- **Answer runs**: DeepSeek workers answer fixed question sets through the MCP only; graded right / partly / wrong
  with arithmetic redone (`reality_engine/pilot3/answer_check.py` for automatic regression; hand grade for the score;
  per-run reports via `answer_run_report.py`).
- **Extractor gates per branch**: the worker measures precision on a random sample; a separate read-only worker
  regrades on its own seed against page text; Claude reruns tests and samples; merge only with zero earlier-right
  rows lost (replay of earlier graded rows plus a diff against the previous store).

Weaknesses we already know:
1. **Tuning on the test.** The same question set drives fixes and reports the score (p20: 54.8% -> 99.6%). There is
   no frozen hold-out set that fixes are never allowed to see.
2. **Self-grades overstate.** Today's examples (worker claim vs independent grader): statements entities 100% / 100%
   / 99.2% / 86.4% claimed vs 64.5% / about 50% / 71.2-41.8% / 78.1-84.2% measured; table cells 48/60 claimed vs
   41/60. Independent graders caught every one, but graders are also models and their own error rate is unmeasured.
3. **Replay tests check presence, not completeness.** T-132 r11 kept 179/179 replayed cells while dropping a whole
   column on two-level-header tables; only a diff against the previous store found it.
4. **Small samples.** Precision gates use 40-60 rows per store; a 90% threshold on 40 rows has a wide interval
   (one grader reported 95% CI 67-87% for a 78% point estimate).
5. **Question sets.** Banks were rewritten per company set; they cover direct, two-step and ripple questions
   (pilot10: direct 85%, two-step 77%, ripple 71%), but not all question shapes appear in every set.

## 7. Live status of the open tickets (updated as they merge)

Last update: 10 Nov 2026, 20:35 IST.

| Ticket | What | State | Latest independent measurement |
|---|---|---|---|
| T-166 | Guidance: only management's own targets | **Merged** (fc1aca12) | 0 targets lost, 1 junk of 27 added; open: 3 wrong speaker names, a volume target keyed as revenue growth |
| T-133 v8.1 | Label map, live KPI leaf matching | **Merged** | 199/200 sample; 0 stored right rows lost; ~470 junk cells removed |
| T-164 | Call statements: entities, topics, whole answer turns | Round 7 done, under independent review | r7 worker: entity 91.8/88.9% u8, 88.6/93.9% q12; topic 88.9-93.2%; NGC 36/38; Virupaksha found; 9 calls gain management statements a misread participant block had dropped. r6 independent: entity 78.1/84.2%, topic 82.0/81.4% |
| T-163 | Segment / business-line / subsidiary table | Round 5 running | r4: u8 90.0%, q12 67.5% (pre-final), 12/14 audit questions |
| T-132 | v2 table cells | **Paused after round 12** for this review | r12 (worker's own measure): strict 47/60; 9 of 40 sampled earlier-right r10 cells still lost; replay 179/179; a parent-by-indentation rule broke 6 graded parents and was reverted. r11 independent: 41/60, 27 of 100 sampled right cells lost. Twelve rounds of layout rules have not converged: see question 1 |
| CHOLAFIN KPI | Sentence extractor: impact ratios, prior-year values, segment figures | Tests pass; 4-store rebuild diff pending | u8 rebuild: 2 wrong removed, 4 corrected, 0 right lost |
| T-167/T-168 | s10 unseen set | List approved; filings fetched (2,719 files, 0 errors) | store build next |

## 8. Questions we want you to judge

1. Is rule-based extraction (regex + layout heuristics, no model in the build) the right core for a 6,000-company
   store, given the round counts above? If not, what is: a model in the build with verification, a learned layout
   model, cell-level table extraction plus a label map (v2), or something else? What would you measure to decide?
2. The answering model fails on reading and arithmetic more than on retrieval. Is v2 (every cell stored with header,
   period, unit; formulas computed in code) the right fix, or should the answer path change (fewer, more structured
   tools; forbidding raw SQL; a planner)?
3. How should the evaluation be restructured so the reported number means "any company"? Frozen hold-out companies,
   question generation, grader calibration, sample sizes, what to measure per answer (correctness, calls, seconds).
4. Which of the five bottlenecks in section 5 gives the most gain per unit of work, and in what order?
5. What would you stop doing?

## 9. Files to read first

- `AGENTS.md`, `tasks/STATE.md`, `tasks/RULINGS.md` (rules and the current step)
- `docs/PILOT3_BLUEPRINT.md` (schema, methods, results history, findings)
- `docs/V2_SCHEMA_CONTRACT.md` (the redesign and why)
- `D:/RealityEngine/night_loop/opus/held_audit/summary.md` (why u8/q12 answers missed)
- `reality_engine/pilot3/build.py`, `kpi.py`, `transcripts.py`, `guidance.py`, `segments.py`
- `reality_engine/v2/table_cells.py`, `label_map.py`, `periods.py`
- `plugins/reality-data/server/lookups_pilot3.py` (the answer tools)
- `tasks/efficiency/worker_reviews.jsonl` (every worker round and its independent grade)
