# T-239 server fix brief: make the pilot3 tools stop answerers from missing held facts (model-free)

Ticket: T-239 (Shivam 23 Nov: "fix the server till the point we can"). Reviewer: Wolf (Opus).

Goal: in trial 2 (200 frozen questions, 91 Telegram stores) 53 graded answers were not right; only 4 were store gaps.
The rest: reading 16, question 13, retrieval_wording 8, routing 7, compute 3. Fix what the SERVER can fix so any
answerer (Opus included) finds held facts and gets unambiguous figures. No model calls, no paid embeddings.

Evidence:
- `D:/RealityEngine/tg_build/trials/trial2/failures_for_server_fix.jsonl` (53 rows: qid, symbol, store_db, question,
  grader error, truth with doc+page, suggested fix). Read all of it first.
- Cases to reproduce (all in that file): NAVKARCORP Gati Shakti terminal (store holds Rs 63.22 cr + 35-year licence,
  answer said not disclosed); ASIANENE Oilmax MDO contracts; NITTAGELA collagen expansion press release; GREENPOWER
  Jul 2026 call on land monetisation; KRYSTAL public vs private pricing (tender + 2-5% bank guarantee); RAMKY ROE
  series read as ROCE; NSIL P/B on a stale FY26 book value instead of Q2FY27; ALICON prior-year base 429.92 vs 428.18.
- Code: `plugins/reality-data/server/lookups_pilot3.py` (fact ~3800, kpi ~745, fin ~1108, ratio, statements ~1896,
  topic ~2500, search, `_obs_rows`), `server.py`, `reality_engine/scripts/p3ask.py`; FTS table `doc_page_fts`.

Steps:
1. Nearest-pages on empty: when fact/kpi/fin/ratio/guidance/statements/obs return no row (or `found: false`), the reply
   adds `nearest` = the top 3 page hits (doc_key, page, doc_type, known_at, 300-char snippet) from `doc_page_fts` plus
   the top 3 `obs_fact` statement rows for the same words, as_of-cut, labelled "not a stored row: read the page".
2. Query expansion (model-free): a small committed thesaurus (`plugins/reality-data/server/synonyms.json`) used by
   search/topic/statements/obs/nearest: capex~capital outlay~investment~project cost; lease~licence~concession;
   contract mining~MDO~mine developer; pricing~tender~bid~L1; land monetisation~sale of land~divest land; collagen
   etc. Build it from the 53 failures' question words vs the truth pages' words (list the pairs you add and why).
   An expanded term is OR-ed, never required; the reply names which expansions matched.
3. Ratio clarity: every ratio row names its definition and inputs (numerator, denominator, period, basis). ROE and
   ROCE must never share a series label; add a test from the RAMKY case.
4. Valuation on the latest book: pilot3_ratio / pilot3_fact for P/B, book value per share and EV must use the latest
   book value known at as_of (a quarter's balance sheet when filed), and say which balance sheet it used (NSIL case).
5. Prior-period bases: fin growth/comparison helpers return the stored prior-period row with its doc+page, so an
   answer cannot invent a base (ALICON case: 428.18).
6. Re-run the 8 cases above through p3ask on their stores and show each now surfaces the truth row/page in the first
   reply. Tests on synthetic stores for 1-5. Docs: `docs/PILOT3_BLUEPRINT.md` tool section + server instructions
   text in server.py.

Files: lookups_pilot3.py, server.py, p3ask.py (only if a new arg), synonyms.json, tests, the blueprint.
Do not edit tasks/STATE.md. Never write a store.

Pitfalls: replies must stay small (no page dumps: snippets only, 3+3 max); existing reply shapes unchanged except the
new keys; `nearest` must respect as_of; do not loosen any row check.

Accept: new tests pass; plugins/reality-data/tests/test_lookups_pilot3.py and reality_engine/tests/test_obs_wiring.py
pass; typecheck 0 errors on changed files; the 8 cases show the truth in the first reply; report under 20 lines.

Stop if: a fix needs a model or paid call.

Budget: about 3 hours, DeepSeek max effort.
