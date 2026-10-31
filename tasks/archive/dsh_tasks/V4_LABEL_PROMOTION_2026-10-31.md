# Task — v4 label promotion driven by measured frequency

## Goal
Shivam approved this on 31 Oct. Labelled uses are 76.1%. Raise useful coverage without losing any phrase. First read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md` and `tasks/arch_v4/VOCAB_PASS2.md`.

## Inputs
`v4_vocab.db` tables `surface` (`n_occurrences`, `n_docs`, `n_isins`, `source_kind`), `map`, `label`, `beam_context`. Questions from `tasks/master_bank/MASTER_BANK.jsonl`.

## Work
1. **Mapper bug first:** `ROE`, `ROCE`, `ROCE %` are unlabelled. Find out why short ratio surfaces miss and fix `build_vocab.py`.
2. **Merge spellings:** `p&l`, `p_and_l`, `pnl`, `balance sheet`, `balance_sheet` and the like, deterministically.
3. **Rank** unlabelled surfaces by uses, documents and companies. Compute for each: share of occurrences with a value or quote attached; whether a bank question names it (token and stem match, list matches); whether it means anything alone (`Total`, `17`, `Others` do not).
4. **Decide the top 500 with free Beam** (`beam-free`, `reasoning_effort=low`, `cost_ledger.record_usage`, stable session id, resumable): `new_label`, `alias_of:<label>`, `bucket` (an extractor bucket such as `signal`: never a label; its items keep their own text), or `meaningless`. Beam only suggests. Write `tasks/arch_v4/label_promotion_review.md` with one row per surface, its evidence and Beam's suggestion, for Opus and Shivam to approve. **Do not apply new labels yourself.** Aliases to existing labels may go in a proposed mapping file, not applied.
5. **Keep rare but asked terms:** any surface or label a bank question names stays regardless of frequency, including `tailwind`, `monsoon`, `repo`.
6. **New gate report:** coverage by uses and by company spread, not only a surface count; before and after, assuming the proposals are approved; and how many new topics that takes. Delete nothing: unlabelled surfaces stay searchable as `other:<raw>`.

## Acceptance checks
- Review file has at least 500 rows with evidence.
- The report states honestly how far short of 95% this leaves us, and what else would close the gap.
- Tests pass.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_vocab_claim.py -q
```
