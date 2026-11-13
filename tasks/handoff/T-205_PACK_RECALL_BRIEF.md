Ticket: T-205

Goal: a retrieval-only prototype of the evidence pack (no model call anywhere) and a measurement of how often the pack
CONTAINS the truth, on two seen question sets, before any answer step is built.

Evidence: T-199 (`D:/RealityEngine/reports/2026-11-13_bluestar_atom_test.html`): 39 of 56 lost grades were routing (the
answerer stopped early, missed a part, or said "not found" while the store held it); 60/64 Blue Star questions were
answered right by at least one run. The same brief gave DeepSeek 82.8% and 73.4%.

Method:
1. `reality_engine/answer/evidence_pack.py` (new package `reality_engine/answer/`):
   - `plan(question, as_of) -> dict`: script only. Metrics from the vocab the store already uses (`pilot3.row_checks`
     vocab / `kpi.load_lexicon` / `ratios.FORMULAS`); periods via `row_checks.period_key` + "latest/last/this quarter"
     resolved against as_of; topic words = the question minus stop words and the company name; kind = one of fact,
     statement, list, guidance, compute, price, holding by keyword rules (unsure -> run every route).
   - `gather(db, symbol, plan, as_of) -> pack`: call the reality-data lookup functions IN-PROCESS (the functions
     `reality_engine.scripts.p3ask` dispatches to; do not shell out), routes from a table in `reality_engine/answer/routes.yaml`:
     always `semantic` (limit 8), `search` (exact phrase of the topic words), `topic` (limit 25); per kind: fact -> `fact`
     + `cells` + `kpi` per (metric, period); statement/list/guidance -> also the full text of the top 6 call/deck pages
     ranked by semantic+topic hits (`page`, max_chars 6000, plus the next page when the hit is in the last 20% of a page);
     guidance -> `guidance`; compute -> `cells`/`ratio` for the printed ratio name first, then `fact` for inputs;
     price -> `tech`; holding -> `holding`. Run the routes in a thread pool. Drop every item known after as_of. Dedupe
     (same doc+page, same atom). Each item: id, route, doc_key, doc_type, page, known_at, text or row. Rank: period match,
     printed (atom/fin) before derived, newer first. Cap per route (quota) and in total (`max_chars`, default 120,000);
     record what each route returned and what was cut.
   - Write one `pack_<qid>.json` per question.
2. `reality_engine/answer/pack_recall.py`: for every question of a set, build the pack and check whether the truth is in
   it: truth tokens = every number in the grader truth (normalise commas, crore/lakh words, %, trailing zeros) plus up to 3
   quoted phrases; `hit` = all truth numbers found in the pack text, `partial` = some, `miss` = none; for truths with no
   number, a phrase match. Output CSV `qid,kind,hit,found,missing,pack_chars,items,seconds,routes_nonempty` and a summary
   by kind (hit rate, median pack size, median seconds).
   Sets:
   - Blue Star: questions `D:/RealityEngine/bluestar/answers/questions_in.json`, truths = the `truth` column of
     `D:/RealityEngine/bluestar/report/grades_1.csv`, `grades_2.csv`, `grades_3.csv` (one per qid; take the longest),
     store `D:/RealityEngine/bluestar/bluestar.db`, out `.tmp/pack/bluestar/` (in your workspace).
   - Aurobindo: questions `D:/RealityEngine/aurobindo/answers/questions_in.json`, truths = `reference` column of
     `D:/RealityEngine/aurobindo/report/key_round1.csv`, store `D:/RealityEngine/aurobindo/aurobindo.db`, out
     `.tmp/pack/aurobindo/` (in your workspace).
   The semantic route needs `REALITY_DATA_ALLOW_PAID_EMBED=1` (query embeddings, a few cents in total; Shivam approved
   embeddings 13 Nov); cached queries cost nothing.
3. Tests `reality_engine/tests/test_evidence_pack.py` on a fixture store: plan on 6 example questions (one per kind),
   as_of drops a later item, dedupe, per-route quota, the recall scorer's number normalisation.
4. Docs: `docs/DEVELOPER_GUIDE.md` one paragraph (commands, outputs); `tasks/STATE.md` one line.

Files: `reality_engine/answer/__init__.py`, `evidence_pack.py`, `routes.yaml`, `pack_recall.py`, the test file, the docs.
Writes outside the repo: none (everything under .tmp/pack/).

Accept: `python -m pytest reality_engine/tests/test_evidence_pack.py -q --basetemp=.tmp/pt1` passes; both
`pack_recall.csv` files exist with one row per question; the final answer gives hit/partial/miss by kind for both sets,
median pack chars and seconds, and the 10 worst misses with the route that should have found them.

Stop if: a change touches the stores (read-only), needs a company literal, or a model call; the pack builder takes more
than 30 s per question (report the slow route instead of raising caps).

Budget: 2 hours. Do not open D:/RealityEngine/bluestar/questions/, truth/, truth2/, key_private/ or
D:/RealityEngine/aurobindo/questions/, truth/. Do not commit PROGRESS_NOTES.md.
