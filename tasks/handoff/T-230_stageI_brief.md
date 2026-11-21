# T-230 stage I brief: generalisation fixes from the first read of NEW companies (model-free)

Ticket: T-230 (Shivam 21 Nov 2026). Reviewer: Wolf (Opus). Use the fix loop (`docs/FIX_LOOP.md`, `regress.py`, `--only`).
hy4 quota is out until ~05:30 IST: this stage must be script/recheck only, no model calls.

Goal: the first deck read of the 394 non-91 Telegram companies (`.tmp/t232read/obs_decks394.db` in the main
checkout, 1,071 pages / 57 companies so far, a job may still append to it after 05:30 - work on a copy) graded 50
verified = 37 right / 7 minor / 6 wrong (12%) and 10 unverified = 9 correct values, 6 of them blocked by a check.
Detail (read it): `D:/RealityEngine/t232/wolf_read_decks394_a.md`. Rules tuned on the 91 do not all generalise.

Fixes (each with a selector, a scoped recheck, tests):
1. Per-unit measures never take a crore/lakh/million scale: EPS, DPS, book value per share, Rs/kWh, Rs/unit,
   INR/sq ft, per tonne, per kg, per MW... (ids 974 ADANIPOWER 5.53 Rs/kWh at 1e7; 20613 IRCON EPS 4.57 at 1e7);
   274 verified per-unit rows carry such a scale. "tn"/"trillion" -> 1e12 (22406 AFCONS Rs tn 38.5 at scale 1).
2. Axis-tick rule (stage H) must apply only to chart pages, never to tables: on the new companies it flags 1,208 rows
   (4.3%; 932 on balance-sheet/P&L/cash-flow tables, e.g. 27274 ASTRAMICRO intangible assets 3) vs 0.7% on the 91.
   A table row (label + values across period columns) is never an axis ladder.
3. Not-a-period strings ("Y-O-Y", "YoY", "QoQ", "growth", "vs") are never a period: take the period from the printed
   axis/column header/page header, else no_period (12734 BRAHMINFRA; 157 verified rows).
4. Unit families: "lakh sq ft", "mn sq ft", "sq ft" are area (not money); "BU", "billion units", "MU" are energy (not
   count).
5. Normalise Unicode dashes/hyphens (U+2010-U+2015, U+2212) and NBSP before label matching.
6. Dictionary: add area delivered / area under construction (real estate) and water intensity / energy intensity
   (ESG; node none with reason) with observed aliases only.
7. "crossed Rs X", "over Rs X", "more than", "exceeds" -> a lower bound: value_kind lower_bound, never verified as the
   actual figure. India / industry peak demand, market size and similar are entity_scope country/industry
   (20160 ADANIPOWER 243 GW peak demand stored as capacity.total).
8. Footnote basis: a footnote that names a period's basis ("FY24 figures are standalone") overrides the page basis
   for that period (20120 RAJESH).
9. Golden: append every graded row of `wolf_read_decks394_a.md` to `reality_engine/tests/golden/observations.jsonl`
   keyed as T-233 does, so these new-company rows guard future changes.

Run: scoped recheck on a copy of obs_decks394.db -> `.tmp/t230i/obs_decks394_i.db`, and on
`D:/RealityEngine/t230/obs_91_h.db` -> `.tmp/t230i/obs_91_i.db`; `regress observations` on both (gate: 0 newly
broken). Report under 20 lines: per fix rows changed on each DB, how each cited id comes out, status counts before
/after, regress summary.

Files: `reality_engine/v2/observations.py`, `reality_engine/tests/test_observations.py`,
`reality_engine/tests/golden/observations.jsonl`, `docs/V2_SCHEMA_CONTRACT.md` (section 17 stage I). No other file;
do not edit tasks/STATE.md. If git in your worktree is blocked, say so; Wolf carries files over.

Accept: tests pass; typecheck clean; regress gates pass on both DBs.

Stop if: any fix needs a model call; regress shows a newly broken row you cannot explain.

Budget: about 2 hours, DeepSeek max effort.
