# Retrieval architecture for reasoning questions (2026-10-25)

Goal: data fetching is fast, deterministic and offline, so the model's budget goes to reasoning.
A question is answered in about 3–10 tool calls that each return compact, cited, point-in-time rows. It should not take
50–100 calls of SQL guessing. The eval set is `measure/EVAL25.md`. Every layer below is judged on it.

## Layers

```
 question
   │  L5 eval harness: offline run, scoring, cheat detection, regression gate
   ▼
 L4 evidence contract : every row = {evidence_id, known_at, value/quote}; as_of filter; cite_check
 L3 search            : one search() over all FTS5 indexes (+ optional dense rerank), PIT-filtered, quota per source
 L2 analytics         : returns/CAGR, event_window, rolling_corr, etf_tracking, peer_compare, macro_series
 L1 lookups (built)   : delivery, price_extreme, holding, docs, doc_page, doc_find, facts, price
 L0 identity          : resolve (+ ETFs/MFs), universe(theme) → member list
   │
 data plane: SQLite stores + truth DuckDB snapshot + NumPy vector indexes (read-only)
```

### L0 Identity
- `resolve` covers ETFs/MFs (`etf_master`, `fund_nav`, `bse_master` INF* codes). Today `resolve("543437")` returns nothing.
- `universe(theme, as_of)` turns "gold stocks", "OMCs", "listed HFCs", "dairy companies" or "data-centre players"
  into a member list. Members come from `company_industry` + `business_model_profiles` + a curated
  `universes.yaml`. The tool returns the member list and why each company is in it. Q16, Q17, Q18, Q24 and Q25 need it.

### L2 Analytics (new; deterministic numbers the model must not compute by hand)
| tool | answers | source |
|---|---|---|
| `returns(symbol, start, end)` | CAGR and total return on adjusted prices, with exact start/end rows | `px_*_adj` |
| `event_window(symbol\|universe, start, end)` | the price path, turning points, and the largest daily moves with their dates | px + `events` |
| `macro_series(name, start, end)` | commodities, USDINR, FII/DII, index TRI levels and changes | `mkt_commodity_daily`, `fii_dii_cash`, `index_tri` |
| `rolling_corr(symbol, series, window, start, end)` | correlation regimes, e.g. pre/post Mar-2026 sign flips (Q20) | px + macro_series |
| `etf_tracking(symbol, start, end)` | ETF price vs NAV vs iNAV, premium/discount, tracking error, FX vs index split (Q19) | `etf_px`, `fund_nav`, `etf_inav` |
| `peer_compare(universe, metrics, periods, filters)` | ranked peer table with QoQ/YoY and filter flags (Q17) | results XBRL + deck/concall facts |
| `fin(symbol, metrics, period)` | named metrics across taxonomies (bank net NPA %, segment revenue, geo split) | `results_facts` concept map |

### L3 Search
- One `search(terms, scope, symbol|universe, date_from, date_to, as_of)` over the existing FTS5 indexes: `pib_releases_fts`,
  `policy_events_fts`, `cc_items_fts`, `ar_facts_fts`, `intelligence_fts`, `facts_metric_fts` and RBI/Budget `raw_documents`.
- Ranking is BM25, with a fixed quota per source so one store cannot starve the others (today chunk hits starve `ar_facts`).
  Results are deduplicated and sorted by date.
- `policy_timeline(terms, from, to)` returns the first and the later mentions per source (PIB, RBI, Budget,
  policy_events, concall, deck). It answers "published by PIB or only RBI?" (Q21), "what changed vs the earlier scheme"
  (Q23, Q25) and "PIB before transcripts" (Q16).
- `first_seen(terms|signal, scope)` returns the earliest PIT date at which evidence existed. Q18 is graded on this date.
- **Dense search is a second stage only.** It reranks the FTS candidates with the Nemotron index. The query vector is
  cached on disk by query text, so the same question always gives the same ranking. Query embedding today needs paid
  DeepInfra calls (`REALITY_DATA_ALLOW_PAID_EMBED=1`), so dense search stays off until Shivam decides.

### L4 Evidence contract (what makes it deterministic and checkable)
- Every tool row carries `evidence_id` (`db.table:key`, or `doc_id#page`) and `known_at`.
- Every tool takes `as_of`; rows known after it are dropped and counted in `hidden_after_as_of`. This is also the
  foundation for the next set (forecasting): the model cannot see the future through the tools.
- `cite_check(answer)` re-reads every cited evidence id and confirms that the value or quote is there. Uncited
  claims are flagged.
- Results come back as compact tables (no raw JSON dumps), with a `found:false` + `nearest` + `hint` on misses.

### L5 Eval harness and anti-cheating
- `eval/run.py --set EVAL25 --runs 2` starts read-only workers with the routing guide, collects answers, and scores
  correctness against `EVAL25_KEY.md`, evidence validity (cite_check), tool calls, wall time and output tokens.
  It writes `eval/results/<date>.json` and a one-page diff against the last run.
- **No internet:** four guards, any one of which disqualifies the run.
  1. **Tool allow-list:** reality-data MCP + `reality_engine.toolbelt.*` + read-only file reads. Web/fetch tools are
     off in the eval profile.
  2. **Network block for child processes:** `HTTP(S)_PROXY=http://127.0.0.1:9`, with `NO_PROXY` set only for the model
     endpoint and localhost. curl, requests and urllib then fail fast.
  3. **Log audit:** the run's event log is scanned for web tools, URLs and `curl`/`Invoke-WebRequest`/`requests.get`.
     Any hit flags the run.
  4. **Citation gate:** a claim from memory or the web has no valid evidence id, so it scores 0 even if true.
- **Gate:** a new tool, prompt or context change merges only if it does not lower accuracy and it improves tool
  calls or wall time. This is the same rule that turned the context pack off.

## Data jobs (writes; each needs Shivam's OK)
| job | unblocks |
|---|---|
| Store deck page text in `deck_figures.db` (no Drive fetch per page) | Q9-type questions, doc_find on decks, Q17, Q25 |
| Refresh BSE announcements + corporate_documents past 2026-10-19; rebuild the truth snapshot | Q6, any question about the latest documents |
| Store text of results-filing PDFs (notes to results) | Q14 "Note 5" |
| Commodity daily past 2026-10-06; coal series past 2025-12 | Q23 context, later forecasting |
| Fill `etf_premium` (price vs NAV per day) | Q19 (`etf_tracking` can compute it on the fly meanwhile) |

## Build order (DeepSeek workers, off-peak, each with review → fix → re-review)
0. **Baseline:** run EVAL25 Q11–25 twice with today's tools. The run drafts the answer key and logs where calls are
   wasted. Claude verifies the key.
1. **W1 identity:** ETF/MF resolve + `universe` + `universes.yaml`.
2. **W2 numbers:** `fin`, `returns`, `peer_compare`.
3. **W3 text:** unified `search`, `policy_timeline`, `first_seen`, plus the `as_of` / `evidence_id` contract.
4. **W4 market analytics:** `macro_series`, `event_window`, `rolling_corr`, `etf_tracking`.
5. **W5 harness:** `eval/run.py`, cite_check, offline guards, results diff.
W1–W5 touch separate new modules. Each registers in its own delimited block in `server.py`, as L1/L2 did, so they
can run in parallel. Claude writes the routing guide after the merges. The gated EVAL25 re-run comes last.

## Next set (forecasting) hooks already in this design
`as_of` on every tool; `first_seen` for "when could you have known"; `macro_series` + `peer_compare` for quantified
growth; a forecast log (extend `forecast_skill_history`) so each predicted number and probability is scored later
against what happened.
