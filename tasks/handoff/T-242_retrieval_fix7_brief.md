# T-242 brief: retrieval fix 7 (company figures first; audit-7 causes C1-C3)

Goal: company-number tools serve the company's own figure first (other scopes labelled, never first), paraphrased statement asks find the asked sentence inside a named call, guidance elects the group full-year target, and a served number matches the asked period with no segment/division scope.
Files: plugins/reality-data/server/lookups_pilot3.py, plugins/reality-data/server/server.py (descriptions only if behaviour changes), plugins/reality-data/tests/test_retrieval_fix7.py (new), docs/DEVELOPER_GUIDE.md, machines/MSI_LAPTOP.md
Accept: python -m pytest -q plugins/reality-data/tests/test_retrieval_fix7.py plugins/reality-data/tests/test_retrieval_fix6.py plugins/reality-data/tests/test_retrieval_fix5.py plugins/reality-data/tests/test_retrieval_fix4.py plugins/reality-data/tests/test_retrieval_fix3.py plugins/reality-data/tests/test_retrieval_fix2.py plugins/reality-data/tests/test_lookups_pilot3.py passes; replay of audit 7 (48 rows) AND audit 6 (48 rows), stores pinned mode=ro: audit-7 non-R rows gain >= 8 R, 0 R lost in either audit.
Evidence: C:/RealityEngine/t242/retrieval_audit7/report.md (48 rows, exact calls; stores c631 c229 c355 c136 c274 c503 c257 c319 under C:/RealityEngine/tg_build/universe_fy27/) and C:/RealityEngine/t242/retrieval_audit6/report.md (c346 c75 c317 c12 c347 c1718 c783 c500).
Stop if: a change needs a store schema change or rebuild; a rule is per-company; you lose an R row and cannot fix it in 2 tries.
Budget: ~130 tool calls.
Ticket: T-242

## 1. Company figures first (Eagle's count, 26 Nov)
Served stores hold 13,031 obs_fact rows status='verified' with entity_scope in (industry, country, peer, customer): AR 7,139, deck 4,142, transcript 1,750. `lookups_pilot3.py` never reads entity_scope, so a company question can get an industry/country figure as the verified answer.
Fix: in fact / kpi / fin-from-obs / guidance / topic number rows, sort entity_scope in (company, '', NULL, subsidiary with a named subsidiary) first; rows of other scopes go to `alternatives` labelled `scope: industry figure` / `country figure` / `peer figure` / `customer figure`, and are never the first answer. Show `entity_scope` on every obs row served.

## 2. C1: paraphrased asks inside a named call (9 P of 16)
ARE&M named call 2026-08-11, `statements("capex", rank_terms="How much will they invest this year and where?")`: the asked sentence "during FY27, we estimate to spend around INR1,700 crores ... INR1,300 crores" is rank 24. Fix 6's all-ask-words rule fails on paraphrase; whole-turn word counts win.
Fix: score SENTENCES (not turns) by: topic/measure synonyms (capex ~ invest/spend/capital expenditure; demand ~ volume/offtake; margin ~ EBITDA/profitability; use the existing measure alias map + a small synonym table, structural, not per-company), presence of a figure + period in the sentence when the ask is quantitative ("how much", "what", "target"), then proximity. When the top 25 tie, widen to fill the byte cap rather than cutting a matched target (2 targets were beyond shown=25 with matched_total including them).

## 3. C2: guidance election (3 P, 1 M of 8)
ARE&M `guidance("capex","FY27")` -> 2,320 cr first (a wholly-owned subsidiary board approval) while the company's FY27 estimate 1,700 cr is row 3; ASALCBR FY27 EBITDA margin 13-14% (a brand) first while the call prints the company figure; BAROEXT growth held in obs_fact as `NEW:<...>` placeholder measure -> found=false.
Fix: prefer the row whose quote/segment is the company or group and the full year (no WOS/subsidiary approval, brand, division, segment) ; match obs_fact guidance by printed label words when the measure is a NEW: placeholder.

## 4. C3: period / scope on numbers (1 W, 3 P of 24)
BMW `fact("capex","Q2 FY27")` -> 516.4 cr labelled Q2FY27 but the page says cumulative "As on 30th September 2026" (W); ASALCBR EBITDA margin Q2 FY27 -> 2.0% (ethanol division) first; ANANDRATHI `AUM` -> 18.4% (growth) first; ARE&M EBITDA margin Q2 FY27 -> 10.1% (H1) first.
Fix: a served first row must match the asked period kind (quarter vs half vs as-on vs year) and unit family of the measure (AUM is money, not %), and carry no segment/division scope; otherwise demote to alternatives.

## Limits
Read stores only (mode=ro); no model calls; do not touch hy4 readers or D:/RealityEngine/hy4_out. Never kill processes by name. pytest per file. Report: changed file:line, tests, both replay tables (before/after per row), docs.
