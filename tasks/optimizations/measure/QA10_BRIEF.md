# Task — answer 10 company-data questions from our local data, with provenance

## Goal
Answer each question below from the local data stores only (read-only), each answer with its exact source.

## Why
This measures how fast a worker can find facts in our data and how accurate the answers are.

## Files to touch
- Write your answers only to your final message. Scratch files only under `.tmp/` if needed.
- Do not touch: any tracked file, any database (read-only access only).

## Inputs/data
Local data only. **Route by question shape first, one call each, before any SQL:** delivery → `delivery`; high/low/YTD →
`price_extreme`; promoter holding / share count → `holding`; which/latest documents → `docs`; "page N of the <date>
deck" → `doc_page`; "what did they say about X in the <date> transcript/deck" → `doc_find`. These are reality-data MCP
tools, and the same functions run as CLIs: `python -m reality_engine.toolbelt.lookup_market <tool> ...` and
`python -m reality_engine.toolbelt.lookup_docs <tool> ...` (`--help`). Then the other `reality-data` MCP tools (`resolve`, `price`, `facts`, `search_docs`, `sql`),
otherwise the SQLite databases and DuckDB snapshot via `reality_engine.db.readonly.connect_ro` (never a bare
`sqlite3.connect`), the toolbelt (`python -m reality_engine.toolbelt.<tool> --help`, e.g. `coverage_peek`, `find_docs`),
and the stored PDF/transcript files. No internet. No paid embedding calls.

## Questions
1. What was the **delivery volume** (delivered quantity, not total traded quantity which includes intraday) of Ather Energy Ltd on 13 April 2026 and 14 April 2026, **NSE + BSE combined**? Give NSE, BSE and the sum per day.
2. What is the promoter holding of NSE: BLACKBUCK as of September 2026?
3. How many manufacturing facilities does Ganesha Ecosphere have, per its investor presentation of 5 August 2026?
4. What are the key products of Chemcon Speciality Chemicals per its investor presentation of 22 May 2026, and whom did it mention as acquired for inorganic growth?
5. How many equity shares does Lumax Auto Technologies have, and what is the promoter holding, as of the latest data?
6. What did BSE: 540879 show on page 21 (of 79) of its investor presentation dated 24 October 2026 regarding a licence to manufacture?
7. What did ISIN INE864I01014 say about its fuel-cell capacity expansion due to complete by the end of this year, per its transcript of 6 August 2026?
8. What was the YTD high price of BSE: 532810 in 2026 (value and date)?
9. What did NSE: SAILIFE say about its newly commissioned facilities, as of the latest data?
10. Per the transcript of 18 September 2026 of 540678 / COCHINSHIP: what did it say about the MOU with HD KSOE, and how will EBITDA margins progress from electric tug boats, and what is the plan?

## Steps
1. Resolve each identifier (symbol / BSE code / ISIN / name) to the company first.
2. Find the fact in the store that holds it; quote the source text or the row.
3. If the data does not hold the answer, say exactly that and what you checked. Never guess or use memory.

## Acceptance checks
1. Every question has: answer, source (db.table + key, or document path + page / timestamp), and a short verbatim quote or row values.
2. Answers not found in data are marked `NOT IN DATA` with what was searched.
3. No writes anywhere except `.tmp/`.

## Test command(s)
None (read-only answering task).

## Budget
- ≤ 25 tool calls before the first useful lookup; ≤ 150 total; ≤ 45 min wall; $0 paid.

## Report format
For each question: `Q<n>: <answer> | source: <...> | quote: "<...>"`. Then: tool calls before first edit / total.

## Out of scope
Fixing data gaps; fetching anything from the internet.
