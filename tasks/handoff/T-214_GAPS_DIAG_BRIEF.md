# T-214: root cause of four gaps in the 10 measured Telegram stores (read-only diagnosis)

Ticket: T-214
Goal: for each gap below, find the root cause (missing raw input, missing fetch family, a filter, or a code path) and say what general fix would close it for all 93 queue companies. No fix in this job.

Files (read-only): stores `D:/RealityEngine/tg_build/measure10/cNN/cNN.db` + `b_<part>.log`, `pages.db`, `cNN_profile.json`; per-company figures `D:/RealityEngine/tg_build/measure10/pilot10_measure.csv`; raw manifest `D:/RealityEngine/tg_build/measure10/manifest.csv`; build code `reality_engine/pilot3/` (stores.py, guidance.py, transcripts.py, make_profile.py, sector_map.yaml); source DBs under `reality_engine/data/` (results XBRL, shareholding, equity_intelligence.db). PRIVATE: refer to companies as c01..c10 only; no symbol or name in any file you write or in your answer.

Gaps (Wolf's own read of the stores, 15 Nov):
1. c10: `fin_quarter_xbrl` has 0 rows (printed tables only; price_delivery only 314 rows -> likely a recent listing or BSE-only/SME company).
2. c07 and c10: `shp_category` 0 rows (other stores 42-50).
3. guidance 0 rows in c01, c03, c04, c06, c09. c01/c04/c09 have no transcript document; c03 has 1 transcript (232 statements), c06 has 11 transcripts (3,142 statements) and still 0 guidance.
4. sector key `unknown` for c04, c06, c07, c10.

Steps:
1. Per gap and company: check whether the source rows exist for that ISIN/symbol/scrip code in the source DB (and under which identifier), then follow the build part's query to the line that drops them. Quote the query/line and the count at each stage.
2. For gap 3 c06: sample 10 forward-looking sentences from its transcript_statement and show why guidance.py did not take them.
3. For gap 4: show the taxonomy/industry value each company carries and the sector_map rule that would be needed; say what `unknown` disables downstream (KPI lexicon, row checks).
4. Estimate from the queue file (`D:/RealityEngine/tg_build/build_queue.csv`, counts only) how many of the 93 share each cause.

Accept: final answer has one table: gap, company, cause (file:line or missing source), evidence counts, proposed general fix, size (S/M/L), share of the 93 affected.
Evidence: see Gaps above; all 150 build steps returned rc=0, so these are silent empties, not crashes.
Stop if: a cause needs a network fetch to confirm (state it as "needs fetch check" and move on).
Budget: 90 minutes, DeepSeek max effort. Write nothing outside your worktree `.tmp/`.
