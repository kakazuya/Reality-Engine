# T-242 retrieval fix 1: serve the loaded hy4 rows (obs_fact) through the reality-data tools (Hydrogen, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: retrieval audit 1 (Hydrogen bd4e59df, 20 investor questions on 10 loaded universe companies) scored:
- 13/20 answers right;
- obs_fact rows used in 3/20;
- a better VERIFIED obs_fact row missed in 6-7/20.
Make the tools return the verified obs_fact rows first, without breaking the pilot stores (which have no obs_fact or
an older one) or any existing test.

Files: plugins/reality-data/server/lookups_pilot3.py, plugins/reality-data/server/server.py (INSTRUCTIONS), tests in
plugins/reality-data/tests/test_lookups_pilot3.py and reality_engine/tests/test_obs_wiring.py, docs (the reality-data
tool section of docs/DEVELOPER_GUIDE.md).

Evidence (store via `pilot3_sql(symbol=...)`; ids are obs_fact ids):
- Q1 AADHARHFC "AUM as of H1 FY27": pilot3_fact returned kpi_series id=280 (unverified, a ₹46 bn disbursement
  misread). The verified obs_fact id=9122 holds ₹32,643 cr.
- Q13 AUSTERE PBT H1FY27, Q17 BANSWRAS Yarn revenue / capacity utilisation, Q11 ASALCBR Alcobev revenue and EBITDA
  margin, Q19 BCLIND order book: pilot3_fact/pilot3_kpi returned found=false or a company-level line. Verified
  obs_fact ids: 40713/40695, 42639/42655, 64823/84895, 102635.
- Q4 ADFFOODS and Q18 BANSWRAS (management view): pilot3_statements appends obs_fact rows AFTER transcript_statement,
  and `_shrink`/row_cut(15) then deletes them. Verified rows lost: 66149/66141 and 100228/100252/100266.
- `_pick`/`_same_series` split only on '_', so dotted measures (capacity.utilisation, aum.value, order.book) never
  match. `_nearest` shows an obs_fact number row with statement "" and no value or unit.
- INSTRUCTIONS never mention pilot3_obs. pilot3_guidance ignores `period` for obs_fact and ranks legacy rows first.

Steps:
1. pilot3_fact and pilot3_kpi:
   - query obs_fact (record_type='number') next to the existing sources;
   - a VERIFIED obs_fact row outranks an UNVERIFIED kpi_series or page_cell row for the same metric and period, while
     a filed XBRL/fin row still outranks obs_fact;
   - fall back to obs_fact before found=false;
   - always label the row's status and source table.
2. Measure matching: split on [_.], strip 'NEW:', and add the aliases pbt -> profit_before_tax, gwp ->
   gross_written_premium, and capacity utilisation -> capacity.utilisation (extend synonyms.json where it fits).
3. `_nearest`: show value, unit, period, printed_label and status for number rows.
4. pilot3_statements:
   - apply latest, period, rank_terms and status to obs_fact statement rows;
   - merge them with transcript_statement BEFORE the row cut;
   - verified obs_fact statements rank first, and a transcript_statement duplicate of the same sentence is dropped.
   pilot3_guidance: pass period to the obs_fact query and rank verified rows first.
5. INSTRUCTIONS: name pilot3_obs, and say the structured tools now include the verified page reads (obs_fact). Keep
   the text short.
6. Tests: one per step, plus counter-tests (a pilot store without obs_fact answers as before; an XBRL line still wins).
   Run test_lookups_pilot3.py and test_obs_wiring.py.
7. Re-ask the audit's 20 questions (listed in the audit result below) through the CHANGED code: call the lookup
   functions in-process with the same arguments, not through the MCP server, which still runs the old code. Report
   before -> after per question: tool, source row, status, right Y/N. Target: at least 18/20 right, and every evidence
   row above returned. Commit in the worktree.

Audit questions (symbol: number question / view question):
- AADHARHFC: AUM H1FY27 / medium-term guidance.
- ADFFOODS: EBITDA margin Q2FY27 / freight, Truly Indian and Ashoka outlook.
- ADVENZYMES: EBITDA and PAT Q2FY27 / macro, Animal Healthcare, capital allocation.
- AEGISLOG: revenue and PAT H1FY27 / Kandla CRL-4 and pipelines.
- AJCJEWEL: capacity India and Sharjah / client onboarding.
- ASALCBR: Alcobev revenue and EBITDA margin Q2FY27 / margin pressure and IMFL growth.
- AUSTERE: revenue and PBT H1FY27 / funding.
- BAJAJFINSV: Bajaj General GWP and combined ratio Q2FY27 / Bajaj Life 2.0, GIFT City, Ind AS.
- BANSWRAS: Yarn revenue and utilisation Q2FY27 / raw material and H2 order visibility.
- BCLIND: ethanol order book / CBG plant revenue and margin.

Accept: both test files pass; at least 18/20 right in-process; no pilot-store test changes its answer.
Stop if: a change alters an answer on the pilot stores (pilot10, p20, n10) in the existing tests.
Budget: about 2.5 hours; write scope is your worktree only.
