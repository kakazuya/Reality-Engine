# WP2b progress (vocabulary, claims, own estimates)

Status: DONE (deterministic pass). Tests green 13/13 with the brief's exact command.

Built (2026-10-31):
- `reality_engine/query/v4/build_vocab.py` → `.tmp/v4_vocab.db` (attach as `vocab`):
  148,652 surfaces / 1,815,581 occurrences, 100% mapped, 139 labels (9 L1 + 130 L2),
  26,261 other clusters, 173 queued for promotion.
- `reality_engine/query/v4/build_claim.py` → `.tmp/v4.db`: 647,516 claims, 54.21% labelled,
  127 topics, facets on every row, 275,280 with a pilot surface_id.
- `reality_engine/query/v4/build_own_estimate.py` → `.tmp/v4.db`: 1,233 estimates
  (411 each fin.revenue / fin.pat / fin.eps) over 51 pilot ISINs, 12 band rows,
  replay check 1,233/1,233 clean.
- `reality_engine/query/v4/build_edge_schema.py` → `.tmp/v4.db`: edge / attention /
  hypothesis / reaction_lag DDL, idempotent, 0 rows.
- `reality_engine/tests/test_v4_vocab_claim.py`: 13 tests on small fixtures.

Open / for the controller:
- Label gate NOT met: 59.43% of the 62,601 head surfaces carry an exact label
  (target ≥95%). 25,397 head surfaces remain, dumped to `.tmp/unmapped_head.json`
  for the later free-Beam mapper job. No LLM was called.
- own_estimate bands are wide (fin.revenue SMALL 23.7% … fin.eps MICRO 273.6%)
  because the pilot store mixes single-quarter and YTD XBRL values: 369/1,233
  (29.9%) pairs compare an annual with a quarterly number. Upstream pivot fix.
- VOCAB_PASS1's 1,691,352 occurrence figure is a Counter artifact (per-source
  overwrite, not add); the true sum is 1,815,581.
