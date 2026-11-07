# T-102 fetch on demand: raw files come from Drive when a job needs them

Ticket: T-102
Goal: every pilot3 build step that reads a raw file (PDF, jsonl, csv) works when the file is no longer on the local
disk: it finds the file through the T-102 manifest, downloads it from Google Drive into a temp folder, uses it, and
deletes it. Shivam's ruling (7 Nov): raw files live only on Drive; only databases stay local.

Evidence (gathered by Opus, 7 Nov):
- Manifest `D:/RealityEngine/drive_index/raw_to_drive.db`, table `local_file(path, root, rel, size, mtime, md5,
  status, drive_path, deleted_at)`. `root` is the root folder name (`raw` = `D:/RealityEngine/raw`, `pdfs` =
  `D:/RealityEngine/pdfs`); `rel` is the forward-slash path under it. `path` is stored mixed-slash, e.g.
  `D:/RealityEngine/raw\annual_report\KEC\bbad8592-....pdf`: always compare by (root, rel), never by `path` text.
  After the upload running now, every row has `status='on_drive'` and a `drive_path` (except `raw/user_research/*`,
  which stays local).
- `drive_path` = `<top>/<path inside that top>`. Remote for each top:
  `D_pdfs`, `decks`, `macro_pdfs`, `pdfs`, `results_pdfs`, `msi_raw` -> `gdrive:InfoDiffusion_archive/<top>/<path>`;
  `arch17` -> remote `gdrive_ro:` with `--drive-root-folder-id 1aSQEfkMMGmpEpDDq7tI9MH7kmNJNemTH`, then `<path>`.
  Example: raw `annual_report/KEC/bbad8592-d586-49bd-bc55-f65b64e3f1a6.pdf` ->
  `pdfs/KEC/ANNUAL_REPORT/20261010_97794a94_bbad8592-d586-49bd-bc55-f65b64e3f1a6.pdf`.
- One `rclone copyto` per file costs about 1-2 s of start-up: a company has ~680 files (KEC: 682, 1.38 GB), so fetch
  in one `rclone copy --files-from <list>` per top folder, `--transfers 8 --checksum`.
- Raw readers to switch (all found by grep, line numbers on main `2627bbf`):
  - `reality_engine/pilot3/docs_collect.py`: `discover()` ~L425 walks folders (`_named_dirs`, `_walk_pdfs`, SHA_DIRS,
    `pilot60_history/manifest.csv`, `nse_announcements/*/<SYM>.jsonl`); the profile path ~L658 checks
    `path.is_file()`; `_extract()` ~L501 opens the PDF.
  - `reality_engine/pilot3/comparatives.py` `_open_pdf` ~L778.
  - `reality_engine/pilot3/kpi.py` `_open_pdf_path` ~L2747, `RAW_ROOT` hard-coded ~L2765 (use `config.RAW_ROOT`).
  - `reality_engine/pilot3/hp_ocr.py` `_resolve_pdf` ~L171, `reality_engine/pilot3/ocr.py`, `doc_identity.py` ~L549,
    `plugins/reality-data/server/lookups_docs.py` ~L587 (the MCP reads a page from the raw PDF).
  - `reality_engine/config.py` `resolve_stored_path` ~L50 maps old C paths onto the D roots; keep it, add the
    Drive fallback beside it, not inside it (it must stay cheap and offline).

Files:
- NEW `reality_engine/raw_store.py`, NEW `reality_engine/tests/test_raw_store.py`.
- EDIT the readers listed above; `docs/DEVELOPER_GUIDE.md` (O18, the T-102 paragraph) and `docs/DB_BUILD_GUIDELINES.md`
  (one line: raw readers go through `raw_store`).

Steps:
1. Write `raw_store.py`:
   - `RawStore(manifest=..., roots={"raw": config.RAW_ROOT, "pdfs": config.PDFS_LEGACY_DIR})` reads the manifest once
     (only rows with `drive_path`), keyed by `(root name, rel)`; a path is mapped to its key by which configured root
     it sits under (normcase, both slash forms).
   - `exists(path) -> bool`: local file, else a manifest row.
   - `walk(folder) -> iterator of Path`: local files under `folder` plus manifest rows under it (deduped), so a
     folder walk sees files that are only on Drive. `glob(folder, pattern)` the same.
   - `local(path)` context manager: yields the local path when the file exists; else downloads to
     `tempfile.mkdtemp(prefix="raw_fetch_")`, checks md5 equals the manifest's, yields it, deletes on exit.
   - `prefetch(paths)` context manager: one `rclone copy --files-from` per remote top, md5 check, then `local()`
     inside it returns the fetched copy without a download; the temp folder is deleted on exit, also on exception.
   - A file neither local nor in the manifest: `local()` raises `FileNotFoundError` (same as today).
   - Env `REALITY_RAW_FETCH=0` turns Drive off (tests, offline runs). rclone path from `shutil.which("rclone")`.
2. Switch each reader in the list to the store. `docs_collect` builds per company: call `prefetch` with that
   company's discovered files before `_extract`, so a company is one download and one delete.
3. Tests in `test_raw_store.py` with a fake rclone (monkeypatch the runner): walk merges local + manifest, local file
   needs no fetch, missing file is fetched once and deleted after, md5 mismatch raises, `REALITY_RAW_FETCH=0`
   never calls rclone, kept prefixes untouched.
4. Accept run (real Drive, KEC only, nothing deleted from D:): set `REALITY_RAW_ROOT` and
   `REALITY_PDFS_LEGACY_DIR` to two EMPTY folders under `.tmp/`, point the store's roots at the manifest's names, and
   run `docs_collect` for KEC into `.tmp/kec_drive_pages.db`; run it again with the real roots into
   `.tmp/kec_local_pages.db`. Compare: same `doc` keys, same page count per doc, same text hash per page. Report the
   wall time of both runs and the GB downloaded. Then `build --part comparatives` and `--part kpi --symbols KEC` on a
   copy, empty roots: row counts equal to the real-root run.

- Your sandbox may block rclone, the network or reads outside the worktree. If step 4 cannot run, finish steps 1-3,
  commit, and give Opus the exact step 4 commands to run unsandboxed; that is a success, not a failure.
- The upload of the last 79 GB runs while you work: a KEC file may still lack a `drive_path`; list such files, do not
  wait for them.

Accept:
- `python -m pytest reality_engine/tests/test_raw_store.py reality_engine/tests/test_raw_to_drive.py -q`
- `python -m pytest reality_engine/tests -q -k "pilot3 and (docs_collect or comparatives or kpi)" -m "not slow"` run
  one file per process.
- The step 4 comparison table in your final report: KEC docs, pages, page-text hashes equal; temp folder empty after.

Limits and pitfalls:
- Never delete or move anything under `D:/RealityEngine/raw` or `D:/RealityEngine/pdfs`; Opus runs the delete.
- Never write to the manifest db (read-only connection); never print or copy rclone config or tokens.
- `gdrive` has `drive.file` scope and cannot see `arch17`; only `gdrive_ro` with the folder id can.
- Do not touch `Downloads\Telegram Desktop` or `D:\Shivam_Private`.
- RAM: run tests one file per process; the build of one company only.
- Use the `outline` tool before reading a large file (kpi.py is ~3,000 lines: read only the functions named above).

Stop if: the step 4 comparison differs on any page and you cannot explain it in two attempts; or rclone gives a
quota or auth error (report it verbatim, do not retry in a loop); or the change needs any edit to the manifest
schema.

Budget: 3 hours, about 150 tool calls.

Docs updated: name the doc lines you changed in the final report (no docs, no merge).
