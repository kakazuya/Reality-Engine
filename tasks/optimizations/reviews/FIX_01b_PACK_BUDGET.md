# Task — bring the worker context pack back under its 25k-token budget

## Goal
`python -m reality_engine.scripts.build_worker_context` writes `tasks/worker_context/CONTEXT.md` at ≤ 20k tokens
(chars/4) and exits 0 (today: 30,120 tokens, exits 1 with "over the 25000 token budget").

## Why
Task 01's acceptance requires ≤ 25k; the pack grew past it when the toolbelt, code-intel and `SANDBOX.md` (included
verbatim, 187 lines) landed. Every worker reads the whole pack first, so each extra 1k tokens is paid on every job. A
measurement tonight found no orientation benefit from the 27k pack, so smaller is strictly better.

## Files to touch
- `reality_engine/scripts/build_worker_context.py` — trimming logic.
- `reality_engine/tests/test_dsh_worker_plugin.py` — adjust/add builder tests.
- Do not touch: `tasks/worker_context/SANDBOX.md` itself, `plugins/dsh-worker/server/*`, any database.

## Steps
1. Measure each section's size in the current output.
2. Replace the verbatim `SANDBOX.md` section with a ≤ 25-line digest (permission → mode table, temp/pip rules,
   write scopes incl. `confirm_repo_root_write`, commit/launch request names) plus its path for detail.
3. Trim the repo map (fewer most-referenced scripts, one-line module entries, drop leaf dirs with no docstring).
4. Add a short "Tools" section (≤ 10 lines): toolbelt commands (`reality_engine/toolbelt/README.md`) and the
   `mcp__code-intel__*` tools — "use before grep".
5. Keep the data map (it carries the curated descriptions) and the query/test/conventions sections intact.

## Acceptance checks
1. Builder exits 0; reported estimate ≤ 20,000 tokens; all 7 sections present; runtime < 60 s.
2. Two runs identical except the `Generated:` line.
3. The data map still has curated descriptions for every listed table (count them; report the number).
4. `python -m unittest reality_engine.tests.test_dsh_worker_plugin` passes.
5. `git diff --stat` touches only the files above (do not commit the regenerated CONTEXT.md; Claude does).

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_dsh_worker_plugin
python -m reality_engine.scripts.build_worker_context --data-root C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data --out-dir .tmp/pack
```

## Budget
- ≤ 25 tool calls before the first edit; ≤ 100 total; ≤ 45 min wall; $0 paid.

## Report format
1. What changed  2. How verified (section sizes before/after)  3. Outside-sandbox steps  4. Open problems
5. Tool calls before first edit / total.

## Out of scope
Changing the `context_pack` default; changing what the standing header says.
