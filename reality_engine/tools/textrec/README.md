# TextRecognizer helper (Windows AI Imaging)

Source of the batch runner used by the large OCR accuracy test on the HP
OmniBook.  The engine is `Microsoft.Windows.AI.Imaging.TextRecognizer`; it only
answers from a **packaged, signed** process with package identity and the
`systemAIModels` capability, launched in the interactive user session.

## Headless rule (Shivam's ruling, 1 Nov 2026)

**No HP work may come onto the screen.**  Nothing may show a window or take
focus.  The helper is therefore built as a **GUI-subsystem `WinExe`** (both
csproj files), so it can never own a console window, and the driver refuses to
launch it in the interactive session unless the *installed package's* PE header
says subsystem **2 (GUI)**.

With no console there is nowhere to print, so:

| what it used to print | where it goes now |
|---|---|
| startup, identity, ready state, scaler, modules | `%LOCALAPPDATA%\RETextRecBench\status.log` |
| one progress line per image | `status.log` (the same line the console used to get) |
| the batch totals | `<out>.done` (`rows`, `errors`, `error`, `seconds`, `ready_state`, `modules`, `scale`, `scaler`, `options`) |
| a fatal failure | `status.log` + `<out>.done` with `error`, and a **nonzero exit code** (Task Scheduler's `LastTaskResult`) |
| a per-image failure | an `error` field on that JSON row, counted in `.done.errors` |

`<out>.done` is written on **every** exit path, including a usage error and an
unhandled exception, so a driver never waits for a sentinel that will not come.

The driver (`reality_engine/scripts/hp_ocr_large.py`) reads only the JSONL rows
and `.done`: `wait_done()` raises when `.done` carries `error`, and a timeout
reports the task's `LastTaskResult` plus the tail of `status.log`.

## Files

| file | purpose |
|---|---|
| `Program.cs` | manifest in, one JSON row per PNG out (text, lines, line style, words with `MatchConfidence`, `TextAngle`, timings, box extent) |
| `textrec.csproj` | baseline build on Windows App SDK 1.8.260921001, `OutputType=WinExe` |
| `experimental/textrec20.csproj` | separate build on Windows App SDK 2.0.0-experimental7, defines `TEXTREG_OPTIONS` to exercise `TextRecognizerOptions`, `OutputType=WinExe` |
| `pkg/AppxManifest.xml` | 1.8 package manifest (identity, `runFullTrust`, `systemAIModels`, execution alias) |
| `probe/probe.csproj`, `probe/HeadlessProbe.cs` | windowless evidence probe (`WinExe`, session 1): foreground window and every `WS_VISIBLE` top-level window owned by `textrec`/`conhost`/`cmd`/`powershell`/`pwsh`/`python`, plus the session process table, every 100 ms |
| `probe/summarise.py` | turns a probe log into the acceptance counts (samples, max gap, watched windows, focus changes, conhost/children); process names are matched without their `.exe`, so `conhost.exe` cannot slip through |

No binaries, certificates or keys live in the repo.  Build output, the signing
certificate and the test MSIX stay outside it.  Rebuild steps (plus the
experimental manifest override) are in
`tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md`.

Manifest line format: a PNG path, or `{"id": "...", "path": "..."}`.  The
driver writes one JSON row per line, and `<out>.done` when the batch ends.

`reality_engine/tests/test_hp_headless.py` enforces the rule without the HP or a
build: every csproj under this folder must be `WinExe`, the driver's PE guard
must reject a console EXE, and HP launcher code may create an interactive task
only in `hp_ocr_large.interactive_task_script()`, which applies the hidden
settings.
