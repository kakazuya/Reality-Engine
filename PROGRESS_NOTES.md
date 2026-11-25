2026-11-26 T-242 shared_cache: code + tests + docs done (15 and 172 passed, 0 new typecheck errors); committing.
2026-11-26 T-242 statement window + recheck dedupe: DONE. `obs_speaker.widen_statement` (sentence snap + referent
widen, front-matter/label guards, `referent_outside_window` note) hooked into `attach_statement_speakers`;
`observations.dedupe_repeats` at the end of `recheck_db` (full-content key, verified first, page-scoped).
Tests: 256 passed across test_obs_speaker (57) + test_observations (173) + test_v2_guards + test_transcript_window;
typecheck 0 new errors (14 pre-existing in untouched functions). Measurement (tasks/t242_statement_window_measure.md):
tx394 2,537 snapped / 5,026 widened / 4,697 noted / 7,222 changed of 55,219 (13.08%); fy27 1,159 / 2,836 / 2,228 /
3,821 of 27,951 (13.67%); 0 non-verbatim, 0 label crossings; 6 of 7 evidence rows widened, #37 noted (page-opening
fragment, cannot stay a substring of its page); dedupe drops 0 exact repeats on both copies (the 29,966 narrow-key
"repeats" are distinct observations). v3 window fp 2fae7ddac53e unchanged. Docs: DEVELOPER_GUIDE, FIX_LOOP, STATE,
tasks/t242_statement_window_measure.md.
