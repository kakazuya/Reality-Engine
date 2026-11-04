# Loop 3 worker: speech fix round: restore the lost check page, correct the false note

Goal: on top of branch `dsh/20261104T133227Z-c8ca921f`, `checkpages run` gives 145 with KEC 29, BAJFINANCE 59, HINDALCO 57, because spent-to-date project capex is kept as its own true row; the branch's docs stop saying the fixture is at fault; the few leftovers below are gone.

Ticket: T-056

Evidence:
1. **The 144 comes from this branch, not from HEAD.** Measured by the controller in the same minute: main 145 (HINDALCO 57/123), `Eagle` KPI branch 145, this branch 144 (HINDALCO 56/123). The report and `tasks/STATE.md` on the branch say `checkpages` reads only `kpi`, but `reality_engine/pilot3/checkpages.py:226` imports `guidance` and line 241 runs `guidance.run`. The one page lost: `HINDALCO045 3.2 USD billion decks_full/6b/6b1ecbe7716e4617bab63f97a8205e4979db87e845193a2a0297d51f9b15b69c.pdf p26`, whose sentence is "Estimated total capital cost remains in the order of $5 billion – $3.2 billion capital expenditures spent through end of FY26". Family D of your brief masks the spend before parsing, so it no longer gives a row. Masking was right for the range; the number itself is a true fact an investor asks for.
   Wanted: where family D masks a spend, also store one row: metric `project_capital_spent`, low = high = the spend (3.2, 2.7, 3.8, 2.2 for the same deck sentences), unit `usd_bn`, target_period = the period the sentence names (`end of FY26` gives FY26, `end of Q1FY27` gives Q1FY27, `end of Q3FY26` gives Q3FY26), same quote, same dedupe key. `pilot3_guidance` returns it like any other row. Add it to the metric list in `guidance.py` and in your docs. Not `capex`, so no annual capex answer can pick it up.
2. **False statement in the docs.** Remove from the branch: the `tasks/STATE.md` change (restore main's file exactly; the wrapper writes STATE), `PROGRESS_NOTES.md`, and any "144" or "fixture fails at HEAD" text in `docs/PILOT3_BLUEPRINT.md` and `docs/DEVELOPER_GUIDE.md`.
3. **Leftovers from the controller's read of your 69 guidance rows** (about 8 wrong, down from about 58 of 136: good work). Fix the ones a general rule covers, no company words:
   - INFY `ebitda_margin` FY27 0.7 "The impact of Optimum Healthcare, Stratus and Versent on operating margin will be approximately 0.7%": an `impact of ... on` sentence is an effect, not a target level.
   - KEC `capex` FY26 250-300 "So typically, we have been spending around INR250 crores": `have been spending` is past; `typically` is not a target.
   - KEC `capex` FY26 600 "INR1,000 crores in Orissa and INR600 crores would be in MP": a place's share of a total. The `dimensions` gate can treat a subject of `in <Name>` here: try, and leave it if it costs a true row.
   - KEC `other` FY27 25 bps "whether the quantum will be 25 basis points or 50 basis points, difficult to quantify": `difficult to quantify` is no target.
   - HINDALCO `ebitda_per_tonne` Q1FY27 500 "Underlying Adjusted EBITDA per tonne remains at ~$500/t excluding impacts": `remains at` with no future word is an actual.
   - SUNPHARMA `revenue_growth` FY28 5-7 "China is a large, growing market ...": read the full sentence; if the number is the market's growth, the market is the subject and it goes.
   - SUNPHARMA `revenue_growth` FY27 27 "total revenue would be 27% of a combined business" (your note): a share, not growth.
   - HINDALCO `cost_of_production` FY26 3-4 "the cost of production in the Q2 level ... is about 3% to 4% higher than Q1": said 2025-11-13. The sentence names Q2, and it is past: drop it, as `PAST_ONLY` would if it matched `in the Q2 level`.
4. **Footer in a quote.** INFY `transcript_statement` quote "External Document © 2026 Infosys Limited 3  with an agent services suite called Topaz Fabric.": `boilerplate_lines` (`transcripts.py`) misses a footer with a changing page number. Normalise digits before comparing lines. Also INFY's whole call is `section='prepared'` because `QA_START_RX` keys on the moderator, and a media call has none: when a document has no moderator, the first participant line from the journalists or analysts list starts `qa`.

Where: `reality_engine/pilot3/guidance.py`, `reality_engine/pilot3/transcripts.py`. Work copy: keep `D:\RealityEngine\pilot10\scratch\w_speech.db`, re-run `--part transcripts --symbols INFY` and `--part guidance` (all ten, about 5 s) with `--pages-db D:\RealityEngine\pilot10\scratch\c_kec_pages.db`. Env and gotchas as in `tasks/night_loop/loops/loop_03_worker_speech.md`.

Files: `reality_engine/pilot3/guidance.py`, `reality_engine/pilot3/transcripts.py`, `reality_engine/tests/test_pilot3_guidance.py`, `reality_engine/tests/test_pilot3_speakers.py` (new tests only), your paragraphs in the two docs. Do not touch anything else, `tasks/` included.

Accept:
1. `python -m reality_engine.pilot3.checkpages run` printed: 145, KEC 29, BAJFINANCE 59, HINDALCO 57. `pytest reality_engine/tests/test_pilot3_checkpages.py -q` passes.
2. Print `project_capital_spent` rows; each of Evidence 3's quotes: the row now, or none. All 22 true rows of the first brief still there.
3. `test_pilot3_guidance.py`, `test_pilot3_speakers.py` pass. A1 on the copy not below 662/898, none under baseline.
4. Guards as in the first brief: A3 >= 98%, A5 pass, A4 not up.
5. `git diff main --stat` shows no `PROGRESS_NOTES.md`, no `tasks/`.

Stop if: a rule costs a true row and you cannot settle it: leave that leftover, report it. Free RAM under 2.5 GB: pause.

Budget: first edit within 5 tool calls; 50 total; 45 minutes; no paid calls, no network, no model call in the build.

Out of scope: new extraction, other companies' speaker lists, `kpi.py`, comparatives.

Report as in `tasks/worker_context/BRIEF_TEMPLATE.md`, with a `Docs updated:` line. Say which claim in your first report was wrong and how you would have caught it.
