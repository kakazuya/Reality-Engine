# T-242 brief: ocr_fill - adaptive concurrency per route + Zen model rotation

Goal: ocr_fill reads each free route at the highest concurrency below refusal (AIMD) and rotates Zen between two free vision models by measured speed.
Files: reality_engine/scripts/ocr_fill.py, reality_engine/tests/test_ocr_fill.py, docs/DEVELOPER_GUIDE.md
Accept: python -m pytest reality_engine/tests/test_ocr_fill.py -q passes; --help shows --start-workers/--max-workers
Evidence: see Evidence section below
Stop if: per-route slots need a rewrite of run() over ~200 lines, or any test needs a live model call
Budget: ~60 tool calls
Ticket: T-242

Shivam (26 Nov 01:00): read as fast as each endpoint allows, one notch below refusal, and rotate Zen models: the best reader may be slow while the 2nd best is fast at ~95% quality.

## Evidence
- `reality_engine/scripts/ocr_fill.py` (552 lines). Routes: `FREE_ROUTES` line 61 (kilo = HTTP nemotron VL, zen = `opencode run --standalone` nemotron VL). Workers spread round-robin over routes, fixed count (`run()` line 497). `METHOD = "ocr_nemotron_vl"` line 51 for every row. 429 handling: per-worker backoff only (`_worker` line 394).
- Live run (00:52, 12 workers = 6 kilo + 6 zen): kilo 848 ok, 0 err, ~4-20 s/page; zen 30 ok, ~85-150 s/page; zero 429s. So neither route is at its limit, and zen is slow.
- Bake-off `C:/RealityEngine/t242/ocr_bakeoff/results.md`: `opencode/nemotron-3.5-super-vl-free` recall 94% / precision 98%, 58 s; `opencode/deepseek-v4.1-flash-free` recall 92% / precision 98%, 41 s (98% of the winner's recall). Both cost 0. Paid on Zen (never call): `opencode/mimo-v2.6-flash-free`, `opencode/hy4-flash-free`.

## Steps
1. Zen route gets an ordered model list (quality order): `nemotron-3.5-super-vl-free` (method `ocr_nemotron_vl`), `deepseek-v4.1-flash-free` (method `ocr_deepseek_flash_vl`). Keep the free allow-list guard: an id not in the list cannot be called; mimo/hy4-flash ids are refused explicitly (test it). Kilo keeps its one model.
2. Model choice per Zen call: the model with the lowest EWMA seconds/page (alpha 0.3) among models not cooling down; unmeasured models are tried first in quality order; every 8th Zen call goes to the least-recently-used model so speeds stay measured. A Throttled answer cools that model only (start 30 s, doubling to 600 s) and the page goes back to the queue.
3. Adaptive concurrency per route (AIMD), so each route sits one notch below refusal: route limit L starts at `--start-workers` (default 6), max `--max-workers` (default 24). Threads = sum of max over routes; a worker takes a route slot before a call. After 20 successes in a row with no throttle on that route: L += 1. On Throttled: L = max(1, floor(L * 0.7)). Print a line `limit <route> <old>-><new> (<reason>)` to stdout (it goes to run.log) on every change.
4. Rows: `method` = the model's method. `--resume` and the "never overwrite another method" rule treat a page held by ANY ocr_fill model method as already read (do not re-read a deepseek page with nemotron).
5. Log line: `ok   <route>:<short model> <symbol> p<page> <s>s <chars> chars` (route and model joined by a colon, no space). Same for err lines. Add `models` and `limits` to the final JSON summary (per model: ok, err, throttled, median s).
6. Tests: extend `reality_engine/tests/test_ocr_fill.py` (monkeypatch `ask`; no live calls): AIMD increase after 20 ok and decrease on throttle; faster model chosen after measurement; exploration every 8th call; cooled model skipped; paid ids refused; resume treats the other model's method as held; existing tests still pass.
7. Docs: update the ocr_fill section of `docs/DEVELOPER_GUIDE.md` (routes, models, AIMD, flags) and the module docstring.

## Limits / pitfalls
- Free models only. No live model call in tests. Optional live smoke: at most 4 pages, `--limit 4 --out-dir` a scratch dir, never the live `C:/RealityEngine/t242/ocr_bulk`.
- Do not touch the running OCR job (pid 13276) or its folder. Do not kill any process by name.
- Run tests with pytest per file: `python -m pytest reality_engine/tests/test_ocr_fill.py -q`.
- Thread safety: limits and EWMA under one lock.

## Accept
Tests pass; `python -m reality_engine.scripts.ocr_fill --help` shows `--start-workers/--max-workers`; docstring + DEVELOPER_GUIDE updated; commit message names T-242.
Budget: ~60 tool calls. Stop and report if the run() structure makes per-route slots impossible without a rewrite over ~200 lines.
