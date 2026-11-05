# Worker: KPI precision, on a goal brief

Goal: a person reading 20 random `kpi_series` rows against their quotes finds at least 18 right for INFY and for HINDALCO, and no other company gets worse. How you get there is yours to decide. This round tests a goal brief: no edit list is given.

Ticket: T-079

Evidence: measured on 4 Nov (T-064), hand read seed 20261113: INFY 12 of 20, HINDALCO 7 of 20, HINDUNILVR 18 of 20. Wrong classes seen then:
- USD tables stored as crore;
- six-month figures dated to the quarter;
- the year token "2026" stored as revenue;
- capex commitments stored as capex;
- Novelis and segment income stored as the company total.

T-073 changed `_ytd_period` and `find_dimension` since then, so re-measure first with a fresh seed. Code: `reality_engine/pilot3/kpi.py` (about 2,000 lines, use `outline`), `reality_engine/pilot3/lexicon/`. Rules in guide O2 of `docs/DEVELOPER_GUIDE.md`.

Data: `D:\RealityEngine\pilot10\scratch\w_t079.db`, copied from `D:\RealityEngine\pilot10\pilot10.db` by sqlite3 `backup`. Never write `pilot10.db`. Fast checks:
- `python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part kpi --symbols INFY --out D:\RealityEngine\pilot10\scratch\w_t079.db`
- `python -m reality_engine.pilot3.checkpages run --work D:\RealityEngine\pilot10\scratch\cp_t079`, a few seconds.

Check free RAM first and wait above 2.5 GB: ten answer workers are using this machine and the HP. One heavy job at a time. Build the other companies last, once.

Accept:
1. Hand read: first a before read of 20 rows per company on the copy, fresh seed, written to `.tmp\kpi_before.tsv`. After the fix, a read with a second fresh seed, written to `.tmp\kpi_after.tsv`: row, quote, right or wrong, why. Read the quote, do not infer. INFY and HINDALCO at least 18 of 20; print all ten companies, none lower than its before read by more than one row.
2. `python -m reality_engine.pilot3.checkpages run`: at least 145 found.
3. A1: `python -m reality_engine.night_eval.answerable --db D:\RealityEngine\pilot10\scratch\w_t079.db --qset tasks/night_loop/questions/dev.jsonl --out D:\RealityEngine\pilot10\scratch\a1_t079.json`: live is 759 of 898; per company, none below live. Do not change the grader.
4. `python -m pytest reality_engine/tests/test_pilot3_kpi.py -q`, new tests from real rows. `mcp__code-tools__typecheck` on changed files: no new errors.

Rules: general rules only, no company names in code. Not tuned to a seed. Do not run `guards`. Do not read any question or grade file.

Files: `reality_engine/pilot3/kpi.py`, `reality_engine/pilot3/lexicon/*.yaml` except `results_lines.yaml` and `topics.yaml`, `reality_engine/tests/test_pilot3_kpi.py`, your lines in `docs/PILOT3_BLUEPRINT.md` and guide O2. Do not touch `tasks/`, not even `tasks/STATE.md`: Opus keeps it.

Stop if: free RAM stays under 2.5 GB for 10 minutes, or the targets stay out of reach after three rule rounds; report the rows that stop you.

Budget: 120 tool calls. End with the two reads, A1, checkpages, tests and a `Docs updated:` line, and tell me how the goal brief compared with an edit list: where you lost time and what evidence you wished you had. Then wait: Opus reviews in this same session.
