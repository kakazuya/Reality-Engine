# Project state record, 1 Nov 2026

The long `tasks/STATE.md` as it stood when it was cut to a short start file. A dated record: not kept current.


Live rules, machines and the merge recipe are in `tasks/RULINGS.md`, `tasks/STATE.md` and `machines/`; this keeps the gate numbers, bank status, stores and findings of that date. The gate numbers are on the old 2,681-row bank, replaced by the 1,901-question bank.

## Latest results: `tasks/MORNING_RESULTS_2026-11-01.md`
Hidden OCR text layers on scanned PDFs can be wrong, so scores on those pages and stores built from them are suspect. Size of the problem not yet measured.
Larger Microsoft TextRecognizer test scored on held-out pages: 300 DPI grayscale found 96.65% and 97.16% correct (bar 95, 98), full findings in `tasks/ocr/OCR_ON_HP_FINDINGS_2026-11-01.md` and its `.xlsx`. Workspace review, with grades, root causes and milestones: `tasks/management/WORKSPACE_REVIEW_2026-11-01.xlsx`. Its `Claude check` sheet lists corrections.

## Prototype on 3 companies, 1 Nov
Cost is fine, quality is not: 0 of 40 sampled answers right, 78% of numbers missed in the recall check, false rows passed the worker's accuracy check. No wider run. `tasks/pilot60/PROTOTYPE3_CLAUDE_GRADE_2026-11-01.md`.

## Where the gate stands
Golden rule step 5, 60-name pilot, 2,681 rows. Gate is not passed; the 30% checkpoint is missed.

| Measure | Value | Source |
|---|---:|---|
| Contract strict | 341/2681 = 12.7% | gate on main `17234a4`, 31 Oct 14:30 |
| Contract + shape checks | 237/2681 = 8.8% | same run |
| Rule grade, not reliable | 0.6% [0.28, 1.26] | `tasks/arch_v4/TRUTH_GRADE_2026-10-31.md`, same run |
| **Read grade: the number to trust** | **0/127 answered rows RIGHT, 0.00% [0.00, 0.40] of the bank; 42/127 ill-posed** | `tasks/arch_v4/TRUTH_READ_GRADE_2026-10-31.md`, on the 13:00 run (13.5% contract); not yet repeated on later answers |

Label fix merged after that run; its own run gave 327/2681 = 12.2% (`tasks/arch_v4/GATE_V4_LABELS_2026-10-31.md`). **The traded-close rebuild failed at 16:12 and no fresh gate ran:** `.tmp/traded_close.err` says `company_state_daily: rows lost, install stopped: {'rows': (7258000, 741967)}`. The safety check stopped it before the swap, so live stores are unchanged and `price.close` is still adjusted. Likely cause, not yet confirmed: `build_t1 --universe pilot` compared against a full-universe table. All numbers above are on the old 2,681-row bank.

## Question bank rewrite (Shivam's order, 31 Oct): Claude owns it
Shivam ruled: the test uses only questions the 60 pilot stocks can answer, with no data for any other stock. Claude writes the questions and does the reasoning; DeepSeek only reads passages.
- Rules, by hand: `tasks/pilot60/pilot_bank/rules_a.py` to `rules_e.py`. Builder `run.py`, reads `reads.py`, audit `audit.py`. Output `tasks/pilot60/PILOT_BANK_2026-10-31.jsonl`, removed list `tasks/pilot60/PILOT_BANK_REMOVED_2026-10-31.jsonl`. `MASTER_BANK.jsonl` and `INSTANCES.jsonl` are untouched and stay as the old record.
- Every figure, date and doc date in a question is read from the stores for that stock. Old text and evidence stay on each row.
- A keyword match is not proof: SAIL's "change in control" hit was accounting boilerplate. A passage counts only if DeepSeek quotes it and the code finds the quote verbatim; the date and page in a question are those of that passage.
- **Bank status, 1 Nov: Shivam accepted it as good enough to design the schema from.** 1,901 questions: the 1,899 he reviewed plus MB0579 (NSDL sector flows are held) and MB0222 (computed from tax notes). 95 removed. Scope rule at the top of `AGENTS.md`: the system computes what filings do not state; check `tasks/DATA_INVENTORY.md` before calling data absent. All 30 of Shivam's regression questions stay, in pilot form. Audit: no failures. Excel: `tasks/pilot60/PILOT_BANK_QUESTIONS_2026-10-31.xlsx`, with his comments and what happens to each; they live in `PILOT_BANK_REMOVED_RULINGS_2026-11-01.json`, and `rules_f.py` makes them binding. Next: prototype extraction on BAJFINANCE, HINDALCO and KEC (`tasks/archive/dsh_tasks/PROTOTYPE3_EXTRACTION_2026-11-01.md`); no wider DeepSeek run before its report, by Shivam's order. Design: `tasks/SCHEMA_PILOT_DESIGN_2026-11-01.md`; the pilot goes to 63 names (Apollo Hospitals, KIMS, Ola Electric) once their raw data is in.
- `finish.py` re-reads leftover pairs and can change rows Shivam already reviewed (on 1 Nov it changed 4 and added rows). Diff against the current bank before accepting a rebuild.
- Limits: hand checks of 80 document rows found about 1 in 7 passes weak (the quote is real, the question is not truly answered). The 758 data rows were checked for held data, not answered. Simbhaoli Sugars has no question; 4 more names have under 5. No question has been run through the engine, so there is no score on this bank yet, and the gate still reads the old files until it is pointed at this one.
- Rebuild needs Go key: `python tasks/pilot60/pilot_bank/finish.py`, then `export_xlsx.py`. Reads are stored in `reads.jsonl`, so only new pairs are read.

The contract count measures answer shape, not truth, and fell because stale and wrong-period values stopped counting. Largest cause in the read grade: 66 of 127 answered rows return a nearby measure, not the one asked. Any earlier number (8.2%, 10.2%, 13.5%, 1.0%) is out of date.

## Stores, `reality_engine/data/pilot/v4/`
- `fact_v4_pilot.db`: core facts. `hold.pct` has promoter and public (57 of 60 names) plus FII, DII, MF and insurance (56); `hold.pledge_pct` has 57. **The built store's `price.close` is still split/bonus-adjusted (`adj_close`, using later actions) while `price.open`, `price.high` and `price.low` are raw: POWERGRID 2023-09-11 stores 198.375, traded 264.50.** `fact_view.sql` now loads `company_state_daily.raw_close` and states `basis=raw`; `build_t1.py` now persists that column. The rebuild itself (steps in `tasks/arch_v4/GATE_V4_LABELS_2026-10-31.md`; 103,313 `price.close` rows) is still the controller's, and the live store's `company_state_daily` has no `raw_close` column yet. **Corrected 2 Nov (T-033):** a close *level* no longer reads that column — `execute.traded_close` reads the printed close from `equity_intelligence.daily_price_delivery` (BSE from `mkt_bse_eq_daily`) through `run.Stores.market`, so a level is the traded close, states `basis=raw`, and the store's adjusted level is reported beside it as `store_close` (§D.1.2 of `QUERY_V4_DESIGN.md`). Delivered quantity is read the same way, per exchange (`execute.panel_delivery`), because the fact view's BSE delivery rows are sparse. Returns are still computed over the adjusted series at query time (`price_basis`). No point-in-time corporate action atom.
- `fact_v4_pilot_oi.db`: `macro.oi`. `v4.db`: claims and own estimates. `shp_xbrl_pilot.db`: parsed shareholding XBRL, copied into the core store by `build_membership --shp-xbrl-only`.
- Blank `as_of` defaults to 2026-10-19, the last date all 60 names have a close (`run.py` `DEFAULT_AS_OF`). Shivam ruled on 2 Nov: keep it for pilot tests; live answers use the latest data.
- Raw shareholding XBRL: `D:\RealityEngine\raw\nse_shp_xbrl_pilot`.

## Findings that change what to do
- **Analyst agent test (free Beam + typed PIT tools): KILL.** 7/24 RIGHT (29.2%, Wilson 14.9–49.2) of rows not ILL_POSED and not CORRECT_NOT_IN_DATA; 7 PARTIAL, 10 WRONG, 11 ILL_POSED, 5 CORRECT_NOT_IN_DATA. All 40 answered (native tool calls) at 8.2 s and 19.7k input tokens per question; 0 PIT breaches. Main gaps: premise substitution (11), data gaps (10), no sort/aggregate/chart tools (6). `tasks/arch_v4/ANALYST_AGENT_TEST_2026-10-31.md`.
- Reader test: 13/40 RIGHT (32.5%), killed by its fixed rule; 13 more correctly said not stated, mostly missing documents, and 4 were WRONG. `tasks/arch_v4/READER_TEST_2026-10-31.md`.
- "Latest" now means the most recent period known by `as_of`, within limits in `execute.py` `LATEST_LIMIT_DAYS` (hold 200, fin 400, price 10, flows 100, macro and text 400 days). Named periods are strict, with no older fallback. Lifts pledge questions and removes years-old values given as latest; the run that introduced it fell 369 to 352.
- Answer labels (31 Oct): a difference prints as `<atom> change: value (from X on d1 to Y on d2)`, never as a level; `f.ratio` names its kind and only the inputs used (`derived:f.ratio(pb):price.mcap+fin.book_equity`); a share over 100%, a list over 50 distinct values, an empty value and a change across several entities are typed NIDs. Gate rerun: 937 changed rows, contract 341 to 327 (correct: 64 false/unstatable parts no longer count), PIT 0. `tasks/arch_v4/GATE_V4_LABELS_2026-10-31.md`.
- Returns over closes state their basis and name a held split or bonus (`execute.py` `price_basis`). An unexplained single-session fall of 30% or more is a typed NID. A close level names its basis; an old store's adjusted close is never called raw, and `near_high` uses one basis for the high and the close.
- Rubric scoring is not usable (8 of 40 agreement). Premise audit: 219 of 2,098 instances provably false. `tasks/pilot60/PREMISE_AUDIT_2026-10-31.jsonl`.
- near_high operator: 4 right, 1 partial, 1 wrong of 6. `tasks/arch_v4/STUDY_OPERATOR_TEST_2026-10-31.md`.
- Scope: 945 of 1,073 old parents named a stock outside the pilot. Not a data question: Shivam never asked for those stocks, and the rewrite above removes them.
- OCR: Windows.Media.Ocr on the HP CPU, 186.7 pages/min, number recall 0.964. **1 Nov accuracy pilot FAILED the gate: 110 table pages, number recall 0.839, precision 0.896 (need 0.95, 0.98). Not run.** Bench figure 0.964 does not hold on our table pages. Only about 4,647 of the 1,073 files' 11,728 pages truly lack text. RapidOCR on CPU is being tested.

