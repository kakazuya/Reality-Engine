# Task — source the missing originals (ARs, material announcements, deck gaps, RBI): Drive first, then NSE, BSE last

## Goal
Shivam's ruling (2026-10-28 evening): don't wait for the BSE concall run, and don't re-download what we already hold. Run the exchanges in parallel. The order of sources for each missing original is fixed:

1. **Already held:** on Drive or on D:.
2. **NSE.**
3. **BSE**, only for whatever is still missing after 1 and 2.

The missing sets are in `tasks/RAW_ORIGINALS_INVENTORY_2026-10-27_REPORT.md` §8:
- annual reports FY25+: 1,794 strict (2,845 window);
- material announcements: about 8,540 of 15,250 in `corporate_documents` ANNOUNCEMENT, after dropping procedural ones;
- deck filings: 1,417. 1,345 of them have a `deck_sources` row but the file is absent locally;
- 108 RBI PDFs: on `gdrive:.../macro_pdfs` only.

This is a raw fetch only. No chunking, tagging, embedding or DB loading (golden rule, AGENTS.md).

## Do
1. **Build the missing lists** with bounded `connect_ro` queries, reusing the inventory report's definitions. Write `.tmp/missing_<kind>.csv` with: key, isin, symbol, known_at, title, source_url and size where known.
2. **Held check:**
   - List the Drive folders named in the report with `rclone lsf -R --format pst` (read-only), plus the D: folders.
   - Match by file name or attachment key, and by sha or size where available.
   - Output `held_on_drive.csv` with the exact `rclone copy` commands to bring each one to `D:\RealityEngine\raw\<kind>\`. **Do not run the copies.**
3. **NSE match** for the rest:
   - Use the NSE pilot JSONL and `nse_announcements.py` listing logic.
   - Match per company by ISIN, date within ±2 days, and the category/keyword family:
     - annual report → NSE `desc` "Annual Report" / Reg. 34(1);
     - deck → "Investor Presentation";
     - material → the material bucket.
   - ARs also have NSE's annual-reports API (`/api/annual-reports?index=equities&symbol=`); find and verify the endpoint shape from one cached response or the code. No live calls in this task, so if none is cached, say so and give the plan.
   - Output `nse_match.csv` (BSE key → NSE attachment URL) and `bse_only.csv` (no NSE match).
4. **One downloader:** `reality_engine/scripts/fetch_originals.py`.
   - Input: a list CSV (url, dest path, key).
   - Arguments: `--exchange nse|bse|any`, `--interval` (NSE ≥3 s; BSE ≥2.5 s per stream), resume (skip files already present, `%PDF` magic check), back-off on 403/429/503, a manifest CSV.
   - Downloads go to D: only. **No DB writes.**
   - Offline tests in `reality_engine/tests/test_fetch_originals.py`.
5. **Rate plan.** Total budgets: BSE ≤76/min, NSE ≤20/min. Already running:
   - BSE concall: 2.5 s, about 24/min;
   - BSE decks: `fetch_decks bse --pause 2.0`, about 20–25/min;
   - NSE announcements: 3 s, 20/min, so NSE is full until about 08:00 tomorrow.

   Propose the start order and intervals that keep both exchanges full without crossing their caps. For example: BSE ARs now at 4 s, NSE matches after the NSE announcement run.

## Rules
- **No network** except read-only `rclone lsf` / `rclone size` on gdrive.
- Write only in this worktree. All DBs read-only. No commits.

## Acceptance checks
1. A count per kind: missing → held on Drive / matched on NSE / BSE-only, plus GB and estimated hours at the planned rates.
2. The downloader tests pass.
3. The exact commands, in start order.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_fetch_originals
```

## Report
Give:
- the counts table;
- 10 hand-checked NSE matches (BSE title vs NSE desc and date);
- the commands;
- your tool-call count.
