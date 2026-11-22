# T-238 stage N2 brief: tighten stage N's period fill-in (it failed the hand-read)

Ticket: T-238 (Shivam 23 Nov 2026). Reviewer: Wolf (Opus).

Goal: an independent Opus hand-read of 20 stage-N upgrades (`D:/RealityEngine/t238/stageN_grade.md`, read it) gave
measure remap 9/10 right, basis fill-in 3/5 right + 2 minor, but **period fill-in 0/5 right (4 minor, 1 wrong)**:
- KPIL "75 countries" got FY25 with `period_source='slide_title'` though the title prints no year;
- REPL "1023 acres" took "FY 24" from the page footer, and the acres are a client project's, not REPL's;
- INFOBEAN "42 clients" took a truncated "9M 2025" that labels only the financials row on that slide;
- IRCON 28.50% other-income growth FY24 vs FY23 stored as FY23;
- JWL "697 BOM wagons" is an order size stored as volume.sales.
Also unscoped rows read as company totals: ADANIPOWER 708 GW = India 2047 peak demand; NISMGMT ₹1.94 Cr = one
customer's orders. The deck copy `D:/RealityEngine/t238/deck_n.db` is NOT promoted until this passes.

Evidence: `reality_engine/v2/observations.py` stage N (`slide_period`, `fiscal_periods`, `deck_basis`, `deck_asof`,
`force_fit_veto`), section 17 stage N in `docs/V2_SCHEMA_CONTRACT.md`; graded rows above with page refs.

Steps:
1. `slide_title` period only from the slide's title line (top text block, not footer/header furniture, not a
   table row label), only when that title prints exactly one fiscal label and the value is not inside a multi-column
   table; never from a truncated label ("9M 2025" when the page prints "9M 2025-26").
2. `deck_asof` only for a closed list of snapshot measures (capacity.*, shareholding_pct, count.shares,
   plant/locations counts); never for counts such as customers, countries, employees, orders, or for any ratio/growth.
3. A growth/change row (`*_growth_yoy`, `*_change*`) takes the later period of the printed pair, never the earlier.
4. Scope: a value whose label/heading names a country/industry/market ("India", "peak demand", "industry", "market
   size") or a named client/customer/project gets `entity_scope` country/industry/customer and never verifies as a
   company measure; order quantities ("wagons", "units ordered", "order for") are never volume.sales.
5. Recheck the stage-N copy with the tightened rules into `D:/RealityEngine/t238/deck_n2.db` (if D: denied, the
   worktree `.tmp/t238n2/`), report how many stage-N upgrades revert per rule, regress obs_91_i (0 newly broken),
   and list 20 new random upgraded rows (period rule only) with page refs for Wolf's hand-read.
6. Tests for each case above (synthetic); doc update stage N2.

Files: `reality_engine/v2/observations.py`, `reality_engine/tests/test_observations.py`, `docs/V2_SCHEMA_CONTRACT.md`.
Do not edit tasks/STATE.md. Jobs write `D:/RealityEngine/t238/obs_transcripts_91o.db` and `.tmp/t238read/obs_91_j.db`
in the main checkout: never write them.

Accept: tests pass; typecheck clean; regress gate 0 newly broken; the 5 period cases and 3 scope cases above come out
right in the recheck.

Stop if: a rule needs a model call.

Budget: about 2 hours, DeepSeek max effort.
