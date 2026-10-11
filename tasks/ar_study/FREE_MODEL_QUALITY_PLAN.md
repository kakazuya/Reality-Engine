# Annual reports: free-model quality check (plan)

Written 2026-10-10. **Goal (Shivam):** every relevant fact in an annual report (AR) gets stored in the DB at true
quality. Window and token efficiency are secondary. Bulk reading goes to the free models on OpenCode Go and Kilo
Gateway. Claude's job is to check whether their output is good enough.

**Start:** after concall ingestion finishes (expected end of 2026-10-10). Until then concall ingestion is using the
Kilo throttle, which is shared across both keys.

## 1. Gold set (already built and checked by the main session)

Three FY24 reports, each read section by section by Haiku, with the headline claims checked by grep against the
text:

| Report | Text | Reader output | Notes |
|---|---|---|---|
| COCHINSHIP FY24 | `text/COCHINSHIP_FY24_AR_*` | `scores_COCHINSHIP_FY24.csv`, `notes_COCHINSHIP_FY24.md` | v1 method |
| CONCOR FY24 | `text/CONCOR_FY24_AR_*` | `scores_CONCOR_FY24.csv`, `notes_CONCOR_FY24.md` | v1 method |
| GESHIP FY24 | `text/GESHIP_FY24_AR_S*` | `scores_GESHIP_FY24.csv`, `notes_GESHIP_FY24.md` | v2 method, section split |

The **must-find list** below holds only facts that were checked against the text. A free model passes a report when
it finds these facts with the right number, unit, period and page.

### COCHINSHIP FY24 (₹ lakh in the report)
- Operating cash flow negative: standalone ₹-17,282.73 lakh (FY23 ₹+2,04,600.40 lakh); consolidated ₹-17,159.36 lakh.
- Contract liability for other works: ₹4,87,527.27 lakh (FY23 ₹3,85,917.58 lakh).
- Two 1,200-passenger vessels: delivery dates expired, and the A&N administration asked for them to be reallocated.
- SBFA (shipbuilding financial assistance) grant: part reversed after delivery dates were revised; the C&AG
  comment says the auditor's report did not report it.
- SAP edit log enabled only from March 2024 (auditor's report).

### CONCOR FY24 (₹ crore)
- Key audit matter: land-licence-fee demands (Phillaur 15.96, Tughlakabad 677.68, Moradabad 5.58).
- Railway land leases with no right-of-use asset or lease liability booked (unexecuted agreements); auditor's
  emphasis of matter.
- SEIS claim of 861.05 disallowed and fully provided for.
- Trade receivables 329.45 (FY23 213.10).
- BRSR: related-party purchases 73.65% of purchases (FY23 76.36%).

### GESHIP FY24 (₹ crore)
- Auditor's report modified for the audit trail (third-party software without a controls report; no database-level
  edit log).
- Capital commitments 518.88 standalone (FY23 42.77) and 559.18 consolidated.
- CARE rating for NCDs and bank facilities moved from AA+ to AAA.
- Time-charter receivables: 1,142.46 due within a year (FY23 1,021.83), plus the 1-2 and 2-3 year buckets.
- BRSR: loans to related parties 4.69% of loans and advances (FY23 nil); investments in related parties 51.01%
  (FY23 57.13%).
- CSR: obligation 24.73; spent 18.77 as printed (₹18,77,77,325); 6.17 transferred to the unspent CSR account on 26.04.2024.
- EU ETS: a broker engaged for EUAs; a registry account expected in Q1 FY25.

Before the first run, extend this list to **every table item** in the three score sheets (contingent liabilities by
type, related-party transactions, subsidiary P&L, borrowings maturity, fleet list, and so on), each checked against
the text. Then test **recall** (how many of the gold facts the model finds) as well as headline signals.

## 1b. Step 0: rule-only extraction (no LLM), run before any free-model test

The study has to answer whether an LLM is needed at all to pull the dense facts. The Phase 1/1b runs did **not**
test that: every page went to a model.

Build a deterministic pass on the three gold reports and measure its recall against the must-find list. Whatever it
misses defines the LLM's job.
- Locate sections by heading.
- Drop sections by rule.
- Capture fixed-format statutory blocks whole: auditor's report incl. KAM / emphasis of matter / audit-trail
  paragraph, CARO, C&AG comments, MR-3 qualifications.
- Parse fixed-format forms with a table parser and label map: BRSR Section A (related-party shares), CSR annexure,
  AOC-1, AOC-2, credit-rating table, cash flow, contingent-liability / commitment / time-charter notes.
- Normalise units from the page header (lakh vs crore).

My first read of the 17 must-find items, **not yet tested**:
- About 13 sit in mandated-format sections a script can find.
- About 4 need reading prose: Cochin's 1,200-passenger vessels, what the SBFA and SEIS notes mean, and GESHIP's
  EU ETS.
- Known failure points for rules: tables whose columns come out scrambled in the text layer (CONCOR JV p.135,
  Cochin government-transactions table p.225) and company-specific labels.

## 2. What to test

The free readers are LongCat, Dots and Step via Kilo, plus whatever OpenCode Go lists as free that day. Each reads
the same section files with the v2 instructions (`READER_INSTRUCTIONS_V2.md`). Each is scored on four things:

1. **Recall:** the share of must-find facts it finds, and the share of gold table items it finds.
2. **Precision:** every number it outputs is checked by grep against the text. Count misread numbers, wrong units
   (lakh vs crore), wrong periods (FY23 vs FY24) and wrong standalone/consolidated labels.
3. **False signals:** "contradictions" or "stress" claims that the reference text or the report does not support.
   Phase 1 Haiku made 1 in 9.
4. **Format:** valid CSV and fields, and page numbers that fall inside the section.

**Pass bar (proposed):**
- Must-find recall of at least 90%.
- No misread numbers in must-find items.
- False signals no higher than Haiku's.
- Models below the bar get a second reader or are used only on the sections they handle well.

## 3. What gets stored

Proposed. The quality test settles the fields.

- `ar_section_text`: keep-text only (auditor/CARO modifications, contingent and disputed items, delayed or
  disputed contracts, policy/regulatory paragraphs, MD&A risk paragraphs), plus changed-only sections stored when
  they differ from the previous year (first year = baseline).
- Tables:
  - audit-report modifications and KAMs
  - contingent liabilities and claims by type
  - capital commitments and capital advances
  - order book / contracted revenue
  - related-party share (BRSR) and transactions by party
  - subsidiary/JV P&L (AOC-1)
  - credit ratings
  - borrowings maturity
  - **cash flow and balance-sheet detail**
  - CSR obligation/spent/unspent
  - remuneration ratios
  - fleet or capacity lists
- Every row carries ISIN, fiscal year, report filing timestamp (point-in-time), page, unit, and
  standalone/consolidated.

Cash flow and balance-sheet detail are needed because the DB holds no cash-flow data today (yfinance OCF is 0 on 96%
of rows; see STATE → Known data gaps). This changes if the NSE results XBRL is parsed first.

## 4. Open dependencies

- The AR download stopped partway through the Nifty500 group (STATE → Known data gaps, item 1). Ingestion quality
  is moot for reports we never downloaded.
- Concall ingestion has to finish before free-model AR runs start (shared Kilo throttle).
- Which pipeline to extend: the deck-figures extractor already handles the free-reader rotation, throttling and a
  second reader for weak pages. Reuse it with an AR mode rather than building a new runner.
