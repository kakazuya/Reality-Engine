# WP3 — decomposer + its evaluation (progress notes)

2026-10-31

- Built: `reality_engine/query/v4/parts.py` (typed Ask/Part/Result contract WP4 imports),
  `reality_engine/query/v4/decompose.py` (algorithmic; no DB, no model, no network),
  `tasks/arch_v4/eval_decomposer.py`, gold `tasks/arch_v4/decompose_gold.jsonl`
  (54 dev + 236 hand-checked held-out test cases), split definition
  `tasks/arch_v4/decompose_gold_skeleton.jsonl`, tests `reality_engine/tests/test_v4_decompose.py`
  (20 pass).
- Split: every 4th bank case by mid; every 5th of that sample is dev (54), the other 236 are the
  held-out test split; the 26 measured-unmapped cases were oversampled into test and re-checked.
- Dev (tuned split): part recall 91.6%, precision 98.2%, dim completeness 100%, unmapped 100%;
  audit: 62 required readings named in the text at 98.4% recall.
- Held-out test (final, 2nd run): part recall 57.2%, precision 70.4%, dim completeness 93.75%,
  unmapped recall 33.3%, false_unmapped 28. Audit: 252 required readings the text names at 80.2%
  recall; 122 required readings have no measure word in the question at all (bank-intent-only).
  Acceptance NOT met: see the report's failure taxonomy.
- Next: controller decision — (a) grow WP1's lexicon with the named surfaces in the report,
  (b) re-label a blind second test split with the provenance convention fixed, (c) decide whether
  a terse variations ask may be graded on the declared default instead of a named measure.
- Note: `DSH_WORKER_PROGRESS_NOTES` is not set in this session; notes live here.
