# Task — v4 WP3: decomposer and its evaluation

## Goal
Build `reality_engine/query/v4/decompose.py` and `tasks/arch_v4/eval_decomposer.py` (§H.3): an algorithmic decomposer turning a question into parts via `tasks/arch_v4/concept_registry.json`. No LLM and no DB. First read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`.

## Design sections
§H.3, the decomposer and registry sections they point to, `tasks/master_bank/MASTER_BANK.jsonl`. Output must match the part format WP4's executor expects (§H.4); define it as a small typed module, `reality_engine/query/v4/parts.py`, which WP4 will import. Write that file first and commit its shape early.

## Acceptance checks
- Per-part recall at least 97%, precision at least 97%, dim completeness 100% on the dim-naming subset, measured on a held-out split you do not tune on (state the split; 200+ hand-checked cases).
- Multi-part asks keep every part: "promoter AND public", "NSE AND BSE AND sum", "raw AND adjusted".
- Unmapped questions come back marked as unmapped, never guessed.

## Test command(s)
```bash
python tasks/arch_v4/eval_decomposer.py
python -m pytest reality_engine/tests/test_v4_decompose.py -q
```
Add that test file.
