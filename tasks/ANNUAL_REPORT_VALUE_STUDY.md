# Annual Report Value Study: strategy and pipeline

Self-contained brief for a dedicated session (written 2026-10-10). **Read this file only.** Do not open or change
other workspace files unless a step below names them. Do not edit code in `reality_engine/`, do not touch
`tasks/STATE.md` or `tasks/FRAMEWORK.md`, and write all study output under `tasks/ar_study/`.

## 1. Why this study

Annual reports (ARs) are the biggest, least dense documents we hold. Before downloading and storing more of them,
we want to know, from reading real reports, **which sections carry information that the concall and investor
presentation (PPT) of the same year do not**, and which sections can be dropped.

Facts from the main session (2026-10-10):
- A median AR is ~229 pages and ~870k characters of text (~250k tokens). Range p10-p90: 140-445 pages, 360k-1.4M chars.
- Text layer is good: in a 60-report sample, 3.4% of pages had <200 characters and none of the 60 was a scanned
  document. Read the text layer; OCR only isolated image pages (charts, signatures).
- The 3,501 ARs already chunked into the search index make up 1.36M chunks (388 per AR, 3.1 GB of text), two-thirds of
  the whole index. A concall gives ~20 chunks, a PPT ~4. Storing ARs whole does not scale.
- Usable concalls start in 2022 (decision: use concalls from 2022 onwards only; do not look for older ones).

The question to answer: **section by section, keep as text / extract into a table / keep only if it changed from last
year / drop**, and which sections matter only in specific situations (fraud or stress building up, a policy change,
related-party leakage, auditor unease), with real examples.

## 2. Plan

**Phase 1: two reports (do this first, then stop and report to Shivam).** Two companies from different sectors,
one year each, plus that year's concall(s) and PPT for the same company. Purpose: test the reading method, the scoring
sheet and the token cost before scaling up.

**Phase 2: 10-12 reports (only when Shivam says go).** Suggested spread: a bank, an NBFC, IT services, FMCG, pharma,
capital goods, chemicals, auto/auto ancillary, real estate, a small-cap manufacturer, and 1-2 companies that later
had governance trouble (to see whether the warning signs were in the report beforehand). Pick from companies that
have the AR, a concall and a PPT for the same fiscal year in our data (query in §4).

**Phase 3: write-up.** One ranked section map (keep / table / changed-only / drop), the list of items worth extracting
into tables, the situational signals with examples, and an estimate of chunks per AR under the proposed rules
(target: under ~60 chunks per AR, versus 388 today).

## 3. Reading method and budget

- **Reader: Sonnet**, via the Agent tool with `model: "sonnet"`, reading the extracted text (not page images). The job
  is judgement (is this new? does a footnote hint at trouble?), where Sonnet is clearly better than Haiku.
- A full AR does not fit one agent comfortably. Split each AR into its sections (§5) or into page ranges of ~40-60
  pages, one agent per part. Give every agent the same company's concall/PPT text for that year so it can judge
  redundancy.
- Budget (Pro plan, 5-hour window): ~250k tokens per AR. Rough guide from Haiku waves (300 pages ≈ 10% of a window):
  2 ARs with Sonnet ≈ 15-20% of a window; 12 ARs ≈ most of one window. **Stop at 80% of the 5-hour window** (Shivam's
  standing rule); check with the `get_usage` tool before each batch. Report actual usage after Phase 1.
- Main session runs a deck extractor and an hourly ingestion job in the background. **Do not stop, restart or edit
  them**, and do not use the GPU.

## 4. Where the data is

- Main DB (read-only for this study): `reality_engine/data/equity_intelligence.db` (SQLite, WAL). Open with
  `sqlite3.connect('file:...equity_intelligence.db?mode=ro', uri=True, timeout=60)`.
- `corporate_documents`: one row per filing. Columns used: `id, isin, symbol, doc_type, title, source_url,
  local_file_path, fiscal_period_end, publication_date, bse_dissem_ts, call_date, pit_source`.
  - `doc_type` = `'ANNUAL_REPORT'` (26,614 rows, 3,514 downloaded, i.e. `local_file_path` not null),
    `'CONCALL_TRANSCRIPT'` (9,652 downloaded), `'INVESTOR_PRESENTATION'` (1,615, 2026 only).
  - `doc_date` is the crawl date (2026-08) on most rows: **do not use it**. Use the view `v_document_pit`
    (`pit_ts`, `pit_date`, `pit_basis`) for the real filing date. AR dates are being filled from BSE's annual-report
    API by the main session (`pit_source='bse_ar_api'`); if an AR still has no date, its fiscal year can be read from
    the report itself.
- Older PPTs (decks): `reality_engine/data/deck_figures.db`, table `deck_sources` (`isin, symbol, local_path, sha256,
  known_at, status`), PDFs under `reality_engine/data/decks/`. Figures already read from decks are in table `facts`
  there (`sha256, page_no, metric, period, raw_number, value, unit, is_final`).
- `master_companies` (in the main DB): `isin, nse_symbol, bse_code, company_name, industry, sector, market_cap_tier,
  is_nifty200, is_nifty500` for choosing a sector spread.

Starter query (companies with a downloaded AR plus a downloaded concall, with sector):
```sql
SELECT m.company_name, m.sector, m.market_cap_tier, a.local_file_path AS ar_path, v.pit_date AS ar_date,
       (SELECT COUNT(*) FROM corporate_documents c WHERE c.isin=a.isin AND c.doc_type='CONCALL_TRANSCRIPT'
          AND c.local_file_path IS NOT NULL) AS concalls
FROM corporate_documents a JOIN master_companies m ON m.isin=a.isin
LEFT JOIN v_document_pit v ON v.id=a.id
WHERE a.doc_type='ANNUAL_REPORT' AND a.local_file_path IS NOT NULL
ORDER BY m.sector, m.company_name;
```

Text extraction: `import pymupdf; d = pymupdf.open(path); d[i].get_text()` (0-based pages). Write each part's text to
`tasks/ar_study/text/<symbol>_<fy>_p<start>-<end>.txt` so agents read files, not the PDF. On Windows run Python via
the Bash tool or the full path `C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe`; bare `python` in
PowerShell hits a broken `C:\Windows\System32\python` stub.

## 5. Section map of an Indian annual report (what to look for)

Order varies; headings are reliable. Each row is a hypothesis to confirm or reject.

| Section | Hypothesis |
|---|---|
| Corporate overview, chairman/MD letter | Mostly marketing; may hold strategy shifts and targets. Probably overlaps PPT. |
| Directors' report | Business sections (operations, capacity, expansions, subsidiaries, material changes after year end) may add facts; much is statutory boilerplate. |
| Management Discussion & Analysis (MD&A) | Industry view, segment performance, risks, outlook. Likely overlaps concall; check for risks not said on the call. |
| Corporate governance report | Boilerplate; check board/auditor changes, resignations with reasons, pending complaints, related-party policy, penalties. |
| BRSR (sustainability) | Structured numbers: employees, plants/locations, energy/water, customer concentration, markets. Table candidates. |
| Auditor's report (standalone and consolidated), CARO annexure | Key audit matters, qualifications, emphasis of matter, going concern, CARO remarks (loans to related parties, defaults, frauds reported). Likely high value when non-standard. |
| Secretarial audit report (MR-3) | Non-compliances and qualifications. |
| Financial statements | Main statements already come from XBRL; skip unless something contradicts them. |
| Notes to accounts | Segment data, contingent liabilities, commitments, borrowings and maturities, related-party transactions, subsidiaries/associates (AOC-1), receivable/inventory ageing, changes in accounting policy, subsequent events. Table candidates and possible hidden signals. |
| Annexures: remuneration ratios (Rule 5), AOC-2 related-party contracts, CSR spend, shareholding | Numbers only; table candidates. |
| AGM notice | Usually boilerplate; check special resolutions (borrowing limits, related-party approvals, fund-raises, ESOPs). |

## 6. Scoring sheet (one row per section per report)

Save as `tasks/ar_study/scores_<symbol>_<fy>.csv` with columns:

`section, pages, tokens_est, new_info (none/some/lot), overlaps_concall_ppt (yes/partly/no), when_useful
(always/situational/never), situation (fraud-stress / policy-change / related-party / auditor / capex / other / -),
items_to_extract, example_quote_or_page, verdict (keep-text / table / changed-only / drop)`

Rules for agents:
- Judge against the concall and PPT text you were given; "new" means not stated there.
- Quote the page number for every claimed signal. Do not invent findings: "nothing new" is a valid answer.
- Situational items: say what situation would make it matter and why (e.g. "contingent liability for a tax demand
  equal to 40% of net worth; only matters if the case is lost").

## 7. Phase 1 report back

Put in `tasks/ar_study/PHASE1_FINDINGS.md`: the two companies and years, actual token/usage cost, the filled scoring
sheets summarised, the top 5 valuable sections and top 5 droppable ones, 2-3 situational examples, and any change
to the method before Phase 2. Then stop and wait for Shivam.
