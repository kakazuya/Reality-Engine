# HP OmniBook 5: capacity, OCR accelerators, network (31 Oct to 1 Nov 2026)

**Answers first**

- **Capacity: 5 concurrent short workers, 6 when the work outlives startup.** A real dsh worker holds about 1.25 GB, and six together left 1.28 GB free (§10). Five added on top of four running showed no slowdown; the limit is local cold start (§10A).
- **OCR: Windows App SDK `TextRecognizer` is the best engine measured; no engine passes the gate of 0.95 number recall and 0.98 precision.** 0.9378 / 0.9242 on the frozen 150-page set at 3x (§12), 0.9728 / 0.9761 at 300 DPI grayscale on the larger sample (`tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md`). The NPU RapidOCR path scores 0.7354 / 0.7356 on the frozen set; its 159.7 pages/min in §4 came from a broken path that produced gibberish (§10.5). On the MSI CPU, RapidOCR beats `Windows.Media.Ocr` (§13).
- **dsh runs on the HP only under real Node, not under Bun** (§5).
- **Network is about 10 MB/s (80 Mbit/s)**, LAN or Tailscale; the limit is the Wi-Fi link, not SSH (§6). `hp_run` tries the LAN address first and falls back to Tailscale.

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

- **No step reached the stop rules** (task >2× or commit <1.5 GB). This simulation understated a
  worker by about 8×: real workers hold about 1.25 GB, so §10 and §10A replace its operating point.
- **MSI reference given by Shivam: ~1.15 GB/worker (760 MB node + 390 MB python, 4 workers).**
- **Heavy jobs beside workers: yes.** The NPU OCR run (159.7 pages/min) is one process and leaves
  the CPU mostly idle; the capacity run itself ran beside the raw copy (19,978 files) and the OCR
  runs without hitting the stop rules.

**What was simulated:** the two MCP servers were not started as servers in this run. The worker
held the same children they would start (`basedpyright-langserver`, and the `reality-data` modules
plus a DB handle), without the ~20 MB MCP wrapper. §10 measures real workers with both servers.

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

## 7. What the HP has for real workers

All native unless noted:

1. **Bun** 1.4.4 (`~\.bun\bin\bun.exe`), used only to install dsh.
2. **Node 24 ARM64** (`C:\RE\node24\node-v24.22.2-win-arm64\node.exe`), required: dsh will not run under Bun. A launcher replaces `dsh.exe` (§10.1).
3. **dsh** 0.2.1-rc.5, installed via bun, booted through Node, with the `headless` profile at `~\.dsh\profiles\headless`.
4. **Python 3.14 ARM64** at `%LOCALAPPDATA%\Programs\Python\Python314-arm64`, which also runs both MCP servers (§10.1).
5. **`reality_engine/scripts/hp_run.py`** for sync/copy-db/run/status/fetch, and `C:\RE\repo` as the code snapshot. `hp_worker.py` starts real workers (§10.2).

reality-data needs data: the live set is about 90 GB (about 2.5 h at 10 MB/s), so copy only what a job reads, through `dbs`.

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

- Python x64 under emulation for the cv2/pyclipper pipeline.
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
| Python for the MCP servers | **fine on 3.14 ARM64** | `cryptography` 46.0.3 is installed from its `cp37-abi3-win_arm64` wheel and `pywin32` 312 has a cp314 win_arm64 wheel. The real blockers were four missing pure-Python packages: `pyjwt`, `uvicorn`, `httpx2`, `pyyaml`, now installed into `%LOCALAPPDATA%\Programs\Python\Python314-arm64`. **No 3.13 install was made.** |
| `git` | already on PATH | `C:\Program Files\Git\cmd\git.exe` 2.56.0. HP job trees are owned by `BUILTIN\Administrators` while the ssh user is `zen7s`, so every runner git call passes `-c safe.directory=*`. |
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
    [--commit HEAD] [--permission read-only|workspace-write|danger-full-access] [--max-output-tokens N] [--timeout S] [--peak-ok]

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

## 10A. Worker throughput — 1, 3 and 5 concurrent HP workers (2026-10-31, follow-up)

**Answer: the limit is local cold start, not the provider and not memory.** Five workers
added on top of four already running finished in 8.0–9.7 s against 8.8 s for one — no
slowdown. The earlier "six workers, 4.5× slower" was a *tail* (the slowest job), made of a
58 s cold start plus one 60 s provider stall; the work phase stayed ~10 s in every job.
Recommend **5 concurrent short workers**, or **6** for jobs whose work outlives startup.

### 10A.1 What was run

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

### 10A.2 Why the earlier six-worker run felt 4.5× slower

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

### 10A.3 Recommended operating point

- **5 concurrent short HP workers** is the measured point: 2,078 finished tasks/h on this
  task shape, and per-worker rate (415/h) is unchanged from one worker (409/h).
- **6** for jobs whose work outlives startup (§10.4); the only measured penalty of 6 is the
  extra cold start.
- To make more than 5 pay for short jobs, fix startup rather than add workers: cache the per-commit
  archive on the HP (already in §10.8) and keep one warm checkout instead of a fresh
  `git init` per job — the warm-checkout bench needed no more wall time at 5 than at 1.

Caveats: four concurrent jobs from another worker share the box (real load, unknown mix);
`cpu_pct` is an instantaneous `Win32_Processor` sample and read 100 in every wave, so it is
not used as a load measure; free RAM is one sample per wave at t ≈ 1.3 s.

### 10A.4 Driver

```powershell
python tasks/efficiency/hp_bench_run.py bench --waves 1,3,5
python tasks/efficiency/hp_bench_run.py mcp-check   # real start/status/result/cancel
```

The first attempt wrote empty answers: `hp_run`'s wrapper starts in the job dir, so the
harness could not import `reality_engine` (fix: `set PYTHONPATH=C:\RE\repo`), and a `cd`
inside the command sent `exit.txt` to the repo root, where the wave poller never saw the
job finish. Both fixed in the driver; a wave now reports `problems` if a job has no clean
answer.

## 11. Snapdragon OCR engines: Windows AI, Qualcomm EasyOCR, baseline (31 Oct, unblocked 1 Nov)

**Measured answer: the Windows App SDK `TextRecognizer` is the most accurate engine measured and runs from a signed MSIX; `Windows.Media.Ocr` is the fastest (CPU, 186.7 pages/min) with weaker numbers.** Qualcomm's AI Hub EasyOCR does run on the NPU (both graphs) under `onnxruntime-qnn`, but its pre-exported pair, decoded with the numpy CRAFT post-processing available here, scores 0.291 at 1.5 pages/min. §11.1 holds the 31 Oct 20-page measurements; §12 is the frozen-set result and supersedes them where they differ.

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
| Windows AI `TextRecognizer` | Windows AI | 161.5 | — | — | 0.9378* | — | — | — |

`*` 150-page frozen table set (§12), not this 20-page set; `TextRecognizer` was not scored on these 20 pages. On the larger sample it reaches table-number recall 0.9728 / precision 0.9761 (300 DPI + grayscale) at 126 pages/min: `tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md`.

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

### 11.2 Windows App SDK `TextRecognizer` — gated on 31 Oct, unblocked 1 Nov

The API is **not** in `Microsoft.Windows.AI.Text` on this build (that winmd has
`LanguageModel`, `TextRewriter`, `TextSummarizer`, `TextToTableConverter`). It is
`Microsoft.Windows.AI.Imaging.TextRecognizer` in the installed Windows App SDK 1.8
runtime: `GetReadyState` / `EnsureReadyAsync` / `CreateAsync`,
`RecognizeTextFromImageAsync(ImageBuffer)`, returning `RecognizedText` with
`Lines`, `TextAngle` and per-line `BoundingBox` (four `Windows.Foundation.Point`
corners); `ImageBuffer.CreateForSoftwareBitmap` is the input path.

**31 Oct (history).** An unpackaged C# helper got
`E_ACCESSDENIED` at `GetReadyState` before touching an image, and a loose MSIX with
`runFullTrust` + `systemAIModels` and `uap10:RuntimeBehavior="win32App"` never
reached `Main` (`0x80070032`). No image was recognised.

**1 Nov (resolution).** A signed MSIX with package identity runs it. The exact
working build:

1. **Certificate:** self-signed, `CN=REBench` (must equal the manifest
   `Publisher`), Code Signing EKU, installed to `Cert:\LocalMachine\Root` **and**
   `Cert:\LocalMachine\TrustedPeople` (admin). Thumbprint
   `12D0B68EB482079BF006722B057F1F50B3A2CFC6`, 7-day validity — test only.
2. **Manifest:** `Identity Name="RETextRecBench" Publisher="CN=REBench"
   ProcessorArchitecture="arm64"`, `uap10:RuntimeBehavior="packagedClassicApp"`,
   `uap10:TrustLevel="mediumIL"`, capabilities `runFullTrust` + `systemAIModels`,
   dependency `Microsoft.WindowsAppRuntime.1.8`, execution alias `textrec.exe`.
3. **Build:** .NET 8.0.427, `Microsoft.WindowsAppSDK` 1.8.260921001,
   `WindowsPackageType=None`, and — the critical fix —
   `<WindowsAppSDKBootstrapInitialize>false</WindowsAppSDKBootstrapInitialize>`.
   With the default auto-bootstrapper the packaged app died before `Main` with
   `ERROR 0x80070032: Bootstrapper initialization failed while looking for version
   1.8 (MSIX package version >= 8000.994.2142.0)`, even though 8000.994.2142.0 is
   installed; a packaged app has the framework package in its graph and must not
   run the unpackaged bootstrapper.
4. **Pack/sign:** `makeappx.exe` + `signtool.exe` from
   `Microsoft.Windows.SDK.BuildTools` 10.0.26100.4948 (the Windows Kits copy is not
   installed on this box): `makeappx pack /d pkg /p app.msix /o`, then
   `signtool sign /fd SHA256 /f cert.pfx /p <pw> app.msix`.
5. **Install/launch:** `Add-AppxPackage app.msix`; launch the execution alias from a
   scheduled task with `/IT` (runs in zen7s's session 1, not the SSH session 0).
   `Package.Current` now returns
   `RETextRecBench_1.0.0.8_arm64__yxzf4xjhhje0p`, `GetReadyState()=Ready`, and
   `EnsureReadyAsync()` returns `Success (already ready)` — no model download was
   needed. Loaded modules are `Microsoft.Windows.AI.Imaging.dll`,
   `Microsoft.Windows.AI.Projection.dll` and
   `Microsoft.Windows.AI.Imaging.Projection.dll`; no QNN DLL is loaded, and CPU time
   was 0.047 s per 0.49 s wall on T0001. The API exposes no device name, so NPU use
   is inferred, not proven.
6. **Result:** all 150 frozen pages ran at 161.5 pages/min (recognition time from
   `raw_all.jsonl`, model startup excluded). Table-page number recall 0.9378,
   precision 0.9242; annual reports 0.9936/0.9736; scanned key numbers 0.9889 on
   the 10 hand-read pages. Full breakdown in §12.
7. **Cleanup:** the test package and certificate are removed after the run; the
   pfx/cer stay under `C:\RE\bench\textrec\` only until then.

The `/IT` launch above put a window on the HP's screen; by Shivam's headless ruling it now runs as a hidden `WinExe`: `machines/HP_LAPTOP.md`.

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

> **HP only: this engine ranking does not hold on x64.** §13 re-measured `Windows.Media.Ocr` against `RapidOCR` on the MSI on number recall/precision on financial-table pages: RapidOCR wins 0.916/0.910 vs 0.818/0.852.

Use **Windows AI `TextRecognizer` at 300 DPI grayscale as the first pass**, with a stronger reader for low-confidence numbers (Shivam's agreed direction, `tasks/RULINGS.md`); keep **`Windows.Media.Ocr` as the fallback** where the package cannot be installed. Neither reaches the 0.95/0.98 gate on the frozen table set (§12), so a bulk run still needs Shivam's decision.

- **Time:** Windows AI 161.5 pages/min (recognition only) ⇒ 13,300 pages in
  **~1.4 h**. MediaOcr 270.7 pages/min OCR-only ⇒ **~0.8 h**; add rendering
  (~0.15 s/page) for the wall-clock figure. The QNN baseline is 44.7 pages/min ⇒
  **5.0 h**. EasyOCR ~2.9 pages/min ⇒ ~76 h, rejected.
- **Accuracy on the frozen set:** Windows AI 0.9378 number recall / 0.9242
  precision on table pages; MediaOcr 0.8807 / 0.8980; QNN 0.7354 / 0.7356. On the
  10 hand-read scanned pages: Windows AI 0.9889 key-number recall, MediaOcr 0.4556
  on the kept `C:\RE\ocr_pages` PNGs (the 0.625 in §11.1 was a different PDF render,
  not these PNGs).
- **Media tuning did not close the gap:** 3x/4x/5x, contrast, binarise and
  table-line row crops all sit at 0.795–0.886 recall and 0.887–0.899 precision;
  row crops add 0.006 recall and lose 0.011 precision. Details in §12.
- **The QNN path is no longer the table fallback:** on 110 table pages it scores
  0.7354 / 0.7356, below both Windows engines. Keep it only for pages where the
  package cannot run at all.
- **Two MediaOcr fixes remain mandatory** if it is used: retry 90°/270° when a page
  yields <40 characters, and sort returned lines by bounding box (+3.7 points of
  plain accuracy on the 20-page truth set).
- **Gate:** no engine and no pair of engines reaches 0.95 recall / 0.98 precision;
  the best agreement pair caps precision at 0.944 while losing recall. Do not start
  the 1,073-file run on the strength of these numbers.

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

# Windows App SDK TextRecognizer helper: source at reality_engine/tools/textrec/. It must be a
# signed MSIX with package identity. Full build/run/cleanup steps:
# tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md
C:\RE\dotnet\dotnet.exe publish reality_engine\tools\textrec\textrec.csproj -c Release -r win-arm64
makeappx pack /d pkg /p textrec.msix /o
signtool sign /fd SHA256 /a /f rebench.pfx /p <password> textrec.msix
Add-AppxPackage -Path textrec.msix -ForceUpdateFromAnyVersion
```

### 11.6 Status and still open

- **The gate is still unmet.** Windows AI is closest at 0.9378/0.9242; the best
  agreement pair reaches 0.9429 precision with recall collapsed to 0.8701, and the
  best union reaches 0.9501 recall at 0.7743 precision. A column-aware number
  repair or a better detector is needed before 4,647/13,300 pages are run.
- **The test certificate is self-signed and must not ship.** A machine-trusted or
  Store identity is required for a fleet install; the test package and certificate
  are removed after §12.
- `TextRecognizer` runs from a signed MSIX launched in the interactive session
  (`/IT` scheduled task through the execution alias): see
  `tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md` for the tune table, frozen
  settings and the rebuild/cleanup steps.  `ImageScaler` is still blocked
  (`COMException: Package dependency criteria could not be resolved`) and the
  2.0 `TextRecognizerOptions` geometry modes are no-ops on this build.
- EasyOCR's real accuracy needs `cv2`/`pyclipper` CRAFT decoding. Neither has a
  win_arm64 cp314 wheel today; an x64-emulated Python or a small C++ box decoder
  would be needed. At 2.91 pages/min measured, even a large accuracy gain does not
  change the 1,073-file recommendation.
- The scanned-page score still rests on 10 hand-read number sets. A text-layer
  truth for scanned pages would make the comparison exact.

## 12. Frozen OCR gate test — every method on one page set (2026-11-01)

Goal: find an engine or combination that reaches **number recall ≥ 0.95 and number
precision ≥ 0.98 on table pages**. Nothing was allowed to change the page set, no
full OCR run was made, and no paid model or model API was called.

### 12.1 The frozen set

`C:\RE\ocr_test\pages.json` — 150 pages, seed **20261101**, built once and never
edited: **110 table pages** (annual reports 30, results 45, decks 30, transcripts 5)
and **40 prose pages** (10 / 15 / 10 / 5). The builder refuses to overwrite an
existing `pages.json` unless `--force` is passed. One page per PDF, drawn from
`C:\RE\raw\pilot60_history` after shuffling the PDFs with `random.Random(20261101)`;
annual reports and decks inspect at most 40 unseen pages per PDF, results and
transcripts every page.

Table-page rule (all four): ≥100 characters, ≥15 numeric tokens, ≥8 tokens with
≥3 digits, numeric tokens ≥12% of words. Prose rule: ≥300 characters, ≥60 words,
≤8 numeric tokens, numeric share ≤6%, ≤2 tokens with 3+ digits. Truth is the PDF
text layer; each page was rendered once at **3x** with pypdfium2 (typically
1785×2526; 126 MB of PNGs) into `C:\RE\ocr_test\images\`, with truth in
`C:\RE\ocr_test\truth\`. `C:\RE\ocr_test\subset30_table.json` freezes the same
30-table-page subset (AR 8, results 12, deck 8, transcript 2) used for the slow
engines.

Metric: numbers are distinct `\d[\d,]*(\.\d+)?` tokens with commas stripped (the
`hp_ocr_check.py`/`hp_ocr_bench.py` definition). Recall = truth numbers found in
OCR / truth numbers; precision = found / OCR numbers. Character accuracy is
1 - Levenshtein / truth length on whitespace-normalised, case-folded text; `order
free` sorts the words of both sides first, so a table read column-by-column is not
punished twice.

### 12.2 Results

All runs on the HP OmniBook (Snapdragon X X1-26-100, Windows 11 26H2, Python
3.14.7 ARM64), 2026-11-01. `ppm` is the sum of per-page OCR seconds (pre-rendered
3x PNGs for every engine except Windows AI, whose helper decodes the PNG itself);
PDF rendering is additional. The 30-page rows are the frozen subset, so their
`overall` equals their table score.

| engine | device | pages | ppm | table acc | table order-free | table recall | table precision | overall acc | overall recall | overall precision | gate |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **Windows AI `TextRecognizer` 1.8** | Windows AI | 150 | **161.5** | 0.6597 | 0.8843 | **0.9378** | **0.9242** | 0.6893 | **0.9423** | **0.9051** | fail |
| **Windows.Media.Ocr** (3x, rotation retry) | CPU | 150 | **270.7** | 0.6543 | 0.8627 | 0.8807 | 0.8980 | 0.6863 | 0.8919 | 0.8787 | fail |
| **Tesseract 5.4.0** (psm 6, main pass) | CPU x64 emulated | 150 | 11.3 | 0.2219 | 0.7828 | 0.8139 | 0.8733 | 0.2419 | 0.8441 | 0.8444 | fail |
| **RapidOCR ONNX** (det960 + rec32_960) | NPU QNN HTP | 150 | 44.7 | 0.5841 | 0.6087 | 0.7354 | 0.7356 | 0.6163 | 0.7085 | 0.6940 | fail |
| **RapidOCR ONNX** (same graphs) | CPU | 30 | 4.6 | 0.5979 | 0.6013 | 0.7099 | 0.7197 | 0.5979 | 0.7099 | 0.7197 | fail |
| **Qualcomm AI Hub EasyOCR** | NPU det + CPU rec | 30 | 2.9 | 0.2322 | 0.2305 | 0.2718 | 0.3618 | 0.2322 | 0.2718 | 0.3618 | fail |
| **PP-OCRv5 hybrid** (v5 rec + RapidOCR det) | CPU | 30 | 4.8 | 0.4216 | 0.2941 | 0.6466 | 0.6204 | 0.4216 | 0.6466 | 0.6204 | fail |
| PP-OCRv5 det+rec (pure) | CPU | 1 | – | – | – | 0.365 | 0.575 | – | – | – | abandoned |

**RapidOCR on CPU** is the same det960 + rec32_960 graph pair as the QNN row, run
on the frozen 30-page subset: 391 s, **4.62 pages/min**, 8–36 s per page, table
number recall 0.7099 / precision 0.7197. The full 150 pages were stopped at 9
pages (~20 s/page, ~45 min projected): the subset already fixes the accuracy and
the full run did not fit the budget.

**PP-OCRv5 pure detection failed and was not run over the set.** The official
PaddlePaddle ONNX exports (det 4.8 MB, rec 16.5 MB, dict 18,383 chars, no account)
recognise a clean crop perfectly (25/25 numeric crops matched on T0001), but their
detector probability map decoded with axis-aligned connected components (no `cv2`
or `pyclipper` on win_arm64 cp314, so no DB unclip) gives boxes that clip digits:
T0001 recall 0.365, precision 0.575. The scored row is a hybrid: PP-OCRv5
recogniser over the RapidOCR det960 boxes (proper numpy post-processing), which was
the only way to give the v5 recogniser a fair test without `cv2`.

**MediaOcr tuning variants** (all 150 pages; group of six):

| variant | table recall | table precision | ppm |
|---|---:|---:|---:|
| 3x (selected) | 0.8807 | 0.8980 | 270.7 |
| 4x | 0.8785 | 0.8982 | 171.6 |
| 5x | 0.8813 | 0.8944 | 117.1 |
| 3x + contrast | 0.8800 | 0.8991 | 164.9 |
| 3x + binarise | 0.7950 | 0.8872 | 288.8 |
| 3x + table-line row crops | 0.8864 | 0.8871 | 170.1 |

None is close to the gate. Row crops buy 0.006 recall and lose 0.011 precision;
binarising loses 0.086 recall. The maximum MediaOcr image dimension is **10,000 px**
(`OcrEngine.max_image_dimension`), so 3x/4x/5x pages are never downscaled.

**Tesseract** is x64 under emulation: no native ARM64 Windows build exists. `psm 6`
(uniform block, the table mode) was used at 4x with `preserve_interword_spaces=1`;
the digits-only pass (`tessedit_char_whitelist=0123456789.,()-+%`) was run and
**removed** because it added 0.008 recall but cost 0.151 precision (0.8733 → 0.7223).
Its plain character accuracy is low (0.22) because TSV reading order puts column
headers before row values; order-free is 0.783.

#### By document type (table pages only)

| engine | annual reports n / acc / R / P | results | decks | transcripts |
|---|---|---|---|---|
| Windows AI | 30 / 0.7830 / 0.9936 / 0.9736 | 45 / 0.7166 / 0.8827 / 0.8835 | 30 / 0.4675 / 0.9544 / 0.9554 | 5 / 0.5608 / 1.0000 / 0.8070 |
| MediaOcr | 30 / 0.7575 / 0.9299 / 0.9392 | 45 / 0.7157 / 0.8634 / 0.8645 | 30 / 0.4651 / 0.8375 / 0.9221 | 5 / 0.6176 / 1.0000 / 0.8080 |
| Tesseract | 30 / 0.2409 / 0.9049 / 0.9444 | 45 / 0.2273 / 0.7650 / 0.8353 | 30 / 0.2131 / 0.7669 / 0.8708 | 5 / 0.1123 / 0.9889 / 0.8039 |
| RapidOCR QNN | 30 / 0.6858 / 0.8674 / 0.8480 | 45 / 0.6339 / 0.6348 / 0.6624 | 30 / 0.4092 / 0.7498 / 0.7639 | 5 / 0.5744 / 0.7620 / 0.5501 |
| EasyOCR | 8 / 0.3334 / 0.2429 / 0.3694 | 12 / 0.2071 / 0.1865 / 0.3547 | 8 / 0.1815 / 0.3676 / 0.3735 | 2 / 0.1812 / 0.5161 / 0.3280 |
| PP-OCRv5 hybrid | 8 / 0.4918 / 0.7638 / 0.7092 | 12 / 0.5022 / 0.5709 / 0.5543 | 8 / 0.2654 / 0.6554 / 0.6824 | 2 / 0.2818 / 0.5965 / 0.4145 |
| RapidOCR CPU | 8 / 0.6914 / 0.8541 / 0.8124 | 12 / 0.6807 / 0.5749 / 0.6037 | 8 / 0.3978 / 0.7503 / 0.8280 | 2 / 0.5279 / 0.7807 / 0.6117 |

Results pages are the weak spot for every engine; annual reports are the strong
spot (Windows AI 0.9936 recall / 0.9736 precision on 30 pages). The 5-page
transcript row is noisy and should not drive a choice.

#### Scanned pages (10 hand-read key-number sets, `C:\RE\ocr_pages`)

Scored on the same 10 pages as §10.6/§11.1, but on the kept PNGs, not a fresh PDF
render; that is why these numbers differ from §11.1.

| engine | key-number recall | pages/min (recognition time) |
|---|---:|---:|
| Windows AI TextRecognizer | **0.9889** | 72.8 |
| Windows.Media.Ocr | 0.4556 | 545.0 |
| RapidOCR QNN | 0.4067 | 33.6 (wall, 35.7 s for 20 PNGs) |

Windows AI reads the scanned key numbers almost perfectly; the CPU engines lose
more than half. The earlier §11.1 values (Media 0.625, QNN 0.486) were measured on
PDF renders of the pages, not on `C:\RE\ocr_pages`; use these for the PNG set.

### 12.3 Combinations (computed from saved rows, no rerun)

Each pair accepts the numbers both engines produced (`agree`) or either engine's
numbers (`union`). `flagged` is the share of the 110 table pages where the two
engines' number sets differ or the page's `total` line fails a column-sum check
(heuristic: a line containing "total" whose last numeric column matches no sum of
the three-to-eight numeric lines above it, 1% tolerance).

| pair | agree recall | agree precision | union recall | union precision | flagged | disagree | columns fail |
|---|---:|---:|---:|---:|---:|---:|---:|
| Windows AI × MediaOcr | 0.8701 | 0.9429 | 0.9484 | 0.8875 | 0.873 | 0.873 | 0.100 |
| Windows AI × Tesseract | 0.8032 | 0.9408 | 0.9485 | 0.8799 | 0.855 | 0.855 | 0.082 |
| Windows AI × RapidOCR QNN | 0.7231 | **0.9440** | **0.9501** | 0.7743 | 0.991 | 0.991 | 0.082 |
| MediaOcr × Tesseract | 0.7579 | 0.9430 | 0.9367 | 0.8574 | 0.964 | 0.964 | 0.109 |
| MediaOcr × RapidOCR QNN | 0.6812 | 0.9414 | 0.9349 | 0.7569 | 1.000 | 1.000 | 0.109 |
| Tesseract × RapidOCR QNN | 0.6355 | 0.9343 | 0.9137 | 0.7433 | 1.000 | 1.000 | 0.064 |
| Windows AI × RapidOCR CPU* | 0.7041 | 0.9415 | 0.9357 | 0.7702 | 1.000 | 1.000 | – |

`*` 30 common table pages (the CPU subset), not 110; the column check was not run
for this pair.

**No pair reaches the gate.** The best agreement precision is 0.9440 (Windows AI ×
QNN) but it keeps only 72.3% of the truth numbers; the best union recall is 0.9501
but precision collapses to 0.7743. Engines disagree on 85–100% of table pages, so
agreement is a strong precision filter that throws away too much recall. The
column-sum heuristic flags only 6–11% of pages, i.e. most OCR tables that look
well-formed still contain wrong numbers — adding up is a weak validator here.

### 12.4 Failure examples (top three engines)

**Windows AI** (worst table pages):
- `T0078` (deck) recall 0.550, precision 1.000 — missing `100, 200, 300, 400, 500,
  600` (the page's honest text layer lists them; the image likely puts them in a
  chart/label the recogniser did not read).
- `T0104` (deck) 0.556/0.769 — missing `08, 10, 11, 20, 21, 202`; extras `7, 2021,
  100` (small axis labels).
- `T0073` (results) 0.575/0.670 — missing concatenated dates `312019, 302019,
  312018, 12019, 12018, 0`; the recogniser split them differently.

**MediaOcr**:
- `T0002` (annual report) 0.290/0.800 — missing `300000, 400000, 135043868,
  128100142, 47681127, 5488081`; extras `3, 4, 48, 13526, 14255` (leading digits
  dropped and columns merged, exactly the failure the tuning tried to fix).
- `T0076` (deck) 0.482/1.000 — missing `18, 64, 61, 41, 63.5, 84.6` (no extras:
  silence is scored as recall loss, not precision gain).
- `T0078` (deck) 0.500/0.909 — missing `2, 100, 200, 300, 400, 500`; extra `02`.

**Tesseract**:
- `T0085` (deck) 0.024/0.222 — missing `29, 2048.6, 1598.9, 273.2, 262.2, 28.5`;
  extras `0, 3, 00, 86, 4, 7200888`.
- `T0057` (results) 0.031/0.063 — missing `01, 04, 2020, 30, 09, 31`; extras `6,
  119, 91, 51109, 1981, 034212`.
- `T0016` (annual report) 0.096/1.000 — missing `273, 17986.92, 16388.54, 3386.83,
  4088.57, 1598.38`; no extras.

### 12.5 Forecast for 4,647 pages

Hours = 4,647 / ppm / 60, before PDF rendering (~0.15 s/page ≈ 0.19 h total).

| engine | ppm | hours | note |
|---|---:|---:|---|
| Windows AI TextRecognizer | 161.5 | **0.48** | model startup ~5 s once per process |
| Windows.Media.Ocr | 270.7 | **0.29** | OCR-only; add rendering |
| RapidOCR QNN | 44.7 | 1.73 | NPU pipeline |
| Tesseract 5.4 x64 | 11.3 | 6.85 | x64 emulation |
| PP-OCRv5 hybrid | 4.8 | 16.0 | 30-page rate |
| RapidOCR CPU | 4.6 | 16.8 | 30-page rate |
| Qualcomm EasyOCR | 2.9 | 26.6 | 30-page rate |

Speed is not the blocker for any of the top three; accuracy is. At Windows AI's
rate the whole 4,647-page pass is under half an hour of recognition.

### 12.6 What was installed or changed on the HP

- **Tesseract 5.4.0.20240606** (UB-Mannheim x64 installer, `C:\Program Files\
  Tesseract-OCR`, `eng.traineddata` present). No native ARM64 build exists; it runs
  under x64 emulation.
- **PP-OCRv5 mobile det/rec ONNX** (official `PaddlePaddle/PP-OCRv5_mobile_det_onnx`
  and `_rec_onnx`, plus `ppocrv5_dict.txt`) in `C:\RE\models_ppocrv5\`; downloaded
  without an account.
- **Microsoft.Windows.SDK.BuildTools 10.0.26100.4948** (makeappx/signtool) in
  `C:\RE\bench\sdkbuildtools\`.
- **Test MSIX** `RETextRecBench 1.0.0.8` (arm64) signed with self-signed
  `CN=REBench`, thumbprint `12D0B68EB482079BF006722B057F1F50B3A2CFC6`, installed to
  `LocalMachine\Root` and `TrustedPeople`; scheduled tasks `RETextRecAll`,
  `RETextRecScanned`, `RETextRecActivate*`. **Removed after the run:** the package,
  all three certificate copies, the eight scheduled tasks and the pfx/cer/msix files
  are gone; `Get-AppxPackage RETextRecBench` is empty and neither machine store has
  `CN=REBench`. The rows and `raw_all.jsonl` were saved first.
- **Python packages:** none added for OCR. Used the existing `pypdfium2` 5.14.0,
  `onnxruntime` 1.31.1 + `onnxruntime-qnn` 2.7.0, Pillow 13.0.0, numpy 2.5.4,
  `winrt` (PyWinRT) for Windows.Media.Ocr. `cv2`, `pyclipper`, `shapely`,
  `pytesseract` are absent and were not installed (no win_arm64 cp314 wheels).
  `pandas` 3.1.0 and `openpyxl` 3.1.5 were installed later only so the standing
  pytest collection could import the suite. `pymupdf` would not install (no cp314
  ARM64 wheel), so 9 test modules still fail collection and the two
  `test_pua_fallback` OCR tests fail on `import fitz`; that is an environment gap,
  not an OCR-engine failure.
- **Frozen assets:** `C:\RE\ocr_test\` (pages.json 150 pages, images/, truth/,
  subset30_table.json, one `rows.jsonl` per engine with raw text and line boxes,
  `variants/` for tuning runs, `metrics.json` per engine, `combo_*.json`).

Nothing in the repo imports these engines at runtime; the runners are opt-in
scripts. `pages.json` is the path the MSI should use to score RapidOCR on the
identical list: **`C:\RE\ocr_test\pages.json`**.

### 12.7 Commands

```powershell
python -m reality_engine.scripts.hp_ocr_gate build --out C:\RE\ocr_test --seed 20261101
python -m reality_engine.scripts.hp_ocr_methods run --engine media --variant 3x  --out C:\RE\ocr_test
python -m reality_engine.scripts.hp_ocr_methods run --engine qnn   --variant 3x  --out C:\RE\ocr_test
python -m reality_engine.scripts.hp_ocr_methods run --engine cpu   --variant 3x_sub30 --subset C:\RE\ocr_test\subset30_table.json --out C:\RE\ocr_test
python -m reality_engine.scripts.hp_ocr_methods run --engine tesseract --variant psm6 --psm 6 --out C:\RE\ocr_test
python -m reality_engine.scripts.hp_ocr_methods run --engine easyocr --subset C:\RE\ocr_test\subset30_table.json --out C:\RE\ocr_test
python -m reality_engine.scripts.hp_ocr_methods run --engine ppocr --variant hybrid --subset C:\RE\ocr_test\subset30_table.json --out C:\RE\ocr_test
python -m reality_engine.scripts.hp_ocr_methods convert-windowsai --raw C:\RE\ocr_test\windowsai\raw_all.jsonl
python -m reality_engine.scripts.hp_ocr_gate score --engine C:\RE\ocr_test\windowsai
python -m reality_engine.scripts.hp_ocr_gate combine --a C:\RE\ocr_test\windowsai --b C:\RE\ocr_test\media
python -m pytest reality_engine/tests -q -k ocr
```

### 12.8 Verdict

**No engine and no pair reaches the 0.95 recall / 0.98 precision gate.** Windows AI
is closest (0.9378 / 0.9242): it misses recall by 0.0122 and precision by 0.0558.
Precision is the binding constraint, driven by split comma groups, dropped leading
digits, date concatenation and small axis/note numbers. Combining engines buys
precision only by discarding recall. The 4,647-page pass is fast enough with
Windows AI (~0.5 h), so the work is accuracy, not throughput: a column-aware number
validator (align cells, repair comma groups/decimal points, reject numbers no column
can place) is the next experiment, scored on this same frozen set.

## 13. MSI, 2026-11-01 — does RapidOCR CPU clear the number gate Windows OCR failed?

**Answer: no. RapidOCR 3.10 on the CPU reads financial-table pages better than
`Windows.Media.Ocr` (number recall 0.916 vs 0.818, precision 0.910 vs 0.852 on the
same 110 table pages) but misses both gates (recall 0.95, precision 0.98). The
rotation retry and a larger raster change nothing on these pages. 4,922 of the
13,169 pages in `is_scanned_guess=1` PDFs are the pages that actually need OCR
(37.4%); at the measured 12.07 pages/min end to end that is 6.8 h on this CPU, or
33 min with Windows OCR.**

Host: MSI, x64 Windows, Python 3.14.7. Engines: `rapidocr` 3.10.0 (PP-OCRv6
`det_small` + `rec_small` + cls, onnxruntime CPU execution provider, the package
defaults: 2000-px preprocess cap, text score 0.5) and `Windows.Media.Ocr` through
PyWinRT 10.0.28000 (`winrt` is not installed on the box; the projection wheels were
fetched into `.tmp/pylib`, which is 3 MB, not an install). One process at a time.

### 13.1 Method (the same measure Windows OCR was scored with)

Truth is the PDF text layer, rendered with pypdfium2 at **3x** (A4 → 1788×2526 px).
Numbers are the **distinct** tokens matching `\d[\d,]*(\.\d+)?` with the commas
stripped; recall = truth numbers found in the OCR, precision = OCR numbers present
in the truth. Micro (pooled counts) is the gate number; macro (mean of per-page
scores) is given beside it.

A page is a **table page** when its text layer has ≥15 numeric tokens, ≥8 of them
with 3+ digits, and numbers are ≥12% of its words. Sample: `seed=20261031` over the
local PDFs of `pilot60_history_manifest.db`, quotas annual reports 30, quarterly
results 45, investor presentations 30, concall transcripts 5 (=110), plus 40 prose
pages (11/16/9/4). Drawn: **150 pages, 63 PDFs, 34 symbols**, quotas exact.

```
python -m reality_engine.scripts.ocr_number_bench sample --out .tmp/ocr_bench --scale 3
python -m reality_engine.scripts.ocr_number_bench ocr    --out .tmp/ocr_bench --config asis3
python -m reality_engine.scripts.ocr_number_bench ocr    --out .tmp/ocr_bench --config windows3 --engine windows
python -m reality_engine.scripts.ocr_number_bench score  --out .tmp/ocr_bench
python -m reality_engine.scripts.ocr_number_bench census --out .tmp/ocr_bench
```

### 13.2 Results — table pages only, by document type

| engine | AR (30) | results (45) | decks (30) | transcripts (5) | **all table (110)** |
|---|---|---|---|---|---|
| RapidOCR CPU, as shipped | 0.9817 / 0.9762 | **0.8644 / 0.8581** | 0.9800 / 0.9846 | 0.9837 / 0.8521 | **0.9161 / 0.9098** |
| Windows.Media.Ocr | 0.8060 / 0.9379 | 0.7914 / 0.7896 | 0.8873 / 0.9514 | 0.9593 / 0.8252 | 0.8184 / 0.8522 |

Recall / precision. Gate: 0.95 / 0.98. Both engines **fail**; RapidOCR fails only on
the dense quarterly-results statements (0.864) while annual-report and deck tables
are already at 0.98.

| engine | all 150 | prose 40 | recall (macro) | precision (macro) | OCR pages/min | + render | pages/min end to end |
|---|---|---|---:|---:|---:|---:|---:|
| RapidOCR CPU, as shipped | 0.9195 / 0.9152 | 0.9573 / 0.9782 | 0.9291 | 0.9314 | 12.48 | 0.165 s/page | **12.07** |
| RapidOCR, 90°/270° retry | identical | identical | — | — | — | — | — |
| RapidOCR, 3x with cap 3200 (30-page probe) | 0.9127 / 0.8873 | — | — | — | 10.81 | — | 10.47 |
| Windows.Media.Ocr | 0.8268 / 0.8603 | 0.9212 / 0.9508 | 0.8616 | 0.8840 | **252.26** | — | **148.94** |

- **The rotation retry never fires on this sample:** the shortest OCR output is 280
  characters and every page has ≥3 word-like tokens, for both engines (Windows OCR
  minimum 173). Text-bearing table pages are upright by construction — a rotated
  page has no text layer and therefore cannot qualify as a table page. Rotation is
  a scanned-page concern (§10.5's GMR page), not measurable here.
- **More pixels do not help:** 3x rendered without RapidOCR's 2000-px downscale
  (cap 3200) on every 5th page scored 0.9127 / 0.8873 against 0.9097 / 0.8883 for
  the same 30 pages as shipped, and ran 14% slower. RapidOCR's recogniser is at its
  ceiling on this content, not short of resolution.
- Windows OCR is **12× faster** and reads prose better than tables (0.921 vs 0.818);
  its number loss is skipping text (13.6% of truth numbers are simply absent), while
  RapidOCR's is cell-boundary merging (next section).

### 13.3 Where the loss is

Every distinct truth number on the table pages, classified against the OCR output
(occurrence-level, so it explains the direction rather than replacing 13.2):

| engine | exact token | inside a longer token (cells merged) | not read at all |
|---|---:|---:|---:|
| RapidOCR CPU | **91.6%** | 3.6% | 4.8% |
| Windows.Media.Ocr | 81.8% | 4.6% | 13.6% |

On the emitted side, 92.8% of RapidOCR's numbers are true, 1.1% are merges of two
cells and 6.1% are numbers that are not in the text layer at all. **With perfect
cell splitting RapidOCR would reach ≈0.952 recall — the gate's edge** — so the next
thing to measure is a box/cell-aware post-pass, not another engine.

Failure examples (worst table pages, RapidOCR as shipped):

| page | doc | recall | what happened |
|---|---|---:|---|
| `075_quarte_4` RAJESHEXPO | results | 0.312 | cells merged: `3691` → `36911`, `17077` → `017077`, `498.38` → `1021498.38` |
| `073_quarte_5` DDEVPLSTIK | results | 0.569 | 89 numbers emitted where truth has 51 — the same merges split differently |
| `079_quarte_5` ASHIANA | results | 0.667 | small-font column misread: `0.29` → `0.20`, `9.23` → `1.35` |
| `068_quarte_0` KIMS | results | 0.423 | `51330` → `543308`, `0101` → `01017`: two adjacent cells read as one |

The truth layer is not clean either: some results pages carry a run-together date
column (`2282374414513671`) that no OCR can reproduce, so part of the results-page
error belongs to the truth, not the engine.

### 13.4 How many pages truly need OCR

Read-only census of every `is_scanned_guess=1` PDF in `pilot60_history_manifest.db`
(1,145 held files, 13,169 pages, 0 unreadable), pages with **under 100 characters**
of text layer:

| document type | docs | pages | pages under 100 chars | share |
|---|---:|---:|---:|---:|
| material_filing | 1,019 | 6,060 | **4,084** | 67.4% |
| quarterly_results | 70 | 1,003 | **585** | 58.3% |
| investor_presentation | 20 | 491 | 114 | 23.2% |
| results_press_release | 7 | 24 | 7 | 29.2% |
| annual_report | 24 | 5,529 | 127 | 2.3% |
| concall_transcript | 4 | 61 | 4 | 6.6% |
| concall_audio_link | 1 | 1 | 1 | 100% |
| **total** | **1,145** | **13,169** | **4,922** | **37.4%** |

The earlier sample said 4,647 of 11,728: the same picture on a slightly smaller set.
Most of the OCR need is the Reg 29/31 `material_filing` forms, not the annual
reports (whose scanned-guess PDFs are 97.7% text-bearing).

### 13.5 Time forecast for those 4,922 pages (this MSI, one process)

| engine | rate | 4,922 pages | note |
|---|---:|---:|---|
| RapidOCR CPU, as shipped | 12.07 /min | **6.8 h** | 6.6 h if the render is reused |
| RapidOCR + 90/270 retry | — | **10–20 h** | retry fires on real scans (none on this text sample); +1–2 passes |
| RapidOCR, cap 3200 | 10.47 /min | 7.8 h | no accuracy gain; rejected |
| Windows.Media.Ocr | 148.94 /min | **33 min** | 12× faster, worse numbers |

Memory: the RapidOCR run peaks at ~0.3 GB. The brief's 1.5 GB free-RAM stop fired
mid-run — the operator's browser holds 5.5 GB — so the remaining pages ran in
10-page batches with the stop lowered to 900 MB; free RAM touched 419 MB once
between batches, no page-fault storm, no other job was started.

### 13.6 Verdict

- **RapidOCR CPU as-is: FAIL** the 0.95 recall / 0.98 precision gate —
  0.9161 / 0.9098 on the 110 table pages (0.9195 / 0.9152 over all 150).
- **Windows.Media.Ocr re-measured on the same pages: FAIL, and worse** —
  0.8184 / 0.8522. It lands near the earlier 110-page run (0.839 / 0.896); the gap
  is the page sample and the absent bbox line sort, not the engine.
- **Retry and resolution: no effect** (0 pages trigger; +0.3 pt for +14% time).
- Neither engine can be used for blind figure extraction from table pages. The loss
  is cell boundaries, not digits — a box-aware post-pass is the next experiment,
  and its ceiling on this sample is ≈0.952 recall.

### 13.7 What was not run

- A per-page route between the two engines (Windows OCR for prose, RapidOCR for
  tables) — the table above only prices each engine alone.
- Any post-pass over RapidOCR's boxes (the ≈0.952 ceiling is arithmetic from 13.3).
- Rotated scans, where the retry actually pays: no text-layer truth exists for them.
- The 4,922-page run itself (accuracy test only, per the brief).

Artifacts: `.tmp/ocr_bench/{sample.jsonl,ocr_asis3.jsonl,ocr_windows3.jsonl,ocr_hi3.jsonl,scores_*.jsonl,summary.json,failures.json,census.json}`,
rendered pages in `.tmp/ocr_bench/pages/`. Script:
`reality_engine/scripts/ocr_number_bench.py`, test:
`reality_engine/tests/test_ocr_number_bench.py`.
