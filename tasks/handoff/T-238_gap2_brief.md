# T-238 gap 2 brief: transcript reader + strict dictionary-or-NEW output format (stage M)

Ticket: T-238 (Shivam 22 Nov 2026). Reviewer: Wolf (Opus).

Goal: hy4 reads no call transcripts. In the T-237 Opus deep read of SOMANYCERA, 122 transcript pages gave 1,197
numbers and 589 verbatim management statements (guidance, gas prices, dealer additions, JV turnaround, price hikes).
Also: the reader may invent measure ids silently (annual reports: 23,250 invented names). Shivam 22 Nov: the model
must put each fact into the dictionary, and create a labelled new one when nothing fits.

Evidence:
- Opus record format and rules: `D:/RealityEngine/t237/INSTRUCTIONS.md`; Opus output for comparison:
  `D:/RealityEngine/t237/opus_facts.db` (table fact; type number/statement/rating/audit; is_new + new_definition +
  new_driver_node). SOMANYCERA transcripts: store `D:/RealityEngine/tg_build/measure10/c48/c48.db` (doc_type
  'transcript', 11 docs, 166 pages).
- Reader: `reality_engine/v2/observations.py` (`PROMPT` ~line 2588 already passes the dictionary and allows a
  snake_case id when none fits); measure proposals `propose_measures` (never applied).
- Existing transcript tables in stores: `transcript_statement`, `guidance` (see `docs/PILOT3_BLUEPRINT.md`).

Steps:
1. Output contract: measure = a dictionary id OR `NEW:<id>` with `new_definition` and `new_driver_node`; record types
   number / statement (verbatim, speaker, direction) / guidance (period, low/high, unit, direction). Parse strictly;
   a bare non-dictionary id is rejected as `undeclared_new` (unverified). Store NEW ids in a `measure_new` table with
   counts, pages, definitions.
2. Transcript doc type: text-only pages through the same reader (`--text-only`, T-234 option), with statement and
   guidance records; numbers verify against the transcript text layer; statements verify when the sentence is in the
   text (normalised whitespace); guidance verifies when its value and period words are in the sentence.
3. NEW-id merge: a model-free clustering of NEW ids (normalised name + definition token overlap + unit family) into
   proposed merges, written to a review CSV for Wolf; nothing applied automatically.
4. Scoped run (hy4, cap 300 pages): SOMANYCERA's 166 transcript pages + 4 transcripts of 2 other 91-set companies.
   Compare SOMANYCERA with opus_facts (numbers by value overlap; statements by sentence overlap; guidance rows);
   report undeclared_new count and NEW-id clusters.
5. Tests (synthetic replies) for the contract, statement/guidance checks, clustering; docs V2_SCHEMA_CONTRACT
   section 17 (stage M / T-238), DEVELOPER_GUIDE.

Files: `reality_engine/v2/observations.py`, `reality_engine/tests/test_observations.py`, a new
`reality_engine/v2/measure_new.py` if the clustering is large, the two docs. Do not edit tasks/STATE.md.

Pitfalls: another worker (T-238 gap 1) edits observations.py at the same time in its own worktree for OCR routing
(page_route + text source): keep your changes to the prompt, parsing, record types and transcript doc type; touch the
OCR/route code paths not at all. The deck reader job writes `.tmp/t232read/obs_decks394.db` in the main checkout:
never write it. hy4 quota is shared with that job: cap your run at 300 pages.

Accept: tests pass; typecheck clean; regress observations 0 newly broken on `D:/RealityEngine/t230/obs_91_i.db`;
report under 20 lines: Opus overlap per record type, undeclared_new, NEW-id clusters, tokens per page.

Stop if: hy4 statements match Opus sentences under 40% on SOMANYCERA (report examples).

Budget: about 3 hours, DeepSeek max effort.
