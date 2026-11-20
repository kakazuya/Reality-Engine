# T-228 brief: driver-tree claims from management text (phase 1)

Ticket: T-228 (Shivam 20 Nov 2026). Owner of review: Wolf (Opus). You build and test; Wolf reads your output
between stages. Do ONLY stage 1a below, then stop and report. Later stages arrive as follow-up messages.

Goal: turn verbatim management text already in the company stores into quantified claims on the company's
financial model (the "driver tree"), so a later factor study can test whether text adds prediction over hard
numbers. A statement that changes no node of the tree is dropped ("no_driver"): Shivam's rule is that anything
that does not end in revenue, operating cost, capex, debt or equity is show, not data.

## Driver tree (fixed vocabulary; do not add nodes without saying why in your report)
- revenue.volume (units, tonnes, MW, orders executed, capacity x utilisation), revenue.price (realisation, ASP),
  revenue.total (revenue / growth % when volume and price are not split), revenue.order_book (order book, order inflow,
  execution period)
- cost.raw_material, cost.employee, cost.power_fuel, cost.other, margin.ebitda (margin % or bp change), margin.gross
- capex.amount, capacity.add (new capacity, commissioning date, utilisation path)
- debt.level (borrowings, net debt, repayment), debt.cost (interest rate, finance cost)
- equity.shares (dilution, QIP, warrants, buyback), equity.dividend
- working_capital.days (receivable, inventory, payable days)
Each claim: node, segment (or "total"), sign (+/-/0), value_low, value_high, unit (inr_cr, pct, bp, units named,
months), base (what the value is measured against, e.g. FY25 revenue), effective_period (e.g. FY26, Q3FY26, "next
24 months"), conditional (true when the claim depends on an event, e.g. "if approval comes"), quote_span (the exact
substring of the statement that carries the number), plus source ids copied from the row (symbol, doc_key, page,
known_at, source table + id). known_at is ALWAYS copied from the source row, never from the model.

Evidence: (read these, they are real)
- Stores: `D:/RealityEngine/tg_build/measure10/cNN/cNN.db` (91 stores, read-only; open with
  `reality_engine.db.readonly.connect_ro` or `sqlite3` URI `mode=ro`). Tables used:
  `transcript_statement` (89,872 rows in 53 stores; 15,937 have non-empty `numbers_json`), `guidance`
  (978 rows in 53 stores; columns metric, target_period, low, high, unit, direction, quote, revision_of).
- Example of the gap you are closing: c17 BHAGERIA `guidance` id 11, metric `other`, quote "the incremental capacity
  is expected to generate Rs. 50-Rs. 75 crores additional annual revenue at present price, once fully operational"
  -> should become revenue.volume (capacity.add), +, 50-75 inr_cr per year, effective when fully operational.
  Same store id 12 "about 20%-22% in the revenue" -> revenue.total, +, 20-22 pct, FY26.
- Model: `hy4-flash-free` on OpenCode Go, free. Its request body and endpoint are in
  `reality_engine/scripts/extract_deck_figures.py` lines ~71 and ~109 (`reasoning_effort: "none"` is REQUIRED; with
  "low" it thinks all its tokens away and returns empty). Use `OPENCODE_GO_API_KEY` (account 1) from the environment;
  never print it. Every call sends a stable `x-opencode-session` from `reality_engine.scripts.go_session.session_id`.
- Run ledger: `reality_engine/scripts/run_ledger.py`; see how `reality_engine/v2/page_reader.py` `_ledger` (line ~606)
  writes one run row, and do the same (skip under pytest).

## Steps (stage 1a only)
1. `reality_engine/research/driver_claims.py`:
   a. Script first: map `guidance` rows whose metric already names a node (revenue_growth, ebitda_margin, capex, ...)
      straight to claims with NO model call; keep a mapping table in code; count what maps.
   b. Model for the rest: guidance rows with metric `other`/unmapped, and `transcript_statement` rows with non-empty
      `numbers_json` that look forward (script filter on cue words + numbers; log the filter's in/out counts). Batch
      up to 10 statements per request, JSON out, strict schema; a bad JSON reply is retried once then logged as error.
   c. Independent check (the model's output is never trusted by itself): a claim is `verified` only if every number
      in value_low/value_high appears in its quote_span AND quote_span is an exact substring of the stored statement
      (allow Indian digit grouping and "Rs."/"crore" variants via a normaliser with tests); else `unverified`; a claim
      whose quote_span is not in the statement is `quarantined`.
   d. Output: a separate SQLite DB `--out <path>` (default `.tmp/t228/claims.db`) with tables `claim`, `read_log`
      (one row per request: start, end, seconds, http status, in/out tokens, error text) and `quota_event`
      (every 429/5xx/timeout with UTC + IST time, in-flight count, response body first 300 chars). Never write a store.
   e. Concurrency: `--start N` in flight (default 30) and `--unleashed`: every 5 min raise by 10 while the error rate
      over the last 5 min is under 2%, no upper cap; on 429 log a quota_event, halve in-flight, keep going; stop only
      after 30 consecutive minutes of failures or when the work is done. Resume: skip items already in read_log.
2. Tests `reality_engine/tests/test_driver_claims.py` (synthetic, no network): guidance mapping, number normaliser,
   verified/unverified/quarantined, known_at copied from source, resume skip, limiter raises/halves.
3. Pilot run (real model, small): stores c09 c11 c17 c61 c88 only, `--start 10`, no `--unleashed`.
4. Report (final answer, under 60 lines): counts per stage (rows in, script-mapped, sent to model, claims by status and
   by node, no_driver share), seconds and tokens per item, every error and quota event, and 40 RANDOM claims
   (seeded, across nodes) each printed as: store, node, sign, low-high unit, period, status, and the full stored
   statement. Do not pick or summarise the sample.

Files:
- New: `reality_engine/research/driver_claims.py`, `reality_engine/tests/test_driver_claims.py`,
  `docs/research/T-228_driver_claims.md` (what it does, the tree, the check, how to run; update it with the pilot's
  numbers). Do not edit any other code file.

Accept:
`python -m pytest -q reality_engine/tests/test_driver_claims.py` passes; `typecheck` clean on the two .py files;
pilot run finished with its report.

## Limits and pitfalls
- Read-only on every store. Writes only inside your worktree (`.tmp/t228/`, code, the doc).
- Do not use any paid model; hy4-flash-free only (it is free on Go). No DeepInfra, no Haiku.
- A number the model computed (e.g. a sum of segment figures) is not in the quote: it must stay unverified.
- Statements about the past ("revenue grew 18% this quarter") are not forward claims: drop as `past` (count them);
  the hard numbers already hold them.
- Do not run the full 91-store or unleashed run in this stage.
- Run pytest per file (memory: one-process suites were reaped at 7.9 GB).

Stop if:
- hy4 returns empty answers for more than 20% of pilot requests: stop, report 5 raw responses.
- More than 10% of pilot claims are quarantined: stop and report examples.
- Any store would be opened for write.

Budget:
Stage 1a: about 2 hours; DeepSeek max effort; pilot is at most ~2,000 model items.
