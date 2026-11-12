# T-191: semantic search A/B on AUROPHARMA (plan, 12 Nov 2026)

Shivam, 12 Nov: "make sure that we have alpha beta test for without semantic search and semantic search both, so we
know how much help embeddings are doing." The 9 Nov pilot20 re-ask (33 of 54 misses fixed) had no clean control, so
this is the first measurement where semantic search is the only difference.

## What is held equal
- **Store:** one frozen snapshot `D:/RealityEngine/aurobindo_ab/aurobindo.db`, copied once before either arm starts
  (copy recipe: checkpoint, copy, `PRAGMA journal_mode=DELETE`). Both arms read the same file. It includes the 12 Nov
  SHP XBRL rebuild (all holder categories + pledge, exact share count). T-192 row fixes are NOT waited for (12 Nov: two
  Beam rounds failed review; round 3 on DeepSeek): the wrong rows are the same in both arms, so the A-vs-B
  difference is unaffected.
- **Model and settings:** DeepSeek v4.1 flash, max effort, same Go key, both arms started together off-peak.
- **Questions and brief:** the 69 frozen T-189 questions (`D:/RealityEngine/aurobindo/answers/questions_in.json`), the
  T-189 answer brief word for word, except the store path, the output folder and one tool line.
- **Tool access:** both arms call the store through `reality_engine.scripts.p3ask`. Arm A runs with
  `P3ASK_NO_SEMANTIC=1` (the tool is refused and is absent from the tool list); arm B has `semantic` listed and
  `REALITY_DATA_ALLOW_PAID_EMBED=1`.

## The only difference
Arm B's brief adds: `semantic symbol=AUROPHARMA query="<a sentence>" as_of=<date> [limit=8]`: pages ranked by meaning
(Nemotron 8B page vectors), for what-management-said, topic and paraphrase questions; read the pages it returns with
`page`.

## Steps
1. After Shivam tops up DeepInfra (after 15:30): snapshot; then
   `python -m reality_engine.pilot3.embed_test embed --model 8b --since 2024-04-01 --all-types --max-usd 0.15
   --db D:/RealityEngine/aurobindo_ab/aurobindo.db --out D:/RealityEngine/aurobindo_ab/embed`
   (2,595 pages; dry run $0.0755). Check that `pilot3_semantic` returns pages for 3 test queries before starting.
2. Start arm A and arm B as two read-only dsh workers at the same time (DeepSeek, off-peak), outputs to
   `D:/RealityEngine/aurobindo_ab/arm_A/` and `arm_B/` via the workers' `.tmp`.
3. Grade blind: the answer files are relabelled X/Y by a coin flip recorded in `ab_semantic/blind_key.txt`, which the
   graders never open. Six Opus graders (3 per arm, 23 questions each), the T-189 round-2 rubric
   (`report/GRADING_R2.md`) with two updates: A34-A36 are now held (a "not found" there is wrong), and B04-B06 stay
   not held (the Q2 FY27 call transcript was not on BSE by 12 Nov 13:20).
4. Report `D:/RealityEngine/reports/2026-11-12_semantic_ab.html` + xlsx/csv: score per arm; per-question flips (A
   wrong -> B right and the reverse) with the question text; exact McNemar p on the flips; tool calls, semantic calls
   and seconds per answer; query-embedding spend; which miss causes semantic fixed (topic recall, paraphrase) and
   which it did not (exact figures, complete lists, wrong rows, not fetched).
5. Disclose: the 69 questions were seen in round 1, so both arms' absolute scores are not a fresh-company score; the
   A-vs-B difference is the measurement. Log both runs in the run ledger.

## Optional second model (needs Shivam's OK on cost)
Haiku 5.5 on both arms with the same protocol, to see whether semantic helps a stronger reader less or more.

## Code (12 Nov)
`reality_engine/scripts/p3ask.py`: `P3ASK_NO_SEMANTIC=1` drops `semantic` from the tool list and refuses it
(test `reality_engine/tests/test_p3ask.py::test_no_semantic_arm_drops_only_semantic`).
`reality_engine/pilot3/embed_test.py`: `embed --since --all-types` (every doc type from a date).
