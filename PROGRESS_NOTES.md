
## T-049 F answer_check (3 Nov)
- derived grading added to reality_engine/pilot3/answer_check.py: growth/share/margin/ratio/market cap/difference/sum/cagr from the oracle inputs vs the reply value, columns compared_on + cited_class + derived numbers; topic fallback to terms (price/growth/dividend/rating/volume); results date from pilot3_docs for 'sessions after results' questions
- 22 tests pass: python -m pytest reality_engine/tests/test_pilot3_answer_check.py -q
- baseline on .tmp/pilot3.db copy: 72 match / 33 partial / 111 mismatch / 36 empty / 47 answered_no_oracle (300)
- next: full run after the change, per-company before/after counts, 5 moved examples, docs (DEVELOPER_GUIDE O5, STATE.md)
- final run on the .tmp copy: 88 match / 25 partial / 107 mismatch / 33 empty / 47 answered_no_oracle / 0 no_tool (was 72/33/111/36/47/1); 34 rows compared_on=derived; 45 derived-looking rows had nothing derived in the reply (cited comparison decides); docs: docs/DEVELOPER_GUIDE.md O5, tasks/STATE.md, tasks/dsh_tasks/T049_ANSWER_CHECK_2026-11-03.md
- full suite after: 2298 passed / 388 failed / 134 errors (all environmental: sandbox temp ACLs, server stdio pipes, live DB); the 7 answer-check setup errors of the previous run are gone (plugins/dsh-worker/server/core.py shadowed plugins/reality-data/server/core.py; guards in lookups()); accept command passes 22
