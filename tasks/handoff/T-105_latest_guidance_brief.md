# T-105 latest guidance: catch the targets the extractor misses, and serve only the current one

Ticket: T-105
Goal: the `guidance` table holds the forward targets management states on a call, and `pilot3_guidance` returns the
current target per company + metric + target period by default (an older row only when asked), point in time.
Today the Bajaj Finance Q2 FY27 call (filed 2026-10-23) yields 0 rows, so every model fell back to the April deck's
FY27 AUM growth of 22-24% instead of the call's 26-27% (questions BAJFINANCE-014 and -017).

Evidence (gathered by Opus, 8 Nov):
- Extractor `reality_engine/pilot3/guidance.py`: `run()` L953 reads `transcript_statement` rows (management only,
  roles md/cfo; analyst questions are NOT in that table, only in `doc_page.text`) and calls `extract_sentences()`
  L789 per page; a sentence needs `CUE` (L62) to match, then `metric_candidates()` L493, `pick_number()` L632,
  `plausible()` L515, `subject_ok()` L568; `revisions()` L1004 links a row to the previous row of the same
  metric+period from an earlier document (`revision_of`).
- Query paths that serve the tool: `plugins/reality-data/server/lookups_pilot3.py` `guidance()` L761 (the MCP tool
  `pilot3_guidance`, `plugins/reality-data/server/server.py` L524) and `reality_engine/pilot3/queries.py`
  `guidance_rows()` L280. Both return every row newest first.
- Scratch database with BAJFINANCE, ETERNAL and INFY (`doc`, `doc_page`, `transcript_statement`, `company`):
  YOUR copy is named in the run line at the end of this brief. Rebuild guidance into it with
  `python -m reality_engine.pilot3.guidance --out <your copy> --symbols BAJFINANCE,ETERNAL,INFY`; it prints counts
  per reject reason. Today: BAJFINANCE 6 rows, ETERNAL 11, INFY 16; BAJFINANCE no_cue 1,061.
- Q2 FY27 call, doc_key `BAJFINANCE/concall_transcript/3edbe0c3-f3ed-4804-92a8-a4bc45e22fb6.pdf`. Management
  sentences that are targets but give no row today (page, reject reason):
  - p12 "I would say probably between 26%, 27% growth we should deliver now on a full year basis." (no_cue; the
    metric is AUM growth: the analyst's question on the same page asks about AUM growth and the previous statement
    is "So, I would say FY27, two quarters gone.")
  - p12 "I think that's just medium term, we maintain a guidance of 20% to 25% on a year lower here and a year
    higher there." (medium-term AUM growth)
  - p4 "We are well on track to deliver between 60 million to 62 million new loans in FY27." (dropped silently)
  - p16 "So we'll lower the corridor from 5.5% to 6% to 5% to 5.5%." (no_metric; read the page to name it)
  - p16 "I think exiting the year, they would be at INR800 crores a month, and should continue to probably get to
    INR1,300 crores, INR1,400 crores a month sometime by third quarter of next year." (no_metric; segment line)
- Sentences that must stay out (past facts or hypotheticals): p3 "AUM, as you can see, grew by 26.5% to INR
  5,84,624 crores", p4 "New loans grew 11% to 13.5 million.", p4 "Cost of funds came down sequentially by 9 basis
  points and came in at 7.31%.", p15 "In a year, we may grow 27%, in a year, we may grow 23%.", p12 "Q2 was 10- 12
  basis points lower than Q1."

Files: EDIT `reality_engine/pilot3/guidance.py`, `plugins/reality-data/server/lookups_pilot3.py` (`guidance`),
`plugins/reality-data/server/server.py` (`pilot3_guidance` signature and description), `reality_engine/pilot3/queries.py`
(`guidance_rows`), `reality_engine/tests/test_pilot3_guidance.py`; docs `docs/DEVELOPER_GUIDE.md` (the guidance
paragraph: grep "guidance_cue") and `plugins/reality-data/README.md` if it lists the tool's arguments.

Steps:
1. Recall. Widen `CUE` with forward phrases seen above ("should deliver", "on track to deliver/achieve/reach",
   "we'll lower|raise|cut ... to", "would be at", "on a full year basis", "maintain a guidance") while `PAST_ONLY`,
   `PAST_VERB` and the hypothetical shape ("in a year, we may ...") keep the must-stay-out sentences out. Add count
   targets: metric `new_loans` and `new_customers` (unit `mn`) with a "60 million to 62 million" range parser.
   When a sentence names no metric, take it from the page text before the sentence (the analyst question) or the
   previous management statement on that page; record that in `extractor_rule` as `guidance_cue_v2_context`.
   Mark every new row `guidance_cue_v2`; old behaviour keeps `guidance_cue_v1`.
2. Current target. Add `history: bool = False` to `lookups_pilot3.guidance`, `queries.guidance_rows` and the MCP
   tool. Default returns only rows not superseded at `as_of`: drop a row when another row of the same symbol,
   metric and target_period from a different document has a later `COALESCE(known_at, said_on)` that is itself
   known by `as_of` (no `as_of`: by today). Keep all rows of the latest document (a call can give two). Each
   returned row carries `superseded_rows` (count dropped). `history=true` returns everything, as today.
3. Tests in `test_pilot3_guidance.py`: each evidence sentence above as a unit test of `extract_sentences` (or the
   function you change), the five must-stay-out sentences return no row, and a three-row fixture for step 2 (April
   22-24, October 26-27, as_of before and after October).
4. Rebuild your scratch copy and report: rows per company before -> after, rows per extractor_rule, the Q2 call's
   rows, and 15 random NEW rows with their quote (`--sample 15` prints from the db; it samples all rows, so filter
   to v2) for Opus to hand-check.

Accept:
- `python -m pytest reality_engine/tests/test_pilot3_guidance.py -q` passes, and
  `python -m pytest plugins/reality-data/tests -q -k guidance` if such tests exist.
- On your scratch copy: BAJFINANCE FY27 aum_growth 26-27 from the 2026-10-23 call exists; `guidance(BAJFINANCE,
  metric=aum, period=FY27, as_of=2026-11-04)` returns that row and not 22-24; with `as_of=2026-10-01` it returns
  22-24. Show how you checked it (a test is best).
- No v1 row lost: every v1 row of the three companies is still produced (compare before/after by metric, period,
  low, high, doc_key, page).

Limits and pitfalls:
- Never write `D:/RealityEngine/pilot10/pilot10.db` or any file outside your worktree except YOUR scratch copy.
- Precision over recall: a wrong target served as guidance is worse than a missing one. When in doubt, drop it.
- Do not change `transcript_statement` or how it is built.
- One test file per pytest process; no full test suite.

Stop if: precision on your 15-row sample is under 13 right by your own reading after two attempts; or the change
needs a schema change other than optional new metric names.

Budget: 90 minutes, about 120 tool calls.

Docs updated: name the doc lines you changed in your final report (no docs, no merge).

Final report: what you changed (functions), test results, the before/after table, the 15 sampled rows, and anything
you could not do.
