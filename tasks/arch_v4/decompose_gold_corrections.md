# Declared gold corrections — WP1b (2026-10-31)

The controller's WP1b decision is explicit: **everything from the old `test` split counts as
dev from now on**, and the only held-out evidence is the new blind split
`tasks/arch_v4/decompose_gold_blind.jsonl` (committed before any tuning).

## 1. Split relabel (236 rows)

| field | old | new | why |
|---|---|---|---|
| `split` on the 236 rows that were `test` | `test` | `dev` | controller decision: the old test split is no longer held out; the blind split is the evidence. `decompose_gold.jsonl` therefore holds 290 dev cases. |

No `required`, `evidence`, `expect_status` or `note` value was changed. The evaluator no
longer applies acceptance targets to this file; `--accept` is used on the blind split.

## 2. Provenance `text.passage` — resolved in the decomposer, not by editing gold

The brief named "`text.passage` on provenance asks" as a gold-error class.  On the current
gold, no case is left where the question asks for provenance ("where in the report", "which
page", "who published it first", "name the PIB release", "slide ka reference") and the
evidence omits `text.passage`: the extra `text.passage` parts came from a decomposer defect
(the `doctype` dim owning `text.passage`, so "results"/"concall"/"budget" produced a passage
part).  That defect is fixed in `reality_engine/query/v4/decompose.py` (see the WP1b report),
so the gold was left unchanged rather than loosened.

## 3. What was NOT changed

- No required reading was removed or relaxed.
- No evidence set was widened to make a wrong part pass.
- The blind split was not re-read or rescored after this file was written.
