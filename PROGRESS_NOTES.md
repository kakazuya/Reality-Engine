# WP1b progress notes

- Blind gold split written first (200 cases sampled with seed 20261031 from the 783 bank
  cases not in `decompose_gold.jsonl`; `required`/`evidence` labelled from the question text
  only, each reading marked `named` true/false). File: `tasks/arch_v4/decompose_gold_blind.jsonl`.
  `git commit` is impossible from this worktree (shared .git dir is outside the workspace and
  the sandbox denies writes; no approval channel) — the controller must commit it first.
- Eval scores `named_recall` / `default_coverage` separately; `--accept` applies targets.
- Decomposer fixes (no bank fields): doctype dim no longer steals a clause; multi-measure
  clauses emit every named measure; hyphen compounds that are measures survive; company-name
  possessive/commodity masking; operator defaults only in ask clauses; ratio slash forms carry
  `ratio_kind`; `declared_default` flag on parts.
- Lexicon grown in `tasks/arch_v4/build_concept_registry.py`; registry regenerated (2920
  lexicon rows, deterministic PASS; mapped 913 / NID 146 / unmapped 14).
- Old test split relabelled dev (declared in `tasks/arch_v4/decompose_gold_corrections.md`).
- BLIND RUN (single, after tuning): n=200, named_recall 77.61% (393 named readings),
  default_coverage 48.65%, precision 84.76%, dim_completeness 96.67% (29/30), part_recall 72.59%.
  Acceptance 97/97/100 NOT met. Failure classes recorded in the final report.
- Post-run one-line fix: plural dim words ("FIIs"/"DIIs") now resolve to their owning atom
  (2 `hold.pct` readings); the blind split was NOT re-scored after it.
- Dev (290 cases): named_recall 99.15%, precision 83.66%, dim_completeness 100%.
