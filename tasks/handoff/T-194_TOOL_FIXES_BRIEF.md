Ticket: T-194

Status: DRAFT, waits for Shivam's verdict (12 Nov). Do not start before he approves.

Goal: make the reality-data tools hand a cheap model everything a question needs in one or two calls, so answers stop
early less often. "Stopped early" was the top miss cause for all four models on T-189 AUROPHARMA (8-12 misses each;
report `D:/RealityEngine/reports/2026-11-12_four_model_answer_test.html`). Rules, never per company.

Evidence (T-189 graders' findings, `D:/RealityEngine/aurobindo/report/`):
1. Topic answers are spread over calls. Pen-G output (A15), China plant (A16), launches (A45-A47), specialty pipeline,
   Eugia, gRevlimid: each model read one call and missed the others.
2. Search answers a different question. `search terms="2 billion"` returned "$4 billion" (Zentiva), "growth of 2%"
   and "4 billion doses" as its top 3 while 34 pages hold the exact phrase; it showed 3 hits and did not say more exist.
3. 1,064 of 2,765 call statements (38%) carry topic `other`, so `statements topic=` misses most pharma topics.
4. List questions ("all FY26 USFDA inspections", A31) need every event; every model missed 1-4 of them.
5. Four answers used documents filed after the question's as_of (look-ahead) through `page`, which does not check it.

Steps (each with its own test first):
1. `topic` tool (p3ask + MCP `pilot3_topic`): everything on a topic up to as_of, across every call and document,
   grouped by document date: statements verbatim, related guidance rows, KPI rows, page cells; a count of what was
   cut when over the limit.
2. `search`: exact phrase first, then words; numbers and currency normalised ("US$2 bn" = "$2 billion" =
   "2 billion"); hits grouped by document; the reply always states "N pages match, k shown".
3. Sector topic vocabulary for statements, starting with pharma (USFDA inspection, OAI, VAI, warning letter, Form 483,
   price erosion, ANDA, launch, biosimilar, API/PLI, specialty/injectables), in `reality_engine/pilot3/lexicon/`; the
   tagger reads the company's sector family. Re-tag and report the share of `other` before/after on aurobindo and
   pilot10 copies.
4. `event` table built by script from announcement titles and first pages: regulatory inspections (unit, dates,
   outcome), buybacks, dividends, acquisitions, mergers; one row per event with source and known_at.
5. as_of enforced by the server: `page`, `search`, `topic` refuse documents known after the as_of passed once per
   question (and say so).

Files: `plugins/reality-data/server/lookups_pilot3.py`, `server.py`, `reality_engine/scripts/p3ask.py`,
`reality_engine/pilot3/` (statements tagger, lexicon, a new events builder), tests under
`plugins/reality-data/tests/` and `reality_engine/tests/`; docs `docs/PILOT3_BLUEPRINT.md`, plugin README,
`docs/DEVELOPER_GUIDE.md`.

Accept: new tests pass, one file at a time; on a copy of the aurobindo store, the five evidence cases above come out
right (topic returns Pen-G from every call; search finds the 34 "2 billion" pages; `other` share reported; FY26
inspections listed; a post-as_of page refused); docs updated.

Stop if: a change needs a company literal; a tool reply grows past 20 kB for a normal topic (report sizes).

Budget: 4 hours, one worker (DeepSeek off-peak or Beam), worktree.
