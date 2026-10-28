# Task — add questions for the 11 in-scope Reddit patterns missing from the bank, then rebuild the master bank

## Goal
The reviewer checked `tasks/reddit_mining/patterns.csv` (48 mined patterns) against `QUESTION_BANK_REDDIT_2026-10-28.jsonl`: **13 patterns have zero questions**.

- **2 are out of our data scope.** Mark them out of scope with a reason, and add no questions:
  - `mf_etf_vs_stock` (14,945 posts): fund advice;
  - `broker_platform_process` (8,445): broker/app process.
- **11 are in scope and must be added:**
  - `fno_vs_cash_flow` 6,711;
  - `global_cue_overnight` 3,538;
  - `dividend_record_date` 3,186;
  - `penny_low_price_stock` 2,946;
  - `macro_event_what_if` 1,121;
  - `ta_chart_pattern` 340;
  - `theme_proxy_play` 288;
  - `merger_arbitrage` 159;
  - `ipo_vs_listed_peer` 156;
  - `second_order_beneficiary` 146;
  - `results_calendar` 44.

## Do
1. For each of the 11, write questions with the same schema and rules as the existing Reddit bank rows: qid, group, archetype, family, question, entities, period, as_of, answer_kind, rubric, coverage, why, reddit_pattern. The counts:
   - **5 each for the 5 biggest patterns, 3 each for the other 6**: 43 rows in total;
   - spread across entity levels (stock, index, sector/theme, market-wide, macro) and styles (terse/natural/Hinglish/as-of);
   - include 2nd/3rd-order questions where the pattern invites it (second_order_beneficiary, macro_event_what_if, theme_proxy_play);
   - use real Indian listed entities resolved to an active ISIN;
   - every question must be paraphrased in your own words. **No Reddit text over 15 words, no usernames.** Run `tasks/reddit_mining/check_leak.py`.
2. Append the rows to `QUESTION_BANK_REDDIT_2026-10-28.jsonl`, as qids RD-G-001…, and record the 2 out-of-scope patterns with reasons in `tasks/reddit_mining/REPORT.md` §4.
3. `family`: use the numeric families 1–20 (or the archetype mapping `REDDIT_FAMILY` in `tasks/master_bank/build_master_bank.py`). Never leave one empty.
4. Rebuild with `python tasks/master_bank/build_master_bank.py --check`. All checks must pass. Report the new case count and whether the thin family×level cells improved, especially family 10 and the price-band level.

## Rules
- Read raw Reddit (read-only) at `D:\RealityEngine\raw\reddit` only to understand each pattern. The repo gets paraphrases only.
- No network, no commits, DBs read-only. Write only in this worktree.

## Acceptance checks
1. 43 new rows, unique qids, every one of the 11 patterns ≥3 rows, and `check_leak.py` clean.
2. `build_master_bank.py --check` passes.

## Test command(s)
```bash
python tasks/master_bank/build_master_bank.py --check
```

## Report
Give:
- rows per pattern;
- the leak-check result;
- the new master-bank totals and thin cells;
- your tool-call count.
