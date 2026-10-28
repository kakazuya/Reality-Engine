# Task — make concall_refetch resumable and parallel (fetch speed is latency-bound, not rate-bound)

## Goal
Probes on 2026-10-28 showed no block at about 200 extra requests/min on BSE, nor at 400/min on NSE. The old 76/min BSE cap is stale. But `reality_engine/scripts/concall_refetch.py` fetches one PDF at a time and writes its manifest only at the end. So it can't go faster, and a restart loses everything done so far: the live full run is at about 3,100 of 9,390 after 2.5 h.

## Do
1. **Journal:** append one JSON line per finished candidate to `<root>/_journal_<mode>.jsonl`, where mode is full / widen / rescue. Flush after every line.
   - On start, load the journal and skip every newsid already recorded with status ok or failed-permanent. Retry the transient failures.
   - The final manifest = journal entries + new ones, then the existing dedupe.
2. **Parallel:** add `--workers N` (default 1), using a thread pool for the network fetch, with one `curl_cffi`/`requests` session per thread.
   - Keep a shared pacer so the total rate stays at or below `60/interval` per minute.
   - On a 403/429 from any thread, pause all threads for the back-off, as `fetch_decks.BseDownloader` does.
   - PDF inspection/classification can stay in the main thread, or move to threads if it is thread-safe. Check `inspect_pdf` and the DB handles: read-only `connect_ro` per thread.
3. **Seed the journal** from the running full run's log `D:\RealityEngine\raw\concall_refetch_full.log`. Add `--seed-journal-from-log PATH`: it parses the `[i/9390] SYMBOL quarter status source class chars` lines, maps i back to the sampled candidate (same seed and order), and keeps only the ok rows whose PDF is on disk under root, found by recomputing from the candidate's URL/sha if possible. Otherwise mark them to re-fetch. This lets the controller kill the slow run and restart with `--workers 8` without redoing about 3,100 rows.
4. **Tests:** offline tests for journal resume, skip-done, the parallel pacer cap, and a block pausing all threads.

## Rules
- No network. Write only in this worktree. All DBs read-only. No commits.

## Acceptance checks
1. A resumed run with `--dry-run` reports the skipped-from-journal count. Run it against a fake journal in `.tmp`.
2. `python -m unittest reality_engine.tests.test_concall_refetch` passes.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_concall_refetch
```

## Report
Give:
- the exact restart commands for the full, widen and rescue runs with `--workers 8 --interval 0.25`;
- how many log rows the seed maps;
- your tool-call count.
