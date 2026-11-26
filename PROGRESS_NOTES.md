# T-242 fix 9 progress

- 2026-11-26: fix 9 implemented in `plugins/reality-data/server/lookups_pilot3.py` (guidance sibling election on
  the page's own evidence, sentence-per-turn statements window, spelled-out metric aliases), `server.py`
  descriptions, `test_retrieval_fix9.py` (9 tests); docs `docs/DEVELOPER_GUIDE.md`, `machines/MSI_LAPTOP.md`,
  `tasks/STATE.md`. Verified: 151 passed + 1 skipped across fix 2-9 + lookups + server-no-sql; typecheck 0 errors;
  192-row audit-6/7/8/9 replay (`C:/RealityEngine/tg_build/universe_fy27`, stores mode=ro, live main 5abc768a ->
  branch): 0 R lost in every audit, audit 6 41R=41R, 7 35R->36R, 8 32R=32R, 9 23R->32R.
- Next: controller copies `.tmp/replay_f9.py` (job-local) beside main's `replay_f8.py` if it should stay; the four
  audit-9 store defects (AYE AUM 75.97, BIRLANU Walls split as guidance, BIOCON Syngene entity, INDHOTEL superseded
  row) remain extractor issues, not patched here.
