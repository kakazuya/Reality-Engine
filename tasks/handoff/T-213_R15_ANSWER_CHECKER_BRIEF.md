# T-213 round 15: code checker around the DeepSeek tool-run answers (run B design)

Ticket: T-213
Goal: a script `reality_engine/answer/answer_checker.py` that reads an answer set (`answers.jsonl` + `calls.jsonl`, the
shape written by the T-199 answer runs) and the store, runs five code checks per answer, and writes, per failed
answer, a follow-up text built ONLY from check results. A DeepSeek agent (run-B style, `tasks/handoff/T-199_ANSWER_BRIEF.md`)
then repairs only the flagged answers. No model call inside the checker; no per-question rule; no evidence pack.

Shivam 14 Nov: keep run B (DeepSeek agent with p3ask, unlimited calls, whole pages: 54/64) as the baseline; round 14's
store-wide keyword probe, 600-char items and 12-lookup cap lost (6/12/11 vs 19/9/1) and are not to come back.

Evidence (run B misses, `D:/RealityEngine/bluestar/report_r13/decoded_rows.jsonl`, use == "ds_b"; read-only):
- BS-034, BS-036 (change across calls): answer used one call; Q1FY27 gave 8-10% possibly 12% MEP growth, and a 15%
  room-AC share goal was stated.
- BS-018, BS-025, BS-027 (who said it): BS-018 gave the analyst's Rs 12-13 cr as management's; BS-025 added wording
  not said on that call.
- BS-031 (look-ahead): the answer text cites the FY26 annual report although as_of is 2024-11-30.
- BS-008, BS-040 (scope): company-wide order book 7,229.22 cr used as the segment's book; the segment's printed
  5,141.78 cr was not found.
- BS-026, BS-051 (stopped early): "not found" for PLI Rs 155 cr / Rs 78 cr and the Qatar 49% stake, both in the store.

Store facts (`D:/RealityEngine/bluestar/bluestar.db`, open read-only): `doc(doc_key, doc_type, filing_date, known_at, ...)`,
doc_type in announcement / annual_report / deck / results / transcript; `transcript_statement(doc_key, call_date,
call_period, page, speaker, role, quote, ...)`, role values `md` (3,256) and `mgmt` (452): find out what `md` means
from 3 pages before using role (it may not be "management director"); `doc_page(doc_key, page, text, known_at)`.
11 transcripts, latest Q2FY27 call 89668a89 (2026-11-05). Answer `sources` is a list of {doc_key, doc_type, page,
known_at}; the answer text may also name documents in words ("FY26 annual report", "Q1FY27 call").

Checks (each returns pass/fail + the exact fact that failed; the follow-up quotes these facts, nothing else):
C1 look-ahead: every source known_at <= as_of (end of day); every document named in the answer text (fiscal year /
   quarter + type) must exist with known_at <= as_of. Fail names the late document and its known_at.
C2 calls covered: a question asking how something changed across calls / over FY26-FY27 / "has it changed" (detect by
   words: across, changed, between calls, over the calls, each call, revised, trend; and named quarters) must cite
   every transcript whose call_period falls in the window the question names (or, if none named, every call in the
   last 4 quarters to as_of). Fail lists the missing calls by period, doc_key and date.
C3 speaker: each sentence in the answer that attributes to management (management said / CFO / MD / guided / stated)
   must be backed by at least one transcript_statement or transcript page cited for it whose speaker is management;
   a figure in that sentence must appear on a cited page with a management speaker label before it on the page.
   Fail names the sentence and the speaker the page shows for that figure.
C4 scope: every money figure tied to a segment word in the question must carry a scope word (segment name or
   "company-wide"/"total") in the answer sentence. Fail names the figure.
C5 dug before "not found": a part answered "not found / not stated / not disclosed" needs at least 3 different tools
   among search, semantic, topic, cells, statements in calls.jsonl for that qid, plus at least one `page` read.
   Fail lists the tools still unused.

Follow-up text: "Check failed: <check> - <fact>. Look again in <doc list from the check>." Max 2 follow-up rounds per
answer (the agent re-runs the checker on its own repaired line).

Steps:
1. Tests first `reality_engine/tests/test_answer_checker.py` (fixture store built in tmp from a few real rows, no
   model): one failing-then-passing test per check, using the real cases above (BS-031 late AR, BS-034 one call cited,
   BS-018 analyst figure, BS-008 unscoped segment figure, BS-026 "not found" after 1 tool).
2. Build `answer_checker.py`: CLI `python -m reality_engine.answer.answer_checker --db <store> --answers <dir>
   --out <file.jsonl> [--qid ...]` writing one line per answer {qid, checks:[{id, ok, fact}], followup}.
3. Run it on run B (`D:/RealityEngine/bluestar/answers_ds_b`) read-only, write to `.tmp/r15/check_ds_b.jsonl`. Report how
   many of run B's 10 misses (above) it flags, and how many of run B's 54 right answers it flags (false alarms).
   Target: >= 8 of 10 misses flagged, <= 8 false alarms. Tune the detectors (general rules only) until met or 60 min.
4. Write `tasks/handoff/T-213_R15_REPAIR_BRIEF.md` draft: the agent repair pass (T-199_VERIFY style) that reads the
   checker output and fixes only flagged answers. Claude runs it.
5. Docs: DEVELOPER_GUIDE section next to "Answer arms, round 13": the five checks, CLI, measured flag rates.

Files: `reality_engine/answer/answer_checker.py`, `reality_engine/tests/test_answer_checker.py`,
`tasks/handoff/T-213_R15_REPAIR_BRIEF.md`, `docs/DEVELOPER_GUIDE.md`. Do not edit `tasks/STATE.md`. Write nothing under
D:/RealityEngine.
Accept: python -m pytest reality_engine/tests/test_answer_checker.py -q
Test command: python -m pytest reality_engine/tests/test_answer_checker.py -q
Pitfalls: the checker must never need the grades to decide (grades are only for measuring flag rates in step 3);
don't flag on missing words alone where the answer cites a page holding them; use `--basetemp` under the worktree
`.tmp` for pytest; Windows paths in doc_key use forward slashes.
Stop if: a check needs a per-question rule; 120 minutes.
Budget: 120 minutes, 200 tool calls.
