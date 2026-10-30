# PROGRESS — v4 WP8 (Beam labelling of the head surfaces)

DSH_WORKER_PROGRESS_NOTES was unset in this sandbox, so this file is at the worktree root.

- [done] Read CONTEXT.md + V4_COMMON + §A.9/§H.8 + the WP2b code. Measured the real head:
  62,601 surfaces / 1,815,581 occurrences; 37,204 deterministic / 25,397 unmapped.
  VOCAB_PASS1's 1,691,352 / 64,948 was the stale union figure; corrected in the file.
- [done] `reality_engine/query/v4/map_vocab_beam.py`: copy-once pass2 store with
  `map.source`, deterministic + resumable batch plan, contexts from the three stores
  (25,397/25,397 in ~90 s), closed-label prompt, machine check + one retry then `other`,
  adaptive concurrency, round-2 agreement check, `--status` / `--report`.
- [done] Round 1: 508 batches / 25,397 surfaces, 0 pending. Round 2: 500 surfaces mapped
  twice in different batch compositions.
- [done] Resume proven twice: killed deliberately at 170/508 batches (170 skipped on
  resume, none redone), then a crash on an unhandled 429 at 495/508 resumed from 495.
- [finding] `beam-free` is a reasoning model; default effort truncates a 50-phrase answer
  at the 8k token cap, `reasoning_effort=low` answers all 50.
- [finding] the provider throttles by *slowness* (6 s -> 360 s per batch) and only later
  429s; a 429 now lowers the limit, backs off and retries, else the batch stays pending.
- [result] head surfaces with an exact label: **43,744 / 62,601 = 69.88%** — the 95% gate
  is NOT met, and the reason is vocabulary coverage, not the mapper: 74.25% of the
  workload is AR/BRSR section headings, deck line labels and extractor buckets that no
  declared topic names. Beam/Beam agreement 85.40% over 500 pairs.
- [result] my reading of the 100-row sample: ~91% strict / ~97% lenient exact on the 34
  produced labels; 11 of the 66 `other` calls had a defensible label (recall, not
  precision, is the loss). Written into `vocab_pass2_sample.md`; not a pass.
- [done] `python -m pytest reality_engine/tests/test_v4_vocab_claim.py -q` -> 16 passed.
  Deliverables: `.tmp/v4_vocab_pass2.db` (43.3 MB, gitignored), VOCAB_PASS2.md,
  vocab_pass2_sample.md, VOCAB_PASS1.md correction.
