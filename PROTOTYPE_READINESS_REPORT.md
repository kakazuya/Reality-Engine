# Prototype Readiness Report

**Date:** 2026-08-28
**Scope:** Operational audit of the existing Reality Engine prototype, ahead of any feature expansion.
**Verdict:** The prototype **runs**, but the new top-down funnel is **data-starved** — 3 of its 5 gates are
currently no-ops. The legacy bottom-up path is the only one that operates on real data.

---

## 1. What I ran, and what actually came back

| Check | Command | Result | Verdict |
|---|---|---|---|
| Unit tests | `unittest discover` | **57 tests, OK** in 172s | Pass |
| Checkpoint | `verify-checkpoint` | **200/200** technical + fundamental, date 2026-08-27 | Pass |
| Legacy screen | `screen --universe nifty200 --top 15` | 15 rows, ~1s | Pass |
| **Top-down screen** | `screen --top-down --top 15` | Runs, but **4 survivors of 200**, 3m 55s | **Fails on merit** |
| Causal trace | `trace-causal-chain --node UNION_BUDGET_2026_RAIL_CAPEX --max-hops 3` | 2 nodes, **hop 1 only** | Thin |

### The top-down funnel, stage by stage

```
input                     200
after_industry_ge_4       168   <- industry filter works
after_moat_3_5_stable_exp   4   <- COLLAPSE: only 4 stocks have any moat score
after_policy_ENI_ge_0       4   <- no-op (no policy data; default 0.0 passes >= 0)
after_roic_wacc_gt_0_05     4   <- no-op (no ROIC/WACC data)
after_solvency_secondary    4
output                      4
```

The funnel is **structurally correct**. It is **nutritionally starved**. Only HAL, PIDILITIND,
ASIANPAINT and HAVELLS survive, purely because they are the 4 demo rows hand-seeded during Phase 2.

---

## 1A. Data pipeline audit

Run with `python reality_engine/cli.py audit-data` (add `--net` to probe feeds, `--json` for CI).
Source: `reality_engine/pipeline/data_audit.py`.

**Verdict: the ingestion pipeline is healthy and production-grade for the legacy path. It is NOT the
bottleneck.** The bottleneck is one specific layer, described in section 2.

### Healthy

| Area | Finding |
|---|---|
| Price / delivery | **1,249 sessions**, 2021-10-27 → 2026-08-27, 2,712,383 rows, 3,470 symbols |
| Staleness | **1 day** (latest session 2026-08-27) |
| Session integrity | No thin/partial sessions; recent sessions 2,853–2,872 rows |
| Indicators | **Zero nulls** on the latest session for sma_20, sma_50, sma_200, rsi_14, DSR, DCS |
| Calendar gaps | **1 unexplained gap in 1,249 sessions** (`2022-08-08`); the other 12 "missing weekdays" are NSE holidays |
| Universe | 3,472 companies; Nifty tiers exact (50/100/200/500); **0 null ISIN, 0 duplicate ISIN** |
| Fundamentals | **100% Nifty 200 symbol coverage**; quarterly to 2026-06-30, annual FY21–FY26 |
| Ratio completeness | ROCE, ROE, interest coverage, free cash flow: **0% null** |
| Capital structure | **193/200** symbols have debt+equity in FY26; 197/200 within two fiscal years |
| Feed reachability | NSE archives **HTTP 200**, BSE API **HTTP 200** — ingestion is live |
| On-disk cache | 1,270 bhavcopy files, LanceDB present, 607 inbox files |

Note: `PROGRESS_MADE.md` claims 25 backfilled sessions. The real figure is **1,249**. The docs are badly
out of date relative to the data.

### Defects found

| # | Defect | Impact |
|---|---|---|
| D1 | **6 funnel tables do not exist** in SQLite: `regulatory_political_risks`, `financial_metrics`, `geographic_exposure`, `peer_financial_metrics`, `countries`, `industries` | Top-down funnel cannot evaluate real candidates |
| D2 | `business_model_profiles` is demo-only (4 rows); `moat_evaluations` = 3 rows | Funnel collapses 168 → 4 |
| D3 | **Only 41 of 4,003 corporate documents downloaded** (1.0%) | RAG corpus is 1% of what's indexed |
| D4 | **`chunks_with_industry = 0`** | Industry-scoped hybrid retrieval silently returns nothing |
| D5 | Row-level nulls in Nifty 200 annuals: revenue 13.5%, net profit 14.0%, debt/equity 12.9% | Absolutes patchy though ratios are complete — suggests two upstream sources joined inconsistently |
| D6 | 9.7% of Nifty 200 quarterly rows lack revenue | Degrades the YoY growth factor |
| D7 | Causal graph thin: 3 macro events, 3 ripples, max depth 2, **1 second-order ripple** | Multi-hop transmission untested at scale |
| D8 | `screen --top-down` takes **3m 55s** vs ~1s legacy | Unusable as a daily EOD tool |

### Good news for the P0 backfill

Despite D5, the ROIC > WACC gate **is** supportable. `capital_structure_available = 200`, and 193 of 200
symbols carry debt + equity in the latest fiscal year. The backfill should select the most recent fiscal
year where capital structure is present, falling back at most two years. Only 3 names (HDFCAMC, ICICIGI,
NESTLEIND) need a stale-year fallback.

---

## 2. Root cause: the top-down data layer was only ever built in PostgreSQL

`postgres_schema.sql` (305 lines) is the source of truth for the new funnel. But PostgreSQL was never
provisioned:

- `config.py` contains **no** PostgreSQL settings at all — SQLite paths only.
- `psycopg2` / `pgvector` are **not installed**.
- No `DATABASE_URL` / `PG_DSN` environment variable is set.
- PG access is entirely `os.environ.get(...)` + `try: import psycopg2 / except ImportError: return None`.

So every PG code path silently degrades to SQLite. But the tables the funnel needs **do not exist in
SQLite in usable form**:

| Table the funnel needs | SQLite state |
|---|---|
| `countries` | only `seed_countries_demo` (3 rows) |
| `industries` | only `seed_industries_demo` (12 rows) |
| `business_model_profiles` | only `business_model_profiles_demo` (**4 rows**) |
| `moat_evaluations` | **3 rows** |
| `regulatory_political_risks` | **does not exist** |
| `financial_metrics` (ROIC/WACC) | **does not exist** |
| `geographic_exposure` | **does not exist** |
| `peer_financial_metrics` | **does not exist** |
| `macro_events` | **3 rows** |
| `ripple_effects` | **3 rows** (no multi-hop chains) |
| `insider_trades` | **0 rows** |
| `bulk_block_deals` | **0 rows** |

Meanwhile the *legacy* tables are rich: `daily_price_delivery` 2,712,383 rows, `master_companies` 3,472,
`corporate_documents` 4,003, `quarterly_financials` 1,107, `annual_financials` 918,
`company_forensic_health` 200, `document_chunks` 429, `visual_evidence_artifacts` 100.

**This is the single core finding:** the old architecture is fully fed, the new one is a skeleton.

---

## 3. Secondary defects found

1. **Performance — 3m 55s per top-down screen.** Unacceptable for a daily EOD tool. Caused by
   `_enrich_with_topdown_metrics()` looping `df.iterrows()` and issuing several per-symbol DB lookups.
   The legacy path does the same job in ~1s via vectorized joins.
2. **`screen` defaults to `[LEGACY]`.** The Phase 6 cutover is real but opt-in behind `--top-down`.
   Nothing in the docs says so; `README.md` and `PROGRESS_MADE.md` still describe the bottom-up model.
3. **Docs diverge from code in both directions.** Doc `04` specifies a 0.45/0.35/0.20 weighting with an
   alt-sentiment factor; `PROGRESS_MADE.md` documents 0.45/0.35/0.20 with smart-money; the code uses
   smart-money. `pipeline/`, `agent/`, `search/` are absent from the `PROGRESS_MADE.md` file tree.
4. **Environment is not reproducible.** No `.venv` and no lockfile. Tests only pass on the system
   Python 3.14 at `C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe`; the managed
   3.13.12 interpreter fails all 7 test modules on import (no pandas/PIL/streamlit).
5. **Uncommitted work.** 10 modified files (`cli.py`, `config.py`, `ui/dashboard.py`,
   `composite_screener.py`, `pruning_engine.py`, ingestion clients, pipeline runners) since `0d80b30`.
   The tested state is not fully captured in git.
6. **Smart-money factor is inert.** `insider_trades` and `bulk_block_deals` are empty, so the 20%
   SmartMoney weight contributes nothing but a baseline.

---

## 4. Good news: a full local backfill is feasible

The blockers are *not* credentials or cloud access.

- `moat_scorer.score_from_text()` is a **deterministic keyword heuristic** — explicitly documented as
  "LLM extraction in prod", but it runs locally today with no API key.
- `policy_engine.agg_policy_score()` and `financial_validator.is_financially_valid()` are **pure
  functions** needing no LLM.
- `annual_financials` (918 rows) already carries ROCE/ROE/debt/equity, enough to derive a deterministic
  ROIC and a rule-based WACC.
- `business_model_profiles` can be backfilled from the existing `company_distilled_parameters` (40 rows)
  plus `intelligence_fts` (900 rows) and `corporate_documents` (4,003 rows).

So all 200 Nifty 200 names can be scored **offline, deterministically, today**.

---

## 5. Recommended sequence

### P0 — Make the funnel real (blocking everything else)
1. **Decide the storage question:** provision PostgreSQL, or formally commit to SQLite-only and delete
   the dormant PG path. *Recommendation: SQLite-only for now.* The dataset is small (200 names), PG adds
   an ops burden for zero current benefit, and the 305-line schema is dead weight that confuses readers.
2. **Backfill the funnel tables over SQLite** for all 200 Nifty 200 names: industries → business model
   profiles → moat evaluations → policy ENI → ROIC/WACC. Deterministic, offline, idempotent, logged.
3. **Re-run the funnel** and confirm the stage-by-stage drop is a *screening decision* (e.g. 200 → 90 →
   40 → 25 → 12), not a data-availability artifact.
4. **Vectorize the enrichment loop** to bring the screen back under ~10s.

### P1 — Make it trustworthy
5. Seed the causal DAG with real multi-hop chains (steel duty, budget rail capex) so `trace-causal-chain`
   actually returns 2nd and 3rd order ripples with PN/MN/S.
6. Make top-down the default screen mode; demote legacy to `--legacy`; reconcile the docs with the code.
7. Commit the dirty working tree.

### P2 — Make it reproducible
8. Create `.venv` + pinned lockfile so the test suite passes on a fresh machine.
9. Populate `insider_trades` and `bulk_block_deals` so the SmartMoney factor is live.

---

## 6. Open decisions

| # | Question | Why it blocks |
|---|---|---|
| 1 | Provision PostgreSQL, or commit to SQLite-only? | Determines how every backfill script is written |
| 2 | Accept keyword-heuristic moat/policy scores now, or wait for LLM extraction? | Deterministic scores are fast and offline but shallow; they must be labelled as provisional, not treated as ground truth |
| 3 | Should the funnel's missing gates fail *closed* (exclude unscored names) or *open* (pass them through)? | Currently they fail open, which silently manufactures false confidence |
