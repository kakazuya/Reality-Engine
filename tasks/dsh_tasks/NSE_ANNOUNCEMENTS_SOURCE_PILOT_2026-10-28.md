# Task — NSE corporate-announcements source: pilot on 50 companies

## Goal
Build a reusable fetcher for NSE corporate announcements. We need it for two things:
- NSE-only concall transcripts: 1,519 old corpus rows have no BSE news id;
- every other NSE-only filing: 322 companies have no BSE listing.

This is a **raw fetch only**. The golden rule in `AGENTS.md` allows raw fetches. No chunking, tagging or embedding.

## Do
1. **Find NSE's public corporate-announcements endpoint** (the JSON behind nseindia.com → Companies → Corporate Filings → Announcements).
   - It supports a symbol filter, a date range and a subject/category.
   - Use `reality_engine/ingestion/nse_client.py` if it already has NSE session handling. NSE needs a cookie warm-up: GET the home page, then call the API with the same session and a normal `User-Agent` and `Referer`.
   - **No login, no credentials, no captcha bypass.** If NSE blocks the request (401/403 after the warm-up), stop and report what you saw. Don't try workarounds.
2. **Write `reality_engine/scripts/nse_announcements.py`:**
   - Arguments: `--symbols`, `--from`, `--to`, `--subject-filter`, `--out` (default `D:\RealityEngine\raw\nse_announcements\`, but for this pilot use `.tmp/nse_ann/` in the worktree), and `--interval` (≥3 s between calls).
   - Per announcement, store the raw JSON row plus these fields:
     - `symbol`, `isin` (from the row, or else resolved via `master_companies` with `reality_engine.db.readonly.connect_ro`);
     - `subject`, `desc`;
     - `known_at` = NSE's own dissemination timestamp (`an_dt` / `sort_date` or the equivalent; check which one it is);
     - `attachment_url`.
   - Optionally download attachments (`--download`) with resume: skip a file that already exists with the same size.
   - Exponential back-off on 403/429/503.
3. **Pilot:** 50 companies for 2024-04-01 → today.
   - 25 of them are NSE-only companies (in `master_companies` without a `bse_code`).
   - The other 25 are companies whose old corpus has NSE-sourced transcripts: `corporate_documents` rows with no `bse_newsid`. Find them with a bounded query on `equity_intelligence.db`.
   - Download only the attachments whose subject looks like a concall transcript or an analyst/investor meet. Keep metadata for every subject.
4. **Validate:**
   - Of the old 1,519 NSE-sourced transcript rows that belong to the pilot companies, how many does the fetcher find (match by symbol + date ±3 days)?
   - Is `known_at` consistent with the old rows' dates?
   - Hand-check 10 attachments: are they real transcripts?
   - Measure the request rate NSE tolerates. Report the blocks seen and the safe interval.
5. **Tests:** `reality_engine/tests/test_nse_announcements.py`, offline with fixtures: row parsing, ISIN resolution, `known_at` parsing, resume skip, back-off.

## Rules
- Network is allowed for nseindia.com only, at ≤20 requests/min.
- Write only in this worktree. All databases are read-only (`connect_ro`).
- No commits. Never open `results_notes.db` for writing.

## Acceptance checks
1. The fetcher runs on the 50-company pilot, or a block is reported with evidence.
2. The recall table against the old NSE-sourced rows, plus the 10-attachment hand check.
3. The offline tests pass.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_nse_announcements
```

## Report
Give:
- the endpoint and the session handling;
- the fields and which one is `known_at`;
- the recall numbers and the hand-check result;
- the safe request interval;
- the projected time and GB for a full FY25+ run over all NSE-only companies and over the 1,519 transcript gap;
- your tool-call count.
