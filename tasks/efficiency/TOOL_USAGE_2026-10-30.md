# Tool usage and token spend — every agent source

Generated 2026-10-30T18:34:23+00:00 · since all time · estimated tokens = output chars / 4

Read-only measurement. No message text, document contents or keys; command prefixes are truncated at 400 chars and redacted. Sources under `Manual Dumps` are excluded.

## Headline per source

| source | sessions | steps | tool calls | failures | output chars | est tokens | provider out | cache read | cache create | uncached in | thinking | cost USD | context-carry |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dsh | 187 | 16,335 | 19,678 | 1,244 | 33,143,417 | 8,285,853 | 12,964,501 | 0 | 0 | 0 | 0 | 0.0000 | 634,032,413.6 |
| claude | 24 | 5,245 | 5,659 | 175 | 8,386,663 | 2,096,665 | 3,302,901 | 1,523,425,891 | 13,443,969 | 813,224 | 731,509 | 459.2227 | 1,880,125,354.0 |
| opencode | 34 | 31 | 0 | 0 | 0 | 0 | 20,134 | 101,075 | 0 | 205,414 | 194,246 | 0.0369 | 1,196.0 |
| codex | ABSENT | - | - | - | - | - | - | - | - | - | - | - | - |

dsh jobs with an event log: 187 · Claude transcript files: 26 · OpenCode sessions: 34 · Codex: ABSENT.

Context-carry = Σ over steps of (that step's output tokens) × (later steps in the session). Each step's output is re-sent on every later request, so this is the re-sent volume the outputs create, not a separate bill. Attributed to a class by sharing a step's output evenly across the calls in that step.

## Per source, per tool class

### dsh

| class | calls | failures | output chars | est tokens | context-carry | share of est tokens |
|---|---|---|---|---|---|---|
| LSP navigation | 49 | 0 | 186,258 | 46,564 | 3,278,909.2 | 0.6% |
| LSP diagnostics | 90 | 0 | 348,049 | 87,012 | 422,892.4 | 1.1% |
| .py read whole file | 494 | 3 | 3,502,772 | 875,693 | 21,968,280.3 | 10.6% |
| .py read ranged | 1,305 | 4 | 5,665,472 | 1,416,368 | 40,796,348.4 | 17.1% |
| other file reads | 928 | 11 | 5,060,945 | 1,265,236 | 14,252,124.9 | 15.3% |
| shell file read | 438 | 21 | 947,356 | 236,839 | 11,871,869.9 | 2.9% |
| shell search | 1,219 | 23 | 2,393,488 | 598,372 | 36,980,837.4 | 7.2% |
| shell list/stat | 1,329 | 131 | 1,621,127 | 405,282 | 33,679,806.0 | 4.9% |
| inline Python DB query | 894 | 180 | 1,231,144 | 307,786 | 48,844,584.4 | 3.7% |
| inline Python other | 2,736 | 290 | 5,153,792 | 1,288,448 | 78,238,907.3 | 15.5% |
| sql tool query | 613 | 0 | 1,053,921 | 263,480 | 3,872,120.3 | 3.2% |
| schema probe (any route) | 142 | 6 | 320,697 | 80,174 | 3,627,189.5 | 1.0% |
| other reality-data tools | 263 | 0 | 839,195 | 209,799 | 1,300,260.9 | 2.5% |
| tests/compile | 819 | 234 | 961,984 | 240,496 | 4,740,227.7 | 2.9% |
| bench or gate runs | 151 | 4 | 99,373 | 24,843 | 1,292,158.8 | 0.3% |
| git | 317 | 15 | 820,344 | 205,086 | 4,150,359.0 | 2.5% |
| edit/write | 6,616 | 253 | 1,477,025 | 369,256 | 301,089,453.1 | 4.5% |
| sleep/poll | 705 | 24 | 567,152 | 141,788 | 14,924,822.4 | 1.7% |
| web | 119 | 11 | 565,423 | 141,356 | 82,165.1 | 1.7% |
| subagent or worker control | 128 | 0 | 16,961 | 4,240 | 4,239,722.9 | 0.1% |
| other | 323 | 34 | 310,939 | 77,735 | 4,379,373.6 | 0.9% |

### claude

| class | calls | failures | output chars | est tokens | context-carry | share of est tokens |
|---|---|---|---|---|---|---|
| LSP navigation | 7 | 0 | 10,821 | 2,705 | 69,804.8 | 0.1% |
| LSP diagnostics | 1 | 0 | 1,877 | 469 | 5,530.0 | 0.0% |
| .py read whole file | 3 | 0 | 110,044 | 27,511 | 108,141.0 | 1.3% |
| .py read ranged | 39 | 0 | 61,400 | 15,350 | 5,183,580.3 | 0.7% |
| other file reads | 106 | 0 | 542,868 | 135,717 | 9,600,346.8 | 6.5% |
| shell file read | 583 | 15 | 1,189,755 | 297,439 | 104,893,750.6 | 14.2% |
| shell search | 439 | 6 | 561,010 | 140,252 | 74,101,893.5 | 6.7% |
| shell list/stat | 372 | 19 | 333,521 | 83,380 | 85,083,338.0 | 4.0% |
| inline Python DB query | 240 | 26 | 279,483 | 69,871 | 112,800,783.1 | 3.3% |
| inline Python other | 602 | 31 | 697,254 | 174,314 | 201,654,732.9 | 8.3% |
| sql tool query | 44 | 0 | 30,049 | 7,512 | 13,420,356.7 | 0.4% |
| schema probe (any route) | 12 | 0 | 17,382 | 4,346 | 6,859,714.8 | 0.2% |
| other reality-data tools | 14 | 0 | 19,416 | 4,854 | 7,274,872.3 | 0.2% |
| tests/compile | 78 | 0 | 76,386 | 19,096 | 29,372,341.7 | 0.9% |
| bench or gate runs | 1 | 0 | 7 | 2 | 11,646.0 | 0.0% |
| git | 301 | 11 | 241,069 | 60,267 | 97,664,356.5 | 2.9% |
| edit/write | 1,026 | 42 | 385,021 | 96,255 | 561,245,539.6 | 4.6% |
| sleep/poll | 89 | 7 | 36,839 | 9,210 | 8,915,605.1 | 0.4% |
| web | 84 | 0 | 189,637 | 47,409 | 8,250,783.9 | 2.3% |
| subagent or worker control | 1,108 | 13 | 3,517,225 | 879,306 | 229,732,497.6 | 41.9% |
| other | 510 | 5 | 85,599 | 21,400 | 102,749,331.9 | 1.0% |

### opencode

| class | calls | failures | output chars | est tokens | context-carry | share of est tokens |
|---|---|---|---|---|---|---|

## Waste detectors

### a. whole-file `.py` read, file never edited (>=200 lines)

- count: **77** · est tokens: **163,407**
- formula: calls: whole-file .py reads with file>=200 lines and file not in the session's edited set; tokens: their output chars/4. For files it did edit, median(file lines / lines of the largest edit region) is reported instead.
- edited_whole_reads: `63`

### b. shell reads/searches/listings the read/grep/LSP tools could serve

- count: **3,517** · est tokens: **1,412,034**
- formula: shell-route calls in shell file read / shell search / shell list-stat, output chars/4.
- by_class: `{"shell list/stat": 1587, "shell search": 909, "shell file read": 1021}`

### c. inline DB queries the `sql` tool could serve

- count: **1,134** · est tokens: **377,245**
- formula: calls classified inline Python DB query, output chars/4.

### d. schema probes for stores already documented in `tasks/worker_context/schemas/`

- count: **20** · est tokens: **10,229**
- formula: schema-probe calls whose command/target names a store documented in tasks/worker_context/schemas/*.md (the file stems), output chars/4.
- tables_hit: `{"equity_intelligence": 10, "concall_facts": 7, "deck_figures": 1, "results_xbrl": 1, "bse_announcements": 1}`

### e. identical commands repeated in one session

- count: **462** · est tokens: **131,031**
- formula: repeated = sum over sessions of (occurrences-1) per identical normalised shell command; tokens = chars of the repeats /4. Separate list: .py scripts run >=3x in one session.
- scripts_run_3plus: `[{"session": "20261023T215357Z-145850d9", "script": "tmp_inspect_reality.py", "runs": 3}, {"session": "20261023T215357Z-145850d9", "script": "tmp_sqlite_schema.py", "runs": 6}, {"session": "20261023T215357Z-145850d9", "script": "tmp_catalog_check.py", "runs": 3}, {"session": "20261023T215357Z-145850d9", "script": "tmp_fact_debug.py", "runs": 3}, {"session": "20261023T215357Z-145850d9", "script": "plugins/reality-data/tests/acceptance_check.py", "runs": 6}, {"session": "20261023T215357Z-145850d9", "script": "tmp_ppl_chunks.py", "runs": 3}, {"session": "20261023T234907Z-59821b17", "script": "plugins\\dsh-worker\\server\\store.py", "runs": 5}, {"session": "20261023T234907Z-59821b17", "script": "reality_engine\\tests\\test_dsh_worker_stress.py", "runs": 5}, {"session": "20261023T234907Z-59821b17", "script": "plugins\\dsh-worker\\server\\jobs.py", "runs": 3}, {"session": "20261023T234907Z-598`

### f. failed calls

- count: **1,419** · est tokens: **332,766**
- formula: calls whose status/is_error/exit-code marks them failed; tokens = their output chars/4; top-15 signatures = class + 70-char command prefix.
- signatures: `[["tests/compile :: python -m unittest discover -s plugins/reality-data/tests -p \"test_*.p\u2026", 19], ["tests/compile :: python -m unittest reality_engine.tests.test_dsh_worker_plugin.PluginT\u2026", 12], ["shell list/stat :: Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Select-Obj\u2026", 9], ["web :: web_search", 8], ["inline Python other :: cd C:\\Users\\warri\\Downloads\\IDM-worktrees\\20261027T193025Z-39b30996\\ta\u2026", 8], ["inline Python other :: python .tmp/minipytest.py reality_engine.tests.test_query_planners 2>&\u2026", 8], ["tests/compile :: C:\\Users\\warri\\AppData\\Local\\Programs\\Python\\Python314\\python.exe -m u\u2026", 7], ["inline Python other :: python .tmp\\proto.py 2>&1", 7], ["inline Python DB query :: C:\\Users\\warri\\AppData\\Local\\Programs\\Python\\Python314\\python.exe -c \"\u2026", 6], ["inline Python other :: C:\\Users\\warri\\AppData`

### g. read-only calls in separate steps that could have been one batch

- count: **5,033** · est tokens: **0**
- formula: steps saved = sum over maximal runs of >=2 consecutive model steps whose calls are all read-only, of (run length - 1). Each saved step would also have re-sent the context, so the token value is the step's carry, reported as 0 here because it is already inside context-carry.
- runs: `1378`
- read_only_calls: `8754`

### h. calls/seconds before the first edit

- count: **96 sessions** · est tokens: **0**
- formula: calls before the first edit/write, per session, from the worker's own tool_calls_before_first_edit where present else counted from the transcript; seconds = first edit timestamp - session start.
- n: `96`
- calls_p50: `18`
- calls_p90: `36`
- calls_mean: `20.7`
- calls_max: `75`
- seconds_p50: `222.0`
- seconds_p90: `739.0`
- rows: `[{"source": "dsh", "session": "20261029T212409Z-75391ac5", "calls": 75, "seconds": 938.0}, {"source": "dsh", "session": "20261025T135133Z-c01c539c", "calls": 48, "seconds": 1513.0}, {"source": "dsh", "session": "20261028T181638Z-b384c636", "calls": 46, "seconds": 613.0}, {"source": "dsh", "session": "20261027T214259Z-b6e40c70", "calls": 44, "seconds": 664.0}, {"source": "dsh", "session": "20261029T040215Z-756b4cc4", "calls": 44, "seconds": 673.0}, {"source": "dsh", "session": "20261025T123258Z-007ac55f", "calls": 40, "seconds": 617.0}, {"source": "dsh", "session": "20261028T200955Z-ce1e5b77", "calls": 40, "seconds": 999.0}, {"source": "dsh", "session": "20261028T185734Z-b913bc48", "calls": 38, "seconds": 1127.0}, {"source": "dsh", "session": "20261028T175323Z-4efba8ca", "calls": 36, "seconds": 636.0}, {"source": "dsh", "session": "20261029T040413Z-5d203544", "calls": 36, "seconds": 505.0`

### i. tool outputs over 10,000 chars

- count: **191** · est tokens: **719,058**
- formula: calls with measured output >10,000 chars; tokens = chars/4. Results truncated by the writer are a lower bound (see per-source truncated count).
- top_sources: `[["subagent or worker control :: mcp__dsh-worker__worker_result", 353249], ["subagent or worker control :: mcp__dsh-worker__worker_status", 94098], ["other file reads :: C:\\Users\\warri\\AppData\\Local\\Temp\\claude\\C--Users-warri-Down\u2026", 64906], [".py read whole file :: C:\\Users\\warri\\Downloads\\Info_Diffusion_Model\\.claude\\worktr\u2026", 27509], ["other file reads :: C:\\Users\\warri\\AppData\\Local\\Temp\\claude\\C--Users-warri--cla\u2026", 20428], ["shell file read :: cat /c/Users/warri/Downloads/Info_Diffusion_Model/plugins/ds\u2026", 19010], ["subagent or worker control :: mcp__dsh-worker__list_workers", 18464], ["shell file read :: cd \"C:/Users/warri/Downloads/Info_Diffusion_Model/.claude/wo\u2026", 14759], ["inline Python other :: python -c \" import json d=json.load(open(r'C:\\Users\\warri\\.c\u2026", 11636], ["shell search :: cd /<redacted>-skills/2\u2026", 8371], `

### j. sleep/poll

- count: **794** · est tokens: **0**
- formula: calls in sleep/poll (sleep, Start-Sleep, timeout /t, job_output/job_list waits); seconds = explicit sleep durations only, so it is a lower bound.
- seconds: `45029.0`

## Before vs after the 30 Oct 04:15 IST code-intel change

| window | jobs | calls | LSP calls | LSP/job | LSP share | sql+schema | grep tool | read tool | shell | shell share |
|---|---|---|---|---|---|---|---|---|---|---|
| before | 183 | 18999 | 119 | 0.65 | 0.63% | 744 | 756 | 2596 | 8046 | 42.35% |
| after | 4 | 679 | 20 | 5.0 | 2.95% | 11 | 34 | 131 | 203 | 29.9% |

Post-change jobs: 20261030T173149Z-5d66898d, 20261030T180414Z-e09031f3, 20261030T180428Z-556bef7d, 20261030T180452Z-0683cd3a. n is small — treat the after column as a data point, not a trend. Detail (all four are within hours of the change; three started within minutes of this run and are still young):

| job | started (UTC) | calls | LSP | shell |
|---|---|---|---|---|
| 20261030T173149Z-5d66898d | 2026-10-30T17:31+00:00 | 157 | 6 | 35 |
| 20261030T180414Z-e09031f3 | 2026-10-30T18:04+00:00 | 224 | 8 | 77 |
| 20261030T180428Z-556bef7d | 2026-10-30T18:04+00:00 | 111 | 3 | 42 |
| 20261030T180452Z-0683cd3a | 2026-10-30T18:04+00:00 | 187 | 3 | 49 |

## Cross-checks (measured vs a second count)

- **claude**: deduped transcript sum vs the client's own cost-state aggregate — 12/21 sessions within 2%, worst 46.88%. Chosen session `9e451e0e-3307-4a38-a2a9-477f118b16ff.jsonl` (149 steps): deduped sum 129,316 vs provider 129,449 (0.1027% apart). transcript sum of usage over unique message.id vs the provider aggregate the client recorded in its cost-state line. The cost-state line is a live snapshot: it is exact where written after the last message and drifts on long or resumed sessions, so only the chosen exact session is used for the acceptance check.
- **dsh**: counted calls 15,318 vs the worker's own counter 15,135 (1.21% apart, 132 jobs reporting; 19,678 calls counted over all jobs). only jobs that wrote progress.jsonl carry a worker counter; older jobs have no independent count.
- **opencode**: session aggregate output 20,134 vs the sum of its assistant messages 20,128 (0.03% apart).

## Code-intel vs grep / read / shell

| source | LSP nav | LSP diag | grep tool | read tool | shell (all) | sql tool |
|---|---|---|---|---|---|---|
| dsh | 49 | 90 | 684 | 2727 | 8249 | 613 |
| claude | 7 | 1 | 65 | 148 | 3193 | 44 |
| opencode | 0 | 0 | 0 | 0 | 0 | 0 |

`grep tool` and `read tool` are the dedicated tools only; the shell column is every shell-routed call. `sql tool` is `mcp__reality-data__sql`.

## Top 10 most expensive sessions per source

### dsh

| session | steps | calls | provider out | cache read | context-carry | cost USD | model |
|---|---|---|---|---|---|---|---|
| 20261029T040413Z-5d203544 | 356 | 355 | 223,735 | 0 | 39,791,825.3 | 0.0000 |  |
| 20261028T155107Z-484394b6 | 244 | 265 | 196,927 | 0 | 22,451,802.6 | 0.0000 |  |
| 20261028T142827Z-a646d304 | 201 | 275 | 229,721 | 0 | 19,044,968.4 | 0.0000 |  |
| 20261027T184539Z-fce4cff9 | 217 | 220 | 180,845 | 0 | 17,623,767.9 | 0.0000 |  |
| 20261028T231523Z-f6f865b9 | 215 | 243 | 161,998 | 0 | 16,000,984.1 | 0.0000 |  |
| 20261029T002159Z-598aa67b | 203 | 213 | 157,995 | 0 | 15,807,998.7 | 0.0000 |  |
| 20261027T130242Z-84259659 | 112 | 116 | 258,685 | 0 | 14,803,656.8 | 0.0000 |  |
| 20261029T053108Z-34562ae1 | 218 | 217 | 138,930 | 0 | 14,298,904.8 | 0.0000 |  |
| 20261028T125314Z-007dc139 | 176 | 189 | 173,719 | 0 | 14,162,922.9 | 0.0000 |  |
| 20261028T125051Z-69020cbf | 156 | 155 | 168,000 | 0 | 13,935,337.6 | 0.0000 |  |

### claude

| session | steps | calls | provider out | cache read | context-carry | cost USD | model |
|---|---|---|---|---|---|---|---|
| Tasks/optimizations README and dsh-workers launch · C--Users… | 2,100 | 2,357 | 1,514,693 | 641,035,071 | 1,336,649,311.0 | 204.7760 | claude-opus-5-5 |
| Tasks/optimizations README and dsh-workers launch · C--Users… | 1,152 | 1,308 | 627,231 | 288,473,410 | 379,583,447.0 | 82.7609 | claude-opus-5-5 |
| sv-Info_Diffusion_Model · C--Users-w… | 514 | 465 | 167,342 | 228,295,043 | 64,655,125.0 | 55.2561 | claude-opus-5-5 |
| DeepSeek jobs and worker fleet setup · C--Users-w… | 384 | 423 | 267,115 | 171,462,001 | 46,592,425.0 | 45.5962 | claude-opus-5-5 |
| dsh-worker MCP version 0.2.0 · C--Users-w… | 263 | 274 | 142,214 | 68,925,264 | 17,824,673.0 | 19.7640 | claude-opus-5-5 |
| Stress-test and harden dsh-worker MCP server · C--Users-w… | 149 | 147 | 129,449 | 38,161,847 | 11,795,317.0 | 15.4280 | claude-opus-5-5 |
| neo-Info_Diffusion_Model · C--Users-w… | 185 | 175 | 125,036 | 40,498,731 | 11,707,076.0 | 14.3141 | claude-opus-5-5 |
| agent-a4 · C--Users-w… | 81 | 85 | 95,500 | 21,046,678 | 4,376,614.0 | 0.0000 | claude-opus-5-5 |
| Setup status check: Codex, DeepSeek, database · C--Users-w… | 112 | 107 | 58,020 | 16,462,970 | 2,885,857.0 | 7.1829 | claude-opus-5-5 |
| neo-Info_Diffusion_Model · C--Users-w… | 41 | 112 | 68,706 | 7,430,000 | 1,609,579.0 | 3.9215 | claude-opus-5-5 |

### opencode

| session | steps | calls | provider out | cache read | context-carry | cost USD | model |
|---|---|---|---|---|---|---|---|
| asr-correct-inline clip04_company · ses_e85c1d… | 1 | 0 | 4,433 | 6,144 | 0.0 | 0.0000 | deepseek-v4.1-flash-free |
| asr-correct clip06_ama · ses_e85cb8… | 1 | 0 | 3,399 | 4,224 | 0.0 | 0.0000 | deepseek-v4.1-flash-free |
| Greeting · ses_ea13b3… | 5 | 0 | 635 | 17,592 | 1,189.0 | 0.0017 | beam-free |
| modeltest iceman-contributor-free q2 · ses_e76a9f… | 1 | 0 | 1,695 | 1,017 | 0.0 | 0.0000 | iceman-contributor-free |
| modeltest iceman-contributor-free q4 · ses_e769d5… | 1 | 0 | 1,687 | 605 | 0.0 | 0.0000 | iceman-contributor-free |
| modeltest iceman-contributor-free q1 · ses_e76a9f… | 1 | 0 | 1,034 | 70 | 0.0 | 0.0000 | iceman-contributor-free |
| modeltest iceman-contributor-free q3 · ses_e76a9f… | 1 | 0 | 858 | 1,017 | 0.0 | 0.0000 | iceman-contributor-free |
| modeltest deepseek-v4.1-flash_max q4 · ses_e769d5… | 2 | 0 | 790 | 0 | 0.0 | 0.0159 | deepseek-v4.1-flash |
| modeltest iceman-contributor-free q5 · ses_e769d5… | 1 | 0 | 767 | 70 | 0.0 | 0.0000 | iceman-contributor-free |
| modeltest deepseek-v4.1-flash_max q2 · ses_e769d5… | 1 | 0 | 662 | 0 | 0.0 | 0.0079 | deepseek-v4.1-flash |

## Share of each source's tokens by class

- dsh: .py read ranged 17.1% · inline Python other 15.5% · other file reads 15.3% · .py read whole file 10.6% · shell search 7.2% · shell list/stat 4.9%
- claude: subagent or worker control 41.9% · shell file read 14.2% · inline Python other 8.3% · shell search 6.7% · other file reads 6.5% · edit/write 4.6%
- opencode: no tool calls, so no class share (tokens and cost only)

## Thinking output vs visible output

| source | thinking tokens | visible output | thinking share | thinking (est from event text) |
|---|---|---|---|---|
| dsh | 0 | 12,964,501 | 0.0% | 6,458,839 |
| claude | 731,509 | 2,571,392 | 22.1% | - |
| opencode | 194,246 | 20,134 | 90.6% | - |

Claude reports thinking inside `output_tokens` (as `output_tokens_details`); OpenCode reports `tokens_reasoning` beside `tokens_output`, so its share is over the sum. dsh records no provider thinking split; its provider total is all output, and the last column is the thinking *text* length / 4.

## Classification accuracy

30 random shell rows per class are printed to the samples file. Verdicts are entered by hand; the measured precision is below. Classes not listed were not sampled (too few rows).

| class | sampled | correct | precision |
|---|---|---|---|
| shell file read | 30 | 30 | 100.0% |
| shell search | 30 | 29 | 96.7% |
| shell list/stat | 30 | 30 | 100.0% |
| inline Python DB query | 30 | 30 | 100.0% |
| inline Python other | 30 | 30 | 100.0% |
| tests/compile | 30 | 30 | 100.0% |
| bench or gate runs | 30 | 30 | 100.0% |
| git | 30 | 30 | 100.0% |
| sleep/poll | 30 | 30 | 100.0% |

## What could not be measured, and why

- **dsh output sizes are lower bounds for truncated results** (the event writer caps them); truncated results: 1485.
- **dsh input tokens are not recorded** anywhere in the job directory (events carry no usage); only provider output tokens and model steps are available from `progress.jsonl`.
- **OpenCode holds no tool calls at all** in the live DB: only text/reasoning parts. It is reported for model, tokens and cost, with zero tool calls — not omitted.
- **Codex is absent** on this machine (`~/.codex/sessions` does not exist).
- **pytest is not installed** for the interpreter that runs this report, so the fixture test was executed with `python -m unittest reality_engine.tests.test_tool_usage_report`; the file is a plain `TestCase` and pytest will collect it unchanged.
- **Direct Go API readers are out of scope.** `reality_engine/scripts/{extract_news_prices,extract_deck_figures,concall_pilot,ar_queue}.py` post straight to `opencode.ai/zen/go/v1/chat/completions` with no tool calls. `reality_engine/toolbelt/cost_ledger.py` already writes `tasks/ledgers/spend.jsonl`, but no reader calls `charge()` and that ledger does not exist, so their tokens are uncountable from local state. To count them: call `charge()` (or `cost_ledger --add`) after every response, then sum the ledger by purpose; fall back to the provider's billing export.
