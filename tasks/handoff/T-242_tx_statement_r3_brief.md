# T-242 brief: transcript statements r3 - empty beats wrong periods; widen cut fragments; strip embedded labels

Goal: on a re-reparse of the 394 transcript copy, no statement carries a wrong period, cut-figure fragments are widened within the turn, and embedded speaker labels are stripped - without changing any R row of the last grades.
Files: reality_engine/v2/obs_speaker.py, reality_engine/tests/test_obs_speaker.py, docs/DEVELOPER_GUIDE.md
Accept: python -m pytest -q reality_engine/tests/test_obs_speaker.py ; python -m pytest -q reality_engine/tests/test_observations.py (pass) AND on a fresh --reparse of D:/RealityEngine/hy4_out/obs_transcripts_394_v3.db (to a copy under your worktree .tmp; command in C:/RealityEngine/t242/tx394_reparse/reparse_r2.log style: --reparse --baseline <live> --stores-root C:/RealityEngine/tg_build/full394 --doc-types transcript --transcript-prompt v3 --out <copy>) the W rows 36 43 47 of C:/RealityEngine/t242/tx394_grade_r2 have empty or correct periods, and 0 R rows of tx394_grade_r2 (pack ids per fix.md) change.
Evidence: C:/RealityEngine/t242/tx394_grade_r2/fix.md (FAIL 36R/20P/4W/0J with every kind and row id); packs with page text C:/RealityEngine/t242/tx394_grade_r2/pack_part00.jsonl, pack_part01.jsonl. Anchor code from e88910d8 + agy 004a1031 (merged e6e0e669): `anchored_period`, the default prepared-remark anchor, and call_period selection in obs_speaker.py.
Stop if: removing the default anchor changes R rows beyond period-only fields; a rule is per-company.
Budget: ~110 tool calls
Ticket: T-242

## Steps
1. Remove the default anchor for figure-bearing prepared remarks; anchor only on an explicit own-period cue (this/the quarter, during the quarter, Q1-Q4 named, "for FY26"/"for the year" with FY); never when a comparative cue (YoY, Y-o-Y, versus, vs, compared to/with, last year, previous year, corresponding quarter, same period last year) or an annual cue sits with the figure on a quarterly call.
2. Fragment widen: a statement starting with a connector/demonstrative ("And", "But", "This", "So", "Almost", "we will get") whose figure/subject sits in the previous sentence of the same turn on the same page gets that sentence prepended (verbatim substring kept); reuse widen_statement from 0e8b95f3.
3. Strip a leading embedded speaker label ("Shri <Name>, MD & CEO:", "<Name> - CFO:") from the statement.
4. Re-reparse a copy, report per-rule counts and the 60 pack rows before/after; tests with synthetic text and keep-cases; docs.

## Limits
Never write live DBs; no model calls; do not change the v3 prompt text; pytest per file; never kill processes by name.
