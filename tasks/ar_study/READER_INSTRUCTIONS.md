# Annual-report part reader: instructions

You are reading one ~50-page part of an Indian company's FY24 annual report (AR). The question: **what does this
part of the AR tell an investor that the same year's earnings-call transcripts and investor presentation do not?**

## Inputs (read in full)
1. Your AR part (text extracted per page, marked `=== PAGE n ===`; n = PDF page number).
2. The company's REFERENCE file: FY24 Q3 + Q4 earnings-call transcripts (and investor decks where available).
   "New" means not stated in the REFERENCE.

The files are long, so use the Read tool with `offset`/`limit` to read them in chunks until you have read every line.
Do not skim. Do not open any other file. Do not edit any file except your output.

## Output
Write ONE CSV file (path given in your task) with a header row and one row per AR section, or per sub-section where
the value differs, found in your pages:

`section,pages,tokens_est,new_info,overlaps_concall_ppt,when_useful,situation,items_to_extract,example_quote_or_page,verdict`

- section: the heading as printed (e.g. "Directors' Report - Material changes", "Notes - Contingent liabilities",
  "CARO annexure", "BRSR Section A"). A section cut off at the start or end of your part still gets a row; say so.
- pages: PDF page range, e.g. `112-118`.
- tokens_est: roughly the section's characters ÷ 4.
- new_info: none / some / lot.
- overlaps_concall_ppt: yes / partly / no.
- when_useful: always / situational / never.
- situation: fraud-stress / policy-change / related-party / auditor / capex / other / - .
- items_to_extract: specific numbers or facts that belong in a table (e.g. "contingent liabilities by type, ₹ cr";
  "order book by customer"). Use `-` if none.
- example_quote_or_page: the best piece of evidence, with its page number, e.g. `p.143: "Income tax demand of ₹412 cr
  under appeal"`. Keep quotes under 25 words.
- verdict: keep-text / table / changed-only / drop.
  - keep-text: prose that holds new judgement or facts worth storing as searchable text.
  - table: the value is in specific numbers; store them as rows, drop the prose.
  - changed-only: usually boilerplate, worth storing only if it differs from last year (e.g. auditor, policies).
  - drop: marketing, statutory boilerplate, or repeated from the calls/decks or XBRL financial statements.

Quote CSV fields that contain commas with double quotes.

After the CSV, append to the SAME file, after a blank line, a block starting with `# NOTES` that lists in 3-10
bullets: (a) the most valuable new facts in your part, each with a page number; (b) anything that hints at stress,
related-party leakage, auditor unease, or a policy or regulatory change, with page numbers; (c) anything in the
REFERENCE that this part contradicts.

## Rules
- Quote a page number for every claimed signal. Do not invent findings: "nothing new" is a valid answer.
- For situational items, say what situation would make them matter and why (e.g. "tax demand = 40% of net worth;
  matters only if the case is lost").
- Main financial statements (balance sheet, P&L, cash flow) already come from XBRL: verdict `drop` unless something
  in them contradicts the calls.
- Your final message: just the output path and one line on the most important finding.
