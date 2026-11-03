# Night loop: goal, boundaries, evals (draft for Shivam's approval, 4 Nov 2026)

Authoritative copy. The headless loop session reads this file first and obeys it over anything else it finds,
except `tasks/RULINGS.md`. Only Shivam changes it. A loop that edits it is rejected.

## 1. Goal (one sentence)
Make the pilot3 database (KEC, BAJFINANCE, HINDALCO) hold, as typed rows that the `reality-data` pilot3 tools return,
more of the numbers our hand-graded pilot answers needed, extracted by deterministic scripts (no model call while
building), without losing precision or point-in-time correctness, and with the same or less reading, compute and time.

What "better" means is ONLY what section 4 measures. A change that does not move a section 4 number is not progress,
however good it looks.

## 2. Not the goal (a loop doing any of these is rejected)
- New companies, new downloads, embeddings, OCR runs, paid or model calls of any kind in the build.
- Changing any question, gold answer, grader, eval script, test assertion, ruling or guideline.
- Commentary extraction by rules (guideline 4: commentary stays searchable text).
- Company-specific code: hard-coded symbols, ISINs, BSE codes, doc keys, file hashes, page numbers or gold values.
  Rules must work for any company of the same sector family.
- Writing the live `reality_engine/data/pilot3/pilot3.db`, pushing, merging to `main`, or editing `main`'s files
  outside `tasks/night_loop/`.
- Work outside the queue in section 6.

## 3. Roles
- **Wrapper** (visible Claude session, Eagle): launches one headless loop at a time, re-runs every eval itself,
  reads every diff, merges, backs up and promotes the database, keeps the scoreboard, stops the night.
- **Loop session** (headless `claude -p`, Opus 5.5, effort medium, same config and MCPs as the wrapper, no subagents):
  takes the next queue item, gathers the evidence, writes ONE brief to `tasks/night_loop/briefs/`, steers at most
  2 dsh workers, runs the evals on the worker branch, writes `tasks/night_loop/loops/loop_NN.md`, exits.
  It does not write product code (ruling: Opus manages, dsh builds, until 6 Nov 23:30).
- **dsh workers**: DeepSeek V4.1 Flash at max effort, worktree branches, briefs per `tasks/worker_context/BRIEF_TEMPLATE.md`.

## 4. Evals (frozen before loop 1; built by T-055, never edited by a loop)
Gold: the 550 numbers in the 154 answers hand-graded R (`answer_run2`), normalised once to
(symbol, canonical period, value, canonical unit). Split by a fixed hash of qid: **dev 60%** (the loop may see it)
and **hidden 40%** (only the wrapper sees it; the scorer prints only its counts). Text and date answers are left out.

| # | Measure | Kind | Rule |
|---|---|---|---|
| M1 | Typed recall: gold numbers present as a typed row (kpi_series, fin_annual_line, fin_quarter_xbrl, ratio_panel, guidance, shp_category, share_capital, dividend_event) for the same symbol and period, value within rounding of the printed figure, `known_at` <= the question's as_of | score | dev must rise by >= 1; hidden must not fall; no company may fall |
| M2 | Provenance: every new or changed row with a quote has its value in the quote and the quote on its cited page (`doc_page` text) | guard | >= 98% of new rows |
| M3 | XBRL agreement: deck, press-release and transcript rows for revenue, EBITDA, PAT, finance cost against `fin_quarter_xbrl` for the same period and basis | guard | mismatch count must not rise |
| M4 | Point in time: rows with a period after their document date, rows known before their filing, duplicate documents (hash) | guard | must not rise; 0 new |
| M5 | Junk: rows per page over the 99th percentile, impossible values (margin > 100%, negative counts), total rows up > 15% with no M1 gain | guard | must not rise |
| M6 | No model or network in the build: build run with sockets blocked | guard | must pass |
| M7 | Generality: added lines in `reality_engine/pilot3/` with a symbol, ISIN, BSE code, doc key, 64-hex hash or a gold value literal | guard | 0 |
| M8 | Tests: `pytest -k pilot3 -m "not slow"` each loop; full suite and `checkpages run` (found >= baseline) at merge | guard | green |
| M9 | Cost: build seconds per company for the parts changed; pages read | score | may not rise > 20% without an M1 gain |
| M10 | MCP replay: 30 fixed pilot3 tool calls with expected values (from dev gold) | guard | all still pass |
| M11 | Hand-read: the wrapper reads 20 random new rows against their pages | guard | >= 18 right |

**Accept** a loop only if M1-dev rises, M1-hidden and every company hold, and M2-M8, M10, M11 pass. Otherwise the
branch is kept, not merged, and the reason is logged. **Overfit alarm**: dev up >= 5 numbers while hidden gains 0
over two accepted loops: stop the night. The hand-read score (M11 and the morning sample) is what gets reported to
Shivam; M1 is a guide.

## 5. Boundaries
- At most **2 dsh workers at once in total** (the night's limit includes any worker already running), one headless
  loop at a time, no dsh starts in peak hours (Mon-Fri 06:30-09:30 and 11:30-15:30 IST).
- Headless loop: <= 150 turns, <= 2 hours wall, exits after one queue item. At most 4 loops before Shivam reviews.
- RAM: pause starts under 2.5 GB free; one test process at a time under the RAM watchdog.
- Live database: written only by the wrapper, after a dated backup, from a merged branch.
- Protected paths (any diff touching them = reject): `tasks/night_loop/GOAL.md`, `reality_engine/night_eval/**`,
  gold files, existing test assertions (lines removed or changed in `reality_engine/tests/`), `tasks/RULINGS.md`,
  `docs/DB_BUILD_GUIDELINES.md`, `AGENTS.md`, `.mcp.json`, `plugins/dsh-worker/**`, dsh profiles.
- Audit: the wrapper greps each loop and worker transcript for reads of the hidden gold or the answer runs'
  answer files; any hit rejects the loop.
- Docs: no docs, no merge (blueprint results history and STATE line per accepted loop).

## 6. Queue (in order; a loop takes the first item not done)
1. Segment results from the XBRL results filings, if the filings carry them (guideline 2).
2. Period labels and junk rows found by the 4 Nov re-answer: BAJ deck cost of funds one quarter early; junk `nim_pct`.
3. XBRL calibration: flag each deck / press-release / transcript figure that matches or mismatches XBRL; per-company
   reader accuracy (guideline 3).
4. Duplicate and mis-typed documents: KEC transcripts stored twice; HINDALCO press releases typed as decks.
5. The P-graded answers' missing numbers (from `regrades.tsv` notes; dev questions only).
6. Core-document triage: read only the core set plus the annual report front section; pages read must fall >= 30%
   with M1 not falling.

## 7. Stop the night when
3 loops in a row are rejected; the overfit alarm fires; a guard fails on `main`; the Claude usage limit is hit
(stop, do not wait for the reset); 4 loops are done; or Shivam says stop. The wrapper then writes
`D:\RealityEngine\reports\<date>_night_loop.html`: per loop, what changed, every measure before and after, the
hand-read sample, rejected branches and why.
