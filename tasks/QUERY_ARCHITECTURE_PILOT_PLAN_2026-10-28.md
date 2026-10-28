# Query architecture + pilot plan (2026-10-28, Eagle)

Builds on `tasks/ARCHITECTURE_OVERHAUL_2026-10-27.md`, which holds the store layout, DDL, PIT rules and label rules, and keeps all of it. This document adds four things:
- the **query layer** (how a question becomes an answer);
- the **schema additions** the master bank needs;
- the **pilot design**;
- the **parallel work plan**.

The golden rule order is unchanged: schema → pilot → re-run ≥95% → full chunking. What changes is that the steps run in parallel.

## 1. Query architecture

```
question
  │ 1. parse      entities → ISIN-at-time (resolve; old symbols, BSE codes, names, aliases.csv)
  │               period / as_of → PIT cutoff;  family + entity_level + answer_kind (master-bank fields)
  ▼
  2. route by answer_kind (one planner per shape; a multi-hop question = a chain of planners)
  ├─ LOOKUP     facts(): results_xbrl + metric_series + segment_pnl + ar_facts + deck_figures   (exact number + filing id)
  ├─ SCREEN     market_state: company_state_daily (isin,date) ⋈ membership/sector/theme/mcap intervals AS OF date
  ├─ EVENT      event_day0 (15:30 rule) → price/delivery window [day0-4 … day0+N] → leakage_window flags
  ├─ EVIDENCE   chunks_v3: hybrid (FTS5 + dense) filtered by isin, doc_type, tag, known_at ≤ as_of → passages
  ├─ COMPARE    the same planner run over peer set (peer_graph / sector interval) → table
  └─ RIPPLE     macro_claim_target (policy/commodity → sector/industry) → exposure tables
                (segment_pnl, cost_structure, import_content, order_intake) → company list → EVENT on each
  ▼
  3. assemble   every hop returns rows with provenance (db.table.key or doc_id+page, known_at)
                a hop with no rows → "NOT IN DATA: <what was checked>" (never a guess)
  ▼
  4. answer + evidence list + degradation notes (quarantine, coverage) — AGENTS.md rule 13
```

Rules:
- **The PIT cutoff is applied in SQL at every hop, not afterwards:** `known_at ≤ as_of`, and symbol-at-time from the ISIN history.
- **The router is deterministic, using the master-bank fields.** The LLM only fills slots and writes the final prose. It never invents a hop.
- **Each planner is one function in `reality-data`,** testable on its own. The master bank becomes the regression suite: every case names its planner chain.

## 2. Schema additions, ranked by cases unblocked (from GAP_ROLLUP, then confirmed by the answerability bench)

| Pri | Table / field | Unblocks | Source | Closable |
|---|---|---|---|---|
| 1 | `xbrl_concept_map` (G11) + `company_metric_series` | ~100 | results_xbrl.db | held |
| 2 | `company_state_daily` + `index_membership_interval` + `price_band_daily` | screens, all levels | prices + new index_history + price_bands raw | held (fetched today) |
| 3 | `event_day0` (NG27) + `event_leakage_window` (NG28) | ~47 | announcements/concall known_at + prices | held |
| 4 | `company_segment_pnl` | 41 | ar_facts, deck_figures, XBRL segments | partial |
| 5 | `policy_target` (G10) = `macro_claim_target` | 63 | policy_events, PIB, budgets | partial |
| 6 | `working_capital`, `debt_mix`, `price_revision`, `order_intake`, `capacity_util/capex_project` | 25–55 each | XBRL + AR + concall + announcements | partial |
| 7 | commodity/freight/rainfall series (G12) | 79 | mkt_commodity_daily (13 held) + new fetches | partial |

The bench report (`tasks/answer_bench/REPORT.md`) re-ranks this list with measured blockers.

## 3. Chunking spec v3 (originals only, never `document_chunks` text)

| Doc type | Unit | Header stamped on every chunk |
|---|---|---|
| Concall | speaker turn; Q&A = one question + its answers; cap 900 tokens, split at sentence | isin, symbol_at_time, quarter, call_date, known_at, speaker role (mgmt/analyst), section (opening/QA) |
| Deck | one slide (text + OCR of charts) | isin, period, slide no, known_at |
| Annual report | section-aware (MD&A, segment, notes, related party), cap 1,200 tokens | isin, FY, section, page, known_at |
| Results notes | one note block | isin, quarter, note no, known_at |
| Material announcement | whole doc if ≤1,500 tokens, else by heading | isin, category bucket, known_at (exchdisstime / DissemDT) |
| Macro (RBI/PIB/budget) | by heading/paragraph | issuer, date, claim targets (layer 3) |

Tags: deterministic first (doc type, section, speaker, numbers, guidance verbs). Model tags only after a 300-chunk hand check at ≥0.90 precision (D6).

## 4. Pilot design

- **Pilot universe:** every company named in the master bank (all 5 banks) plus 20 random ones from the universe. Every FY25+ document they have, of every doc type. Questions about those companies are then answerable end to end, so the re-run measures the architecture, not sampling luck.
- **Stores:**
  - `chunks_v3_pilot.db`;
  - `market_state_pilot.db`, built for the full universe, since it is cheap and from held data;
  - pilot `event_day0` and `metric_series`.
- **Re-run:** the full master bank through the router. Grades as in the bench: ANSWERED, PARTIAL, BLOCKED_SCHEMA, BLOCKED_TOOL, NOT_IN_DATA (justified only), WRONG.
- **Gate:**
  - ≥95% ANSWERED, or NOT_IN_DATA with a valid reason;
  - 0 PIT violations;
  - all 30 regressions pass;
  - search p95 < 2 s;
  - tag precision ≥ 0.90.

## 5. Parallel work plan (dsh workers, off-peak; peak Mon–Fri 06:30–09:30 and 11:30–15:30 pauses new starts)

| Stream | Now → next | Output |
|---|---|---|
| A. Raw downloads | running: NSE ×2, BSE concall ×2; next: parallel concall restart, then ARs/announcements via Drive → NSE → BSE | all raw by about 01:00 tonight |
| B. Master bank | worker fixing checks 4c/6c/6e and dedupe | bank for Shivam's approval, about 19:30–20:00 |
| C. Answerability bench | running: 150 cases on today's data | measured blockers, re-ranked §2 |
| D. market_state build | next: from prices + index_history + price_bands | company_state_daily + intervals (pilot DB) |
| E. Metric layer | next: G11 concept map + metric_series + segment_pnl | facts() covers LOOKUP |
| F. Event layer | next: event_day0 + leakage window | EVENT planner |
| G. Chunker v3 | next: concall + deck chunker on the pilot universe, then AR / notes / announcements | chunks_v3_pilot.db |
| H. Router + re-run harness | after B, C: planner functions + a runner that grades the whole bank | the ≥95% gate number |

D, E, F and G start as soon as B and C report, tonight, off-peak.

## 6. Timeline (honest)

| Milestone | Target |
|---|---|
| Raw data in scope downloaded | Wed 28 Oct, about 01:00 (night) |
| Master bank ready for approval | Wed 28 Oct, about 20:00 |
| Bench numbers | Wed 28 Oct, about 21:00 |
| Pilot stores built (D–G) | Thu 29 Oct evening |
| First full re-run + fixes | Thu night → Fri 30 Oct |
| Gate ≥95% passed → **full chunking starts** | Fri 30 Oct (target), Sat 31 Oct (if a second fix round is needed) |
| Full re-embed | after the full chunking; needs Shivam's OK for DeepInfra spend |

Full chunking can't start the moment the raw data lands tonight, because the golden rule needs the pilot gate first. The plan above keeps that gap to about 1–2 days, not weeks.
