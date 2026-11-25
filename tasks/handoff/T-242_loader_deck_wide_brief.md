# T-242 brief: load the widened deck read (obs_decks_wide.db) beside obs_decks_fy27.db

Goal: `load_observations` loads a supplement DB for a doc type in addition to the primary one, page-disjoint, so the 8,427 widened deck pages (few-figure and jumbled-layer pages, checkpoints 1-4 passed) reach the stores without dropping the primary deck rows.
Files: reality_engine/scripts/load_observations.py, reality_engine/tests/test_load_observations.py (create if absent), docs/DEVELOPER_GUIDE.md, tasks/DATA_INVENTORY.md if it lists loader sources
Accept: python -m pytest -q reality_engine/tests/test_load_observations.py passes; a scratch load of 3 symbols into COPIES of their universe stores shows primary deck rows unchanged and supplement rows added only for pages the primary lacks.
Evidence: below
Stop if: obs_fact needs a schema change; observation ids collide in a way that breaks provenance or check_status lookup and you cannot key them by (source db, id) within ~40 lines.
Budget: ~60 tool calls
Ticket: T-242

## Evidence
- reality_engine/scripts/load_observations.py:17-24 OBS_SOURCES; `_load_store` :160-187 loads the FIRST db with rows per source (doc type) and DELETEs that source's obs_fact rows for the symbol (:174). obs_decks_wide.db is not listed, and listing it after deck_fy27 would never load for a symbol that has deck_fy27 rows.
- obs_decks_wide.db (D:/RealityEngine/hy4_out): 8,427 pages read, 87,592 verified / 64,150 unverified / 267 quarantined; its pages are chosen by `--deck-few-figures --deck-jumbled-min 0.70` and are not in obs_decks_fy27's page set (verify: count overlapping (doc_key, page)).
- Both DBs number observation_id from 1, so ids collide across them; `load_checks(db_path)` is keyed per DB.

## Steps
1. Add a SUPPLEMENTS list: ("deck_wide", "D:/RealityEngine/hy4_out/obs_decks_wide.db", "deck"). After the primary source for a doc type is loaded, append supplement rows whose (doc_key, page) the primary did not supply; same `source='deck'`, plus a provenance marker the tools can show (e.g. a `source_db` / `obs_db` column if one exists, else reuse an existing provenance field - no schema change).
2. Keep ids unique in obs_fact: if observation_id is a key there, offset supplement ids (e.g. + 10,000,000) consistently, and look up checks with the original id.
3. Tests: primary-only symbol unchanged; supplement adds only non-overlapping pages; reload is idempotent (delete+insert covers both); id offset applied.
4. Measure on copies of 3 universe stores (pick symbols present in both DBs): rows before/after by source, overlap count; report.
5. Docs.

## Limits
Never write live stores or D:/RealityEngine/hy4_out DBs; copies only under your worktree .tmp. No model calls. pytest per file. Never kill processes by name.
