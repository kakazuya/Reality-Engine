# Task — test Snapdragon-specific OCR engines on the HP NPU

## Goal
Our current HP pipeline is RapidOCR's ONNX models run on the NPU through `onnxruntime-qnn`, with `pypdfium2` for rendering and hand-written numpy post-processing (`reality_engine/scripts/hp_ocr_check.py`). It scores 66.7% mean against text-layer truth on 20 pages, and 93.5–95.4% on clean letters. Find out whether an engine built for this hardware does better. Read `tasks/efficiency/HP_ACCEL_BENCH_2026-10-31.md` §10 first.

## Engines to test
1. **Windows App SDK `TextRecognizer`** (the Windows AI text recognition API; `IsAvailable` / `MakeAvailableAsync`). Find out if it runs on this Snapdragon X X1-26-100 from an unpackaged app; a small C# or Python/WinRT wrapper is fine. Confirm it uses the NPU.
2. **Qualcomm AI Hub EasyOCR** (`qualcomm/EasyOCR`, detector and recogniser, ONNX or QNN_DLC). It is listed for Snapdragon X Elite and X Plus; confirm it runs here. Check its licence and report it.
3. **Baseline:** the current pipeline, on the same pages.
4. Only if quick: proper `pyclipper` and `opencv` post-processing with the current models (an ARM Python version or a build that has them), to separate model quality from our numpy code.

## Test set
The same 20 text-layer pages and 20 scanned pages as `hp_ocr_check.py`. Measure accuracy with case-insensitive, whitespace-normalised, order-insensitive matching as well as the plain similarity, because reading order on tables deflates the score. Report separately: letters, tables, and rotated pages. Also numbers: exact-number recall, since figures matter most in filings.

## Fence (full-access run; the brief is the limit)
On the MSI write only your worktree. On the HP write only `C:\RE` and user-level installs. Nothing from `Manual Dumps/` goes to the HP. No firewall, antivirus, account or power changes. Never print a key. Downloading model files from Hugging Face or Qualcomm is allowed; no paid services or sign-ups: if one needs an account, report it and skip.

## Acceptance checks
- A table per engine: pages/min, accuracy overall and by page type, number recall, and confirmation of NPU use.
- One recommendation for the 1,073 scanned files, with the expected hours and accuracy. Do not run all 1,073 files.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_hp_run.py -q
```

## Output
Append §11 to `tasks/efficiency/HP_ACCEL_BENCH_2026-10-31.md`.
