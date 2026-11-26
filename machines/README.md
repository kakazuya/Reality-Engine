# Machines: how to operate the computers

This folder is about running the machines, not about the Reality Engine itself. Put new setup, access and operating notes here. Live work status stays in `tasks/STATE.md`.

**hy4 reading loops, remote control (26 Nov 2026, Eagle; for after the move, over Tailscale/SSH):**
`pwsh -File reality_engine/scripts/hy4_ctl.ps1 status|start|stop|adopt [transcripts|ar]`.
- Two loops:
  - `transcripts`: `.tmp/hy4_always.sh`, log `D:/RealityEngine/hy4_out/hy4_lowssd.log`;
  - `ar`: `.tmp/hy4_ar.sh`, log `hy4_ar.log`.
- Git bash re-launches itself (`exec bash "$0"`, `$(...)` subshells) as new Windows processes, so one recorded PID
  never covers a loop. Every action therefore finds the loop's processes by their exact command line: bash running
  the loop script, and python readers whose `--out` is one of the loop's DBs. It then acts on those PIDs only, never
  on processes picked by image name. (On 25 Nov a kill-by-name ended every worker and MCP server.)
- The `bash -lc '... exec bash <script>'` start wrapper stays behind as an idle stub after the loop re-launches
  itself. It is not counted as a loop instance, but `stop` ends it too. A reader is matched only by its `--out`
  file name, so a recheck that names the DB in `--baseline` is never touched (26 Nov).
- `status` lists each loop instance and reader PID, and prints `DUPLICATE` when two instances run. On 26 Nov three
  transcript loops were found, two writing `obs_transcripts_394_v3.db` at once.
- `start` refuses while any instance runs, launches the loop hidden, and records its PID in
  `D:/RealityEngine/hy4_out/<loop>.pid`.
- `stop` ends every matched instance and reader by PID, re-checks, and lists any survivors.
- `adopt` records the PID of a loop that was started without the script.
- To hold one job for a store swap without stopping reading, create `D:/RealityEngine/hy4_out/<db>.hold`. The
  transcript loop then skips that job; delete the file to resume. This only works in `.tmp/hy4_always.sh`, since 26 Nov.
- A loop at an ungraded checkpoint keeps running and rechecks every 10 minutes; it never exits.

| File | What it covers |
|---|---|
| `HP_LAPTOP.md` | HP OmniBook: access, starting jobs, the headless rule, the TextRecognizer package |
| `MSI_LAPTOP.md` | MSI laptop: what runs there, workers, hardware limits |
| `REMOTE_ACCESS_SETUP.md` | Setting up SSH and RDP on a new machine, and known traps |
| `HP_ACCEL_BENCH_2026-10-31.md` | HP accelerator speed tests |

Rule: passwords, keys and certificates never go in these files.
