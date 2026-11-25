# T-242 brief: retrieval fix 8b - quarantined rows are never served (standing ruling)

Goal: on top of fix 8 (branch dsh/20261125T222633Z-30c94e90, head a536b346), remove the "serve a quarantined KPI with check_status 'quarantined' + warning" path; a quarantined-only match returns found=false with the existing `held_quarantined` disclosure (value, page, how to show it with include_quarantined=true), exactly as before fix 8. Everything else in fix 8 stays.
Files: plugins/reality-data/server/lookups_pilot3.py, plugins/reality-data/server/server.py (pilot3_kpi description), plugins/reality-data/tests/test_retrieval_fix8.py, plugins/reality-data/tests/test_lookups_pilot3.py (KEC GNPA case back to the held_quarantined contract), docs/DEVELOPER_GUIDE.md, machines/MSI_LAPTOP.md
Accept: pytest test_retrieval_fix8/7/6/5/4/3/2 + test_lookups_pilot3.py pass; the 144-row replay (.tmp/replay_f8.py in the fix-8 worktree; copy at C:/Users/warri/Downloads/Info_Diffusion_Model/.tmp/replay_f8.py) vs live main: 0 R lost in audits 6/7/8; audit 8 expected 27R -> 32R (the two quarantined-KPI gains, BLUESTARCO capex 130 cr and AFFORDABLE orders 22 cr, go back to M with held_quarantined).
Evidence: Shivam's architecture ruling (8 Nov, RULINGS): every extracted row is verified / unverified (served labelled) / quarantined (NEVER served). Wolf's fix-8 brief asked for the served-quarantined path by mistake; the reviewer caught it.
Stop if: removing it changes any other replay row.
Budget: ~40 tool calls
Ticket: T-242

## Limits
Stores read-only (mode=ro), no model calls, pytest per file, never kill processes by name.
