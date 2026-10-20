# What is on Google Drive vs still on the PC (2026-10-20 23:40 IST, PC Claude session)

Drive: My Drive / `InfoDiffusion_archive/` (rclone remote `gdrive:` with `--drive-root-folder-id 1A3MOQnFsYw27Vk4DVmypfdIHR9ERydHB`;
browser uploads also sit in folder `1aSQEfkMMGmpEpDDq7tI9MH7kmNJNemTH`). The upload remote (`gdrive:`, drive.file scope) only
sees files rclone uploaded itself; the read-only remote `gdrive_ro:` sees everything: use gdrive_ro for any check or listing.
Every item below was checked with `rclone check --one-way` (MD5) or name+size+MD5 (scripts/cleanup_verify.py).

| Data | On Drive (folder) | On the PC |
|---|---|---|
| Annual reports (C: data/pdfs + D:\RealityEngine\pdfs) | pdfs, D_pdfs | deleted 2026-10-20 (freed space) |
| Investor presentations, offer documents (433 companies, 904 docs 2021-2026; list analysis/offer_document_companies.csv) | pdfs | deleted |
| Decks (BSE/NSE presentation slides) | decks | deleted |
| Concall transcripts (20,479) | pdfs | kept (readers use them) |
| 6 SQLite DBs, set 2026-10-19 (equity_intelligence, ar_facts, deck_figures, results_xbrl, concall_facts, bse_announcements) | db_backups/2026-10-19 (23 x .7z parts) | live |
| Truth snapshot truth_2026-10-19.duckdb (69 tables) | snapshots | kept; also on the laptop |
| raw_market (NSE/BSE bhavcopy, delivery, deals, insider, SAST, NSDL, indices, results XBRL, shareholding XBRL, nse_pr ...) 194k files | raw_market (46 .7z, one per subfolder) + bhavcopy/bhavcopy.7z | kept |
| macro_pdfs (Union budgets, Economic Surveys, RBI, PIB, PRS state budgets) | macro_pdfs | kept |
| telegram_media | telegram_media | kept |
| vector_index_nemotron8b (paid DeepInfra, transcripts+macro+decks tiers) | vector_index_nemotron8b | kept |
| vector_index_qwen8b_ar (11.2 GB, Nebius paid), vector_index_qwen8b (2.7 GB), vector_index (bge, 2.5 GB) | same names | kept; MD5 ok 2026-10-21 01:17 (duplicates removed with rclone dedupe) |
| lancedb (2.3 GB, frozen copy 2026-10-21 ~01:20; the live store kept changing during upload) | lancedb | kept |
| Work files: data/ small dirs (inbox research reports, parquet, reader_tests, concall_pilot, reports, tax_sources gazette PDFs, hotline, dsh_tasks, cc_query_test, fixtures, seed, index_constituents, news_images, video_out, visual_snapshots ...), logs, analysis (non-DB) | work_files/data_work_files.7z, logs.7z, analysis_nondb.7z | kept |
| concall_facts.db as of 2026-10-20 23:35 (cc_docs ok 7,477; all reader results incl. MiniMax run complete) | db_backups/2026-10-20_concall | live |
| PIB + policy tables as of 2026-10-20 23:50 (pib_releases 75,129 to 2026-10-20, pib_days, pib_ml_* regional 8,816 + 14,416 matches, policy_events 21,552, policy_docs 3,054, policy_eni_history 5,470; no FTS tables, rebuild them) | db_backups/2026-10-20_pib_policy/pib_policy_2026-10-20.db | live |

Not on Drive:
- Other main-DB (equity_intelligence.db) changes after 2026-10-19 16:50 besides PIB/policy (e.g. raw_documents/chunks
  added by ingest jobs). The PC is shut down 2026-10-21 until ~2026-11-26/27, so no 05:00 backup runs before then.
- Gemma re-embed index (vector_index_gemma, partial): re-embed STOPPED 2026-10-20 23:35 by Shivam; annual reports and
  offer docs will be embedded with Nemotron on DeepInfra instead (estimate: Nemotron-1B NVFP4, ~906M tokens, ~$9.06
  for ARs; offer docs ~0.56M chunks more, ~$12-13 total; DeepInfra balance ~$3).
- On purpose never: model weights (data/models, whisper, llama-*: re-downloadable), secrets (browser_profile,
  telegram_session.session, rclone.conf, auth files), Haiku queue folders (claude_queue, ar_queue: results in DB),
  old DB copies (*.pre_*backup, *.post_bse_union_snapshot).

`corporate_documents.local_file_path` for deleted types points at files that no longer exist on the PC: fetch them
from Drive by file name.

## PC status at shutdown (2026-10-21 ~01:30 IST; PC off until ~2026-11-26/27, flatmate starts it)
- **All RealityEngine-* scheduled tasks DISABLED 2026-10-21 01:30 (Shivam: "switch them off")**; nothing starts at the next boot.
  Re-enable with Enable-ScheduledTask only on his word. (Old note:) Shivam shut the PC down after this upload. At the next boot the scheduled tasks would start again by themselves
  (BootRecover, EODMarket, DBBackup, DeepSeekHeartbeat): readers (Beam 6 workers, MiniMax if anything is queued),
  writers (PIB backfill, policy register ...), DB backup to Drive, hourly paid DeepSeek checks. Decide before
  then whether the PC should still do any of that (disable the tasks from the laptop session via Shivam/RDP if not),
  because the laptop is now the main workstation and the PC DBs will diverge from the laptop's.
- Gemma re-embed: removed from boot recovery (stays off). DeepInfra Nemotron for ARs/offer docs instead.
- PC disk after cleanup: C: ~280 GB free, D: ~125 GB free.
