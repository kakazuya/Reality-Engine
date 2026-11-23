# Telegram trial: answer brief (one worker per batch)

Goal: answer every question in `{batch}` from the company's own store only, and say exactly what the store lacked.

Files: read `{batch}` (one JSON object per line: qid, symbol, store_db, question, theme, data_needed, as_of).
Write `{answers}` (one JSON line per question, appended as you go, never rewritten).

## How to ask the store
Run from the repo root, with `REALITY_DATA_ROOT` set to the main checkout's `reality_engine/data`:

    python -m reality_engine.scripts.p3ask --db <store_db> --qid <qid> --log {calls} <tool> symbol=<SYM> as_of=<as_of> ...

Tools: fact, kpi, fin, ratio, holding, statements, guidance, topic, obs, events, search, docs, page, cells, tech, calc,
catalog, sql. `obs` searches the figures, management statements and guidance read from decks, annual reports and call
transcripts (args measure=, terms=, period=, record_type=number|statement|guidance); `events` lists order wins, capex
and fund raises (kind=). Rows with status 'unverified' are usable but say so in the answer. Start with the routed tool (fact for one number, guidance for targets, topic for a theme across calls,
statements for what management said, holding for shareholding, fin/ratio for financial lines, search/page for
anything else). `sql` is the last resort; say why when you use it.

## Each answer line
    {"qid": ..., "symbol": ..., "answer": "<the answer with figures, periods and units>",
     "tools": ["<tool> <args>", ...], "sources": [{"doc_key": ..., "page": ..., "known_at": ...}],
     "gap": "<what the store should have held to answer fully, with the tool/table you looked in; '' if none>",
     "status": "answered | partly | not_found | out_of_scope"}

Routes by theme (try these before giving up; a `search` alone is never enough):
- accounting (receivables, debt, cash flow, margins, write-offs): fin, ratio, fact, then search/page for the note.
- long_vs_short (is this an entry / valuation): tech (52-week range, moving averages), ratio (PE, PB, ROE), fin trend.
- revenue_sources, segments, geography: kpi, fin, topic, search; read the page the hit names (`page`).
- forward_profitability, next_two_quarters: guidance, statements, topic, then the last two quarters' fin.
- integration_pivot (acquisitions, new businesses): topic, statements, docs, search, page.
- transcript (what management said on a call): statements, topic, obs record_type=statement terms=..., docs.
- order book, order wins, capex, fund raises: events, kpi, obs, topic.
- any figure fact/kpi/fin lacks: obs measure=... or obs terms=... before search.

Rules:
- `partly` or `not_found` needs at least three different tools from the routes above; before you finish run
  `python -m reality_engine.scripts.tg_trial check --answers {answers} --calls {calls} --batch {batch} --min-kinds 3`
  and redo every qid it lists (append a new line for that qid; the last line wins).
- Every figure comes from a tool reply; compute ratios with `calc` and show the formula.
- A question about opinion or the future is answered from what management said or guided, quoted with date.
- `not_found` only after at least two different tools; name both in `gap`.
- Never read raw PDFs, the internet or another company's store.
- Budget: at most 12 tool calls per question; move on after that and record the gap.

Accept: one line per qid in `{batch}`, valid JSON. Stop if: every qid answered, or 4 hours.
Evidence: the stores were built 16-17 Nov from exchange filings since 2024-04-01 (R-001..R-012 in
`tasks/store_repair/INDEX.md` list the known gaps).
Budget: 4 hours, 12 tool calls per question.
