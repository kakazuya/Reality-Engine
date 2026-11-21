# T-228 stage 2c — progress notes

- 21 Nov, worktree 20261121T052428Z-17494c2e: read CONTEXT.md, Wolf's 91-read and driver_claims.py;
  implemented period_norm, unit normalisation, order_kind, part scope, collapsed-range repair, event repair
  (duplicates marked, revisions linked), the repair CLI/report and tests (101 pass, typecheck clean).
- Repaired DB: `.tmp/t228/claims_91_s2c.db` (copied from D:/RealityEngine/t228/claims_91_s2.db, source never
  written); report `.tmp/t228/repair_91_s2c.md`.
- Final counts: 10,102 rows — verified 1,954, unverified 5,724, duplicate 2,256, quarantined 168. 494 of
  2,451 pre-repair verified rows became duplicate (20.2%, stop condition 60%). 13 rows re-judged, 12 passed.
- Of Wolf's 22 WRONG: 18 resolved; 4 remain (wrong node 2511/4984/9972, related-party approval 13053).
- Docs: `docs/research/T-228_driver_claims.md` §5, §6, §8, §10, §12 end and new §13.
- Done unless the controller asks for more.
