Ticket: T-197

Goal: make the reality-data `pilot3_*` tool replies (and their `p3ask` CLI twins) tell a cheap model, in the reply
itself, everything the store holds that is relevant and what the reply did NOT cover, so the model never has to fight
the tools to find a held answer and never reads a partial reply as complete. Every change is a general rule that works
the same for any company, sector and question. You must not tune anything to a particular question, company or
figure.

## Anti-overfitting rules (binding; the review checks each)
1. You may NOT open `D:/RealityEngine/aurobindo/questions/`, `answers/`, `report/`, `rerun_t195/`, `D:/RealityEngine/aurobindo_ab/`,
   or any grades file. The evidence below is all you get, on purpose.
2. No company symbol, name, ISIN, product, person or figure in code, vocabulary or tests (`test_pilot3_no_company_literals.py`
   must pass). Test fixtures use invented companies ("ACME", "Foo Pharma") and invented numbers.
3. A change is accepted only if it is a property of the reply shape or the search method (coverage, paging, text
   reach, date rules), never a new special case. If a fix needs a word list, it goes in the existing lexicon files by
   sector family, with at least two sectors' entries.
4. Measure on stores the test questions never touched as well: pilot10 copy (KEC, HINDALCO, SBILIFE, INFY, MARUTI) and
   the aurobindo copy, with the structural metrics in "Accept". No question-answer scoring by you.

## Evidence (T-196, 12 Nov: 21 held answers missed; the models' own accounts, checked by an Opus grader)
- 8 of 21: the reply LOOKED complete. `topic` and `statements` return only call statements whose tagger topic matched;
  the reply's "4 of 5 items" is a count of tagged rows, which models read as "everything management said". Decks,
  annual reports and filing bodies never appear in those replies (four product approvals sat in a deck table; a
  "from next year we will not have product X" line sat on an untagged Q&A page; a regulator-letter impact sentence
  sat in the body of a one-page filing; a price-erosion answer sat in an untagged earlier call).
- `topic` returned "50 of 113 items" for an inspections theme; the model took the 4 newest as the whole list.
- A search with `date_from` excluded the one call that held the answer; nothing in the reply said so.
- Look-ahead still reached answers through tools other than `page` (a document known after `as_of` cited).
- `cells` returned row labels without values for a press-release segment table (rows exist; `page_cell` count unchanged).
- `event` rows come back with `doc_type`/`title` null at the group level, and carry only the title, not the body
  sentences (impact, observations, classification) that answer the question.
- 8 of 21 were the model stopping at the first plausible hit (did not open the table/page beside a headline figure):
  that part is fixed by reply shape (pointers to the next pages to read) and by the instructions, not by the model.

## Method (do these in order; one test per step first, fixture DB, no real store in tests)
1. **One coverage block on every text reply** (`topic`, `statements`, `search`, `semantic`, `cells`, `docs`): a `coverage`
   object with: `searched` (tables and doc types actually searched), `not_searched` (doc types and sources this tool
   cannot see, by name), `matched_total`, `shown`, `cut`, `hidden_after_as_of`, `outside_date_filter` (matches that a
   `date_from`/`date_to` excluded, with their dates), and `documents` = EVERY matching document (doc_key, type, date,
   title, pages that match, match count) even when its items were cut. The one-line `text` must start with the
   honest scope, e.g. "56 tagged statements + 31 page-text matches in 14 documents (8 calls, 3 decks, 2 annual reports,
   1 filing); 25 shown; 62 cut - call again with offset=25 or read the listed pages". Keep a reply under 20 kB:
   documents beyond 40 are summarised by type and month with counts.
2. **Full-text reach for `topic` and `statements`**: in addition to tagged statements, run the same phrase-first matcher
   `search` already uses (T-194) over `doc_page` text of ALL document types (transcripts' untagged pages, decks,
   annual reports, press releases, announcements/filings), merge by document and date, and label each item
   `match: tag | text`. Lexicon expansion (sector family) applies to both. Untagged transcript pages that match come
   back as page hits with a snippet, not dropped.
3. **Paging**: `offset` on `topic`, `statements`, `search`, `semantic`, `cells`, `docs`; every cut reply says the exact
   next call. Deterministic order (date desc, then doc_key, page).
4. **"Read next" pointers**: when a reply shows a figure from a table/deck page or a headline sentence, include
   `read_next` = the page itself and its neighbours (page-1, page+1) and, for a call, the Q&A pages that mention the
   same terms. This turns "stop at the first hit" into "here is where the rest is".
5. **`as_of` on every tool, one helper**: every lookup that returns document-derived rows (fact, fin, ratio, kpi, cells,
   guidance, statements, holding, tech, docs, search, semantic, topic, page, calc inputs) filters by `known_at <= as_of`
   through one shared function and reports `hidden_after_as_of` with the hidden documents' dates. `sql` gets a
   reply note when its result includes rows known after a passed `as_of`. Add a test per tool.
6. **Date-filter guard**: when `date_from`/`date_to` excludes matches, the reply lists them under
   `coverage.outside_date_filter` (date, doc type, count); a filter never silently hides the answer.
7. **Events carry their bodies**: `event` rows (build `reality_engine/pilot3/events.py`) store `body_excerpt` = the
   sentences of the filing page that state outcome, observations, classification, impact or amounts (sentence split +
   cue words from the lexicon, sector family), plus doc_type and title; `topic` shows them. Fix the null doc_type/title.
8. **`cells` values**: find why label-only rows come back (join or column-pick fault in `cells()` ~line 355) and return
   the value cells with their column headers and period; add a fixture test with a two-column results table.
9. **Instructions**: update the MCP server instructions (`plugins/reality-data/server/server.py`) and `p3ask` help with
   general answer rules, no examples from the test set: (a) a list question is answered only after paging through every
   item the reply counted; (b) "not disclosed" needs `coverage.not_searched` empty or each listed source read; (c) a
   headline figure is checked against its table page (`read_next`); (d) never narrow by date before the period asked;
   (e) prefer the company's printed figure and say when the store's preferred figure is derived.

## Files
`plugins/reality-data/server/lookups_pilot3.py` (topic ~1328, statements ~997, search ~1549, docs ~1265, cells ~355,
`_asof` ~175), `plugins/reality-data/server/lookups_semantic.py`, `plugins/reality-data/server/server.py`,
`reality_engine/scripts/p3ask.py`, `reality_engine/pilot3/events.py`, `reality_engine/pilot3/lexicon/*.yaml`,
tests `plugins/reality-data/tests/test_lookups_pilot3.py`, `reality_engine/tests/test_pilot3_events.py`, `test_p3ask.py`;
docs `plugins/reality-data/README.md`, `docs/PILOT3_BLUEPRINT.md`, `docs/DEVELOPER_GUIDE.md`. Use `code-tools outline`
before reading a long file.

## Accept
- New tests pass, one file per process (`--basetemp=.tmp/pt<n>`, a new name each run); `test_lookups_pilot3.py`,
  `test_pilot3_events.py`, `test_p3ask.py`, `test_pilot3_no_company_literals.py`, `test_lookups_docs.py` all pass.
- On COPIES (copy recipe: checkpoint, copy into `.tmp`, `PRAGMA journal_mode=DELETE`) of `D:/RealityEngine/pilot10/pilot10.db`
  and `D:/RealityEngine/aurobindo/aurobindo.db`, write `.tmp/T-197_MEASURE.md` with, for 12 themes chosen by you from the
  lexicon's generic vocabulary (order book, capex, margin guidance, dividends, buyback, regulator inspection,
  acquisition, credit rating, debt, launches, pricing, capacity) across 5 companies: before/after `matched_total`,
  documents and doc types reached, `not_searched`, reply bytes, seconds. Before = main code, after = branch, same copy.
- Every reply stays under 20 kB at default limits; median `topic` time under 2 s on the copies.

## Stop if
- a change needs a company/question literal or a test-set question (stop and write why);
- a reply grows past 20 kB for a normal theme and cannot be summarised (report sizes);
- the T-198 worker's files collide (it owns `reality_engine/pilot3/row_checks.py` and `fact()` in lookups ~2305; do not
  edit those).

## Budget
4 hours, one session, DeepSeek off-peak. Never write to live stores. Do not commit PROGRESS_NOTES.md.
