# T-242: corroborate call numbers against filings (brief for a DeepSeek worker, 24 Nov 2026, Eagle)

Ticket: T-242

Goal: Shivam's ruling (24 Nov, recorded at transcript_number_gate on main): an earnings-call NUMBER or GUIDANCE row is
never verified by the page check alone. It earns `verified` only when a filing we hold states the same thing.
Build `reality_engine/v2/corroborate.py`: a deterministic, model-free matcher that marks call rows corroborated,
with the source cited, so a cheap model can serve them as facts.

Files:
- new `reality_engine/v2/corroborate.py`
- new `reality_engine/tests/test_corroborate.py`
- `docs/DEVELOPER_GUIDE.md`: one paragraph after the "transcript number gate" paragraph (grep `transcript_number`).
- Read-only inputs: the observation DB C:/RealityEngine/t242/394_v2_reparsed4.db (table `observation`), and the
  stores C:/RealityEngine/tg_build/full394/cNNN/cNNN.db. Store tables: fin_quarter_xbrl, fin_quarter_printed,
  fin_annual_line, ratio_panel, kpi_series, guidance, order_win, doc. Find a symbol's store through
  `company.symbol` in each store DB (one company per store); build that index once.
- The observation DB columns are listed by `pragma table_info(observation)`. The ones used here are symbol,
  doc_key, page, measure, value, value_high, unit, scale, period, basis, record_type, status, status_reason,
  value_text and known_at.

Evidence (measured 24 Nov on reparsed4: 2,000 call pages, 8,886 number rows):
- The commonest call measures are revenue.mix 447, ebitda_margin 318, mix.share 241, ebitda 233,
  revenue_growth_yoy 215, pat 203, revenue_from_operations 195, capex 168, order.book 127, ebitda_growth_yoy 111,
  pat_growth_yoy 88, pat_margin 57 and profit_before_tax 47.
- Call periods are written "Q2 FY27", "FY26" and "Q1 FY25". Store fiscal_period is written "Q1FY25" / "FY25" /
  "9MFY24", so normalise by removing spaces and upper-casing. 2,287 rows have an empty period; they are never
  corroborated.
- Store units: fin_quarter_xbrl value 5581100000.0 has unit 'inr' and scale 1.0 (rupees). kpi_series value 611.28
  has unit 'inr_cr' and scale 1e7. Observation rows carry `scale` (1e7 for crore). Compare value*scale on both sides.
- ratio_panel metrics include ebitda, ebitda_margin_pct, pat, pat_margin_pct, revenue_from_operations,
  revenue_growth_yoy_pct, pat_growth_yoy_pct, roe, roce and others. Percent metrics are plain numbers such as 23.4.
- fin_quarter_xbrl line_items include revenue_from_operations, pat, pbt, total_income, finance_cost and
  depreciation; there is a `basis` column (standalone/consolidated).

Steps:
1. Write a measure map (a dict in code, documented): call measure -> list of (store table, metric/line_item,
   value_kind). Start with the measures above that have a filed counterpart:
   - revenue_from_operations, pat, profit_before_tax->pbt, total_income, ebitda go to ratio_panel and
     fin_quarter_xbrl;
   - ebitda_margin->ebitda_margin_pct, pat_margin->pat_margin_pct, revenue_growth_yoy->revenue_growth_yoy_pct and
     pat_growth_yoy->pat_growth_yoy_pct go to ratio_panel;
   - order.book goes to kpi_series metric order_book;
   - capex, capacity.* and volume.* go to kpi_series, if their metric names exist there; list what does exist.
   Measures without a counterpart are left alone and counted.
2. Match rule for a NUMBER row: same symbol and normalised period, with the basis compatible. Call rows usually
   leave basis empty; take consolidated first, then standalone, and report which one matched. The filed value must
   be within 1% (relative) or within 0.05 absolute for percentages. When the call row has value_high, any filed
   value inside [value, value_high] counts.
   POINT IN TIME: only filed rows whose known_at (or the filing date of their doc) is on or before the call
   row's known_at + 1 day, or later. Report both counts separately, as `pre_call` and `post_call`. A post-call
   match still corroborates the number, but the citation says the filing came later.
3. Match rule for a GUIDANCE row: the same symbol, metric and target_period in the store's `guidance` table,
   whose said_on falls within 120 days of the call. Low/high must agree within 1%. If store guidance is sparse,
   report the count and do not invent a source.
4. Output: never edit the input DB. Write `--out <copy>`: copy the input DB, then for each matched row set
   status 'verified' and replace the 'transcript_number:' reason with
   `corroborated: <table>.<metric> <fiscal_period> <basis> = <value> (<pre_call|post_call>)`.
   Unmatched rows stay unverified with their reason unchanged.
   CLI: `python -m reality_engine.v2.corroborate --obs <db> --stores-root <dir> --out <db> [--limit-symbols N]`.
   It prints a JSON summary: rows considered, matched by measure, pre/post call, by table, unmatched-with-
   counterpart, and no-counterpart.
5. Tests: tiny in-memory store and observation fixtures covering
   - a crore number vs XBRL rupees;
   - a margin vs ratio_panel;
   - a range;
   - a period mismatch, which must not match;
   - a 2% difference, which must not match;
   - a guidance match;
   - no counterpart, which stays unverified;
   - the input DB is never written.
6. Run on reparsed4 with --stores-root C:/RealityEngine/tg_build/full394, out
   C:/RealityEngine/t242/394_v2_corroborated.db. Then put 20 random matched rows (seed 2424) in your final
   answer: call value_text, call period, matched table/metric/value/period. That lets the reviewer read them.

Accept: `python -m pytest reality_engine/tests/test_corroborate.py reality_engine/tests/test_no_control_chars.py -q`
passes; the CLI run finishes; the summary and 20 samples are in the final answer; the doc paragraph is written.

Stop if:
- the measure map needs a judgement you cannot make from the table contents (list it and leave it out);
- a store's schema differs from the above;
- matching would need a model call.
Never loosen the 1% rule to raise the count.

Budget: about 2 hours; one worktree.

Pitfalls:
- Read the stores with read-only URIs: `file:...?mode=ro`, or `reality_engine.db.readonly.connect_ro`.
- Write regexes as raw strings, never through a bash heredoc (\b has been corrupted into \x08 before; the test
  test_no_control_chars.py checks this).
- The same figure can appear in fin_quarter_xbrl and ratio_panel; cite one (XBRL first).
- EBITDA has no XBRL line; use ratio_panel.
