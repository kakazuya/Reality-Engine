# Task: chart/image-aware vision pass — annual-report image pages + deck low-text leftovers (free readers only)

Owner: Shivam (2026-10-24: "Do it"). Reviewer: Claude.

## Context (from `tasks/CONCALL_READER_READINESS_2026-10-24.md`, images section)

- Annual reports are chunked text-layer only. ~700 reports have < 50% text pages = 86,053 pages of which only 12,532
  have text (~73.5k image-only pages); FY26: 110 reports < 50% text, 65 < 20%; plus 70 FY26 reports with mis-encoded
  font layers.
- Decks (`deck_figures.db`): 815,837 pages, 62,598 low-text image-heavy pages got no vision output.
- The deck pipeline already does this well: render page → vision reader → `facts(metric, period, raw_number, value,
  unit)` + `chart_trends`, with routes, recall checks, spend/call logs (`pages`, `outputs`, `facts`, `chart_trends`).
  Free vision reader **dots-3** (`dots-studio/dots-3-note-preview:free`, also via Kilo keys) ran ~10k pages/h at $0.

## Do

1. Reuse the deck page-reader code path (find it: the script that fills `deck_figures.db`; prompt versions; routes)
   for annual-report pages. Store AR results in `ar_facts.db` in new tables mirroring the deck ones
   (`ar_vision_pages`, `ar_vision_outputs`, `ar_vision_facts`, `ar_vision_chart_trends`) with doc_id/isin/symbol/
   fiscal_year/page_no/known_at, so the AR text facts stay untouched. Schema change additive only.
2. Page selection: image-only or low-text pages (text_chars small, numbers present in image) of annual reports, plus
   pages of the 70 mis-encoded FY26 reports. Order newest → oldest (FY26 first). PDFs: FY26 are on disk
   (`reality_engine/data/pdfs`, `D:\RealityEngine\pdfs`); older ones need fetching from Drive
   (`gdrive:InfoDiffusion_archive/pdfs`, `D_pdfs`) — fetch only the reports you need, newest first, and delete the
   local copy after its pages are read if disk gets tight (keep FY26).
3. Deck leftovers: the 62,598 low-text pages with no vision output — deck PDFs are not on this laptop; fetch from
   `gdrive:InfoDiffusion_archive/decks` the needed decks only, newest first.
4. Free readers only: dots-3 (OpenRouter free + Kilo keys 1/2), with the existing 429 handling and three-strikes cull;
   no paid model. Respect `known_at` (point-in-time) on every row.
5. Quality gate before bulk: 30 AR image pages also read by the same reader on two prompts → spot-check 10 pages
   by comparing facts to the page (render the page PNG and check numbers). Report precision of values and a sample.
6. Run in the background with resumable state; progress lines into a log; respect the single-writer rule per DB.
   Run tests for any new code.

Final answer: what was built, gate results, pages/hour, pages done vs queued (AR FY26 / older AR / decks), facts
written, and how to resume. Leave the run going if it is healthy and not finished; say so.
