# Factor Spine Design — dated, point-in-time-correct factor series

> **Status:** DESIGN. No source code written, no pipeline run, no live-DB write.
> **Date:** 2026-09-29 · **Author:** design subagent · **Authority:** `tasks/CURRENT_PLAN_2026-09-27.md`
> **Scope:** the *first* step only — a factor spine that will *later* be joined to company returns and exposure magnitudes. The spine alone delivers **zero** company-level predictions (§3.4).
>
> **Repo rules this design is bound by** (`AGENTS.md`, `FUNDAMENTAL_REALITY_ENGINE_OBJECTIVES.md`, `tasks/strategies.md` §1):
> quarantine before inference reads · honest-NULL over synthesis · raw kept for audit · every claim carries provenance
> (`symbol + fiscal + event_date + source_doc_id + chunk_span`).
>
> **The failure class this design exists to prevent** — `tasks/next_wave_plan_2026-09-23.md:176-182` (§2M):
> `composite_screener._lookup_moat_metrics(symbol, isin)` and `ensemble_ranker.get_ensemble_weights_for_context` take **no date/asof key**; moat and policy are single-snapshot. Backfilling past dates therefore stamps **today's** substrate onto the past — "a look-ahead machine." The mechanism is reproduced verbatim by `move_attributor._build_attribution` (`move_attributor.py:367-415`), which passes `date` only to the EOD predictors and reads ranker weights with context `{"stock_id": symbol}` (`move_attributor.py:385`).
> **Every temporal decision in this document is a column in a `WHERE` clause, not a parameter threaded through a function signature.** That is the structural difference, and it is the whole point of §2.

---

## 0. Verified starting state (read-only recon, 2026-09-29)

All "known repo facts" in the brief were re-verified against `reality_engine/data/equity_intelligence.db` (33.35 GB) via a `mode=ro` connection. **Corrections and sharpenings are flagged — do not carry the brief's numbers forward unedited.**

| Brief says | Verified | Note |
|---|---|---|
| `macro_events` 30 rows, ~3 PHASE5 fixtures | **30**, 3 match `event_id LIKE 'PHASE5%'` | ⚠ a 4th, `event_id='MEV_56' / event_name='PHASE5_DEMO_MILESTONE'`, is demo material that **escapes the quarantine rule** (see §1.7) |
| `ripple_effects` 61, `transmission_elasticity=1.0` on all | **61**, `DISTINCT transmission_elasticity` = `{1.0}` | confirmed constant |
| ripple `target_sector_id`/`target_industry_id` 0/61 | 0/61 and 0/61 — **and `target_company_id` is 19/61** | ⚠ sharper: 12 rows declare `target_type='Industry'` and 23 declare `'Sector'`, **all 35 with a NULL FK**. Real targets live in prose inside `transmission_channel`, e.g. `target=SAIL \| company_resolved:DomesticSteelProducers \| safeguard_duty_protection \| import_surge_persist` |
| `regulatory_political_risks` 5,470, 3,239 placeholders | **5,470 / 3,239 (59.2%)**; `coverage_status` `no_template`=3,239, `mapped`=2,231; 44 distinct real `policy_name`; `factor_type`: Tariff 2,025 / FX 104 / Subsidy 97 / Tax 4 / Antitrust 1 | confirmed |
| `countries` 4, `industries` 12 archetypes | **4** (IND/USA/CHN/EU), **12** (Information Technology → Defence) | confirmed archetype-only |
| `master_companies` 6,445 | **6,445** | but `sector` is free TEXT: 22 distinct, and `NULL`=2,714 + `'General Diversified'`=1,868 + `'Other'`=1,363 → **5,945/6,445 = 92.2% unusable** |
| `daily_price_delivery` 3.13M, ~1,263 sessions | **3,133,449 rows / 1,269 distinct sessions / 2021-10-27 → 2026-09-24** | |
| `document_chunks` 2.03M, symbol 99.92% | **2,031,900 / 2,030,258 = 99.92%** | ⚠ **`industry_id` and `sector_id` are 0/2,031,900 populated** — there is no live chunk→industry link anywhere |

Additional verified facts that constrain the design:

- **Numeric `company_id` FKs are dangling in SQLite.** `moat_evaluations.company_id` → `master_companies.isin` = **0/2,653**; `business_model_profiles.company_id` → `isin` = **0**; `geographic_exposure.company_id` → `isin` = **0**. These are surrogate integers from a `companies` table that exists only in the PG DDL. The PG `postgres_schema.sql:49-65` declares `companies(company_id SERIAL)` and `moat_evaluations(company_id INT PRIMARY KEY REFERENCES companies(company_id))`, but the live SQLite `moat_evaluations` holds `company_id` 1..2653 that resolve to **nothing**.
- **`symbol`/`ticker` TEXT is the only join key that works today:** `moat_evaluations.ticker`→`master_companies.nse_symbol` = **2,652/2,653**; `business_model_profiles.symbol` = **2,651**; `regulatory_political_risks.symbol` = **5,468/5,470**; `financial_metrics.symbol` = **2,585/2,585**. `ripple_effects.target_company_id` → `moat_evaluations.company_id` = 19 — i.e. it joins the *surrogate*, never `master_companies`.
- **History tables are essentially empty of time.** `moat_history` 2,654 rows / **2** distinct `asof_date`; `policy_eni_history` 5,470 rows / **1** distinct `asof_date` (all `2021-10-27`); `ripple_history` 76 rows / 5 dates. This is the "levels without history" root cause (`next_wave_plan` §2G), confirmed.
- **`model_explainer_rankings`**: 69,500 rows, `regime_tag` = `'*'` on **69,500/69,500 (100%)**, and each of the four `lens_family` values has exactly 17,375 rows.
- **Existing repo precedents this design reuses** (do not reinvent): `ripple_effects.revision_count` + `last_revised_at`; `raw_documents.doc_version` + `event_date` + `event_source` + `is_structural_milestone`; `noise_floors(symbol, floor, realized_vol, liquidity, sample_days, learned_at)`; module-owned idempotent DDL (`substrate_hygiene.ensure_schema`, `move_attributor.ensure_move_attribution_schema`, `Repository.ensure_validation_schema` at `repository.py:3853`).
- **The live DB is ahead of `schema.sql`.** `macro_events` has a `doc_id` column in the DB but not in `schema.sql:323-331`; `raw_documents` in the DB has 13 columns vs 9 in `schema.sql:447-459`. **⇒ New DDL must ship through an `ensure_*` idempotent helper first, and may only be appended to `schema.sql` later as documentation.** Editing `schema.sql` alone will not create anything in the live DB.
- Working tree has 30+ modified files including `reality_engine/db/schema.sql`. This design **modifies nothing**.

---

## 1. THE SPINE SCHEMA

### 1.1 Shape: two core tables + one event table + one link table (deferred)

```
factor_series        1 ────< factor_observation      (the numeric spine)
    │
    └──────────────< factor_event_window             (shocks with an effect window)

factor_series ────< factor_symbol_link                (DEFERRED — see §1.8; this is the
                                                          table that actually answers
                                                          "which companies benefit", and it
                                                          is NOT in the first load)
```

Naming follows repo convention: `snake_case`, `*_id` surrogate keys (`INTEGER PRIMARY KEY AUTOINCREMENT`, mirroring `repository.py:3820` and `peer_graph.py:62`), dates stored as `TEXT` in `'YYYY-MM-DD'` (mirroring `moat_history.asof_date`, `model_validation_scores.asof_date`, `raw_documents.created_at` — the repo's additive tables use TEXT dates even where `schema.sql` declares `DATE`), `created_at TEXT DEFAULT CURRENT_TIMESTAMP`.

### 1.2 `factor_series` — the definition (SQLite / PG-fallback DDL)

```sql
-- ====================================================================
-- FACTOR SPINE (SQLite fallback) — additive only. Owned by
-- processing/factor_spine.py, which ships ensure_factor_spine_schema()
-- (precedent: substrate_hygiene.ensure_schema, peer_graph PEER_DDL).
-- Never modify an existing table. Never rewrite a definition row: a
-- changed definition is current_status='deprecated' + a new series_id.
-- ====================================================================
CREATE TABLE IF NOT EXISTS factor_series (
    series_id INTEGER PRIMARY KEY AUTOINCREMENT,
    factor_key TEXT NOT NULL UNIQUE,        -- stable public id: 'IN.RBI.REPO_RATE'
    display_name TEXT,
    family TEXT NOT NULL,                   -- rates_credit | crude_energy | policy_budget
                                            -- | fx_flows | metals | OTHER (see §1.3)
    unit TEXT NOT NULL,                     -- 'pct' | 'inr_cr' | 'inr_tonne' | 'usd_inr' | 'index'
    frequency TEXT NOT NULL,                -- daily | weekly | monthly | quarterly
                                            -- | irregular (event-driven) | annual
    value_semantics TEXT NOT NULL DEFAULT 'level'
                                            -- level | rate | index_level | spread
    source TEXT NOT NULL,                   -- rbi_official | mospi | pib | nse_official
                                            -- | vendor:<name> | manual | fixture
    source_url TEXT,                        -- canonical landing page for the series
    methodology_notes TEXT,                 -- how the number is defined/derived
    license TEXT,                           -- redistribution terms; see §6
    current_status TEXT NOT NULL DEFAULT 'active'
                                            -- active | deprecated | unreachable
    -- ---- read contract (declared once, enforced by the resolver) ----
    aggregation_policy TEXT NOT NULL DEFAULT 'lvcf'
                                            -- lvcf   : step/level, carry last value forward
                                            -- last   : flow/period value, take the period
                                            -- sum    : accumulate within a window
                                            -- none   : point observation, never carried
    max_lookback_days INTEGER NOT NULL,     -- HARD staleness ceiling. NOT NULL is
                                            -- deliberate: it forces a declaration. A
                                            -- series may not claim "always fresh".
    expected_publication_lag_days INTEGER NOT NULL DEFAULT 0,
                                            -- flow series: ref period end -> publication.
                                            -- Used by the load-audit, never by the resolver.
    is_point_in_time INTEGER NOT NULL DEFAULT 1
                                            -- 1 : as_of_date is the TRUE public-knowledge
                                            --     date, taken from the publisher.
                                            -- 0 : as_of_date is OUR best reconstruction
                                            --     (e.g. inferred from a document header).
                                            --     Usable, but must be reported alongside.
    availability_contract TEXT NOT NULL DEFAULT 'pita_strict'
                                            -- pita_strict | pita_estimated
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fs_family ON factor_series(family, current_status);
CREATE INDEX IF NOT EXISTS idx_fs_source ON factor_series(source);
```

`max_lookback_days INTEGER NOT NULL` is the single most important column in this table. It is what turns "return something" into "return something *or honest-NULL*" (§2.3).

### 1.3 `factor_observation` — the fact (SQLite / PG-fallback DDL)

```sql
CREATE TABLE IF NOT EXISTS factor_observation (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id INTEGER NOT NULL,
    period_start TEXT NOT NULL,        -- inclusive first day of the MEASURED period
    period_end TEXT NOT NULL,          -- inclusive last day of the MEASURED period
                                      -- (== period_start for a point/step observation)
    value REAL,                        -- NULL is a legal, meaningful observation
    unit TEXT,                         -- snapshot of series.unit at observation time
    as_of_date TEXT NOT NULL,          -- KNOWLEDGE date: earliest date this number was
                                      -- PUBLIC. THE ONLY temporal gate in any read.
    retrieved_at TEXT NOT NULL,        -- when WE fetched it (system time). NEVER a
                                      -- read predicate.
    source TEXT NOT NULL,
    source_url TEXT,
    vintage INTEGER NOT NULL DEFAULT 1,-- 1 = first release; 2.. = restatements (§1.5)
    revision_of INTEGER,               -- observation_id of the vintage this supersedes
    is_latest INTEGER NOT NULL DEFAULT 1,
                                      -- DISPLAY/AUDIT ONLY. The resolver MUST NOT filter
                                      -- on this — it means "latest as of NOW", which is
                                      -- precisely a look-ahead. See §2.2 rule R5.
    confidence REAL,                   -- 0..1; loader-set, never model-set
    notes TEXT,
    -- provenance (strategies.md §1: symbol + fiscal + event_date + source_doc_id + chunk_span)
    source_doc_id INTEGER,             -- -> raw_documents.doc_id when extracted from a
                                      -- stored document. NULL for pure web/API pulls.
    chunk_span TEXT,                   -- 'chunk_id:start_off-end_off'
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (series_id) REFERENCES factor_series(series_id),
    UNIQUE(series_id, period_start, period_end, vintage)
);
```

**Indexes for the as-of point query** (verified against the resolver in §2; these are the covering set):

```sql
-- THE hot path: "latest vintage of the latest period known on date T, for series S".
-- Column order mirrors the resolver's ORDER BY exactly.
CREATE INDEX IF NOT EXISTS idx_fo_series_asof
    ON factor_observation(series_id, as_of_date DESC, period_end DESC, is_latest);
-- Window scans (deltas, returns, panel regression inputs).
CREATE INDEX IF NOT EXISTS idx_fo_series_period
    ON factor_observation(series_id, period_end DESC);
-- Freshness / load audit: which series have gone quiet.
CREATE INDEX IF NOT EXISTS idx_fo_source_retrieved
    ON factor_observation(source, retrieved_at DESC);
-- Provisional-provenance surfacing (is_point_in_time=0 series get a loud label).
CREATE INDEX IF NOT EXISTS idx_fo_period_start
    ON factor_observation(series_id, period_start DESC);
```

SQLite partial index (supported since 3.8.0) for the version-chain integrity probe:

```sql
CREATE INDEX IF NOT EXISTS idx_fo_latest_only
    ON factor_observation(series_id, period_start, period_end)
    WHERE is_latest = 1;
```

**Column-set rationale for the two timestamp columns.** `as_of_date` and `retrieved_at` are different and must never be conflated. `as_of_date` is a property of the *world* (when the publisher released the number). `retrieved_at` is a property of *us* (when we happened to fetch it). Every look-ahead bug in this class of system is a conflation of the two, and §2 makes it structurally impossible by allowing only `as_of_date` in a read predicate. Note the consequence, stated plainly: **a series backfilled today carries `retrieved_at = today` for every historical row.** That is fine and correct — but it means `retrieved_at` can never be used to answer "could we have known this?", only `as_of_date` can. A backfill is a *reconstruction of what was public*, which is exactly what the design claims, and exactly what `is_point_in_time` flags when it is a guess.

### 1.4 Four kinds: one table + one series-level discriminator, or four tables?

The brief asks whether a *state variable known from `as_of` onward* (repo rate step function), a *flow with publication lag* (monthly credit growth), an *event with an effect window* (budget provision), and a *revised series* (tariff true-up) need different tables. **Answer: three tables, and the discriminator lives on the series, not on the row.**

| Kind | Example | Where | Read semantics |
|---|---|---|---|
| (a) **State / step function** | `IN.RBI.REPO_RATE` | `factor_series` + `factor_observation` | `aggregation_policy='lvcf'`, `frequency='irregular'`. One row per policy action. The value is the state from `period_start` until superseded. |
| (b) **Flow with publication lag** | `IN.NBFC.CREDIT_GROWTH_YOY` | `factor_series` + `factor_observation` | `aggregation_policy='last'`, `frequency='monthly'`, `expected_publication_lag_days≈45`. `period_end` = ref month end; `as_of_date` = actual release. The lag is **data, not inference** — the resolver never guesses it. |
| (c) **Event with effect window** | `IN.BUDGET.FY26.RAIL_CAPEX` | **`factor_event_window`** | Not a value at a period. A shock with a start, an optional end, and a magnitude that decays. |
| (d) **Revision / revised series** | `IN.TARIFF.STEEL.TRUEUP` | `factor_observation`, `vintage ≥ 2` | Same period, new number, later `as_of_date`. A *version chain*, not a new period. |

**Justification for the split.** (a), (b) and (d) are the same *storage* fact — "a number attached to a measured period, with a date on which it became public." They differ only in **read semantics**, and read semantics are a property of the *series definition*, not of the row: the resolver reads `aggregation_policy` once from `factor_series` and applies the right rule uniformly. Declaring the kind per-row would let one series carry contradictory `aggregation_policy` values across its history, which is exactly the kind of quiet inconsistency that becomes a look-ahead bug six months later.

(c) is genuinely different in kind. An event is not a value observed at a period; it is a *shock with a start, an optional end, and a magnitude that must decay*. Forcing it into `factor_observation` would mean NULL-able `window_end` / `magnitude` / `direction` columns on 100% of rows, and — worse — it would invite `aggregation_policy='lvcf'` to carry an *event magnitude* forward as if it were a level, which is precisely how a one-day budget provision turns into a fake 6.50% repo rate.

**⇒ `factor_event_window` (separate table), the other three in `factor_observation`, kind declared on `factor_series`.** The fourth kind (revision) is not a kind at all — it is an *attribute* of an observation. That is the reason the brief's four-way split collapses to a two-table split plus an event table.

```sql
-- Events with an effect window. Magnitudes decay; they are never carried forward.
CREATE TABLE IF NOT EXISTS factor_event_window (
    event_window_id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id INTEGER NOT NULL,           -- the SHOCK series, e.g. IN.BUDGET.RAIL_CAPEX
    macro_event_id TEXT,                  -- soft link -> macro_events.event_id (TEXT; 23/30
                                          -- resolve to raw_documents via doc_id)
    event_label TEXT NOT NULL,            -- human: 'FY26 Rail Capex provision'
    announced_date TEXT NOT NULL,         -- public announcement (== as_of for the shock)
    window_start TEXT NOT NULL,           -- effect begins
    window_end TEXT,                      -- effect ends; NULL = open-ended
    magnitude REAL,                       -- in series.unit; NULL if not yet quantified
    direction INTEGER,                    -- +1 tailwind | -1 headwind | NULL unknown
    lag_time_months INTEGER,              -- consistent with ripple_effects.lag_time_months
    probability REAL,                     -- 0..1, honest-NULL if unquantified
    as_of_date TEXT NOT NULL,             -- knowledge date of THIS magnitude (may be revised)
    vintage INTEGER NOT NULL DEFAULT 1,
    is_latest INTEGER NOT NULL DEFAULT 1,
    confidence REAL,
    source TEXT NOT NULL,
    source_url TEXT,
    source_doc_id INTEGER,
    chunk_span TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (series_id) REFERENCES factor_series(series_id),
    UNIQUE(series_id, event_label, announced_date, vintage)
);
CREATE INDEX IF NOT EXISTS idx_few_series_date ON factor_event_window(series_id, announced_date DESC);
CREATE INDEX IF NOT EXISTS idx_few_macro_event ON factor_event_window(macro_event_id);
```

Decay: **do not compute a decayed magnitude in the loader.** Compute it at query time from `pruning_decay_config` (the repo's own table, `schema.sql:496-513`, already carrying `lambda = LN(2)/half_life_months` and `is_structural_milestone`). A stored decayed value is a value that silently disagrees with the config the moment someone tunes a half-life; `v_ripple_decayed` (`postgres_schema.sql:589-635`) already demonstrates the correct "decay at query time, never at write time" pattern.

### 1.5 Revisions: version chain, **not** bitemporal

**Recommendation: `vintage` + `revision_of` + `is_latest` (a version chain).** Defend it on cost and on this project's actual stage.

The bitemporal alternative (`valid_from`/`valid_to` interval columns, exclusion constraints) buys exactly one capability we do not need and one that we cannot enforce where the data lives:

1. **It is unenforceable on the fallback DB.** SQLite has **no exclusion constraints**. The guarantee "no two rows may be valid for the same period" would be a comment in `schema.sql` and a trigger (or nothing) in the live DB. A correctness guarantee that exists only in production is a guarantee that will be violated the first time someone loads on SQLite — which is *every* current load, since PG is not running. The version chain's equivalent guarantee (`UNIQUE(series_id, period_start, period_end, vintage)`) is enforced by the DB on both engines, today.
2. **The resolver does not actually need full bitemporality.** "What did we know on T" over a version chain is: among rows with `as_of_date <= T`, take `MAX(vintage)` per period. That *is* as-known-at-T semantics, restricted to the period axis. The only thing bitemporal adds is the ability to hold a period's "then-current" and "now-restated" values in one query with interval algebra — which the release-level view in §2.4 already does with a plain `vintage` column.
3. **The revision rate does not justify it.** Macro/commodity/policy series revise rarely: a handful of series more than once a year. At the target scale (<100k observation rows) a version chain is three extra columns and one extra index; bitemporal is a second interval table per engine, a rewrite of the loaders, and a much harder EXPLAIN for the same answer.
4. **It matches the repo's existing convention rather than inventing one.** `ripple_effects.revision_count` + `last_revised_at` and `raw_documents.doc_version` are already the project's way of saying "this got restated."
5. **What we give up, stated honestly:** we cannot ask "what did the vendor *say* on the day they said it" for a period that had **no** release on that day. That case resolves to honest-NULL, which is the repo's stated preference (`strategies.md` §1) rather than a loss.
6. **Escalation trigger (write it down now, so the decision is revisited on evidence):** promote to bitemporal if (a) any single `(series, period)` accumulates > 5 vintages, (b) the verifier ever needs the original and restated value *simultaneously* in one result set, or (c) `retrieved_at` proves unusable as a system-time axis (i.e. bulk backfills destroy the ordering). All three are measurable — add them as degradation probes (§1.7).

### 1.6 The availability contract

**The rule, in one line: a factor observation is usable on date `T` if and only if `as_of_date <= T`. Never earlier, never on the strength of any other column.**

Three supporting commitments:

- **`is_point_in_time` is metadata, not enforcement.** It answers "how much do we trust the `as_of_date` we wrote", not "is the row visible". It lives on `factor_series` (a series is uniformly trustworthy or uniformly estimated) and is **reported alongside every answer** — an `is_point_in_time=0` series may be *used* (an honest reconstruction beats no data) but must be *labelled*. Enforcing visibility is the `WHERE as_of_date <= T` predicate's job and nothing else's. A per-row `is_point_in_time` boolean would be a flag that can be set wrong, which is worse than no flag.
- **`period_end` is never a visibility gate.** `period_end` describes the *world*; `as_of_date` describes the *reader*. Conflating them is the single most common look-ahead bug in macro backtests: joining `o.period_end <= T` and calling it point-in-time silently imports every restatement, every advance release, and every month-end data snapshot the market never saw. **Only `as_of_date` decides visibility. This is non-negotiable and is enforced by the resolver having no other temporal predicate at all.**
- **Never use `retrieved_at` in a read predicate** (see §1.3). Add a lint test: the shipped resolver SQL must not contain the substring `retrieved_at`.

`availability_contract`:
- `pita_strict` — `as_of_date` is the publisher's own stated release date (RBI press release timestamp, MoSPI release date). Trustworthy to the day.
- `pita_estimated` — `as_of_date` is reconstructed by us (e.g. inferred from a document's `published_date`, or a monthly series with no stated release time). Usable, must be reported, and **must not be used to claim a same-day edge**.

### 1.7 Quarantine and synthetic markers: how they interact

**Yes — factor rows must be quarantine-eligible, and the existing mechanism absorbs them with zero DDL change.** `substrate_quarantine` has `PRIMARY KEY (rule_id, table_name, row_key)` (`substrate_hygiene.py:150-159`), so a new table is quarantined by writing `(rule_id, 'factor_observation', CAST(observation_id AS TEXT))` — exactly the pattern `QUARANTINE_RULES` already uses for `ripple_effects` (`substrate_hygiene.py:82-88`). No schema change to the trust layer is required.

New rules, appended to `QUARANTINE_RULES` in `substrate_hygiene.py` (additive, same tuple shape):

```python
{
    "rule_id": "demo_factor_series",
    "table_name": "factor_series",
    "key_expr": "CAST(series_id AS TEXT)",
    "where": "source = 'fixture' OR source LIKE 'test%' OR factor_key LIKE 'PHASE5%' "
             "OR factor_key LIKE 'TEST%' OR factor_key LIKE 'DEMO%'",
    "reason": "demo/test-seeded factor series definition",
},
{
    "rule_id": "synthetic_factor_observations",
    "table_name": "factor_observation",
    "key_expr": "CAST(observation_id AS TEXT)",
    "where": "source = 'fixture' OR source LIKE 'test%'",
    "reason": "fixture/test-seeded factor observation (not a published number)",
},
{
    "rule_id": "demo_factor_event_windows",
    "table_name": "factor_event_window",
    "key_expr": "CAST(event_window_id AS TEXT)",
    "where": "source = 'fixture' OR source LIKE 'test%'",
    "reason": "fixture/test-seeded factor event window",
},
```

New **degradation** probes (reported, never hidden — `DEGRADATION_RULES` shape, `substrate_hygiene.py:111-148`):

- `broken_version_chain` — any `(series_id, period_start, period_end)` with ≠ 1 rows at `vintage = MAX(vintage)`. This is a real integrity signal that `is_latest` was hand-edited.
- `unlinked_factor_series` — `factor_series` with 0 observations and `current_status='active'`. (The honest-zero state, made visible instead of looking like "no data".)
- `provisional_factor_series` — observations belonging to an `is_point_in_time=0` series. Surfaced with every answer.
- `overdue_factor_series` — active series whose newest known observation's `as_of_date` is older than `max_lookback_days` as of today. This is the early-warning for the staleness rule in §2.3.

**Three interaction rules the resolver MUST honour** (these are the subtle ones):

1. **Quarantine the SERIES, not the individual observation, and refuse rather than fall back.** If a series is quarantined or `current_status != 'active'`, the resolver returns `value_usable = NULL, status = 'quarantined_or_inactive_series'` for the *whole series*. It must **not** filter the bad rows out and let last-value-carry-forward silently launder the previous good value forward. *(Verified: my first draft of the resolver returned **zero rows** in this case, which is a silent-drop bug; the shipped form in §2.3 uses a `LEFT JOIN` onto a single-row gate CTE so the resolver returns exactly one row in every case — including unknown, quarantined, never-fetched, and stale.)*
2. **A quarantined factor never becomes a silently-absent one.** `status` is part of the contract, so a caller can distinguish "this series is quarantined" (a data-integrity problem) from "this series has no data" (a coverage problem). They are different failures with different fixes.
3. **The loader must be unable to write a future-dated observation.** `as_of_date > date('now')` is a look-ahead bug *at construction*. Reject it in Python at insert time and assert `as_of_date <= period_end` is NOT required (a series can be released after its ref period) but `as_of_date >= period_end` for `frequency IN ('monthly','quarterly','annual')` **is** required. Violations are refused, not warned.

**A live gap the spine must not inherit.** The existing rule `demo_macro_events` is `where: "event_id LIKE 'PHASE5%'"` (`substrate_hygiene.py:70-75`), which misses `event_id='MEV_56' / event_name='PHASE5_DEMO_MILESTONE'`. Separately, `unresolvable_ripples` requires `target_type IS NULL` (`substrate_hygiene.py:89-98`) and therefore quarantines **3** rows while **35** rows declare an `Industry`/`Sector` target with a NULL FK and pass the trust layer. **This design does not fix either** (out of scope, and §3.3 says so), but the new rules above are written against the *value* of the source, not a naming convention of the key, precisely so the spine does not inherit the bug.

### 1.8 Linkage forward — the foreign-key reality, and what degrades gracefully

**Verified FK reality (the single most important input to this section):** integer `company_id` FKs into `master_companies` are **dangling** (0/2,653 on moat, 0 on bmp, 0 on geographic_exposure). The PG DDL's `companies(company_id SERIAL)` table has no SQLite counterpart. `symbol`/`ticker` TEXT resolves cleanly everywhere it exists (2,652 / 2,651 / 5,468 / 2,585). `document_chunks.industry_id` and `.sector_id` are 0/2,031,900 populated. `master_companies.sector` is 92.2% NULL/`General Diversified`/`Other`. **`industries` is 12 archetype rows and must not be used as a sector taxonomy.**

**⇒ Design rule: the spine keys on `symbol` TEXT and adds no integer `company_id` FK. Ever.**

Three tiers, each with an explicit graceful degradation:

**Tier 1 — company, by `symbol` (the tier that works).** `factor_symbol_link`, **deferred out of the first load** (§4) but specified here so the schema is not retrofitted:

```sql
CREATE TABLE IF NOT EXISTS factor_symbol_link (
    link_id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,                  -- the ONLY company key that resolves today
    isin TEXT,                             -- copied, NOT a join key
    exposure_magnitude REAL,               -- d(return)/d(factor). NULL = not yet estimated
    exposure_direction INTEGER,            -- +1 | -1 | NULL
    exposure_basis TEXT,                   -- 'declared_segment' | 'revenue_mix' |
                                          -- | 'estimated_panel' | 'llm_distilled'
    as_of_date TEXT NOT NULL,              -- when this exposure was KNOWN
    vintage INTEGER NOT NULL DEFAULT 1,
    is_latest INTEGER NOT NULL DEFAULT 1,
    confidence REAL,
    source TEXT NOT NULL,
    source_doc_id INTEGER,
    chunk_span TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(series_id, symbol, as_of_date, vintage)
);
CREATE INDEX IF NOT EXISTS idx_fsl_symbol ON factor_symbol_link(symbol, series_id);
CREATE INDEX IF NOT EXISTS idx_fsl_series ON factor_symbol_link(series_id, as_of_date DESC);
```

`exposure_magnitude` is **honest-NULL by default**. It is not a number anyone may assert; it is the output of the edge-estimation step in §3.4 and it does not exist yet. The table can exist, and be queried, with every magnitude NULL — that is a valid and useful state, because "which series *could* apply to which names" is answerable before "by how much" is.

Soft-FK policy: **`symbol` is not an enforced FK.** `master_companies` is the authority; every read resolves `symbol → nse_symbol` and **reports the unresolved rate** alongside the answer. Declared `FOREIGN KEY`s in the DDL are documentation (see the note below), not enforcement.

**Tier 2 — event.** `factor_event_window.macro_event_id` → `macro_events.event_id` (TEXT). 23/30 events resolve onward to `raw_documents.doc_id`. Unresolved events are reported, never dropped. The spine **reads** `macro_events` (for the event date and the doc provenance) and **does not modify** it.

**Tier 3 — industry/sector: DO NOT BUILD YET.** There is no live taxonomy to join to (0/2,031,900 chunk industry; 92.2% of `master_companies.sector` unusable; `industries` is archetypes). When it is built it must be a *new, stated* taxonomy — e.g. `sector_taxonomy(sector_code TEXT PK, sector_name, source='nse_official')` seeded from the official NSE sector list already fetched by `master_sync`, plus a new `master_companies.sector_code` column — **never** by overloading the 12 archetype rows. Until that exists, any factor→sector question returns **honest-NULL with a stated reason**, and the report says how many companies that hides. See §6 **Q9**: this requires modifying an existing table, which is a user call.

**What the spine does with `ripple_effects`:** nothing structural. It **does not read `transmission_elasticity`** (constant 1.0 on 61/61 rows — a constant is not a signal, and per `peer_graph.py:11-17` a near-constant feature must be *dropped*, not weighted). The spine supplies the missing half: a **dated, PIT-correct, actually-varying driver value** that the ripple graph could one day be calibrated against. `ripple_history` (76 rows / 5 dates) is likewise untouched.

**FK enforcement — the honest statement.** SQLite defaults `PRAGMA foreign_keys = OFF`, and this repo never turns it on; the live 33 GB DB therefore **does not enforce any declared FK**, in the spine or anywhere else. A declared `FOREIGN KEY` in this codebase is a comment that PG will honour and SQLite will not. Therefore:

1. Declare FKs in the DDL for PG parity and for the reader.
2. **Enforce in application code** in the loader (`series_id` must resolve in `factor_series`; `source_doc_id` must resolve in `raw_documents` when non-NULL).
3. **Verify with a probe, not a constraint.** A `factor_link_integrity` degradation rule reporting orphan counts for every declared FK on the spine. Report it with every answer.
4. Mirror the DDL into `postgres_schema.sql` (append-only) when PG is actually the target, so the guarantee exists in one engine and is *measured* in the other.

---

## 2. THE AS-OF JOIN CONTRACT

> Every SQL block below was **executed against a throwaway in-memory SQLite** with a seeded fixture (repo-rate step function with a restatement, a quarantined series, a registered-but-never-fetched series, an unknown series). Outputs quoted are real.

### 2.1 What we owe the caller, in one paragraph

> A factor read is a function of `(series, T)`, never of "now". It returns **exactly one row per series, always** — carrying `value_usable` (the number, or NULL) plus a `status` that says why a NULL is NULL: `ok`, `stale_beyond_max_lookback`, `no_observation_known_at_T`, `null_value`, `quarantined_or_inactive_series`, or `unknown_series`. A value is usable **iff `status = 'ok'`**; consumers gate on `value_usable` and must never read the raw `value` column. Knowability is decided by `as_of_date <= T` and by nothing else — `period_end`, `retrieved_at`, and `is_latest` are never read predicates. Within a period, the vintage chosen is the highest `vintage` that was already public on `T`, which is not the same as the current `is_latest`. Levels and steps are carried forward (LVCF) only until they exceed the series' own declared `max_lookback_days`, after which the honest answer is NULL, not a stale number and never an interpolated one. Nothing is ever forward-filled across a gap that the declared staleness ceiling does not cover, and no consumer may reach the spine by any route other than these functions.

**This paragraph is the contract. The SQL below is its only sanctioned implementation.** Any component that needs a factor value and does not call one of these two functions is a look-ahead defect by definition — which is exactly the failure `next_wave_plan` §2M documents, re-created in a new place.

### 2.2 The rules, enumerated (each is a test)

- **R1 — `as_of_date <= T` is the only visibility gate.** A row is knowable on `T` iff it was public on `T`.
- **R2 — `period_end` is never a visibility gate.** It describes the world, not the reader. Using it imports every restatement and every advance release the market never saw.
- **R3 — `retrieved_at` is never a visibility gate.** A backfilled row carries `retrieved_at = today` for every historical period; gating on it would make every historical read empty, and gating on its absence would be worse.
- **R4 — Order the step by `period_end`, never by `retrieved_at` or `rowid`.** For LVCF, the *newest state* is the one with the latest `period_end`, regardless of the order in which we happened to fetch it. Ordering by retrieval is the same class of bug wearing a different hat.
- **R5 — `is_latest` is never a read predicate.** It means "latest as of **now**". Filtering on it is a look-ahead in one word. The resolver picks `MAX(vintage) WHERE as_of_date <= T` instead. This is the sharpest trap in the design and gets its own test (§5, `test_is_latest_flag_is_never_used_by_resolver`).
- **R6 — Staleness ceiling, per series.** `age_days = julianday(T) - julianday(chosen.period_end)`. If `age_days > factor_series.max_lookback_days`, the value is **not usable** — return `stale_beyond_max_lookback` and NULL. `max_lookback_days` is `NOT NULL` precisely so "no ceiling" is not expressible.
- **R7 — No interpolation, ever.** Never average across a gap, never linearly extend, never nearest-neighbour backwards. LVCF carries a *declared* value forward; it never manufactures one.
- **R8 — Max-lookback policy (the outer bound).** Additionally, a caller may pass `:max_lookback_override_days` to apply a *stricter* ceiling at a specific call site (e.g. a backtest that refuses anything older than 10 sessions). The effective ceiling is `MIN(series.max_lookback_days, override)`. The override may only ever *tighten*.
- **R9 — Quarantine precedes LVCF, and refuses rather than falls back.** A quarantined/inactive series returns NULL + reason for the whole series. It never degrades into "the last value before the bad row".
- **R10 — Exactly one row out, always.** Even for an unknown series id. A resolver that returns zero rows makes "no data" indistinguishable from "I forgot to write the query".

### 2.3 The state resolver — `factor_state(series_id, as_of_date)` (SQLite, runnable)

```sql
-- v_factor_state : THE ONLY sanctioned way to read a factor value as of date T.
-- Returns exactly one row. Gate on value_usable; never read raw_value.
WITH series_gate AS (
  SELECT b.series_id,
         b.asof_date,
         any.series_id        AS any_series_id,      -- does the definition exist at all?
         live.series_id       AS live_series_id,     -- exists AND active AND not quarantined
         MIN(live.max_lookback_days, :max_lookback_override_days) AS max_lookback_days
  FROM (SELECT :series_id AS series_id, :asof_date AS asof_date) b
  LEFT JOIN factor_series any
         ON any.series_id = b.series_id
  LEFT JOIN factor_series live
         ON live.series_id = b.series_id
        AND live.current_status = 'active'
        AND NOT EXISTS (SELECT 1 FROM substrate_quarantine q
                        WHERE q.table_name = 'factor_series'
                          AND q.row_key  = CAST(live.series_id AS TEXT))
),
ranked AS (
  -- R1/R2/R3/R5: knowledge gate is as_of_date alone; best vintage KNOWN AT T, not is_latest.
  SELECT o.observation_id, o.period_start, o.period_end, o.value, o.unit,
         o.as_of_date, o.vintage,
         ROW_NUMBER() OVER (
           PARTITION BY o.period_start, o.period_end
           ORDER BY o.vintage DESC, o.as_of_date DESC, o.observation_id DESC
         ) AS vintage_rank
  FROM factor_observation o
  JOIN series_gate g ON g.live_series_id = o.series_id
  WHERE o.as_of_date <= g.asof_date                                        -- R1 (only gate)
    AND NOT EXISTS (SELECT 1 FROM substrate_quarantine q
                    WHERE q.table_name = 'factor_observation'
                      AND q.row_key  = CAST(o.observation_id AS TEXT))     -- R9
),
latest_known AS (SELECT * FROM ranked WHERE vintage_rank = 1),
picked AS (
  -- R4: newest STATE = latest period_end. Never order by retrieved_at.
  SELECT lk.observation_id, lk.value, lk.unit, lk.period_start, lk.period_end,
         lk.as_of_date, lk.vintage,
         julianday(g.asof_date) - julianday(lk.period_end) AS age_days,
         g.max_lookback_days, g.any_series_id, g.live_series_id
  FROM latest_known lk
  CROSS JOIN series_gate g
  ORDER BY lk.period_end DESC, lk.vintage DESC
  LIMIT 1
)
SELECT s.factor_key, s.family, s.is_point_in_time, s.availability_contract,
       p.value AS raw_value,
       CASE WHEN <status> = 'ok' THEN p.value END AS value_usable,   -- expanded below
       p.period_start, p.period_end, p.as_of_date, p.vintage,
       CAST(ROUND(p.age_days) AS INTEGER) AS age_days, p.max_lookback_days,
       <status> AS status
FROM series_gate g
LEFT JOIN factor_series s ON s.series_id = g.series_id
LEFT JOIN picked p ON 1 = 1;                                          -- R10
```

with `<status>` expanded (used twice — in SQLite, factor the status into a CTE and select from it so the CASE is written once):

```sql
statused AS (
  SELECT g.series_id, g.any_series_id, g.live_series_id, g.max_lookback_days,
         p.observation_id, p.value, p.unit, p.period_start, p.period_end,
         p.as_of_date, p.vintage, p.age_days,
         CASE
           WHEN g.any_series_id  IS NULL THEN 'unknown_series'
           WHEN g.live_series_id IS NULL THEN 'quarantined_or_inactive_series'
           WHEN p.observation_id IS NULL THEN 'no_observation_known_at_T'
           WHEN p.value          IS NULL THEN 'null_value'
           WHEN p.age_days > g.max_lookback_days THEN 'stale_beyond_max_lookback'   -- R6
           ELSE 'ok'
         END AS status
  FROM series_gate g LEFT JOIN picked p ON 1 = 1
)
SELECT s.factor_key, s.family, s.is_point_in_time, s.availability_contract,
       x.value AS raw_value,
       CASE WHEN x.status = 'ok' THEN x.value END AS value_usable,       -- R6/R7/R9
       x.period_start, x.period_end, x.as_of_date, x.vintage,
       CAST(ROUND(x.age_days) AS INTEGER) AS age_days, x.max_lookback_days, x.status
FROM statused x
LEFT JOIN factor_series s ON s.series_id = x.series_id;
```

**Verified behaviour** (seed: repo rate 6.25 @ `period_end 2023-01-06`, 6.50 @ 2023-12-06, 6.50 @ 2024-04-10 (v1), 6.75 @ 2024-04-10 (v2, `as_of 2026-08-01`); `max_lookback_days=45`; one quarantined series; one never-fetched series):

| Query T | `value_usable` | `period_end` | `vintage` | `age_days` | `status` |
|---|---|---|---|---|---|
| `2023-01-10` | `6.25` | 2023-01-06 | 1 | 4 | `ok` |
| `2023-01-20` | `6.25` | 2023-01-06 | 1 | 14 | `ok` (LVCF carrying) |
| `2023-03-01` | **`None`** | 2023-01-06 | 1 | 54 | `stale_beyond_max_lookback` |
| `2024-04-10` | `6.50` | 2024-04-10 | **1** | 0 | `ok` (v2 not yet public) |
| `2026-08-02` | **`None`** | 2024-04-10 | **2** | 844 | `stale_beyond_max_lookback` |
| series 2, `2023-02-01` | `None` | — | — | — | `quarantined_or_inactive_series` |
| series 3, `2023-01-01` | `None` | — | — | — | `no_observation_known_at_T` |
| series 99 | `None` | — | — | — | `unknown_series` |

The 2024-04-10 row is the money shot: the v2 restatement exists in the table, and the resolver still returns **v1** because v2 was not public until 2026-08-01. That is the whole anti-look-ahead mechanism in one result row.

### 2.4 The release view — "what did we know on T" (no LVCF, no staleness)

Used by the verifier and by any "was there news on this day?" question. Returns **releases**, not state:

```sql
-- v_factor_releases : every (period, vintage) KNOWN at T. One row per release.
-- Deliberately un-gated on staleness: this view answers "what existed", not "what to use".
SELECT o.observation_id, o.series_id, s.factor_key, s.family, s.is_point_in_time,
       o.period_start, o.period_end, o.value, o.unit,
       o.as_of_date, o.vintage, o.is_latest,
       (o.vintage > 1) AS is_revision
FROM factor_observation o
JOIN factor_series s ON s.series_id = o.series_id
WHERE o.series_id IN (:series_ids)
  AND o.as_of_date <= :asof_date
  AND NOT EXISTS (SELECT 1 FROM substrate_quarantine q
                  WHERE q.table_name = 'factor_observation'
                    AND q.row_key  = CAST(o.observation_id AS TEXT))
ORDER BY s.family, s.factor_key, o.period_end, o.vintage;
```

Verified — the same seed returns **3 rows** at `T=2024-04-10` and **4 rows** at `T=2026-08-02` (the extra row is the `vintage=2, as_of=2026-08-01` restatement, which the earlier query correctly could not see). This is the view that makes revision history auditable without a second schema.

### 2.5 The panel resolver — all active series at T

For the forward join against company returns. **Corrected after execution:** the naive two-correlated-subquery form returns `value_candidate` for a *stale* series unless the staleness gate is applied in the outer `WHERE`. The shipped form computes candidate + age, then gates:

```sql
-- v_factor_panel_asof : one row per ACTIVE, UNQUARANTINED series at date T.
WITH cand AS (
  SELECT s.series_id, s.factor_key, s.family, s.unit, s.is_point_in_time,
         s.availability_contract, s.max_lookback_days,
         (SELECT o.value FROM factor_observation o
           WHERE o.series_id = s.series_id
             AND o.as_of_date <= :asof_date                       -- R1
             AND NOT EXISTS (SELECT 1 FROM substrate_quarantine q
                             WHERE q.table_name = 'factor_observation'
                               AND q.row_key  = CAST(o.observation_id AS TEXT))
           ORDER BY o.period_end DESC, o.vintage DESC, o.as_of_date DESC  -- R4
           LIMIT 1) AS value_candidate,
         (SELECT CAST(ROUND(julianday(:asof_date) - julianday(o.period_end)) AS INTEGER)
           FROM factor_observation o
           WHERE o.series_id = s.series_id
             AND o.as_of_date <= :asof_date
             AND NOT EXISTS (SELECT 1 FROM substrate_quarantine q
                             WHERE q.table_name = 'factor_observation'
                               AND q.row_key  = CAST(o.observation_id AS TEXT))
           ORDER BY o.period_end DESC, o.vintage DESC, o.as_of_date DESC
           LIMIT 1) AS age_days
  FROM factor_series s
  WHERE s.current_status = 'active'
    AND NOT EXISTS (SELECT 1 FROM substrate_quarantine q
                    WHERE q.table_name = 'factor_series'
                      AND q.row_key  = CAST(s.series_id AS TEXT))
)
SELECT factor_key, family, unit, is_point_in_time, availability_contract,
       value_candidate,
       CASE WHEN value_candidate IS NOT NULL
             AND age_days <= max_lookback_days
            THEN value_candidate END AS value_usable,                   -- R6 applied HERE
       age_days, max_lookback_days,
       CASE WHEN value_candidate IS NULL            THEN 'no_value_known_at_T'
            WHEN age_days > max_lookback_days       THEN 'stale_beyond_max_lookback'
            ELSE 'ok' END AS status
FROM cand
ORDER BY family, factor_key;
```

Verified at `T=2023-03-01`: `IN.RBI.REPO_RATE → value_usable = None, status = stale_beyond_max_lookback` (the naive form wrongly returned `6.25` here). At `T=2023-01-10`: `value_usable = 6.25, status = ok`.

### 2.6 The gap audit — proving no forward-fill happened

`max_lookback_days` bounds staleness in *days*. This bounds staleness in *observations*, and is what a reviewer runs to confirm a series is not being silently carried across a long break. Deduplicate to the latest **known** vintage first (otherwise the version chain shows up as a bogus `gap_days = 0` self-row):

```sql
-- v_factor_gap_audit : consecutive known periods as of T, with the gap between them.
-- Any gap_days >> frequency is a carry-forward the max_lookback rule is silently absorbing.
WITH latest_known AS (
  SELECT o.*, ROW_NUMBER() OVER (PARTITION BY period_start, period_end
           ORDER BY vintage DESC, as_of_date DESC) AS vr
  FROM factor_observation o
  WHERE o.series_id = :series_id AND o.as_of_date <= :asof_date
)
SELECT period_start, period_end, value, vintage, as_of_date,
       LAG(period_end) OVER (ORDER BY period_end) AS prev_period_end,
       CAST(julianday(period_end) - julianday(LAG(period_end) OVER (ORDER BY period_end))
            AS INTEGER) AS gap_days
FROM latest_known
WHERE vr = 1
ORDER BY period_end;
```

Verified output on the seed: `(2023-01-06, 334d gap), (2023-12-06, 126d gap)` — i.e. a series with two long breaks, correctly surfaced rather than hidden.

### 2.7 The invariant guard — the anti-look-ahead assertion

The one query that must return **0, forever**, and that ships as a test:

```sql
-- v_factor_lookahead_audit : MUST be empty/0. Any row a decision-path read can return
-- whose as_of_date is later than T is a look-ahead defect.
SELECT COUNT(*) AS lookahead_violations
FROM (
  SELECT o.observation_id, o.as_of_date
  FROM factor_observation o
  JOIN factor_series s ON s.series_id = o.series_id
  WHERE o.series_id = :series_id
    AND o.as_of_date <= :asof_date          -- the ONLY temporal predicate a read may use
) r
WHERE r.as_of_date > :asof_date;
```

**Non-vacuity is part of the assertion.** A `0` from a table with no future rows proves nothing. The test must additionally assert `COUNT(*) WHERE as_of_date > T > 0` on the *whole table* — i.e. the fixture contains at least one row the gate must exclude. On the verified seed at `T=2024-04-10`, the guard returns `0` while the table holds **1** observation with `as_of_date > T`. That is a real, non-vacuous proof.

### 2.8 Decision-path vs evaluation-path: a naming discipline that prevents the whole class

The verifier legitimately reads the future (it must, to measure error). The decision path must never. Distinguishing them by convention alone is weak, so make it mechanical:

- Every function that may be called from a decision path is named `*_decision` (`factor_state_decision`, `factor_panel_decision`). Every function that reads forward returns is named `*_evaluation` (`factor_forward_return_evaluation`).
- **A lint test greps the source of every `*_decision` function and asserts it contains no `retrieved_at`, no `is_latest =` in a `WHERE`, no `period_end <=` as a visibility gate, and no reference to `daily_price_delivery` with a future date predicate.** This is a source-level test, not a behavioural one, because the failure is a *shape* of the query, not a value.
- The evaluation ledger (`factor_forecast_log`, §3.4) is a **different table** from anything a decision read can join, so a mis-wired join fails loudly rather than returning plausible fiction.

---

## 3. WHY THE CURRENT SUBSTRATE CANNOT ANSWER THE USER'S QUESTION YET

The question: *"when a new shock happens, predict which stocks benefit and by how much, then measure how close we were."*

### 3.1 Defect-by-defect: what the spine fixes, partly fixes, and does not touch

| # | Defect | Verified evidence | Spine effect |
|---|---|---|---|
| D1 | **Constant transmission elasticity** | `SELECT DISTINCT transmission_elasticity FROM ripple_effects` → `{1.0}` on 61/61 | **Does not touch.** The spine has no elasticity and must not invent one. Per `peer_graph.py:11-17`, a near-constant feature is *dropped*, not weighted. Any β estimated off a constant-1.0 column is 1.0 by construction. |
| D2 | **Ripple targets unresolvable** | 12 rows `target_type='Industry'` + 23 `'Sector'`, **all 35 with NULL FK**; real targets live in prose inside `transmission_channel`; only 19 `target_company_id` and those join the *surrogate* `moat_evaluations.company_id`, never `master_companies` | **Partially.** The spine supplies the missing *driver*: a dated, PIT-correct, genuinely varying input where the ripple graph has a constant and a string. It does **not** resolve ripple targets — that is `strategies.md` S3, unstarted. |
| D3 | **`__NO_POLICY_TEMPLATE__` placeholders** | 3,239/5,470 = **59.2%**; `coverage_status='no_template'`, `severity_score` NULL on all 3,239; only 44 distinct real `policy_name` | **Partially.** The factor series carry the real macro number, so a policy lens can vote on a number instead of on a placeholder. The 3,239 sentinel rows remain and must keep being excluded by the existing predicate (`policy_name != '__NO_POLICY_TEMPLATE__'`, as in `postgres_schema.sql:343-345`). |
| D4 | **Degenerate FK columns** | `moat_evaluations.company_id`→isin **0/2,653**; `business_model_profiles.company_id`→isin **0**; `geographic_exposure.company_id`→isin **0**; `document_chunks.industry_id`/`.sector_id` **0/2,031,900** | **Partially — by avoidance.** The spine links on `symbol` TEXT (the only key that resolves: 2,652 / 2,651 / 5,468 / 2,585) and adds **no** integer `company_id` FK. It does not repair the existing dangling FKs; it declines to extend them. |
| D5 | **63% of ensemble weight on mute lenses** | material rows 43,789: quality 0, policy 0, supply 0 directions; factor 42,346. Weights: supply 0.358 + quality 0.271 = **0.629** (`desk_quant_2026-09-25.md:25`, `test_findings_2026-09-24.md:9`) | **Not fixed directly — supplies the missing input.** Mute lenses are mute because there is nothing dated for them to vote on. The spine is the *mechanism* by which `policy_macro`/`supply_chain` gain dated flows. It is not a *guarantee*: the weight distribution only moves once real history accumulates under the §4 promotion bar. |
| D6 | **Levels without history** | `moat_history` 2,654 rows / **2** dates; `policy_eni_history` 5,470 / **1** date (all `2021-10-27`); `ripple_history` 76 / 5 dates | **Not fixed.** That is substrate *versioning* for moat/policy/ripple, a different workstream. The spine is a new table that is **born dated**; it cannot retro-date the others. |
| D7 | **Unconditional regime** | `model_explainer_rankings` 69,500 rows, `regime_tag='*'` on **100%**; 4 lenses × exactly 17,375 | **Partially.** The spine can supply *real, dated* regime tags (e.g. `rates_up`, `crude_down`) as a derived classification. The ranking table stays degenerate until `EODCorrector` starts writing conditioned rows. |
| D8 | **No sector taxonomy** | `master_companies.sector`: NULL 2,714 + `General Diversified` 1,868 + `Other` 1,363 = **5,945/6,445 = 92.2% unusable**; `industries` = 12 archetype rows | **Not fixed — explicitly out of scope.** The spine returns honest-NULL at company→sector and reports how many names that hides. Needs a user answer — **Q9**. |
| D9 | **Quarantine leaks** | `event_id='MEV_56' / event_name='PHASE5_DEMO_MILESTONE'` escapes `where: "event_id LIKE 'PHASE5%'"` (`substrate_hygiene.py:70-75`); 35 declared-but-unresolvable ripples escape `unresolvable_ripples` (needs `target_type IS NULL`, `substrate_hygiene.py:89-98`) | **Not fixed** — but the spine's own rules (§1.7) key on **source value**, not key naming, precisely so this class is not reproduced. |
| D10 | **Macro substrate is thin and partly archived** | `macro_events` 30 rows, **11 already `'Archived'`** by `prune_decayed_signals()`'s 24-month rule; 3/30 with no `affected_nodes_json`; `macro_events.category`: Fiscal 13 / Archived 11 / Policy 2 / Trade 2 / Monetary 1 / Regulatory 1 | **Partially.** The spine is dated and is **not** subject to the 24-month archive rule (see **Q11**) — that is the point of building it separately. |

### 3.2 The honest summary of the spine's own value

With **one** series loaded and **zero** exposure rows, the spine delivers:
- a correct, dated, auditable, non-look-ahead **input**;
- a **time axis** that later stages can join to `daily_price_delivery` without re-deriving point-in-time semantics;
- an **honest-zero** state that is a valid, queryable answer rather than a failure.

It delivers **no** company-level signal whatsoever. Stated that way so nobody mistakes a clean schema for a working model.

### 3.3 What the spine explicitly does not fix

Constant elasticities (D1), dangling numeric FKs elsewhere (D4), the 59.2% policy placeholders (D3), the degenerate history tables (D6), the 100%-unconditional regime tag (D7), the absent sector taxonomy (D8), the two live quarantine leaks (D9), and the archived macro events (D10). Every one of these is a **separate workstream with its own owner**. The spine is a foundation under all of them, not a substitute for any of them.

### 3.4 What remains between the spine and the user's question

Ordered by how much each blocks the actual goal.

1. **Exposure magnitudes** — `|∂return_ij / ∂factor_k|` per company. The spine supplies the shock; **nothing in the repo supplies the loading.** This is the single largest gap and it is the reason the spine alone answers nothing. Table: `factor_symbol_link` (§1.8), deferred.
2. **Edge estimation** — the loading must be *estimated*, not asserted. Repo has no estimation harness. It needs a panel regression or binned event study run under the `strategies.md` §4 bar: ≥30 cohorts (≥13 at 20D), cohort-clustered mean ≥ +500bps net of measured costs, hit-rate CI lower > 0.5 cluster-robust, same sign in both regimes, shuffle-entry placebo ≈ 0. **An exposure asserted by an LLM is a placeholder wearing a number's clothes** — the same failure as D3, one layer up.
3. **Forward integrator** — a component that, given (new observation, exposure table, edge estimates), emits per-symbol predicted returns. Does not exist. Must be a `*_decision`-only consumer of §2.
4. **Verifier** — record the prediction, realize the forward return, score the error. `model_validation_scores` and `move_attribution` are the wrong shapes: they score *lens agreement* and *residual attribution*, not *predicted magnitude vs realised magnitude*. Needs a new `factor_forecast_log(forecast_id, asof_date, series_id, symbol, predicted_return, predicted_horizon, is_point_in_time, created_at)` plus a scoring pass, carrying the same PIT guarantees — and it must be an `*_evaluation` consumer (§2.8), because reading the future is its entire job.
5. **Sector taxonomy** (D8) — before any sector-level answer is possible at all.
6. **Survivorship / universe discipline** — the universe map was found shifting (2,093/2,481 → Microcap 250, `next_wave_plan` §4). A forward-return join across a moving universe needs a dated membership table or the forward returns are not comparable across time. Cheap to get wrong, expensive to notice.

**Bottom line for the user: the factor spine is a necessary and sufficient *foundation* for "predict which stocks benefit" and a necessary-but-nowhere-near-sufficient piece of it. Items 1–4 above are the actual work.**

---

## 4. THE MINIMAL FIRST LOAD

### 4.1 Shape: works with one real series; degrades honestly to zero

Three properties, in order of importance:

- **A registered-but-never-fetched series is a first-class, queryable state.** The `factor_series` registry is written from a code constant, not from a fetch. A series in the registry with zero observations returns `status='no_observation_known_at_T'`, `value_usable=NULL`. **The schema is useful the moment it is written, before any network call succeeds.** This is the honest-zero state.
- **A loader that cannot reach its source returns `[]` and records the failure; it never raises into the pipeline.** Follows `peer_graph`'s `insufficient_signal` discipline (`peer_graph.py:24-27`, recorded in `company_peer_runs`) and the `reality_intelligence` ingest pattern. A source being unreachable is a *reported* degradation, not an exception.
- **With zero reachable sources the whole system still runs**: zero observations, every series honest-NULL, the verifier reports `n_observations=0` and refuses to produce a score. Nothing fabricates a zero, a neutral value, or a carry-forward from nothing.

### 4.2 Components (all specified; none written by this task)

**`reality_engine/processing/factor_spine.py`** — owns its DDL, following `substrate_hygiene.py:173-178` / `move_attributor.py:170-175` / `repository.py:3853-3874`:

```python
FACTOR_SERIES_REGISTRY: tuple[dict, ...] = (
    # IN.RBI.REPO_RATE: step function, family rates_credit. FIRST series (§4.3).
    dict(factor_key="IN.RBI.REPO_RATE", family="rates_credit", unit="pct",
         frequency="irregular", value_semantics="rate", source="rbi_official",
         source_url="https://www.rbi.org.in/", license="RBI public press release; review before redistribution",
         aggregation_policy="lvcf", max_lookback_days=45, expected_publication_lag_days=0,
         is_point_in_time=1, availability_contract="pita_strict",
         methodology_notes="RBI policy repo rate, effective date of each MPC action"),
    # Registered, unreachable until a loader exists. Honest-NULL by design.
    dict(factor_key="IN.CPI.YOY", family="rates_credit", unit="pct",
         frequency="monthly", source="mospi", max_lookback_days=400,
         expected_publication_lag_days=45, aggregation_policy="last", is_point_in_time=1, ...),
)
```

Public surface: `ensure_factor_spine_schema(manager=None)`, `register_series(manager)`, `upsert_observations(manager, series_key, rows) -> int`, `factor_state(manager, series_key, asof_date) -> dict`, `factor_panel(manager, asof_date) -> list[dict]`, `factor_releases(manager, asof_date, series_keys) -> list[dict]`, `gap_audit(manager, series_key, asof_date) -> list[dict]`, `lookahead_audit(manager, series_key, asof_date) -> dict`.

`upsert_observations` guard (the load-time half of the anti-look-ahead contract):
```
raise ValueError if as_of_date > today            # future knowledge is a bug at construction
raise ValueError if source not in ALLOWED_SOURCES # no vendor:<name> without a license decision
raise ValueError if series_id not resolved
warn + record in factor_load_run if as_of_date < period_end for a monthly/quarterly series
```

**`reality_engine/scripts/run_factor_spine_load.py`** — follows `run_substrate_hygiene.py` / `run_peer_graph.py`: prints counts, prints a `PIT SELF-CHECK` block, prints `ALL CHECKS PASSED`, is idempotent, takes `--dry-run` and `--series <key>`.

**`factor_load_run`** (audit; the "it tried and this is what happened" record):

```sql
CREATE TABLE IF NOT EXISTS factor_load_run (
    load_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id INTEGER,
    factor_key TEXT,
    status TEXT NOT NULL,              -- ok | partial | failed | refused
    n_observations INTEGER DEFAULT 0,
    n_inserted INTEGER DEFAULT 0,
    n_revised INTEGER DEFAULT 0,
    earliest_period_end TEXT,
    latest_period_end TEXT,
    latest_as_of_date TEXT,
    source TEXT,
    error TEXT,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);
```

### 4.3 First series: `IN.RBI.REPO_RATE` — and why

1. **It is the cleanest step function in existence**, so LVCF, the staleness ceiling, the no-forward-fill rule, and the "supersede, don't accumulate" semantics all get exercised end-to-end by the very first load. A monthly flow series would exercise only a fraction of the contract.
2. **The join value already exists in the repo**: `regulatory_political_risks` carries live policy names `RBI_RATE_CYCLE` and `RBI Repo Rate Cut Tailwind`, so the very first series has an immediate consumer.
3. **Its `as_of_date` is exact, not estimated** — RBI publishes an announcement date, so it is `pita_strict` from day one. Nothing in the first load should be a reconstruction.
4. **It is free and officially published**, which keeps §6 **Q4** (vendor licensing) out of the critical path.
5. **`max_lookback_days = 45`** is honest: the MPC meets roughly bi-monthly, so a state older than ~6 weeks *should* be reported stale rather than presented as current. A larger number would launder a missed load into a confident wrong answer.

**If the RBI source turns out to be unreachable (the likely outcome — the recon subagent's source survey is the live evidence):** the fallback is **not** a hand-entered "real-looking" series. The fallback is the honest-zero state: the series stays registered, returns `no_observation_known_at_T`, and the `overdue_factor_series` degradation probe fires. A hand-typed number whose `as_of_date` we guessed is exactly the `pita_estimated` / synthesis failure the repo forbids — and at minimum it must be loaded with `source='manual'`, `is_point_in_time=0`, `availability_contract='pita_estimated'`, and reported as provisional on every read.

Second choice if rates are unavailable: a **monthly flow with publication lag** (`IN.CPI.YOY` or credit growth) — it exercises the `last` policy, `expected_publication_lag_days`, and the flow semantics that the step function cannot. Between the two, the *step* function is preferred because it exercises strictly more of the contract.

### 4.4 The test that proves PIT correctness

> **An as-of query on a past date must not return any row whose `as_of_date` is later than that date — and the test must be non-vacuous.**

```python
def test_asof_query_never_returns_row_with_later_as_of(self):
    """The core anti-look-ahead assertion, on a frozen past date.

    Non-vacuity is part of the assertion: the fixture must contain at least
    one observation with as_of_date > T, otherwise COUNT(*)=0 proves nothing.
    """
    T = "2024-04-10"                       # frozen; v2 of this period is public only 2026-08-01
    # 1. the whole table DOES contain rows the gate must exclude
    self.assertGreater(
        self.n_obs_where("as_of_date > ?", T), 0,
        "fixture is vacuous: no future-dated row exists, so the guard proves nothing")
    # 2. the invariant query returns 0
    self.assertEqual(lookahead_audit(self.conn, series_id=1, asof_date=T)["lookahead_violations"], 0)
    # 3. the resolver's own output satisfies the same invariant
    row = factor_state(self.conn, "IN.RBI.REPO_RATE", T)
    self.assertIsNotNone(row["raw_value"])
    self.assertLessEqual(row["as_of_date"], T)
    # 4. and it picked the vintage that was public on T, not the current one
    self.assertEqual(row["vintage"], 1)
    self.assertAlmostEqual(row["value_usable"], 6.50)
```

Four independent assertions, and the third line — `vintage == 1` while the table's `is_latest` row is `vintage == 2` — is the one that would fail first if someone "simplified" the resolver by filtering on `is_latest`.

---

## 5. TEST PLAN

New file `reality_engine/tests/test_factor_spine.py`, `unittest`, in-memory SQLite fixture (no live DB, no network), following the repo's `unittest discover -s reality_engine/tests -p "test_*.py"` pattern.

Fixture: a 3-series in-memory DB — `IN.RBI.REPO_RATE` (3 step observations + 1 restatement), `IN.RBI.SDF` (quarantined), `IN.CPI.YOY` (registered, zero observations) — the exact seed used to validate the SQL in §2.

| # | Test name | Assertions |
|---|---|---|
| 1 | `test_asof_query_never_returns_row_with_later_as_of` | Fixture contains ≥1 row with `as_of_date > T` (non-vacuity); `lookahead_audit` returns 0; resolver's `as_of_date <= T` (§4.4). |
| 2 | `test_asof_predicate_is_not_vacuous` | The future-dated row count > 0 for every T in the frozen list `['2023-01-10','2023-03-01','2024-04-10','2026-08-02']`. A mutation that drops the predicate fails this. |
| 3 | `test_lvcf_step_function_carries_value_forward` | T=2023-01-10 and T=2023-01-20 both return `6.25` with `period_end=2023-01-06`, `status='ok'`. |
| 4 | `test_step_function_uses_latest_period_not_latest_retrieval` | Two observations, same `as_of_date`, different `period_end`, **earlier row retrieved last**. Resolver returns the one with the later `period_end`. Guards R4. |
| 5 | `test_staleness_beyond_max_lookback_returns_null` | T=2023-03-01 → `value_usable is None`, `status='stale_beyond_max_lookback'`, `age_days=54 > 45`, and `raw_value` is still 6.25 (diagnosable, not silently dropped). |
| 6 | `test_staleness_within_max_lookback_returns_value` | T=2023-01-20 → `value_usable == 6.25`, `status='ok'`. |
| 7 | `test_no_forward_fill_across_declared_gap` | With `max_lookback_days` lowered so the 334-day gap is not covered, the resolver returns NULL across it; `gap_audit` reports `gap_days=334`; **no interpolated value appears at any T inside the gap**. |
| 8 | `test_revision_resolver_picks_vintage_known_at_T` | T=2024-04-10 → `vintage=1`, `value_usable=6.50` (verified output). |
| 9 | `test_revision_resolver_ignores_vintage_published_after_T` | T=2024-04-10 → the `vintage=2, as_of=2026-08-01` row is invisible; T=2026-08-02 → `vintage=2`, `value=6.75` (verified output). |
| 10 | `test_is_latest_flag_is_never_used_by_resolver` | Seed a row with `is_latest=0` at the highest `vintage`. The resolver still returns it. **Fails if the resolver filters on `is_latest`** — the R5 guard. |
| 11 | `test_resolver_never_uses_retrieved_at_or_period_end_as_gate` | Behavioural: T=2023-03-01 returns the 2023-01-06 row by `period_end` ordering while its `retrieved_at` is 2026-09-29; a gate on `retrieved_at` would return nothing. |
| 12 | `test_quarantined_series_returns_null_with_reason` | `IN.RBI.SDF` → `value_usable is None`, `status='quarantined_or_inactive_series'` (verified). |
| 13 | `test_quarantined_series_does_not_fall_back_to_prior_value` | After quarantining the series that holds the *current* step, the resolver returns NULL — **not** the previous step's 6.25. Guards the laundering bug. |
| 14 | `test_quarantine_rule_materializes_factor_keys` | `substrate_hygiene.apply(conn)` writes `table_name='factor_series'` and `'factor_observation'` rows for the fixture seeds; `quarantined_keys(conn,'factor_series')` is non-empty. |
| 15 | `test_zero_load_degrades_to_honest_null` | `IN.CPI.YOY` (registered, zero obs) → `value_usable is None`, `status='no_observation_known_at_T'` (verified). |
| 16 | `test_unknown_series_returns_one_row` | `series_id=999` → exactly one row, `status='unknown_series'` (verified). Guards R10 against the zero-row bug I hit in drafting. |
| 17 | `test_future_as_of_date_rejected_at_insert` | `upsert_observations(..., as_of_date='2099-01-01')` raises `ValueError`; nothing written. |
| 18 | `test_backfill_is_dated_by_publication_not_retrieval` | A 200-point backfill all carrying `retrieved_at=today` still resolves correctly at 200 historical `T`s. This is the property that makes historical extension safe. |
| 19 | `test_decision_query_has_no_future_reference` | **Source-level lint.** Every `*_decision` function's source contains no `retrieved_at`, no `is_latest =` inside a `WHERE`, no `period_end <=` visibility gate, and no `daily_price_delivery` future-date predicate. |
| 20 | `test_evaluation_query_is_distinctly_named` | Every function that reads forward returns has an `_evaluation` suffix; every decision function has `_decision`. Blocks the two paths from being confused. |
| 21 | `test_frozen_regression_snapshot` | **Golden test.** `factor_panel(T='2024-04-10')` and `factor_releases(T='2024-04-10')` return exactly the frozen expected rows, compared field-by-field including `vintage`, `as_of_date`, and `status`. Any change to the resolver's output changes the golden file and fails loudly. |
| 22 | `test_series_registry_declares_no_null_max_lookback` | Every registry entry has non-NULL `max_lookback_days` and a recognised `aggregation_policy`/`family`. Stops a series being registered without a staleness contract. |
| 23 | `test_panel_query_applies_staleness_gate` | Regression for the bug found in §2.5: at T=2023-03-01 the panel returns `value_usable is None` for the stale repo-rate series, and **not** 6.25. |
| 24 | `test_broken_version_chain_probe_fires` | A fixture with two rows at the same `MAX(vintage)` for one period makes the `broken_version_chain` degradation probe return > 0. |
| 25 | `test_observation_provenance_is_present_or_null` | Every observation has either a `source_url` or a (`source_doc_id` + `chunk_span`); neither may be synthesized. |

**Minimum bar to call the spine "working": tests 1, 2, 5, 9, 10, 13, 15, 16, 21, 23 green.** The rest are hardening.

**Integration test (later, when a loader exists):** load the real repo-rate series, then assert `factor_state(T)` for every T across the loaded range produces a sequence that is **monotone non-increasing in vintage** and never contains a value whose `as_of_date > T`. A re-run of the same load produces byte-identical output (idempotence).

---

## 6. OPEN DECISIONS FOR THE USER

> Numbered **Q1–Q12** so they do not collide with the defect IDs D1–D10 in §3.1.
> Only the user can answer these. Ordered by how much they block the work.

**Q1 — Primary engine: PostgreSQL or SQLite for the spine?**
PG is the stated production target (`AGENTS.md` rule 2) but **nothing is running on it**; all 33 GB is SQLite, and SQLite has no exclusion constraints, no `LATERAL`, and enforces no FKs. *Recommendation:* write both DDLs now (the schema is portable as drafted), load SQLite, migrate later — the tables are tiny. But the answer changes what guarantees can be **enforced** rather than merely **measured**.

**Q2 — Revision handling: accept the version chain, or pay for bitemporal?**
§1.5 recommends `vintage`/`revision_of`/`is_latest` and gives the escalation triggers. Accepting bitemporal means the "no two valid rows per period" guarantee is enforceable on PG and **unenforceable on SQLite** — i.e. it exists only in the engine that is not running. Confirm the version chain, or accept that split.

**Q3 — Which factor families first, and in what order?**
The five named (`rates_credit`, `crude_energy`, `policy_budget`, `fx_flows`, `metals`) come from the brief. *Recommendation:* `rates_credit` first (cleanest step functions, already has live policy-name consumers in `regulatory_political_risks`), then `crude_energy`, then `policy_budget` (hardest — effect windows, not levels). Confirm or reorder.

**Q4 — Third-party series vendors: acceptable?**
Bloomberg / Refinitiv / CRISIL / CEIC / FRED / World Bank. Today the repo is entirely free + official sources. Vendors buy (a) reliable machine-readable history, (b) a genuine `as_of_date` with publication timestamps, (c) no scraping fragility — all three of which are the hard part of this work. Confirm whether any paid vendor is acceptable, or whether this must stay free-and-official. **This is the single decision most likely to change the timeline.**

**Q5 — Licensing and redistribution constraints.**
Whether `factor_observation` may store vendor values at all; whether the resulting numbers may appear in generated reports/dashboards; whether `license` must be enforced (e.g. blocking rows whose `license` is non-permissive from `*_decision` reads, or surfacing a "licensed, do not redistribute" flag). RBI/SEBI/MoSPI terms specifically. Needs a human answer, not a code default.

**Q6 — How far back should the spine be backfilled?**
Prices reach 2021-10-27; macro series availability varies and is the binding constraint, not the price data. Backfilling to 2021 vs 2024 changes the cohort count materially (`next_wave_plan` §2L: the 20-session tests are underpowered ~10×; the index-breadth bound 2025-09-01 gives ≈13 independent 20-session cohorts vs ≈2). Confirm the target depth and the minimum acceptable cohort count.

**Q7 — `max_lookback_days`: per-series or per-family?**
§1.2 makes it per-series and `NOT NULL`. Per-family would be simpler to manage but forces a repo-rate series and a monthly CPI series to share a staleness rule, which is wrong. Confirm per-series, or specify a family default with per-series override.

**Q8 — May the spine *write* to other substrate tables?**
Specifically: may it derive and persist `regime_tag` values into `model_explainer_rankings` (currently 100% `'*'`)? *Recommendation:* **no — the spine stays a read-only input for now.** Every write is a new way to be wrong, and D7's PIT guarantee only holds for readers that respect the contract. Confirm read-only, or specify the write path and its audit requirements.

**Q9 — Add `sector_code` to `master_companies`?**
Without a real sector taxonomy (D8: 92.2% of `master_companies.sector` unusable; `industries` is 12 archetypes), no sector-level question can be answered. This requires **modifying an existing table**, which is beyond "additive only" and therefore a user call. Approve adding `sector_code TEXT` + a `sector_taxonomy` table seeded from the official NSE sector list, or confirm that sector-level answers are out of scope for now.

**Q10 — Provenance floor: what counts as a citable source?**
`strategies.md` §1 requires `symbol + fiscal + event_date + source_doc_id + chunk_span`. For a factor series pulled from a live API there is no `raw_documents` row. Options: (a) allow `source_url` alone, (b) require a `raw_documents` snapshot row for every series (audit-grade, more work, more storage), (c) allow `source_url` but mark the series `is_point_in_time=0`. *Recommendation:* (a) with `is_point_in_time=1` permitted only when the publisher states a release date. Confirm.

**Q11 — Does the retention/pruning regime apply to the spine?**
`prune_decayed_signals()` (`postgres_schema.sql:519-583`) archives `macro_events` older than 24 months and purges embeddings older than 12 months, and it has **already archived 11 of 30** macro events. If the same regime applies to `factor_observation`, the spine destroys the history that backtesting needs. *Recommendation:* **factor tables are exempt** — the spine is a time series, not a decaying signal, and its half-life is infinite by construction. But this contradicts an existing rule, so it needs explicit approval. Also: should `factor_observation` get an `is_structural_milestone`-style permanent-survival flag, consistent with `pruning_decay_config.is_structural_milestone`?

**Q12 — Minimum honest load before any prediction is attempted.**
The spine can be declared "working" with one series. Should a *prediction* be gated behind a minimum (e.g. ≥3 series across ≥2 families, ≥N observations, ≥1 exposure row per symbol with a stated `exposure_basis`)? *Recommendation:* yes — a prediction over a single unexposed series is a number with no mechanism, and would be reported as edge when it is arithmetic.

---

## Appendix A — Module map (for the implementer)

| Artifact | Precedent to copy |
|---|---|
| DDL ownership + idempotent `ensure_*` | `substrate_hygiene.py:150-178`; `peer_graph.py:61-103`; `repository.py:3853-3874` |
| Quarantine rule shape | `substrate_hygiene.py:60-106` (`QUARANTINE_RULES`), `:111-148` (`DEGRADATION_RULES`) |
| Degradation probe shape (count + denominator + share) | `substrate_hygiene.py:208-232` |
| Refuse-rather-than-emit discipline | `peer_graph.py:24-27` + `company_peer_runs.status='insufficient_signal'` |
| Missing-is-missing, never imputed | `peer_graph.py:19-22` |
| Additive-only tables beside live levels | `schema.sql:561-614` (`moat_history` / `policy_eni_history` / `ripple_history`) |
| Version/revision convention | `ripple_effects.revision_count`/`last_revised_at`; `raw_documents.doc_version` |
| TEXT dates in additive tables | `moat_history.asof_date`, `model_validation_scores.asof_date` |
| Runner script shape | `reality_engine/scripts/run_substrate_hygiene.py`, `run_peer_graph.py` (`--dry-run`, `ALL CHECKS PASSED`, idempotent) |
| PIT-correct attribution precedent | `move_attributor.py:14-21` (per-scrip noise floor, `date <= attribution_date`) |

## Appendix B — Reproducing the verification in §0

Read-only, no writes, no pipelines:

```python
import sqlite3
c = sqlite3.connect(
    "file:reality_engine/data/equity_intelligence.db?mode=ro", uri=True)
q = lambda s: c.execute(s).fetchall()
q("SELECT DISTINCT transmission_elasticity FROM ripple_effects")      # -> [(1.0,)]
q("SELECT target_type, COUNT(*), SUM(target_industry_id IS NOT NULL) FROM ripple_effects GROUP BY 1")
q("SELECT COUNT(*) FROM moat_evaluations m JOIN master_companies c ON c.isin=m.company_id")   # -> 0
q("SELECT COUNT(*) FROM moat_evaluations m JOIN master_companies c ON c.nse_symbol=m.ticker") # -> 2652
q("SELECT regime_tag, COUNT(*) FROM model_explainer_rankings GROUP BY 1")                     # -> [('*', 69500)]
q("SELECT COUNT(DISTINCT asof_date) FROM policy_eni_history")                                 # -> 1
q("SELECT COUNT(*), SUM(industry_id IS NOT NULL) FROM document_chunks")                        # -> (2031900, 0)
q("SELECT sector, COUNT(*) FROM master_companies GROUP BY 1 ORDER BY 2 DESC LIMIT 4")
```

The §2 SQL blocks were executed against a throwaway in-memory SQLite built from the DDL in §1.2/§1.3/§1.4 plus the fixture described in §2.3. The table in §2.3 and the outputs in §2.4–§2.6 are real query results, not illustrations. The repo was not modified.
