# T-242 retrieval audit 1: do the reality-data tools serve the loaded hy4 rows? (Hydrogen, read-only, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: Shivam's standing order is to audit read quality AND retrieval. Decks and universe transcripts were loaded today
into the 681 universe stores (table `obs_fact`; the tools route to them through D:/RealityEngine/stores.json since
14:50). Find out whether a model answering investor questions through the reality-data MCP tools reaches those rows,
and where it gets wrong or stale ones instead. Known lead: `pilot3_statements` reads the old `transcript_statement`
table (ungated greetings such as "Thank you so much, Shreya"), while the graded v3 statements sit in `obs_fact`, which
`pilot3_obs` serves.

Companies (all loaded, with deck and transcript rows): AADHARHFC, ADFFOODS, and 8 more that you pick at random from
`pilot3_sql(store=..., "SELECT symbol FROM company")` over stores c100-c600 that have obs_fact rows. Check with
`SELECT doc_type, count(*) FROM obs_fact GROUP BY 1`.

Steps:
1. For each of the 10 companies, ask 2 real investor questions answerable from the latest call or deck: one number
   (e.g. AUM, order book, margin guidance) and one management view (e.g. demand outlook, capex plan). 20 questions.
2. Answer each the way a cheap model would: follow the reality-data server instructions' routing (pilot3_fact /
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
