# T-056 loop 3 worker progress

- 2026-11-04: transcripts.py speaker rules landed (participants block, moderator "with us today" names, bare-name marks
  when colon marks < 5, Q&A answers-after-analyst fallback). ETERNAL 691 rows (3 speakers), INFY 2512 (Salid/Jayesh/
  Rishi/Nandan), KEC 1803. HDFCBANK/SUNPHARMA/HINDALCO gained the real participants (Keki Mistry, Kaizad Bharucha,
  Steve Fisher, Dilip Shanghvi, Kirti Ganorkar, Jayashree Satagopan).
- guidance.py families A-I landed: next/coming year +1, backward-quarter filter, nearest explicit label, guided-range
  actuals out, spent-to-date masked, project_capital_cost, lender/segment/other gates, questions out, inr scale,
  cross-document dedupe keyed on (symbol, metric, period, low, high, unit, said_on).
- Next: A1 eval + guards, hand reads, docs (PILOT3_BLUEPRINT, DEVELOPER_GUIDE O2/O6, tasks/STATE.md).
- 2026-11-04 done: A1 662/898 (was 651, KEC 51->62, no company down), guards ok (A3 31/31, A5 pass, A6 ok),
  25 pytest pass (19 guidance + 6 speakers), typecheck clean, docs updated. checkpages 144 vs fixture 145
  (HINDALCO 56/123): pre-existing, checkpages reads kpi + the live pilot3.db only.
