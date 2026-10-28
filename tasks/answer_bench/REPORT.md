# Answerability benchmark — how many master-bank questions we can answer today

Read-only benchmark of `tasks/master_bank/MASTER_BANK.jsonl` (1,030 cases) on a 150-case sample, seed 20261028, answered through the `reality-data` tool functions (same code the MCP server exposes) with at most 8 tool calls per case. No chunking, no DB writes, no network, no paid embeddings.

Generated: 2026-10-28 · sample `SAMPLE.jsonl` · rows `RESULTS.jsonl` (150 cases) · tools `run_bench.py`

## 1. Overall

| grade | cases | share |
|---|---|---|
| ANSWERED | 7 | 4.7% |
| PARTIAL | 88 | 58.7% |
| BLOCKED_SCHEMA | 25 | 16.7% |
| BLOCKED_TOOL | 17 | 11.3% |
| NOT_IN_DATA | 13 | 8.7% |
| WRONG | 0 | 0.0% |
| **total** | 150 | 100% |

- **ANSWERED: 7/150 = 4.7%** of the master bank can be answered end-to-end with provenance today.
- ANSWERED or PARTIAL (at least one hop answered with provenance): 95/150 = 63.33%. That is the real ceiling today: the tools reach part of most questions, the whole question rarely.
- **ANSWERED is post-audit.** The probe produced 20 end-to-end rows; a hand pass (`recheck.py`) read each against its question and downgraded 13 that had answered only part of a multi-part ask (each keeps the missing hop in `blocker`). The 7 that survived are a holding %, a delivered quantity, a YTD high, an index plus dispersion day, a top-losers list and two more point lookups.
- **The 30 regressions (Shivam's questions): 4/30 = 13.3% answered; 19/30 = 63.3% answered or partial.**

## 2. Answered % by family

| family | cases | ANSWERED | % | PARTIAL | %answered+partial |
|---|---|---|---|---|---|
| 1 | 21 | 0 | 0.0% | 5 | 23.8% |
| 2 | 24 | 5 | 20.8% | 14 | 79.2% |
| 3 | 8 | 0 | 0.0% | 5 | 62.5% |
| 4 | 8 | 0 | 0.0% | 4 | 50.0% |
| 5 | 4 | 0 | 0.0% | 1 | 25.0% |
| 6 | 20 | 0 | 0.0% | 16 | 80.0% |
| 7 | 7 | 0 | 0.0% | 5 | 71.4% |
| 8 | 6 | 0 | 0.0% | 3 | 50.0% |
| 9 | 13 | 0 | 0.0% | 10 | 76.9% |
| 11 | 15 | 3 | 20.0% | 6 | 60.0% |
| 12 | 7 | 0 | 0.0% | 3 | 42.9% |
| 13 | 4 | 0 | 0.0% | 4 | 100.0% |
| 14 | 8 | 0 | 0.0% | 6 | 75.0% |
| 15 | 6 | 2 | 33.3% | 4 | 100.0% |
| 16 | 17 | 0 | 0.0% | 12 | 70.6% |
| 17 | 6 | 0 | 0.0% | 2 | 33.3% |
| 18 | 7 | 0 | 0.0% | 4 | 57.1% |
| 19 | 8 | 0 | 0.0% | 3 | 37.5% |
| 20 | 5 | 0 | 0.0% | 2 | 40.0% |
| None | 17 | 0 | 0.0% | 16 | 94.1% |

Family tags are a list per case, so a case counts under each of its tags.

## 3. Answered % by entity level

| entity level | cases | ANSWERED | % | PARTIAL | %answered+partial |
|---|---|---|---|---|---|
| index | 5 | 0 | 0.0% | 3 | 60.0% |
| industry | 21 | 0 | 0.0% | 13 | 61.9% |
| macro | 6 | 0 | 0.0% | 0 | 0.0% |
| market-cap bucket | 6 | 0 | 0.0% | 4 | 66.7% |
| market-wide | 12 | 2 | 16.7% | 8 | 83.3% |
| policy | 9 | 0 | 0.0% | 8 | 88.9% |
| price band | 1 | 0 | 0.0% | 1 | 100.0% |
| sector | 5 | 0 | 0.0% | 2 | 40.0% |
| stock | 78 | 5 | 6.4% | 45 | 64.1% |
| theme | 7 | 0 | 0.0% | 4 | 57.1% |

## 4. Answered % by source bank

| bank | cases | ANSWERED | % | PARTIAL | %answered+partial |
|---|---|---|---|---|---|
| open300 | 38 | 2 | 5.3% | 24 | 68.4% |
| reddit200 | 30 | 0 | 0.0% | 23 | 76.7% |
| ripple200 | 23 | 0 | 0.0% | 10 | 43.5% |
| shivam30 | 30 | 4 | 13.3% | 15 | 63.3% |
| variations300 | 29 | 1 | 3.4% | 16 | 58.6% |

## 5. Blocker frequency

One blocker per non-answered case: the probe's own gap when the failing hop named one, else the roll-up's gap for that case id.

| gap id | what it is | cases | grades | closable from held data |
|---|---|---|---|---|
| G11 | XBRL concept map per taxonomy (Ind AS / banking / NBFC / insurance) +  | 28 | BLOCKED_SCHEMA:7, PARTIAL:21 | yes |
| G6 | layer-1 v3 chunk tags (`known_at`, `section`, `speaker_role`, `content | 20 | BLOCKED_TOOL:12, PARTIAL:8 | partial |
| NG16 | no consensus or target-price store | 18 | NOT_IN_DATA:10, PARTIAL:8 | no |
| G10 | macro claim targets | 14 | BLOCKED_SCHEMA:2, PARTIAL:12 | partial |
| G12 | dated macro/commodity series (crude, coal, tariff, FX, El Niño) with e | 14 | BLOCKED_SCHEMA:9, PARTIAL:5 | no |
| NG13 | no operating-metrics series (stores, orders, volumes, LTV) | 10 | BLOCKED_SCHEMA:6, NOT_IN_DATA:1, PARTIAL:3 | partial |
| G3 | F&O history | 9 | BLOCKED_SCHEMA:1, PARTIAL:8 | no |
| U-OTHER | unclassified coverage gap | 5 | BLOCKED_TOOL:1, NOT_IN_DATA:1, PARTIAL:3 | no |
| metric_series | quarterly_financials holds 15,173 rows against 45,517 FY25+ XBRL filin | 5 | NOT_IN_DATA:1, PARTIAL:4 | partial |
| G8 | price band 2022-02-19→2026-09-14 | 3 | PARTIAL:3 | no |
| U-STORE | the entity has no rows in the store the template needs | 3 | PARTIAL:3 | no |
| segment_pnl | Segment contexts in XBRL are unmapped, which is why a segment number c | 3 | BLOCKED_TOOL:1, PARTIAL:2 | partial |
| G1 | shares outstanding + daily market cap | 2 | PARTIAL:2 | partial |
| NG02 | audit opinion detail (type / EOM / going-concern / KAM) is not extract | 2 | PARTIAL:2 | partial |
| G9 | results-notes backfill | 1 | BLOCKED_TOOL:1 | no |
| G0 | ISIN anchor is defective (83 false changes, 1,370 synthetic ISINs, 1,6 | 1 | PARTIAL:1 | yes |
| NG18 | no sector-level FII/DII flow split | 1 | PARTIAL:1 | partial |
| screen_join | Screen over a peer/universe table | 1 | PARTIAL:1 | partial |
| price_revision | A price hike is announced in several calls in several words; without t | 1 | BLOCKED_TOOL:1 | partial |
| pass_through | The measured lag: regress the margin trough on the input shock across  | 1 | PARTIAL:1 | partial |
| working_capital | The XBRL facts exist and are unmapped; annual_financials holds only OC | 1 | BLOCKED_TOOL:1 | partial |

## 6. Top 15 schema additions, ranked by cases unblocked

`cases` = sample cases whose answer depends on it; `effort d` from the roll-up where it exists, blank for the tool-layer proposals.

| # | gap / addition | what | cases | closable | path | effort d |
|---|---|---|---|---|---|---|
| 1 | G11 | XBRL concept map per taxonomy (Ind AS / banking / NBFC / ins | 28 | yes | build from held data | 1.0 |
| 2 | G6 | layer-1 v3 chunk tags (`known_at`, `section`, `speaker_role` | 20 | partial | new fetch | 8.0 |
| 3 | NG16 | no consensus or target-price store | 18 | no | new fetch |  |
| 4 | G10 | macro claim targets | 14 | partial | build from held data | 5.0 |
| 5 | G12 | dated macro/commodity series (crude, coal, tariff, FX, El Ni | 14 | no | new fetch | 13.0 |
| 6 | NG13 | no operating-metrics series (stores, orders, volumes, LTV) | 10 | partial | build from held data |  |
| 7 | G3 | F&O history | 9 | no | new fetch | 1.0 |
| 8 | metric_series | quarterly_financials holds 15,173 rows against 45,517 FY25+  | 5 | partial | build from held data | 2.0 |
| 9 | U-OTHER | unclassified coverage gap | 5 | no | new fetch |  |
| 10 | G8 | price band 2022-02-19→2026-09-14 | 3 | no | new fetch | 0.5 |
| 11 | segment_pnl | Segment contexts in XBRL are unmapped, which is why a segmen | 3 | partial | build from held data | 2.5 |
| 12 | U-STORE | the entity has no rows in the store the template needs | 3 | no | new fetch |  |
| 13 | G1 | shares outstanding + daily market cap | 2 | partial | build from held data | 3.0 |
| 14 | NG02 | audit opinion detail (type / EOM / going-concern / KAM) is n | 2 | partial | build from held data |  |
| 15 | G0 | ISIN anchor is defective (83 false changes, 1,370 synthetic  | 1 | yes | build from held data | 2.0 |

## 6b. Tool-layer additions, measured in this run

These are not missing tables. The data is held; the tool cannot serve it inside the 15 s statement guard or has no parameter for it. They are the BLOCKED_TOOL side of the same work.

| tool | call shape | cases | max s | what to add |
|---|---|---|---|---|
| facts | period-filtered fact lookups | 3 | 15.5 | index (symbol, kind, period) or a per-company fact sheet; `guidance` WITH a period times out, without one it returns in ~1.9 s |
| doc_find / transcript passage | lexical search inside held documents | 14 | 3.7 | 14 cases: the document is in the store but no passage carries the ask - lexical search has no paraphrase recall without the dense index |
| facts / docs / doc_find | no as_of argument | 76 |  | add a known_at/as_of bound to every document and fact lookup; these PIT-shaped cases cannot be enforced today |

## 7. Point-in-time findings

- Hard violations (evidence dated **after** the case's `as_of`): **1**.
  - `MB0026` as_of 2026-10-19: page evidence 2026-10-24 > as_of 2026-10-19
- Exposure without a violation: **76** cases used `facts`/`docs`/`doc_find`, which have **no `as_of` parameter at all**, on a PIT-shaped question. The tool cannot enforce point-in-time; the probe filtered by returning dates only.
- Tool surface behind that exposure: `facts` 116, `doc_find` 77, `docs` 50

## 8. Slow tools

Per-call wall clock (the read-only connection kills any single statement at 15 s, so a 15 s row is a **timeout**, not a slow success).

Calls over 20 s (BLOCKED_TOOL by the brief's rule): **0**.

| tool | args shape | calls | max s | mean s |
|---|---|---|---|---|
| facts | ASIANPAINT | 4 | 15.52 | 4.14 |
| facts | LUMAXTECH | 1 | 15.45 | 15.45 |
| facts | DPABHUSHAN | 2 | 15.24 | 7.74 |
| search_docs | gold Jun Jul | 1 | 4.41 | 4.41 |
| search_docs | export demand two markets | 1 | 4.22 | 4.22 |
| docs | ADANIENT | 1 | 4.07 | 4.07 |
| doc_find | MOTHERSON | 2 | 3.70 | 2.25 |
| doc_find | COALINDIA | 1 | 3.59 | 3.59 |
| doc_find | INFY | 3 | 3.48 | 1.54 |
| doc_find | TITAN | 1 | 3.25 | 3.25 |
| doc_find | RELIANCE | 3 | 3.14 | 1.55 |
| doc_find | NYKAA | 1 | 2.96 | 2.96 |
| doc_find | MUTHOOTFIN | 2 | 2.92 | 1.71 |
| doc_find | LICHSGFIN | 1 | 2.91 | 2.91 |
| doc_find | HDFCBANK | 2 | 2.86 | 1.67 |
| doc_find | POLYCAB | 1 | 2.41 | 2.41 |
| doc_find | TCS | 2 | 2.34 | 1.33 |
| doc_find | MPHASIS | 1 | 2.25 | 2.25 |
| doc_find | RVNL | 1 | 2.01 | 2.01 |
| doc_find | ASIANPAINT | 7 | 2.00 | 0.73 |

Calls killed at the 15 s statement guard: `facts` x3

## 9. Method and caveats

- Sampling: 30 regressions + 30 `reddit200` + 90 stratified over (rarest family tag x entity level). Every family tag appears at least 3 times; every entity level at least 5 times except `price band`, which has exactly 1 case in the whole bank (so 5 is impossible for it).
- A case is probed hop by hop: the hops come from the case's own `rubric.required_evidence`, else from its family. Each hop executes a real tool call (<=8 per case). ANSWERED = every hop returned the answering evidence and the answer was checked against `ground_truth` where the bank has one (23 cases).
- PARTIAL = at least one hop answered and at least one failed; the failed hop is named in `blocker`. A list/ranking ask is never ANSWERED on one entity's evidence.
- BLOCKED_SCHEMA = the held store has no table/field for the hop; BLOCKED_TOOL = the store has it but the tool cannot reach it in time or has no parameter for it; NOT_IN_DATA = nothing held; WRONG = the measured value contradicts the rubric ground truth.
- The probe's own measured gap beats the roll-up prior: when a hop failed for a reason the roll-up does not name, the new name is used (see `PROPOSALS` in `rollup.py`).
- No case was graded WRONG: the numeric ground truths were matched (3) or left unverified (12) because the probe answered a different window/metric. The first pass used a looser numeric rule and produced 13 false WRONG rows (e.g. a state of the rupee mentioning one date versus a ground truth about another date); the rule now needs the same date and the same named subject before it calls a value contradictory. A data defect that is visible without a reference answer is in section 10.
- Calibration: the same 150 cases and the same held data were run five times while the evidence gate was tightened, and ANSWERED fell 47 -> 36 -> 26 -> 22 -> 20. The high numbers came from accepting any fact/passage the store returned for the symbol (hand checks found values that did not answer the ask, e.g. total income for a net-NPA question, an unrelated RBI event for a repo-hike question); the final rule requires the retrieved evidence to carry the asked metric/term as that word. **20 is the number to quote; treat anything above it as contaminated by lexical false positives.**
- ANSWERED means the tool returned the answering fact/passage; matching is lexical, so a passage that mentions the ask's terms in unrelated prose can still slip through. Those are the false-positive risk in the ANSWERED number, and the reason `passage_precision` is in the table.
- Total tool calls in the benchmark: **514**, mean 3.4/case, max 8/case; total measured tool time 273 s.

## 10. Where the roll-up prior disagrees with what this run measured

Section 5/6 label cases with the roll-up's gap id, which was written before this run. The probes found four of those labels wrong or too coarse:

- **G12 is not a new fetch.** The live `mkt_commodity_daily` holds **25,255 rows of 13 series (usdinr, copper, crude_brent, crude_wti, gold, silver, aluminium, zinc, coal_newcastle, steel_hrc_us, iron_ore_62, natural_gas, platinum), 2019-01-01..2026-10-06**, and 8 sampled cases answered the copper/crude/usdinr hop from it. The blocker is that the dated DuckDB snapshot (`truth_2026-10-19.duckdb`) has no commodity/currency table at all, so a PIT-stamped series is missing: closable = partial (copy the held series, stamp known_at), not `new fetch`.
- **NG05 (shareholding stub) is stale.** `truth.shp_index` holds **50,838 rows to 2026-10-16** and `holding()` answered promoter/public for 7 sampled stocks (quarter 2026-09-30 included). The 40-row `equity_intelligence.shareholding` table is a different, unused table.
- **The `mkt_*` tables are live-only.** `mkt_nse_index_daily` (206,437 rows to 2026-10-23) and `mkt_fii_dii_cash` (1,935 rows) answer questions, but they are not in the snapshot and carry no `known_at`; the 14 G12 cases and the flow cases that still fail fail on the mapping/derivation, not on the raw series.
- **`facts(symbol, kind='guidance', period=...)` is a hard timeout** (15 s, 3/3 attempts; the same call without a period returns in 1.9 s) and **`search_docs` peaked at 4.4 s** on a market-wide FTS query. Those are the 14 BLOCKED_TOOL cases, and both are fixable in the tool layer, not the schema.

Two further measurement notes: `doc_page` returned a document dated after the case's `as_of` (MB0026), which is a real PIT leak; and 81 cases used `facts`/`docs`/`doc_find` on a PIT-shaped question although those tools have no `as_of` argument, so point-in-time can only be reconstructed, never enforced.

