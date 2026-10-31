# Task — v4 decomposer: fresh blind split and a Beam-suggested lexicon

## Goal
The decomposer's blind score is 77.6% recall, 84.8% precision. Hand-added synonyms overfit, and that blind split is now spent. Get an honest new number with a lexicon that generalises. First read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md` and `tasks/dsh_tasks/V4_LEXICON_GROWTH_2026-10-31.md`.

## Work
1. **Blind split first, in its own commit:** 200 new cases, none in any earlier gold file, with `required` and `evidence` labelled from the question alone by a fixed seed. Do not read or score it until step 4. All earlier splits count as dev.
2. **Beam suggests surfaces:** give free Beam (`beam-free`, `reasoning_effort=low`, `cost_ledger.record_usage`, stable session id, resumable) each measure in `tasks/arch_v4/build_concept_registry.py` with its definition and ask for general synonyms and Indian-filing terms. Give it no bank questions and none of the blind split.
3. **Filter by evidence:** keep a suggestion only if it raises dev recall without lowering dev precision, and does not change any other concept's mapping. Report kept and rejected counts, and list every entry kept.
4. **Run the blind split once.** Report that number, whatever it is, with failure classes. Do not tune afterwards.

## Acceptance checks
- Blind split commit comes before any lexicon commit.
- `named_recall`, precision and `default_coverage` reported separately on blind and dev, so the overfit gap is visible.
- `build_concept_registry.py --check` stays deterministic.
- No question text memorised: entries must be general surfaces.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_decompose.py -q
python tasks/arch_v4/eval_decomposer.py
```
