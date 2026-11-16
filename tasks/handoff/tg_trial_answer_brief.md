# Telegram trial: answer brief (one worker per batch)

Goal: answer every question in `{batch}` from the company's own store only, and say exactly what the store lacked.

Files: read `{batch}` (one JSON object per line: qid, symbol, store_db, question, theme, data_needed, as_of).
Write `{answers}` (one JSON line per question, appended as you go, never rewritten).

## How to ask the store
Run from the repo root, with `REALITY_DATA_ROOT` set to the main checkout's `reality_engine/data`:

    python -m reality_engine.scripts.p3ask --db <store_db> --qid <qid> --log {calls} <tool> symbol=<SYM> as_of=<as_of> ...

Tools: fact, kpi, fin, ratio, holding, statements, guidance, topic, search, docs, page, cells, tech, calc, catalog,
sql. Start with the routed tool (fact for one number, guidance for targets, topic for a theme across calls,
statements for what management said, holding for shareholding, fin/ratio for financial lines, search/page for
anything else). `sql` is the last resort; say why when you use it.

## Each answer line
    {"qid": ..., "symbol": ..., "answer": "<the answer with figures, periods and units>",
     "tools": ["<tool> <args>", ...], "sources": [{"doc_key": ..., "page": ..., "known_at": ...}],
     "gap": "<what the store should have held to answer fully, with the tool/table you looked in; '' if none>",
     "status": "answered | partly | not_found | out_of_scope"}

Rules:
- Every figure comes from a tool reply; compute ratios with `calc` and show the formula.
- A question about opinion or the future is answered from what management said or guided, quoted with date.
- `not_found` only after at least two different tools; name both in `gap`.
- Never read raw PDFs, the internet or another company's store.
- Budget: at most 12 tool calls per question; move on after that and record the gap.

Accept: one line per qid in `{batch}`, valid JSON. Stop if: every qid answered, or 4 hours.
Evidence: the stores were built 16-17 Nov from exchange filings since 2024-04-01 (R-001..R-012 in
`tasks/store_repair/INDEX.md` list the known gaps).
Budget: 4 hours, 12 tool calls per question.
