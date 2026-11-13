# T-208 round 3: printed-results reader takes OCR words for garbled pages and joins wrapped labels

Ticket: T-208

Goal: PVRINOX Q2 FY27 revenue_from_operations is missing in both bases and consolidated `exceptional_items` holds the
PBT (3,511 Rs mn). Round 2 proved three code causes (DEVELOPER_GUIDE, block "T-208 round 2", item 5). Fix them as
general rules (any company, no per-company code), prove on copies, lose zero right rows in the other stores.

Evidence (read these first, nothing else needed to start):
- `docs/DEVELOPER_GUIDE.md` "T-208 round 2" item 5: causes (a) `comparatives` reads `page.get_text("words")` from the
  PDF, never `doc_page`/`ocr_page`; (b) wrapped label on p9: "Profit before share in net profit /(loss) of joint
  venture," then "3 exceptional items and tax (1-2) 3,511 ..." -- the continuation line alone matches
  `exceptional_items`; reproduces on PDF words AND OCR words; (c) TextRecognizer truncates p3's label to "Revenue fro"
  and reads p9's current-quarter revenue as "1,051" where the page prints 21,051.
- Document: PVRINOX `quarterly_results/fa10203c...pdf` (find the full doc_key in `D:/RealityEngine/s10/pvrinox/pvrinox.db`
  table `doc`), p3 standalone, p9 consolidated. Truth: standalone Q2FY27 revenue 20,620 (other income 287, total
  income 20,907); consolidated 21,051 (other income 342, total income 21,393; 6-month 37,273 = 21,051 + 16,222).
- Code: `reality_engine/pilot3/comparatives.py` (`match_line` l.139, `read_page` l.606, `run` l.819,
  `_extract_symbol` l.842); `reality_engine/v2/page_words.py` (`words_for`, its quality heuristic);
  `reality_engine/pilot3/build.py` (its `ocr_inputs`). OCR words: `D:/RealityEngine/s10/pvrinox/ocr/ocr_textrec.db`;
  page text and dictionary scores: `D:/RealityEngine/s10/pvrinox/pages.db`, `ocr_score_pages.csv`,
  `ocr_merge_log.csv`. Dictionary-score rule and threshold 0.75: round-2 item 1.

Steps:
1. Write failing tests first (`reality_engine/tests/test_comparatives_wrapped_ocr.py`, synthetic word rows, no real
   store): (i) a two-line wrapped label assigns the number to the joined label, not the continuation; (ii) a page under
   the dictionary threshold takes OCR words; (iii) an OCR value that breaks the page's own arithmetic (revenue + other
   income = total income, or quarter + previous quarters = 6-month/9-month) is NOT stored -- no row beats a wrong row;
   (iv) a label truncated by OCR ("Revenue fro") is matched only when the row's figure reconciles as in (iii).
2. Wrapped labels: join a label line with no number to the next line before `match_line`, as one general rule.
3. `page_words.quality`: use the dictionary score (same lexicon and 0.75 threshold as round 2) beside its share
   heuristics; `comparatives._extract_symbol` takes words from `page_words.words_for(store, doc_key, page, ocr_dbs)`;
   `build.py` passes its `ocr_inputs` to `comparatives.run`. OCR words for a figure are kept only when the
   reconciliation in step 1 (iii) holds; else the PDF word value if it reconciles; else no row.
4. Prove on copies with `python -m reality_engine.scripts.store_diff` (DEVELOPER_GUIDE "Store diff before a merge"),
   `--base main --head .` and `--parts comparatives,preferred,ratios` on: pvrinox (`--target pvrinox`), kei, medanta
   (s10 profiles beside each store) and `D:/RealityEngine/bluestar/bluestar.db`. Outputs under `.tmp/store_diff_t208r3_<n>`.
5. Show in the result: PVRINOX Q2FY27 revenue_from_operations standalone 20,620 p3 and consolidated 21,051 p9 via
   `fin_quarter_current` on the head copy; `exceptional_items` 3,511 gone; per-store churn and every removed or changed
   printed row in kei/medanta/bluestar listed with page (each one must be explained as a fix, or it is a regression).
6. Docs: a "T-208 round 3" bullet in `docs/DEVELOPER_GUIDE.md` after round 2 (rule, threshold, tests, store_diff
   numbers); PROGRESS_NOTES lines.

Files: `reality_engine/pilot3/comparatives.py`, `reality_engine/v2/page_words.py`, `reality_engine/pilot3/build.py`, the
new test file, `docs/DEVELOPER_GUIDE.md`. Live stores under `D:/RealityEngine` are read only; all writes in this
worktree's `.tmp/`.
Accept: python -m pytest reality_engine/tests/test_comparatives_wrapped_ocr.py -q
Test command: python -m pytest reality_engine/tests/test_comparatives_wrapped_ocr.py reality_engine/tests/test_store_diff.py -q
Pitfalls: never store OCR "1,051" for 21,051 -- that is the failure this round exists to prevent; no symbol- or
doc-specific branch; run pytest per file (one-process suites were reaped at 7.9 GB); store_diff one store at a time;
check free RAM before each build (stop a step if under 2 GB free).
Stop if: the fix needs a per-company rule; bluestar loses any right printed row you cannot explain; 3 hours.
Budget: 3 hours, 250 tool calls.
