# Task — gate blockers: the EVENT hop (140), RIPPLE period (80) and RIPPLE hop (38)

## Goal
The full gate run on main (`tasks/answer_bench/GATE_RUN_2026-10-29.md` §4, commit `3489a87`; strict 137/2,681 = 5.1%) lists these blockers:
- **140** cases where the EVENT hop fails ("fetch: event_day0 + announcement dissemination index"). But `event_day0` **is built**: 3.01 M rows in `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\pilot\pilot60\market_state_pilot.db`. The announcement index is `bse_announcements.db:ann`, which now has the `idx_ann_sym_dissem` index.
- **80** cases where the RIPPLE rows fall outside the asked period. The period fix (`820202c`) covered SERIES, EVIDENCE, FACTS, SCREEN and COMPARE, but not RIPPLE.
- **38** cases where the RIPPLE hop fails (macro claim target + sector transmission; `company_sector_pit` is in the T1 build, `macro_all.db` on the SSD).

## Do
1. EVENT planner (`reality_engine/query/planners/event.py`):
   - read `event_day0` from the T1 store through `Ctx`;
   - apply the 15:30 IST day-0 rule: filed before 15:30 means day 0 is T, after means T+1;
   - use a 4-session diffusion window;
   - resolve the event from `ann` (symbol + DissemDT window), with the PIT rule `known_at` ≤ as_of.

   Rows carry the ISIN, the event date and the concept (results, order win, rating action, …).
2. RIPPLE planner (`planners/ripple.py`): honour the router's resolved window (`slots` `date_from`/`date_to`/`period_label`) through `planners.in_period`, the same way the other planners now do. Use `company_sector_pit` for the sector hop and `macro_all.db` for the claim → target map.
3. Add tests per fix: the day-0 rule at 15:29 vs 15:31, a RIPPLE row outside the window dropped, and a sector hop as-of.
4. Re-run the full bank, one bench process at a time: `python tasks/pilot60/gate_run.py bank --resume --chunk 100`, then `hand60`, `grade` and `report`. Report the before/after for each blocker and the strict total.

## File scope
Allowed: `planners/event.py`, `planners/ripple.py`, their tests, and `ctx.py` (T1 alias only).

Do NOT touch:
- `gate.py`;
- the period code of the other planners;
- the concept routing (another worker owns it).

## Rules
- Pilot DBs are read from the SSD paths only; never from D:. Live DBs are read-only. Use no paid models and no LLM in the query path, and make no commits.

## Acceptance checks
- `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"` passes.
- EVENT hop failures fall by ≥60% and RIPPLE period failures reach 0, with 0 PIT breaches and no new WRONG in hand-60.

## Test command(s)
```bash
python -m unittest discover -s reality_engine/tests -p "test_query_*.py"
```

## Report
Give:
- the before/after per blocker;
- the new strict total;
- 10 hand-checked EVENT answers;
- what's left;
- your tool-call count.
