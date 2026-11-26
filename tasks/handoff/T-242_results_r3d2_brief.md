# T-242 brief: results r3d2 - the ambiguous-duration rule abstains outside a two-values-one-date group (dsh DeepSeek, 27 Nov, Wolf)

Ticket: T-242
permission: workspace-write (worktree)
Base: branch dsh/20261126T151707Z-ee04de04 (r3e on r3d).

Goal: r3d's `results_period_duration_ambiguous` rule downgrades 8 rows graded R (found by the r3e worker, confirmed in
Eagle's review): ASARFI 48901, AAVAS 8962, BBTCL 3906, AKSHOPTFBR 11178 / 11185, AMITSEC 37761, AEONXDIGI 26019,
AVONMORE 94458 (observation ids in C:/RealityEngine/t242/results_r3d/base.db). r3d was meant only for one label holding
TWO values for one date key. Change the rule so it ABSTAINS (keeps the row's existing period and status) unless the row
belongs to such a group (same doc, page, measure/label, date key, two or more distinct values); inside a group the r3d
behaviour stays (duration by column position, else the bare date).

## Steps
1. Read the rule in reality_engine/v2/observations.py (search `results_period_duration_ambiguous`) and its r3d tests.
2. Reproduce the 8 rows as unit tests from their page text (stores under C:/RealityEngine/tg_build/universe_fy27,
   read-only `mode=ro`, timeout=300; the row's doc_key/page are in base.db): each keeps its period and status.
3. Keep r3d's own evidence tests (AGARWALEYE, AANCHALISP, AMERISE two-values cases) passing, and every r3e test.
4. Docs: one line in the DEVELOPER_GUIDE.md r3d bullet; tasks/t242_results_measure.md.

Files: reality_engine/v2/observations.py, reality_engine/tests/test_results_gates.py, docs/DEVELOPER_GUIDE.md,
tasks/t242_results_measure.md.
Accept: python -m pytest -q reality_engine/tests/test_results_gates.py ; test_observations.py ; test_ar_sections.py ;
test_deck_guards.py - each separately, pass; the 8 rows unchanged; r3d's two-values cases still resolved.
Stop if: the abstain breaks an r3d evidence case after 2 tries: report and stop. Hard stop 05:30 IST (Shivam: operations
stop by 08:00).
Pitfalls: pytest, not unittest; never write under C:/RealityEngine or D:/RealityEngine; no model calls; never kill
processes by name.
Budget: ~1 hour, ~80 tool calls.
