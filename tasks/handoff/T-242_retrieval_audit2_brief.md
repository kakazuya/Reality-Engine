# T-242 retrieval audit 2: fresh questions on the merged retrieval fix (DeepSeek, read-only, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: retrieval fix 1 (c59c6076, by Hydrogen) makes pilot3_fact / kpi / statements / guidance / nearest serve VERIFIED
obs_fact rows first. It scored 20/20 on the 20 questions it was tuned on (audit 1: 13/20 before). Judge it on FRESH
questions and companies. The running MCP servers still hold the old code, so call the CHANGED functions in-process:
`import sys; sys.path.insert(0, "plugins/reality-data/server"); import lookups_pilot3 as L` with
`REALITY_PILOT3_STORES=D:/RealityEngine/stores.json` set, then call L.fact / L.kpi / L.statements / L.guidance /
L.obs exactly as the MCP tools do (read server.py for the argument names).

Files: plugins/reality-data/server/server.py (tool -> function map and INSTRUCTIONS routing),
plugins/reality-data/server/lookups_pilot3.py. Stores via D:/RealityEngine/stores.json (universe stores c1-c681).

Evidence: audit 1 companies (do NOT use them): AADHARHFC, ADFFOODS, ADVENZYMES, AEGISLOG, AJCJEWEL, ASALCBR, AUSTERE,
BAJAJFINSV, BANSWRAS, BCLIND. Pick 10 OTHER universe companies with both deck and transcript rows in obs_fact
(`SELECT doc_type, count(*) FROM obs_fact GROUP BY 1`), spread across sectors (a bank or NBFC, an EPC or infra
company, a manufacturer, a consumer company, an IT company...).

Accept: the final answer holds the 20-row table and the counts.
Stop if: the in-process import fails twice. Report the error; do not edit code.
Budget: about 75 minutes; read-only (write and commit no files).

Steps:
1. For each of the 10 companies, ask 2 real investor questions answerable from the latest call or deck: one number
   (e.g. AUM, order book, margin guidance) and one management view (e.g. demand outlook, capex plan). 20 questions.
2. Answer each the way a cheap model would: follow server.INSTRUCTIONS routing (the merged text) (pilot3_fact /
   pilot3_guidance / pilot3_kpi / pilot3_statements / pilot3_topic / pilot3_obs ...). Record every tool call made.
3. For each answer record:
   - the tool that answered;
   - whether the cited row is an obs_fact row (and its status: verified or unverified) or an old-table row;
   - whether the answer is right against the page;
   - whether a better verified obs_fact row existed that the tools did not return. Check with
     `pilot3_sql "SELECT ... FROM obs_fact WHERE ..."`.
4. Final answer, part 1: a table with columns q, symbol, question, tools_called, answer, source (table/row/status),
   right(Y/N), better_row_missed(Y/N + id).
5. Final answer, part 2: counts (right; used obs_fact; better row missed), the routing gaps (which question kinds go to
   a tool that ignores obs_fact), and the 3 most useful fixes, each naming the tool and the file
   (plugins/reality-data/server/*.py).

Rules: read-only. Write and commit no files. Do not read raw PDFs; the store's doc_page text is enough for checking.
Budget: about 75 minutes.
