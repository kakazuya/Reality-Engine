# Loop 3 worker: finish the sector KPI lexicons (the stopped l2kpi work)

Goal: the sector KPI lexicon work of `tasks/night_loop/loops/loop_02_worker_kpi.md` is finished and reported: `kpi_series` holds the sector KPIs each company prints, a lexicon family applies only to its sector, and every Accept of that brief is met or reported as unmet, with the changes below.

Ticket: T-056

Evidence:
- Read `tasks/night_loop/loops/loop_02_worker_kpi.md` in full. It is your brief: its Evidence, Files, Accept, Stop if and Gotchas all apply, except where this file overrides them.
- A Sonnet worker built most of this and stopped at a usage limit with no report and no review: commit 2690518 on branch `Eagle-sonnet-l2kpi` changes `kpi.py` (+83), adds `auto_oem`, `bank`, `consumer_internet`, `fmcg`, `insurance_life`, `it_services`, `pharma` yaml, adds `sectors` to `lenders`, `metals`, `orders`, and adds tests in `test_pilot3_kpi.py`. **Start with `git cherry-pick 2690518`** (it applies cleanly on main, checked). Treat it as unreviewed: read its diff first; every Accept check is still yours.
- Overrides:
  1. The base database is now `D:\RealityEngine\pilot10\scratch\l3_base.db` (main, stores, ratios and segments rebuilt), not `pilot10.db`. Work copy `D:\RealityEngine\pilot10\scratch\w_kpi3.db` from it by sqlite3 `backup`. The old `w_kpi.db` is stale: ignore it.
  2. Baseline A1 is 651/898 = 72%, not 571: BAJFINANCE 71/88, ETERNAL 65/88, HDFCBANK 71/101, HINDALCO 69/84, HINDUNILVR 71/96, INFY 65/91, KEC 51/79, MARUTI 59/91, SBILIFE 67/92, SUNPHARMA 62/88 (`D:\RealityEngine\pilot10\scores\a1_loop03_base.json`). A1 must rise, no company falls.
  3. `--base-db` for guards is `l3_base.db`; output `D:\RealityEngine\pilot10\scratch\w_kpi3_a1.json`, `w_kpi3_guards.json`.
  4. A rerun of `--part kpi` must keep the segment rows `xbrl_segments` wrote (segments is merged: `kpi.py` `DELETE` line keeps them). Accept adds: `kpi_series` rows with `metric LIKE 'segment_%'` on the copy are the same count before and after, per company.
  5. Unmet-needs list: read the TSV `D:\RealityEngine\pilot10\scratch\unmet_kpi_loop02.tsv`, but filter to what the new baseline's json still lists as unmet; segment needs are met already.
  6. Period trap and hand-read accept stand unchanged. They are why this needs care: a value in the wrong period is worse than no value. Report the hand-read rows.
- Where: as in the old brief. Other names are out of date only as listed above.
- Data: as in the old brief.
- Checks: `build --profile tasks/night_loop/pilot10_profile.json --part kpi --symbols SBILIFE --out <copy>`; 230 s for all ten, one company at a time.
- Gotchas: as in the old brief; also: another worker owns `ratios.py`, `build.py`, `schema.py`, `lookups_pilot3.py` and a new `comparatives.py`. Yours are `kpi.py` and the lexicons. Scratch files in `D:\RealityEngine\pilot10\scratch\kpi3\`.

Files:
- Change: `reality_engine/pilot3/kpi.py` (only `load_lexicon`, `label_matches`, `Entry`, as the old brief says), `reality_engine/pilot3/lexicon/*.yaml` except `results_lines.yaml`, which the other worker owns; `reality_engine/tests/test_pilot3_kpi.py` (new tests only).
- Docs: `docs/PILOT3_BLUEPRINT.md`, `docs/DEVELOPER_GUIDE.md` section O (a short entry). A second worker edits other sections of both: touch only your own paragraphs.
- Do not touch: `stores.py`, `ratios.py`, `schema.py`, `build.py`, `xbrl_segments.py`, `comparatives.py`, `tasks/night_loop/`, `reality_engine/night_eval/`, any question file.

Accept: Accept 1-7 of the old brief, with the overrides above. Report as in `tasks/worker_context/BRIEF_TEMPLATE.md`, with A1 before and after per company, each hand-read family's count, the still-unmet list with a reason each, and a `Docs updated:` line.

Stop if: as in the old brief; the cherry-pick conflicts in a way you cannot resolve within `kpi.py` and the lexicons.

Budget: first edit within 12 tool calls; 150 tool calls in total; 3 hours; no paid calls, no network, no model call in the build.

Out of scope: guidance, transcripts, comparatives, OCR, downloads.
