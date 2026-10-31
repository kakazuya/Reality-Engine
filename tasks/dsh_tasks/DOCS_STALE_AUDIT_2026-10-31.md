# Task — find and clear stale docs that workers read

## Goal
Shivam found workers reading old copies and giving wrong assumptions. `tasks/STATE.md` was a log last updated 27 Oct, and the context pack fed its 24 Oct section to every worker as recent. It is now a short live state, with the old log in `tasks/archive/`. Clear the rest.

## Work
1. Inventory every `.md` under `tasks/` (top level, `tasks/arch_v4/`, `tasks/handoff/`, `tasks/optimizations/`, `tasks/pilot60/`, `tasks/efficiency/`), plus `AGENTS.md` and `tasks/worker_context/`. Skip `tasks/dsh_tasks/` except for point 4, and skip `tasks/archive/`.
2. For each doc decide, checking against `tasks/STATE.md`, the repo and the stores:
   - **Live:** still correct and used. Fix any wrong number, path, command or status in place.
   - **Report of its date:** a dated record that is still true as a record. Keep it, and if a later result overrides its headline, add one line at the top naming the newer file. For example `tasks/arch_v4/GATE_V4_2026-10-31.md` (8.2%), `tasks/arch_v4/REVAMPED_PLAN_2026-10-31.md` (baseline and "running" labels), `tasks/arch_v4/TRUTH_GRADE_2026-10-31.md` (calls the rule panel the authority; the read grade replaces it), and `tasks/efficiency/HP_ACCEL_BENCH_2026-10-31.md` (says the HP needs Python 3.13 for `cryptography`, but `cryptography` and `mcp` are on its 3.14).
   - **Stale:** an old hand-off or plan that points workers at finished or abandoned work. Move it with `git mv` to `tasks/archive/`, and fix any link to it.
3. Search live docs for references to moved files and for old headline numbers (`8.2%`, `10.2%`, `1.0%` gate, "read tasks/HANDOFF_", "read tasks/optimizations/HANDOFF"). Fix each one.
4. Briefs under `tasks/dsh_tasks/` for finished work: list them and move those whose job is merged to `tasks/archive/dsh_tasks/`. Keep briefs named in `tasks/handoff/QUEUE_2026-10-31.md` and `V4_COMMON_2026-10-31.md`. Keep all briefs that are not clearly finished.
5. Write `tasks/archive/README.md`: one line per moved file, with why it moved and what replaces it.

## Limits
- No file is deleted: `git mv` only. Do not rewrite dated reports beyond the one-line pointer.
- No code changes except a path that a move would otherwise break. Find these with a search over `reality_engine/` and `plugins/`.
- `tasks/FRAMEWORK.md` and the golden rule are Shivam's: report any contradiction, do not edit them.
- Do not touch `reality_engine/data/` or `Manual Dumps/`.

## Acceptance checks
- `tasks/archive/README.md` lists every move. A link check finds no live doc pointing at a moved path.
- `python -m reality_engine.scripts.build_worker_context` runs, and the pack holds no section older than the live state.
- Report: counts of live, dated and moved docs, and every number you corrected, old and new.
- Tests pass.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_doc_gate.py reality_engine/tests/test_hp_run.py -q
```
