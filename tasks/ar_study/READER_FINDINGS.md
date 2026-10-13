# Annual-report readers: findings and current setup (2026-10-12/13)

Detailed per-test lines: `tasks/ar_study/free_test/FINDINGS.md`. Profiles in force: `reality_engine/scripts/reader_profiles.json`.
Passed Zen models: `reality_engine/scripts/zen_models.json`. The overnight tuner appends its decisions at the end of this file.

## Admission test

- **Pieces:** 110 study pieces (COCHINSHIP, CONCOR and GESHIP FY24; more pieces when they are cut smaller).
- **Prompt:** the production prompt `ar-v1`, or `ar-v1x` = `ar-v1` plus the EXHAUSTIVE instruction.
- **Commands:** `ar_queue.py test-export / drive / test-score`.
- **Pass requires all of:**
  - 25/25 must-find facts;
  - < 1% of numbers not in the text;
  - every piece answered (or a fallback reader for empty answers);
  - depth >= 4,500 facts (added 2026-10-13: a shallow reader hits the must-find list but loses most facts);
  - regrouped numbers < 0.5% (commas placed unlike the page, the tenfold-error risk). Commas added to unformatted numbers are harmless.

## Results

| model | route | prompt / piece | must-find | facts | not in text | verdict |
|---|---|---|---|---|---|---|
| LongCat 2.5 | Go API | plain 36k | 25/25 | ~2.0k (CSV test) | 0.6% | in use (main run) |
| Gemma 4 31B | Google | plain 36k | 25/25 | 2.6k | 0.4% | in use (main run) |
| Space Bunny | Zen CLI | plain 36k | 25/25 | 9,872 | 0.04% | passed (Zen) |
| Big Pickle | Zen CLI | plain 36k | 25/25 | 9,459 | 0.0% | passed (Zen) |
| Muse Spark 1.3 | Zen CLI | plain 36k | 25/25 | 5,080 | 0.0% | passed (Zen) |
| Gemini 3.5 Flash-Lite | Google | plain 36k | 24/25 | 3,916 | 0.2% | fail |
| | | plain 18k | 25/25 | 5,459 | 0.1% | 28 empty pieces |
| | | **exhaustive 18k** | 24/25* | **18,352** | 0.0% | **in use** (*miss in an empty piece; Gemma 31B re-reads empties) |
| Gemini 3.1 Flash-Lite | Google | plain 36k / 18k / 9k | 25 / 24 / 25 | 1,189 / 2,021 / 3,126 | <1% | fail (depth) |
| | | **exhaustive 9k** | 25/25 | **7,632** | 0.3% | **in use** |
| Gemma 4 26B | Google | plain 36k | 24/25 | 3,078 | 0.4% | fail |
| | | **exhaustive 36k** | 25/25 | **10,072** | 0.1% | **in use** (regrouped 0.24%, no tenfold errors) |
| Laguna S 2.1 | Kilo | plain 36k | 23/25 | 2,926 | **2.3%** (regrouped 3.2%) | fail (misreads numbers) |
| Ling 3.1 Flash | Kilo / Zen | plain 36k | 15/25 (32/110 answered) | 2,657 | 0.6% | unusable (upstream overloaded; Zen endpoint down) |
| DeepSeek V4 / V4.1 Flash | Token Harbor | | | | | free allowance ran out after ~40 calls |
| Claude Haiku 5.5 (free) | Token Harbor | | | | | not offered on this account |
| Dots, Nemotron Super/Ultra, Glyph | Kilo | | 14-23/25 or too slow | | | fail (10-11 / 10-12) |

**Main lesson:** the EXHAUSTIVE instruction ("go line by line, one line per figure for every row and column, leaving out a
figure is an error") multiplies depth 2-3x on every model tested, without adding wrong numbers. Smaller pieces help
shallow models. Pending (overnight tuner): exhaustive tests for Gemma 31B, LongCat (Go) and the three Zen models.

## Quotas learned

- **Google AI Studio free tier** is per **model** and per **project** (key):
  - Gemma 31B and 26B: 30 requests/min, 16k tokens/min, 14.4k/day.
  - Flash-Lite 3.5 and 3.1: 15 requests/min, 250k tokens/min, 500/day.
  - Two projects in one account behave as independent keys (keys 9 and 10 measured equal to keys 1-8).
  - The Flash-Lite daily limit did **not** reset cleanly at PT midnight (12:30 IST): on 10-13 25 of 30 keys were still
    refused after 12:30, then freed up gradually, so it looks like a rolling 24-hour window. A daily refusal now rests
    the key 1 h and retries (before: until PT midnight, which idled 25 keys).
- **OpenCode Zen free tier** is per **machine/IP**, not per account and not per model.
  - All four models were cut off together after ~1,800 calls / ~35M tokens in ~2.5 h.
  - **Daily quota, reset at 00:00 UTC (05:30 IST):** refused from 17:00/18:31 IST on 10-12; all four models answered
    again at 05:30:29 IST on 10-13 (probe log `zen_quota_probe.log`). Budget ~1,800 calls / ~35M tokens a day.
  - Logging the Zen account in ("OpenCode Console") routes calls to the account but does not lift the IP limit.
  - The Zen free tier refuses direct API calls and custom agent prompts; `opencode run` with the stock agent works.
- **Free promotions end:** LongCat, Space Bunny and Step on OpenCode are time-limited. Gemma on Google keys is the
  durable backbone.

## Boilerplate / CPU-skip review (`ar_review.py`, every 200 finished reports via the watchdog)

- **Facts are not dominated by boilerplate.** At 1,158 reports (1.0M facts) the most frequent items are ratios and
  statement lines, each <= 0.12% of facts.
- **43% of text pages produce no fact**, but no cheap CPU rule removes them safely:
  - Heading rules: dead pages are spread over many sections (<= 1.5% of pages).
  - "<= 20 digits and no protected keyword": cuts 5.8% of pages but loses 0.8% of facts, including stress signals
    and summary figures on image pages. **Rejected.**
- **The year-over-year skip** (identical pages, numbers included) stays: ~14% of pages in reports with a previous year.
- **RapidOCR** applies only to scanned reports (`no_text`), which come later; it cannot shrink pages that have a text layer.

## Incident

2026-10-12 ~18:00-22:06: the main run froze for 4 h on a malformed PDF (PyMuPDF spinning while holding Python's lock).
Every text split now runs in a child process with a 3-minute limit. The watchdog also restarts a job that reads no
pages for 30 minutes even while it keeps logging.

2026-10-13 04:11-06:05: the Zen worker stood still for ~2 h in a deadlock. When every reader was benched at once, all
threads handed pieces back with a blocking put() into a full queue. Hand-backs now go to an unbounded retry list (same
fix in every worker; the Google workers had the same risk at their daily caps).

## Tuner decisions
- 2026-10-13 06:34 (profile_tuner) t-g31-ex (gemma-4-31b-it) exhaustive prompt: FAIL - must-find 23/25, facts 8618 (plain baseline 2638), not in text 0.06%, regrouped 0.04%, unanswered 3.6%
- 2026-10-13 06:55 (Claude) t-g31-ex rescored after its 4 unanswered pieces (429s from sharing keys with production) were re-read: **PASS** - 25/25, 8,756 facts (plain 2,638), 0.1% not in text, regrouped 0.04%, 2/110 unanswered. The tuner's FAIL above was a test artefact. Profile switched to exhaustive; main run restarted.
- 2026-10-13 06:55 (Claude) t-lcgo-ex (Go LongCat, exhaustive): 23/25 - missed GES capcom-standalone 518.88 in an answered piece and CON SEIS 861.05 - but 13,413 facts (plain ~2,000), 0.0% not in text. Real misses, so LongCat stays on the plain prompt. Option for Shivam: exhaustive plus a must-include list (capital commitments, cash flows, contingent liabilities), retested.
- 2026-10-13 08:04 (profile_tuner) t-lcgo-ex (longcat-2.5-preview-free, longcat-2.5-preview-free@zen) exhaustive prompt: FAIL - must-find 23/25, facts 13725 (plain baseline 2000), not in text 0.02%, regrouped 0.20%, unanswered 0.0%
- 2026-10-13 09:44 (profile_tuner) t-bunny-ex (space-bunny-free) exhaustive prompt: FAIL - must-find 22/25, facts 21533 (plain baseline 9872), not in text 0.04%, regrouped 0.16%, unanswered 8.2%
- 2026-10-13 09:50 (Claude) the t-bunny-ex FAIL above is a test artefact: 9/110 pieces unanswered because Zen's daily quota ran out mid-test (21,533 facts read, 0.04% not in text). The tuner now waits for quota when failures are rate limits; t-bunny-ex is back in its queue.
