# T-241 brief: hand audit of hy4 transcript facts (Eagle reads, Wolf acts)

Goal: can Opus, querying these rows, find the hidden details in the calls and trust them? Find the defect
classes, how often each occurs, and which a script can fix after the read vs which need the reader prompt.

## Data (read only, never open the live file)
- Snapshot: `C:/Users/warri/AppData/Local/Temp/claude/12b5f02fd3b7ce95/82f0cda6-8a84-4831-a260-84b9a6b057ad/scratchpad/obs394.db`
  (copy of `D:/RealityEngine/hy4_out/obs_transcripts_394.db` at 12:15; the live file is being written - do not query it).
  Table `observation`: 267,614 rows, 274 companies; record_type number/statement/guidance; status
  verified/unverified/quarantined.
- Page text: store `C:/RealityEngine/tg_build/full394/cNN/cNN.db`, table `doc_page(doc_key, page, text)`; NN is the
  1-based row of the symbol in `C:/RealityEngine/tg_build/full394/universe394.csv` (2 digits min: c05, c123).

## Wolf's first look (12 verified number rows): 7 clean, 3 partial, 2 wrong
- IRCON p1: filing date "12th February" stored as a number 12 (2,293 date-like rows, 638 verified).
- AWFIS p8: INR55 cr fixed-asset depreciation stored as depreciation_and_amortisation_expense (total was 196).
- Ranges keep one end (EMS 16% of "16%-17%"; value_high set on only 4,889 rows).
- SPANDANA: monthly average disbursal without "per month"; QPOWER: number from an analyst's question.
- speaker is empty on all 145,586 number rows; 113,864 NEW:* rows use 69,148 distinct measure names.
- Values themselves: 300/300 random numbers appear verbatim on their page.

## Steps
1. Seeded random sample (seed 241): 60 number rows (30 verified, 30 unverified), 30 statements, 20 guidance,
   stratified across >= 40 companies. Read each against its page text. Grade: right / partial / wrong / junk, and
   name the defect class (period, basis, measure, component-vs-total, range, unit/scale, speaker, junk, other).
2. Coverage: pick 10 transcripts (seed 241), read every page yourself, list facts an investor would want that no
   row holds (the "hidden details" test). Count found vs missed.
3. Write `D:/RealityEngine/reports/2026-11-24_hy4_transcript_audit.xlsx` (one row per graded item, with page
   quote) and a short summary .md beside it: per class rate with sample size, worst examples, and for each class
   "script fix after read" or "prompt change" with the rule you'd use.
4. Recompute any arithmetic yourself; do not trust the row's status.

## Limits
Read only; no code changes; no live DB queries; stay under 100k context per sub-read (batches of 8 pages if you use
subagents). Report to Wolf (neo-...) with the summary when done.
