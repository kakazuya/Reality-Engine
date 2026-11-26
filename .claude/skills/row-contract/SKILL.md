---
name: row-contract
description: What every stored row must carry (numbers/KPIs, call statements, guidance) and the checks that keep it usable for forecasts and backtests. Use when designing a reader prompt or gate, writing a loader, adding a table, or judging whether a stored row is right.
---

# Row contract (obs_fact / observation)

A row is served only when `status='verified'`; `unverified` is served labelled; `quarantined` never. Unsure = no row. The author of a reader never writes its checks (`row_checks` layer is independent).

## Every row
`symbol, doc_key, page, known_at` (point in time: filing before 15:30 IST -> day T, after -> T+1; `doc_date` is the crawl date, never use it as known_at), `record_type`, `reader`, `read_at`, read provenance `read_model` (e.g. `opencode-go/hy4-flash-free`), `read_gateway` (opencode-go / opencode-zen / kilo-gateway / google-ai-studio / ...), `read_harness` (our script, agy, Claude Code, dsh, OpenCode harness), `prompt_fp` (Shivam 26 Nov: every reader and every new table writes these, see `observations.read_provenance`), `text_source` (text layer / ocr / jumbled), `status`, `status_reason`.

## Number / KPI rows
| Field | Must be | Common failure (seen in grades) |
|---|---|---|
| value, value_text | exactly as printed; value_text keeps the print | footnote digits glued to labels |
| unit, scale | from the printed unit line ("Rs Cr", "in lakhs") | invented unit; scale missed |
| period, period_kind, period_source | from a printed column/period header | guessed period; comparative column taken as current |
| basis, basis_source | consolidated / standalone from the page heading or doc section | "Notes annexed to the Consolidated..." missed |
| entity_scope | company / named subsidiary / segment; never an unnamed subsidiary or market/peer figure | governance, shareholding pages mis-tagged subsidiary |
| printed_label, measure | label as printed; measure code; `NEW:` codes keep the words | subset row stored as the total |
| is_total, value_kind | flow (period) vs stock (as at) | closing balance stored as a flow |
| segment, product, geography, customer, group_path | only when printed | current vs non-current swapped |
Check arithmetic: totals, growth %, QoQ/YoY columns. Any filed (XBRL) figure stays as filed; a call/deck number is unverified until a held filing matches within 1%.

## Statement rows (calls)
`statement` verbatim (never paraphrased), `speaker` named (never "Management"; check in-document handovers), `direction`, `question_context` (the analyst question it answers), call date. Fill where printed: period, segment, speaker role. Drop greetings and handover lines.

## Guidance rows
metric (not "other"), period, low/high, unit, the verbatim quote, revisions kept as new rows (latest served first).

## Scope reminders
Store verbatim first, compute later; an unstated number is a formula, not a gap. Before saying "not held", check `tasks/DATA_INVENTORY.md` and raw text.
