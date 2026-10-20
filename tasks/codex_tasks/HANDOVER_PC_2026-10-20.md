# PC (perfect-machine, Hyderabad) hand-over to Codex — 2026-10-20 23:10 IST

From the PC Claude session (now advisor; Codex / GPT-6.1 Sol leads until Fri 2026-10-23 23:30 IST, Shivam).
The PC is reachable only from itself (no SSH server); the laptop reaches nothing on the PC except through Shivam/RDP
or a Claude session on the PC. Repo on GitHub `kakazuya/Reality-Engine` main is current (this file included).

## Commits since 49dff37c (all pushed)
- eea79d51 concall_deepseek: lane-level 429 handling. A 429 marks the model lane down; workers wait; exactly ONE call
  every 15 min (LANE_TAP_S=900); first answer reopens the lane; a 429 never spends a doc attempt or writes `error`.
  Docs with status `queued_429` are read first. Beam back at `--workers 6` (was 32).
- b7dbbb02 PC disk cleanup (below) + `scripts/cleanup_verify.py`.
- Earlier today: 1e7c5d1f heartbeat restart fix + DeepSeek off-peak window; 9f3c8b18 Drive upload cap 12 MB/s;
  91a41da9 boot smoke-check + background full quick_check; d326ca73 duckdb in requirements.

## Running on the PC now (23:05)
| Job | State | Log |
|---|---|---|
| Beam transcript reader (beam-free, shards 1,2,3/4, 6 workers) | upstream 429 since 11:52; tapping once per 15 min; ~10,687 docs queued (256 `queued_429` first) | data/logs/concall_beam-free.log |
| MiniMax reader (shard 0/4, 16 workers) | **RUN_COMPLETE 21:51**: ok 3,744, skip 662, error 24 (connection resets, never retried) | concall_minimax-m3.1-flash-free.log |
| Gemma re-embed (GPU, --duty 0.6) | 329,472 / 2,317,200 done, ~168 h left (AR tier) | reembed_gemma.log |
| Resource watchdog | alive (pid file) | resource_watchdog_report.md |
| PIB backfill | **log not written since 04:30 (power cut)** although boot recovery says it started it: check it is really alive | pib_backfill.log (at 2023-12) |
| Policy register | last log 19:33: check whether finished or died | policy_register_docs.log |

## Scheduled tasks on the PC (all S4U = run with nobody logged in)
- `RealityEngine-BootRecover` at startup + logon: readers at once, 0.3 s smoke-check of 6 DBs, writers, then a
  background low-priority full `PRAGMA quick_check` (`boot_recover --full-check`, result logs/db_full_check.json).
- `RealityEngine-EODMarket` weekdays 19:35: prices, deals, FII/DII, announcements, PIB, snapshot rebuild, query speed.
- `RealityEngine-DBBackup` daily 05:00: 7z of the 6 DBs to Drive `db_backups/<date>/`, uploads only 05:00-13:00.
  The 2026-10-19 set is complete on Drive (23 parts, MD5 ok) but state.json still says complete=false until the
  05:00 run re-checks it.
- `RealityEngine-DeepSeekHeartbeat` hourly: restarts dead Beam/MiniMax readers (no LLM), Sunday 02:00 starts the weekly
  full DB check, and off-peak runs one DeepSeek check -> hotline.md (+ needs_claude.md). Off-peak = NOT Mon-Fri
  06:30-09:30 / 11:30-15:30 IST; weekends all off-peak. Paid DeepSeek on Go account 2.
- Windows Search service is disabled (Shivam); workspace folders are NotContentIndexed.

## Open items in data/hotline/needs_claude.md (DeepSeek, 23:04) — decisions for the lead
1. Beam dead 11 h while MiniMax is idle (finished): DeepSeek proposes moving Beam's unread shards 1,2,3/4 to MiniMax
   (or a second MiniMax lane on the same Go keys). Shivam's last Beam rule: 6 workers + 15-min single tap.
2. MiniMax's 24 connection-reset docs were never retried (status error): requeue.
3. Garbled transcript text produces "faithful" junk rows: add a readability check before extraction
   (skip_unreadable_text or OCR route).
4. MiniMax 300 s/doc rule (decisions.md:73) is not enforced in concall_deepseek.py.
Older, unhandled: Beam broken-JSON 3.9-8.6% (04:29); "ok" docs with ~0 kept items (GULPOLY 36969, IPCALAB 44750,
SUKHJITS 83542, GSFC 36446): log items_kept/dropped, treat keep<10% as error.

## Data and Drive (gdrive: InfoDiffusion_archive/)
- On Drive, MD5-verified: pdfs, D_pdfs, decks, db_backups/2026-10-19 (6 DBs), snapshots/truth_2026-10-19.duckdb,
  embed_test, raw_market (46 .7z, one per subfolder), bhavcopy.7z, vector_index_nemotron8b, macro_pdfs, telegram_media.
- PC cleanup 21:20 (Shivam OK): 66,364 files / 384.8 GB deleted after MD5 match (ARs, offer docs, IPs, decks,
  D:\RealityEngine\pdfs, hard-link upload folders, truth_2026-10-08). Concall transcripts (20,479) stay on the PC.
  `corporate_documents.local_file_path` for deleted types now points at missing files: fetch from Drive.
- Not on Drive yet (Shivam asked 22:55, pending his yes): DB changes since 10-19 (next 05:00 backup), Gemma index
  (in progress, 7 GB+), Qwen-8B indexes (14 GB, paid Nebius), small data/ work dirs (~0.5 GB: inbox, parquet,
  reader_tests, concall_pilot, reports, tax_sources, hotline, dsh_tasks), logs + analysis (0.44 GB).
  Never upload: browser_profile (cookies), telegram_session.session, model weights.
- Gemma 4 transcript pilot 20:45 (10 docs, prompt v3): 17/20 calls Google HTTP 500, survivors kept ~30% of MiniMax's
  items -> no Gemma lane (data/concall_pilot/gemma_v3/).
- Laptop has: truth_2026-10-19.duckdb, 51 API key env vars, rclone.conf, OpenCode auth; NOT the Telegram session.

## Rules that bite (from today)
- Power: the PC's UPS does not hold 20 min; cuts happen. Boot recovery handles restarts; never run the GPU flat out.
- Killing PC jobs was blocked for Claude by the auto-mode classifier twice (rclone); Shivam ran Stop-Process himself.
- Cross-folder drags in Explorer copy, not move; Google Drive G: shows the C: cache size, not cloud quota.
