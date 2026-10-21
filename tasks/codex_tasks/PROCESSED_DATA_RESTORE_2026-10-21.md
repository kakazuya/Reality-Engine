# Processed Drive data restore — 2026-10-21

Shivam requested all available processed data, excluding original annual-report PDFs, presentations, concalls, government/RBI documents and similar source files. No upload or embedding run is authorized by this restore.

## Completed

- Existing active AR, deck, XBRL, main and latest concall databases plus the dated research snapshot were already local. Their older compressed backups were not redundantly downloaded.
- Missing `reality_engine/data/bse_announcements.db` restored from the 19-Oct Drive archive: 1,162,780,672 bytes, 1,947,087 announcement rows, SQLite quick_check = ok. Archive MD5 `01d38388f597917332d0ed7b1e18f6bc` independently matched Drive; 7-Zip extraction CRC passed. Original exchange timestamps preserved, with first three rows inspected; this is a restoration, not a new filing-date interpretation.
- All three work archives independently MD5-matched Drive. Original compressed archives are under `reality_engine/data/backups/drive_processed_2026-10-21/work_files/`.
- Selectively extracted 3,130 data/work files (183.89 MiB), 74 analysis files (247.36 MiB), and 791 logs (152.32 MiB) into sibling `processed_data/`, `processed_analysis/`, `processed_logs/` folders. Original PDFs, presentations, images/media, transcript test inputs, stale lock files and known credential paths were excluded. Verified zero source PDF/PPT/image/video files in the extraction. Files are staged, not merged over active local work; archived scripts/instructions were not executed.
- The mixed `data_work_files.7z` necessarily contains some source documents in its compressed bytes; they were not extracted. Original source-only Drive folders were not downloaded.

## Index restore completed

`rclone copy gdrive_ro:InfoDiffusion_archive reality_engine/data` completed successfully at 04:20 IST with include filters for `vector_index*/`, `lancedb/`, `embed_test/` only. All 29 selected files (21,939,524,275 bytes, 20.433 GiB) independently MD5-matched the saved Drive inventory; zero missing files or mismatches. Existing index folders were absent and LanceDB was empty before restore. Download log: `reality_engine/data/logs/drive_processed_restore_2026-10-21/index_download.log`; complete independent audit: `index_hash_audit.json` in the same directory. Completed-file hashes were reused only when local size/mtime and expected source hash were unchanged, avoiding repeated large disk reads.

Remote file inventory including source MD5 hashes: `reality_engine/data/logs/drive_processed_restore_2026-10-21/remote_manifest.json`. Archive hash audit, selection lists, archive listings and BSE restore audit are in that same gitignored log directory. This requested restore of available processed backups is complete; the provenance and embedding gaps below remain explicit.

## Known limits

- Post-19-Oct main-DB raw documents/chunks absent from the final backup remain unavailable while the PC is off. The later PIB/policy and concall results were restored separately earlier.
- Final PC handoff explicitly says partial Gemma was stopped and some annual-report/offer-document embeddings remain pending. Existing embedding backups are not proof that every source was embedded.
- Raw source folders remain on Drive. The frozen LanceDB backup includes its original legacy/stale files; preserve provenance and do not delete them during this restore.
