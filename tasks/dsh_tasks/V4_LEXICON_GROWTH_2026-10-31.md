# Task — v4 WP1b: grow the lexicon until the decomposer passes on a blind split

## Goal
WP3 scored part recall 57.22%, precision 70.39% on its held-out split, against a 97% target. Raise it honestly. First read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`, and the WP3 failure taxonomy below.

## Findings to act on
- 252 readings named in the text: 80.2% recall. Misses are mostly lexicon gaps in `tasks/arch_v4/build_concept_registry.py`: `profitability`→`f.margin`; `iron ore`, `pellets`→`macro.commodity_close`; `forward premia`, freight→`macro.series`; `on the register`→`hold.pct`; `better proxy`→`price.close`; `equity shares`→`price.shares_out` (currently resolves to `fin.book_equity`); `resignation`, `credit rating`, `declaration of unmodified opinion`, `remark`, `capacity expansion`→`claim.claim` topics; `net X against Y`→`f.net`. Find the rest from the dev split only.
- 122 of 374 readings have no measure word in the question ("DEEDEV Aug-2026 concall remark"). **Controller decision:** the §C.2 declared default is a legitimate output for these, marked `declared_default=true`, and they are scored separately: `named_recall` (target 97%) and `default_coverage` (reported, no target yet). Do not count a default as a named match.
- Gold errors the worker found after measuring, such as `text.passage` on provenance asks: fix them in the existing gold only as a declared correction list, and do not use the old test split as the final evidence after that.
- 28 false unmapped: mostly registry surface gaps.

## Blind test
Before any tuning, write a NEW gold split of 200 cases not in `tasks/arch_v4/decompose_gold.jsonl`, with `required` and `evidence` labelled from the question alone, and commit it first in its own commit. Do not read or score it until tuning is finished. Run it once and report that number, whatever it is. Everything from the old test split counts as dev from now on.

## Acceptance checks
- On the blind split: `named_recall` and precision at 97% or better, or the true numbers and the remaining failure classes.
- Dim completeness 100% on the dim-naming subset. `holder_class` FII+DII stays two readings or the design says why not.
- `build_concept_registry.py --check` still deterministic; report mapped / NID / unmapped.
- No question text or bank-field memorised: lexicon entries must be general surfaces. List every entry added.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_decompose.py -q
python tasks/arch_v4/eval_decomposer.py
```
