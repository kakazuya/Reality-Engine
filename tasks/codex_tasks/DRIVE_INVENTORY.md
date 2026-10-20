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
| Qwen-8B indexes, bge vector_index, lancedb, work files (inbox, parquet, reader_tests, concall_pilot, reports, tax_sources, hotline, dsh_tasks ...), logs, analysis | vector_index_qwen8b(_ar), vector_index, lancedb, work_files/*.7z | uploading 2026-10-20 23:05 (check misc_upload.log) |

Not on Drive:
- DB changes after 2026-10-19 16:50 (concall reader results, PIB, policy register): the PC's daily 05:00 DBBackup job
  makes the next set in db_backups/<date>/ (uploads only 05:00-13:00 IST).
- Gemma re-embed index (vector_index_gemma, partial): re-embed STOPPED 2026-10-20 23:35 by Shivam; annual reports and
  offer docs will be embedded with Nemotron on DeepInfra instead (estimate: Nemotron-1B NVFP4, ~906M tokens, ~$9.06
  for ARs; offer docs ~0.56M chunks more, ~$12-13 total; DeepInfra balance ~$3).
- On purpose never: model weights (data/models, whisper, llama-*: re-downloadable), secrets (browser_profile,
  telegram_session.session, rclone.conf, auth files), Haiku queue folders (claude_queue, ar_queue: results in DB),
  old DB copies (*.pre_*backup, *.post_bse_union_snapshot).

`corporate_documents.local_file_path` for deleted types points at files that no longer exist on the PC: fetch them
from Drive by file name.
