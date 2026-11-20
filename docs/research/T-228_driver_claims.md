# T-228 stage 1a/1b/2a: driver-tree claims from management text

Built 20 Nov 2026 by a dsh worker for ticket T-228 (Shivam 20 Nov; review Wolf). Stage 1a-fix 21 Nov after
Wolf's first hand read; round 3 after his second (28 right, 4 wrong, 3 doubtful of 35); **round 4** after his
third (23 right, 1 wrong, 1 doubtful of 25). **Stage 2a** (21 Nov) widens the sources past the call transcript:
annual-report MD&A / outlook pages, press releases and exchange announcements, a deterministic announcement
pre-parse, and a `source_kind` on every claim. Stages B (forward estimate), C (management credibility) and the
test that B+C add prediction over the T-210 hard-number panel are not built here.

Code `reality_engine/research/driver_claims.py`, tests
`reality_engine/tests/test_driver_claims.py` (77 tests, synthetic, no network; three real announcement texts
are embedded as fixtures with the doc_key they came from). A statement that ends in no tree node is show, not
data: it is dropped as `no_driver`.

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
still lists "pharmaceuticals" (a "formulations" hit). A store with no transcripts gets a brief with the name
only (stage 2a added no text source to it).

**Script, guidance (no model).** A `guidance` row whose metric names a node maps straight to a claim:
`revenue_growth`->`revenue.total`, `ebitda_margin`->`margin.ebitda`, `capex`->`capex.amount`,
`order_intake`->`revenue.order_book`, `aum_growth`->`revenue.volume` (segment aum), `nim`->`margin.ebitda`
(net_interest_margin), `credit_cost`/`cost_of_production`/`opex_to_nti`->`cost.other`, `interest_cost`->
`debt.cost`. `sign` follows `direction`; `effective_period` is `target_period`; `quote_span`/`statement` are
the row's `quote`; context is empty. A row with no values is `no_value`. Unmapped metrics (`other`,
`project_capital_spent`) go to the model: `project_capital_spent` covers CSR spend and historical capex.

**Script, announcement (stage 2a, no model).** `announcement_claims(item)` reads an announcement paragraph and
fills the three shapes an exchange letter prints in full:

| shape | node | required in the letter | example |
|---|---|---|---|
| order win | `revenue.order_book` | an award verb + `order/contract/LOA/LOI` + a money value + an execution period | "has secured an order worth Rs. 200.02 Crores", "Time period ... is to be executed 25 months approx." |
| capex approval | `capex.amount` | `capex/capital expenditure` + an approval verb + an amount (`from A to B` becomes target B, base A, sign by B-A) | "The Board has approved an increase in capital expenditure from Rs. 176.44 crore to Rs. 238.43 crore" |
| fund raise | `equity.shares` | a raise cue (QIP, rights issue, preferential issue, warrants, equity shares) + an aggregate size + an issue price per share | "aggregating upto Rs. 139.50 crores on preferential basis ... issue price of Rs. 215/- per equity share" |

A "demand order" (GST, customs, penalty, court) is excluded (`_ORDER_BAD`); a completed allotment, conversion
or forfeiture is excluded (`_RAISE_DONE`), because only a proposed or approved raise is forward. The size is
the claim value, the issue price is recorded in `base`. A period is set only when the letter prints one
(`execution_period` for orders, `HORIZON` for capex and raises); an approved capex or QIP whose letter prints
no horizon is kept as a script claim but is `unverified`/`no_period` under the same checks as every other claim.
The order value and its execution period usually sit in different sentences (the opening line and a table row),
so the period falls back to the whole announcement. A fully parsed paragraph leaves the model queue.

**Model, transcript and guidance.** Unmapped guidance rows plus `transcript_statement` rows with non-empty
`numbers_json`, not fragments, passing the forward-cue regex `CUE`. Each statement is sent with the two
statements before it in the same call (`seq` order within `doc_key`) and, when it answers an analyst
(`answer_turn`), with the question from `transcript_question`. The quote is checked against the target
statement only. Up to 10 statements per request to `hy4-flash-free` on OpenCode Go (`reasoning_effort: "none"`
is required). Strict JSON; a bad reply is retried once, then logged as an error.

**Model, documents (stage 2a).** `doc_items(store, doc_types)` reads `doc` + `doc_page` (read-only) for
`annual_report`, `press_release` and `announcement`, with `<store>_ocr.db.ocr_page` as the fallback for a page
whose main text is empty. Each page is cut into paragraph-sized chunks (`split_paragraphs`: real paragraphs on
blank lines, otherwise sentences packed to 700 characters); an announcement or press-release page of 3,000
characters or less is sent whole, because the exchange letter is one item. A paragraph is kept only when it has
a document cue from the brief's list (`DOC_CUE`: expect, target, plan, will, guidance, outlook, order, awarded,
commission, approve, capex, capacity, raise, allot, plus intend/aim/going-forward) **and** a number with a unit
(`DOC_NUMBER`). The transcript `CUE` is deliberately not reused: a results table says "increase/(decrease)" on
every line. Annual-report paragraphs matching `BOILERPLATE` (CSR, BRSR, secretarial audit, risk/governance
lists, related-party boilerplate, director bios) are dropped and counted; the boilerplate drop is not applied
to announcements, where the same words are part of the real letter. An announcement whose **title** is a
filing type rather than an event (`FILING_SKIP`: annual report or AGM notice re-filed, letter of offer,
prospectus, placement document, voting/scrutinizer report, BRSR, creditor list, shareholding pattern) is
skipped whole and counted, because its annual-report content is read once from the `annual_report` doc type.
The context sent with a document paragraph is the document title and the previous paragraph. Item ids carry
`(doc_key, page, paragraph index)` and the source table is `doc_page`.

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

Stage 2a announcement claims go through exactly the same checks. An order win carries its printed execution
period, so it verifies; a board-approved capex or fund raise whose letter prints no horizon is stored as
`unverified`/`no_period` (never verified without a period), and the quarterly status counts say so.

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
`t228-judge`), batches of up to 5 claims of one store, with the company brief, the claim's own context and its
`SOURCE` (transcript, guidance, annual_report, press_release, announcement). Six booleans: `node_ok`,
`sign_ok`, `unit_ok`, `period_ok`, `forward_ok`, `company_ok` (the claim is about this company's own figures,
not the industry, the country, a customer, a supplier or a competitor). `verified` means check 1 passed AND all
six are true.

**Source rule (stage 2a, in both prompts).** An annual report is published months after the fiscal year it
covers: its own-year figures and growth rates ("FY25 revenue grew 20%") are past even on the MD&A or the
directors' report page, and only an explicit later-period outlook is a claim. An announcement of a completed
event (an allotment made, a meeting held) is past; an order won with execution ahead is forward
(`revenue.order_book`, execution period as `effective_period`), and so are a board-approved capex
(`capex.amount`) and a proposed or approved QIP/rights/preferential issue (`equity.shares`).

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

- `claim` — one row per claim plus `source_table`, `source_kind` (transcript, guidance, annual_report,
  press_release, announcement), `paragraph` (the doc_page paragraph index for a document claim, NULL for a
  transcript or guidance claim), `method` (`script`/`model`), `extractor`, `status`, `status_reason`,
  `judge_ok`, the six `judge_*` booleans (`judge_company`), `judge_fail`, `judge_why`, `judge_suggest`,
  `run_id`, `created_at`. An older claims DB is migrated in place with the two additive columns.
- `read_log` — one row per HTTP request: `role` (`extract`/`judge`), start, end, seconds, status, in/out
  tokens, items, claims, outcome counts, item keys finished, in-flight count, error text.
- `quota_event` — every 429 / 5xx / timeout: UTC and IST time, status, in-flight count, body head.

`run` also writes `<out>.build.json` (the builder counters and per-store counts) so the report can name the
items per doc type and the drop reasons without re-reading the stores.

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

# stage 2a: the 7 stage-1 pilot stores plus 5 stores without transcripts (seed 31), documents included
python -m reality_engine.research.driver_claims --stores c09 c11 c17 c61 c88 c19 c42 \
  --pick-no-transcript 5 --pick-seed 31 --start 15 --out .tmp/t228/claims_s2_pilot.db
python -m reality_engine.research.driver_claims --report --out .tmp/t228/claims_s2_pilot.db --seed 61 \
  --baseline D:/RealityEngine/t228/claims_91.db --build-json .tmp/t228/claims_s2_pilot.build.json \
  --report-file .tmp/t228/report_s2a.md
```

`--doc-types` defaults to `annual_report press_release announcement`; give the flag with no value to read no
document pages (a stage-1 run). `--pick-no-transcript N` adds N stores from `stores_without_transcripts()`
(no transcript document and no transcript statement row), seeded by `--pick-seed`. With no `--stores`,
`active_stores()` picks every store that holds at least one statement or guidance row (the rest are skipped).
`--pick N --pick-seed 7` adds N stores with statements chosen by `random.Random(seed).sample` over the sorted
list. The run writes one run-ledger row and skips the ledger under pytest; in this sandbox the ledger is
outside the writable workspace, so it prints `run ledger not written` and continues (`run_ledger ingest-dsh`
records the job).

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

77 pass (`python -m pytest -q reality_engine/tests/test_driver_claims.py`). They cover the guidance map, the
number normaliser, the three statuses, the unit-word rule, the node-unit table, the from-A-to-B target rule
(both the change, percent and the plain-range case), the ambiguous-range sign rule, the period-or-horizon
rule, the mix/share re-tag (pct only, pattern required, segment named) and the list-span rule (8-8
truncated, 8-10 and 20-22 fine), the re-tag migration on an existing DB (mix keeps a status only with the
judge's agreement; truncation downgrades; quarantined untouched), the context attachment and question
lookup (and that context numbers never satisfy the quote), the company brief (text-built, empty-safe), the
judge (six-field parse, tolerant parse, id fallback, measure and node_suggest prompt rules, renode in the
tree, suggestion outside the tree ignored, retry twice then accept, retry twice then `judge_error` with HTTP
codes, `--judge-only` re-queue), dedupe, seeded store picking, resume skip, quota events, the extract batch
with a fake client, and the limiter (raise/halve/stop/limit). Stage 2a adds the paragraph splitter, the
document item builder (forward paragraph kept, boilerplate dropped, page without a cue dropped, OCR fallback,
short announcement sent whole, filing-type title skipped for announcements only, a parsed announcement leaving
the model queue), the three real announcement parses (order win 200.02 crore / 25 months; capex 176.44 ->
238.43 crore plus a 7.16 crore preferential issue on the same page; two preferential issues 139.50 and 34.19
crore at Rs. 215), the negative cases (a completed allotment and a GST demand order are not script claims),
`source_kind` on every producer, the doc claim round trip and the additive-schema migration.

## 11. Stage 2a: document sources and the pilot (21 Nov 2026)

Stage 2a widens the sources so a factor study is not limited to 52 companies with transcripts. Code, tests,
the item builder and a judged (but partial) pilot are done; the extraction could not finish because the
shared hy4 key closed for 2.5 h mid-run (the judge model, on a separate limit, did).

**The 12 pilot stores:** `c09 c11 c17 c61 c88 c19 c42` (stage 1's 7) plus `c01 c21 c23 c60 c78`, the last
five picked without transcripts by `random.Random(31).sample` from the 37 stores that hold no transcript
document and no transcript statement row.

**Item builder, measured on the 12 stores (`--dry-run`, `claims_s2_pilot.build.json`):**

| source | docs | pages read (OCR) | paragraphs | model items | script claims | dropped |
|---|---|---|---|---|---|---|
| annual_report | 41 | 6,856 (254) | 16,854 | 1,590 | 0 | 1,070 paragraphs boilerplate; 11,208 no cue; 2,986 no number; 2,529 pages no cue; 2,470 pages no number; 37 short pages |
| announcement | 1,296 | 4,594 (387) | 7,084 | 1,808 | 13 | 219 documents / 4,817 pages by filing type; 4,026 paragraphs no cue; 1,237 no number; 1,487 pages no cue; 1,597 pages no number |
| press_release | 17 | 59 (0) | 45 | 30 | 0 | 10 paragraphs no cue; 5 no number; 9 pages no cue; 21 pages no number |
| transcript | - | - | 1,116 with numbers | 449 | 0 | 168 fragments, 641 no cue, 5,002 no numbers |
| guidance | - | - | - | 19 unmapped | 27 mapped | 2 no value |

**Total 3,896 model items** (under the brief's 5,000 stop) and **40 script claims** (27 guidance, 11 order
wins in c01, 2 preferential-issue sizes in c11). The filing-type skip is what keeps the count down: the
"announcement" doc type includes 219 filings that are an annual report/AGM notice re-filed, a letter of
offer, a prospectus or a voting/scrutinizer report (4,817 pages); their annual-report content is read once
from the `annual_report` doc type. c88's 342-page "Intimation under Regulation 30" is a prospectus and still
contributes 658 items by itself.

**The extraction that could not finish.** The run started 02:53:09 IST at `--start 15` (no `--unleashed`) and
met **478 HTTP 429 "Rate limit exceeded" in six minutes**; the limiter halved to 1 and stayed there. Only 17
requests succeeded (170 items, 38 model claims). A single-request probe then returned
`Retry-After: 8832` seconds (2 h 27 min): the key was exhausted account-wide by the other hy4 jobs on it, not
by this run's concurrency. The run was stopped at 02:58:56; the remaining 3,726 items were not sent. The same
command in §8 resumes (the 17 finished batches are skipped by `items_done`) and must be retried after 05:30
IST, or at `--start 2` while another hy4 job is running.

**The judge did run.** The judge model (`beam-free`) has a separate limit and was serving: `--judge-only`
judged all 66 script-verified claims in 16 requests (394 s, 0 errors, all HTTP 200). **31 passed (47%)**;
fail fields `period_ok` 24, `node_ok` 15, `forward_ok` 9, `sign_ok` 8, `unit_ok` 2, `company_ok` 2 — the same
`period_ok` dominance as stage 1b, because the judge is not given the claim's own date and reads a stale
FY25 target period as past.

**The judged pilot DB** `.tmp/t228/claims_s2_pilot.db`: **78 claims — 31 verified, 46 unverified,
1 quarantined**. Verified by source: announcement 15 (10 script order wins + 5 model), annual_report 12
(model), guidance 4 (script). Verified by node: `revenue.order_book` 19, `equity.dividend` 5,
`capex.amount` 4, `margin.ebitda` 2, `cost.power_fuel` 1. Script claims after judging: 14 of 40 verified (10
order wins, 2 guidance capex, 2 guidance margin); 23 guidance claims and 2 no-period fund-raise sizes were
rejected, mostly on `period_ok`. Model claims: 17 of 38 verified (12 annual-report, 5 announcement), which is
the first judged evidence that an annual-report paragraph can carry a driver claim
("planned capital expenditure of Rs. 65 crore for FY2027" -> `capex.amount`, verified).

**Coverage gain vs `claims_91.db` (judged claims only):** companies with a verified claim 52 -> pilot 3;
**gained 1** — BLKASHYAP/c01 with 21 verified claims (10 script order wins, 5 model announcement claims,
6 annual-report claims; c01 has no transcripts, so every one is new); **months gained 2** (2024-09,
2026-09); 15 company-months. The 31 random verified claims (seed 61, full paragraphs) are in
`.tmp/t228/report_s2a.md`. Verified is still not truth: the sample keeps a doubtful margin row ("go up by 10%
Q-on-Q ... 10% to 15% next quarter" read as `margin.ebitda +15 pct`), and the 46 unverified rows must not be
used.

**Pitfall for the rerun:** an approved capex or QIP whose letter prints no horizon is `unverified`/`no_period`
by design (2 of the 13 announcement script claims); the order wins verify because the letter prints the
execution period. `Retry-After` is the only reliable signal for a closed key; the 429 body carries no reset
time, and a full extraction needs about 1.5-2 h of a free key.
