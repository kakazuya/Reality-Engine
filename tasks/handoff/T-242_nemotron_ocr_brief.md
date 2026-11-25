Goal: an OCR fill step that reads image-only deck pages with the free Nemotron 3.5 Super VL and writes their text into each store's `<store>_ocr.db`, so the existing reader (routes `needs_ocr`, T-238) picks them up. Shivam 25 Nov 22:10: "use nemotron 3.5 Super VL then for second reader pass". T-242.
Evidence:
- Bake-off C:/RealityEngine/t242/ocr_bakeoff/results.md: Nemotron 3.5 Super VL recall 49/52, precision 55/56, 58 s/page; same model on Kilo (`nvidia/nemotron-3.5-super-vl:free`, MODELS entry in reality_engine/scripts/extract_deck_figures.py ~line 148, KILO_API_KEY) and on OpenCode Zen (`nemotron-3.5-super-vl-free`, base https://opencode.ai/zen/v1). Use both routes, each with its own limiter, to double throughput.
- Pages: universe routes.csv (C:/RealityEngine/tg_build/universe_fy27/c*/routes.csv), deck rows with route `needs_ocr` and reason starting "text layer none": 1,363 pages.
- `_ocr.db` schema: reality_engine/pilot3/ocr.py line 35 (table `ocr_page`: symbol, doc_key, page, doc_type, known_at, text, words_json, ocr_conf, n_boxes, dpi, seconds, method). Readers: reality_engine/v2/page_words.py `ocr_words` (line 234, method priority dict) and observations.py `_ocr_pages` (~line 7040), `ocr_page_text` (6217).
- Raw PDFs are on Drive: fetch through reality_engine/raw_store.py, delete the local copy after.
Steps:
1. Script `reality_engine/scripts/ocr_fill.py`: select the pages above (`--limit`, `--seed`, `--symbols`), render at 150 dpi (PyMuPDF), call the model with the prompt "Transcribe all text on this slide exactly, in reading order. Keep every number with its label, unit and column or period header. Output plain text only.", write one `ocr_page` row per page with method `ocr_nemotron_vl`, words_json as one pseudo-word per line (x/y from line order, so `ocr_words` can read it; say how in the docstring), `--resume` skipping pages already held. Two routes round-robin with adaptive back-off on 429; record route, seconds and errors per page in a JSONL log.
2. Add `ocr_nemotron_vl` to the method priority in page_words.py, below `ocr_textrec`/`ocr_rapid`.
3. Free-only guard: refuse any model id not in a FREE list in the script; never print keys.
4. pytest tests for selection, the row written, resume, and the priority (no network: monkeypatch the model call).
5. The script takes `--out-dir`: when given, rows go to `<out-dir>/<store stem>_ocr.db` instead of beside the live store (so a pilot never feeds the live hy4 loop before its grade). Pilot run ONLY: `--limit 40 --seed 1125 --out-dir .tmp/ocr_pilot`. Report per-page seconds, errors, route mix, how many pages carry >= 4 figures, and 10 sample outputs.
6. DEVELOPER_GUIDE entry.
Files: reality_engine/scripts/ocr_fill.py, reality_engine/v2/page_words.py, reality_engine/tests/test_ocr_fill.py, docs/DEVELOPER_GUIDE.md.
Accept: python -m pytest -q reality_engine/tests/test_ocr_fill.py reality_engine/tests/test_page_words.py passes (pytest, not unittest); pilot of 40 pages written under .tmp/ocr_pilot with the log; nothing written beside the live stores.
Stop if: either route reports a non-zero cost or a paid model, or the pilot errors on more than 10 of 40 pages: report and stop. No bulk run beyond 40 pages: the bulk waits for a 60-row grade.
Pitfalls: never kill processes by name (kill your own PIDs only); never scan the disk; never write under C:/RealityEngine or D:/RealityEngine (raw_store's own cache excepted); regexes via the file editor.
Budget: 75 minutes.
Ticket: T-242
