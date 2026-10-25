# Task G5 — store identical raw files once (sha256 + hard links on D)

## Goal
Every raw file under `D:\RealityEngine` with identical content is stored once. Duplicates become hard links to one
file, so every path that existed still opens, and new downloads reuse an existing copy instead of writing a second one.

## Why
Shivam (2026-10-25): companies file the same results PDF twice (standalone/consolidated, revisions) and re-file
decks under new names. Results PDFs alone could reach ~130–300 GB, so storing duplicates wastes the D drive.

## Files to touch
- New `reality_engine/scripts/dedupe_raw.py`:
  - Walk the roots (default `D:\RealityEngine\raw` and `D:\RealityEngine\pdfs`, or `--root` repeated).
  - Group files by size, then by sha256 (read in chunks; skip files under 1 KB).
  - Keep the oldest file of each group as the canonical copy. Replace the others with hard links: create the link
    at `<path>.lnk-tmp`, then `os.replace` it over the duplicate.
  - Only within one volume. Skip `.part` files and anything open or locked.
  - Dry run by default; `--apply` performs the links.
  - Writes a JSON report to `RAW_ROOT/_dedupe/<date>.json`: groups, links made, bytes saved, skipped files with reasons.
  - Before each replace, re-verify size and sha256 of both files. Never delete the only copy.
- New `reality_engine/raw_store.py` with `store_bytes(dest: Path, data: bytes) -> Path`. It uses a sha index (SQLite
  at `RAW_ROOT/_dedupe/sha_index.db`: sha256, size, first_path) and:
  - hard-links `dest` to an existing copy when the sha is already stored;
  - otherwise writes `.part` → fsync → `os.replace`, and records the file in the index.
- Use `store_bytes` in `reality_engine/scripts/fetch_results_notes_text.py` (its PDF cache write) and
  `reality_engine/scripts/fetch_decks.py` (its PDF write). Change nothing else in those files.
- `plugins/dsh-worker/jobs.yaml`: a new `dedupe_raw` job (`enabled: false`; weekly; lock `db:` none; writes the D
  roots; success check on the report date). Mirror an existing entry.
- New tests `reality_engine/tests/test_dedupe_raw.py`, using temp dirs only:
  - groups are found;
  - links are made and both paths read the same bytes;
  - a changed file between plan and apply is not linked;
  - a single copy is never removed;
  - a cross-volume pair is skipped (simulate with a monkeypatched `os.link` raising);
  - `store_bytes` reuses an existing sha.
- Config: use `reality_engine.config.RAW_ROOT` / `PDFS_DIR` (already defined).

## Acceptance checks
1. `python -m unittest reality_engine.tests.test_dedupe_raw` passes. If the sandbox blocks temp dirs, use the
   workspace `.tmp` and say what was blocked.
2. Read-only dry run on the real D roots: report the file count, the duplicate groups, and the bytes that would be
   saved, split by folder. Do not run `--apply`.
3. `python -m unittest reality_engine.tests.test_new_feeds_g2` still passes.
4. `git diff --stat` touches only the files listed.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_dedupe_raw
```

## Budget
≤ 12 tool calls before the first edit; ≤ 80 total; $0 paid. No `--apply` on real folders; no DB writes except
temp test DBs.

## Report format
1. What changed  2. Dry-run numbers (per folder: files, dup groups, bytes saved)  3. Open problems  4. Tool calls.
