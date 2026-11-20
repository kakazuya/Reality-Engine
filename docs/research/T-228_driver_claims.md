# T-228 stage 1a/1b: driver-tree claims from management text

Built 20 Nov 2026 by a dsh worker for ticket T-228 (Shivam 20 Nov; review Wolf). Stage 1a-fix 21 Nov after
Wolf's first hand read; round 3 after his second (28 right, 4 wrong, 3 doubtful of 35); **round 4** after his
third (23 right, 1 wrong, 1 doubtful of 25). Stages B (forward estimate), C (management credibility) and the
test that B+C add prediction over the T-210 hard-number panel are not built here.

Code `reality_engine/research/driver_claims.py`, tests
`reality_engine/tests/test_driver_claims.py` (52 tests, synthetic, no network). A statement that ends in no
tree node is show, not data: it is dropped as `no_driver`.

## 1. The driver tree (fixed vocabulary)

| group | nodes |
|---|---|
| revenue | `revenue.volume` (units, tonnes, MW, orders executed, capacity x utilisation), `revenue.price` (realisation, ASP), `revenue.total` (revenue or growth % when volume and price are not split), `revenue.order_book` (order book, inflow, execution period), `revenue.mix` (share or contribution of a segment, product or geography, with the segment named) |
| operating cost | `cost.raw_material`, `cost.employee`, `cost.power_fuel`, `cost.other`, `margin.ebitda` (margin % or bp change), `margin.gross` |
| capex | `capex.amount`, `capacity.add` (new capacity, commissioning date, utilisation path) |
| debt | `debt.level` (borrowings, net debt, repayment), `debt.cost` (interest rate, finance cost) |
| equity | `equity.shares` (dilution, QIP, warrants, buyback), `equity.dividend` |
| working capital | `working_capital.days` (receivable, inventory, payable days) |

One claim row: `node`, `segment`, `sign` (+/-/0), `value_low`, `value_high`, `unit`, `base`,
`effective_period`, `conditional`, `quote_span`, `statement`, `context`, and the source ids copied from the
row (`symbol`, `doc_key`, `page`, `known_at`, `source_table` + `source_id`). `known_at` is copied from the
source row and never invented.

## 2. Producers and the company brief

**Company brief (script-built).** `company_brief(store)` counts a fixed vocabulary (`RAW_MATERIALS`,
`PRODUCTS`, `SECTORS`) over the store's own guidance quotes, transcript statements and KPI labels, and writes
one paragraph: name, inferred sector (only when it scores 5+ hits and 1.5x the runner-up), what it sells and
what it buys or uses, with the rule that an input price is a cost node and the company's own output price is
revenue. Injected once into the extraction prompt and once per judge request. It is a hint, not a fact; c61
still lists "pharmaceuticals" (a "formulations" hit).

**Script (no model).** A `guidance` row whose metric names a node maps straight to a claim:
`revenue_growth`->`revenue.total`, `ebitda_margin`->`margin.ebitda`, `capex`->`capex.amount`,
`order_intake`->`revenue.order_book`, `aum_growth`->`revenue.volume` (segment aum), `nim`->`margin.ebitda`
(net_interest_margin), `credit_cost`/`cost_of_production`/`opex_to_nti`->`cost.other`, `interest_cost`->
`debt.cost`. `sign` follows `direction`; `effective_period` is `target_period`; `quote_span`/`statement` are
the row's `quote`; context is empty. A row with no values is `no_value`. Unmapped metrics (`other`,
`project_capital_spent`) go to the model: `project_capital_spent` covers CSR spend and historical capex.

**Model.** Unmapped guidance rows plus `transcript_statement` rows with non-empty `numbers_json`, not
fragments, passing the forward-cue regex `CUE`. Each statement is sent with the two statements before it in
the same call (`seq` order within `doc_key`) and, when it answers an analyst (`answer_turn`), with the
question from `transcript_question`. The quote is checked against the target statement only. Up to 10
statements per request to `hy4-flash-free` on OpenCode Go (`reasoning_effort: "none"` is required). Strict
JSON; a bad reply is retried once, then logged as an error.

## 3. Check 1, script (deterministic)

1. `quote_span` empty or not a substring of the target statement (whitespace-normalised) -> **quarantined**.
2. Every value must be a printed number inside the span, else **unverified**.
3. The unit word in the span must agree with the unit (`UNIT_CUES`), else **unverified** (`unit_mismatch`).
4. The node must accept the unit (`NODE_UNITS`), else **unverified** (`unit_not_for_node`): `capacity.add`
   is a size (pct, mw, tonnes, mt, units, named), never days/months/years; `working_capital.days` is days; a
   margin is pct/bp; `capex.amount`/`debt.level` are money; `debt.cost` is pct/bp or a finance-cost amount;
   `revenue.volume` is a physical quantity or pct; `revenue.order_book` may be months.
5. A range stated as "plus or minus", "+/-" or "±" forces `sign` to `0`.
6. **From A to B (round 4).** "from A to B", or "A to B" with a change verb (reduce, come down, increase,
   rise, expand, target, reach...), is a target: `value_low = value_high = B`, `base = A`, `sign` from B vs
   A. A plain range with no from/verb ("INR 2,700 to 2,800 crores") stays a range. Enforced in
   `from_to_target`, called at the head of `verify_claim`; tested both ways. Percent works too ("from 18%
   to 20%" -> target 20).
7. **Mix and share (round 5, tightened round 6).** A pct claim whose span or statement carries "% of
   (total|revenue|income|sales|turnover)", "contribut...", "share of" or "mix" moves to `revenue.mix`, with
   the segment set from the text when the statement names one (exports, domestic, a product). It does NOT
   move when the clause(s) the span touches name a margin (margin/EBIT/EBITDA/PAT/gross) or a change word
   (better, growth, grow, increase, higher, up), unless that clause itself says "% of..." or "share of":
   c73 "product mix and EBIT margin of 30%-35%" and c82 "contribute upwards of 25% ... EBITDA margins" are
   margins, c62 "H2 ... 25% better" is growth. Enforced in `mix_should_fire` / `number_clause` (every clause
   the span touches, so a long span cannot hide a change clause).
8. **A list read as one value (round 5).** When the span lists two or more numbers of the claim's unit
   joined by "," / "to" / "-" / "or" (also "and"), `value_low`/`value_high` must span them; else
   **unverified** (`range_truncated`). "8%, 10% increase" cannot be 8-8. Skipped when the from-A-to-B rule
   already rewrote the claim.
9. A claim needs an `effective_period` or a forward horizon in its own quote, else `no_period`.

The number normaliser strips Indian/western digit grouping, reads `INR40` and `1.25x`, and strips period
labels (`FY26`, `Q2FY26`, `H1FY26`, `9MFY26`, `CY2024`) before reading. A `pct` claim written 0.2 for 20%
matches.

**Sign rule.** An absolute level or range the company expects (revenue of Rs. 1,900 crore, utilisation of
60%-65%, margins around 30%) is `sign 0` and is right; `+`/`-` is only a stated change. Both prompts and the
judge say so.

**Measure follows the question (round 4).** When the context or the analyst's question names the measure
(gross margin, EBITDA margin, utilisation, realisation), the node follows it: gross margin -> margin.gross,
EBITDA margin -> margin.ebitda, utilisation -> revenue.volume. In both prompts.

## 4. Check 2, independent judge (`beam-free`)

Every claim that passed check 1 is read again by `beam-free` on the same endpoint (free, stable session id
`t228-judge`), batches of up to 5 claims of one store, with the company brief and the same context. Six
booleans: `node_ok`, `sign_ok`, `unit_ok`, `period_ok`, `forward_ok`, `company_ok` (the claim is about this
company's own figures, not the industry, the country, a customer, a supplier or a competitor). `verified`
means check 1 passed AND all six are true.

**`node_suggest` (round 4).** The judge also returns `node_suggest`: the tree node the claim really belongs
to when `node_ok` is false, else null. When the number check passed and the suggestion is a tree node, the
claim is stored under the suggested node as **unverified** with `status_reason='judge_renode'` (never
verified), so a right number on a wrong node is kept for review instead of lost (e.g. c19 "60%-65%
utilisation"). The suggestion is stored in `judge_suggest`; an invalid or unchanged suggestion is ignored and
the claim keeps `judge:node_ok`.

**Judge robustness.** Up to 3 attempts (two retries) with 2 s / 4 s backoff; 429s log a quota event and halve
in-flight. A reply whose JSON is broken is first read item by item (id, six booleans, node_suggest) and then
retried. Block ids 1..n fall back to block position. `max_tokens` is 16000: with 3000, beam spent the budget
on reasoning and returned empty content on 41 of 79 requests (round 3 first pass), which is why the judge
body is the model's own 16000.

`verified` is still not truth: the judge is a second model. In the stage-1b sample it still admits some
doubtful calls (captive 40 MW solar as `capacity.add`; a c61 "pharmaceuticals" brief line) and loses some
right ones (utilisation guidance on `revenue.volume` was rejected by `node_ok` in round 3; round 4's
`node_suggest` now re-homes such claims instead of dropping them).

## 5. Dedupe

After judging, claims are deduplicated by `(symbol, normalised quote_span, node)`: survivor order is
judge-agreed, verified, script over model, lowest id. The same quote can arrive both as a `guidance` row and
as a transcript statement; the evidence rows differ, the claim is one.

## 6. Output

`--out` (default `.tmp/t228/claims.db`), three tables:

- `claim` — one row per claim plus `method` (`script`/`model`), `extractor`, `status`, `status_reason`,
  `judge_ok`, the six `judge_*` booleans (`judge_company`), `judge_fail`, `judge_why`, `judge_suggest`,
  `run_id`, `created_at`.
- `read_log` — one row per HTTP request: `role` (`extract`/`judge`), start, end, seconds, status, in/out
  tokens, items, claims, outcome counts, item keys finished, in-flight count, error text.
- `quota_event` — every 429 / 5xx / timeout: UTC and IST time, status, in-flight count, body head.

Resume: extraction items whose keys are in a successful request's `items_done` are skipped; failed batches
are retried. The judge picks up every script-verified claim with `judge_ok IS NULL`; `--judge-only`
re-queues `judge_error` claims and re-runs just the judge. No store is ever opened for write (`connect_ro`,
`mode=ro`); both models are free.

## 7. Concurrency

`--start N` (default 30) extraction requests in flight, `--judge-start N` (default 5) judge requests.
`--unleashed`: every 5 minutes the extraction limit rises by 10 while the error rate over the last 5
minutes is under 2%, no upper cap; a 429 logs a quota event, halves the limit (floor 1) and the request is
retried after 5 s; the run stops only after 30 consecutive minutes of failures or when the work is done.
Stage 1a also stops extraction when more than 20% of answers are empty.

## 8. How to run

```bash
python -m reality_engine.research.driver_claims --stores c09 c11 c17 c61 c88 c19 c42 --dry-run
python -m reality_engine.research.driver_claims --unleashed --start 30 --out .tmp/t228/claims_91.db
python -m reality_engine.research.driver_claims --judge-only --stores ...
python -m reality_engine.research.driver_claims --report --seed 53 --report-file .tmp/t228/report_1b.md
python -m pytest -q reality_engine/tests/test_driver_claims.py
```

With no `--stores`, `active_stores()` picks every store that holds at least one statement or guidance row
(the rest are skipped). `--pick N --pick-seed 7` adds N stores with statements chosen by
`random.Random(seed).sample` over the sorted list. The run writes one run-ledger row and skips the ledger
under pytest; in this sandbox the ledger is outside the writable workspace, so it prints `run ledger not
written` and continues (`run_ledger ingest-dsh` records the job).

## 9. Stage 1b run (21 Nov 2026, all active stores, `--unleashed --start 30`)

Another hy4 job (page reader) was running in ~200 requests in flight on the same Go key throughout.

| stage | count |
|---|---|
| stores | 57 active of 91 (34 hold no statements or guidance) |
| guidance rows | 1,090: 778 script claims, 161 unmapped -> model, 39 no value |
| `transcript_statement` rows | 89,872: 15,937 with numbers, 2,347 fragments, 9,069 no cue, 71,901 no numbers -> 6,555 sent |
| model items | 6,716 planned (6,555 statements + 161 guidance), 6,636 completed in 697 batches |
| extraction | 978 HTTP attempts: 689 x 200, **289 x 429**; 337,358 s summed request time; 1,845,925 in / 323,912 out tokens; 8 batches lost (80 items) after 4 tries, 0 empty |
| quota events | 289 (all HTTP 429 "rate limit exceeded", IST 00:38-00:4x), in-flight 1-30; **peak in-flight 30**; the competing job kept the error rate above 2%, so `--unleashed` never raised the limit and every 429 halved it |
| claims before judge | 4,354: 2,459 passed check 1, 1,885 unverified, 10 quarantined |
| judge | 514 requests, 20,632 s, 865,609 in / 2,852,270 out; 2,459 judged, 1,249 passed, **0 errors**, all HTTP 200 |
| judge agreement | 54% (1,198 of 2,233 judged rows after dedupe); fail fields: `period_ok` 494, `node_ok` 494, `sign_ok` 338, `unit_ok` 100, `company_ok` 53, `forward_ok` 103 |
| judge-renoded | 85 claims kept under their suggested node (unverified) |
| claims after judge + dedupe | **4,070: 1,198 verified, 2,862 unverified, 10 quarantined**; 284 deduped |
| claims by node | revenue.total 1,364, margin.ebitda 772, revenue.volume 653, capex.amount 525, revenue.order_book 206, capacity.add 201, cost.other 158, debt.level 131, working_capital.days 70, revenue.price 63, cost.power_fuel 58, equity.shares 46, debt.cost 35, cost.raw_material 35, margin.gross 26, equity.dividend 5, cost.employee 6 |
| item outcomes | 3,128 items with claims, 1,066 `no_driver`, 2,442 `past`, 73 `no_value` (52.9% dropped) |

Full detail: `.tmp/t228/report_1b.md` (counts, per-store table, all 289 quota events with IST time, in-flight
and code, peak in-flight, 40 random verified claims seed 53 with statement and context, 10 judge-rejected,
15 judge-renoded). Stage 1b is the round-4 code; the earlier 7-store run `.tmp/t228/claims.db` predates the
round-4 rules and is history only.

**Round-4 fixes, checked against Wolf's examples:** #195 "short-term debt from INR450 crores to INR100
crores" is now target 100 with base INR450 and sign `-`, not a 100-450 range (tested); the measure naming
rule is in both prompts and the judge; #23 "margins to go up by at least 10%" with a gross-margin question is
handled by the prompt/judge rule; a right number on a wrong node is re-homed (`judge_renode`) rather than
lost.

**Known limits:** the brief is a vocabulary hint (industry terms creep in); `period_ok` is the judge's most
frequent objection (494 claims); the 289 429s cost the run 8 batches and most of its wall time; `verified`
still needs a human read before a study uses it.

**Round-5/6 re-tag of stage 1b (no new extraction calls).** `--retag` on `claims_91.db`: round 5 moved
**153 claims to `revenue.mix`**, flagged **149 `range_truncated`** (148 remain) and **downgraded 47 verified
claims**; round 6's clause rule **restored 40 of those mix moves** (32 in the first pass, 8 more once every
clause a long span touches was read; 8 restored claims went back to verified). Final: **1,159 verified,
2,901 unverified, 10 quarantined**; `revenue.mix` 113 (107 `mix_retag`, 5 `range_truncated`, 1 quarantined),
margin.ebitda 758, revenue.total 1,204, revenue.volume 600, capex.amount 393, capacity.add 191,
revenue.order_book 191, cost.other 152, debt.level 130, working_capital.days 68, revenue.price 60,
cost.power_fuel 56, equity.shares 44, cost.raw_material 38, debt.cost 33, margin.gross 29, cost.employee 6,
equity.dividend 4. The three round-5 false positives (c73 margin, c82 EBITDA margin, c62 "25% better") are
back on margin.ebitda / margin.ebitda / revenue.total. Quarantined claims are left untouched. The final DB is
`D:/RealityEngine/t228/claims_91.db` (copied by Wolf 21 Nov 02:40 IST: 1,159 verified, 2,901 unverified, 10
quarantined), with the run report `D:/RealityEngine/t228/report_1b.md`.

**Quota finding (21 Nov).** hy4-flash-free on OpenCode Go is rate limited, not unlimited: with a page-reader job
at ~250-290 pages/min on the same key, this run met 289 HTTP 429 "Rate limit exceeded" at 00:38-00:45 IST and the
page job met its own 429s from 01:00; both recovered after backing off. Plan hy4 jobs on one key to share about
250 page-sized requests a minute.

**Wolf hand reads.** Round 1: ~7/13 right; round 2: 28/35; round 3: 23/25; stage 1b on unseen stores: 15/20 right,
2 wrong (mix share as growth; list truncated), both fixed by rounds 5-6. Verified means: number printed in the
quote, script unit/sign/period rules pass, and the beam-free judge agrees on node, sign, unit, period, forward and
company scope. It is about 90% right on meaning, not 100%: use it as labelled model-read input.

## 10. Tests

60 pass (`python -m pytest -q reality_engine/tests/test_driver_claims.py`). They cover the guidance map, the
number normaliser, the three statuses, the unit-word rule, the node-unit table, the from-A-to-B target rule
(both the change, percent and the plain-range case), the ambiguous-range sign rule, the period-or-horizon
rule, the mix/share re-tag (pct only, pattern required, segment named) and the list-span rule (8-8
truncated, 8-10 and 20-22 fine), the re-tag migration on an existing DB (mix keeps a status only with the
judge's agreement; truncation downgrades; quarantined untouched), the context attachment and question
lookup (and that context numbers never satisfy the quote), the company brief (text-built, empty-safe), the
judge (six-field parse, tolerant parse, id fallback, measure and node_suggest prompt rules, renode in the
tree, suggestion outside the tree ignored, retry twice then accept, retry twice then `judge_error` with HTTP
codes, `--judge-only` re-queue), dedupe, seeded store picking, resume skip, quota events, the extract batch
with a fake client, and the limiter (raise/halve/stop/limit).
