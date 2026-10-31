# Task — audit instance premises and prepare two review sheets for Shivam (no bank changes)

## Goal
The review (`tasks/arch_v4/GATE95_REVIEW_2026-10-31.md` ideas 3 and 6) estimates that 23-28% of bank rows are instances whose premise is false for the substituted company, and 34.6% name companies outside the pilot. Only Shivam can rule on these. Give him the evidence to rule quickly. Read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`.

## Work
1. **Rule-check premises in `tasks/pilot60/INSTANCES.jsonl`, deterministic where possible:** price moves on a date against stored closes; company-specific facts such as order book, listing, business type or sector against held data; leftover names from the parent question; text identical to the parent. Give each row: `holds`, `false`, `cannot_check`, with the evidence value and its source. Write `tasks/pilot60/PREMISE_AUDIT_2026-10-31.jsonl` and report counts by reason, bucket and family. Measure the reviewer's numbers and say where they differ: 34 of 38 checkable price premises false; 180 of 1,551 instances identical to parent.
2. **Sheet A, `tasks/arch_v4/SHIVAM_SHEET_PREMISES.md`:** 30 flagged rows by a committed seed, covering each reason. Per row: the question, why it is flagged, the evidence with source, and a blank verdict column. Keep each row to two or three lines. The review's decision rule: if he calls fewer than 20 ill-posed, drop the idea.
3. **Sheet B, `tasks/arch_v4/SHIVAM_SHEET_SCOPE.md`:** 20 set, ranking or theme questions by a committed seed. Answer each by read-only query over the 60 pilot names, stating that scope in the answer, with values and provenance read back from the stores. Say where the scoped answer is plainly weak. Add a blank column for whether a scoped answer would satisfy him. These are hand-built demonstrations for his ruling, not engine output, and must be labelled so.
4. **Size the options for his scope ruling:** for parents naming companies outside the pilot, the distinct names, which structured stores already hold them, and document count and rough chunking hours for widening the pilot. Use measured file counts. Report as `tasks/arch_v4/SCOPE_OPTIONS_2026-10-31.md`, with no recommendation to re-scope: he has said no re-scope (`D:\RealityEngine\plans\DECISION_LOG.md` line 329). Present the options and costs only.

## Limits
- Do not change `MASTER_BANK.jsonl`, `INSTANCES.jsonl`, `instantiate.py`, any grader or `reality_engine/query/v4/`.
- Read data read-only. Use no paid models. Point-in-time holds for any premise judged as of a date.
- Bounded queries, one heavy process at a time.

## Acceptance checks
- Every flagged row carries evidence and a source. No row is called false from text alone.
- Both sheets are readable by a person in under 20 minutes.
- Tests pass.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_premise_audit.py -q
```
Create the test file: a false price premise is flagged, a true one is not, an uncheckable one is `cannot_check`.
