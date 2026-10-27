# Task — price-band history and index-membership history: fetchers plus a timed test

## Goal
Shivam's rulings (2026-10-27/28, `tasks/NEXT_SESSIONS_PLAN_2026-10-27.md`, decisions 5 and 6):
- **Price bands:** the daily circuit limit per stock (2/5/10/20%, none for F&O), and whether the stock hit its upper or lower circuit that day.
- **Index-membership history:** which stocks were in Nifty 50, 100, 200, 500, Midcap 150, Smallcap 250 and so on, as of any date.
- **The 3-hour rule, for each dataset:** fetch back to **2019-01-01** if the full fetch takes under 3 hours; otherwise from **2024-04-01** (FY25).

Today we have band data for only 538 dates, and `index_membership` is a single 300-row snapshot as of 2026-09-30.

This is a raw fetch only: no chunking or embedding. The data feeds `company_state_daily` later.

## Do
1. **Price bands (NSE):**
   - Find the NSE archive file that carries the daily price band per security. Candidates: `sec_list_DDMMYYYY.csv` and the price-band files under `nsearchives.nseindia.com/content/equities/`.
   - Check what the existing 538 band dates came from (search `equity_intelligence.db` with `connect_ro` and the repo scripts for the band table) and reuse that source.
   - Upper/lower circuit hits can be derived later from OHLC vs the band. Note which columns allow that; don't build it.
2. **Index history (niftyindices / NSE):**
   - Find the sources for dated constituent changes: the "index changes" press releases and notices (niftyindices.com), the semi-annual review announcements, and any historical constituent CSVs.
   - Plan to rebuild membership as valid_from/valid_to intervals per index from the 2026-09-30 snapshot backwards, by reversing the dated changes.
3. **Write fetchers:** `reality_engine/scripts/fetch_price_bands.py` and `reality_engine/scripts/fetch_index_history.py`.
   - Arguments: `--from`, `--to`, `--out`, `--interval` (≥2 s on NSE). Default out paths: `D:\RealityEngine\raw\price_bands\` and `D:\RealityEngine\raw\index_history\`. **For this task, write to `.tmp/` in the worktree.**
   - Resume: skip files already present.
   - Back off on 403/429/503.
   - NSE needs a cookie warm-up session. No logins, no credentials, no captcha bypass. If you are blocked, stop and report.
4. **Timed test, per dataset:**
   - Fetch a sample of about 30 trading days spread from 2019 to 2026 (bands), or the equivalent notice sample (index).
   - Measure the requests needed and the seconds per request at a safe interval.
   - Project the full 2019→today time. Apply the 3-hour rule and state the decision with the numbers.
   - Also check that the source actually reaches back to 2019. If it doesn't, give the earliest date available.
5. **Parsers and tests:**
   - Parse the samples into tidy rows: bands as (date, symbol, series, isin if present, band_pct); index as (index_name, isin/symbol, change_type, effective_date, announced_date).
   - Offline tests in `reality_engine/tests/test_price_bands_index_history.py`.

## Rules
- Network to NSE and niftyindices only, at ≤20 requests/min **in total**. Another worker (NSE announcements pilot) is also using nseindia.com, so keep your interval ≥3 s.
- Write only in this worktree. All databases read-only. No commits.

## Acceptance checks
1. Both fetchers run on the sample, or a block is reported with evidence.
2. A timed projection and the 3-hour-rule decision for each dataset, plus the earliest date available.
3. Parsed sample rows and passing tests.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_price_bands_index_history
```

## Report
Give:
- the sources (URL patterns);
- the earliest date available for each dataset;
- the request count and projected time, and the 3-hour decision for each;
- the exact commands for the full runs;
- your tool-call count.
