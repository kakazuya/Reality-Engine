# Task — query layer v1: sub-question decomposition, strict grader, named-document preference, rerank

## Goal
The reviewer found that v0 (`reality_engine/query/`, merged) over-reports. In its 150-case bench (`tasks/answer_bench/RESULTS_v0.jsonl`), ANSWERED went 7 → 17, but spot checks showed:
- **MB0885** answered only the ranking half ("biggest promoter stake sale"), not the "did the stock absorb it?" half, and appended an unrelated deck figure (NPS);
- **MB0023** led with 2021 deck values when the question named the 5 Aug 2026 deck.

## Do
1. **`reality_engine/query/decompose.py`:** split each case into sub-questions, deterministically from the rubric steps and the question's conjunctions. Each sub-question gets its own planner chain via the router, and the answer must address every one.
2. **Strict grader** `tasks/answer_bench/grade_v1.py`:
   - ANSWERED only if every sub-question has evidence-backed content;
   - an answer row for the wrong metric or entity → WRONG;
   - evidence from a document other than the one named (date/type) when that document exists → WRONG;
   - stale data (older than the latest available as of the as_of) without a reason → PARTIAL;
   - unrelated rows in the answer reduce the grade.
3. **Named/latest-document preference** in FACTS/EVIDENCE: when the question names a date or doc type, filter to that document (±3 days on the filing date) first; otherwise take the latest as of the as_of.
4. **Relevance filter** in `answer.py`: drop rows whose metric doesn't match the sub-question's metric family (synonym table).
5. **Rerank** EVIDENCE passages with a cheap local scorer: BM25 plus entity, metric and date overlap features. No paid embeddings.
6. Re-run the 150 bench cases with v1 and the strict grader. **Also re-grade v0's results with the strict grader**, so the before/after is honest. Report both.

## Rules
- Read-only DBs. No network. No paid embeddings. Write only in this worktree. No commits.

## Acceptance checks
1. `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"` passes, with new tests for decompose, the grader rules and doc preference.
2. `tasks/answer_bench/REPORT_v1.md`: strict v0 vs strict v1, by grade/family/bank, plus the 30 regressions.

## Test command(s)
```bash
python -m unittest discover -s reality_engine/tests -p "test_query_*.py"
```

## Report
Give:
- strict v0 → strict v1 ANSWERED/PARTIAL/WRONG;
- 10 examples of fixed cases;
- the remaining top blockers;
- your tool-call count.
