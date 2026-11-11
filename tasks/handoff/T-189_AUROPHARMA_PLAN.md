# T-189: unseen-company test on AUROPHARMA (Aurobindo Pharma) — plan for the next session

Ticket: T-189. Chosen by Shivam 11 Nov 2026 22:30 from ten companies in no test set (pilot3, pilot10, p20, u8, q12,
n10, s10, the 107 pilot-60 raw names). Owner: Eagle. Start in a fresh session; read this file, `tasks/STATE.md`,
and `docs/V2_SCHEMA_CONTRACT.md` sections 12-14 only.

## 1. What we are testing and the pass bar
- Question: does the extraction plan (scripts + routed page reading + the existing pilot3 build) let a cheap model answer
  every first-order question about one company it was never tuned on?
- Pass bar (Shivam): **>= 92% of first-order questions graded right** by Opus hand-read, arithmetic redone. Partly right
  is not right. "Not disclosed" is right only when the search holds up (ruling 9 Nov).
- If it passes: run the same pipeline unchanged on 5 more fresh names (BLUESTARCO, GODREJPROP, MGL, SHRIRAMFIN, LTTS).
  If not: report root causes per miss; no per-company fixes.
- Comparison (unfair by design, stated in the report): pilot honest baselines p20 54.8%, u8 72.5%, q12 50.3%,
  pilot10 88% after tuning. Never quote p20's 99.6% (fitted to its own questions).

## 2. Rules that bind this test
- Questions are written and **frozen (SHA-256 recorded in DECISION_LOG) before the store is built**. No fix may be
  drawn from them during this test. Every exception is disclosed in the report and the run ledger.
- Free models first; Dots (`dots-studio/dots-3-note-preview:free@kilo2`) is the table/chart reader. **Haiku is a
  separate, measured arm and needs Shivam's OK for the page count** (he approved 30 pages on 11 Nov only; estimate
  ~USD 2-3 per 1,000 pages at API rates).
- DeepSeek off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST). OCR on the HP only, headless; HP must be online
  and unlocked (it was offline 15:20-19:29 on 11 Nov).
- Every model run logged in the run ledger (DEVELOPER_GUIDE s7); answer run ends with `answer_run_report.py`.

## 3. What is held (inventory written 11 Nov: `D:/RealityEngine/aurobindo/inventory_fy25plus.csv`)
- ISIN INE406A01037. From 2024-04-01: corporate_documents 130 (80 other filings, 37 call files = transcripts plus
  audio links and repeat copies, 6 announcements, 4 decks, 3 annual reports); deck_sources 11 decks (status ok);
  results XBRL 58 filings 2018-12 .. 2026-06. **No file is local** (raw lives on Drive); the fetch step pulls them.
- Universe file for the fetch: `D:/RealityEngine/aurobindo/universe_aurobindo.csv`.

## 4. Steps

### Step 0 — freeze the questions (before any build)
1. Harvest: one `agy` worker (gemini-3.8-flash-medium) with `tasks/handoff/T-130_harvest_brief_template.md`,
   `{COMPANIES}` = `AUROPHARMA, Aurobindo Pharma`; verified sources only. Output
   `D:/RealityEngine/aurobindo/questions/harvest.csv`.
2. Opus writes the test set `D:/RealityEngine/aurobindo/questions/questions.csv` (id, question, as_of, kind, needs):
   ~60 first-order questions about the company itself, reframed from the harvest where possible, covering: quarterly
   and annual P&L lines (consolidated and standalone), segment / geography mix (US formulations, Europe, growth
   markets, ARV, API), injectables (Eugia), biosimilars (CuraTeQ), PEN-G / China plant, R&D spend, capex, net debt or
   net cash, margins and ratios, guidance given in calls and whether it changed, USFDA inspections/observations and
   warning letters as stated by the company, shareholding (promoter, FPI, MF), pledge, dividends, buybacks, price
   reaction to results, management statements on pricing and launches. Undated questions use `as_of` 2026-10-19.
3. `sha256sum questions.csv` -> append to `D:/RealityEngine/plans/DECISION_LOG.md` (also gdrive
   `InfoDiffusion_archive/plans`). From here on nobody edits the file.

### Step 1 — fetch and base build (scripts, same recipe as `D:/RealityEngine/n10/build.sh`)
```
D=D:/RealityEngine/aurobindo
python -m reality_engine.pilot3.make_profile AUROPHARMA --name aurobindo --root $D --window-start 2024-04-01 \
    --compute-start 2019-01-01 --out $D/aurobindo_profile.json
python -m reality_engine.scripts.fetch_pilot60_history --fetch --universe $D/universe_aurobindo.csv \
    --window-start 2024-04-01 --window-end 2026-11-11 --out $D/raw/manifest.csv
python -m reality_engine.pilot3.docs_collect --profile $D/aurobindo_profile.json
for part in registry pages transcripts kpi guidance stores comparatives preferred ratios segments notes checks; do
  python -m reality_engine.pilot3.build --profile $D/aurobindo_profile.json --out $D/aurobindo.db --part $part; done
```
Run with `PYTHONIOENCODING=utf-8`; logs `$D/b_<part>.log`; stop on any non-zero exit. Check the first written rows'
dates against the filing record (known_at from the BSE dissemination time, before/after 15:30 IST rule).

### Step 2 — routed page reading (one dsh worker, DeepSeek off-peak, worktree; new code)
Build a new module `page_route` in `reality_engine/v2/` (+ test) that sorts every page of the store's `doc_page` into exactly one route
with a reason, using scripts only:
- `no_figures` (cover letters, intimations, prose without numbers, contents pages, auditor-report prose): no reader.
  This is also the fix for readers inventing figures on such pages (11 Nov: every reader did it on 2-4 pages).
- `text_ok` (prose with a clean text layer): keep the text layer as is.
- `needs_ocr` (no text layer, or a garbled one: `v2/page_words.py` text-quality verdict `none`/`jumbled`): HP
  TextRecognizer via `reality_engine/pilot3/hp_ocr.py` (`plan --pdf-dir` / `fetch --words-out`, merged 11 Nov; extend to
  doc+page lists if needed). Its words feed the route decision again (prose -> text, table -> Dots).
- `table_or_chart` (number density, ruled/columnar layout, images with numbers): Dots on the **page image** in grid
  format. `v2/page_reader.py` (T-183) reads layout text today; add an image input (11 Nov measure on 30 hand-read
  pages: Dots image P 83.8 / R 89.6 vs Dots on layout text ~62 / ~67). Each cell then goes through the position check
  (`v2/reference_geom.py`) and `row_checks.py`: verified / unverified (served labelled) / quarantined (never served).
- Arm B (only with Shivam's OK): pages where Dots fails the checks go to Haiku 5.5 medium, batches of 8 pages, under
  100k context (11 Nov: Haiku P 91.1 / R 95.2, ~9 s/page per reader). Report A and A+B separately.
Worker gets: this section, the evidence numbers above, the 11 Nov results (`handread/score_local.csv`), and the stop
rule "never open `D:/RealityEngine/aurobindo/questions/` or `.../truth/`".

### Step 3 — reading truth (Opus)
Seeded sample of 20 `table_or_chart` pages of the new store (seed 20261112), rendered to PNG + layout text;
Opus subagents (batches of 8, <100k) write `<page>.truth.txt` in `D:/RealityEngine/aurobindo/truth/` in grid format
(same prompt as 11 Nov). Score with `python -m reality_engine.v2.truth_score`. Also 10 `no_figures` pages to measure
routing (any figure written there = routing miss).

### Step 4 — answers and grades
- Answerer: DeepSeek V4.1 Flash (off-peak) through the `reality-data` MCP `pilot3_*` tools only, with
  `REALITY_PILOT3_DB=D:/RealityEngine/aurobindo/aurobindo.db` (restart reality-data first). One answer per question,
  tool calls and seconds logged; raw SQL use must say why.
- Grader: Opus reads every answer, redoes the arithmetic, grades R / P / W, root cause per miss (not extracted, reader
  wrong, routing, tool routing, worker misread, not disclosed). `D:/RealityEngine/aurobindo/report/grades.csv`.
- `answer_run_report.py` -> Excel + CSV in `D:/RealityEngine/reports/`.

### Step 5 — report to Shivam
HTML `D:/RealityEngine/reports/2026-11-12_aurobindo_test.html`: score with sample size, misses by cause, reading P/R on
the 20 truth pages, routing counts and time per step (fetch, build, OCR pages/min, Dots pages/min), the pilot baselines
beside it, every disclosure. Then the scale decision (5 more names) per section 1.

## 5. Known risks
- Dots on Kilo: 502s and 429s seen 11 Nov; retry, never silently drop a page (count unread pages).
- The position check misses many right cells (174 of 264 on 7 pages after T-185): unverified cells must still be
  served labelled, or recall collapses.
- Pharma KPIs (US formulation revenue, ANDA filings/approvals, Eugia, biosimilars) may need a pharma lexicon family
  check in `sector_map.yaml` / `label_map`; a missing family is a finding, not a per-company patch.
- MSI RAM ~16 GB: one heavy job at a time; tests per file.
