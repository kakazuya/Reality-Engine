# Task: local OCR pilot on the laptop GPU vs Haiku's deck facts (≤ 200 pages, free)

Owner: Shivam (2026-10-24). Reviewer: Claude.

## Question
Can a local OCR model on this laptop's **GTX 1050 Ti (4 GB, Pascal sm_61)** + the free text reader reproduce the
facts Claude Haiku extracted from hard investor-deck pages, well enough to process image pages for free?

## Setup
- Reference: `reality_engine/data/deck_figures.db` — `pages` where `final_model='claude-haiku-5-5'` (16,012 hard,
  image-heavy pages; avg text-layer recall 0.48) and their `facts(metric, period, raw_number, value, unit, is_final)`.
  Sample **200 pages**, stratified across years 2021–2026 and page types (tables, bar/line charts, KPI tiles), seed
  fixed. Use `connect_ro`.
- PDFs are not on this laptop: fetch only the needed decks from `gdrive:InfoDiffusion_archive/decks` (match by
  sha256 / `deck_sources.local_path` basename) into this worktree; render the pages to PNG at the same DPI the deck
  pipeline uses (find it in the deck reader code).
- OCR arm 1: **PaddleOCR-VL** (latest, ~0.9B). Install into a separate venv in this worktree. Try GPU on the
  1050 Ti (check CUDA/compute-capability support; try 4-bit/8-bit or the smallest backend that fits 4 GB); if the GPU
  path is unsupported, say exactly why and run it on CPU for timing anyway. Output Markdown/tables per page.
- OCR arm 2 (fallback/baseline): **RapidOCR** (repo's `ocr_engine.py`; onnxruntime CPU or CUDA if it works).
- Fact step: feed each page's OCR text to the free text reader we use in production (`beam-free` via Go key 2 or Kilo,
  stable session id) with the deck fact prompt adapted to text input (same output schema). Also score "OCR text
  alone" (does the number string appear anywhere in the OCR text) as an upper bound on recall.

## Metrics (per arm, overall and by page type/year)
- Recall vs Haiku's final facts: a Haiku fact counts as found if the same value (unit-normalised, ±0.5% or exact
  string) appears for the same metric (fuzzy metric match) — report strict (value+metric+period) and loose (value).
- Precision: facts the arm produced that are not on the page (spot-check 20 pages by viewing the PNG yourself:
  render and compare numbers); report wrong-value rate.
- Speed: seconds/page OCR (GPU vs CPU), reader seconds/page; projected hours for 73.5k AR image pages + 62.6k deck
  leftovers.
- Success marker (decided now): strict recall ≥ 0.85 of Haiku's and wrong-value rate ≤ 1% → viable for bulk;
  0.70–0.85 → viable only with a second check; < 0.70 → not viable.

## Output
`tasks/research/local_ocr_pilot/REPORT.md` + `results.json` + the scripts. No paid calls. Final answer: the
metric table per arm, GPU feasibility finding, speed/projection, verdict vs the marker, and 3 example pages where
the arms disagree with Haiku.
