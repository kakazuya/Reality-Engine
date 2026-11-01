# HP OmniBook 5 — capacity, OCR accelerators, network (2026-10-31)

> **Corrections later the same day:** the HP does **not** need Python 3.13 — `cryptography` 46.0.3 installs on its 3.14 ARM64 and `mcp` runs there (§10.1 below); §2 and §7's 3.13 requirement is stale. The LAN address `192.168.1.42` now times out; use `HP_RUN_HOST=zen7s@100.78.87.112` (`tasks/STATE.md`).

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

---

## 10. Real dsh workers — host, capacity, proof (2026-10-31, follow-up run)

**Measured answer: six real workers is the operating point, not eight.** Six real
`dsh` workers ran together: **7.49 GB RSS, 1.28 GB free RAM left, 42 processes,
13–26% CPU**. One worker peaks at **1.29 GB** (8 processes: node + two Python MCP
servers + basedpyright + shells); the same task took **16.9 s alone and 76.9 s**
with the other five running (4.5×). Eight workers would need ~10.3 GB against the
~7.5 GB this box has free, so 8 would swap — the simulated 155 MB/worker figure in
§1 was off by ~8× because a real dsh worker keeps its two MCP servers, the LSP
child and a Node runtime.

Two real workers finished end to end (**298 s** and **450 s**) and their patches
applied cleanly on the MSI (`dsh-hp/<id>` branches, 524 B and 514 B).

### 10.1 Host setup — what was actually missing

| item | state | note |
|---|---|---|
| Python for the MCP servers | **already fine on 3.14 ARM64** | The brief's 3.13 requirement is stale: `cryptography` 46.0.3 is installed from its `cp37-abi3-win_arm64` wheel and `pywin32` 312 has a cp314 win_arm64 wheel. The real blockers were four missing pure-Python packages: `pyjwt`, `uvicorn`, `httpx2`, `pyyaml`, now installed into `%LOCALAPPDATA%\Programs\Python\Python314-arm64`. **No 3.13 install was made.** |
| `git` | already on PATH | `C:\Program Files\Git\cmd\git.exe` 2.56.0 (§7 item 3 is stale). HP job trees are owned by `BUILTIN\Administrators` while the ssh user is `zen7s`, so every runner git call passes `-c safe.directory=*`. |
| Node-backed `dsh` shim | built | 5.6 KB AnyCPU C# launcher compiled once with `csc.exe`; runs `node.exe` on the bun-installed `@deepseek-ai/dsh/lib/bin.js`. Bun's launcher is kept as `~\.bun\bin\dsh.bun.exe`. `dsh --version` → `0.2.1-rc.5`; `DSH_NODE` overrides the node path. |
| code-intel MCP | **answers a real call** | stdio JSON-RPC `initialize` + `tools/call`: `symbols("connect_ro")` → `reality_engine/db/readonly.py:119`, `source: lsp`. |
| reality-data MCP | answers; needs data | `catalog()` returned `{ok:false, code:"snapshot_missing"}` with an empty `C:\RE\data` — a correct answer for a data-less host. `--dbs` mounts named DBs (WAL-consistent `sqlite3.backup`, read-only attribute, copied only when the MSI DB is newer). |
| Tailscale address | flaky this run | `100.78.87.112` refused connections mid-run while `192.168.1.42` stayed up; `HP_RUN_HOST=zen7s@192.168.1.42` is the safe default for the runner. |

The HP jobs run the same interpreter (3.14 ARM64), execute the job checkout's own
`run_deepseek_harness.py` under the Node shim, and use the same model
(`deepseek-v4.1-flash`), max effort, account 2 and stable `x-opencode-session`
(`fb0219dd-…`). Each job gets the same context-pack header and the same
`CODE_INTEL_INSTRUCTION` / `PROGRESS_NOTES_INSTRUCTION` text MSI workers get
(imported from `plugins/dsh-worker/server` at start time, not copied prose).

### 10.2 `reality_engine/scripts/hp_worker.py`

```powershell
# start (refuses Mon-Fri 06:30-09:30 / 11:30-15:30 IST exactly like the MSI manager)
python -m reality_engine.scripts.hp_worker start tasks/brief.md `
    [--dbs equity_intelligence.db,bse_announcements.db] [--test-cmd "python -m pytest ... -q"] `
    [--commit HEAD] [--permission workspace-write|read-only] [--max-output-tokens N] [--timeout S] [--peak-ok]

python -m reality_engine.scripts.hp_worker status [hp-...]   # state, exit, result size, test tail
python -m reality_engine.scripts.hp_worker result <id>       # fetch + print result.md, status, log
python -m reality_engine.scripts.hp_worker fetch-patch <id>  # git diff back, apply on dsh-hp/<id>
python -m reality_engine.scripts.hp_worker cancel <id>       # taskkill /T the job's pid
```

A job is `C:\RE\jobs\<id>\`: `repo\` = `git archive <commit>` of the MSI HEAD with a
throwaway `git init` + base commit (plus `.git/info/exclude` for the scratch files a
worker produces), `brief.md`, `hp_mcp.yml` (per-run MCP patch), `run.cmd`, and
`result.md*`. The launch is WMI `Win32_Process Create` — the route proved in §2; the
launcher scp's `run.cmd` and only sends a ~600-character encoded command, because the
old in-command base64 exceeded cmd.exe's 8 KiB limit. `run.cmd` runs the harness and
then the `--test-cmd` **outside dsh's sandbox** (dsh's `workspace-write` blocks pytest
temp dirs and piped child stdio on this host — both workers hit it and reported it),
so the test tail in `status` is the real host result.

DB sync stages a WAL-consistent copy with `sqlite3.backup`, copies only when the MSI
file is newer (mtime stored beside the remote file), and marks the remote file
read-only.

### 10.3 Proof: two real workers, end to end

| job | task | duration | result | host test | patch | applied on MSI |
|---|---|---:|---:|---|---|---|
| `hp-20261031T041248-a8844d` | docstring sentence in `hp_run.py` | 297.8 s | 4,104 chars | **10 passed** | 524 B | `dsh-hp/hp-…a8844d` ✔ |
| `hp-20261031T041347-265ef0` | docstring line in `test_hp_run.py` | 449.8 s | 3,640 chars | **10 passed** | 514 B | `dsh-hp/hp-…265ef0` ✔ |

- Both status records: `state completed`, `exit_code 0`, `failure null`, **0 heartbeat
  pings, 0 unanswered**, 86/91 worker-activity events. No tool failure other than the
  sandbox limits each worker diagnosed itself.
- **Survives closing ssh**: both workers were launched by WMI and the start command had
  returned long before completion; they ran to the end with no session open (same route
  as the 90/90-tick test in §2).
- The workers used both MCP servers in-run (`code-intel symbols/module_map/diagnostics`
  and `reality-data catalog`) and reported the data-less answer honestly.

### 10.4 Six at once — real RAM, CPU, time

All six started within 6 s of each other (each uploads its own 129 MiB archive; the
start path is bandwidth-bound, not memory-bound).

| workers | free RAM | RSS of node+python | processes | CPU | time |
|---:|---:|---:|---:|---:|---|
| idle | 7.51 GB | 0 | 0 | ~0% | — |
| 1 | 6.86 GB | **1,293 MB** | 8 | 9.6% | **16.9 s** (same brief) |
| 2 (proof) | — | — | — | — | 298 s / 450 s |
| **6** | **1.28 GB** | **7,488 MB** | **42** | 13–26% peak 100% at boot | 17.1–76.9 s (mean 38.8 s) |

Per-worker ≈ **1.25 GB** in the six-worker run, matching the 1.29 GB single-worker
peak. The box does not have 8 × 1.25 GB free next to the desktop + raw copy, so
**6 is the measured safe number; 8 needs ~2.5–3 GB more RAM than it has**.

### 10.5 OCR accuracy vs text-layer truth (20 pages) — the post-processing was the bug

Text-layer pages: 20 non-scanned filings from `pilot60_history_manifest.db` on the
MSI, the page with the most text per PDF, rendered 3× with pypdfium2, truth =
`page.get_textpage().get_text_range()`, accuracy =
`1 − edit_distance(casefolded truth, casefolded OCR) / len(truth)`.

| page | truth chars | OCR chars | char acc. | line-sorted acc. |
|---|---:|---:|---:|---:|
| STLTECH__373691c5 p2 (slide) | 5,975 | 6,068 | **0.954** | 0.762 |
| JUBLINGREA__dd188e96 p1 | 3,361 | 3,410 | 0.938 | 0.861 |
| NLCINDIA__40a7cb32 p1 | 3,075 | 3,076 | 0.935 | 0.828 |
| UBL__15cda7c0 p1 | 3,709 | 3,956 | 0.883 | 0.713 |
| ASHIANA__45a28a8f p1 | 1,843 | 1,698 | 0.857 | 0.307 |
| DOLLAR__27b15a3b p1 | 1,934 | 2,086 | 0.848 | 0.591 |
| KEC__021b8327 p0 | 1,507 | 1,512 | 0.760 | 0.837 |
| ASHIANA__5bc3f505 p0 | 1,540 | 1,604 | 0.745 | 0.706 |
| ESAFSFB__0fe7c53a p0 | 2,668 | 2,429 | 0.724 | 0.534 |
| KEC__0c7457f6 p0 | 1,375 | 1,388 | 0.671 | 0.789 |
| STLTECH__c57b1e3b p0 | 1,298 | 1,307 | 0.613 | 0.854 |
| BIGBLOC__ccd47fdc p0 | 1,346 | 1,621 | 0.609 | 0.683 |
| KALYANKJIL__a9062e06 p0 | 1,682 | 1,706 | 0.600 | 0.853 |
| KALYANKJIL__17d7027f p0 (same letter) | 1,682 | 1,706 | 0.600 | 0.853 |
| IDEA__6259d560 p0 | 1,251 | 1,632 | 0.512 | 0.341 |
| PIDILITIND__14ccea68 p0 | 1,799 | 1,695 | 0.499 | 0.670 |
| UFBL__a606683d p0 | 1,639 | 1,654 | 0.459 | 0.858 |
| URAVIDEF__8231788a p0 | 1,356 | 2,028 | 0.409 | 0.406 |
| TMPV__ffe2f0d4 p0 | 748 | 880 | 0.389 | 0.738 |
| PRESTIGE__3afb2252 p1 | 1,872 | 2,020 | 0.333 | 0.405 |
| **mean (20)** | | | **0.667** | **0.680** |

The old path (fixed 320-px rec canvas, wide lines squashed then clipped) scores
**0.151 mean / OCR chars = 14.1% of truth** on the same 20 pages — that is the
"gibberish" the brief warned about, and CPU/NPU agreement could not see it because
both devices shared the same post-processing.

**What was fixed in `reality_engine/scripts/hp_ocr_check.py`:**
1. **Line chunking**: a full-width A4 line is ~50× taller than wide; the rec graph is
   shape-locked at 48×960. Squashing it to 960 (or clipping at 320) destroys it. Each
   line is now cut into ≤960-px-wide chunks at the emptiest column near the boundary;
   the join adds a space only when the cut column was white.
2. **Line bands inside a merged component** (row-density valleys), instead of one
   recognition pass over a whole paragraph.
3. **90°/270° retry** when a page yields <40 chars (landscape tables on portrait pages,
   rotated scans). The GMR Airports encumbrance page went from **1 character to 1,654**
   and now matches the page.

Residual error is page content, not recognition: logo/all-caps letterheads are read as
extra text (URAVIDEF 2,028 OCR chars vs 1,356 truth), the text layer's reading order
differs from the visual order (ASHIANA Form C: the "FORM C" logo comes last in the text
layer), and ruled tables are seen as graphics. On pages without a logo block the
pipeline reaches 0.93–0.95.

Cost of the fix: **43.9 pages/min** on the NPU (was 159.7 pages/min through the broken
flat path; the extra rec chunks are the price). For the 1,073 scanned files (~13,300
pages) that is **~5.0 h**, still ~3× the CPU and ~1.9× the GPU.

### 10.6 Twenty scanned pages — NPU output vs the page

Corpus: the first 20 entries of `C:\RE\pages30.txt` (middle page of each scanned PDF,
`C:\RE\raw\pilot60_history`), `--provider qnn-htp`, chunked path. First 200 characters
of NPU output vs my reading of the rendered page:

| # | NPU first 200 chars | the page says |
|---:|---|---|
| 00 | `GlobalIyre Industry TireProduction TireRubberd Consumption (mn units) (ooo tonnes) +3.2% +3.1% 2,098 31,733 +2.2% 1,788 +2.3% 27,281 1,691 24,737 21,692 1,433 206 2011 2016 2021E 2806 2011 2016 2021E` | OCCL "Global Tyre Industry": two bar charts, production 1,433/1,691/1,788/2,098 mn units and rubber 21,692/24,737/27,281/31,733 kt; every number right, "206" is 2006, "Tyre" split. |
| 01 | `Anupam Rasayan 1to acguire stake in Tanfac Industri ies from Birla Group Holdings Private Limited and Others Surat,February01,2022: Anupam Rasayan JIndia Ltd.(NSE,BSE: ANU) RAS）ARIL one of India'slead` | Anupam Rasayan press release: acquisition of 24.96% of Tanfac from Birla Group Holdings for ₹148.14 cr + 26% open offer for ₹154.31 cr. OCR is right apart from spacing. |
| 02 | `? Asahisongwon physical form s hall not be processed unless t he securities are heldm Idmembers at the Registered Office of the Company d uring office hours in dematerialisedform with the depository,` | Asahi Songwon AGM notice, two columns. OCR interleaves the columns (left/right merged per line) — recognition is good, reading order is not. |
| 03 | `SBMUTUALFUND SBl Funds Manag ement Limited A Joint venture bel ween SBr& AMUNDr PARTNERE RFORLFE (CIN:U65990MH 992PLC065289) Format for Disclosures under Regulation 29(1) of SEBI (Substantial Acquisit` | SBI MF Reg 29(1) form for Ashiana: 5,061,223 shares (4.9449%) before, 235,000 acquired, 5,296,223 (5.1745%) after. Header right; the table values are not in the first block. |
| 04 | `sLOSUREUNDERREGULATTON 29D OF SEBI SUBSTANTIAL ACOUIS ONOF SHARESANDTAKEOERSREGU LAONSO Part-A-Details of tl heAsguisition Name of the Ta rget Company TC Adani Gas Limited Name(s)of the acg uirer andP` | Adani Gas Reg 29(1): Total Holdings SAS, after 41,13,31,740 shares (37.4002518%). All-caps heading is mangled; values later in the text are usable. |
| 05 | `After the sa eholding ofe 0.% 0.80% a)shares carrying voting rights b)shares encumbered with the seller vRs otherwise than by eguity shares d)Warrants/convertblesec uritiesanyother instrument that ent` | Rajasthan Global Securities Reg 29(2): Majesco open-offer sale, 4,53,31,34 shares, 2,86,29,689 shares of ₹5 after. Body text readable, table numbers weak. |
| 06 | `602,Floor 6,Rahei aTitanium MSKA Western Express Highway,Geetanjali Railway Colony,Ram Nagar,Goregaon （E） Mumbai 40o063,INDIA Tel: +91 22 6831 1600 & Associates chartered Accountants IndependentAudlit` | MSKA & Associates audit review report on Majesco's June-2021 results. Address and heading right; "MSKA"/"Auditor's" split. |
| 07 | `Formatfordisclosures under Regulation 292lof sEBl (Substantial Acguisition if Shares and Takeovers) Regulal ons.z Nameaf the Target company(TO BIGBLOCCONSTI RUCTION LIMITED Namesof the acguirer and Pe` | Bigbloc Reg 29(2): Narayan Saboo, transmission of 2,50,000 shares, 7.90% → 8.26%, date 21-03-2022. Recognisable. |
| 08 | `Chartered Accountants INDEPENDENFAUDITORSLIMITED R EVIEWREPORT To Board of Directors of BGBLOCCONSTR UCONMTTED We have reyiiewed the accompanying Staltement of Consolidated Unaud ited Financial Result` | RKM & Co. limited review of Bigbloc (Sep-2022). Company name and words are mangled; readable meaning. |
| 09 | `Bnd ustriestd Date-24/0o9/2019 ListingDepartment The General Manager Calcuttastock Exchange Limited Departmento f corporate services Lyons Range BSELimited Kolkata-zoooo1 PhirozeJee eebhoyTower Dalal` | BMW Industries letter to the exchanges on a credit-rating outlook (24/09/2019), with a 3-row rating table. Good except the merged headings ("Bnd ustriestd" = BMW Industries Ltd). |
| 10 | `Resolution( special Resolution required :(Ordinary /Special) Whether promoter/promot ter group are interested ino No the agenda/resolution? Description of resol lution considered Appointment of Ms. Pa` | Bosch resolution(7) e-voting table appointing Ms. Padmini Khare; the numbers table is not detected (1,161 chars). |
| 11 | `N NA bVRs acquiredotl herwise than by eguity NA. N shares NA N.A NA c)Warrants/convertibl e securities/any other / NA. instrumentthat eni fitles the acguirer to receive shares carrying voting rights i` | Dalmiya Bharat Reg 29(2): Odisha Cement shares cancelled in the scheme, 23/01/2019, capital 5,69,00,220 → 19,27,27,553. Form labels partly readable. |
| 12 | `september i4 2oi9 as the cut-off dateThe Comlpany has engaged the services of i Link Intime India pvt.Ltd.to providlethe e voting facilityoni instavote platform The Remote e- voting wil commence on Tu` | Karda Constructions e-voting/AGM letter (Sept 2019). Mostly correct, dates in digits get confused (14). |
| 13 | `DLELMTED DLE DLEGateway Tower.R Block BUILDINGINDIA DLFCityPhase I1,Gurugram 122 002, HaryanaIndia Tel.:(+91-124) 4396000: investor-relationsadlf.in Annexurei BriefProfile of Ms. savifri Devi Si ngh a` | DLF Annexure 1: profiles of Ms. Savitri Devi Singh / Ms. Anushka Singh as non-executive independent directors. Header logo garbled, names right. |
| 14 | `Annexure-A LIST OF PERSONS AC TING IN CONCERT (PACS) Formingpar oif disclosurc under Reguilation 2or D ofthe SEBl rSubstantial Acguisi ion of sares and Takeovers Reulations,21 01 1 dated 28.06.20j91 T` | DLF Annexure-A: the 16 PACs list. Heading right; table names later in the text. |
| 15 | `Ni Ni TC(specifyholdingi ineachcategory)Nil Ni acquired/sold N N Ni dShares encumbered /invoked/releasedbyN1 d the acquirer e）Total（a+b+c+d） 60.00,000 o.24 o.24 After the aeuis ion/sale, holding of:` | DLF Reg 29(2) page 2: 60,00,000 shares (0.24%), after 1,84,92,28,865 (74.71%), 1 Aug 2023. Table labels noisy, numbers usable. |
| 16 | `SR BATLIBOI &COLLP chartere soraEntity Relation 43 DLF Green Valley Partnership Firm 44 DLF Home Developers Limited Subsidiary 4 DLF Homes Goa Private Limited subsidiary 46 DLF Homes Panchkula Private` | S.R. Batliboi list of DLF group entities (rows 43–64). Nearly correct. |
| 17 | `Format for disclosures undler Regulation 29(2) of SEBl (Substantial TAcquisition of Shares and Takeovers Regul ations,2011 Nameof the Targel tcompany(tc) DOLLARINDUST RIESLIMITED l Name(s) of the acgu` | Dollar Industries Reg 29(2): Simplex Impex, 25,576,771 (45.10%) before, 10,000 acquired. Good. |
| 18 | `CHANDRAKALAGUPTA 16A GURUSADAY ROAD, FLAT-4AB,TOWER-3, TheEMPIRE K0LKATA-700019 Warrants/convertibi lesecurities/anyother instrument that entit les the acquirer to receive shares carryi ing voting rig` | Chandrakala Gupta inter-se gift transfer, 2,51,650 shares (0.44%) → 1,06,420 (0.19%). Address right, form text usable. |
| 19 | `Disclosure by the 2romoter (s) to the Stock Exchangles and to the Target Companv for encuImbrance of shares / invocation olFencumbrancelrelease of encumbrance in terms of Reaulation 31 (1) and 31 (2` | GMR Airports encumbrance disclosure (landscape table). **Before the rotation retry this page produced 1 character**; now the heading and the rest of the table come out. |

Hand verdict: **NPU text is usable for reading and indexing, not for blind figure
extraction.** Body sentences come out right; logos, all-caps headings, ruled tables
and rotated pages still need a human or the text layer.

### 10.7 Commands used in this run

```powershell
python -m reality_engine.scripts.hp_worker start tasks/brief.md --test-cmd "python -m pytest reality_engine/tests/test_hp_run.py -q" --max-output-tokens 6000 --timeout 1500
python -m reality_engine.scripts.hp_worker status
python -m reality_engine.scripts.hp_worker result  hp-20261031T041248-a8844d
python -m reality_engine.scripts.hp_worker fetch-patch hp-20261031T041248-a8844d   # -> dsh-hp/<id>
python -m reality_engine.scripts.hp_worker cancel hp-...
# OCR (deployed at C:\RE\hp_ocr_check.py, also committed in reality_engine/scripts)
python C:\RE\hp_ocr_check.py --mode textlayer --text-dir C:\RE\ocr_text --models C:\RE\models_fixed --provider qnn-htp --out C:\RE\ocr_check
python C:\RE\hp_ocr_check.py --mode scanned --list C:\RE\pages30.txt --base C:\RE\raw\pilot60_history --models C:\RE\models_fixed --provider qnn-htp --limit 20 --out C:\RE\ocr_check
python -m pytest reality_engine/tests/test_hp_worker.py reality_engine/tests/test_hp_run.py -q   # 25 passed
```

Left on the HP: `C:\RE\jobs\hp-*` (worker jobs), `C:\RE\ocr_text` (20 text-layer
PDFs), `C:\RE\ocr_pages` (20 rendered pages), `C:\RE\ocr_check` (rows JSONL),
`C:\RE\mcp_check.py`, `C:\RE\hp_ocr_check.py`, the dsh shim and `dsh.bun.exe`.

### 10.8 Still open

- No DBs are mounted on the HP by default; a reality-data worker is only as good as
  the `--dbs` list (copying 50 GB at 10 MB/s is 1.4 h).
- Each start uploads a fresh 129 MiB archive; six starts are ~80 s of Wi-Fi and the
  workers wait for it. A per-commit cache on the HP would cut that.
- The HP tree's ownership (`Administrators` vs `zen7s`) makes plain git refuse it;
  the runner passes `safe.directory=*`, but a human on the box will hit the warning.
- Worker sandbox: pytest inside a `workspace-write` dsh session cannot create its
  `0o700` temp dirs or pipe child stdio on this host. The runner's post-run test step
  covers the check; a worker asked to run pytest itself will fail and should be told.
- OCR: 0.93–0.95 on clean pages, not 0.95+ everywhere; the remaining loss is logos,
  all-caps letterheads, ruled tables and text-layer reading order, not recognition.

## 11. Worker throughput — 1, 3 and 5 concurrent HP workers (2026-10-31, follow-up)

**Answer: the limit is local cold start, not the provider and not memory.** Five workers
added on top of four already running finished in 8.0–9.7 s against 8.8 s for one — no
slowdown. The earlier "six workers, 4.5× slower" was a *tail* (the slowest job), made of a
58 s cold start plus one 60 s provider stall; the work phase stayed ~10 s in every job.
Recommend **5 concurrent short workers**, or **6** for jobs whose work outlives startup.

### 11.1 What was run

05:38–05:40 IST, OpenCode Go **account 1**, `deepseek-v4.1-flash` at max effort. One shared,
warm `C:\RE\repo` checkout (no per-job upload), one fixed brief: read
`reality_engine/config.py` and answer with the first ALL_CAPS constant and its line number.
Wave N launched N harness workers within ~2 s of each other; free RAM, process RSS and CPU
were sampled 1.3 s after the launch. **Another worker's four HP jobs were running
throughout** (`other_running_jobs = 4` in every sample), so the box was carrying 5, 7 and 9
dsh workers — a deliberately conservative, real-load test.

| workers added | others running | free RAM MB | per-worker wall, s | max | mean | startup | model wait | local | finished/h, wave | per worker/h |
|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4 | 3,804 | 8.8 | 8.8 | 8.8 | 5.0 | 3.0 | 0.8 | 409 | 409 |
| 3 | 4 | 3,457 | 9.1, 9.6, 10.0 | 10.0 | 9.6 | 5.7 | 3.3 | 0.6 | 1,129 | 376 |
| 5 | 4 | 2,623 | 9.7, 8.8, 8.0, 8.0, 8.8 | 9.7 | 8.7 | 4.8 | 2.8 | 1.1 | 2,078 | 415 |

All nine jobs exited 0 and returned the same correct answer (`PROJECT_ROOT line 10`).
Split comes from each job's heartbeat events: the gap ending at a model-produced event
(thinking/text/step_output/tool_call/final) is provider time; the first such gap also
contains dsh cold start and is charged to `startup`; tool execution and teardown are
`local`. Raw: `tasks/efficiency/hp_bench_results.json`, per-job status in
`tasks/efficiency/hp_bench_raw/`, driver `tasks/efficiency/hp_bench_run.py`.

- **Provider — not the limit at 5.** Model wait is flat: 3.0 s (1 worker), 3.3 s (3), 2.8 s
  (5). No queueing appeared even with nine dsh workers on the box.
- **Memory — not the limit.** Measured free RAM fell 3.8 → 2.6 GB, all processes together
  4.8–6.1 GB RSS, no OOM, no swap; every job still finished inside 10 s.
- **Local — the limit.** Even warm, startup (dsh boot + harness import) is 55–65% of each
  job's wall time and is per worker. Adding workers does not increase it on the shared
  warm checkout, but a cold checkout does (below).

### 11.2 Why the earlier six-worker run felt 4.5× slower

That run (04:31–04:34, **account 2**, a fresh 129 MiB `git archive` + `git init` per job and
both MCP servers in each worker) gave 17.1, 21.2, 68.1, 28.5, 76.9 and 20.8 s. Replaying
their heartbeat events: the *work phase* is ~10 s in every job. The spread is **(a) cold
start, 7–58 s** (job `hp-20261031T043114-b81e3c` took 58 s to its first model event; others
7–16 s) and **(b) one provider stall**: `hp-20261031T043117-d5be16` has a 60 s gap between
two model steps (23:02:40 → 23:03:40) while every other step is 5 s.

So the honest ratios are: mean 38.8 s = **2.3×** the fastest 17.1 s job; max 76.9 s =
**4.5×** — and that max is one cold start plus one provider stall, not a concurrency
penalty. The 13–26% CPU reading was sampled after the cold-start burst; startup is where
the CPU goes, which is why CPU looked idle while walls stretched.

### 11.3 Recommended operating point

- **5 concurrent short HP workers** is the measured point: 2,078 finished tasks/h on this
  task shape, and per-worker rate (415/h) is unchanged from one worker (409/h).
- **6** for jobs whose work outlives startup (the capacity section above measured 6–8 safe
  on RAM/CPU); the only measured penalty of 6 is the extra cold start.
- To make 6–8 pay for short jobs, fix startup rather than add workers: cache the per-commit
  archive on the HP (already in §10.8) and keep one warm checkout instead of a fresh
  `git init` per job — the warm-checkout bench needed no more wall time at 5 than at 1.

Caveats: four concurrent jobs from another worker share the box (real load, unknown mix);
`cpu_pct` is an instantaneous `Win32_Processor` sample and read 100 in every wave, so it is
not used as a load measure; free RAM is one sample per wave at t ≈ 1.3 s.

### 11.4 Driver

```powershell
python tasks/efficiency/hp_bench_run.py bench --waves 1,3,5
python tasks/efficiency/hp_bench_run.py mcp-check   # real start/status/result/cancel
```

The first attempt wrote empty answers: `hp_run`'s wrapper starts in the job dir, so the
harness could not import `reality_engine` (fix: `set PYTHONPATH=C:\RE\repo`), and a `cd`
inside the command sent `exit.txt` to the repo root, where the wave poller never saw the
job finish. Both fixed in the driver; a wave now reports `problems` if a job has no clean
answer.
## 11. Snapdragon OCR engines — Windows AI, Qualcomm EasyOCR, baseline (2026-10-31)

**Measured answer (updated 2026-11-01): the Windows App SDK `TextRecognizer` is
the most accurate engine measured and it now runs from a signed MSIX; Windows'
`Windows.Media.Ocr` remains the fastest (CPU, 186.7 pages/min).** The earlier
"gated" result in §11.2 was superseded on 2026-11-01 — **the engine runs from a
signed MSIX launched in the interactive session (scheduled task `/IT`)**; on the
larger 2,387-page sample its best setting reaches table-number
recall/precision 0.9728/0.9761. Qualcomm's AI Hub
EasyOCR *does* run on the NPU (both graphs) under `onnxruntime-qnn`, but its
pre-exported detector/recogniser pair, decoded with the numpy CRAFT post-processing
available here, scores 0.291 and runs at 1.5 pages/min — 30× slower than the
baseline and 4× worse.

Host: HP OmniBook, Snapdragon X X1-26-100 (Hexagon NPU), Windows 11 26H2 build
26300.9818, Python 3.14.7 ARM64, `onnxruntime` 1.31.1 + `onnxruntime-qnn` 2.7.0,
`pypdfium2` 5.14.0. Same 20 text-layer pages and 20 scanned pages as §10.5/§10.6.
The other HP worker (`hp-…3e6065`) was running throughout, so page rates are a
little below the §10 numbers; accuracy does not depend on load.

### 11.1 Results

Text-layer pages: truth = the PDF text layer, `acc` = case-folded character
accuracy after whitespace normalisation (the §10 metric), `order-free` = the same
edit distance after sorting both sides' words (bag of words, so a table read
column-by-column is not punished twice), `numbers` = exact-number recall after comma
normalisation. 17 letters, 2 statutory annexures, 1 presentation page.

| engine | device | pages/min | chars acc | order-free | number recall | letters (17) | tables (2) | slide (1) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **RapidOCR ONNX, QNN HTP** (current) | **NPU** | **43.9** | **0.6669** | 0.6241 | 0.7544 | 0.6585 | **0.5950** | 0.9536 |
| **Windows.Media.Ocr** | CPU | **186.7** | **0.6703** | **0.8782** | **0.9640** | **0.6802** | 0.4217 | **0.9983** |
| Windows.Media.Ocr, lines sorted by bbox | CPU | 186.7 | 0.7072 | 0.8782 | 0.9640 | — | — | — |
| Qualcomm AI Hub EasyOCR | NPU+CPU | 1.49 | 0.2910 | 0.2809 | 0.3601 | 0.2907 | 0.2811 | 0.3162 |
| Windows AI `TextRecognizer` (signed MSIX) | NPU | not measured on these 20 pages | — | — | — | — | — | — | — |

The `TextRecognizer` line is deliberately blank here: it was not scored on this
20-page set.  On the larger 1,300-page sample it reaches table-number recall
0.9728 / precision 0.9761 (300 DPI + grayscale) at 126 pages/min;
`tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md` has the lever table and test rows.

Scanned pages: no text layer, so scored on the ten pages with hand-read key numbers
from §10.6 (key-number recall) and on output volume:

| engine | device | pages/min | key-number recall | rotated page recovered | OCR chars |
|---|---|---:|---:|---|---:|
| RapidOCR ONNX, QNN HTP | NPU | 38.6 | 0.486 | **yes** (1/20, GMR page) | 41,666 |
| Windows.Media.Ocr | CPU | **171.6** | **0.625** | no (garbage on the GMR page) | 39,538 |
| Qualcomm AI Hub EasyOCR | NPU+CPU | — | — | — | not run (1.5 ppm ⇒ 2.2 h for 20 pages) |

NPU confirmation is the loaded backend DLL, because this box exposes no NPU
performance counter: the QNN runs load `QnnHtp.dll`, `QnnHtpPrepare.dll`,
`QnnHtpV73Stub.dll` (V73 is the X1's Hexagon) and `onnxruntime_providers_qnn.dll`;
`Windows.Media.Ocr` loads none of them and spends ~0.22 CPU-s per 0.32 wall-s,
i.e. the classic CPU OCR. The QNN sessions also run with
`session.disable_cpu_ep_fallback=1`, so a graph that did not compile on HTP would
fail rather than silently fall back.

### 11.2 Windows App SDK `TextRecognizer` — runs from a signed MSIX

**Current state (2026-11-01): it runs.**  The API is
`Microsoft.Windows.AI.Imaging.TextRecognizer` in the installed Windows App SDK
1.8 runtime (`8000.836.2153.0`): `GetReadyState` / `EnsureReadyAsync` /
`CreateAsync`, `RecognizeTextFromImageAsync(ImageBuffer)`, returning
`RecognizedText` with `Lines`, `TextAngle`.  A **signed** MSIX installed with
`Add-AppxPackage` and launched through its execution alias **in the interactive
session by a scheduled task with `/IT`** gets package identity, reports
`ready_state=Ready`, and recognises images.

The earlier result stands for what it tested: an **unpackaged** process gets
`E_ACCESSDENIED` at `GetReadyState` before any image, and a **loose
(unregistered, unsigned) MSIX** could not be made to start.  Those four launch
shapes are the historical record.  The missing piece was a properly signed
package plus an interactive-session launch, not a capability the API lacks.

What the working run measures (full method and levers in
`tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md`):

* 300 DPI + grayscale, defaults: tune rank 0.9680, table-number
  recall/precision 0.9728/0.9761, table words 0.9819/0.9776, prose numbers
  0.9924/0.9138, 126.1 OCR pages/min, 0 failed pages.
* 200 DPI no clean-up baseline: rank 0.9640, numbers 0.9645/0.9766,
  words 0.9786/0.9787, 149.5 pages/min.
* Word-level `MatchConfidence` is usable (1.51% of 13,297 number tokens wrong);
  `TextAngle` is 0 on every page and `RecognizedLineStyle` is `Handwritten` on
  every printed line, so those two fields carry no signal on filings.
* 400 DPI throws `NullReferenceException` on 10667×6000 px pages; 300 DPI
  (8001×4500) is the practical ceiling on this box.

### 11.3 Qualcomm AI Hub EasyOCR — runs on the NPU, loses on speed and accuracy

Asset: `easyocr-onnx-float.zip` v0.65.0 from
`qaihub-public-assets.s3…/qai-hub-models/models/easyocr/releases/v0.65.0/`, 87 MB,
**no account or sign-up needed**. The matching `qualcomm/EasyOCR` model card on
Hugging Face is **Apache-2.0**; the weights derive from EasyOCR (Apache-2.0) and the
AI Hub tooling is BSD-3-Clause. Detector: CRAFT, 20.8M parameters (79.2 MB), input
608×800 RGB, ImageNet normalisation, output is (text score, link score) at
half resolution. Recogniser: EasyOCR `english_g2` VGG + 2×BiLSTM, 3.84M parameters
(14.4 MB), input 64×800 grayscale, 199 CTC steps over 96 characters + blank.

Both ONNX graphs compiled on QNN HTP (`session.disable_cpu_ep_fallback=1`,
`QnnHtpV73Stub.dll` loaded). The LSTM recogniser also compiles on HTP, but CPU was
faster, so the scored run is detector-HTP + recogniser-CPU. Result: **1.49
pages/min, 0.291 char / 0.281 order-free / 0.360 number recall**, worse than the
baseline on every page type. Per page it spends 17–66 s in ~40–165 recogniser calls.

Two caveats, both measured rather than assumed:

- **The missing CRAFT post-processing.** EasyOCR's intended decode needs
  `cv2.minAreaRect` and `pyclipper` expansion. `pip install opencv-python-headless`
  on this Python 3.14 ARM64 reports "from versions: none" — there is no win_arm64
  wheel — so the run used the bench's axis-aligned connected-component boxes
  (threshold 0.3, 1.4× expansion, row-band splitting), which merge/split words.
- **The recogniser is not better even with identical boxes.** Feeding both
  recognisers the *same* RapidOCR det960 boxes: EasyOCR 0.521 vs RapidOCR 0.784
  (ASHIANA Form C), 0.190 vs 0.375 (JUBLINGREA), 0.084 vs 0.046 (STLTECH slide).
  So the 0.291 end-to-end is not only box geometry: the AI Hub recogniser is weaker
  on this corpus than RapidOCR's rec32.

For the 1,073-file job EasyOCR is therefore a non-starter on time alone: at
1.49 pages/min, ~13,300 pages would take **~150 hours**.

### 11.4 Recommendation for the 1,073 scanned files

Use **`Windows.Media.Ocr` as the first pass** for speed, and
**`TextRecognizer` (300 DPI grayscale) where the figures matter**: it is 1.5×
slower than MediaOcr but its exact-number accuracy is the best measured
(table numbers 0.9728/0.9761; 0.8131 of scanned XBRL facts found vs 0.8103 for
the 200 DPI baseline).  The current NPU pipeline stays last here.

- **Time:** 171–187 pages/min measured ⇒ 13,300 pages in **~1.2–1.3 h**; allow
  **~1.5 h** once the 90°/270° retry is added. The current NPU baseline is
  38.6–43.9 pages/min ⇒ **5.0–5.7 h**. EasyOCR: ~150 h, rejected.
- **Accuracy:** on the pages with truth, 0.670 plain / **0.878 order-free** /
  **0.964 exact-number recall** (baseline: 0.667 / 0.624 / 0.754). On the scanned
  key numbers, 0.625 vs the baseline's 0.486. Among the three engines in this
  section it is the only one whose figure recall is usable for filings;
  `TextRecognizer` now leads it (table-number recall 0.9728 on the larger set).
- **Two fixes are mandatory, both already in `hp_ocr_check.py`:** retry 90°/270°
  when a page yields <40 characters (MediaOcr produced garbage on the rotated GMR
  page, where the baseline recovers it), and sort the returned lines by their
  bounding boxes (+3.7 points of plain accuracy on the truth set).
- **Keep the NPU path for two cases:** tabular/annexure pages, where the baseline
  is better (0.595 vs 0.422), and any page still under 40 characters after the
  rotation retry. A per-page route on layout is cheaper than making one engine do
  both.

Expected for the 1,073 files: ~1.5 h, ~0.67 plain / ~0.88 order-free character
accuracy on text-bearing pages, number recall ~0.96 on clean pages and ~0.62 on
scans — i.e. better figures than today, in a quarter of the time, on the CPU that
is otherwise idle while the NPU pipeline post-processes in numpy.

The NPU is not the bottleneck in the current pipeline: the baseline uses 0.27 CPU-s
per page at 43.9 pages/min, while MediaOcr uses 0.22 CPU-s at 186.7 pages/min.
Replacing numpy post-processing (or the per-line QNN call overhead) would do more
for the NPU path than changing models.

### 11.5 Commands used

```powershell
# benchmark harness (new): scores any engine on the same pages/metrics
python -m reality_engine.scripts.hp_ocr_bench --engine qnn  --mode textlayer --models C:\RE\models_fixed --out C:\RE\bench\out
python -m reality_engine.scripts.hp_ocr_bench --engine media --mode textlayer --out C:\RE\bench\out
python -m reality_engine.scripts.hp_ocr_bench --engine easyocr --mode textlayer --out C:\RE\bench\out --det-provider qnn-htp --rec-provider cpu
python -m reality_engine.scripts.hp_ocr_bench --engine qnn  --mode scanned --list C:\RE\pages30.txt --base C:\RE\raw\pilot60_history --keys C:\RE\bench\scanned_keys.json --limit 20 --out C:\RE\bench\out
python -m reality_engine.scripts.hp_ocr_bench --engine media --mode scanned --list C:\RE\pages30.txt --base C:\RE\raw\pilot60_history --keys C:\RE\bench\scanned_keys.json --limit 20 --out C:\RE\bench\out

# Windows App SDK TextRecognizer helper: source is now committed at
# reality_engine/tools/textrec/, and it must be a signed MSIX launched in the
# interactive session.  Full build/run/cleanup steps:
# tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md
C:\RE\dotnet\dotnet.exe publish reality_engine\tools\textrec\textrec.csproj -c Release -r win-arm64
makeappx pack /d pkg /p textrec.msix /o
signtool sign /fd SHA256 /a /f rebench.pfx /p <password> textrec.msix
Add-AppxPackage -Path textrec.msix -ForceUpdateFromAnyVersion
```

### 11.6 Status and still open

- `TextRecognizer` runs from a signed MSIX launched in the interactive session
  (`/IT` scheduled task through the execution alias): see
  `tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md` for the tune table, frozen
  settings and the rebuild/cleanup steps.  `ImageScaler` is still blocked
  (`COMException: Package dependency criteria could not be resolved`) and the
  2.0 `TextRecognizerOptions` geometry modes are no-ops on this build.
- EasyOCR's real accuracy needs `cv2`/`pyclipper` CRAFT decoding. Neither has a
  win_arm64 cp314 wheel today; an x64-emulated Python or a small C++ box decoder
  would be needed. Given 1.49 pages/min, even a large accuracy gain does not change
  the 1,073-file recommendation.
- The scanned-page score still rests on 10 hand-read number sets. A text-layer
  truth for scanned pages would make the comparison exact.

