# Tool usage and token spend — every agent source

Generated 2026-11-01T21:22:47+00:00 · since 2026-10-30T19:00:00+00:00 · estimated tokens = output chars / 4

Read-only measurement. No message text, document contents or keys; command prefixes are truncated at 400 chars and redacted. Sources under `Manual Dumps` are excluded.

## Headline per source

| source | sessions | steps | tool calls | failures | output chars | est tokens | provider out | cache read | cache create | uncached in | thinking | cost USD | context-carry |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dsh | 67 | 5,597 | 7,718 | 503 | 14,153,180 | 3,538,294 | 4,089,741 | 636,178,944 | 0 | 10,251,913 | 0 | 0.0000 | 140,656,736.4 |
| claude | 16 | 831 | 1,310 | 19 | 2,697,911 | 674,476 | 1,542,628 | 193,250,570 | 4,807,444 | 362,644 | 412,683 | 73.8110 | 84,378,876.0 |
| opencode | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | 0.0 |
| codex | ABSENT | - | - | - | - | - | - | - | - | - | - | - | - |

dsh jobs with an event log: 67 · Claude transcript files: 42 · OpenCode sessions: 0 · Codex: ABSENT.

Context-carry = Σ over steps of (that step's output tokens) × (later steps in the session). Each step's output is re-sent on every later request, so this is the re-sent volume the outputs create, not a separate bill. Attributed to a class by sharing a step's output evenly across the calls in that step.

## Direct API ledger

- entries: **5,338** · input tokens: 9,778,129 · output tokens: 4,973,110 · cost USD: 4.4506
- by model: `{"deepseek-v4.1-flash": 5338}`
- by caller: `{"pilot_bank_reads": 5338}`

## Per source, per tool class

### dsh

| class | calls | failures | output chars | est tokens | context-carry | share of est tokens |
|---|---|---|---|---|---|---|
| LSP navigation | 98 | 0 | 508,412 | 127,103 | 2,018,163.6 | 3.6% |
| LSP diagnostics | 84 | 0 | 368,699 | 92,175 | 406,288.6 | 2.6% |
| .py read whole file | 150 | 2 | 1,019,781 | 254,945 | 3,975,299.5 | 7.2% |
| .py read ranged | 722 | 1 | 3,343,149 | 835,787 | 20,794,686.5 | 23.6% |
| other file reads | 652 | 9 | 2,943,622 | 735,906 | 5,637,142.8 | 20.8% |
| shell file read | 130 | 4 | 187,133 | 46,783 | 1,841,887.9 | 1.3% |
| shell search | 532 | 8 | 1,117,580 | 279,395 | 11,847,890.8 | 7.9% |
| shell list/stat | 507 | 47 | 576,360 | 144,090 | 6,174,323.4 | 4.1% |
| inline Python DB query | 205 | 59 | 283,291 | 70,823 | 6,488,564.3 | 2.0% |
| inline Python other | 983 | 117 | 1,823,455 | 455,864 | 10,848,891.1 | 12.9% |
| sql tool query | 92 | 0 | 128,735 | 32,184 | 2,635,101.0 | 0.9% |
| schema probe (any route) | 12 | 0 | 28,724 | 7,181 | 29,551.8 | 0.2% |
| other reality-data tools | 62 | 0 | 121,697 | 30,424 | 2,583,624.6 | 0.9% |
| tests/compile | 354 | 127 | 526,145 | 131,536 | 1,281,365.7 | 3.7% |
| bench or gate runs | 42 | 4 | 26,427 | 6,607 | 676,901.8 | 0.2% |
| git | 93 | 10 | 230,980 | 57,745 | 1,227,928.9 | 1.6% |
| edit/write | 2,706 | 105 | 629,801 | 157,450 | 60,090,051.5 | 4.4% |
| sleep/poll | 161 | 0 | 179,242 | 44,810 | 867,690.6 | 1.3% |
| web | 6 | 5 | 9,778 | 2,444 | 79,047.9 | 0.1% |
| subagent or worker control | 19 | 0 | 997 | 249 | 142,855.8 | 0.0% |
| other | 108 | 5 | 99,172 | 24,793 | 1,009,478.3 | 0.7% |

### claude

| class | calls | failures | output chars | est tokens | context-carry | share of est tokens |
|---|---|---|---|---|---|---|
| LSP navigation | 3 | 0 | 6,902 | 1,726 | 64,010.2 | 0.3% |
| .py read whole file | 6 | 0 | 19,737 | 4,934 | 275,268.7 | 0.7% |
| .py read ranged | 14 | 0 | 40,117 | 10,029 | 355,736.1 | 1.5% |
| other file reads | 198 | 0 | 745,236 | 186,309 | 3,731,009.5 | 27.6% |
| shell file read | 36 | 1 | 120,977 | 30,244 | 1,701,248.1 | 4.5% |
| shell search | 57 | 1 | 98,663 | 24,666 | 3,650,503.2 | 3.7% |
| shell list/stat | 31 | 2 | 82,155 | 20,539 | 1,652,628.8 | 3.0% |
| inline Python DB query | 48 | 5 | 142,034 | 35,508 | 6,254,418.9 | 5.3% |
| inline Python other | 132 | 3 | 384,587 | 96,147 | 8,262,450.0 | 14.3% |
| sql tool query | 4 | 0 | 3,308 | 827 | 209,056.6 | 0.1% |
| schema probe (any route) | 4 | 0 | 8,989 | 2,247 | 263,072.3 | 0.3% |
| other reality-data tools | 15 | 0 | 46,202 | 11,550 | 1,642,857.7 | 1.7% |
| tests/compile | 8 | 0 | 8,413 | 2,103 | 316,992.8 | 0.3% |
| bench or gate runs | 4 | 0 | 2,385 | 596 | 78,378.4 | 0.1% |
| git | 51 | 1 | 170,653 | 42,663 | 2,269,610.9 | 6.3% |
| edit/write | 450 | 6 | 368,719 | 92,180 | 31,720,902.8 | 13.7% |
| sleep/poll | 15 | 0 | 15,162 | 3,790 | 815,883.7 | 0.6% |
| web | 25 | 0 | 81,225 | 20,306 | 856,206.3 | 3.0% |
| subagent or worker control | 172 | 0 | 338,216 | 84,554 | 10,044,457.7 | 12.5% |
| other | 37 | 0 | 14,231 | 3,558 | 3,141,919.4 | 0.5% |

### opencode

| class | calls | failures | output chars | est tokens | context-carry | share of est tokens |
|---|---|---|---|---|---|---|

## Waste detectors

### a. whole-file `.py` read, file never edited (>=200 lines)

- count: **18** · est tokens: **36,833**
- formula: calls: whole-file .py reads with file>=200 lines and file not in the session's edited set; tokens: their output chars/4. For files it did edit, median(file lines / lines of the largest edit region) is reported instead.
- edited_whole_reads: `11`

### b. shell reads/searches/listings the read/grep/LSP tools could serve

- count: **634** · est tokens: **265,096**
- formula: shell-route calls in shell file read / shell search / shell list-stat, output chars/4.
- by_class: `{"shell file read": 166, "shell list/stat": 388, "shell search": 80}`

### c. inline DB queries the `sql` tool could serve

- count: **253** · est tokens: **106,235**
- formula: calls classified inline Python DB query, output chars/4.

### d. schema probes for stores already documented in `tasks/worker_context/schemas/`

- count: **0** · est tokens: **0**
- formula: schema-probe calls whose command/target names a store documented in tasks/worker_context/schemas/*.md (the file stems), output chars/4.

### e. identical commands repeated in one session

- count: **163** · est tokens: **52,632**
- formula: repeated = sum over sessions of (occurrences-1) per identical normalised shell command; tokens = chars of the repeats /4. Separate list: .py scripts run >=3x in one session.
- scripts_run_3plus: `[{"session": "20261030T213539Z-cffa075c", "script": ".tmp/probe_wp1.py", "runs": 3}, {"session": "20261030T213539Z-cffa075c", "script": ".tmp/probe_v4.py", "runs": 4}, {"session": "20261030T213539Z-cffa075c", "script": "tasks/arch_v4/eval_decomposer.py", "runs": 13}, {"session": "20261030T213539Z-cffa075c", "script": ".tmp/dbg_mb125.py", "runs": 3}, {"session": "20261030T213648Z-1bce7b6b", "script": "C:\\RE\\qnn_probe2.py", "runs": 3}, {"session": "20261030T213648Z-1bce7b6b", "script": "C:\\RE\\qnn_probe6.py", "runs": 3}, {"session": "20261030T213648Z-1bce7b6b", "script": ".tmp/hp/net_test.py", "runs": 3}, {"session": "20261030T221155Z-aa3d44d8", "script": ".tmp/probe2.py", "runs": 3}, {"session": "20261030T221305Z-6688ac0b", "script": "tasks/arch_v4/eval_decomposer.py", "runs": 8}, {"session": "20261030T221305Z-6688ac0b", "script": "tasks/arch_v4/build_concept_registry.py", "runs": 8}, `

### f. failed calls

- count: **522** · est tokens: **133,863**
- formula: calls whose status/is_error/exit-code marks them failed; tokens = their output chars/4; top-15 signatures = class + 70-char command prefix.
- signatures: `[["edit/write :: C:\\Users\\warri\\Downloads\\IDM-worktrees\\20261031T002903Z-1f9394e3\\reali\u2026", 9], ["inline Python other :: cd \"C:\\Users\\warri\\Downloads\\IDM-worktrees\\20261031T003321Z-dfb237e6\";\u2026", 9], ["tests/compile :: python -m pytest reality_engine/tests/test_v4_execute.py reality_engin\u2026", 9], ["edit/write :: C:\\Users\\warri\\Downloads\\IDM-worktrees\\20261030T231950Z-e48659fb\\reali\u2026", 7], ["inline Python other :: cd 'C:\\Users\\warri\\Downloads\\IDM-worktrees\\20261030T213539Z-cffa075c';\u2026", 6], ["inline Python other :: $s = @' $py = \"$env:LOCALAPPDATA\\Programs\\Python\\Python314-arm64\\pytho\u2026", 5], ["tests/compile :: cd \"C:\\Users\\warri\\Downloads\\IDM-worktrees\\20261030T221155Z-aa3d44d8\";\u2026", 5], ["tests/compile :: cd \"C:\\Users\\warri\\Downloads\\IDM-worktrees\\20261030T231148Z-597b2681\";\u2026", 5], ["tests/compile :: python -m`

### g. read-only calls in separate steps that could have been one batch

- count: **1,710** · est tokens: **0**
- formula: steps saved = sum over maximal runs of >=2 consecutive model steps whose calls are all read-only, of (run length - 1). Each saved step would also have re-sent the context, so the token value is the step's carry, reported as 0 here because it is already inside context-carry.
- runs: `436`
- read_only_calls: `3364`

### h. calls/seconds before the first edit

- count: **41 sessions** · est tokens: **0**
- formula: calls before the first edit/write, per session, from the worker's own tool_calls_before_first_edit where present else counted from the transcript; seconds = first edit timestamp - session start.
- n: `41`
- calls_p50: `28`
- calls_p90: `48`
- calls_mean: `30.3`
- calls_max: `57`
- seconds_p50: `222.0`
- seconds_p90: `421.0`
- rows: `[{"source": "dsh", "session": "20261031T071254Z-c7976733", "calls": 57, "seconds": 311.0}, {"source": "dsh", "session": "20261031T085616Z-1054f133", "calls": 53, "seconds": 421.0}, {"source": "dsh", "session": "20261031T074247Z-5e4f1551", "calls": 51, "seconds": 294.0}, {"source": "dsh", "session": "20261030T231148Z-597b2681", "calls": 50, "seconds": 596.0}, {"source": "dsh", "session": "20261031T014728Z-0ca981de", "calls": 48, "seconds": 360.0}, {"source": "dsh", "session": "20261030T232027Z-2a9015df", "calls": 47, "seconds": 269.0}, {"source": "dsh", "session": "20261101T122310Z-b9dd8380", "calls": 44, "seconds": 259.0}, {"source": "dsh", "session": "20261030T221305Z-6688ac0b", "calls": 43, "seconds": 434.0}, {"source": "dsh", "session": "20261030T231950Z-e48659fb", "calls": 42, "seconds": 709.0}, {"source": "dsh", "session": "20261030T234857Z-5d808eaa", "calls": 42, "seconds": 392.0},`

### i. tool outputs over 10,000 chars

- count: **43** · est tokens: **234,513**
- formula: calls with measured output >10,000 chars; tokens = chars/4. Results truncated by the writer are a lower bound (see per-source truncated count).
- top_sources: `[["other file reads :: C:\\Users\\warri\\AppData\\Local\\Temp\\claude\\C--Users-warri-Down\u2026", 51961], ["other file reads :: C:\\Users\\warri\\.claude-neo\\projects\\C--Users-warri-Downloads\u2026", 43557], ["edit/write :: S='C:\\Users\\warri\\AppData\\Local\\Temp\\claude\\C--Users-warri-D\u2026", 14575], ["other file reads :: C:\\Users\\warri\\Downloads\\Info_Diffusion_Model\\tasks\\arch_v4\\\u2026", 14422], ["inline Python other :: cd /<redacted>--Users-warri-D\u2026", 6177], ["shell file read :: cd /c/Users/warri/Downloads/Info_Diffusion_Model; date +%H:%\u2026", 5830], ["git :: cd /c/Users/warri/Downloads/Info_Diffusion_Model; B=dsh/2026\u2026", 5414], ["git :: git diff main...dsh/20261101T204312Z-47a63343 -- reality_eng\u2026", 5171], ["inline Python other :: cd /c/Users/warri/Downloads/Info_Diffusion_Model W=../IDM-wo\u2026", 4974], ["git :: git diff 032560c...dsh/20261101T2057`

### j. sleep/poll

- count: **176** · est tokens: **0**
- formula: calls in sleep/poll (sleep, Start-Sleep, timeout /t, job_output/job_list waits); seconds = explicit sleep durations only, so it is a lower bound.
- seconds: `254.0`

## Before vs after the 30 Oct 04:15 IST code-intel change

| window | jobs | calls | LSP calls | LSP/job | LSP share | sql+schema | grep tool | read tool | shell | shell share |
|---|---|---|---|---|---|---|---|---|---|---|
| before | 0 | 0 | 0 | 0 | 0.0% | 0 | 0 | 0 | 0 | 0.0% |
| after | 67 | 7718 | 182 | 2.72 | 2.36% | 104 | 627 | 1524 | 2500 | 32.39% |

Post-change jobs: 20261030T213539Z-cffa075c, 20261030T213610Z-86063cb7, 20261030T213631Z-559aaf44, 20261030T213639Z-4674cd3f, 20261030T213648Z-1bce7b6b. n is small — treat the after column as a data point, not a trend. Detail (all four are within hours of the change; three started within minutes of this run and are still young):

| job | started (UTC) | calls | LSP | shell |
|---|---|---|---|---|
| 20261030T213539Z-cffa075c | 2026-10-30T21:35+00:00 | 168 | 2 | 45 |
| 20261030T213610Z-86063cb7 | 2026-10-30T21:36+00:00 | 123 | 2 | 29 |
| 20261030T213631Z-559aaf44 | 2026-10-30T21:36+00:00 | 0 | 0 | 0 |
| 20261030T213639Z-4674cd3f | 2026-10-30T21:36+00:00 | 169 | 3 | 46 |
| 20261030T213648Z-1bce7b6b | 2026-10-30T21:36+00:00 | 195 | 3 | 118 |
| 20261030T221155Z-aa3d44d8 | 2026-10-30T22:11+00:00 | 98 | 1 | 44 |
| 20261030T221305Z-6688ac0b | 2026-10-30T22:13+00:00 | 238 | 5 | 63 |
| 20261030T221849Z-7bd0e740 | 2026-10-30T22:18+00:00 | 139 | 4 | 45 |
| 20261030T222900Z-d5c8137a | 2026-10-30T22:29+00:00 | 244 | 4 | 99 |
| 20261030T231148Z-597b2681 | 2026-10-30T23:11+00:00 | 178 | 8 | 53 |
| 20261030T231950Z-e48659fb | 2026-10-30T23:19+00:00 | 98 | 1 | 18 |
| 20261030T232027Z-2a9015df | 2026-10-30T23:20+00:00 | 150 | 5 | 29 |
| 20261030T232639Z-221523c3 | 2026-10-30T23:26+00:00 | 22 | 1 | 10 |
| hp-20261031T050720-8c1f52 | 2026-10-30T23:37+00:00 | 2 | 0 | 0 |
| hp-20261031T050823-a4fd29 | 2026-10-30T23:38+00:00 | 0 | 0 | 0 |
| hp-20261031T050937-cc102e | 2026-10-30T23:39+00:00 | 0 | 0 | 0 |
| 20261030T234840Z-fae55c33 | 2026-10-30T23:48+00:00 | 100 | 2 | 43 |
| 20261030T234857Z-5d808eaa | 2026-10-30T23:48+00:00 | 169 | 3 | 62 |
| 20261030T234858Z-26b32595 | 2026-10-30T23:48+00:00 | 73 | 1 | 34 |
| hp-20261031T053935-990b42 | 2026-10-31T00:09+00:00 | 2 | 0 | 0 |
| hp-20261031T054102-9f650e | 2026-10-31T00:11+00:00 | 0 | 0 | 0 |
| 20261031T001316Z-b46043ac | 2026-10-31T00:13+00:00 | 22 | 0 | 8 |
| hp-20261031T055711-dc3feb | 2026-10-31T00:27+00:00 | 90 | 0 | 14 |
| 20261031T002846Z-a3be41ad | 2026-10-31T00:28+00:00 | 169 | 4 | 52 |
| 20261031T002903Z-1f9394e3 | 2026-10-31T00:29+00:00 | 171 | 3 | 49 |
| 20261031T003321Z-dfb237e6 | 2026-10-31T00:33+00:00 | 166 | 4 | 79 |
| 20261031T014728Z-0ca981de | 2026-10-31T01:47+00:00 | 62 | 2 | 24 |
| 20261031T014746Z-75bfd3df | 2026-10-31T01:47+00:00 | 55 | 1 | 22 |
| hp-20261031T071758-6f8c26 | 2026-10-31T01:47+00:00 | 69 | 5 | 19 |
| 20261031T071254Z-c7976733 | 2026-10-31T07:12+00:00 | 120 | 5 | 51 |
| 20261031T071310Z-d607af6b | 2026-10-31T07:13+00:00 | 127 | 4 | 46 |
| hp-20261031T124311-a4b43d | 2026-10-31T07:13+00:00 | 280 | 5 | 94 |
| 20261031T073914Z-8a792c97 | 2026-10-31T07:39+00:00 | 106 | 1 | 30 |
| 20261031T074247Z-5e4f1551 | 2026-10-31T07:42+00:00 | 157 | 8 | 60 |
| hp-20261031T135309-f89fb8 | 2026-10-31T08:23+00:00 | 308 | 2 | 169 |
| hp-20261031T135452-ede795 | 2026-10-31T08:24+00:00 | 168 | 1 | 18 |
| 20261031T085616Z-1054f133 | 2026-10-31T08:56+00:00 | 213 | 4 | 73 |
| hp-20261031T151835-613da5 | 2026-10-31T09:48+00:00 | 171 | 7 | 54 |
| 20261031T200654Z-2d667ad0 | 2026-10-31T20:06+00:00 | 175 | 3 | 81 |
| hp-20261101T015205-8e8c92 | 2026-10-31T20:22+00:00 | 7 | 0 | 4 |
| 20261031T211916Z-26beb47a | 2026-10-31T21:19+00:00 | 56 | 2 | 9 |
| 20261031T212748Z-e2175799 | 2026-10-31T21:27+00:00 | 95 | 2 | 19 |
| hp-20261101T030633-21c22f | 2026-10-31T21:36+00:00 | 69 | 0 | 30 |
| hp-20261101T030706-33b5de | 2026-10-31T21:37+00:00 | 63 | 1 | 14 |
| hp-20261101T030741-211ff9 | 2026-10-31T21:37+00:00 | 67 | 0 | 21 |
| hp-20261101T031209-a556c0 | 2026-10-31T21:42+00:00 | 39 | 0 | 19 |
| 20261031T215040Z-4ef5184a | 2026-10-31T21:50+00:00 | 197 | 4 | 64 |
| hp-20261101T034935-31ca45 | 2026-10-31T22:19+00:00 | 184 | 7 | 41 |
| hp-20261101T035009-ab1d74 | 2026-10-31T22:20+00:00 | 165 | 1 | 19 |
| 20261031T222045Z-a1c65afb | 2026-10-31T22:20+00:00 | 128 | 1 | 65 |
| hp-20261101T040329-6fce13 | 2026-10-31T22:33+00:00 | 197 | 3 | 97 |
| 20261031T224217Z-51255fdf | 2026-10-31T22:42+00:00 | 177 | 3 | 51 |
| 20261101T085509Z-179011eb | 2026-11-01T08:55+00:00 | 0 | 0 | 0 |
| 20261101T085537Z-c725e0b4 | 2026-11-01T08:55+00:00 | 96 | 0 | 46 |
| hp-20261101T172002-15e0f2 | 2026-11-01T11:50+00:00 | 138 | 4 | 35 |
| 20261101T122310Z-b9dd8380 | 2026-11-01T12:23+00:00 | 310 | 7 | 63 |
| 20261101T122321Z-c0a2d041 | 2026-11-01T12:23+00:00 | 91 | 5 | 23 |
| hp-20261101T181205-06ed5d | 2026-11-01T12:42+00:00 | 26 | 1 | 11 |
| hp-20261101T200233-336f17 | 2026-11-01T14:32+00:00 | 38 | 1 | 14 |
| 20261101T181317Z-dd908113 | 2026-11-01T18:13+00:00 | 181 | 3 | 37 |
| 20261101T202143Z-aaa5ff41 | 2026-11-01T20:21+00:00 | 96 | 4 | 27 |
| 20261101T202200Z-e545d45a | 2026-11-01T20:22+00:00 | 109 | 5 | 32 |
| hp-20261102T015327-7b1c9e | 2026-11-01T20:23+00:00 | 48 | 1 | 23 |
| 20261101T204312Z-47a63343 | 2026-11-01T20:43+00:00 | 78 | 5 | 16 |
| 20261101T205730Z-172d7dec | 2026-11-01T20:57+00:00 | 46 | 4 | 6 |
| 20261101T210210Z-521b20a9 | 2026-11-01T21:02+00:00 | 164 | 8 | 33 |
| 20261101T211651Z-042ff303 | 2026-11-01T21:16+00:00 | 56 | 6 | 0 |

## Cross-checks (measured vs a second count)

- **claude**: deduped transcript sum vs the client's own cost-state aggregate — 1/4 sessions within 2%, worst 35.83%. Chosen session `b8444ef0-b222-4eab-a05a-1767a1698f9d.jsonl` (75 steps): deduped sum 163,651 vs provider 163,880 (0.1397% apart). transcript sum of usage over unique message.id vs the provider aggregate the client recorded in its cost-state line. The cost-state line is a live snapshot: it is exact where written after the last message and drifts on long or resumed sessions, so only the chosen exact session is used for the acceptance check.
- **dsh**: counted calls 5,509 vs the worker's own counter 5,447 (1.14% apart, 40 jobs reporting; 7,718 calls counted over all jobs). only jobs that wrote progress.jsonl carry a worker counter; older jobs have no independent count.

## Code-intel vs grep / read / shell

| source | LSP nav | LSP diag | grep tool | read tool | shell (all) | sql tool |
|---|---|---|---|---|---|---|
| dsh | 98 | 84 | 482 | 1524 | 2500 | 92 |
| claude | 3 | 0 | 27 | 218 | 486 | 4 |
| opencode | 0 | 0 | 0 | 0 | 0 | 0 |

`grep tool` and `read tool` are the dedicated tools only; the shell column is every shell-routed call. `sql tool` is `mcp__reality-data__sql`.

## Top 10 most expensive sessions per source

### dsh

| session | steps | calls | provider out | cache read | context-carry | cost USD | model |
|---|---|---|---|---|---|---|---|
| 20261031T003321Z-dfb237e6 | 167 | 166 | 193,363 | 0 | 15,763,315.8 | 0.0000 |  |
| 20261031T085616Z-1054f133 | 188 | 213 | 128,756 | 0 | 10,965,838.2 | 0.0000 |  |
| 20261101T122310Z-b9dd8380 | 193 | 310 | 125,430 | 0 | 9,983,953.4 | 0.0000 |  |
| 20261030T221305Z-6688ac0b | 131 | 238 | 171,859 | 0 | 7,598,722.3 | 0.0000 |  |
| 20261030T213539Z-cffa075c | 107 | 168 | 188,612 | 0 | 6,964,320.2 | 0.0000 |  |
| 20261030T221849Z-7bd0e740 | 123 | 139 | 106,486 | 0 | 6,528,988.9 | 0.0000 |  |
| 20261030T222900Z-d5c8137a | 128 | 244 | 154,797 | 0 | 6,243,895.5 | 0.0000 |  |
| 20261030T213639Z-4674cd3f | 113 | 169 | 129,567 | 0 | 5,269,041.8 | 0.0000 |  |
| 20261031T002846Z-a3be41ad | 109 | 169 | 136,612 | 0 | 5,207,477.8 | 0.0000 |  |
| 20261031T002903Z-1f9394e3 | 109 | 171 | 111,638 | 0 | 4,477,779.4 | 0.0000 |  |

### claude

| session | steps | calls | provider out | cache read | context-carry | cost USD | model |
|---|---|---|---|---|---|---|---|
| neo-Info_Diffusion_Model · C--Users-w… | 272 | 427 | 593,223 | 73,926,788 | 54,185,621.0 | 32.7626 | claude-opus-5-5 |
| neo-Info_Diffusion_Model · C--Users-w… | 146 | 293 | 300,716 | 30,635,602 | 14,948,435.0 | 20.1912 | claude-opus-5-5 |
| neo-Info_Diffusion_Model · C--Users-w… | 75 | 143 | 163,880 | 18,477,542 | 6,555,865.0 | 10.4790 | claude-opus-5-5 |
| neo-Info_Diffusion_Model · C--Users-w… | 61 | 120 | 183,667 | 14,212,040 | 4,905,939.0 | 10.3782 | claude-opus-5-5 |
| neo-Info_Diffusion_Model · C--Users-w… | 42 | 85 | 63,130 | 6,511,413 | 1,355,135.0 | 0.0000 | claude-opus-5-5 |
| agent-a2 · C--Users-w… | 25 | 42 | 70,242 | 3,543,124 | 625,276.0 | 0.0000 | claude-opus-5-5 |
| agent-ab · C--Users-w… | 21 | 20 | 22,297 | 1,527,792 | 270,762.0 | 0.0000 | claude-haiku-5-5 |
| agent-a6 · C--Users-w… | 21 | 20 | 22,340 | 1,524,114 | 260,430.0 | 0.0000 | claude-haiku-5-5 |
| agent-a6 · C--Users-w… | 21 | 20 | 17,796 | 1,477,341 | 189,314.0 | 0.0000 | claude-haiku-5-5 |
| agent-a6 · C--Users-w… | 21 | 20 | 17,341 | 1,448,383 | 170,340.0 | 0.0000 | claude-haiku-5-5 |

## Share of each source's tokens by class

- dsh: .py read ranged 23.6% · other file reads 20.8% · inline Python other 12.9% · shell search 7.9% · .py read whole file 7.2% · edit/write 4.4%
- claude: other file reads 27.6% · inline Python other 14.3% · edit/write 13.7% · subagent or worker control 12.5% · git 6.3% · inline Python DB query 5.3%
- opencode: no tool calls, so no class share (tokens and cost only)

## Thinking output vs visible output

| source | thinking tokens | visible output | thinking share | thinking (est from event text) |
|---|---|---|---|---|
| dsh | 0 | 4,089,741 | 0.0% | 2,406,657 |
| claude | 412,683 | 1,129,945 | 26.8% | - |
| opencode | 0 | 0 | 0.0% | - |

Claude reports thinking inside `output_tokens` (as `output_tokens_details`); OpenCode reports `tokens_reasoning` beside `tokens_output`, so its share is over the sum. dsh records no provider thinking split; its provider total is all output, and the last column is the thinking *text* length / 4.

## Classification accuracy

30 random shell rows per class are printed to the samples file. Verdicts are entered by hand; the measured precision is below. Classes not listed were not sampled (too few rows).

_Not adjudicated in this run (`--precision` not given)._

## What could not be measured, and why

- **dsh output sizes are lower bounds** for truncated results (the event writer caps them); truncated results: 690.
- **dsh input tokens** come from `progress.jsonl` digests written from 31 Oct 2026 on (`input_tokens`, `cache_read_tokens`); older jobs carry output tokens only.
- **OpenCode holds no tool calls at all** in the live DB: only text/reasoning parts. It is reported for model, tokens and cost, with zero tool calls — not omitted.
- **Codex is absent** on this machine (`~/.codex/sessions` does not exist).
- **pytest** is installed for the system interpreter from 31 Oct 2026; the fixture test also runs unchanged under `python -m unittest reality_engine.tests.test_tool_usage_report`.
- **Direct Go API readers** (`extract_news_prices`, `extract_deck_figures`, `concall_pilot`, `ar_queue`, `ingest_annual_reports`) call `cost_ledger.record_usage()` after every response and appear in the **Direct API ledger** section; `tasks/arch_v4/nid_beam_preread.py` does the same. Before 31 Oct they logged nothing, so that window has no local record for them.

## Comparison vs baseline

Baseline generated 2026-10-30T18:34:23+00:00 · window 2026-11-01T21:22:47+00:00

| metric | unit | baseline | window | delta |
|---|---|---|---|---|
| Claude cached tokens per step | tokens/step | 290452.982078 | 232551.829122 | -20% |
| Claude edit/write share of re-sent volume | share | 0.338304 | 0.410326 | +21% |
| Tokens per worker-control call | tokens/call | 793.597473 | 491.593023 | -38% |
| Inline DB share of DB calls | share | 0.84507 | 0.923077 | +9% |
| Inline DB failure rate | share | 0.108333 | 0.104167 | -4% |
| Batchable steps as a share of steps | share | 0.232891 | 0.266024 | +14% |
| Sleep seconds per worker-hour | s/h | None | 9.155444 | n/a |
| LSP calls per dsh job | calls/job | 0.743316 | 2.716418 | +265% |
| Calls before first edit (p50) | calls | 18 | 28 | +56% |
| Read share of dsh calls | share | 0.138581 | 0.19746 | +42% |
| Tests/compile failure rate | share | 0.285714 | 0.358757 | +26% |
| Shell share of dsh calls | share | 0.419199 | 0.323918 | -23% |
