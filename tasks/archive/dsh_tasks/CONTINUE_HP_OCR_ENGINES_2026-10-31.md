You are running ON the HP itself (not the MSI). Run commands locally and do not ssh to it. Any 'partial work' in the note below is gone: this is a fresh checkout, so check what is already installed on this machine and start from there.

# CONTINUE: the earlier run was killed mid-task on 31 Oct at about 05:17 IST (supervisor and worker both gone, most likely when the session that owned it closed)

This worktree already holds YOUR partial work from that run, uncommitted. Before anything else:
1. Read `.tmp/PROGRESS_NOTES.md` (or root `PROGRESS_NOTES.md`) if present, then `git status` and `git diff --stat`.
2. Keep what is correct. Re-run only the steps that did not finish. Resume long jobs from existing outputs and `.tmp` DBs instead of starting over.
3. Check for leftovers of the killed run before starting anything long: stray python processes on the MSI, and any HP processes this task started (the HP is `zen7s@192.168.1.42`; another worker's job `hp-20261031T051124-3e6065` is running there, never touch it).
4. Finish the original brief below and give its full report. Do not commit: the reviewer commits this worktree after review.
5. RAM is tight on the MSI: at most one heavy process at a time. If `REALITY_DATA_ROOT` is unset, read data from `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data`, read-only.

---
# Task — test Snapdragon-specific OCR engines on the HP NPU

## Goal
Our current HP pipeline is RapidOCR's ONNX models run on the NPU through `onnxruntime-qnn`, with `pypdfium2` for rendering and hand-written numpy post-processing (`reality_engine/scripts/hp_ocr_check.py`). It scores 66.7% mean against text-layer truth on 20 pages, and 93.5–95.4% on clean letters. Find out whether an engine built for this hardware does better. Read `machines/HP_ACCEL_BENCH_2026-10-31.md` §10 first.

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
Append §11 to `machines/HP_ACCEL_BENCH_2026-10-31.md`.


