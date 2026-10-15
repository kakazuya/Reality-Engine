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
- 2026-10-13 18:50 (Claude) t-lcgo-exc (Go LongCat, exhaustive + CORE list): INCONCLUSIVE - 19/110 pieces unanswered (competing with production LongCat at 128 slots x 2), 19/25, 9,137 facts, 0.0% not in text. Re-run the missing pieces in a quiet period (`ar_queue.py drive --run t-lcgo-exc --workers 4`, then `test-score`) before deciding.
- 2026-10-14 01:24 (Claude) t-lcgo-exc re-run finished (Go LongCat, exhaustive + CORE): FAIL - 22/25 (missed CSL operating
  cash flow standalone + FY23, CON SEIS 861), 1/110 piece unanswered (timeouts), 12,224 facts, 0.0% not in text, 95
  regrouped. LongCat stays on the PLAIN prompt (Shivam 2026-10-14: retest only while it is free; it was).
- 2026-10-14 00:32 (Claude) t-catjam-1013 (Zen CLI, Cat Jam, plain 36k): PASS - 25/25, 12,191 facts, 0.2% not in text,
  110/110 answered. Text only (provider refuses images: no deck use). Free on Go too (Go docs: Unlimited, limited time).
  In production: Zen x3 and Go 32 -> 64 slots per account (01:12; 0 errors, 64 s and 118 facts per piece vs LongCat
  229 s / 52 at 00:36-01:10).
- 2026-10-14 04:38 (Claude) t-kilo-north-1014 (Kilo, Cohere North Mini Code free, plain 36k, 6 workers): FAIL - 19/25
  (missed CONCOR KAMs x3, SEIS 861, receivables; GESHIP capcom standalone), 4,492 facts, 0.6% not in text, 6/110 pieces
  unanswered (empty answers, dropped connections). No 429 in ~140 calls. Text only. Keep for coding work, not AR.
- 2026-10-14 05:47 (profile_tuner) t-bunny-ex (space-bunny-free) exhaustive prompt: PASS - must-find 25/25, facts 24615 (plain baseline 9872), not in text 0.04%, regrouped 0.14%, unanswered 0.0%
- 2026-10-14 05:47 (profile_tuner) profile switched to exhaustive for space-bunny-free; worker restarted
- 2026-10-14 06:02 (profile_tuner) t-muse13-ex (muse-spark-1.3-contributor-free) exhaustive prompt: PASS - must-find 25/25, facts 12544 (plain baseline 5080), not in text 0.00%, regrouped 0.00%, unanswered 0.0%
- 2026-10-14 06:02 (profile_tuner) profile switched to exhaustive for muse-spark-1.3-contributor-free; worker restarted
- 2026-10-14 06:12 (Claude) t-catjam-72k (Zen CLI, Cat Jam, plain, 72k pieces = 55 calls): 25/25, 8,415 facts, 0.1% not in
  text, 0 unanswered. More facts per call (153 vs 111 at 36k) but 31% fewer facts per report: KEEP 36k (quality over
  efficiency). Zen per-call overhead (~19k tokens/call vs ~9k of text) is better attacked with the exhaustive prompt
  (more facts per call at the same piece size): Space Bunny 2.5x, Muse 2.5x (tuner, 05:47/06:02).
- 2026-10-14 06:53 (Claude) t-catjam-ex (Zen CLI, Cat Jam, EXHAUSTIVE 36k): PASS - 25/25, 20,846 facts (plain 12,191), 0.1% not in text, 0.05% regrouped, 110/110. Cat Jam switched to exhaustive on Go and Zen 06:55.
- 2026-10-14 09:10 (Claude) Cat Jam Go quota = TOKEN BUDGET shared by both Go accounts: window 1 00:42-01:58 3,784 pieces,
  40,292 pages, 39.1M in / 83.2M out tokens; window 2 07:00-08:00 3,648 pieces, 46,357 pages, 37.7M in / 84.0M out, then
  HTTP 429 'Upstream request failed: Rate limit exceeded' on both accounts. Refill period: being measured (watch from
  08:05; Go readers probe every 3 min). Slots only change how fast the budget is spent. Go-API exhaustive test
  t-go-catjam-ex: 21/25 on 102/110 answered (the 8 unanswered pieces hold the 4 GESHIP misses; quota refused the
  re-run), 13,173 facts; Go exhaustive production ~110 facts/piece vs plain ~117: the exhaustive gain seen on Zen
  (1.7x) does not show on the Go API. Output tokens per page similar, so keeping exhaustive costs no budget.
- 2026-10-14 14:15 (Claude) Cat Jam Go still refused at 14:11 (6 h after the ~08:00 cut). Best hypothesis: a DAILY
  budget of ~84M output tokens (~40-46k pages) shared by both Go accounts, reset 00:00 UTC (05:30 IST); the two windows
  (00:42-01:58 IST = 10-13 UTC, 07:00-08:00 IST = 10-14 UTC) each used one day. To confirm: first answer after 05:30 IST
  on 10-15 (Go readers probe every 3 min).
- 2026-10-14 (Claude) LongCat piece size (Go API, plain): 18k = 25/25, 6,966 facts, 0.4% not in text, 194/199 answered, 30,702 call-s; 36k = 25/25, 5,377 facts, 0.1%, 107/110, 24,101 call-s. +30% facts per report, same facts per slot-second. Shivam: switch -> main-run piece size 18k (applies to LongCat, Cat Jam, Gemma 31B).
- 2026-10-14 18:20 (Claude) Gemma capacity: Google-side load shedding, not our quota. Hourly 10-13/14: Gemma 31B ~180-300
  pages/min with no errors 00-05 IST (10-13) and 04-09 IST (10-14); HTTP 500 (some 429 "exceeded your current quota")
  most other hours, near zero 23-03 and from 10:00 on 10-14. 18:15 probe: 37/37 keys HTTP 500 on a one-line request
  for 31B; 26B 20 x 200 / 17 x 500 (26B had zero errors for 36 h until ~13:00 on 10-14). Per-key use ~160 requests/day vs
  14.4k. Change: a Google key answering 500/503 rests 2 min and hands its piece back (was: retry every 10 s, ~1,300
  failing calls/min during storms). Expect Gemma 31B mainly in the 04:00-10:00 IST window.
- 2026-10-15 04:00 (Claude) t-kilo-step-ex18 (Kilo, Step 5 free, exhaustive, 18k): 0/199 answered in 40 min; StepFun upstream refuses every call ('current: 151, limit: 150', shared by all Kilo users) or 'engine_overloaded'. Stopped. Retry at a quieter hour; Kilo adds no AR capacity until then.
- 2026-10-15 05:38 (Claude) CONFIRMED: Cat Jam's Go budget resets at 00:00 UTC (05:30 IST): refused until 05:28, first answer 05:30:53, 915 pieces in 8 min. Benches now never run past the reset.
- 2026-10-15 06:45 (Claude) Cat Jam Go budget efficiency: plain 36k 11.0 facts/page, 188 out-tokens/fact (40k pages/day); exhaustive 36k 8.6, 211; exhaustive 18k (10-15) 20.0 facts/page, 174 out-tokens/fact, 20k pages/day. Same ~400k facts per daily budget, twice the depth per report: keep exhaustive 18k.
- 2026-10-15 09:46 (Claude) Kilo Step retry 08:45-09:45: 15/199 answered; StepFun's shared limit ('current N, limit 150') refuses most calls even at 4 workers. Not usable for AR volume; stopped.
- 2026-10-15 13:15 (Claude) Flash-Lite 3.5 read 2 pieces all day (10,460 on 10-13): some pieces get empty answers (200, STOP, no text); the fallback Gemma 31B was in 500 outage, its calls hung and the pieces cycled. Fallback switched to Gemma 26B for both Flash-Lite routes: 3.5 FL back to 105 pages/min (12:55-13:15).
- 2026-10-16 03:00 (Claude) Hard reports (> 10% numbers not found, 345): causes garbled OCR/scans 111, digit-encoding fonts 46, clean text 188 (mostly LongCat / Gemma 26B misreads, some mixed-font pages). New value_check rule for shifted-digit fonts (OIL U+0144, PPAP control chars) re-verified 8,217 numbers for free (not_found 43,953 -> 35,736). Claude Haiku reading page images (checked against RapidOCR text of the same image): 12 scanned reports, 711 -> 3,984 numbers, verified 418 -> 3,732; replaced 11, kept 1. Haiku image reads of faint scans are reliable (1-8% not found on most; GUJCOTEX 32%, KAIZENAGRO 34% where the old facts were kept).
