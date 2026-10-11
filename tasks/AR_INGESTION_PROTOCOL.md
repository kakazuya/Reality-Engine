# Annual-report ingestion: protocol and pipeline (draft 2026-10-12)

Owner: main session (the AR study hand-off is `tasks/ar_study/HANDOFF_AR_PIPELINE.md`; its prototypes are in
`tasks/ar_study/challenger/`). Goal (Shivam): **every relevant AR fact stored at true quality, labelled to stock and
filing time**. Efficiency is secondary. No bulk reading by Claude; bulk LLM work goes to free models that passed the
quality test.

Decisions so far (Shivam, 2026-10-11/12):
- Statements come from XBRL; AR tables are parsed on CPU; an LLM gets only what the CPU cannot verify.
- Row-mode clean-up pass: **yes**. Prose-slice tightening (28% -> 12-15%): **no**, the wide slice stays.
- Readers need not be vision models. Any free text model that passes the must-find test may be used.

## Scope
- 34,278 ARs filed since 2019-07 are on disk (5,373 companies); `corporate_documents` (doc_type ANNUAL_REPORT).
  99.3% have a filing timestamp (`pit_source` bse_ar_api / bse_feed / filename).
- XBRL Yearly filings (`results_xbrl.db`) cover 2,543 NSE symbols (18,327 filings). Roughly half the AR companies
  have no XBRL (BSE-only, SME), so for them the gate relies on prior-year ties and subtotals.

## Pipeline per report

1. **Inventory.** One row per (ISIN, fiscal year): the AR PDF, its filing timestamp and the previous year's AR. A
   duplicate filing (same sha256) is read once. A revised AR replaces the earlier one, and both timestamps are kept.
2. **CPU stage** (no LLM, no GPU, below-normal priority, ~13 s per report):
   - page text and section classification (`extract_cpu.py`), table parsing (`columns.py`);
   - XBRL tie (`xbrl_tie.py`) where XBRL exists, prior-year tie and subtotal checks (`gate.py`);
   - year-over-year prose diff against the previous AR (`yoy.py`): repeated prose is stored once, new prose moves
     on. A company's first AR is its baseline and is read in full.
   Output: verified table rows, tables that failed the gate, and the prose slice (wide tier, ~28% of characters).
3. **LLM stage** (free readers, JSON lines output, never CSV):
   - a. **Row clean-up**: verified rows as compact lines (`label | column header | year | unit | value | page`).
     The model returns the canonical label, the unit (rupee scale / % / count / physical unit) and keep/drop. It never
     retypes the value.
   - b. **Failing tables**: that table's page text only, returned as rows.
   - c. **Prose slice**: facts and signals (auditor/CARO/C&AG/secretarial, disputes, delays, policy, stress), each
     with page and quote.
   - A second reader handles low-confidence answers, as in the deck pipeline. Readers rotate by free capacity.
4. **Validation.** Every LLM number must appear on the cited page, or the row is rejected. The unit comes from the
   page/table header (lakh vs crore). The period must fall inside the report's FY or the prior year. Standalone and
   consolidated are tagged by section.
5. **Storage** (a separate DB, `reality_engine/data/ar_facts.db`, like deck_figures.db, so the main DB is not locked):
   - `ar_facts`: isin, symbol, fiscal_year, filing_ts, doc sha256, page, section, label_raw, label, value, unit,
     scale, period_end, scope (standalone/consolidated), source (xbrl/cpu/llm), check (xbrl/prior_year/sums/page_match/
     unchecked), model;
   - `ar_text`: new prose only, plus changed-only sections, with page ranges;
   - `ar_signals`: auditor modifications, KAMs, CARO/C&AG remarks, stress items, each with page and quote;
   - search chunks: ~25-50 per AR from `ar_text`, instead of ~388 from whole reports. Whether the existing AR chunks
     in `document_chunks` (Nifty200, from the disabled hourly task) are replaced is still open.

## Quality gates (before and during production)
1. Row clean-up: on the 39+39 hand-checked rows (`challenger/hand_check_verdicts.csv`), >= 90% fully right.
2. Each reader: must-find test on the gold reports (`tasks/ar_study/free_test`, 25 facts). LongCat 25/25 (passed);
   Nemotron Ultra/Super are being tested.
3. A fresh unseen set (~10 reports, including a bank and an NBFC) is hand-checked each round, so the rules are not
   tuned to the 13 study reports.
4. After the first ~200 production ARs, audit a sample (labels, units, periods, scope) before scaling up.
5. Bank/NBFC schedule formats go to the LLM path by default until a bank parser exists.

## Operations
- A detached runner, resumable, logging a progress line every 30 s. It is registered in the resource watchdog's JOBS
  so it is kept alive and its waste is reported.
- The reader client (limiters, spend ledger, benching on 402/429/quota) is shared with the deck extractor and moved
  into a common module instead of copied.
- Shared resources: OpenCode Go free models and the Kilo quota are shared with the deck job; the GPU is never used.
- Rough duration: ~130 page-equivalents of LLM work per AR (wide slice), ~4.5M in total: ~2.6-5 days at 10-20
  page-equivalents/s, plus the CPU stage (~1.3 days on 4 workers, run in parallel).

## Build order
1. Row clean-up prompt and test on the hand-checked rows (gate 1).
2. Parser fixes from the hand-off: BRSR two-page spreads, physical units and counts, bank format.
3. Move the prototypes from `tasks/ar_study/challenger/` into `reality_engine/` with tests; shared reader client.
4. Storage schema and the end-to-end runner on the 13 study reports, scored against gold.
5. Pilot 200 ARs, audit (gate 4), then the full run, newest-first.

Open: replace or keep the existing Nemotron/Kilo route if NVIDIA's free NIM key works better; what to do with the
existing AR chunks in `document_chunks`; OpenCode Go's terms (meant for coding agents, traffic monitored) for bulk
reading.
