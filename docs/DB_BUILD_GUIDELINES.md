# Database build guidelines

How to build the company database for all held companies: most information for the least reading, every row precise
and point-in-time, every question answerable fast through the `reality-data` MCP. Adopted by Shivam on 4 Nov 2026.
Facts, tests and results behind these rules are in `docs/PILOT3_BLUEPRINT.md`; this file holds only the rules.
Change a rule only with a measurement that supports the change, and note it in `D:\RealityEngine\plans\DECISION_LOG.md`.

## 1. Read few documents, the right ones, once
- **Core set per company per quarter**: results filing (XBRL + PDF), investor presentation, concall transcript, results
  press release. Plus material announcements (order wins, board outcomes, credit ratings, acquisitions / capacity,
  management changes, AGM/EGM outcomes, dividends / capital) and the annual report's front section once a year.
  About 50-60 documents per company since FY24-25 (pilot companies hold 600-750 in all).
- Everything else is kept on disk, registered with title, category and date, searchable by title, and gets no OCR and
  no extraction until a question needs it.
- **Annual report**: read from the cover to where the financial statements start (front section, directors' report,
  MD&A). Skip statements, notes, auditor report and AGM notice (XBRL covers the statements). Add the notes later only
  for questions that need them (related parties, contingent liabilities, segment assets).

## 2. Structured data first
- Anything an exchange publishes as structured data (XBRL results, shareholding, corporate actions, prices) comes from
  that feed, never from a PDF.
- Check first whether segment results are in the XBRL results filing; if yes, segments come from there with no
  hand-written patterns.

## 3. Calibrate readers against XBRL instead of reading by hand
- Revenue, EBITDA, PAT and similar figures printed in a presentation, press release or transcript must match XBRL for
  the same period and basis. A match confirms that table's period mapping; a mismatch flags the table.
- Keep a per-company reader accuracy score from these matches; a company below the bar is fixed before its rows are used.

## 4. Numbers become rows; commentary stays searchable text
- Extract numbers (financials, KPIs, guidance) into typed rows with period, unit, basis, entity, quote, page, known_at.
- Do not write rules to extract commentary. Store page text and speaker-tagged quotes and answer by search.
- Search blend per document type (pilot measurement): presentations lean on embeddings; annual reports and transcripts
  blend keyword + embeddings; press releases keyword only. Text vectors only, no page images.

## 5. One vocabulary across companies
- Every metric gets a canonical id, unit (crore for money), period label (FY / Qn FY), basis (consolidated /
  standalone) and entity. Company labels map to canonical ids through one lexicon per sector family (10 families
  today: bank, nbfc, insurance_life, auto_oem, consumer_internet, fmcg, it_services, metals_nonferrous,
  epc_capital_goods, pharma), each checked on 3-4 companies. Cross-company comparability comes before any single
  company's completeness.
- The taxonomy -> family map is `reality_engine/pilot3/sector_map.yaml`, read by `make_profile.py` only (not under
  `lexicon/`, where every yaml is a KPI lexicon). It lists all 191 basic industries of `company_industry`: 47 map to a
  family and 144 are an honest `unknown` (common lexicons only). A company with no taxonomy row is also `unknown`,
  reported, never guessed from its name; 3,344 of the 5,358 active companies have no row, mostly BSE-only. The
  label is looked up by every ISIN and then by the symbol (14 labels rescued); `master_companies.industry` is a
  second tier only where the taxonomy has nothing, and only for names that map cleanly (usable for 495 of 5,358).

## 6. Models only where the rules are unsure
- Rule-based readers mark their confidence. Only low-confidence rows go to a model: a sentence with two figures, a
  table that fails the XBRL check, a multi-series chart. Everything else stays deterministic and repeatable.

## 7. Point in time is a hard check
- Every row inherits its document's `known_at`; a transcript is never known before its call date; a period never starts
  after its document's date.
- A nightly invariant check runs over the whole database: no period after its document, no row before its filing, no
  duplicate documents (exact file hash + first-page text fingerprint).

## 8. OCR only what earns it
- Order: exchange category and headline at download, then text-layer check (96% of pilot pages need no OCR), then OCR
  page 1 of a scan to classify, then the rest only if the document is in the core set. OCR runs on the HP.

## 9. Fast checks for every change
- Rebuild only what changed: one build part, one company (`python -m reality_engine.pilot3.build --part kpi --symbols KEC`); under a profile (`--profile <json>`, T-056) `--symbols` limits every part, so the same command builds one company of the profile; extraction cached by document hash + extractor version.
- Fixed check pages per extractor run in seconds (`python -m reality_engine.pilot3.checkpages run`: 314 pages, about 6 s); a fix round is `pytest reality_engine/tests -q -k pilot3 -m "not slow"`.
- The full rebuild and integration tests (marked `slow`, `-m slow`) run once, at merge. Heavy test suites run one file per process under a RAM cap.

## 10. Prove by sector sample, not company by company
- About 20 template questions per sector run as SQL against every company in it; empty or failing results are the gap
  list. Hand-read only a random sample per sector. The pilot's hand-read grade stays the reference.

## 11. Workers
- Brief a DeepSeek worker only with its evidence gathered: defect rows and ids, file / function / line, table columns,
  fast check command (project rule, `tasks/RULINGS.md`). One long-lived worker per track; parallel workers only on
  disjoint files.

## 12. Identity before extraction (T-093, 6 Nov 2026)
- Every document gets one `doc_identity` verdict before a page is extracted: `ok`, `set_aside`, `unknown` (text too
  thin), `on_drive` (archive only, not downloaded) or `not_held`; one column and reason each for company, fiscal year,
  type and date (`reality_engine/pilot3/doc_identity.py`). No model call.
- `resolve_file` reads a sha-to-path index built once over the raw store's sha-named folders
  (`docs_collect.SHA_DIRS`) plus the Drive index kept by `reality_engine/toolbelt/drive_fetch.py`; a row only in the
  archive is `on_drive`, and only a bounded sample (at most 50 files) is ever downloaded.
- A raw file may live only on Drive (T-102): a build step asks `reality_engine/raw_store.py` (`exists`/`walk`/`glob`/
  `subdirs` to see it, `local`/`prefetch` to read it), never `Path.is_file()` alone, and treats a file neither local
  nor in the T-102 manifest as missing.
- A failure is set aside by the flag, never deleted: `docs_collect.collect(..., set_aside={sha,...})` skips that file,
  and `registry.build_doc` leaves out every `doc_identity.doc_key` whose verdict is `set_aside` (`doc_key` is the
  sha256, else `corp:<corporate_documents.id>`).
- Checks, each tested on hand-read pages: a first-page name miss re-reads the whole file (auditor's-report pages for a
  late name, ISIN prefix / scrip code for a former name); annual reports and results are checked against the record's
  fiscal year; the type is the first-page text (a newspaper clipping or a meeting notice is not an annual report, a
  transcript under the BSE "Investor Presentation" category still is); the date is `bse_dissem_ts`, then
  `publication_date`, and `doc_date` equal to the crawl date with no BSE/PIT field is flagged `crawl_date`.
- A 1-3 page web-link letter or a 1-page notification that the transcript is on the website is a refetch candidate:
  its `type_reason` starts `cover_letter:`, `linked_url` holds the http(s) link printed on the page, and
  `duplicate_of` holds the lowest `corporate_documents.id` when another row of the same company shares the sha256
  (the build reads that file once; cross-symbol hashes, an equity and its listed debt, are counted but not linked).
- Score and check:
  ```bash
  python -m reality_engine.pilot3.doc_identity_eval tasks/dsh_tasks/doc_identity_gold.jsonl   # 20 of 20, 6 Nov 2026
  python -m pytest reality_engine/tests/test_pilot3_doc_identity.py -q                       # 21 passed
  python -m reality_engine.scripts.doc_identity_scan --symbols KEC,INFY --processes 6        # report + CSV; default D:\RealityEngine\reports, --report-dir .tmp/idreports in a workspace-write sandbox
  ```


## 13. Independent row checks (T-113, 8 Nov 2026; standing rule in `tasks/RULINGS.md`)
- The worker that wrote an extractor never checks it. Every `guidance` and `kpi_series` row is judged by
  `reality_engine/pilot3/row_checks.py`, which shares no code or word list with the extractors: its own number
  reader, its own label vocabulary (`reality_engine/pilot3/row_checks_vocab.yaml`, kept out of `lexicon/`), its own
  period arithmetic. It opens the build read-only (a WAL database in a directory the process cannot write is opened
  `immutable=1` when no `-wal` exists) and writes `row_check` (one verdict per row) and `row_check_fail` (one line
  per failed check, `hard` 1/0) to a separate database.
- Verdicts: `verified` (every applicable check passed, and a table row with several numbers is pinned by an
  independent source), `unverified` (nothing failed but something is not pinned: served with that label),
  `quarantined` (a hard check failed: never served). When unsure, an extractor writes no row.
- Hard checks: quote on the cited page; value present in the quote; a label of the metric in the quote (or, soft, in
  the 3,000 characters before it); no other metric's label between the row's label and its number, and no other
  metric named in the number's clause when the row's own is absent (`label_foreign`; a word that is also one of the
  row's own weak labels is not foreign, so "domestic sales" is a volume, not revenue); a listed order ("Gross NPA
  and Net NPA stood at a% and b% ... as against c% and d%") puts the number in the row's place (`list_order`, only
  when at least as many values as labels are printed: "revenue and order intake ... 1,550 crore" quoted up to its
  first value is not a list); a change ("reduction of 145 KT") is not stored as a level (`delta_value`); the metric
  fits the company's sector family; plausible bounds; a reported figure's period had ended when it was known; a
  guidance row has a number, a forward word, no system / industry / GDP wording near the number, no realised figure
  ("we grew at 12%" -> `past_figure`), and a target period that had not ended when said; the filed statements agree
  on revenue / PAT (`fin_conflict`). T-113 A added `part_not_total` (dimension `total` but the amount is under 15% of
  the filed figure of the same family: revenue against filed revenue, PAT against filed PAT, order against filed
  revenue, USD revenue against the median of the company's other USD revenue rows of the period), `period_word`
  (the number's sentence names 9M / nine months / YTD / H1 / half year / Q1-Q4 and the row's `fiscal_period` holds
  another; a comparative phrase such as "over Q1 FY26" and table/chart quotes do not count), and `currency` (the
  label-to-number span prints another currency than the row's unit: the nearest marker before the number decides,
  so "$ 6,724 $ 5,176" is USD and "Rs 2,050 crore ($ 246 million)" is INR at the rupee number; the corpus's
  backtick rupee glyph counts as INR).
- Soft: scaled value, several numbers in a table quote, disagreeing independent sources (`cross_doc`, another
  document AND another wording; a deck table copied into the next deck is one source), `variant` (a PAT / EBITDA /
  revenue figure labelled adjusted / before exceptional / excluding / per ... unless the metric name says so),
  `entity_mismatch` (dimension and entity name two different non-symbol subsidiaries), `dimension_word` (a total row
  whose quote names a segment word from the company's own non-total dimensions or a capitalised noun phrase in the
  60 characters before its label: "Aluminium Business EBITDA", "Renewables ... Revenues"; a window that holds the
  metric's own full name before its abbreviation, "Return on Average Equity (ROE)", is not a segment), missing
  vocabulary or page text, unknown sector, a weak or pre-quote label.
- Run:
  ```bash
  python -m reality_engine.pilot3.row_checks --db D:/RealityEngine/pilot10/pilot10.db --out <verdicts.db> \
      --profile tasks/night_loop/pilot10_profile.json --report .tmp/rc_report --sample 20 --seed 81108 --status verified
  ```
  7.6 s for 6,149 rows on the v2 dev copy (`pilot10/scratch/t113_p10_v2.db`, read-only). `--report DIR` writes
  `row_checks_summary.csv` (status counts by metric x sector x document type x extractor rule) and the sample TSV
  (id, symbol, metric, dimension, period, value, unit, quote, fails) for the human read; `--tables guidance` runs a
  database without `kpi_series`.
- Measured 9 Nov 2026, round 2 (T-113 A follow-up; dev databases read-only): v2 database guidance 47 verified / 24
  unverified / 35 quarantined (unchanged), kpi_series 4,193 / 1,493 / 357 (round 1: 4,203/1,493/347); `t105_agy.db`
  guidance 30 / 22 / 14 (unchanged; no currency or dimension hits in a guidance-only database). New hard `currency`
  quarantines 12 rows: the six HINDALCO Novelis figures stored `inr_cr` from "$ 6,724 / $ 5,176" and "capex $414 /
  $372", including HINDALCO 44300 "Adjusted Net Debt $ 6,724 $ 5,176" (the one wrong row in Opus's round-1 verified
  sample; now quarantined). The nearest-marker rule and the backtick rupee glyph keep correct rows: KEC "USD 225
  million (approximately ` 2,000 Crore" is the rupee number. New soft `dimension_word` flags 7 rows: HINDALCO
  "Aluminium Business EBITDA" stored total (3), HINDALCO "Aluminium metal production" stored total (2), SBILIFE
  "Individual New Business Premium" stored total (2); the first pass flagged 148, 136 of them the metric's own name
  before its abbreviation, so the full-name window guard is what makes the check usable. Round 1 unchanged: all six
  known-wrong v2 rows and all seven Gemini known-wrong rows quarantined; the INFY products-and-platforms row (246 of
  5,082 USD mn) is `part_not_total`; MARUTI 13 days, KEC 1,550 crore, BAJFINANCE 0.18% as 18 bps verified. Per check:
  `list_order` 53, `part_not_total` 83, `period_word` 3, `variant` 81 (soft), `entity_mismatch` 36 (soft),
  `currency` 12, `dimension_word` 7 (soft), guidance `past_figure` 1, guidance `label_foreign` 1, kpi
  `label_foreign` 1.
- Tests: `python -m pytest reality_engine/tests/test_row_checks.py -q` (18 passed, 9 Nov) builds a tiny fixture
  database from the dev column lists, puts every ticket sentence in page text verbatim, and pins each known-wrong
  and known-right verdict (currency signs both ways, a segment word before a total label, the metric-name guard);
  `python plugins/code-tools/ct.py typecheck reality_engine/pilot3/row_checks.py
  reality_engine/tests/test_row_checks.py` is clean.
- Acceptance is measured, not trusted: Opus reads a fixed random sample of `verified` rows per release (about 60 per
  stratum) on companies the extractor's worker never saw; the hold-out stays outside the repo.
