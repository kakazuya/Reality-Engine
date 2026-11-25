# T-242: question_end demotes real management answers (Hydrogen, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: narrow the `question_end` rule in `reality_engine/v2/obs_speaker.py` (around line 1118). It currently makes
every statement ending in '?' unverified. Keep catching analysts' questions stored as management statements, but
stop unverifying management answers that merely end with a courtesy or tag question.

Evidence:
- The re-grade of the fy27_v3 reparse copy failed: 5 of 20 wrong were real answers ending in "right?".
- 298 rows in C:/RealityEngine/t242/reparse/fy27_v3_r1.db carry `question_end` (status_reason). A sample of 12 shows
  at most 3 real questions. Examples:
  - These are answers and must stay verified:
    - "...So I would kind of just keep stable as your sort of base case, right?"
    - "...Industries that are served are aerospace, consumer electronics, and so on. Is that helpful?"
    - "...we are fairly confident that we'll sustain the volumes. Am I able to answer your question?"
    - "...Now exact numbers, we can't obviously give, but it is around that figure. What was your second question, Dipesh?"
  - These are questions and must stay unverified:
    - "But how do we mitigate the risk?" (one sentence, the whole passage a question)
    - "Gopal, you want to take up, saying high ROCE?"
- The rule was added after a spot check found 43 verified passages ending in '?' that were analysts' questions.
  Those are typically short and mostly made of questions.

Steps:
1. Read `answer_with_tag_question` and the rule at the line above (use code-tools `outline` on obs_speaker.py first).
2. New rule, a pure function `question_passage(statement) -> bool`. True only when the passage ends in '?' AND:
   - (a) it has at most 2 sentences; or
   - (b) at least half its sentences end in '?'.
   A last sentence that is a courtesy or tag question never counts towards (b): "right?", "Is that helpful?",
   "Am I able to answer your question?", "Does that answer your question?", "What was your (second/next)
   question?", "isn't it?", "no?". Replace the condition with `question_passage(stmt)`.
3. Tests in reality_engine/tests/test_obs_speaker.py: the 6 examples above, plus a 3-sentence analyst question
   ("Sir, on margins. What is the outlook? And will capex rise?" -> question).
4. Measure in place (read-only, no model): apply `question_passage` to the 298 `question_end` rows of
   fy27_v3_r1.db. Report how many stay flagged, and 15 random rows that are no longer flagged, with their last 160
   characters.
5. Docs: one line in docs/DEVELOPER_GUIDE.md next to the existing question_end/'?' rule entry.

Pitfalls: do not change any other rule. The v3 prompt fingerprint must stay 2fae7ddac53e (only obs_speaker changes).
Run pytest on test_obs_speaker.py, test_v2_guards.py, test_transcript_window.py and test_no_control_chars.py only.

Accept: those 4 test files pass, and the measure is reported.
Stop if: more than 80% of the 298 rows would be unflagged. Report and stop; the rule may be too loose.
Budget: about 45 minutes; write scope is your worktree only.
