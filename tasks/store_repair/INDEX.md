# Store-repair notes (generated from notes.jsonl by `store_repair note`; do not edit by hand)

One entry per store defect: the question that exposed it, the part, the cause, the fix, the stores repaired. Stores are named by their build folder, never by company.

| id | status | part | symptom | cause | fix | stores repaired |
|---|---|---|---|---|---|---|
| R-001 | open | guidance | Worded guidance (no number) is missed, and widening the sentence patterns loses right rows on unseen stores | pilot3/guidance.py worded path: four worker rounds (T-214 fix B) each failed on fresh stores; tag-question ban ignores who speaks; accounting-policy pages are in scope | not written; Claude to redesign per document type and speaker; evidence D:/RealityEngine/tg_build/fixB_evidence |  |
| R-002 | open | docs_collect | Store holds no call transcript: 0 transcript_statement and 0 guidance rows (38 of 93 queue companies) | fetch manifest is BSE-API only and holds no transcript for the company; no title of its 100 documents names a call | transcript fetch family (needs Shivam's go-ahead for the network work) |  |
| R-003 | fixed | events | 0 event rows although 19 held announcements are order wins ('secured a new work order of Rs. 300 Crores') | pilot3/events.py had no order-win kind and event has no value column | pilot3/order_wins.py (prescribed Regulation 30 table by label, headline fallback) writes order_win in the events part; c01: 19 rows, Rs 6,361 crore, 2.5 s repair | c01, c02, c03, c04, c05, c06, c07, c08, c09, c10 |
| R-004 | open | stores | shp_category holds promoter and public only (2 rows per quarter, source shp_index); no FPI, MF, insurance or pledge rows | the company's shareholding XBRL is not in the store source; only the index summary is read | not written; check nse_shp_xbrl_universe on Drive (T-209) before any fetch |  |
| R-005 | open | kpi | 117 of 182 kpi_series rows quarantined, 13 verified | not diagnosed; read row_check_fail.why by check_name first | not written |  |

## Questions that exposed them

- R-001 (pilot10, n10): What guidance did management give on margins for the year, and did it change between calls?
- R-002 (c01): What did management say on the last call about order inflow and margins?
- R-003 (c01): How large are the recent order wins against annual revenue, and over what period are they executed?
- R-004 (c01): How have FPI and mutual fund holdings moved over the last four quarters?
- R-005 (c01): What is the order book and how many years of revenue does it cover?
