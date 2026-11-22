# T-230 stage K brief: annual-report observations - measure aliases, basis and period from headers (model-free)

Ticket: T-230 (Shivam 22 Nov 2026: "you can start the work"). Reviewer: Wolf (Opus). Use the fix loop
(`docs/FIX_LOOP.md`, `regress.py`, `--only`). No model calls: script rules and `--recheck` only.

Goal: the 91-company annual-report read (`.tmp/t230ar/obs_ar_91.db` in the MAIN checkout
`C:/Users/warri/Downloads/Info_Diffusion_Model`; rechecked copy `.tmp/t230ar_rc/obs_ar_91_rc.db`) is 98,624 verified /
319,266 unverified / 6,300 quarantined. Wolf's breakdown of unverified reasons (a row can carry several):
measure not in dictionary 215,770 (23,250 distinct invented names; top 500 = 45% of rows), basis_conflict 94,108
(67,742 with empty basis), no_period 86,094, printed_axis/label not in text layer ~40k, no_unit 19,812.
Most unmapped names are governance/compliance (shareholding %, workers, share price high/low, section references, AGM
number, sitting fees, complaints): leave those unverified. Recover the real driver figures only.

Evidence: the two DBs above (work on copies); `D:/RealityEngine/tg_build/measure10` stores (read-only); measure
dictionary + `measure_alias` in `reality_engine/v2/observations.py`; examples of driver-relevant invented names in the
top 40: dividend_per_share (654 rows, 58 cos), total_comprehensive_income (460), other_comprehensive_income (412),
accumulated_depreciation (718), csr_amount_spent (745), statutory_dues_disputed (415), count.employees (1,747),
employee_turnover_rate (464). Query: `select measure,count(*),count(distinct symbol) from observation where
status_reason like '%not in the dictionary%' group by 1 order by 2 desc`.

Steps:
1. Alias pass: for the top 500 unmapped names, map a name to an EXISTING dictionary measure only when the meaning is
   the same (e.g. dividend_per_share -> the dictionary's DPS measure); add genuinely new driver measures (revenue,
   cost, margin, capex, capacity, debt, equity, working capital nodes) with observed aliases only; everything else stays
   unmapped. Write the mapping table to `D:/RealityEngine/t230/stageK_aliases.csv` (name, rows, companies, action,
   target, reason) - or `.tmp/t230k/` if D: is denied - so Wolf can review it.
2. Basis from headers: on annual-report pages, take basis from the printed page/column header ("Standalone",
   "Consolidated") nearest above the value; a page that prints both takes the column's header; empty basis stays a
   conflict only when no header is found.
3. Period from headers: column header years ("FY 2024-25", "31 March 2025", "2024-25") set the period when the row has
   none; never guess.
4. Scoped recheck: `--only` selector of affected rows into `.tmp/t230k/obs_ar_91_k.db`; regress on it and on
   `D:/RealityEngine/t230/obs_91_i.db` (decks; must not change except via aliases): gate 0 newly broken.
5. Tests per rule (synthetic); doc: V2_SCHEMA_CONTRACT section 17 stage K.

Files: `reality_engine/v2/observations.py`, `reality_engine/tests/test_observations.py`, `docs/V2_SCHEMA_CONTRACT.md`.
Do not edit tasks/STATE.md. If git in your worktree is blocked, say so.

Pitfalls: a deck reader job appends to `.tmp/t232read/obs_decks394.db` in the main checkout all day - never touch it;
do not map governance counts onto driver measures; an alias must not change any golden RIGHT row's measure.

Accept: tests pass; typecheck clean; regress gates pass; report under 20 lines: aliases added (rows, companies),
verified before/after on the AR copy, rows changed per rule, 10 sample changed rows with page refs for Wolf's read.

Stop if: any rule needs a model call; a newly broken golden row you cannot explain.

Budget: about 2 hours, DeepSeek max effort.
