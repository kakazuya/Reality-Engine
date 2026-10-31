# Local OCR pilot — handoff (2026-10-24, stopped on Shivam's call)

Status: **setup + partial measurements only. No verdict.** The 200-page sample is fetched and rendered, RapidOCR is
measured on 136 pages, and the free reader (`beam-free`) is smoke-tested. PaddleOCR-VL was **not installed** (the
579 MB cu126 wheel download did not finish), so the GTX 1050 Ti GPU question is only partly answered.

## What was set up, and where

| Thing | Path | Notes |
|---|---|---|
| Python 3.12.15 (uv-managed) | `.tools/pythons/cpython-3.12.15-windows-x86_64-none/` | base box only has 3.14, too new for Paddle/RapidOCR |
| uv 0.13.5 | `.tools/uv/uv-0.13.5.data/scripts/uv.exe` | manual wheel unpack (pip's temp ACL is broken under the sandbox) |
| OCR venv | `.venv-ocr/` | `rapidocr 3.10.0`, `onnxruntime-directml 1.24.4`, `pymupdf 2.0`; **no Paddle yet** |
| Fetched decks | `tasks/research/local_ocr_pilot/work/pdfs/` | 200 PDFs, 1.0 GB, sha256-verified |
| Rendered pages | `tasks/research/local_ocr_pilot/work/pages/` | 200 PNGs at **1600 px longest side** (deck pipeline: `zoom = 1600/max(w,h)`, JPEG q85; PNG used here) |
| OCR output | `work/ocr/rapidocr_cpu.jsonl` (+ `.md` per page) | 140/200 pages done when stopped |
| Sample definition | `work/sample.json`, `work/sample.csv` (copy in task root) | seed 20261024, stratified year × page-type proxy |
| rclone config copy | `.tools/rclone.conf` | **contains OAuth token — gitignored, do not commit** |
| Partial metrics | `partial_metrics.json` (task root) | OCR-text-alone recall + RapidOCR timing |

Sampling: 200 Haiku-final pages from `deck_figures.db` (`final_model='claude-haiku-5-5'`, `status='ok'`, `n_facts>=1`),
stratified by year (2021:70, 2022–2026:26 each) and a page-type proxy: `table` = ≥15 facts, `chart` = 6–14, `kpi` = 1–5.
Eight sampled decks were absent from `gdrive:InfoDiffusion_archive`; they were replaced from the same strata
(`topup_pages.py`), so the rendered set is 200 pages from 200 decks.

## GPU finding (GTX 1050 Ti, 4 GB, Pascal sm_61)

Hardware/driver: `nvidia-smi` reports GTX 1050 Ti, 4096 MiB, **1114 MiB already used at idle** (~2.9 GB free), driver
582.78, CUDA 13.0; compute capability is **sm_61**.

- **RapidOCR + ONNX Runtime DirectML worked** on the GPU (no error, 3 pages): 3.81–3.92 s/page. CPU was
  3.07–3.77 s/page on the same pages, i.e. **no measurable DirectML speed-up**. RapidOCR lazy-loads its sessions; the
  active provider was not confirmed before the stop (open item — inspect `engine.text_det.session`).
- **PaddleOCR-VL on GPU was not tested.** PaddlePaddle-GPU 3.3.1 (cu126, Windows cp312) exists (579 MB), but the
  download ran at 0.6–0.75 MB/s and did not complete in the session; the 0-byte partial wheel was left in
  `.tools/wheels/` and is not installed. No empirical sm_61 result exists yet.
- **Expected constraint (reasoned, not measured):** PaddleOCR-VL is ~0.9B params; fp32 weights alone are ~3.6 GB, more
  than the ~2.9 GB free, so it can only fit as **fp16** (weights ~1.8 GB) plus the PP-DocLayoutV2 layout model and
  activations. Pascal has severely limited native FP16 throughput (1:64 vs FP32), so even if fp16 fits it may be
  **slower than CPU**. PaddlePaddle 3.3.1's compiled SM list for this wheel is also unverified.
- Verdict on GPU viability: **unresolved**. The cheap test is one GPU inference with `precision="fp16"`; if Paddle
  rejects sm_61 or OOMs, the CPU path is the pilot's real arm.

## Partial metrics (140 pages, 4,583 Haiku final facts; OCR text alone)

Upper bound = does the Haiku value string appear anywhere in the OCR text (unit-normalised, ±0.5%):

| Year / type | hit / n | recall |
|---|---:|---:|
| 2021 chart | 221 / 233 | 0.948 |
| 2021 kpi | 74 / 76 | 0.974 |
| 2021 table | 1346 / 1373 | 0.980 |
| 2022 chart | 171 / 176 | 0.972 |
| 2022 kpi | 109 / 132 | 0.826 |
| 2022 table | 485 / 565 | 0.858 |
| 2023 chart | 190 / 196 | 0.969 |
| 2023 kpi | 93 / 140 | 0.664 |
| 2023 table | 644 / 724 | 0.890 |
| 2024 chart | 214 / 250 | 0.856 |
| 2024 kpi | 106 / 114 | 0.930 |
| 2024 table | 594 / 604 | 0.983 |
| **all** | **4247 / 4583** | **0.927** |

RapidOCR CPU: mean 4.69 s/page, median 4.03 s/page (140 pages). DirectML: 3 pages, ~3.85 s/page.
Reader smoke test only: `beam-free` on one table page's OCR text returned **84 parsed facts in 14.2 s** (table rows
preserved, e.g. `Shareholder's Equity | Mar 31, 2015 | 15,886 | INR mn`). No full reader run, no strict/loose recall,
no precision spot-check.

Projection (rough, 136.1k pages = 73.5k AR + 62.6k decks): single-stream OCR+reader at 4.0 s + 14 s ≈ 18 s/page →
**~680 h**. With one OCR process and 6 parallel reader calls ≈ max(4 s, 14/6 s) ≈ 4 s/page → **~150 h**. Reader
throughput is the bottleneck; OCR alone at 4 s/page is ~151 h for 136.1k pages.

## Open problems / exact next steps

1. **Finish the Paddle install.** The wheel is at
   `https://paddle-whl.cdn.bcebos.com/stable/cu126/paddlepaddle-gpu/paddlepaddle_gpu-3.3.1-cp312-cp312-win_amd64.whl`.
   Resume the download (requests supports Range; `curl -C -` may be faster) and install:
   ```
   .tools\uv\uv-0.13.5.data\scripts\uv.exe pip install --python .venv-ocr\Scripts\python.exe <wheel> --no-deps
   .tools\uv\uv-0.13.5.data\scripts\uv.exe pip install --python .venv-ocr\Scripts\python.exe "paddleocr[doc-parser]==3.7.0"
   ```
   (install `paddleocr` without letting it pull the CPU `paddlepaddle`; re-install the GPU wheel afterwards if it does).
2. **Probe the GPU exactly:**
   ```
   .venv-ocr\Scripts\python.exe -c "import paddle; paddle.utils.run_check(); print(paddle.device.cuda.get_device_capability())"
   ```
   then one page: `PaddleOCRVL(precision='fp16').predict(png)`; record OOM vs unsupported-arch vs success. Also confirm
   RapidOCR's provider (`engine.text_det.session`).
3. **PaddleOCR-VL model weights** are ~2.1 GB (`PaddlePaddle/PaddleOCR-VL`, HF/ModelScope) and were not downloaded.
   Pre-download before the next timed run.
4. **Run the reader on both arms** (400 calls, free):
   ```
   .venv-ocr\Scripts\python.exe tasks\research\local_ocr_pilot\scripts\run_rapidocr.py --device cpu
   .venv-ocr\Scripts\python.exe tasks\research\local_ocr_pilot\scripts\run_reader.py --ocr rapidocr_cpu --workers 6
   ```
   Key 2 is `OPENCODE_GO_API_KEY_2`; key 1 is the fallback. Kilo `beam-free` is **paid now** (HTTP 402), so it is not a
   fallback.
5. **Scoring is not written yet.** `partial_metrics.json` used an inline value-only matcher; a `score.py` still needs
   strict (value+fuzzy metric+period) / loose (value) recall, per year/type, and the 20-page manual wrong-value check.
6. PaddleOCR-VL's output must be mapped from its Markdown/tables to the same `metric | period | number | unit` schema;
   the reader prompt for OCR text is in `run_reader.py` (`PROMPT`/`RULES`, adapted from `extract_deck_figures.py`).

## Scripts

- `scripts/sample_pages.py` — stratified 200-page draw, deck path mapping, `work/decks.txt`.
- `scripts/topup_pages.py` — replace pages whose deck is missing from gdrive.
- `scripts/prepare_pages.py` — verify sha256, render 1600 px PNG, text layer, layout features, `work/pages.json`.
- `scripts/run_rapidocr.py` — RapidOCR CPU/DirectML arm, JSONL + Markdown per page.
- `scripts/run_reader.py` — OCR text → `beam-free` (Go key 2/1), same fact schema, JSONL.

No paid calls were made. No model weights or venvs are committed; `work/`, `.venv-ocr/`, `.tools/`, `.tmp/` are ignored.
