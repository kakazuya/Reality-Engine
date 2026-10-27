# Task — sector label accuracy pilot: are NSE and BSE industry labels right for small caps?

## Goal
Shivam's decision 8 (audit §11) waits on this pilot. How often does each exchange label match what the company actually does?
- The NSE label is the 4-level `company_industry`: macro / sector / industry / basic_industry.
- The BSE label is the industry/sector shown on BSE's company header.

The audit found 2,177 companies with no sector. The question is whether BSE's label can fill them, and whether either label can be trusted for small caps.

## Sample (fixed seed 20261028; write the list before reading any evidence)
- **200 companies**, small-cap and micro-cap only. Use `master_companies.market_cap_tier` or the latest close × shares if that is missing.
- Stratify the 200 as follows:
  - **150 that have an NSE label** in `company_industry`, spread across at least 25 NSE sectors. Over-sample conglomerates and companies with 2+ reported segments, to 40 or more.
  - **50 BSE-only or unlabelled companies** (no `company_industry` row).
- Every company must have business evidence held locally from FY2024-25 on: AR segments or financials in `ar_facts.db`, XBRL segment results, deck text, or AR/deck chunks. If one doesn't, replace it with the next draw and record the replacement.

## Labels
- **NSE:** read from `company_industry` with `connect_ro`.
- **BSE:**
  - Fetch the header for only these 200 scrip codes, using the project client in `reality_engine/ingestion/bse_fundamentals_client.py`.
  - Endpoint: `ComHeadernew/w?scripcode=…`. The bulk `ListofScripData` endpoint returns Access Denied, so don't use it.
  - Use the client's headers and pacing, ≤20 requests/min. A results-notes job is also using BSE at up to 76 requests/min.
  - Save the raw JSON responses under `.tmp/bse_header/` in this worktree.
  - If the network is unavailable in this sandbox, finish the NSE half. Report the BSE half as blocked; don't try workarounds.

## Ground truth: what the company actually does
For each company, from the local evidence:
- revenue share by segment (latest FY);
- the main products or services, in one line;
- the evidence used, with store and table, doc and page, or chunk id.

Then grade **each** label at two levels, sector and industry/basic industry, as one of:
- `correct`;
- `partly`: right sector, wrong industry, or a label for only a minor segment;
- `wrong`;
- `stale`: right for the old business but not the current one;
- `cannot_tell`: the evidence is too thin.

Add a one-line reason with each grade.

## Output (this worktree)
1. `tasks/sector_pilot/sector_label_pilot.csv`: one row per company with
   - isin, symbol, bse_code, bucket, NSE four levels, BSE industry/sector;
   - the segment split, main business and evidence refs;
   - the four grades (NSE/BSE × sector/industry) with reasons.
2. `tasks/sector_pilot/REPORT.md`:
   - **Accuracy:** accuracy for NSE and BSE at each level, overall and split by single- vs multi-segment companies and by small vs micro.
   - **Error types:** counts for the error types, e.g. conglomerate, pivot/stale, too-generic ("Diversified"/"Miscellaneous"), plainly wrong.
   - **Unlabelled group:** for the 50 unlabelled companies, BSE accuracy alone. This answers whether BSE can fill the gap.
   - **Recommendation:** what to do among these options. Use BSE as a separate column; build a mapping; derive our own label from segment revenue; or a mix.
   - **Examples:** 10 worked examples of mislabels.

## Rules
- Read-only everywhere except this worktree. Use `reality_engine.db.readonly.connect_ro` and keep queries bounded.
- Network is allowed only for BSE header calls on the 200 sample codes. No other sites, no paid APIs, no commits.
- Don't open `results_notes.db` for writing; read it with `connect_ro` only.
- Never guess a business from the company name alone. If the evidence is thin, the grade is `cannot_tell`.

## Acceptance checks
1. 200 rows, at most one per ISIN. The strata (150/50, 25+ NSE sectors, 40+ multi-segment) are met, or the shortfall is explained.
2. Every graded row cites at least one piece of evidence that can be traced.
3. `cannot_tell` stays at or below 15% of rows. If it is higher, say which evidence is missing.
4. The report gives the accuracy table and a recommendation.

## Test command(s)
```bash
python -c "import csv;r=list(csv.DictReader(open('tasks/sector_pilot/sector_label_pilot.csv',encoding='utf-8')));assert len(r)==200 and len({x['isin'] for x in r})==200;print('ok')"
```

## Report
Give:
- the accuracy table;
- the recommendation;
- how many BSE headers were fetched or failed;
- your tool-call count.
