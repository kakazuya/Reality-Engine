# HP OmniBook 5 — capacity, OCR accelerators, network (2026-10-31)

**Answers first**

- **Capacity: yes, good enough. 8 simulated workers ran with 8.56 GB of commit left and every
  task under 1.45× the 1-worker time; no step came near the 2× or 1.5 GB stop rules. Recommend
  6–8 concurrent dsh workers, and heavy jobs (OCR, benches) can run beside them — the NPU OCR
  run leaves the CPU mostly idle.**
- **OCR: use the NPU (Hexagon HTP). 159.7 pages/min vs 15.1 on the CPU and 86.1 on the Adreno
  GPU; NPU text agrees with CPU text at 0.971 mean character similarity, the GPU one at 0.611.**
  The 1,073 scanned files are ~13,300 pages → **\~1.4 h on the NPU** (2.6 h GPU, 14.7 h CPU).
- **dsh runs on the HP only under real Node, not under Bun** (Bun 1.4.4 is native but boots dsh
  into `node-addon-require-builtin unsupported`; Node 24.22.2 win-arm64 runs it and made a real
  Go call).
- **Network is ~10 MB/s (80 Mbit/s)** to the HP, LAN or Tailscale; three parallel streams
  aggregate 11.5 MB/s, so the limit is the Wi-Fi link, not SSH. A raw TCP port is not reachable
  (Windows Firewall) and changing that is outside the fence.

---

## 1. Capacity — how many dsh workers the HP can host

Machine: Snapdragon X X1-26-100 (8 cores), 16.36 GB RAM, Windows 11 ARM64. Idle free RAM
before each step was 7.0–7.7 GB (**half the box was already in use** by the desktop, the raw-copy
job and the OCR runs), commit left 8.5–9.4 GB.

Method: each simulated worker holds what a real dsh worker holds on this box — one
`basedpyright-langserver` child (the code-intel LSP, 88 MB resident after initialize) and one
Python process holding the `reality-data` server modules plus a read-only SQLite handle — and then
runs the typical three tasks in parallel across all workers: `pytest` on a repo test module, a
grep over the 128 MB checkout, and a read-only query on the copied pilot manifest DB. Timings are
the max across workers; memory is the summed RSS of every worker process tree.

| workers | free RAM GB | commit left GB | CPU % | MB/worker | pytest | grep | sqlite |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 7.65 | 9.37 | 14.6 | 155 | 1.00× (0.76 s) | 1.00× (0.11 s) | 1.00× (0.07 s) |
| 2 | 7.69 | 9.28 | 23.1 | 155 | 1.04× | 1.09× | 1.00× |
| 4 | 7.34 | 8.93 | 26.6 | 155 | 1.14× | 1.18× | 1.43× |
| 6 | 7.29 | 8.84 | 29.1 | 155 | 1.20× | 1.27× | 2.00× (0.14 s, noise) |
| 8 | 7.03 | 8.56 | 16.8 | 155 | 1.21× | 1.45× | 1.43× |

- **No step reached the stop rules** (task >2× or commit <1.5 GB), so 8 is a measured-safe
  number, not the ceiling. At 155 MB/worker the memory ceiling is ~35 workers, but CPU (8 cores)
  and the 2× rule would bite long before that. **Operating point: 6–8.**
- **A real dsh runtime adds node on top**: one real `dsh` call measured 208 MB resident, 311 MB
  peak (3 children) — so a real worker is ≈ **365 MB** (155 + 210), not 155. Eight real workers
  ≈ 2.9 GB, still well inside 8.5 GB of commit left.
- **MSI reference given by Shivam: ~1.15 GB/worker (760 MB node + 390 MB python, 4 workers).**
  The HP workers are much lighter here because the measurement holds the two children a worker
  spawns, not the whole dsh bundle; a production dsh worker will sit between 0.4 and 1.15 GB.
  Treat **8 workers** as the measured answer and 12–14 as the memory-feasible maximum.
- **Heavy jobs beside workers: yes.** The NPU OCR run (159.7 pages/min) is one process and leaves
  the CPU mostly idle; the capacity run itself ran beside the raw copy (19,978 files) and the OCR
  runs without hitting the stop rules.

**What was simulated, and the one real gap:** the two MCP servers could not be started as servers
on this box — `mcp` imports `cryptography`, and there is **no cp314 win_arm64 wheel** (pip falls
back to building from Rust source, which fails). The worker therefore holds the same children the
MCP servers would start (`basedpyright-langserver`, and the `reality-data` modules + DB handle)
without the ~20 MB MCP wrapper. Fix: a Python 3.13 ARM64 install for the MCP servers (3.13 has
`cryptography` wheels); not installed in this run (python.org downloads stalled from the HP).

## 2. Job runner — `reality_engine/scripts/hp_run.py`

`sync` (`git archive HEAD` → tar over ssh → fresh `C:\RE\repo`, 128.7 MiB this run), `copy-db`,
`run <name> -- <cmd>` (detached, `job.log` + `exit.txt`), `status`, `fetch`. Remote shell is
cmd.exe, so every PowerShell snippet is base64 `-EncodedCommand`-ed and every job body is written
once as `run.cmd`.

**Does a job survive the SSH session closing?** Measured with a 90 s ticking job, started and then
the SSH session closed immediately:

| launch | survives | notes |
|---|---|---|
| `Start-Process` (`--method start`) | **no** | process dies with the session; no ticks written |
| Task Scheduler, `/RU SYSTEM` (`--method schtasks`) | **yes** | 90/90 ticks; runs with the SYSTEM profile env, so `%LOCALAPPDATA%` is the system profile — job commands must use absolute paths |
| WMI `Win32_Process Create` (`--method wmi`, **default**) | **yes** | 90/90 ticks; runs as the ssh user with the user profile env and records `pid.txt` |

All jobs in this report ran through `run --method wmi`. Tests: `python -m pytest
reality_engine/tests/test_hp_run.py -q` → **10 passed** (no network; fake ssh/scp).

## 3. Accelerators — no CUDA; QNN HTP (NPU) and QNN GPU both work

- **There is no CUDA on Qualcomm and no CuPy/torch wheel for ARM64 Windows** — stated after
  confirming: `onnxruntime.get_available_providers()` on the stock runtime is
  `[AzureExecutionProvider, CPUExecutionProvider]`; there is no CUDA toolkit, no `cupy`, and no
  `torch` for cp314 win_arm64.
- `onnxruntime-qnn` 2.7.0 installs (win_arm64) and its EP plugin registers with
  `onnxruntime.register_execution_provider_library("qnn", …/onnxruntime_providers_qnn.dll)`;
  `QnnHtp.dll` (NPU) and `QnnGpu.dll` (GPU) ship beside it and need `os.add_dll_directory`.
- **What was needed:** only **fixed input shapes**. The shipped RapidOCR graphs have dynamic
  H/W (det) and dynamic width (rec); with those, QNN assigns **zero nodes** and everything runs
  on the CPU — the silent-fallback trap. Writing the input dims as constants
  (`det 960×960`, `rec 3×48×320`) puts **100% of the graph on QNN**. **No quantisation was
  needed** (QNN 2.7 runs the float graphs, fp16 on HTP: det max diff 3.7e-04, rec 2.9e-02 vs CPU).
- **Proof the work ran on the accelerator:** every QNN session was created with
  `session.disable_cpu_ep_fallback = 1` — ORT refuses to create a session unless every node is
  assigned to QNN — and it succeeded for all four models. The ORT profile of the same runs shows
  a single `qnn` partition and **zero CPU kernel events** (profile `{'qnn': 6}` per 6 runs).
  The GPU backend shows the same, with fp32 output (diff 1.35e-07 on det).

Model-level timings (median of 5, single call):

| model | CPU | NPU (QnnHtp) | GPU (QnnGpu) |
|---|---:|---:|---:|
| det 640×640 | 28.2 ms | 7.5 ms (3.8×) | 17.0 ms (1.7×) |
| det 960×960 | 229.6 ms | 22.5 ms (10.2×) | 36.5 ms (6.3×) |
| rec 48×320 | 49.1 ms | 3.0 ms (16.3×) | 7.4 ms (6.6×) |
| rec 48×960 | 115.8 ms | 8.8 ms (13.2×) | 19.4 ms (6.0×) |

## 4. OCR on 30 real scanned pages

Pages: 30 of the 1,073 `is_scanned_guess=1` documents in `pilot60_history_manifest.db`, one
middle page per PDF, selected every 23rd of the 692 files already complete on the HP (the raw copy
was still running; nothing incomplete was read). Pipeline: PDF → pypdfium2 render → det → boxes →
rec, one process, batch 1.

**End-to-end RapidOCR is blocked on native Python 3.14 ARM:** `opencv-python-headless` and
`pyclipper` have no wheels (OpenCV publishes no win_arm64 wheels at all; pyclipper is source-only).
The bench therefore uses a numpy-only replacement for those two steps (DB mask → connected
components → boxes, CTC decode from the model's own character metadata), identical on every
device. Windows' built-in OCR and an x64-emulated Python were **not** tested — time went to the
QNN work and capacity.

| device | 30 pages | pages/min | vs CPU | text agreement with CPU (mean char similarity) |
|---|---:|---:|---:|---:|
| HP CPU (8 cores) | 119.5 s | 15.1 | 1.0× | — |
| **HP NPU (QnnHtp)** | **11.3 s** | **159.7** | **10.6×** | **0.971** (19/30 pages ≥0.97) |
| HP GPU (QnnGpu) | 20.9 s | 86.1 | 5.7× | 0.611 (the rec logits shift: fp32-diff 0.18, so text degrades) |

Hand check (5 pages, first lines eyeballed): pages 00, 01, 04, 10, 27 read the same on CPU and
NPU ("Global Tyre Industry | Tire Production | …" vs the same line, one glyph apart). The GPU run
loses words on the same pages (e.g. page 04: 1,194 chars vs 1,376 on CPU). **Accuracy verdict:
NPU ≈ CPU > GPU.**

## 5. dsh on ARM Windows

- **Bun 1.4.4 installs natively** (`bun.sh/install.ps1`, win-arm64) and `bun add -g
  @deepseek-ai/dsh` installs `0.2.1-rc.5` (555 packages, 49 s).
- **But dsh does not boot on Bun**: `dsh --profile headless` dies with
  `dsh: host preparation failed: node-addon-require-builtin unsupported: Unsupported/no-context
  (required V8 current-context symbols were not found)` in `@deepseek-ai/dsh-app-boot`. The
  native addon needs real Node V8 symbols.
- **It runs under Node 24.22.2 win-arm64** (official ARM64 zip): `node .../dsh/lib/bin.js
  --version` → `0.2.1-rc.5`, `--profile headless --help` boots the profile, and a real
  `deepseek-v4.1-flash` call (max effort, Go account 2, stable `x-opencode-session`) returned in
  **9.2 s / 12.8 s** on two runs, made a shell tool call and answered `42`; events:
  `session/status/thinking/tool_call/tool_result/text/final`. The same session id
  `fb0219dd-4b70-5e7a-b486-81c4b4442f92` on both runs = stable.
- **Tokens used:** the `--json` stream of this dsh build carries no usage block (`usage` fields
  absent from every event), so the exact count has to come from the OpenCode Go ledger. Two
  short calls were made (the second re-run to dump events), 1,024- and 512-token caps, roughly
  a few hundred tokens each — the only model use in this run.
- **The harness needs a shim on ARM:** `run_deepseek_harness.py` hardcodes
  `~/.bun/bin/dsh.exe` (the Bun launcher). On the HP that binary must be replaced by a wrapper
  that execs `node …/dsh/lib/bin.js`. Everything else in the harness (patch builder, session id,
  key env, heartbeat plugin) is portable; `--no-refresh` is needed until the hotline files exist.

## 6. Network (after the raw copy finished — 19,978 files)

Memory-to-null upload, 200 MiB of zeros from this laptop, remote reader discarding to null:

| path | MiB/s | Mbit/s |
|---|---:|---:|
| ssh → Tailscale IP 100.78.87.112 | 8.92 | 74.8 |
| ssh → LAN IP 192.168.1.42 | 10.00 | 83.9 |
| 3 parallel ssh streams, LAN | 11.51 aggregate | 92.1 |
| raw TCP 192.168.1.42:9100 | not reachable (firewall) | — |

Link rates are 351/780 Mbps and both laptops are on 5 GHz, so the measured ~80–92 Mbit/s is
**the Wi-Fi link/AP airtime, not SSH** (parallel streams barely help) and not CPU (the HP's 8
cores sat at ~15% during the transfer). A 50 GB data root would take ~1.4 h to copy at this rate;
the 128.7 MiB repo snapshot takes ~15 s.

## 7. What the controller needs to start real workers on the HP

Working already (all native unless noted):

1. **Bun** 1.4.4 (`~\.bun\bin\bun.exe`) — native.
2. **Node 24 ARM64** (`C:\RE\node24\node-v24.22.2-win-arm64\node.exe`) — required, dsh will not
   run under Bun.
3. **dsh** 0.2.1-rc.5 installed via bun, booted through Node.
4. **`headless` profile** created from the shipped template at `~\.dsh\profiles\headless`
   (cordis.yml + cordis.patch.yml + package.json + pnpm-workspace.yaml).
5. **Python 3.14 ARM64** at `%LOCALAPPDATA%\Programs\Python\Python314-arm64` with
   `onnxruntime`, `onnxruntime-qnn`, numpy, pillow, pypdfium2, duckdb, onnx,
   rapidocr-onnxruntime (models + metadata), basedpyright 1.40.2, pytest, psutil.
6. **`reality_engine/scripts/hp_run.py`** for sync/copy-db/run/status/fetch, and `C:\RE\repo`
   as the code snapshot.

Still missing / broken on ARM:

1. **MCP servers cannot import**: `mcp` → `cryptography` has no cp314 win_arm64 wheel. Needs a
   **Python 3.13 ARM64** interpreter for the MCP servers (3.13 has the wheels). This is the one
   blocker to a worker that can call code-intel/reality-data.
2. **The harness's `DSH` path** must become a Node-based shim (Bun can't run dsh).
3. **No git on the HP** — the controller's worktree/commit flow needs `git` installed (nothing
   in this run used it; the runner syncs a tar).
4. **reality-data needs data**: `REALITY_DATA_ROOT` + the DBs. Only the 21 MB pilot manifest DB
   was copied; the live set is ~90 GB (≈2.5 h at the measured 10 MB/s), so copy only what the
   workers read.
5. **Heartbeat plugin / profile patches**: the per-run patch (provider, session id, effort) is
   built by `run_deepseek_harness.py` and works; the heartbeat Cordis plugin
   (`dsh_heartbeat_control.mjs`) is in the repo but its loopback mailbox was **not** exercised
   here (no long run to supervise).
6. **The `x-opencode-session` header** is emitted from the patch; it was present in both calls
   (same id), so Go does not reject the HP.

## 8. Commands used

```powershell
python -m reality_engine.scripts.hp_run sync
python -m reality_engine.scripts.hp_run copy-db <file>
python -m reality_engine.scripts.hp_run run <name> -- <absolute python> <script>
python -m reality_engine.scripts.hp_run status [name]
python -m reality_engine.scripts.hp_run fetch <remote path> [--dest <local>]
python -m pytest reality_engine/tests/test_hp_run.py -q      # 10 passed
```

HP-side benchmark files (left in place): `C:\RE\ocr_bench.py`, `C:\RE\capacity2.py`,
`C:\RE\hp_dsh_call.py`, `C:\RE\models_fixed\{det960,rec320}.onnx`,
`C:\RE\out\{cpu,htp,gpu}\texts.jsonl`, `C:\RE\cap_result.json`.

## 9. Not tested

- Windows built-in OCR, and Python x64 under emulation for the cv2/pyclipper pipeline.
- A real dsh worker holding its MCP servers (blocked by the `cryptography` wheel — see §7).
- The heartbeat supervisor over a long run.
- Token counts per call (not exposed by `--json`; read them from the Go ledger).
- Sustained multi-hour thermal behaviour of the NPU.
