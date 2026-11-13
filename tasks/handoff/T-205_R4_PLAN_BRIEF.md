Ticket: T-205

Goal: round 4 of the evidence pack. Replace the word-matching planner with a MODEL-WRITTEN lookup plan chosen from a
per-company menu of what the store holds; the script validates the plan, runs every lookup, and records per question
part what was searched and what was found. No answer step in this round.

Why (read this first): the answering model is not short of data, it is short of routing. On Blue Star (64 frozen
questions) 39 of 56 lost grades were routing and none was missing data. Rounds 1-3 let a script guess the lookups from
the question's words. A reader-judge of the round-3 packs says the pack holds enough for 27 of 64, partly 30, missing 7
(round 2: 21 / 27 / 16). Word matching cannot connect the question's words to the store's names, so the plan must be
written by a model that SEES the store's names.

Evidence (round-3 packs `D:/RealityEngine/bluestar/pack/pack_BS-*.json`, judge `pack_judge_r3.csv` beside them):
- BS-060 "share price and volume reaction on the first session after the Q2FY27 results, against the prior close": the
  pack has the 30 Oct 2026 close, volume and delivery but not the prior session's close. A plan must ask for the day AND
  the session before it.
- BS-033 "how did the margin guidance change between calls": the two call pages that carry it (Q1FY27 call p4
  "6.5%-7%", Q2FY27 call p12 "7%-7.5%") are not in the pack; the words "margin guidance" do not occur near the figures.
  A plan must name each call document and ask for its guidance rows and the pages around them.
- BS-046 "cash flow from operations FY26 vs FY25": not in the pack. The `fin` route answered found=false and listed only
  profit-and-loss lines as available; the figure sits in another table. The planner never saw where cash-flow lines live.
- BS-057/058/059 holding questions: latest quarter present, the earlier quarters asked for are absent.
- BS-034: 73 route errors in one pack; most are `fin` found=false for metric names the store does not use.
- Pack size: item text is capped (median 74k, max 120k chars) but the JSON file is 170k-440k chars because each item
  carries `row` and `text` and the pack repeats text at top level.

Files: `reality_engine/answer/evidence_pack.py` (keep `plan()` and `gather()` working as they are; add beside them),
`reality_engine/answer/routes.yaml`, new modules `menu` and `plan_model` in that package (built on branch `dsh/20261113T103928Z-0a9aa11d`, not on main yet),
`reality_engine/answer/pack_recall.py` (a `--planner model|script` switch), `reality_engine/tests/test_evidence_pack.py`
plus a new `test_plan_model.py`, `docs/DEVELOPER_GUIDE.md` (the evidence-pack paragraph), one line in `tasks/STATE.md`.

Steps:
1. `menu.build(db, symbol, as_of) -> dict` (script only, read-only SQL on the store). For every lookup `gather()` can
   run, list what exists for this company on or before as_of: metric / line-item / KPI / ratio names with the periods
   held (ranges, not every row); every table that holds financial lines incl. cash flow and balance sheet, by name;
   guidance metrics with call dates; holding categories with the quarter ends held; price date range; documents by type
   with doc key, date and page count (calls and decks listed one by one, other types as counts). Render it as text
   under 8,000 characters (`menu.render`). Read `lookups_pilot3.py` to see each lookup's arguments; build the menu
   from the same tables those functions read, so every name in the menu is a name the lookup accepts.
2. `plan_model.write_plan(question, as_of, menu_text, model) -> dict`: ONE model call returning JSON:
   `parts`: the question split into the separate things it asks (each comparison period is its own part);
   `lookups`: at most 25 entries `{part, route, args}` where route is one of the routes in `routes.yaml` and args use
   only names and doc keys from the menu. The prompt states the rules the evidence above shows: a comparison needs every
   period named; "prior close / previous quarter / year ago" is its own lookup; a question across calls needs each call
   document; a computed figure needs each input. Model call: free Beam on Go, following the call pattern and stable
   session id (`reality_engine/scripts/go_session.py`) used in `reality_engine/pilot3/second_read.py`; the model name is
   an argument (`--plan-model`, default `beam-free`). Never a paid model.
3. `plan_model.validate(plan, menu) -> (ok_lookups, rejected)`: script check of every route and name against the menu.
   If anything is rejected, ONE repair call with the rejected entries and the reason; after that, rejected entries go to
   `route_errors` and the run continues. A plan that is not valid JSON after the repair call falls back to the script
   planner and the pack says so (`planner: "script_fallback"`).
4. `gather()` gains a path that runs the validated lookups (thread pool, as_of filter, dedupe and caps as now), plus
   the `always` routes at half their quota. The pack gets a `coverage` list: for each part, the lookups run, found or
   not, and item ids. This list is what a later answer step will use to say "not found, searched X".
5. Write a second file per question, `pack_<qid>.txt`: the reading copy (question, parts, coverage, then items once
   each, no duplicated row/text), target median under 60,000 characters. Report median and max.
6. Run both seen sets with `--planner model` into `.tmp/pack_r4/bluestar/` and `.tmp/pack_r4/aurobindo/` (question and
   truth paths as in `tasks/handoff/T-205_PACK_RECALL_BRIEF.md`). Save every raw model reply and the validated plan
   (`plan_<qid>.json`). Cache plans by (question, as_of, menu hash, model) so a rerun costs no model call.
7. Tests on a fixture store with the model call mocked: menu lists a cash-flow line that `fin` does not serve; an
   unknown metric is rejected and reaches `route_errors`; the prior-session lookup is kept; invalid JSON falls back and
   is labelled; `coverage` has one entry per part; the reading copy has no duplicated item.
8. Docs as listed under Files. Final answer: for each set, questions with every part found / some / none (from
   `coverage`), rejected lookups per question (median, max), model calls and seconds per question, reading-copy size,
   and for BS-033, BS-046, BS-057, BS-060 and BS-062 the plan written and whether the named evidence is now in the pack.

Pitfalls seen in rounds 1-3: an empty symbol silently disabled half the routes (assert the symbol reaches every lookup);
"30 Sep 2026" was read as Q3 (it is the Q2 FY27 quarter end; fiscal year starts 1 April); a default that filters
document types hid announcements (pass document types explicitly); a route that fails must appear in `route_errors`,
never be swallowed.

Accept: `python -m pytest reality_engine/tests/test_evidence_pack.py reality_engine/tests/test_plan_model.py -q
--basetemp=.tmp/pt1` passes; `.tmp/pack_r4/bluestar/` and `.tmp/pack_r4/aurobindo/` each hold one pack, one reading
copy and one plan per question; the final answer carries the numbers of step 8 and a `Docs updated:` line.

Stop if: a change would write to a store (they are read-only); the code needs a company name or symbol literal; the
planner needs more than 2 model calls for a question; a model other than a free one is needed; a write would land
outside this workspace and its `.tmp` (stop and say so; do not write to D:/RealityEngine). Do not open
`D:/RealityEngine/bluestar/questions/`, `truth/`, `truth2/`, `key_private/` or `D:/RealityEngine/aurobindo/questions/`,
`truth/`. Do not judge your own packs: an independent reader will. Do not commit PROGRESS_NOTES.md.

Budget: 3 hours, about 200 tool calls. The semantic route needs `REALITY_DATA_ALLOW_PAID_EMBED=1`; the questions are
the same as in round 3, so the query embeddings are cached and cost nothing. If a query is not cached, skip the
semantic route for that question and record it in `route_errors`.
