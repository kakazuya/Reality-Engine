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
  on revenue / PAT (`fin_conflict`; a filed value of 0 or below is never a witness, so a period whose only filed
  figures are 0 is "no filed figure", not a conflict; round 9: a filed line whose `unit` text names a scale
  ("₹ in mn", "rs lakh", "rs billion") is read at that scale even when the store left `scale` at 1 — the printed
  unit is the document's own word — an ambiguous unit text naming two scales is no witness, and a filed value below
  Rs 1 crore never witnesses revenue / PAT for a company whose other filed revenue is above Rs 100 crore; the
  dev-store rows this repairs are reported upstream, not fixed here); `net_cash_sign` (a `net_debt` row whose words say "net cash"
  / "cash surplus" / "net cash positive" while the value is stored positive, or "net debt" while the value is stored
  negative and the quote prints neither a minus, a bracket nor the word "minus": the sign is the opposite of the
  words); `page_unit` (the nearest scale declaration above the number on the same page — "All amounts are in million
  of Indian Rupees", "(Rs. in Mn)", "(₹ Million)", "(in Crores)", "Rs. lakh" — names a scale other than the row's
  unit; the quote's own scale word at the number wins, and a declaration in another currency does not judge a row
  printed in dollars on the same page). T-113 A added `part_not_total` (dimension `total` but the amount is under 15% of
  the filed figure of the same family: revenue against filed revenue, PAT against filed PAT, order against filed
  revenue, USD revenue against the median of the company's other USD revenue rows of the period), `period_word`
  (the number's sentence names 9M / nine months / YTD / H1 / half year / Q1-Q4 and the row's `fiscal_period` holds
  another; a comparative phrase such as "over Q1 FY26" and table/chart quotes do not count; round 8 adds a
  cumulative phrase in the number's own clause before or just after it — "up-to-date", "till date", "to date",
  "so far", "cumulative", "since April", "during the year so far" — as a conflict with a `Q` row, so a YTD capex
  stored as one quarter is caught), and `currency` (the
  label-to-number span prints another currency than the row's unit: the nearest marker before the number decides,
  so "$ 6,724 $ 5,176" is USD and "Rs 2,050 crore ($ 246 million)" is INR at the rupee number; the corpus's
  backtick rupee glyph counts as INR), `target_frame` (guidance: the number's sentence frames it as medium/long term
  or a CAGR while the target is one fiscal year; a frame about the past, "has been our CAGR", is not the target's)
  and `target_year` (guidance: the sentence prints a fiscal year or year range that is not the target's year;
  "22-24%" is a percentage, not a year, and a range counts only with an FY prefix, a four-digit end or consecutive
  years).
- Soft: scaled value, several numbers in a table quote, disagreeing independent sources (`cross_doc`, another
  document AND another wording; a deck table copied into the next deck is one source), `variant` (a PAT / EBITDA /
  revenue / net-debt figure, or a margin / ratio, labelled adjusted / before exceptional / excluding / excl. / ex- /
  pre Ind AS / post Ind AS / of which / per ... unless the metric name says so; round 8 extends it beyond
  revenue / PAT / EBITDA, and when a foreign metric's label sits inside such a qualifier phrase — "EBITDA pre Ind AS
  & excl. other income" — that is a variant, not a hard `label_conflict`; round 9 normalises the Ind AS spelling
  before matching, so a qualifier glued to digits or in brackets is still a variant: "pre IndAS116",
  "pre-Ind AS 116", "pre IND-AS", "post IndAS116", "ex-IndAS"), `same_doc_conflict` (two rows of the same
  company / metric / scope / period from the SAME document disagree by more than 1.5% after scale — a filed figure
  that matches one of them arbitrates, and a variant row is exempt), `question_next` (the quote's speaker could not
  be found and the sentence right after the number asks a question: at most unverified, never a quarantine),
  `entity_mismatch` (dimension and entity name two different non-symbol subsidiaries), `dimension_word` (a total row
  whose quote names a segment word from the company's own non-total dimensions or a capitalised noun phrase in the
  60 characters before its label: "Aluminium Business EBITDA", "Renewables ... Revenues"; a window that holds the
  metric's own full name before its abbreviation, "Return on Average Equity (ROE)", is not a segment), missing
  vocabulary or page text, unknown sector, a weak or pre-quote label, `not_pinned` (guidance: one or more of the
  five verified conditions below is missing, with the letters in the why), `scope_word` (kpi: a total row whose
  label-to-number span names a part scope: per store/unit/tonne, facility, plant, project, maintenance, segment,
  division, international, domestic, mix, share, contribution, of revenue/sales, excluding, ex-).  A row carrying
  `label_weak` or `variant` is never `verified`, even when corroborated: corroboration proves the number is printed
  twice, not that the wording names this metric or that a variant is the plain line (round 9).
- Guidance is `verified` only when ALL of these hold, else soft `not_pinned` with the missing letter(s): (a) a strong
  label of the row's own metric within 45 chars of the number, in the same sentence; (b) no part-scope word between
  that label and the number or right after the number (per showroom/store/unit/tonne unless the metric is per-unit;
  facility, plant, project, maintenance, segment, division, international, domestic, mix, share, contribution, of
  revenue/sales unless the metric is a ratio of that; excluding, ex-); (c) a forward word in the same sentence;
  (d) the target period is stated in the sentence, or the sentence says this/next/full year (or "for the year") and
  the document date gives it; (e) not a reported actual ("was", "stood at", "delivered", "reported", "for the
  quarter/9M ended" governing the number).  KPI keeps its logic with (b) as soft `scope_word` on total rows.
- Run:
  ```bash
  python -m reality_engine.pilot3.row_checks --db D:/RealityEngine/pilot10/pilot10.db --out <verdicts.db> \
      --profile tasks/night_loop/pilot10_profile.json --report .tmp/rc_report --sample 20 --seed 81108 --status verified
  ```
  7.6 s for 6,149 rows on the v2 dev copy (`pilot10/scratch/t113_p10_v2.db`, read-only; round 8: **11.1-11.3 s**,
  still under the 15 s accept). `--report DIR` writes
  `row_checks_summary.csv` (status counts by metric x sector x document type x extractor rule) and the sample TSV
  (id, symbol, metric, dimension, period, value, unit, quote, fails) for the human read; `--tables guidance` runs a
  database without `kpi_series`.
- Measured 8 Nov 2026, round 3 (out-of-pilot generalisation; companies ALKEM, TEJASNET, PIDILITIND, UFLEX,
  KALYANKJIL, ASHOKA; 1,365 guidance rows from an older extractor, four of six sectors unknown, no `kpi_series` and
  no filed tables): **99 verified / 907 unverified / 359 quarantined -> 80 / 882 / 403**. Reading the seeded
  40-row samples before the fixes: of 40 verified, **21 were not a correct forward target** (gross margin stored as
  EBITDA 3, a reported quarter figure 1, capex-% of revenue / order-book share / revenue-mix share / spending-%
  worded as `revenue_growth` 6, per-showroom / project / maintenance amounts stored as company capex 4, a delta
  stored as a level 1, a wrong fiscal year or a CAGR / medium-term frame stored as one FY 5, a preference-share
  coupon as `interest_cost` 1). Of 40 quarantined, 4 were right: two `label_foreign` on the word "mix" (121, 1214),
  one `third_party` because "repo" matched inside "report" (522), one `label_conflict` on a growth row with an
  earlier revenue mention (1069). The fixes changed 61 rows (9 verified->quarantined, 11 verified->unverified, 38
  unverified->quarantined, 2 quarantined->unverified, 1 quarantined->verified 522); of the original verified sample
  10 changed and all 10 were wrong. Rules: `target_frame` and `target_year` above; "gross margin" is its own metric,
  not an `ebitda_margin` label (3 wrong rows unverified); a denominator no longer hides the metric's own name ("17%
  of EBITDA margin" keeps its label, "2-3% of revenue" does not); `delta_value` reads "improve by" and checks every
  occurrence (the BAJFINANCE opex 25-40 bps rows are improvements, not levels); `list_order` ignores delta and glued
  ("Q2") numbers; `third_party` "repo" is word-bounded. Residual wrong rows still verified: a reported quarter (16),
  capex %-of-revenue worded as growth (723, 193), per-facility and maintenance capex (147, 769, 783), a project
  margin (1045), a preference-share coupon (664), "for 2021" (964); 121/1214 (`label_foreign` "mix") and 1069 stay
  wrongly quarantined. On the pilot dev databases the change is small: v2 guidance 47/24/35 -> 43/24/39 and agy
  30/22/14 -> 27/21/18 (six genuine catches: BAJFINANCE opex improvements, HINDALCO cost delta, ETERNAL 60% CAGR,
  SBILIFE long-term), kpi unchanged 4,193/1,493/357; all six v2 and seven Gemini known-wrong rows stay quarantined.
  Round 2 unchanged: `currency` 12, `dimension_word` 7 (soft), `list_order` 53, `part_not_total` 83, `period_word` 3,
  `variant` 81 (soft), `entity_mismatch` 36 (soft).
- Measured 8 Nov 2026, round 4 (verified as a high bar; same unseen6 database): **80 verified / 882 unverified /
  403 quarantined -> 12 / 946 / 407**. Reading the fresh seed-4 samples: unseen6 has only 12 verified left, **7 right
  and 5 wrong** (173 and 193 store a past "increased sales investment by 21%/23%" as revenue growth; 237 and 186 a
  revenue-mix / order-book share; 990 an EBITDA margin); pilot10 kpi **20 of 20 right** (several `multi_number` rows
  corroborated by a second source). 68 previously verified unseen6 rows became unverified; of 15 re-read, 7 were
  wrong rows the gate correctly unpinned and 8 were right-ish but not provable from the quote alone (label 50-75
  chars away, period not stated, "Q4" without a year); 265 (label at 60 chars) and 80 (bare Q4 + doc date) are
  over-strict on one criterion and stay unverified by design. Pilot dev databases: v2 guidance 43/24/39 ->
  **19/48/39**, kpi 4,193/1,493/357 -> **4,168/1,518/357** (25 rows now carry `scope_word`); agy 27/21/18 ->
  **15/33/18**. Two general bugs the reading exposed and fixed: a sentence break at "Rs." truncated the number's
  sentence, so its forward word and period fell outside it; and "Q3 FY2026" was read as FY20 by the period token,
  which quarantined a correct SUNPHARMA PAT row (45728, verified again). All six v2 and seven Gemini known-wrong rows
  stay quarantined.
- Measured 8 Nov 2026, round 5 (KPI wrong classes; pilot10 v2 and the unseen6 guidance set): v2 kpi
  **4,168/1,518/357 -> 3,851/1,773/419**, v2 guidance 19/48/39 -> **19/46/41**, unseen6 guidance 12/946/407 ->
  **7/934/424**, agy 15/33/18 unchanged. New rules: `multi_number` now applies to ANY quote whose label is followed
  by more than 2 values of the row's unit (1,481 rows; verified only when corroborated, which is what makes the
  pilot10 tables serve as unverified); soft `uncorroborated` for a total revenue / PAT / EBITDA / order row with no
  filed statement and no second source (253); hard `not_company_speaker` for a question, "you said", "I wanted to
  understand", "can you", "could you", "what is", or an Analyst / Moderator speaker line as the last speaker before
  the quote; hard `range_value` when the number is one end of a printed range ("5 to 6000"; adjacent-number rule, so
  "FY26 to 7.54%" and negative comparisons are not ranges); hard `unit_kind` for a days row with no days word next
  to the number, and a percent row with no % / per cent / bps unless its label names the ratio ("EBITDA Margins 7.1"
  and "Annualised ROA 4.5" are table cells with the unit in the label; "Annualised loan loss 2.05" is not). The
  guidance read from round 4 is now hard too: another metric's strong label nearer the number than the row's own
  (within 45 chars, denominators excluded) and a past-tense verb governing the number (`increased ... by 21%`)
  quarantine. Reading the fresh seed-5 samples: **pilot10 kpi 20 of 20 right** (XBRL segment rows, margins, CRAR,
  PAT, NWC days, per-share values) and **all 7 verified unseen6 guidance rows right**. False-positive passes the
  reading exposed and fixed: `range_value` first fired 21 times, on "FY26 to 7.54%" and on negative comparisons;
  `unit_kind` first quarantined ~95 correct table cells until the label-naming-the-ratio rule; `not_company_speaker`
  first quarantined a KEC answer because "moderator" appeared 250 chars earlier, so only the last speaker label
  counts. All six v2 and seven Gemini known-wrong rows stay quarantined; the NPA list rows are now unverified (four
  values in one sentence, no second source), never quarantined.
- Measured 8 Nov 2026, round 6 (independent corroboration and structural analyst detection): v2 kpi
  **3,851/1,773/419 -> 3,851/1,746/446**; v2 guidance 19/46/41, unseen6 7/934/424 and agy 15/33/18 unchanged.
  `multi_number` corroboration is now independent of column reading: only a filed figure or a source quote that is
  single-valued for the label (at most one value of the unit after the label) corroborates a multi-column row; two
  multi-column quotes agreeing do not, and `cross_doc` witnesses must be single-valued too (the UFLEX
  "10.3% 10.2% ... +62bps" pair no longer verifies; a table then serves as unverified unless another document prints
  one number). Analyst detection is structural on transcripts: the speaker turn containing the quote (name line
  "Name:" / "Name -") must be in the document's management list (role lines and participant headings on the first
  four pages) or answer the question just before, else hard `not_company_speaker`; "trying to understand",
  "my question" and "just wanted to" join the phrase list. Reading: the TEJASNET "net cash balance ... just trying
  to understand how" row is quarantined, and the 33 remaining speaker quarantines on pilot10 v2 are analyst turns
  (Vaibhav Shah, Amit, Arafat Saiyed, Sumit Kishore, Sudeep Bora, Nipun Khemka, Shreya Shivani, Shubhranshu Mishra,
  Kunal Shah, Bharat Shah), including the "leverage was 4.9x" row that round 5 had verified; a first pass
  quarantined 2,353 rows because a "Name:" line on a deck page was read as a speaker turn, so the structural check
  is transcript-only with a readable participant list, and the list scan reads role lines ("MANAGEMENT: MR. VIMAL
  KEJRIWAL – MANAGING DIRECTOR") instead of losing names at a line break. All six v2 and seven Gemini known-wrong
  rows stay quarantined; guidance results are unchanged. (The round-6 open case 45254 is closed: SBILIFE FY25 PAT
  is 24.1 bn, FY24 18.9, so that row was right.)
- Measured 8 Nov 2026, round 7 (disagreement, witness validity, history and scale): v2 kpi
  **3,851/1,746/446 -> 3,709/1,888/446** in about 12 s; v2 guidance 19/46/41, unseen6 7/934/424 and agy 15/33/18
  unchanged. Four rules: (1) any independent witness more than 1.5% away for the same key makes both sides
  unverified (`cross_doc`, 1,157 rows; the KALYANKJIL 33,818 mn / 5,486 mn pair no longer verifies); (2) a witness
  counts only when its own row passes every hard check and is not multi_number (the ASHOKA "Profit After Tax 72.0
  134.7 -47% 34.2" row is not corroborated by the single-valued "Profit After Tax of 34.2 crore in Q3 FY23" row,
  because that witness fails its own `period_word`; the hidden-build witness could not be inspected, so the exact
  sentences are pinned in the test); (3) a quote with more than 5 values of the unit after the label
  (`history_row`, 247) and (4) an amount below 10 in `inr_mn` / `inr_cr` on a total capex / revenue / PAT / EBITDA /
  net-debt / order row (`scale_doubt`, 12) verify only on a filed figure. Reading the fresh seed-7 pilot10 kpi
  sample: **20 of 20 right** after checking each figure against sibling rows — 42113 AUM 353,765 is the standalone
  AUM (the consolidated 484,477 rows carry basis `consolidated`), 45457 SBILIFE APE 99.2 is the H1FY26 column and
  45456 NBP 121.7 the same column on the same slide, 41354 KEC 5.2% is standalone against 7.0% consolidated, and
  44079 HINDALCO gross debt 63,330 is the Q1FY26 column of a four-value history. All six v2 and seven Gemini
  known-wrong rows stay quarantined.
- Measured 8 Nov 2026, round 8 (four defects from the Opus read plus four hidden-hold-out additions), same two dev
  dbs: unseen6 1,152 rows **kpi 124/734/118 -> 93/711/172**, guidance 8/110/58 -> **8/111/57**; pilot10 v2 6,149
  rows **kpi 3,709/1,888/446 -> 3,534/2,072/437**, guidance 19/46/41 unchanged, in **11.1-11.3 s** (accept < 15 s).
  Ticket rows: 24 ALKEM +19 bn net cash -> `net_cash_sign`, 985 ASHOKA "capex for up-to-date" Q2 -> `period_word`,
  245 TEJASNET analyst -> `not_company_speaker`; all three quarantined (24 was verified, 985 and 245 too). The
  speaker line for 245 is on page 9 and the quote starts on page 10, so `speaker_turn` now reads one page back;
  when no speaker is found a question in the sentence after the number is soft `question_next` (0 hits on both dbs,
  always caught as unverified rather than quarantined). The previous-page fallback exposed prose lines that look
  like a speaker ("Coming to the order book status", "Some of the key highlights include"), so a speaker label must
  be a person / role: this removed 4 false quarantines on unseen6 and 9 on v2 (e.g. Paresh Mehta's EBITDA margin
  8.4%, INFY headcount 332,000), none of them an analyst. `net_cash_sign` fires twice on unseen6 (ALKEM net cash
  +19 bn, rows 13 and 24) and zero times on v2: HINDALCO "net debt is minus INR6,000 crores" stored -6,000 is
  right once the word "minus" counts as a printed sign. `page_unit`: 54 unseen6 quarantines (UFLEX / ASHOKA pages
  declaring "(` in lakhs)" / "(rs. in lacs)" while the row says `inr_cr`; 10 read, all a wrong scale, e.g.
  1,466,251 `inr_cr` where the page's lakh figure is 14,662 cr) and 6 v2 rows (BAJFINANCE PAT 19,332 crore stored
  `inr_mn` on a "₹ in crore" page, all already quarantined); a declaration in another currency does not judge a
  dollar row on the same page (INFY USD revenue rows stopped being false positives). `same_doc_conflict` is soft:
  473 rows on unseen6 and 795 on v2; the pairs read are genuine same-document disagreements (ALKEM revenue
  30,409.1 `inr_cr` vs 86,967 `inr_mn`, ALKEM EBITDA margin 14.4% vs 61.9%, KEC press release EBITDA 430 vs 308,
  margins 7.1 / 6.2 / 7.0 / 5.6, HINDALCO EBITDA/t 1,467 vs 2,331); 28 unseen6 and 156 v2 verified rows became
  unverified because of it, and a filed figure that matches one side arbitrates the pair. Variant words extended to
  net debt and every margin / ratio: 7 kpi + 1 guidance rows on unseen6, 111 kpi + 1 guidance on v2; the 35 newly
  failing v2 rows read are all genuine ("before one-time actions", "Adjusted return on average equity", "leverage
  ratio (Adjusted Net Debt / TTM Adjusted EBITDA)"), "as per" is not a per-unit variant, and a foreign label inside
  the qualifier phrase changes a hard `label_conflict` into the soft variant. A filed value of 0 or below is never
  a witness: 627 non-positive `fin_annual_line` values on unseen6 and 463 on v2, but **0** quarantines removed on
  either db (no kpi key's only filed figures were non-positive). Bare "leverage" is now a weak label of
  `net_debt_to_ebitda`, not a strong one: v2 `label_weak` 49 -> 96 (the 48 new BAJFINANCE / HINDALCO "Leverage
  ratio ..." rows serve unverified, and 5 "leverage ratio at 3.5x and liquidity ..." rows moved hard
  `label_foreign` -> soft label_weak). `question_next` 0 hits on both dbs.
- Measured 8 Nov 2026, round 9 (same two dev dbs; round-8 verdicts -> round 9): unseen6 unchanged **93/711/172** kpi
  and 8/111/57 guidance; pilot10 v2 kpi **3,534/2,072/437 -> 3,527/2,079/437**, guidance 19/46/41 unchanged, in
  11.1 s. Four rules. (1) `label_weak` and `variant` never verify even when corroborated: **7 v2 rows moved
  verified -> unverified** (HINDALCO `net_debt_to_ebitda` "leverage ratio at 3.7x" 44121/44139/44149, "Net Leverage
  Ratio 4.1" 44305/44340, MARUTI `export_volumes` 46034/46061), 0 on unseen6; no variant row was verified before, so
  that half moves 0. (2) The Ind AS qualifier is normalised before matching, so "pre IndAS116", "pre-Ind AS 116",
  "pre IND-AS", "post IndAS116" and "ex-IndAS" count (`EBITDA margin (pre IndAS116) at 19.7%` is pinned by a test);
  the dev dbs hold none, so variant stays 1 guidance + 7 kpi on unseen6 and 1 + 111 on v2. (3) A filed line whose
  `unit` names a scale is read at that scale even when `scale` is 1, and a filed value below Rs 1 crore never
  witnesses revenue / PAT for a company whose other filed revenue is above Rs 100 crore: 93 unseen6 + 11 v2
  `fin_annual_line` rows have the disagreement (the full list is reported upstream as a store bug, not fixed here);
  30 unseen6 and 4 v2 witness rows get the printed scale (ALKEM FY26 revenue 106,342 "₹ in mn" -> ₹10,634 cr,
  ASHOKA FY24 revenue 979,846 "rs lakh" -> ₹9,798 cr, SBILIFE FY26 PAT 24.7 "rs bn" -> ₹2,470 cr, SUNPHARMA FY26 PAT
  115 "₹ billion" -> ₹11,500 cr), changing 12 unseen6 and 3 v2 witness keys; the sub-crore rule drops 2 KEC Q1FY27
  PAT values (₹52 lakh) on v2 and none on unseen6. **0 fin_conflict quarantines go away** (p10 stays 151, unseen6 0)
  and no other verdict moves: the correct quarter-view rows already witnessed these keys, so the repair protects
  future builds rather than changing these two dbs.
- Tests: `python -m pytest reality_engine/tests/test_row_checks.py -q` (59 passed, 8 Nov) builds a tiny fixture
  database from the dev column lists, puts every ticket sentence in page text verbatim, and pins each known-wrong
  and known-right verdict (currency signs both ways, a segment word before a total label, the metric-name guard,
  gross margin as its own metric, the denominator keep rule, "improve by" as a delta, medium-term / CAGR /
  fiscal-year mismatches with their comparative and percentage-range controls, "repo" not matching "report", each
  of the five verified conditions a-e, kpi `scope_word` with the per-unit exemption, the "Rs." abbreviation and a
  four-digit FY year, multi-column `multi_number` for any rule, `not_company_speaker`, `range_value`,
  `uncorroborated` and `unit_kind`, the nearer-foreign-label / past-tense guidance rules, two multi-column quotes
  failing to corroborate each other while a single-valued witness does, speaker turns by management list vs
  analyst name vs answering-a-question, the 1.5% disagreement rule, a witness failing its own hard check, a
  history row that only a filed figure pins, `scale_doubt` with its filed exemption, `net_cash_sign` both signs and
  the printed minus / bracket / "minus" controls, a cumulative capex stored as a quarter, a question starting on
  the previous page, the soft `question_next` fallback, a prose line that is not a speaker, same-document evidence
  both agreeing and disagreeing (a variant peer exempt), a zero filed figure as no witness, the page-unit
  declarations and their currency and quote-unit exemptions, the extended variant words, "as per" not matching,
  bare leverage as a weak label, corroboration failing to verify a weak or variant label, the glued / bracketed
  Ind AS qualifiers, a filed unit that names its own scale, and a sub-crore filed value that cannot witness);
  `python plugins/code-tools/ct.py typecheck reality_engine/pilot3/row_checks.py
  reality_engine/tests/test_row_checks.py` is clean.
- Acceptance is measured, not trusted: Opus reads a fixed random sample of `verified` rows per release (about 60 per
  stratum) on companies the extractor's worker never saw; the hold-out stays outside the repo.
- **Serving (T-113 B).** `python -m reality_engine.pilot3.build --part checks` (last in `all`, after `guidance` and
  `notes`) runs the same checker into a temp file beside the build and copies `row_check` and `row_check_fail` into the
  build in one transaction (`reality_engine/pilot3/build.py`; `row_checks.py` itself is unchanged and still writes its
  own output). A build that holds no `guidance`, or no financial tables, skips only the missing table.
  `pilot3_kpi`, `pilot3_guidance` and the stated-ratio part of `pilot3_ratio` (`plugins/reality-data/server/lookups_pilot3.py`,
  tool text in `server.py`) LEFT JOIN the verdicts by `tbl` + `row_id`: a `quarantined` row is dropped unless the call
  passes `include_quarantined=true`, and every served row carries `check_status` (`verified` / `unverified`, NULL when
  the check part has not judged it) plus `check_note` (the soft checks' names) on an unverified row. An `available` /
  `held_options` / `held_period_dimension` hint never names a metric whose every row is quarantined. Any part that
  rewrites `guidance` or `kpi_series` (`guidance`, `kpi`, `extract`; all of them in `all`) first deletes that table's
  verdicts, because a rebuilt row has a new id and an old verdict would hide or label the wrong row: **re-run
  `--part checks` after any kpi or guidance rebuild**. A build without
  `row_check` serves exactly as it did. Measured on the dev copy `D:/RealityEngine/pilot10/scratch/t113_p10_serve.db`
  at round 2, 8 Nov: 7.3 s for the part and 6,149 verdicts — guidance 46 verified / 26 unverified / 34 quarantined,
  kpi 4,249 / 1,422 / 372 (the round-8 checker itself takes 11.1-11.3 s on v2; re-measure the part before quoting
  its time again);
  `kpi('BAJFINANCE','nnpa_pct','FY25')` fell from 8 rows (the 1.18 gross-NPA row among them) to 4,
  `guidance('HDFCBANK')` 3 -> 1 and `guidance('SBILIFE')` 4 -> 2. Tests: `reality_engine/tests/test_pilot3_row_check_serve.py`
  (7 passed); `python -m unittest plugins/reality-data/tests/test_lookups_pilot3.py` (24 passed, no verdict table).
