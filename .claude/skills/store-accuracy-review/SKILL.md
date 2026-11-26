---
name: store-accuracy-review
description: Review and raise the accuracy of stores already built or being built, without ever blocking reading - check layers (filed XBRL, arithmetic), the 10% rule, status moves at load, fix-by-severity, reload touched symbols. Use for any "improve/review the database" work, after a grade, or when a new check or reader is added.
---

# Review and improve stores (Shivam 26 Nov 2026: consult, review, improve - never block)

Architecture: `docs/CONTINUOUS_STORE_ARCHITECTURE.md`. Rulings: `docs/rulings/RULINGS_VERBATIM.md` (26 Nov entries).

## Never do
- Put a `.hold` on a reader, stop a hy4 loop, or refuse a load because a grade failed or is missing.
- Edit a read row in place. Reads are append-only; corrections live in checks.
- Trim a rule to fit a file: the full wording goes to `docs/rulings/` (skill `record-ruling`).

## The only block
More than 10% of the database corrupt. A doc type output whose LATEST graded sample is > 10% W+J loads with its
`verified` rows as `unverified` (`read_gate.verified_allowed`, `load_observations._cap_unverified`). That is a label,
not a stop.

## Check layers (verdict files keyed by source DB + observation_id; never edit the read)
| Check | Code | Verdicts -> status at load |
|---|---|---|
| Filed XBRL (results P&L quarters) | `reality_engine/v2/xbrl_crosscheck.py --db <hy4 db>` -> `D:/RealityEngine/checks/xbrl/` | match -> verified (even in a capped type); unit_fix / contradicts -> unverified |
| Arithmetic (sums, subset-as-total, sign, 100x jump) | `reality_engine/v2/arith_checks.py` (T-242, DeepSeek de0ee829) -> `D:/RealityEngine/checks/arith/` | flagged -> unverified |
| Model settles | Sonnet/Gemma verdicts (`load_observations.CHECKS`) | advisory `check_status` |
Add a new check the same way: a module + CLI writing `{id, verdict, evidence, checker}` JSONL, register its dir in
`load_observations`, map verdict -> status in `_apply_check_status`, test in `reality_engine/tests/`.

## Loop
1. Measure: 60-row grade per output DB every 2,000 pages (skill `checkpoint-grade`, Hydrogen/DeepSeek grader);
   record counts R/P/W/J; W+J share per doc type.
2. Rank defects: companies hit x severity (wrong number > wrong line/subset > wrong tag). Read 3 rows yourself first.
3. Fix: structural rule (never per company) by the ladder (skill `model-ladder`); recheck a COPY
   (`observations --recheck --baseline <copy>`), 0 graded-R rows may change status.
4. Swap: backup `<db>_before_<fix>_<date>.db`, carry over rows newer than the copy, move in (skill `hy4-store-load`).
5. Re-run checks (`xbrl_crosscheck`, `arith_checks`), reload touched symbols only:
   `python .tmp/load_symbols.py --from-db <hy4 db>` (log C:/RealityEngine/t242/load_symbols.log).
6. Report to Shivam in plain words: rows fixed, rows promoted/demoted, sample errors with real values.

## Pitfalls seen
- Loader reading a DB a hy4 loop is writing: `_ro` waits 300 s; never kill the loop.
- `filing_events` needs `T228_STORE_ROOT=C:/RealityEngine/tg_build/full394` with `--stores`.
- Grader "R" hides wrong rows: re-read a random 10 of its R plus suspicious ones before recording.
- XBRL covers P&L quarters only; empty basis is never called wrong; segment rows never compared to totals.
