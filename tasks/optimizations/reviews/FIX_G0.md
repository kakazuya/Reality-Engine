# Fix task — G0 raw-on-D review defects (verdict FAIL)

## Goal
Fix the reviewer's defects below in this worktree (`C:\Users\warri\Downloads\IDM-worktrees\20261025T123252Z-e22819ec`,
branch `dsh/20261025T123252Z-e22819ec`), with tests, so that Claude can run one safe `--apply` that moves
16.7 GB from C to D and deletes the C copies.

## Reviewer defects (verbatim)
1. `migrate_raw_to_d.py:148-152` — `already_on_d` unlinks C without re-checking dest; a dest removed between plan and apply = data loss. Fix: re-verify size+sha right before `unlink`, else copy.
2. `migrate_raw_to_d.py:176-182` (+`main` 213-215) — manifest rewritten with only the current plan's rows; resume/re-run on the same date loses earlier entries; 2nd apply leaves `files:[]` (flow at `test_raw_root.py:132`). Violates "manifest records every file". Fix: merge rows by `src` with the existing manifest.
3. `migrate_raw_to_d.py:195-213` — no guard dest≠source, source exists, plan non-empty; `--dest <source>` (e.g. legacy `REALITY_ENGINE_PDFS_DIR=C ...\data\pdfs`) classifies all pdfs `already_on_d` and deletes them; empty source exits 0. Fix: reject resolved dest == src or nested in src, and empty plan.
4. `config.py:31` + `nse_client.py:161,293,305` / `bse_client.py:347,374` — import-time dir creation removed, writers never mkdir; `D:\RealityEngine\raw\bhavcopy` absent, so `fetch_index_bhavcopy` returns None (OSError swallowed) and bhavcopy caches are skipped until apply. Fix: mkdir at the 3 write sites.
5. `lookups_docs.py:575-577,641-643,704-718`; `ingest_annual_reports.py:459`; `extract_deck_figures.py:1043` — stored C paths unresolved: `corporate_documents` has 39,338 rows with C paths, `deck_sources` 26,387. After apply, `lookups_docs.doc_page` local reads die, and ingest/extract skip moved files.
6. `migrate_raw_to_d.py:27` — `FOLDERS` omits `hotline`; add it and switch its readers/writers, or record the exclusion.
7. `zip_packer.py:50,56,62`; `verify.py:28,32`; `build_pack.py:62,266`; `jobs.yaml:993` — readers/jobs still on C; post-apply they silently produce empty packs/verify/upload.
8. `test_raw_root.py` — no resume/kill, locked/mismatch-copy, dest==src/empty-source tests.
9. No fsync before unlink — power loss after delete can lose the last writes (low).

## Manager decisions
- Defect 5: add `config.resolve_stored_path(p) -> Path`.
  - It maps any stored path under the old C roots (`...\reality_engine\data\pdfs`, `\data\decks`, `\data\raw_market`,
    `\data\bhavcopy`, `\data\macro_pdfs`, `\data\ar_queue`, `\data\tax_sources`, `\data\index_constituents`) to the
    same relative path under the new D location.
  - It returns the original path if that still exists.
  - Use it at every read site that opens a DB-stored path: the files listed in defect 5, `concall_deepseek.py:77-80`,
    and any other `local_path` / `file_path` opener you find (grep).
  - **Do not UPDATE the DBs.**
  - `lookups_docs.py` sits in `plugins/reality-data/server/`; import the resolver through the repo root the same way
    that module already imports `reality_engine`.
- Defect 6: `hotline/` stays on C. It holds ops notes, not fetched raw data. Record the exclusion in a comment in
  `FOLDERS` and in the module docstring.
- Defect 9: `os.fsync` the destination file (and best-effort the directory) before unlinking the source.
- Defects 1–4, 7, 8: as the reviewer says. For 7, `jobs.yaml:993` (drive_upload rclone source) points at the new D
  folder, and the `writes:` entries name the new locations.

## Files to touch
`reality_engine/config.py`, `reality_engine/scripts/migrate_raw_to_d.py`, `reality_engine/ingestion/nse_client.py`,
`bse_client.py`, the files in defects 5 and 7, `plugins/dsh-worker/jobs.yaml`, `reality_engine/tests/test_raw_root.py`.
Nothing else. No DB writes. Do not run `--apply` on the real folders.

## Acceptance checks
1. One test per defect 1, 2, 3, 4, 5, 9 (fsync called), plus resume-after-kill and locked/mismatch copy tests (8).
   Each fails before the fix and passes after.
2. `resolve_stored_path` test: a stored `C:\...\reality_engine\data\pdfs\X\AR\a.pdf` resolves to `<PDFS_DIR>\X\AR\a.pdf`
   when only the D file exists, and to itself when the C file exists.
3. `python -m unittest reality_engine.tests.test_raw_root` passes (if the sandbox blocks temp dirs, use a folder under
   the workspace `.tmp` and say what was blocked).
4. A read-only dry run of the real folders still reports about 7,632 files / ~16.76 GB / 68 already on D / 0 conflicts.
5. `git diff --stat` touches only the files listed.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_raw_root
```

## Budget
≤ 12 tool calls before the first edit; ≤ 90 total; $0 paid. Do not commit (Claude commits).

## Report format
1. Per defect: change (file:line) + test name  2. Dry-run numbers  3. Every stored-path read site now resolved
(list)  4. Open problems  5. Tool calls.
