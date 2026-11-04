# Progress notes — loop 3 KPI lexicons (T-056)

- 2026-11-04: cherry-picked the stopped Sonnet l2kpi work (14 files), reviewed it; work copy `w_kpi3.db` from
  `l3_base.db`. First full build: A1 680/898, accept-2 values present, sector-wrong rows gone, segment rows kept.
- Hand-read of the first build showed the sentence reader taking neighbouring numbers (chart fragments, prose
  comparisons): sector families were mostly under 18/20. Added `strict` sentence labels (new optional entry key) so
  the sentence path demands the value right after the term while tables keep the plain labels; tightened negs;
  made gap quantifiers lazy.
- Final: A1 676/898 (base 651, no company below base), A3 99.85 %, A4 xbrl_disagreements 312 (base 335),
  pytest test_pilot3_kpi 45 passed, checkpages 145 (29/59/57), accept-2 10/11 (MARUTI export_volumes Q2FY27
  108,119 missing: deck p16 table read off-column). Hand-read seed 20261104: fmcg 20/20, insurance_life 16/20,
  pharma 14/20, it_services 12/20, consumer_internet 11/20, bank 10/20, auto_oem 9/20, lenders 9/20; metals and
  orders have no new rows. Remaining causes: label-after-values results tables (HDFC p2/p3, INFY fact sheet p3/p4),
  monthly sales releases dated by month, prose comparatives.

## T-061 KPI precision round 3 (4 Nov 2026)
- Six general rules (split numbers/decimals, lakh units, right-aligned table columns, quote/neg/subject guards, plan/list/share-of guards, 100x abs outlier gate, monthly/investee page skip); `w_kpi6.db` A1 727/898, `test_pilot3_kpi.py` 66 passed, checkpages 145.
- Hand read seed 20261111: KEC 18/20 only; BAJFINANCE 17, HINDALCO 12, HDFCBANK 16, SBILIFE 16, INFY 5, SUNPHARMA 14, MARUTI 15, HINDUNILVR 12, ETERNAL 16. Round fails the 18/20 target; next: segment-table revenue dimensions, debt-table vs leverage rows, flow-change values.
