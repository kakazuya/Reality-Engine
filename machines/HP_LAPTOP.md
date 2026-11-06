# HP laptop

HP OmniBook 5, Windows 11 on ARM64, Snapdragon X with 8 cores, 16 GB. Shivam may be using it, and access is agreed until 15 Nov 2026 (Shivam, 2 Nov).

## Headless rule (Shivam, 1 Nov 2026)
**No work may come onto this laptop's screen or take focus.** Prefer session 0, meaning SSH or a non-interactive task. An API that needs the interactive session gets a `WinExe` program launched hidden. Fix: job `hp-20261101T172002-15e0f2`. Proof on an unlocked desktop passed on 1 Nov: `tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md` section 14.7.

Screensaver and lock: it locks after 180 idle seconds, and a playing video did not stop that at 18:15. To read the lock over SSH, use `WTSQuerySessionInformationW` class 25 for the console session: the `SessionFlags` Int32 at byte offset 16 is 0 locked, 1 unlocked. `LockApp.exe` runs either way, so it proves nothing.

## Access
- `ssh zen7s@100.78.87.112` (Tailscale, `sumit-hp`) or `zen7s@192.168.1.42` (LAN), using key `~/.ssh/id_ed25519`.
- The default SSH shell is cmd. Inline PowerShell quoting breaks, so use `powershell -NoProfile -EncodedCommand` or copy a `.ps1` over.
- If SSH times out after a Wi-Fi change, check that the network is set to Private. On 31 Oct both routes came back after that.

## Starting work
- `start_worker(host="hp", permission="danger-full-access", hard_timeout_seconds=N, ...)`. `permission` is required; a start without it is refused as `permission_required`, not defaulted to read-only. Without a timeout it stops at 1,800 s. Uses Go account 2 by default (key 1 hit 99% of its limit, Shivam 6 Nov; T-097).
- Up to 5 workers, with at least 3 GB free. `dbs` takes bare file names and copies them read-only for the job.
- `hp_worker start ... --pilot-db <path>` (T-070) copies one profile database from anywhere on this laptop (`D:\RealityEngine\pilot10\pilot10.db`) to `C:\RE\data\<basename>` with the same staging and `.meta.json` rule as `dbs`, and sets `REALITY_PILOT3_DB` for the job's `reality-data` server, so the HP serves the 10-company build. A missing path is refused before the job record is written; without the flag the MCP patch is unchanged.
- Results: `python -m reality_engine.scripts.hp_worker fetch-patch <job>` gives branch `dsh-hp/<job>`.
- `worker_status` re-checks a stale local record once by reading the remote `job.log`/`exit.txt` and fetching `result.md`; `worker_result` re-fetches a final result that an ssh timeout left missing. If a job still shows `running`, check `C:\RE\jobs\<job>\job.log` on the HP for `rc=`. Logic: `reality_engine/scripts/hp_worker.py` and `plugins/dsh-worker/server/core.py`.
- `message_worker` returns `not_supported_on_hp` for HP jobs: they have no control channel, so a running HP worker cannot be steered.

## Layout
`C:\RE\repo` code snapshot; `C:\RE\jobs\<job>` job runs; `C:\RE\raw\pilot60_history` raw PDFs; `C:\RE\ocr_large` OCR test. The MSI is the source of truth; the HP is disposable. Never copy `D:\Shivam_Private\Manual Dumps` here. Do not share SQLite over the network.

## Python and tools
ARM64 Python at `%LOCALAPPDATA%\Programs\Python\Python314-arm64\python.exe`. .NET 8 at `C:\RE\dotnet`. `makeappx` and `signtool` under `C:\RE\bench\sdkbuildtools`. `pymupdf` is not installed, so tests needing `fitz` fail here.

## TextRecognizer package
It works only from a signed MSIX with package identity, in the interactive session. Calling it unpackaged gives `E_ACCESSDENIED`. Source: `reality_engine/tools/textrec/`. Build steps: `tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md`. Remove the package and the test certificate after each use: the 2 Nov cleanup left the 1.0.1.0 package installed (certificate already gone), and the 3 Nov pilot3 run removed it. OCR results: `tasks/ocr/OCR_ON_HP_FINDINGS_2026-11-01.md`.

## Pilot page OCR
`tasks/pilot60/proto3_text/thin_pages.py` runs on the MSI: it sends every PDF of the 3 companies and a plan of every page to `C:\RE\raw\proto3_docs`, marking pages under 400 characters on the PDF page as thin. `tasks/pilot60/proto3_text/hp_ocr_pages.py <name>` runs on the HP from a job folder and writes `ocr_pages.jsonl.gz` at 300 DPI grayscale, in resumable batches of 200; numbers under 0.9 confidence go in `low_conf_numbers`. `reality_engine/scripts/hp_ocr_large.py` re-runs a failed image twice, and one that still fails keeps a row with its error. Fetch that file to `tasks/pilot60/proto3_text/`, where extraction reads it. `tasks/pilot60/proto3_text/kec_fetch.py --save` is the KEC transcript fetch, on the MSI, to `D:\RealityEngine\raw\kec_transcripts`; `--pair` writes `_known_at.json`, taking known_at from each filed cover letter. The site's publish dates are wrong for at least two quarters, so never use them.

**pilot3 page OCR (T-052).** `reality_engine/pilot3/hp_ocr.py` runs on the MSI and drives the HP with the same TextRecognizer package: `plan` reads the MSI `ocr_page` rows (`D:\RealityEngine\pilot3\ocr\ocr_<SYM>.db`), adds the pages `ocr.pending()` still lists, resolves each PDF as `pending()` does and copies only those PDFs to `C:\RE\raw\pilot3_ocr\pdfs\<sha[:2]>\<sha>.pdf`; `run` refuses while the console session is locked, copies the drivers, starts them as the hidden S4U task `Pilot3OCR` in session 0 (the helper it starts is the packaged hidden task) and waits; `fetch` writes `D:\RealityEngine\pilot3\ocr\ocr_textrec.db` (method `ocr_textrec`, word boxes in PDF points, `ocr_conf`, `low_conf_numbers`, error rows kept); `compare` writes `D:\RealityEngine\pilot3\ocr\OCR_COMPARE.html`; `cleanup` removes the package, certificate, tasks and copied PDFs. A page that will not render at 300 DPI (a 11520x8064 pt exhibit is 48,000x33,600 px), or still fails after two retries, keeps an error row. On 3 Nov this re-read the 1,453 pages the MSI had read (KEC 110, BAJFINANCE 354, HINDALCO 989) from 242 PDFs in 754 s (12.6 min): 1,429 pages with words and 24 error rows (23 engine `NullReferenceException`, plus one 11520x8064 pt HINDALCO page that cannot render at 300 DPI and failed on the MSI too). After the fetch it removed the package, both tasks and the copied PDFs (the test certificate was already absent).

## Measured speed
Against the MSI on 31 Oct, in a short test while the MSI was busy: 1.6x single-core, 3.3x all-core, 1.6x SQLite and disk. Transfer about 9 to 10 MB/s. A job can hold about 9 GB.
