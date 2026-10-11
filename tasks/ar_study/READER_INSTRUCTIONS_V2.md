# Annual-report section reader: instructions v2

Changes from v1 (Phase 1): one reader per **section** (not per 50 pages); readers compare against a short
**REFERENCE_FACTS** list instead of the full transcripts (the full file is there to grep only when unsure); the
verdict rules are stricter; one row per sub-section that has its own verdict, not per heading.

## The question

You are reading one section of an Indian company's FY24 annual report (AR). What does this section tell an investor
that the same year's earnings calls and investor decks do NOT already say, and that the company's XBRL filing
(the main financial statements: balance sheet, P&L, cash flow and their standard line items) does not already hold?

## Inputs

1. Your AR section file (text per page, marked `=== PAGE n ===`; n = PDF page number). Read every line, using the
   Read tool with `offset`/`limit`.
2. `REFERENCE_FACTS` (path in your task): every fact and number stated in the FY24 Q3 and Q4 calls and decks. Read it
   in full first.
3. `REFERENCE` (full call and deck text, path in your task): do NOT read it in full. Use Grep on it to check a
   specific claim before you call something "new" or a "contradiction".

Do not open any other file. Do not edit any file except your output.

## Output

ONE CSV file (path in your task). Header:

`section,pages,tokens_est,new_info,overlaps_concall_ppt,when_useful,situation,items_to_extract,example_quote_or_page,verdict`

- At most about 15 rows. A row is a sub-section with its own verdict (e.g. "Notes - Contingent liabilities"). Group
  boilerplate together (e.g. one row for "Accounting policies (all)").
- tokens_est = characters ÷ 4. new_info: none / some / lot. overlaps_concall_ppt: yes / partly / no.
  when_useful: always / situational / never. situation: fraud-stress / policy-change / related-party / auditor /
  capex / other / -.
- items_to_extract: the specific fields worth storing as table rows, or `-`.
- example_quote_or_page: the best evidence, with the page, quote under 25 words.
- verdict, strictly:
  - **keep-text**: prose with judgement or facts that are new and would change an investor's view. Expect this to
    be rare: about 10% of a section's tokens at most.
  - **table**: specific numbers NOT in the main financial statements (e.g. contingent liabilities by type, fleet
    list, related-party transactions by party, remuneration ratios). Figures already in the balance sheet, P&L or
    cash flow are `drop`, not `table`.
  - **changed-only**: boilerplate worth storing only if it differs from last year (policies, governance
    structure, auditor).
  - **drop**: everything else: statutory text, marketing, anything already in the calls, decks or XBRL.
- Quote any field containing a comma with double quotes. Check that every row has exactly 10 fields.

After the CSV, a blank line, then `# NOTES` with 3-8 bullets:
(a) the most valuable new facts, each with a page;
(b) hints of stress, related-party leakage, auditor unease, or a policy/regulatory change, with pages;
(c) contradictions with the calls/decks. Only list a contradiction after grepping the REFERENCE for it, and
    give the REFERENCE line. Differences of definition (e.g. standalone vs consolidated, gross vs net) are not
    contradictions: say "definition difference" instead.

## Rules

- Quote a page for every claim. "Nothing new" is a valid and common answer.
- Watch the units: crore vs lakh vs million, standalone vs consolidated.
- For situational items, say what situation would make them matter and why.
- Final message: the output path and one line on the most important finding.
