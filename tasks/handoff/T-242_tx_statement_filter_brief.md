# T-242 brief: transcript statements - drop non-content turns, anchor prepared-remark periods

Goal: the transcript reader stores no logistics/filler/deferral/thanks turns as statements, and a prepared-remark statement saying "this quarter"/"the year"/"previous year" carries the call's period so it reads alone.
Files: reality_engine/v2/obs_speaker.py, reality_engine/v2/observations.py (only where statements are gated), reality_engine/tests/test_obs_speaker.py, docs/DEVELOPER_GUIDE.md
Accept: python -m pytest -q reality_engine/tests/test_obs_speaker.py ; python -m pytest -q reality_engine/tests/test_observations.py (both pass)
Evidence: D:/RealityEngine/hy4_out/obs_transcripts_394_v3.db.audit/ckpt_0014.fix.md (FAIL 41R/15P/0W/4J). Pack with page text: C:/RealityEngine/t242/tx394_ckpt14/pack_part00.jsonl (ids 1-30) and pack_part01.jsonl (ids 31-60). J rows: 5 deferral "will email you the loss numbers", 27 "thanks ... open the floor for questions", 31 "walk over and demo the products", 42 "You will see that it does not end here.". P period rows: 15, 18, 25, 28 (prepared remarks, qc empty). Earlier passing grades to protect: ckpt 12 C:/RealityEngine/t242/tx394_ckpt12 (46R), ckpt 13 C:/RealityEngine/t242/tx394_ckpt13 (43R) - their R rows by observation_id.
Stop if: a rule drops or changes any R row of ckpt 12/13/14 packs; a rule is per-company; > 3% of statements dropped on a copy.
Budget: ~80 tool calls
Ticket: T-242

## Steps
1. Non-content filter (dropped, not stored): moderator-style logistics ("open the floor", "take questions", "walk over", "demo", "break"), deferrals ("will email", "share offline", "get back to you", "take it offline"), thanks/closing lines, and fillers with no content word, figure, named subject or measure. Structural word lists + a content-word count; reuse obs_speaker helpers.
2. Prepared remarks: when the statement has a relative period ("this quarter", "the quarter", "the year", "this year", "previous year", "last year", "half year") and qc is empty, set period_discussed from the call (the transcript's call quarter/FY already known to the reader) - never invent one; if unknown, leave as is.
3. Measure on a COPY of D:/RealityEngine/hy4_out/obs_transcripts_394_v3.db (scratch in your worktree .tmp): statements dropped by rule, period anchored count, protected R rows changed (must be 0), 20 random dropped (seed 7).
4. Tests; docs.

## Limits
Never write live DBs; no model calls; pytest per file; never kill processes by name. Eagle owns the v3 prompt: do not change the prompt text (that moves the read-gate fingerprint).
