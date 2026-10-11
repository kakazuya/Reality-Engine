# Challenger study: where annual reports need an LLM and where CPU/GPU rules are enough

Written 2026-10-11. Same three FY24 reports as the LLM study: COCHINSHIP (362 pages, ₹ lakh), CONCOR (432 pages,
₹ crore), GESHIP (171 pages, ₹ crore). Code and outputs in `challenger/`; nothing in `reality_engine/` or the DB
was changed.

## 1. Setup

**Challenger** (`challenger/extract_cpu.py`): PyMuPDF only, no model. For each page it:
1. assigns a section family from the heading or running header (auditor, CARO, C&AG, secretarial, BRSR, CSR,
   AOC-1/2, governance, MD&A, directors' report, AGM notice, statements, notes);
2. drops the AGM notice;
3. keeps whole blocks: auditor's report pages, CARO and C&AG pages, secretarial pages with observations;
4. keeps lines matched by a fixed red-flag lexicon, plus 3 lines of context either side (delay, dispute,
   disallowed, under protest, not acknowledged, reversal, rating, ETS/EUA, audit trail, unspent...);
5. turns table-bearing pages into (label, values) rows: PyMuPDF's table finder, then a word-position fallback
   (same baseline gives one row), then a plain-text fallback;
6. applies a credit-rating rule (agency + grade + outlook);
7. tags each page with a unit (lakh/crore/million, from the page header) and a scope (standalone/consolidated).

**Gold sets:**
- `gold_numbers.json`: 948 numbers that the Haiku readers cited with a page reference, each confirmed present on
  that page. Bare integers (page and note numbers) are excluded.
- `gold_mustfind.json`: the 17 headline signals, checked by hand.

**Grades for each gold number:**

| Grade | Meaning | Needs an LLM? |
|---|---|---|
| clean | labelled row, label ≤ 12 words, ≤ 2 values (current/previous year) | no |
| multicol | labelled row with more than 2 values; the column headers still need mapping | a rule-based header parser should do; LLM as fallback |
| sentence | the number sits in prose; the "label" is a sentence fragment | yes, to name the metric (or keep it as text) |
| no-label | number found, label lost | rules can probably fix (layout) |
| captured | only inside kept text | yes, to structure it |
| missed | not in any output | yes, or more rules |

## 2. Results

**Speed:** 35-68 s per report on one CPU core, about 1 minute. Output per report: 3,400-6,000 rows, and 15-20% of
the text kept as signal text.

### All 948 gold numbers

| clean | multicol | sentence | no-label | captured | missed |
|---|---|---|---|---|---|
| **37%** | 21% | 20% | 8% | 4% | 11% |

### Split by where the number sits in the report

| | n | clean | multicol | sentence | no-label | captured | missed |
|---|---|---|---|---|---|---|---|
| **Tabular** (number on its own line) | 709 | 46% | 27% | 12% | 10% | 1% | **4%** |
| **Prose** (number inside a sentence) | 239 | 10% | 3% | 46% | 0% | 10% | **30%** |

### By section family (gold numbers that ended up in some row)

- Statements: 100%.
- BRSR: 97%.
- Notes: 93%.
- CARO: 81%.
- Directors' report: 78%.
- MD&A: 69%.
- Governance: 55%.
- CSR: 33%.
- AGM notice: 0% (dropped by design).

### Must-find signals: 16 of 17 found by CPU

| Item | Result |
|---|---|
| Cochin operating cash flow (standalone and consolidated), contract liability; CONCOR SEIS 861.05, related-party purchases 73.65%; GESHIP capital commitments, time-charter receivables, related-party loans 4.69% | clean rows |
| CONCOR KAM ₹677.68 cr, CONCOR EoM (unbooked leases), Cochin C&AG SBFA comment, Cochin and GESHIP audit-trail items, GESHIP CARE AAA (rating rule), GESHIP EU ETS (lexicon) | captured as text or rows |
| CONCOR receivables 329.45 | found, label lost |
| **Cochin: two 1,200-passenger vessels past delivery, customer asks to reallocate (p.138)** | **missed.** Ordinary prose in a note, with no red-flag word. This is the kind of item only reading finds |

### Units

The page-header unit agrees with the unit the reader wrote next to the number in 125 of 134 checks. Some of the 9
disagreements are readers converting lakh to crore; at least one is a real error (CONCOR p.203 tagged lakh, actually
crore). The unit needs to be taken from each statement or table header, not the page.

### GPU / OCR

- The two tables a reader flagged as unreadable (CONCOR p.135 JV table, Cochin p.225): OCR found the same figures as
  the text layer. The problem is column layout, not missing text.
- All 21 low-text pages across the three reports, OCR'd: **0 figures** (photos and covers).
- For these reports **GPU OCR adds nothing**. Keep RapidOCR as a fallback for scanned reports only; none of the
  60-report sample was scanned.

## 3. Where each kind of work belongs

| Work | CPU rules | Needs an LLM |
|---|---|---|
| Section map, dropping boilerplate | ✔ (headings and running headers are reliable) | |
| Statutory signal blocks: auditor (KAM, EoM, modifications, audit trail), CARO, C&AG, secretarial | ✔ capture whole (small: a few % of pages) | to **interpret** them (what changed, how material) |
| Fixed forms: BRSR Section A, credit ratings, AOC-2, statements, two-column notes | ✔ ~46% of tabular gold is clean rows already | |
| Multi-column notes (segments, JVs, maturity buckets, related parties by party) | ✔ with a column-header parser, still to build (27% of tabular gold) | fallback when headers are irregular |
| Lost labels | ✔ layout fixes (10% of tabular gold) | |
| Numbers inside prose (MD&A, directors' report, narrative notes, contingency text) | ✗ | ✔ **about 75% of prose numbers** are sentence fragments, text-only or missed |
| Surprises with no trigger word (Cochin's vessels) | ✗ | ✔ reading the narrative notes and MD&A |
| Mapping company-specific labels to one schema across companies | partial (dictionary) | ✔ or a local embedding model (untested) |
| Units and periods | ✔ from statement/table headers (current page-level rule is ~93% right) | |

**What the LLM would read:** the kept signal text (15-20% of characters) plus the "sentence" rows, instead of the
whole report. That is roughly a fifth of today's input, aimed where the judgement items are.

**What the free LLMs are needed for** in the next test (`FREE_MODEL_QUALITY_PLAN.md`):
1. Turning prose numbers into rows.
2. Interpreting auditor, C&AG and contingency blocks.
3. Reading narrative notes for untriggered surprises.
4. Normalising labels.

**Not needed for:** the bulk tables.

## 4. Caveats

- **The rules were tuned on these same three reports**, so expect lower scores on unseen reports. Next step: run
  unchanged on 10 unseen reports from other sectors, especially a bank and an NBFC, whose formats differ most.
- The gold set is what Haiku chose to cite. That leans towards tabular numbers and away from long tables nobody
  cited. Recall is measured on cited facts, not every row in the report.
- "clean" means the number has a short label in the same row. It does not prove the label and year column are right.
  A sample of about 40 rows looked right in most cases. Multi-column rows need header mapping before they are
  trustworthy.
- The lexicon's precision was not measured: 15-20% of text kept is broad.

## 5. Proposed next steps

1. Build the column-header parser and per-table unit/period detection (CPU).
2. Run the extractor unchanged on 10 unseen reports, then grade a sample by hand or with Haiku.
3. Free-model test on the LLM slice only: kept text plus sentence rows, scored against the gold set. Start after
   concall ingestion finishes.
4. Bulk run: about 1 CPU-minute per report, so about 12.7k reports ≈ 210 CPU-hours, about 1 day on 10 workers.
   This waits for the download job (STATE → Known data gaps, item 1).

---

# Part 2 (2026-10-11): column-header parser and a test on 10 unseen reports

## What was built (`challenger/columns.py`, CPU only, no templates)

The parser has **no per-company or per-table templates**. For every page it works out the layout itself:

- **Lines and spreads.** It rebuilds lines from word positions, re-joins numbers split by kerning, and splits
  two-page spreads at the gutter (GESHIP prints two report pages on one PDF page).
- **Table blocks.** A run of numeric lines is a table. Short label or header lines inside it are allowed; a prose
  line or a large gap ends it. A number inside a label ("Less than 1 year") stays part of the label.
- **Columns** come from clustering the right edges of the figures, which are right-aligned.
- **Headers.** Words above each column become its header, assigned phrase by phrase:
  - a phrase spanning several columns ("As at 31 March") goes to all of them;
  - a group header in the gap between two columns (a JV name over its two years) goes to both;
  - a table continued on the next page inherits the previous page's header.
- **Wrapped labels** attach to the nearest numeric line.
- **Years** (fiscal year end) are read from header text in any word order. A year in the row label is also used.
  Two unlabelled columns default to current year, then previous year (marked `*`).
- **Units** come from the table's own header or the text just above it, falling back to the page, then the report.
- **Confidence** per table = share of value columns with a header (40%) + share with a year (30%) + share of rows
  with a label (30%).

The extractor now parses tables on **every** page. Section tags only decide which text to keep, because tagging
drifts on unseen layouts and was hiding whole balance sheets.

## Results on the three tuned reports

- Tabular gold numbers in a labelled row: **71% clean** (was 46%); 6% missed.
- Year check (pairs like "X (FY23 Y)" from the readers' text, numbers in a column row): 23 right, 1 wrong,
  4 with no year (**82% right**).
- Speed: 4-7 s per report (was 35-68 s with PyMuPDF's table finder).
- Prose numbers are now mostly "missed" rather than half-useful sentence rows. That is by design: they are the LLM's
  job.
- Must-find: still 16/17. The miss is again Cochin's vessels.

## Results on 10 unseen FY24 reports (rules unchanged during the run; general fixes in between)

Report: `challenger/unseen_report.md`.

| Report | Balanced statements found (of 4) | Revenue / profit vs yfinance | Figures on table-dense pages in a labelled, dated row |
|---|---|---|---|
| Axis Bank | 0 (bank format; its MD&A summary tables did balance) | - | 44% |
| Bajaj Finance | 0 (balance sheet split over pages, 41% low-confidence tables) | - | 37% |
| Infosys | 0 | (yfinance reference is wrong scale) | 35% |
| Dabur | **4** | revenue ✔ (12,404 vs 12,262) | 57% |
| Cipla | 2 (consolidated) | - | 39% |
| Cummins | 0 | - | 59% |
| Atul | 2 (standalone) | - | 47% |
| Exide | 0 | - | 49% |
| Sobha | 0 | revenue ✔, profit ✔ (₹ million, right unit) | 51% |
| JK Cement | **4** | profit ✔; revenue 11,556 vs 11,203 (yfinance's definition likely differs) | 52% |

**Hand check of 30 random rows from these reports:**
- About 15 are correct (label, year and unit).
- About 6 have the right label but no year (related-party and sensitivity tables, where a year does not apply).
- About 9 are wrong or junk: a merged label, a director's DIN read as a value, a % holding tagged as ₹ crore,
  and empty labels.
- Most junk rows have confidence below 0.7. Three Infosys rows and one Bajaj row did not.

## What this means for "CPU vs LLM"

1. **The parser does adapt.** Standard two-column statements and notes come out right on unseen reports
   (balance-sheet identities hold for Dabur and JK Cement in full; Sobha's revenue and profit match yfinance in
   ₹ million).
2. **It is not good enough to trust blindly on unseen reports.** About a third to a half of table figures land in a
   labelled, dated row, and about 30% of random rows are wrong. The tuned reports looked much better, so the earlier
   numbers were optimistic.
3. **Proposed design:**
   - CPU parses everything and keeps tables with confidence ≥ 0.7 *and* passing a check (balance identity, totals
     adding up, a match with another source).
   - Tables that fail are sent to a free LLM **as that table only**, not the whole report.
   - Prose and judgement blocks always go to the LLM.

   This keeps LLM volume to a slice of each report, which is what the cost limit needs.
4. **Bank and NBFC reports** (schedule-based statements, balance sheet over two pages) are the weakest. They need
   either a bank-format pass or default routing to the LLM.

## Remaining CPU work, in order of payoff

1. **Validation layer.** Check that a table's subtotals add up to its "Total" rows and that the balance sheet
   balances across pages. A table that passes can be trusted without an LLM; this is the main quality gate.
2. **Units for % and counts.** If the column header or the value has %, holding, number or shares, it is not ₹.
3. **Label merging.** Stop attaching the next section's heading to a total row ("Total assets EQUITY AND
   LIABILITIES").
4. **Bank/NBFC schedule format** and statements split across pages.
5. **Store a routing flag per table:** `cpu_ok` / `send_to_llm`. Measure what share of each report goes to the LLM.

---

# Part 3 (night of 2026-10-11): build steps 1-4 run on 13 reports (CPU only, low priority, alongside the extraction jobs)

Code: `challenger/xbrl_tie.py` (step 1), `yoy.py` (step 2), `gate.py` (step 3), `run_step4.py` + `row_verify.py`
(step 4). Report: `challenger/step4_report.md`. Each report takes 9-17 s including parsing last year's report.

## Step 1: XBRL statements tie to the annual report (works)

The annual "Yearly" results XBRL holds the full-year flows (context `FourD`) and the year-end balance sheet (`OneI`).
For 12 of 13 reports, **60-90% of XBRL figures are found in the report's parsed tables**, with correct labels.
Examples:
- Dabur consolidated revenue 12,404, PAT 1,811.31, operating cash flow 2,013.47.
- Infosys revenue 1,53,670.
- Cochin operating cash flow -17,282.73 lakh.

Axis Bank: 38-50 of 85, because the bank taxonomy differs. **Decision: statement figures come from XBRL**; the
report's figures are the cross-check.

## Step 2: year-over-year diff (works for surprises)

Shingle diff against last year's report. Cochin's untriggered vessel note (79% new) and the SBFA/C&AG passages
(77-96% new) are flagged new. Repeated statutory text is not re-sent: CONCOR's EoM on unbooked leases is repeated
from FY23, so it is stored from the baseline year, not sent again.

## Step 3: validation gate

A table is `cpu_ok` when any of these holds:
- an XBRL figure matches;
- subtotals add to totals (with confidence ≥ 0.7);
- **prior-year tie**: its FY23 column equals the FY24 figures printed in last year's report. This is the strongest
  general check, and it took gate-passing cells from 22% to 47%.

Rows inside passing tables must also have a label and a year (or be a % or count) to be stored.

## Step 4: results (13 FY24 reports)

| Measure | Result | Target |
|---|---|---|
| Table cells stored by CPU, table-level gate + row filter | **33%** (25-52% per report) | — |
| Table cells verified at **row level** (a cell in that row matches XBRL or last year's report) | **28%** (12-40%) | — |
| Hand check, 39 random rows from passing tables | ~74% fully right | ≥ 90% ✘ |
| Hand check, 39 random row-verified rows | ~72% fully right, ~87% with the right value, year and unit but a vague label | ≥ 90% ✘ (close on value/year/unit) |
| Must-find signals reaching storage or the LLM | 15/17. K2 is repeated from FY23 (by design); G5 sits on a BRSR spread page the parser missed | ≥ 90% ✔ |
| LLM share: new prose | 28% of characters (~87 page-equivalents per report); the flagged-only tier is 21% | was estimated ~9% ✘ |
| LLM share: tables failing the gate | ~44 page-equivalents per report | — |

## What the numbers say

1. **The CPU reliably gets the number, year and unit; it does not reliably get a clean label.** The remaining
   errors are:
   - labels merged with headings or cut off;
   - counts or tonnes tagged as ₹;
   - absolute rupees tagged as lakh;
   - an odd header bleeding into the year.

   CPU alone plateaus at about 75-85% row quality. The 90% target is not reachable with more rules in a reasonable
   time.
2. **Cheapest way to reach ≥ 90%: send compact rows, not pages, to a free LLM.** CPU rows (label | column header |
   year | unit | value, about 60 characters each) go to a free model to normalise the label and confirm the unit.
   Verified rows are about 2k cells per report, roughly 30 page-equivalents of text. The LLM never re-reads the
   table page, and every number stays tied to the source by the CPU match.
3. **The LLM share for prose is larger than the earlier estimate** (28%, not 9%). The 9% figure used a narrower
   filter that missed untriggered items. Tomorrow's tuning:
   - require novelty ≥ 0.6 for red-flag lines (statutory pages stay at 0.4);
   - shorten the lexicon (upgrade, reversal and demand fire too often);
   - drop BRSR and governance prose unless flagged.

   Expected ~12-15%. Must-find recall needs re-checking after every tightening.
4. **Total load per report, honestly:**
   - about 130 page-equivalents to the free LLM today (prose 87 + tables 44);
   - after the tuning above plus row-mode for tables, expect about 40-60, against ~280 pages per report.

   At 12.7k reports that is ~0.5-0.75M page-equivalents, roughly the size of the deck job, not half of it.

## Next (for 2026-10-12)

1. Tune the prose slice: novelty and lexicon as above. Re-measure must-find recall and the LLM share.
2. Row-mode LLM pass design (prompt + output schema: canonical label, unit, keep/drop). Test on the 39 + 39
   hand-checked rows with one free model once the Kilo throttle is free.
3. Fix the BRSR spread pages (G5) and counts/tonnes in BRSR and environment tables (unit `count` / physical units).
4. Then the free-LLM slice test (plan step 5) and storage (step 6).
