# T-230 stage L brief: tighten the checks that stage K's annual-report upgrades slipped through (model-free)

Ticket: T-230 (Shivam 22 Nov 2026). Reviewer: Wolf (Opus). Fix loop: `docs/FIX_LOOP.md`, `regress.py`, `--only`.
No model calls.

Goal: stage K (merged 949eb09b) moved 6,384 annual-report rows from unverified to verified
(`.tmp/t230k/obs_ar_91_k.db` in the MAIN checkout `C:/Users/warri/Downloads/Info_Diffusion_Model`; baseline
`.tmp/t230ar_rc/obs_ar_91_rc.db`). Opus hand-read 24 random upgraded rows against the page images: **11 right /
9 minor / 4 wrong** - not acceptable for "verified" (ruling: zero wrong rows verified). Grades with reasons:
`D:/RealityEngine/t230/stageK_read/grade{1,2,3}.md`, rows `batch{1,2,3}.jsonl` (observation ids inside).

Evidence (defect classes, ids in the grade files):
1. Parts-sum proof passes on degenerate parts: every value 0, or every value equal (DIVGIITTS p125 "Other" = 0 stored
   as count.beneficiaries; MANINFRA p111 complaints 0; ESTER: 39,99,800.01 matched another fund's unit count).
2. Generic row labels on BRSR / notes pages ("Other", "Male", "Total Employees", "Wages", "Interest Cost") stored under
   a measure the printed row does not mean (NAVKARCORP p162 gratuity interest cost -> finance_cost; KITEX 4,648
   permanent workers -> count.employees under "Male"; MANINFRA 494 trained workers -> count.beneficiaries; RANEHOLDIN
   Total (A) headcount -> training coverage).
3. Sub-row qualifier dropped: AVADHSUGAR count.employees = 1 from a "Permanent employees" sub-row (total 667).
4. Basis blank although the page header says consolidated ("Notes to Consolidated FS", "Group"): KRYSTAL p185,
   COSMOFIRST.
5. Period from an inline comparative "(31 March 2024 : NIL)" (ESTER); a closing balance "as at 31 March 2024" stored as
   the full year (BLKASHYAP).

Steps:
1. Parts-sum: a proof needs at least 2 non-zero parts with at least 2 distinct values and a printed total that is not
   itself one of the parts; else no proof (row keeps its other reasons). Apply in reader and `--recheck`.
2. Generic labels: when the printed label (and its row header) is a generic category word (gender, "Other", "Total",
   "Wages", "Interest Cost" under a benefit-obligation heading, etc.), the row verifies only when the group_path / table
   heading names the measure; else unverified with reason `generic_label`. Gratuity/defined-benefit tables never map to
   finance_cost. A BRSR sub-row (male/female/permanent/other) is a part, never the total measure.
3. Basis: page/section header "Consolidated", "Notes to Consolidated", "Group" sets consolidated (and "Standalone"
   standalone) when the row has none.
4. Period: a date inside an inline comparative bracket is never the row's period; "as at <date>" gives a point-in-time
   period (period_kind instant), not the fiscal year.
5. Golden: append the 24 graded rows to `reality_engine/tests/golden/observations.jsonl` (keyed like T-233: store,
   doc_key, page, measure, value_text; grade + reason), so annual-report rows have golden coverage.
6. Scoped recheck: (a) the 6,384 stage-K upgrades + every verified row whose proof was parts-sum, on a copy of
   obs_ar_91_k.db -> `.tmp/t230l/obs_ar_91_l.db`; (b) the parts-sum rule on copies of
   `D:/RealityEngine/t230/obs_91_i.db` and `.tmp/t232read/obs_decks394.db` (a reader job appends to the latter all day:
   copy it, never write it). Use `--sample 91` / `--sample 400` with `--stores-root` (the default sample is small).
   Regress each; report verified before/after per DB and per rule.
7. Tests per rule (synthetic); doc: V2_SCHEMA_CONTRACT section 17 stage L.

Files: `reality_engine/v2/observations.py`, `reality_engine/tests/test_observations.py`,
`reality_engine/tests/golden/observations.jsonl`, `docs/V2_SCHEMA_CONTRACT.md`. Do not edit tasks/STATE.md.

Pitfalls: a full recheck of ~200k rows takes ~45 min; start it once, in the background, and do not wait on it with
repeated sleeps - finish tests and docs meanwhile; if the 3 h limit nears, commit and report the command for Wolf.

Accept: tests pass; typecheck clean; on the 24 AR golden rows no WRONG row stays verified and no RIGHT row is lost;
deck regress 0 newly broken; report under 20 lines with per-rule counts and verified before/after per DB.

Stop if: a rule needs a model call; the parts-sum change downgrades more than 2% of verified deck rows (report first).

Budget: about 2.5 hours, DeepSeek max effort.
