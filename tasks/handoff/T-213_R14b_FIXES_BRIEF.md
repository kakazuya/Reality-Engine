# T-213 round 14b: make the follow-ups actionable (probe pages become items), close three loop holes

Ticket: T-213

Goal: the round-14 loop (branch `dsh/20261113T214924Z-bcef5051`, `reality_engine/answer/checked_lookups.py`) works,
but a replay of 6 Blue Star questions showed its follow-ups often cannot be acted on. Fix these five structural
faults. No per-question or per-company rule; no evidence pack.

Evidence (replay output, read-only: `D:/RealityEngine/bluestar/answers_r14_replay/answers.jsonl` and `calls.jsonl`):
1. Probe hits are not citable. BS-004: C4 found deck f54a2af0 p16 (prints the H1FY27 figure the part asked for) and
   told the model to read it, but the page was never fetched as an item; the model cited "probe:f54a2af0 p16", C1
   rejected it, and the part ended not_found. -> When C4 fails, CODE fetches each hit page (`page` lookup, doc_key +
   page, as_of) and appends it as new items `L<n>` BEFORE sending the follow-up; the follow-up names those item ids
   ("read L31 (deck p16) ...").
2. An empty answer survives. BS-009 final answer text is "" with every part status missing (C1 x2) after 2
   follow-ups. -> A reply with empty `answer` or no part statuses never replaces the previous non-empty answer; if no
   non-empty answer exists after the budget, write each part as "not found after: <lookups + probe pages>" from code.
3. Probe ranks the wrong document. BS-016 part "Q2FY27 room AC primary growth": the probe's hits were the Q1FY27 call
   (3fadd68c, known 2026-08-13) and an August filing; the Q2FY27 call (89668a89, known 2026-11-05) p3 prints "Blue Star
   figure is around 42%, the primary growth". -> Probe order: (a) when the part names a period or the question is
   about the latest quarter, first search only documents of that period's results window (filing dates within ~45
   days after the period end, as_of-bounded), newest first; (b) then the unrestricted search. Use the part's own
   distinctive words, and drop words the store spells differently (e.g. try "primary growth" when "primary sales"
   has no hit: run the search once per 2-word phrase of the part, not one mashed query).
4. management_said / change_between_calls parts marked not_found skip C5. -> C5 applies to not_found parts too: a
   management_said part that never had an item from the latest transcript known by as_of fails C5, and code fetches
   the top 3 FTS-matching pages of THAT transcript as items (fix 1 mechanics).
5. C2 is unit-blind. An answer "Rs 679.0 crore" passes against an item 67.90 crore because 679 is a million-variant.
   -> Parse the unit word written after each number in the answer (crore/cr, lakh, mn/million, bn/billion, %), convert
   both sides to rupees (or keep % as %) and require equality within rounding; a number with no unit word keeps the
   current variant rule.

Steps:
1. Tests first in `reality_engine/tests/test_checked_lookups.py` (mocked model, fixture store): one test per fault
   above that fails on the current code and passes after the fix (fault 5: "Rs 679.0 crore" vs item 67.90 crore fails;
   "Rs 67.90 crore" and "679 mn" pass).
2. Fix in `checked_lookups.py` only.
3. Re-run the full test file and `test_plan_model.py`.
4. Docs: extend the O26 block in `docs/DEVELOPER_GUIDE.md` with a "round 14b" paragraph (the five rules).
No model calls in this round (off-peak ends 06:30 IST; Claude runs the replay).

Files: `reality_engine/answer/checked_lookups.py`, `reality_engine/tests/test_checked_lookups.py`,
`docs/DEVELOPER_GUIDE.md`. Do not edit `tasks/STATE.md` (Claude owns it). Read the replay files; write nothing under
D:/RealityEngine.
Accept: python -m pytest reality_engine/tests/test_checked_lookups.py -q
Test command: python -m pytest reality_engine/tests/test_checked_lookups.py reality_engine/tests/test_plan_model.py -q
Pitfalls: probe pages added as items count toward the 20-lookup cap (raise the cap only for probe fetches, by 6 at
most, and say so); never loosen C2 for numbers that have a unit word; the follow-up text still comes only from check
results; use `--basetemp` under the worktree `.tmp` for pytest (the round-14 worker hit an ACL error on
`.tmp/pytest-of-SYSTEM`).
Stop if: a fix needs a per-question rule; 90 minutes.
Budget: 90 minutes, 150 tool calls.
