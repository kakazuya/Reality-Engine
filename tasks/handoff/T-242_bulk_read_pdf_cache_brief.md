# T-242 brief: bulk hy4 reads fetch each Drive PDF once, not once per page

Goal: a bulk `observations` run downloads each Drive-only PDF once per run (thread-safe shared cache), so the 30 reader threads wait on the model, not on rclone.
Files: reality_engine/raw_store.py, reality_engine/v2/observations.py (run path around line 7980 only), reality_engine/tests/test_raw_store.py (or the existing raw_store test file), docs/DEVELOPER_GUIDE.md
Accept: python -m pytest <raw_store test file> -q and python -m pytest reality_engine/tests/test_observations*.py -q pass (run per file); new test shows 8 threads x 5 pages of one Drive-only doc = exactly 1 fetch
Evidence: below
Stop if: the cache needs changes to page_words/page_reader signatures, or any existing test breaks for a reason you cannot explain in 2 lines
Budget: ~70 tool calls
Ticket: T-242

## Evidence (measured 26 Nov 01:00)
- 4 bulk readers (30 workers each) on the Go endpoint: per-call median 7.4 s (deck-wide), 12.7 s (results), zero 429s. Expected ~240 pages/min per reader; measured 5-10 pages/min.
- 60 `rclone copy gdrive:InfoDiffusion_archive/msi_raw ... raw_fetch_*` processes alive at once: every page fetches its whole PDF from Drive separately.
- Fetch points: `process_page` -> `page_words.words_for` (observations.py:7019) and `page_reader._page_image` (:7034); `process_window` similar (:6870). The recheck path already fixed this for one thread with `_kept_pages` (:7466, T-238) using `store.keep()`; `keep()`/`prefetch()` in raw_store.py (~line 400-470) swap instance state (`_keep_dir`, `_fetched`) and are NOT thread-safe, so they cannot be used from 30 threads.

## Steps
1. raw_store: add a thread-safe context manager `RawStore.shared_cache(max_bytes=3 GB)`: while active, any `local()`/fetch of a Drive-only file downloads it once into one temp dir on C: (per-key lock: concurrent callers of the same file wait for the one fetch), reuses it, evicts least-recently-used files above `max_bytes` (delete from disk), and deletes the dir on exit. Hash check as today. Outside the context nothing changes.
2. observations bulk run: wrap the ThreadPoolExecutor block (~:7980) in `shared_cache()` and submit pages ordered by (doc_key, page) so a document's pages are read close together (keeps the cache small). Recheck path unchanged.
3. Optional if cheap: drop a cached PDF once all submitted pages of that doc are done (refcount), instead of waiting for LRU.
4. Tests (no Drive, no model): fake runner counting fetches; 8 threads x 5 pages of one doc -> 1 fetch; eviction deletes files above the cap; dir removed on exit; outside the context behaviour unchanged.
5. Docs: raw_store section and the hy4 bulk-read section of docs/DEVELOPER_GUIDE.md.

## Limits / pitfalls
- Do not touch the running readers or their DBs under D:/RealityEngine/hy4_out; no live model calls; no Drive calls in tests.
- Raw files stay Drive-only (standing rule): the cache is temporary and must be deleted on exit, also on exception.
- Never kill processes by name. pytest per file (RAM).
