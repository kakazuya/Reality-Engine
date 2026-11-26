# T-242 brief: run_ledger ingest-hook reads only new transcript lines (CPU waste)

Goal: `run_ledger ingest-hook` (fired by the session hook on every Claude stop) reads a session transcript and the dsh event logs incrementally from a stored byte offset, instead of re-reading whole files each time.
Files: reality_engine/scripts/run_ledger.py, reality_engine/tests/test_run_ledger.py, docs/DEVELOPER_GUIDE.md (run ledger section, s7)
Accept: python -m pytest -q reality_engine/tests/test_run_ledger.py passes; a new test shows a second ingest of an appended transcript reads only the new lines and yields the same ledger rows as a full ingest.
Evidence: measured 25 Nov: the ingest-hook process used ~13% CPU on the MSI; transcripts are tens of MB (this session's .jsonl) and `ingest_claude` (run_ledger.py:170-177) does `transcript.read_text(...).splitlines()` on every call; `ingest_dsh` (:124-138) re-reads every job's events file the same way. Called from session_hooks.py:53-76.
Stop if: the ledger schema must change in a way old rows cannot keep (add a small offsets table instead); dedupe semantics change (rows must stay idempotent).
Budget: ~50 tool calls
Ticket: T-242

## Steps
1. Add an `ingest_offset(path TEXT PRIMARY KEY, size INTEGER, offset INTEGER, mtime REAL)` table; read from the stored offset with a binary seek, process complete lines only, store the new offset; if the file shrank or mtime/size say it was replaced, read from 0.
2. Same for dsh events files.
3. Keep existing idempotent row keys so a full re-read still yields no duplicates.
4. Tests (tmp files): append-only incremental read; truncated file resets; full vs incremental give identical rows.
5. Docs.

## Limits
Do not touch D:/RealityEngine/ledger/ledger.db (tests use a tmp DB). pytest per file. Never kill processes by name.
