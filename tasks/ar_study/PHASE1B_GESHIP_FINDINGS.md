# Annual Report Value Study: Phase 1b, GESHIP FY24 with the revised method

Written 2026-10-10. Follows `PHASE1_FINDINGS.md` (Cochin Shipyard + CONCOR). Shivam asked to re-run the shipping
case on Great Eastern Shipping and to find out why it was missed (answer in §5).

## 1. What was read

- **The Great Eastern Shipping Co. (GESHIP)**, FY24 annual report, filed 2024-07-08. Downloaded from the BSE link
  already in our index to `src/GESHIP_FY24_AR.pdf`. The DB and the ingestion job were not touched.
  171 PDF pages (many are two-page spreads; printed page numbers run to about 300), 819k characters, 12 near-empty
  pages.
- Compared against the Q3 FY24 call (2024-01-31), the Q4 FY24 call (2024-05-10) and both decks (from
  `deck_figures.db`).

## 2. Method changes tested (from Phase 1)

| Change | Done |
|---|---|
| Split by section, not 50 pages | 9 sections cut at the report's own headings: AGM notice; chairman/ESG/highlights; board's report + annexures + MR-3; corporate governance; BRSR; fleet + auditor + CARO; standalone FS + notes; consolidated (2 parts) |
| Compare against a short fact list | One Haiku agent turned the calls and decks into `GESHIP_FY24_REFERENCE_FACTS.md` (436 facts, each with its source). Section readers read that list and grep the full text only to confirm a point |
| Stricter verdicts | `READER_INSTRUCTIONS_V2.md`: keep-text at most about 10%; table only for figures not in the main statements; at most about 15 rows per section; a contradiction must be confirmed by grep, otherwise it is labelled a "definition difference" |
| Grep check of headline claims | Done (§4) |
| Sonnet pass over merged notes | Skipped. The main session (Opus) did the merge and checking itself, to stay under the 80% window cap |
| Does XBRL hold cash flow? | **No** (§5) |

## 3. Results

129 rows (Phase 1 had about 340 per report). Readers' token split for the whole report (about 200k tokens):

| Verdict | Tokens | Share |
|---|---|---|
| keep-text | 2.2k | **1%** |
| table | 77k | 39% |
| changed-only | 69k | 34% |
| drop | 52k | 26% |

The stricter rules worked on keep-text: it fell from about 20% of tokens to 1%. "table" is still large. Much of it is
note detail (borrowings, employee benefits, financial risk) that readers kept because XBRL does not hold it for us
(§5). Taken as stored rows it is cheap; it is not prose to index.

### What the report adds that the calls and decks don't (verified)

1. **Auditor's report modified for audit trail** (pp.102, 136-137). One accounting package is run by a third party
   with no controls report covering the edit log. In other packages the edit log is not enabled at database level,
   so direct data changes are not logged. The internal-controls opinion is still clean. → keep-text.
   Cochin also had a late edit log (p.234). This looks like a common FY24 audit item, so it is worth a flag column
   across companies.
2. **Capital commitments rose sharply**: ₹518.88 cr standalone (FY23 ₹42.77 cr; p.128) and ₹559.18 cr consolidated
   (FY23 ₹59 cr; p.162). Capital advances are ₹46.17 cr (FY23 ₹24.65 cr). The calls describe management as
   "cautious" on buying ships. Not a confirmed contradiction (the report does not say what was ordered), but it is a
   quantified capex signal absent from the calls. → table.
3. **Credit rating upgraded**: CARE moved the NCDs and bank facilities from AA+ to **AAA** (p.75). This is not in the
   calls or decks. → table (rating history).
4. **Contracted revenue cover**: future time-charter receivables of ₹1,142 cr within a year (FY23 ₹1,022 cr), plus
   1-3-year buckets (p.167). This is the only quantified forward cover in the report. → table.
5. **Related parties and subsidiaries**:
   - BRSR shows loans to related parties at 4.69% of all loans and advances (FY23 nil; p.83). This is the ₹65 cr
     loan to subsidiaries in CARO (p.104).
   - Investments in related parties are 51% of investments.
   - The subsidiary table shows the trading arms (Great Eastern Chartering UAE + Singapore) at about ₹189 cr PAT,
     about 7% of consolidated (p.135).
   - Ravi K. Sheth's pay is borne entirely by the subsidiary Greatship (p.68).
   - Dividends to key management and family are ₹116 cr, 22% of the payout (pp.151, 162).
   → table.
6. **EU ETS exposure** (EU carbon-permit trading): a broker has been engaged for the permits (EUAs) and a registry
   account is expected in Q1 FY25 (p.84, ESG section). There is no cost estimate, and the calls do not mention it.
   → keep-text (policy change).
7. **Contingent and tax items**:
   - Contingent liabilities total ₹571 cr consolidated, 4.6% of equity; service tax of ₹384.83 cr is under appeal,
     unchanged.
   - ₹28.76 cr of disputed dues is net of ₹41.24 cr paid under protest (CARO p.104).
   - No deferred tax is provided on ₹718 cr of undistributed subsidiary earnings (FY23 ₹366 cr; p.156).
   → table.

### Droppable (confirmed again)

- AGM notice: 60% drop. Keep only director shareholdings and special resolutions.
- Chairman's statement: mostly repeats the calls and decks.
- Accounting policies: changed-only.
- Corporate-governance procedure: drop or changed-only.
- BRSR principle prose: drop, except the related-party share table (an early warning that cost nothing to find).
- CSR project lists: drop.
- Financial statement bodies: drop once we hold the figures elsewhere (§5).

## 4. Reader accuracy (checked by grep against the text)

| Claim | Result |
|---|---|
| CARE AA+ → AAA | ✔ p.75 |
| Audit-trail modification | ✔ p.102 (text quoted) |
| Capital commitments 518.88 / 559.18 | ✔ |
| Time-charter receivables 1,142.46 < 1 yr | ✔ |
| Loans to related parties 4.69%, FY23 nil | ✔ |
| EU ETS / EUA broker | ✔; absent from the reference |
| Great Eastern Chartering subsidiary | ✔ |
| CSR "does not reconcile" | Partly right. Obligation ₹24.73 cr, spent ₹18.77 cr as printed (₹18,77,77,325), transferred to the unspent account ₹6.17 cr (26.04.2024). The ₹0.21 cr gap is too small to matter and is probably interest. Not a signal |

No false contradictions this time. Phase 1 had one in nine. Readers labelled 6 differences (net cash, NAV, EPS, gross
debt, FPI share, the BRSR intensity base) as definition differences rather than conflicts, which is the behaviour
the v2 rule asked for.

## 5. Why GESHIP was missed, and the cash-flow check

**Why it was missed.** GESHIP has 15 indexed annual-report rows in `corporate_documents` (FY12-FY26, all dated) with
no `local_file_path`. The only download run (`run_annual_report_ingest.py`, all rows stamped 2026-08-28 18:56)
works through Nifty200 → Nifty500 → rest, and **stopped partway through the Nifty500 tier**:
- Nifty200: 197/197 companies downloaded.
- Nifty500-only: **117/288 companies**, 1,085 of 2,882 reports.
- Rest: 0 of 1,936 companies.

GESHIP is Nifty500 but not Nifty200. My Phase 1 candidate query only looked at downloaded files, so it skipped
GESHIP without saying so, and I wrongly reported that GESHIP had no reports. Screener is right that the reports
exist. Logged as an open item in `tasks/STATE.md` → Known data gaps.

**Cash flow.** There is no structured cash-flow data. `annual_financials.operating_cash_flow_inr_cr` (source:
yfinance) is 0 or null on 12,432 of 13,015 rows, including all three study companies. `mkt_nse_pit_xbrl_facts` holds
only insider-trade disclosures (no financial-statement fields). So Cochin's negative operating cash flow, customer
advances, receivables, contingent liabilities and related-party figures **today exist only in the annual-report
PDFs**. Two ways to fix it: parse the NSE results XBRL (STATE "Next" #1; it carries cash flow only half-yearly), or
pull the cash flow, balance-sheet detail and key notes out of the reports into tables. Also logged in STATE.

## 6. Cost: the revised method did not save tokens

- 5-hour window: 58% → 71% (13 points for 1 report). This includes the main session's own work (downloading,
  splitting, checking).
- Subagent tokens:
  - Phase 1: 4.6M tokens for 2.16M characters of report, about 2.1 tokens per character.
  - Phase 1b: 2.03M tokens for 0.82M characters (fact list 0.30M + 9 readers 1.73M), about 2.5 tokens per
    character.
- Why there was no saving:
  - The fact list came out at 10k words (target was 4-7k).
  - Readers made 9-21 tool calls each, and every call re-sends the whole context.
  - Readers still read every page of sections that end up as drop.
- **What would actually cut cost** (for Phase 2):
  - **Drop by rule before any model reads it.** Headings are reliable. The AGM notice, accounting policies, the
    financial-statement bodies, governance procedure, BRSR principle prose and CSR project lists are about 40-50% of
    the text. A heading rule can remove them for free; a script or a cheap table extractor keeps what is needed from
    them (director holdings, ratings, related-party tables).
  - Fewer, larger reads per agent: allow up to about 2,000 lines per Read.
  - Cap the fact list at about 5k words.
  - Expected result: about 0.8-1.0M subagent tokens per report, about 5-6 points of the window. Then 12 reports
    still need two windows.

## 7. Chunk estimate (revised)

Under v2 verdicts, keep-text is about 2-3k tokens per report, so **under 10 chunks**. Changed-only text (about 70k
tokens) is stored only when it differs from last year; the first year needs a baseline. Tables go to structured rows.
That is well under the 60-chunk target. The open question is not chunk count; it is building the table extractors
(rating history, capital commitments, time-charter backlog, contingent liabilities by type, related-party shares,
subsidiary P&L, audit-report modifications).

## 8. Decisions for Shivam

1. Phase 2 (10-12 reports) with the heading-rule pre-filter, over two 5-hour windows?
2. The download gap is in STATE for another session to own. Resuming the download is a separate decision (about
   12.7k reports, about 110 GB).
3. Cash flow: get it from XBRL (Next #1) or from the reports? This decides whether the report extractor needs the
   main statements at all.
