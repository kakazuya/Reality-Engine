# T-242 brief: retrieval fix 8 (audit-8 causes: prepared-remark ranking, quarantined-but-printed KPIs, negated targets)

Goal: paraphrased statement asks find prepared-remark sentences, a KPI the page prints is not hidden behind found=false, and a target its own page disclaims is never served first.
Files: plugins/reality-data/server/lookups_pilot3.py, plugins/reality-data/server/server.py (descriptions if behaviour changes), plugins/reality-data/tests/test_retrieval_fix8.py (new), docs/DEVELOPER_GUIDE.md, machines/MSI_LAPTOP.md
Accept: pytest on test_retrieval_fix8/7/6/5/4/3/2 + test_lookups_pilot3.py passes; replay of audits 6, 7 and 8 (144 rows; audit 6 row 6 is regraded: the right answer is (26.9) cr consolidated, p4) against LIVE main (head 2aa900aa or later) and your branch, PYTHONIOENCODING=utf-8: 0 R lost in any audit, audit 8 gains >= 7 R.
Evidence: C:/RealityEngine/t242/retrieval_audit8/report.md (48 rows, exact calls, 8 stores; companies ADSL ALKEM BLUESTARCO AFFORDABLE INDIGO AZTEC ASARFI ACI); replay script pattern: copy C:/Users/warri/Downloads/Info_Diffusion_Model/.tmp/replay_f7.py and add the audit-8 rows.
Stop if: a rule is per-company; a rule needs a schema change; you lose an R and cannot fix it in 2 tries.
Budget: ~120 tool calls
Ticket: T-242

## Causes (audit 8)
C1 prepared remarks lose the ranking (6 of 16 statement asks M; all 6 sentences held in transcript_statement). Q04 ADSL "why are large enterprise deals taking longer to close" -> held p4 "large contracts are taking longer to conclude" absent from 13 rows; row 1 "So, there are a lot of partnerships...". Fix: a small structural synonym table for investor paraphrase (deal~contract/order, convert/close~conclude, customer~client/clientele, ...; reuse the fix-7 measure-word table), IDF-style weight so the rarest ask word outranks many common ones; prepared-remark sentences scored like Q&A ones.
C2 quarantined but printed KPI -> found=false (Q14 BLUESTARCO capex Q2FY27 130 cr transcript p8; Q20 AFFORDABLE orders 22 cr). Fix: when the ONLY match is quarantined and its quote prints the value with the asked label, serve it with check_status 'quarantined' and a warning field (never verified, never ahead of a verified/unverified row). Do not change the row checker.
C3 disclaimed or rule-noise targets elected (2 W, 2 M): Q18 BLUESTARCO guidance EBITDA margin FY27 serves 10% ("aspiring") while the same page says "no guidance at the moment ... get to 6.5%"; Q36 AZTEC serves NEW:capex_allocation_share percentages as capex; Q08 ALKEM fact cannot reach Rs 1,036 cr capex (no capital expenditure<->capex alias on the fact route). Fix: a target whose own quote or the next 2 sentences carry a negation/aspiration cue ("no guidance", "not guiding", "aspir", "hope to") is not elected first; for a money ask skip NEW:*share/*allocation/*_pct rows; add the capex alias to fact/fin.

## Limits
Stores read-only (mode=ro); no model calls; never kill processes by name; pytest per file. Report: file:line, tests, the 144-row replay diff vs live main, docs.
