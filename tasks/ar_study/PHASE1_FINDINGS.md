# Annual Report Value Study: Phase 1 findings

Written 2026-10-10. Brief: `tasks/ANNUAL_REPORT_VALUE_STUDY.md`.

## What was read

| | Shipping | Logistics |
|---|---|---|
| Company | Cochin Shipyard (COCHINSHIP), shipbuilding and ship repair | Container Corporation of India (CONCOR), rail container logistics |
| Annual report | FY24, filed 2024-09-07, 362 pages, 1.07M chars | FY24, filed 2024-08-30, 432 pages, 1.09M chars |
| Compared against | Q3 + Q4 FY24 call transcripts, Q3 + Q4 FY24 investor decks | Q3 + Q4 FY24 call transcripts (no FY24 deck in our data) |
| Reader parts | 7 (about 50 pages each) | 8 |

Note on sector choice: SCI has reports but no concalls. **Correction (later the same day):** GESHIP does have
reports. They are indexed but were never downloaded, because the download job stopped partway through the Nifty500
group. See `PHASE1B_GESHIP_FINDINGS.md`, which re-runs the shipping case on GESHIP.

Text layer: only 9 of 794 pages had less than 200 characters. No OCR was needed. Cochin reports in ₹ lakh, CONCOR in
₹ crore.

**Change from the brief:** at Shivam's request the readers were **Haiku**, not Sonnet. The instructions given to every
reader are in `READER_INSTRUCTIONS.md`.

## Cost

- 5-hour window: **43% before, 57% after, so about 14 points for 2 reports with Haiku.** Weekly use went from 29% to 30%.
- 15 reader agents ran for about 5-10 minutes each, using 4.6M subagent tokens in total. Most of that is the
  same reference file (about 30k tokens) being re-read by every agent.
- At this rate, Phase 2 with 12 reports would take about 85 points, which is more than one window. Either split it
  across two windows (6 reports each), or cut cost: split by section rather than by page, and give each reader only
  the call excerpts relevant to its section.

## Output files

- `scores_COCHINSHIP_FY24.csv` (337 rows) and `scores_CONCOR_FY24.csv` (351 rows): the merged scoring sheets.
- `notes_<SYMBOL>_FY24.md`: each reader's NOTES block (new facts, stress hints and contradictions, with page numbers).
- `parts/`: the raw output from each reader. `text/`: the per-page extracted text.

## Scoring sheets summarised

Tokens by the readers' verdict:

| | keep-text | table | changed-only | drop | total |
|---|---|---|---|---|---|
| Cochin | 69k (24%) | 103k (37%) | 60k (21%) | 49k (18%) | 282k |
| CONCOR | 49k (19%) | 76k (30%) | 56k (22%) | 66k (26%) | 253k |

By section family (both reports, tokens):

| Section family | Tokens | keep | table | changed-only | drop | Comment |
|---|---|---|---|---|---|---|
| Notes to accounts (other) | 187k | 35k | 77k | 34k | 40k | Largest block. The value sits in a few notes (see below). |
| Auditor / CARO / C&AG | 77k | 37k | 8k | 23k | 9k | The densest source of signals. |
| BRSR | 35k | 2k | 19k | 7k | 7k | Section A numbers only. |
| Corporate governance | 33k | 7k | 6k | 9k | 12k | Mostly changed-only. |
| Subsidiaries / JV (AOC-1) | 29k | 6k | 10k | 9k | 5k | Table. |
| Contingent liabilities / commitments | 24k | 6k | 8k | 5k | 4k | High value. |
| MD&A | 22k | 9k | 4k | 5k | 3k | Mostly overlaps the calls. |
| Directors' report | 17k | 1k | 6k | 7k | 4k | |
| Chairman letter / overview | 11k | 4k | 5k | 1k | 1k | |
| Financial statements | 10k | 0 | 2k | 0 | 6k | XBRL already has them. |
| Related-party notes | 9k | 2k | 5k | 2k | 0 | Table. |
| CSR / segment / AGM notice | 24k | 1k | 11k | 4k | 8k | |

**The readers were too lenient.** They marked only about 22% of tokens as drop. Many "table" rows are figures that
XBRL already has, and Haiku split sections finely (about 340 rows per report), so the same section appears in two
parts. My judgement after checking is below. Treat the raw verdicts as an upper bound on what is worth keeping.

## Top 5 valuable sections (new compared with the calls and decks)

1. **Independent auditor's report: key audit matters, emphasis of matter, CARO, C&AG comments.** CONCOR: the KAM on the
   railway land-licence-fee demands (Tughlakabad ₹677.68 cr, p.413), and no Ind AS 116 right-of-use asset or lease
   liability booked for railway land leases whose agreements are unexecuted (pp.68, 388, 416). Cochin: a C&AG comment
   that the auditor's report did not cover the Shipbuilding Financial Assistance accounting (p.51); the SAP edit log
   was enabled only from March 2024 (p.234). → keep-text.
2. **Contingent liabilities, claims not acknowledged as debt, commitments.** CONCOR: unacknowledged claims of ₹1,373.58
   cr, about 11.5% of net worth (p.396); a ₹861.05 cr SEIS export-incentive claim disallowed, fully provided for, with
   the appeal pending (p.237); unsecured capital advances of ₹1,053 cr and capital commitments of ₹624 cr
   (pp.231, 343). → table, plus one line of text per item above a materiality threshold.
3. **Revenue / contract notes: unexecuted orders, contract liabilities, delayed contracts.** Cochin: customer advances
   (contract liabilities) rose to ₹4,875 cr from ₹3,859 cr, up 26% (verified in the text). On the Q4 call the analyst
   said they had dropped and management said they would come down. Fresh orders in FY24 were small, and the
   report's unexecuted order value is on a different basis from the call's backlog figure (p.301+). Two 1,200-passenger
   vessels are past their delivery dates, and the Andaman & Nicobar administration asked for them to be reallocated
   to other buyers (pp.138, 151+). The Q3 call treated them as live orders. → table, plus keep-text for delayed or
   disputed contracts.
4. **Related-party disclosures (BRSR related-party share, AOC-2, related-party note).** CONCOR: related-party purchases
   are 73.65% of all purchases (FY23 76.36%). This is verified, and is almost certainly rail haulage paid to Indian
   Railways, so it is structural, not leakage. Cochin: related-party loans and advances are 42.83% of the total
   (p.104), and there is a ₹35.3 cr advance to a related party that was nil in FY23 (p.286). → table. The value is
   the year-on-year change.
5. **Subsidiaries / JVs (AOC-1) and project status (capital work in progress ageing, overdue projects).** CONCOR's
   Fresh & Healthy subsidiary has reserves of minus ₹189 cr against ₹229 cr of share capital (p.134); CONCOR's MMLP
   Paradip and Jajpur civil works were still overdue at FY24 end (p.335). Cochin put ₹44 cr of rights-issue equity
   into its subsidiary HCSL in the same year HCSL redeemed ₹44 cr of NCDs held by Cochin, and HCSL's loss widened to
   ₹30 cr from ₹20 cr (pp.26, 38, 224). → table.

Also new, and possibly worth a row: Cochin's FY24 operating cash flow was **negative (₹-172.8 cr standalone, ₹-171.6 cr
consolidated, against ₹2,046 cr in FY23)**, verified at pp.~170 and 248, and never raised on the calls. This comes
from the cash-flow statement, so it is covered **if** our XBRL feed carries cash flow. Check that before treating it as
annual-report-only value.

## Top 5 droppable

1. **Financial statement bodies** (balance sheet, P&L, cash flow): XBRL has them. Keep only the notes listed above.
2. **AGM notice:** 7k tokens, all marked drop. Keep only a flag when there is a special resolution (borrowing limits,
   related-party approvals, fund-raises).
3. **Chairman letter / corporate overview:** repeats the decks and calls. Changed-only at most, for targets.
4. **Corporate governance report boilerplate** (committee terms, meeting attendance, code of conduct): changed-only.
   Keep board composition and director changes as a table. CONCOR had 4 independent directors out of 10 (p.120).
5. **BRSR principle-by-principle prose, CSR project lists, accounting-policy notes:** drop or changed-only. Keep
   BRSR Section A numbers and CSR obligation against amounts spent and unspent as tables. CONCOR left ₹21.31 cr of its
   ₹27.45 cr CSR obligation unspent (pp.123-124).

## Situational examples

- **Policy / regulatory, counterparty is the government or a related party (CONCOR land-licence fee):** the Q4 call
  did give the Tughlakabad demand (about ₹680 cr). What the report adds is the auditor making it a key audit matter,
  the total unacknowledged claims (₹1,373.58 cr), and the fact that the leases are not on the balance sheet. This
  matters only if Railways enforces the demand or the accounting changes. Then it is about 11% of net worth.
- **Stress in the order book (Cochin's 1,200-passenger vessels):** delivery dates expired, liquidated damages
  provided only up to April and October 2023, customer asks to reallocate. A small order in rupees, but an early
  sign of a contract going bad that the calls did not show. This class of note matters for any order-book-driven
  company.
- **Government grant reversal plus auditor unease (Cochin SBFA):** ₹10.72 cr of SBFA grant reversed because vessel
  delivery dates were revised, and the C&AG flagged the auditor's report as deficient on this point. Small in amount,
  but it is the kind of auditor/C&AG friction that matters if it repeats or grows.

## Reader accuracy (spot-check)

I checked 9 headline claims against the extracted text. 8 held up:
- Cochin: operating cash flow, contract liabilities, SBFA, the 1,200-passenger vessels.
- CONCOR: receivables (₹213.10 cr → ₹329.45 cr), the Tughlakabad ₹677.68 cr KAM, related-party purchases at 73.65%,
  SEIS ₹861.05 cr.

**1 was wrong.** A reader said the Q4 call put the Tughlakabad demand at "about ₹540 cr". In fact the call says
"Rs. 680-odd crores" (REFERENCE line 2145), so the report's ₹677.68 cr agrees with the call.

Other issues:
- Readers flagged several small "contradictions" that are probably definition differences: 75 vs 90 LNG trailers,
  66 vs 64 terminals, average lead distance 894 vs 823 km, and the repair-segment margin. Treat these as unverified.
- About 8 CONCOR rows had unquoted commas, which broke the verdict column.
- Two readers noted text-extraction gaps on tables: the CONCOR JV table at pp.135-136 has columns out of line, and
  the Cochin government-transactions table at p.225 has no figures in the text.

## Chunk estimate

At about 645 tokens per chunk (today: 388 chunks per AR), the readers' keep-text alone would give about 105 chunks
(Cochin) and 75 chunks (CONCOR). If the tables are stored as rows rather than chunks, and keep-text is limited to the
auditor/CARO block, contingent items, delayed or disputed contracts, related-party changes, and MD&A risk paragraphs,
the estimate is **about 35-50 chunks per AR**. That is under the 60 target. Phase 2 needs to confirm this.

## Proposed changes before Phase 2

1. **Split by section, not by 50 pages.** Detect headings first (they are reliable), then give one reader per
   section family. This stops duplicate rows and lets each reader get only the relevant call excerpts, which cuts
   cost.
2. **Tighten the scoring guide:** "table" only for figures not in XBRL; financial-statement figures are drop by
   default; one row per section, not per sub-heading.
3. **Keep a verification pass.** The main session checks every headline claim with grep against the text (cheap, and
   it caught 1 wrong claim in 9). With Haiku readers this is necessary.
4. **Model choice:** Haiku found real signals and quoted pages correctly. Its weak points were verdict calibration
   and an occasional wrong contradiction. A good split: Haiku for extraction and first pass, then one Sonnet pass
   per report over the merged notes only, which is small (about 25k characters).
5. **Before Phase 2, check whether our XBRL feed has the cash-flow statement and contract-liability lines.** That
   decides whether the negative operating cash flow and customer-advances signals are annual-report-only value.

Stopped here and waiting for Shivam.
