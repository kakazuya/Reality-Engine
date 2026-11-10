Ticket: T-171
Goal: independent read-only review of T-171 (cut per-worker RAM) before merge. You did not write it. Do NOT edit any file. Branch dsh/20261110T104718Z-42948b98 head 4a1b8d9c, worktree R = C:/Users/warri/Downloads/IDM-worktrees/20261110T104718Z-42948b98.
Evidence: diff = code workers skip the data-gather MCP (`- id: mcp-data-gather / disabled: true` appended to the per-run dsh patch unless --data-job), dsh-worker start_worker passes --data-job for write_scope='data' or data_job=True, reality-data lazy-imports duckdb, sqlite page caches cut (core.connect_sqlite 128 MB -> 32 MB, mmap 256 -> 64 MB; lookups_pilot3 64 -> 16 MB; search_docs 256 -> 64 MB). Controller verified: tests pass (harness controls 7, dsh_worker_plugin 80, lookups_pilot3 32, lookups_docs 18) and a live Beam smoke run with the branch harness saw only code-tools and reality-data and called catalog and outline successfully.
Steps:
1. Read git diff main...HEAD. Flag anything unsafe: a data job (start_job from jobs.yaml, write_scope data) that would now lose data-gather; any caller of build_patch not updated; any path where duckdb is used before _duckdb() is called (grep every `duckdb.` use in plugins/reality-data/server/*.py).
2. Latency: time 20 typical reality-data calls (pilot3_sql, pilot3_fin, pilot3_kpi, pilot3_search, search_docs if available) by importing the server modules from main (C:/Users/warri/Downloads/Info_Diffusion_Model) and from R in two fresh python processes each; report p50/p95 per side. The target is answers under 10 s, so flag any call slower by more than 20%.
3. RSS: in each process report RSS after import and after the 20 calls.
Files: none written by you (scripts via python - on stdin).
Accept: final answer holds the diff findings, the latency table main vs branch, the RSS table, and MERGE or SEND BACK with reasons.
Stop if: you would need to change code to judge something.
Budget: <=60 tool calls. Do not edit tasks/STATE.md. Do not write D:/.
