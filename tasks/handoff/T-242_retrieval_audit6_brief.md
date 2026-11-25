# T-242 brief: retrieval audit 6 (after fix 5), read-only, non-author

Goal: fresh-question audit of the reality-data lookup tools after retrieval fix 5 (merged 316f0734), graded R/P/W/M/N against page text, comparable with audits 2-5.
Files: none written (read-only). Put the full report (markdown) in your final answer; Wolf saves it to C:/RealityEngine/t242/retrieval_audit6/report.md.
Accept: 48 graded rows with tool call, returned value/quote, rank and grade; counts by slice; comparison table; top 3 causes with one example each.
Evidence: audits 2/3/4/5 = 33R8P3W4M / 32R12P0W4M / 45R3P / 36R1P0W11M of 48. Fix 5: a named call's obs_fact statements and doc_page hits now come from documents whose PRINTED call date (transcript_statement.call_date) or filing date is within 3 days; replay of the 16 audit-5 statement asks went 4R3P9M -> 15R1P.
Stop if: fewer than 8 eligible fresh companies, or the lookups module will not import.
Budget: ~120 tool calls. Off-peak run.
Ticket: T-242

Follow the recipe in `.claude/skills/retrieval-audit/SKILL.md` exactly. Specifics:

1. Companies: eligible universe stores (deck >= 20 and transcript >= 1 obs rows; see `C:/RealityEngine/t242/load_universe.log`), excluding every company in earlier audits: KEI ARTEMISMED ACLD BRITANNIA BORORENEW BLACKROSE ARPOB ACMERAIL AJAXENGG AVANTIFEED AUBANK AGARWALEYE BLEL BELRISE ARKADE BANDHANBNK BATAINDIA AUROPHARMA ADFFOODS ASAHISONG APPL BBOX BHARATFORG APEX BLACKBUCK AJCJEWEL BIGBLOC AADHARHFC BIKAJI BRGIL ABFRL BOSCHLTD AIRFLOA AWHCL AEGISVOPAK ANGELONE ABDL BRIGADE AGL BHARTIARTL. Pick with `random.Random(1126).sample(sorted(eligible), 8)`; print the list first.
2. Pin every call: `os.environ["REALITY_PILOT3_DB"] = <that company's store>` and `sys.path.insert(0, "plugins/reality-data/server"); import lookups_pilot3 as L`. Read the tool descriptions in `plugins/reality-data/server/server.py` and call as they instruct. No MCP server, no model calls.
3. Per company: 3 numbers (printed label + period), 2 statements naming a call, 1 guidance = 48 questions. Vary how the call is named (Shivam): one statement ask uses the call date printed inside the transcript, the other the date the transcript was filed (pick calls where those differ by more than 3 days when the company has one). Report both dates for every statement row.
4. Grade strictly: R right value/quote first; P right but not first (record rank) or a wrong row first; W wrong served as the answer; M missing though held; N not held (prove with page text). Re-open the page text for every W and M; recompute any derived number.
5. Also measure: reply bytes per call (cap 19,000), rows_cut present or not, and any row from another call in a named-call reply (count them).

Limits: read-only; do not touch hy4 readers or stores under C:/RealityEngine/tg_build (read only, mode=ro). Never kill processes by name. pytest not needed.
