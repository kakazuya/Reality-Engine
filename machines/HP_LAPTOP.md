# HP laptop

HP OmniBook 5, Windows 11 on ARM64, Snapdragon X with 8 cores, 16 GB. Shivam may be using it, and access was agreed through Monday morning, 2 Nov 2026.

## Headless rule (Shivam, 1 Nov 2026)
**No work may come onto this laptop's screen or take focus.** Prefer session 0, meaning SSH or a non-interactive task. An API that needs the interactive session gets a `WinExe` program launched hidden. Fix: job `hp-20261101T172002-15e0f2`. Proof on an unlocked desktop passed on 1 Nov: `tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md` section 14.7.

Screensaver and lock: it locks after 180 idle seconds, and a playing video did not stop that at 18:15. To read the lock over SSH, use `WTSQuerySessionInformationW` class 25 for the console session: the `SessionFlags` Int32 at byte offset 16 is 0 locked, 1 unlocked. `LockApp.exe` runs either way, so it proves nothing.

## Access
- `ssh zen7s@100.78.87.112` (Tailscale, `sumit-hp`) or `zen7s@192.168.1.42` (LAN), using key `~/.ssh/id_ed25519`.
- The default SSH shell is cmd. Inline PowerShell quoting breaks, so use `powershell -NoProfile -EncodedCommand` or copy a `.ps1` over.
- If SSH times out after a Wi-Fi change, check that the network is set to Private. On 31 Oct both routes came back after that.

## Starting work
- `start_worker(host="hp", permission="danger-full-access", hard_timeout_seconds=N, ...)`. `permission` is required; a start without it is refused as `permission_required`, not defaulted to read-only. Without a timeout it stops at 1,800 s. Uses Go account 1 by default.
- Up to 5 workers, with at least 3 GB free. `dbs` takes bare file names and copies them read-only for the job.
- Results: `python -m reality_engine.scripts.hp_worker fetch-patch <job>` gives branch `dsh-hp/<job>`.
- `worker_status` re-checks a stale local record once by reading the remote `job.log`/`exit.txt` and fetching `result.md`; `worker_result` re-fetches a final result that an ssh timeout left missing. If a job still shows `running`, check `C:\RE\jobs\<job>\job.log` on the HP for `rc=`. Logic: `reality_engine/scripts/hp_worker.py` and `plugins/dsh-worker/server/core.py`.
- `message_worker` returns `not_supported_on_hp` for HP jobs: they have no control channel, so a running HP worker cannot be steered.

## Layout
`C:\RE\repo` code snapshot; `C:\RE\jobs\<job>` job runs; `C:\RE\raw\pilot60_history` raw PDFs; `C:\RE\ocr_large` OCR test. The MSI is the source of truth; the HP is disposable. Never copy `D:\Shivam_Private\Manual Dumps` here. Do not share SQLite over the network.

## Python and tools
ARM64 Python at `%LOCALAPPDATA%\Programs\Python\Python314-arm64\python.exe`. .NET 8 at `C:\RE\dotnet`. `makeappx` and `signtool` under `C:\RE\bench\sdkbuildtools`. `pymupdf` is not installed, so tests needing `fitz` fail here.

## TextRecognizer package
It works only from a signed MSIX with package identity, in the interactive session. Calling it unpackaged gives `E_ACCESSDENIED`. Source: `reality_engine/tools/textrec/` (on branch `dsh-hp/hp-20261101T140451-175638`, not merged). Build steps are in `tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md` on that branch. The package and test certificate are removed after each test. OCR results: `tasks/ocr/OCR_ON_HP_FINDINGS_2026-11-01.md`.

## Measured speed
Against the MSI on 31 Oct, in a short test while the MSI was busy: 1.6x single-core, 3.3x all-core, 1.6x SQLite and disk. Transfer about 9 to 10 MB/s. A job can hold about 9 GB.
