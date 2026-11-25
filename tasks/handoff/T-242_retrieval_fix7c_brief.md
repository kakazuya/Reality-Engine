# T-242 brief: retrieval fix 7c - zero R lost against the LIVE code (fix 6)

Goal: on top of fix 7b (branch dsh/20261125T213723Z-c067fb9c, head 146cec40), audit-6 row ACEVECTOR `fact("adjusted EBITDA","H1 FY27")` serves 16.7 crore first again (live fix-6 code does; fix 7 serves -26.9 crore from p4 first), with no other R lost.
Files: plugins/reality-data/server/lookups_pilot3.py, plugins/reality-data/tests/test_retrieval_fix7.py, docs/DEVELOPER_GUIDE.md
Accept: the seven test files of fix 7b pass; Wolf's replay diff (main = live fix-6 code at C:/Users/warri/Downloads/Info_Diffusion_Model, branch = yours), same script .tmp/replay.py, PYTHONIOENCODING=utf-8: 0 R rows of main lost in either audit, audit 7 >= 39 R. Wolf measured main audit6 39R / audit7 30R; f7b audit6 38R / audit7 39R; the only lost row is 6|ACEVECTOR|fact|adjusted EBITDA|H1 FY27 (main R "16.7 crore", f7b P "-26.9 Cr").
Evidence: C:/Users/warri/Downloads/Info_Diffusion_Model/.tmp/replay_main.txt and .tmp/replay_f7b.txt (one line per row). Store c75 (ACEVECTOR) under C:/RealityEngine/tg_build/universe_fy27/. Audit-6 report row 6: 16.7 crore obs p11 "Adjusted EBITDA Rs16.7 crore in H1 FY27", alt -26.9 p4.
Stop if: the cause is not structural (find which fix-7 rule - scope rank, period-kind rank, unit family, money conversion - reorders it and why), or the fix loses another R; ~40 tool calls; then report.
Budget: ~50 tool calls
Ticket: T-242

## Limits
Stores read-only (mode=ro), no model calls, no per-company rule, pytest per file, never kill processes by name. Run the replay with PYTHONIOENCODING=utf-8 (the rupee sign breaks cp1252 stdout).
