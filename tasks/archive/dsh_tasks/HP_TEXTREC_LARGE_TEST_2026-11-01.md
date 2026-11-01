# Task: larger accuracy test of Windows AI TextRecognizer, with its settings

## Goal
Find the most accurate way to run `Microsoft.Windows.AI.Imaging.TextRecognizer` on this HP for English letters, digits and Roman numerals. Claude set the sample and scorer. You build and run; Claude scores the held-out pages on the MSI.

## Inputs, in `C:\RE\ocr_large`
- `sample.json`: `digital` pages (`id`, `pdf`, `page` 0-based, `kind`, `split`) and `scan_docs` (`pdf`, `page_count`, `split`). Do not change.
- `pdf\<pdf path>`: the PDFs. `truth\`, `scan_xbrl_truth.json`: answer keys for `split=tune` only. The test keys are not on this machine; do not try to recreate them from the PDFs' text layers.
- `score_large.py`: scorer. Do not change or copy with edits. `python C:\RE\ocr_large\score_large.py ROWS.jsonl tune C:\RE\ocr_large`
- Row format: `{"id": ..., "text": ...}`. Digital pages use the page `id`. Scanned filings use `id` = `<pdf>#<page>`, for every page of each filing.
- Earlier helper: `C:\RE\bench\textrec\` (`Program.cs`, `textrec.csproj`, `pkg\AppxManifest.xml`). It works only as a signed MSIX, launched in the interactive session by a scheduled task with `/IT`. Earlier run: `reality_engine/scripts/hp_ocr_bench.py` and the git log. Remove the package and test certificate when finished.

## Do this, in order
1. Move the helper source into the repo at `reality_engine/tools/textrec/` (source and manifest only, no binaries, no certificate or key). Add word rows: `text`, `MatchConfidence`, box. Add line style and `TextAngle` to the output. Also add a `RecognizedLine` style field to rows when available.
2. Baseline on all tune pages: render with pypdfium2 at 200 DPI and no clean-up. Score it.
3. Test one lever at a time on tune pages, keeping the best each round:
   - DPI: 150, 200, 300, 400. Record whether the engine downsizes large images, if it can be observed.
   - Clean-up: grayscale, contrast stretch, unsharp mask, adaptive black and white, deskew.
   - `ImageScaler` AI upscaling, 2x on 150 and 200 DPI renders. If its access is limited, record the exact error and go on.
   - Overlapping tiles at high DPI, with line de-duplication using boxes.
   - A separate build on Windows App SDK 2.0 experimental with `TextRecognizerOptions`: each `DetectorOutputGeometryMode` value and `EnableWordLevelConfidence`. If it can't run, record the exact error and go on.
   - Rendering hidden text off: confirm with one scanned page that the render is the image, not the text layer.
4. Confidence: on the best setting, tabulate for number tokens on tune digital pages the share wrong at confidence bands 0-0.5, 0.5-0.67, 0.67-0.8, 0.8-0.9, 0.9-0.95, 0.95-0.99, 0.99-1. Report what share of tokens each cutoff would send for checking.
5. Flag-only checks, written to separate fields and never changing `text`: letters inside numeric tokens (`3L`, `O5`), and column totals that do not add up when a table's lines parse cleanly. Report on tune pages how many true errors each catches and how many false alarms.
6. Freeze: choose at most 2 settings from tune scores alone, plus the baseline. Give the reason for each. Record pages per minute for each.
7. Run those settings once on every `test` digital page and every page of every `test` scanned filing. Write `C:\RE\ocr_large\rows\<setting>\test.jsonl`, with confidence rows in a sibling `test_words.jsonl`. Do not rerun with different settings after the test run, and do not attempt to score it.

## Limits
Use only one NPU process at a time. HP free memory stays at or above 3 GB. Shivam may be using this laptop: keep CPU rendering to 4 processes. No paid models, no model vision, and no raw data other than this folder. Do not use `Manual Dumps`. Do not push.

## Acceptance checks
- Tune table: scores for every lever, with pages per minute and exact errors for anything blocked.
- Test rows exist for all test pages at each frozen setting, with no missing IDs and errors counted.
- MSIX and certificate removed; state it. Repo holds source only.

## Docs
Write `tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md` with method, levers, frozen settings and how to rebuild the signed package. Name each changed code file in that doc. No docs, no merge.

Test command(s): python -m pytest reality_engine/tests -q -k ocr

End with `Docs updated:`.
