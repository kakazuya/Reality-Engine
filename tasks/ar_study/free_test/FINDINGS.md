# Free-reader AR test, baseline (2026-10-11, test only, nothing stored)

Whole sections (GESHIP v2 split) or 50-page chunks (COCHINSHIP, CONCOR) of the 3 gold FY24 reports, sent in the
prompt to LongCat 2.5 Preview (OpenCode Go, free) and Dots 3 Note (Kilo key 2, free). Each returns every storable
fact as CSV rows. Scores in `SCORES.md`, raw answers in `outputs/`, code in `free_reader_test.py`. Step was left out
because the deck run's second readings use it.

This is NOT the approved design's test (HANDOFF_AR_PIPELINE.md: CPU tables + gate, LLM on the slice and on compact
rows). It answers a narrower question: can the free readers read AR pages at all and get the checked facts right?

| | LongCat | Dots |
|---|---|---|
| Must-find recall (25 checked facts) | **25/25** | 23/25 (missed Cochin consolidated OCF, SAP edit log) |
| Numbers not found in the section text | 22 of 3,746 (0.6%) | 25 of 7,769 (0.3%) |
| Rows | 4,722 | 9,302 |
| Answers cut at the 32k output limit | 1 of 26 | 7 of 26 |
| Median time per call | ~2 min | ~3.4 min |
| Tokens in / out | 0.87M / 0.23M | 0.87M / 0.48M |

What the "numbers not found" are (sample of 20): mostly not misreads. Dates rewritten as ISO, values converted to
another unit (₹18,00,00,000 written as 1,800 lakh), totals the model added up itself (employees 2,101), USD amounts
given as "2.00". The prompt said "exactly as printed", and both models sometimes ignore that. Unit conversion by the
model is the real risk.

Problems:
- **Dots loops.** GESHIP S1 (AGM notice) gave 546 rows, only 100 of them distinct, and ran to the output limit; 7
  answers were cut, and one chunk (CONCOR p51-100) came back with no CSV at all. Dots is not usable on whole sections
  without a repetition guard and smaller inputs.
- **CSV breaks.** Unquoted commas (Indian grouping, labels) broke rows: LongCat CONCOR p351-400 had 144 of 160 rows
  malformed. The production format should be JSON lines or a stricter schema.
- The checks here are digit matches. Label, unit (lakh/crore), period and standalone/consolidated correctness are
  NOT scored yet. That needs the hand-checked rows (`challenger/hand_check_verdicts.csv`).
- Gold-list fix: GESHIP CSR spent is ₹18.77 crore in the report (₹18,77,77,325), not 18.78.

Takeaway: LongCat reads AR text well enough to find every checked fact, with few unsupported numbers. Dots needs a
loop guard. Next is the approved design's row-mode test (suggestion 1) on the 39+39 hand-checked rows.

## Nemotron and NVIDIA NIM (2026-10-11): dropped

- Nemotron Ultra via Kilo: 4 of 26 parts answered in ~50 min; the rest were NVIDIA "overloaded" (503) or dropped
  connections.
- NVIDIA NIM (Shivam's free key, `NVIDIA_API_KEY`), whole-section test with thinking off
  (`chat_template_kwargs.enable_thinking=false`; with thinking on, Super spent 80% of its output on reasoning):
  - Nemotron 3 Super: all 26 parts answered, but **14/25 must-find**, 2.5% of numbers not in the text. Several
    50-page chunks came back almost empty (19-280 output tokens).
  - Nemotron 3 Ultra: 1-3 min per section plus 503s; stopped partway (12/25 on the parts it finished), too slow.
- Screen of 22 other NIM chat models on GESHIP S6 (25 pages): 11 are listed but return "Not found for account";
  DeepSeek V4.1 Flash, Kimi K3, GLM 5.3, Gemma 4 31B, Llama 3.2 90B did not start answering within 3-5 min (free-tier
  queue); GLM 5.3 Flash and Nemotron 3.5 Lightning / Nano Omni spent the budget on reasoning (no CSV). Answered:
  Laguna XS 2.1 (32 s, 36 rows, 0 numbers not in text, many malformed rows), Muse Glimmer 30B (244 s, 53 rows, 0),
  gpt-oss-20b (140 s, 31 rows, 1).
- Decision (Shivam's rule "if slow, drop"): NIM is too slow or too weak for bulk AR reading. Keep the OpenCode Go and
  Kilo free models (LongCat passed 25/25).

## Row clean-up test (protocol gate 1), LongCat, 2026-10-11

`row_cleanup_test.py`; side-by-side answers in `row_cleanup_results.md`. 78 hand-checked rows (39 cpu_ok + 39
row-verified), one call per table block (64 calls per variant, ~2-15 s each). V1 = the table's rows only; V2 = rows plus
the page text. Judged by Claude from the row fields, column headers and the AR study's verdicts, not by re-opening
every page. 4 rows could not be judged (INFY 207/292, CIPLA 94, INFY 290's 1-digit coincidental match) and are left
out (74 scored).

| | parser alone | V1 rows only | V2 rows + page | V1 + guards | V2 + guards |
|---|---|---|---|---|---|
| fully right | ~72% (56/78) | 77% (57/74) | 78% (58/74) | ~88% (65/74) | **~95% (70/74)** |

The model fixes most parser errors: share counts, tonnes, m3, % and absolute rupees get the right unit, and cut or
merged labels get completed (V2 better, since it sees the page). But it also adds errors of its own, of three kinds,
which simple rules catch:
1. **Currency scale turned into "rupees"** on crore tables (V2: 5 rows, V1: 2). Guard: never let the model move a
   currency-scale unit (lakh/crore/million) to rupees, or between scales, unless the page header supports it; accept
   non-currency units (count/shares/%/tonnes/m3...).
2. **Period changed against the column header** (e.g. "As at 31/03/2023" turned into 2024; 4 rows V2, 5 V1). Guard:
   keep the parser's period unless it is empty, or the column header holds the model's year and not the parser's.
3. **Label swapped for another row's label** (e.g. "Turnover" -> "Reserves & Surplus", "Railway Siding" ->
   "Building..."). Guard: the new label must share most content words with the parser's label, else keep the parser's
   label and flag it. Also, keep=false is ignored for verified rows (one verified "Power and fuel" row was dropped).
Left after guards (V2): a wrong label context added (CONCOR 365 "guarantee", CUMMINSIND 187 cash-flow text, SOBHA 216)
and ATUL 184's unit (thousand -> should be crore; the model said count).

Caveats: the guards were designed on this same sample (risk of overfitting), and the judging is from fields, so the
~95% needs confirming on a fresh, page-checked sample before production.
Cost: V2 sends one page of text per table block, which is ~100-150 page-equivalents per report (not the ~30 planned
for rows only). A hybrid keeps it lower: V1 for clean rows, V2 only for suspicious ones (long or merged labels, short
labels like "Others"/"Total", currency units on pages without a currency header).

## Guards built + fresh page-checked confirmation (2026-10-11)

Guards are now pipeline code: `reality_engine/processing/ar_row_guards.py` (tests: `reality_engine/tests/test_ar_row_guards.py`,
12 cases from both rounds). The model's own label never counts as evidence, and the model may not change scope.

Fresh test (`fresh_rows_test.py`): 6 FY24 reports never used before (SUNPHARMA, LT, ICICIBANK, TITAGARH, KPIGREEN,
NAVINFLUOR). Each row was judged by Claude against the page text around its value (`fresh_review.md`, `fresh_vreview.md`).

| sample | scored | parser | V1 + guards | V2 + guards |
|---|---|---|---|---|
| round A: any storable row (not what production cleans) | 45 | 56% | 67% | 76% (82% with the evidence fixes below) |
| round B: **verified rows** (XBRL or prior-year tie, >= 3 significant digits) | 53 | 58% | 79% | **89% (47/53)** |

After the guards, **no unit or year corruption reached the output** in round B. About 12 bad year changes were rejected, and
the swap guard blocked real swaps. Fixes made during the rounds (all in the tests): count evidence includes
"Quantity"/"options"; "ratio" counts as evidence for times; "‘000s" with a curly quote counts for thousand; the page header
is the first 15 lines; a label made only of words from the row's own label and column is a trim, not a swap.

The 6 rows still wrong in round B (V2):
- wrong context added: "Stock-in-trade - Goods-in-transit" (SUNPHARMA p244), "Fair value" for a carrying value
  (KPIGREEN p167);
- the parser's label belongs to another row and the model kept it (KPIGREEN p221: gratuity provision labelled current
  tax);
- a merged heading kept ("Net block ... I. Gross Block"), a typo ("March 31, 224"), a BRSR row with no period.
Values were right in every scored row.

Takeaway: V2 + guards is at ~89% fully right on unseen verified rows, against 90% target and ~58% for the parser
alone. The remaining errors are label context, not number/unit/year corruption. To pass 90% cleanly: a second reader
when the two readings disagree on the label, and a check that a label naming a different measure (fair vs carrying,
gross vs net) is supported by the column header.

## Gemma 4 31B and Glyph Cluster on the AR test (2026-10-12)
- **Gemma 4 31B (Google AI Studio free keys, native API, thinking minimal): PASSES.** 25/25 must-find, 0.4% of 2,638
  numbers not in the text (LongCat: 25/25, 0.6%). Sections cut into ~10-page pieces (99 pieces) because the free tier is
  16k tokens/min per project; ~75 s per piece. Throughput: ~15 report pages/min per key (~20k pages/day per account).
- **Glyph Cluster (Kilo free, stealth reasoning model): FAILS.** 18/25 must-find, 6.5% of 1,332 numbers not in the text
  (~10x Gemma/LongCat), and 7 of 26 sections timed out upstream (HTTP 408).
