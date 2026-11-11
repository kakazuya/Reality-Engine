# T-188 progress — local llama.cpp OCR readers (PaddleOCR-VL-1.6, GLM-OCR, LightOnOCR-3-0.8B)

- `2026-11-11 19:40` Done: context pack read; GPU confirmed (GTX 1050 Ti, 4 GB, driver 582.78, cc 6.1);
  GGUF sources chosen — `PaddlePaddle/PaddleOCR-VL-1.6-GGUF` (official, Q8_0 + mmproj),
  `ggml-org/GLM-OCR-GGUF` (Q8_0 + mmproj Q8_0), `prithivMLmods/LightOnOCR-3-0.8B-GGUF` (Q8_0 + mmproj q8_0).
  Wrote `reality_engine/v2/local_reader.py` + `reality_engine/tests/test_v2_local_reader.py` (tests pass).
  Next: unzip llama.cpp b12284 CUDA builds (13.5 first per Shivam, then 12.4), prove GPU, tune on dev pages.
  Blocker note: GitHub release CDN throttles to ~90 KB/s per connection here, so downloads use 12-32 parallel
  range connections (~1.2 MB/s); HF is ~5.5 MB/s.
- `2026-11-11 22:10` Done: GPU proven (CUDA 12.4 build; 13.5 dies on sm_61), b12284 only ships 13.5/12.4 Windows CUDA.
  All three models run hidden under llama-server; converter handles OTSL (Paddle), HTML colspan/rowspan (GLM),
  markdown + HTML (LightOn). v1 frozen2 runs: paddlevl 1,367 rows / 25 of 30 pages; glmocr 165 rows (bug: it ran the
  card's **Text Recognition:** prompt, which returns plain lines, so the grid is lost); lighton still running.
  Eagle review in: fix GLM to `Table Recognition:`, keep blank cells and ' > ' header joins, convert chart output,
  compare dev cell counts with Dots, then re-run frozen2 into run_local_glmocr_v2 / run_local_paddlevl_v2.
  Next: LightOn finishes, dev checks (p018/p020 chart pages for Paddle, p016/p046 for GLM), v2 runs, docs.
- `2026-11-11 23:15` Done: all runs finished, no llama-server left running (VRAM back to 587 MiB). Frozen2:
  `run_local_paddlevl_v2` 1,367 rows/25 pages, `run_local_glmocr_v2` 1,039/26 (Text Recognition in v1 gave 220/8),
  `run_local_lighton` 1,014/19; Dots 1,393/27. 7 tests pass, basedpyright 0. Docs: V2_SCHEMA_CONTRACT s14,
  machines/MSI_LAPTOP.md, tasks/STATE.md, D:/RealityEngine/models/MODELS.md. Open: chart panels unread (no layout
  crop in llama.cpp), GLM reads one column group of a wide table, Paddle degenerates on one prose page.
