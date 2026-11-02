# Gap loop review fixes, round 1 (T-048)

Ticket: T-048

Goal: Fix the defects Claude found reviewing branch `dsh/20261102T100413Z-ad726c64` (`reality_engine/gap_loop/`). Work in this worktree on top of that branch. Each defect is quoted from the code.

1. **One bad row fails the whole unit, and round 1 cannot pass.** `accept_answers` returns `False` on the first row whose check fails, and `check_answer_row` fails any number whose page is not in `kec.db doc_text` (`"source: page not in doc_text"`). In round 1 `doc_text` is empty, so every answer with a number fails, every unit burns 3 Haiku attempts, then DeepSeek, then escalates. Change: a unit fails only for a malformed report (not JSON, a qid missing, a bad status or gap type). A row whose number fails a check is stored with status `unverified` and the check's reason; it is not counted as answered, and it goes to the fix stage as gap type `unverified` (fix: put the cited page's text into `doc_text`, or cite a checkable source).
2. **Numbers from the stores cannot be checked.** Answers will cite the `reality-data` MCP (facts from `ar_facts`, `deck_figures`, `results_xbrl`, prices, holdings), not a `doc_text` page. Add a source kind: a number may carry `"tool": "<reality-data tool name>", "args": {...}` instead of `doc_key`/`page`. The loop re-runs that call in Python by importing the reality-data server functions from `plugins/reality-data/server/` (no MCP round trip, read-only, never with `REALITY_DATA_ALLOW_PAID_EMBED`), and the check passes only if the value appears in the returned record and, when a quote is given, the quote does too. Apply the as-of rule to the record's `known_at`/date. Update the answer prompt to describe both source kinds.
3. **Fix units are unbounded.** `fix_units` puts every question of one gap type in one unit. Cap a fix unit at 10 questions; split the rest into further units.
4. **Tier 2 start does not record approval.** `run_tier2` starts DeepSeek with `danger-full-access` and `write_scope="data"`; pass `approved_by="Shivam, 2 Nov: full permissions inside the T-048 sandbox"`.
5. **Escalation per unit hides which question failed.** When a unit escalates, write one escalation line per question that never got a valid row, with the last check reason for it.

Files: `reality_engine/gap_loop/` (checks.py, loop.py, tiers.py, store.py as needed), `reality_engine/tests/test_gap_loop.py`, `docs/DEVELOPER_GUIDE.md` section N.

Accept: `python -m pytest reality_engine/tests/test_gap_loop.py reality_engine/tests/test_doc_review_loop.py -q` passes with no model call, with new tests: a unit with one unverified row and nine good rows succeeds and stores the bad row as `unverified`; a store-sourced number passes when the re-run tool returns it and fails when it does not; a store record dated after as-of fails; 25 questions of one gap type become 3 fix units; tier-2 start carries `approved_by`. `python -m reality_engine.gap_loop --sandbox D:\RealityEngine\sandbox\kec_loop --dry-run` still exits 0.

Stop if: the reality-data functions cannot be imported without starting the MCP server (report what it would take); any change touches the question file, `tasks/RULINGS.md` or tracker files.

Budget: 90 minutes, about 80 tool calls.

Docs updated: required in your report.
