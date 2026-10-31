# Task — HP laptop: job runner, GPU/NPU test for OCR, network speed

## Goal
Shivam gave a second laptop as extra compute all weekend and wants its GPU tested for OCR. Build the job runner, measure the accelerators and the network, and recommend what runs where.

## The machine
HP OmniBook 5, Windows 11 ARM64, Snapdragon X X1-26-100, 8 cores, 16 GB, Adreno X1-45 GPU, Hexagon NPU. `ssh zen7s@100.78.87.112` (key auth, default shell cmd.exe, so scp a `.ps1`/`.py` and run it; inline quoting breaks). LAN 192.168.1.42; this laptop is 192.168.1.44. Python: `%LOCALAPPDATA%\Programs\Python\Python314-arm64\python.exe`. Code snapshot in `C:\RE\repo`. Raw PDFs are being copied to `C:\RE\raw\pilot60_history` by another process: **do not touch that copy**, and read only files already complete.

## Fence (full-access run; the brief is the limit)
- On this laptop write only your worktree. On the HP write only `C:\RE` and its Python packages.
- Never copy API keys, `.env` files, or anything under `Manual Dumps/` to the HP.
- No firewall, antivirus, account or power-setting changes on either machine.
- No paid services.

## Work
1. **Runner.** `reality_engine/scripts/hp_run.py`: `sync` (code snapshot via `git archive HEAD`, because this repo is shallow), `copy-db <file>`, `run <name> -- <cmd>` (detached with log and exit-code files), `status`, `fetch <path>`. **Prove a job survives the SSH session closing**: plain `start` may not; if it dies, try `schtasks` or `Start-Process` variants and record which works. Add tests that do not need the network.
2. **Accelerators.** There is no CUDA on Qualcomm; state that plainly after confirming. `onnxruntime-qnn` 2.7.0 installs (win_arm64). `onnxruntime-directml` and `torch` have no wheel for this Python; check other routes briefly (other Python versions, x64 Python under emulation).
   - Run the RapidOCR det and rec ONNX models through QNN `QnnHtp.dll` (NPU) and `QnnGpu.dll` (GPU) vs CPU. Confirm the nodes really run on the accelerator (partition or profile output), since silent CPU fallback is the trap here. Models may need quantising or fixed shapes: report what was needed.
   - End-to-end OCR is blocked on native Python 3.14 ARM because `opencv-python-headless` and `pyclipper` have no wheels. Try: an ARM Python version that has them, x64 Python under emulation, a small numpy replacement for those two steps, and Windows' built-in OCR.
3. **OCR comparison.** Use 30 real pages from the 1,073 files with `is_scanned_guess=1` in `reality_engine/data/pilot/pilot60_history_manifest.db`. Same pages on: HP CPU, HP NPU and GPU where they work, MSI CPU, MSI GTX 1050 Ti. Report pages/min and text accuracy (hand-check 5 pages against each other). Install OCR packages on the MSI only in your worktree's `.tmp` venv.
4. **Numerics.** Does any GPU route beat HP CPU for the §F.8 matrix workloads? Short answer is enough.
5. **Network.** After the raw copy ends (19,978 files on the HP), measure with a memory-to-null transfer: SSH over Tailscale vs SSH to the LAN IP vs raw TCP on the LAN if a port is reachable. Report MB/s and where the limit is. Both laptops are on Wi-Fi, 5 GHz; link rates are 351 and 780 Mbps.

## Output
`tasks/efficiency/HP_ACCEL_BENCH_2026-10-31.md`: tables, and one recommendation: which engine and machine should OCR the 1,073 scanned files, and the estimated hours.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_hp_run.py -q
```
