# Machines: how to operate the computers

This folder is about running the machines, not about the Reality Engine itself. Put new setup, access and operating notes here. Live work status stays in `tasks/STATE.md`.

**hy4 reading loops, remote control (26 Nov 2026, Eagle; for after the move, over Tailscale/SSH):**
`pwsh -File reality_engine/scripts/hy4_ctl.ps1 status|start|stop|adopt [transcripts|ar]`.
- Two loops:
  - `transcripts`: `.tmp/hy4_always.sh`, log `D:/RealityEngine/hy4_out/hy4_lowssd.log`;
  - `ar`: `.tmp/hy4_ar.sh`, log `hy4_ar.log`.
- `start` launches the loop hidden and records its bash PID in `D:/RealityEngine/hy4_out/<loop>.pid`.
- `stop` ends ONLY that recorded PID and its child tree, never processes picked by image name. On 25 Nov a kill-by-name
  ended every worker and MCP server.
- `adopt` records the PID of a loop that was started without the script.
- A loop at an ungraded checkpoint keeps running and rechecks every 10 minutes; it never exits.

| File | What it covers |
|---|---|
| `HP_LAPTOP.md` | HP OmniBook: access, starting jobs, the headless rule, the TextRecognizer package |
| `MSI_LAPTOP.md` | MSI laptop: what runs there, workers, hardware limits |
| `REMOTE_ACCESS_SETUP.md` | Setting up SSH and RDP on a new machine, and known traps |
| `HP_ACCEL_BENCH_2026-10-31.md` | HP accelerator speed tests |

Rule: passwords, keys and certificates never go in these files.
