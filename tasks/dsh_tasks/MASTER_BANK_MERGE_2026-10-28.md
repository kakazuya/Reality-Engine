# Task — merge every question bank into ONE deduplicated master bank, then the gap analysis

## Goal
This is step 2 of the golden rule (`AGENTS.md`, top). Shivam approves only ONE merged master bank, never a single bank on its own. The banks are:
- Shivam's 30 originals: fixed regressions, listed in `tasks/QUERY_TEMPLATES_2026-10-27.md` §5. Full texts are in `tasks/DB_QUALITY_TEST_2026-10-24.md`, `tasks/optimizations/measure/QA10_BRIEF.md` and `tasks/optimizations/measure/EVAL25.md`.
- `tasks/QUESTION_BANK_300_2026-10-27.jsonl`: the variations.
- `tasks/QUESTION_BANK_OPEN_2026-10-27.jsonl`: 300 open questions.
- `tasks/QUESTION_BANK_RIPPLE_2026-10-28.jsonl`: 200 ripple questions, each with a hop chain.
- **The Reddit bank (200 questions, a quarter technical) does not exist yet.** Build the pipeline so it can be re-run with the Reddit file added. Its expected path is `tasks/reddit_mining/QUESTION_BANK_REDDIT_2026-10-28.jsonl`.

## Do
1. **`tasks/master_bank/build_master_bank.py`:**
   - Load every bank into one common schema: `mid`, `source_bank`, `source_qid`, `question`, `entities`, `entity_level`, `family` (1–20), `archetype`, `period`/`as_of`, `answer_kind`, `rubric` (evidence, steps, forbidden, ground_truth), `coverage` (verdict, note, gap), `chain` (ripple only), and `style` (terse / natural / Hinglish / point-in-time).
   - Missing fields stay null; never invent them.
2. **Dedupe in two layers:**
   - **Exact or near-duplicate text:** normalise case, punctuation and numbers, then token Jaccard ≥ 0.8.
   - **Same "case":** the same template (family + answer_kind + entity level + the shape of the evidence needed) asked of the same entity and period, even with different wording.

   Keep one representative per case: prefer the row with the richest rubric and a ground truth. Record every merged duplicate under `duplicates: [source_qid…]`. Keep wording variants that test **naming** (ISIN, BSE code, old symbol) or **style** (Hinglish, terse, as-of) as separate cases: those are robustness tests, not duplicates.
3. **Coverage matrix** over the unique cases: family (1–20) × entity level (stock, industry, sector, theme, index, market-cap bucket, price band, policy, macro, market-wide) × style. Flag empty and thin cells (fewer than 3 cases). Shivam's 30 originals are always kept and tagged `regression: true`.
4. **Gap roll-up:** merge every gap named in the banks into one deduplicated list:
   - G0–G12 from `tasks/BACKWARD_REQUIREMENTS_AUDIT_2026-10-27_REPORT.md`;
   - NG01–NG29 from the open bank;
   - the 41 proposals in `tasks/RIPPLE_SCHEMA_REQUIREMENTS_2026-10-28.md`.

   For each gap give:
   - the unique cases it blocks;
   - whether data we **already hold** could close it (name the store, table or column; check with bounded `connect_ro` queries, e.g. `mkt_commodity_daily` already holds 13 commodity series);
   - whether it needs a **new fetch** or is truly **NOT IN DATA**.
5. **Output:**
   - `tasks/master_bank/MASTER_BANK.jsonl` and `MASTER_BANK.md`, readable for Shivam: a summary with counts per source bank before and after dedupe, the coverage matrix, then one table per family;
   - `tasks/master_bank/GAP_ROLLUP.md`, ranked by unique cases blocked per unit of effort, with a "closable from held data" column.

## Rules
- Read-only everywhere except this worktree. No network, no commits.
- Never open `results_notes.db` for writing.
- Don't rewrite question text, except to merge exact duplicates.

## Acceptance checks
1. Every row of every source bank maps to exactly one master case, either as the representative or listed as a duplicate. Report the counts.
2. All 30 originals are present with `regression: true`.
3. The coverage matrix and the gap roll-up are written.
4. Re-running with the Reddit file present works. Test this with a 5-row fake Reddit file in `.tmp`.

## Test command(s)
```bash
python tasks/master_bank/build_master_bank.py --check
```

## Report
Give:
- the counts per bank and unique cases after dedupe;
- the top 10 thin or empty coverage cells;
- the top 15 gaps with "closable from held data: yes/no";
- your tool-call count.
