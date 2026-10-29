# Task — harden the strict grader: a 10-row hand check found only ~40% of strict-ANSWERED rows are right

## Goal
The full gate on main (`3489a87`) reports strict ANSWERED 137/2,681 (5.1%). The controller hand-checked 10 random strict-ANSWERED rows (seed 20261029) and found **4 OK, 3 PARTIAL, 3 WRONG**. ANSWERED must mean right, so the grader still over-credits. The failure patterns:

1. **Multi-part asks pass with one part.**
   - MB0280#MS asks for the share count AND the promoter holding; only the promoter holding is given.
   - MB0125#MS asks for the promoter AND public percentages; only public is given.
   - MB0003#L asks for the business + segments; one segment is given.
2. **Ask not addressed but some row passes.** MB0996#MS asks "has the debt fallen or moved into CWIP/JVs?" and is answered with a 4-year price return.
3. **Unrelated rows appended** still pass: MB0310#L carries a Novelis EBITDA-bridge deck passage, and MB0125#MS an unrelated price row.
4. **Bank or instance data defects.**
   - MB0234 (and its instances): the question says "11-12 Aug, NSE and BSE", but the case's `period` field says "13-14 Apr 2026". The answer follows the wrong field, and it is single-exchange.
   - Instance questions keep the ORIGINAL company name ("Trent…", "BHEL…") while the instance entity is another company. The grader judges by slot, but the text is misleading for a human reader.

## Do
1. Grader (`tasks/answer_bench/grade_v1.py`, plus `reality_engine/query/gate.py` only where the contract needs it):
   - **ask coverage:** every part of a multi-part ask (the decomposer's slots: "X and Y", "raw and adjusted", "NSE and BSE", "promoter and public", "count and holding") must be answered, or marked NOT IN DATA. Otherwise the case is PARTIAL.
   - **unrelated-row penalty:** rows whose entity or concept matches no part of the ask are counted. More than 1 such row, or any unrelated row that carries a number, makes it PARTIAL. Report the `unrelated_rows` count.
   - **concept substance:** a judgement ask (has X fallen / moved / improved) needs a row carrying the X metric over the asked span, not a price return.
2. Bank audit, read-only on `tasks/master_bank/MASTER_BANK.jsonl`:
   - list every case whose `period`/`as_of` contradicts the dates in its question text (as MB0234 does);
   - list instance questions whose text names a different company than the instance entity.

   Write `tasks/master_bank/BANK_DEFECTS_2026-10-29.md` with each defect and a proposed fix. Do NOT edit the approved bank, since Shivam approves bank changes. Instead, make `tasks/pilot60/instantiate.py` rewrite the instance question with the instance company's name, and regenerate `INSTANCES.jsonl`.
3. Re-grade the CURRENT results (no bank re-run needed: `gate_run.py grade` + `report`). Report the new strict ANSWERED.
4. Draw 40 strict-ANSWERED rows (seed 20261030), hand-check each against its evidence rows, and report precision with a Wilson lower bound. Target ≥90%. If it's lower, tighten again and repeat once.

## File scope
Allowed: `grade_v1.py`, the grade/report parts of `gate_run.py`, `tasks/pilot60/instantiate.py`, the defect report, and grader tests.

`gate.py`: add-only checks. Never relax.

Do NOT touch planners, since other workers own them.

## Rules
- Read-only on data and the approved bank. Use no paid models and make no commits.

## Acceptance checks
- `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"` passes, plus new grader tests (a multi-part ask missing one part is PARTIAL; unrelated numeric rows make it PARTIAL).
- The 40-row precision is ≥90%, with the lower bound reported.

## Test command(s)
```bash
python -m unittest discover -s reality_engine/tests -p "test_query_*.py"
```

## Report
Give:
- the before/after strict counts;
- the 40-row precision with its lower bound;
- the bank defect counts;
- your tool-call count.
