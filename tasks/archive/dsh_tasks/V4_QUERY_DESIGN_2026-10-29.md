# Task — v4 design: factored concept registry + algorithmic query engine + discovery layer

(Rewritten 30 Oct 00:40 IST by Wolf after Shivam's design review. This replaces the 29 Oct version.)

## Why
- The pilot gate is 27/2,681 strict (1.0%). The target is ≥95%.
- Nearly every failure is a COMPOSITION failure, not missing data. Counts from `tasks/answer_bench/GATE_RESULTS_*_strict.jsonl`:
  - `ask_match`: 2,884;
  - "sub-question N not addressed": 2,708;
  - "unrelated rows": ~1,500;
  - blocked + NOT_IN_DATA: only 383 + 132.
- Patching planners with aliases has plateaued.
- Shivam's direction:
  - answers come from **pure algorithmic computation over the database design**;
  - the LLM only synthesises at the last step and suggests new links to test;
  - the registry must be **as small as possible**;
  - the same machinery must find **2nd/3rd-order links people miss**;
  - it must stay fast as data keeps arriving for every company.

## Inputs
- `tasks/STATE_FOR_ANY_AI_2026-10-29.md`, `tasks/arch_v3/QUERY_LAYER.md`, `tasks/arch_v3/SPEED_PLAN.md`
- `tasks/SCHEMA_FINAL_2026-10-29.{md,sql}`, `tasks/SCHEMA_FINAL_CASES_2026-10-29.jsonl`, `tasks/pilot_b/cases_pilot_b.jsonl`
- `tasks/master_bank/MASTER_BANK.jsonl`: 1,073 cases; `question` text, `rubric`, `chain`
- `tasks/answer_bench/GATE_RESULTS_*_strict.jsonl`: failure reasons
- `reality_engine/query/*`: router, decompose, planners, gate, answer
- `tasks/HYPOTHESIS_REGISTER.md`, `tasks/PRICE_SIDE_DIFFUSION_STUDY_2026-10-03.md`
- Pilot stores, read-only, on the C: SSD only: `reality_engine/data/pilot/pilot60/*.db`. Note that `facts_pilot.company_metric_series` (1.06 M rows) is already long-format.

## Write
- `tasks/arch_v4/QUERY_V4_DESIGN.md`: the design (sections A–H below).
- `tasks/arch_v4/build_concept_registry.py`: the generator.
- `tasks/arch_v4/concept_registry.json`: the generator's output.
- `tasks/arch_v4/registry_coverage.md`: coverage + the size-vs-coverage curve.
- `tasks/arch_v4/bench_screen.py` + `tasks/arch_v4/bench_screen.md`: the measured CPU benchmark (section F).

## Design sections

### A. Factored registry: atoms, never composed concepts
A question is `operator(atom | formula, dims, window, entity_set)`. For example, "SBICARD's YTD high in 2026, with the date, on which exchange" = `max_with_date(price.high, window=YTD 2026, entity=SBICARD, exchange=each)`.

The registry is five small tables, all GENERATED (hand-check only the lexicon):
1. **atoms:** a raw measure → store, table, column, unit, grain (day/quarter/FY/event), entity key, PIT column (`known_at`), coverage. Target: tens of rows.
2. **dims:** qualifiers that live ON an atom, not as new concepts:
   - exchange {NSE, BSE, each, sum};
   - basis {raw, adjusted};
   - {consolidated, standalone};
   - holder class {promoter, public, FII, DII, …};
   - segment.
3. **formulas:** derived measures as expressions over atoms (margin, growth, ratios, YoY/QoQ). They are never stored as data.
4. **operators:** a closed set (~25), each a parameterised SQL/array template:
   - value_at, change, pct_change, max/min_with_date, rank, screen/filter, compare;
   - lag_between, event_window_return, first_visible (by `known_at`);
   - zscore, count, correlate;
   - named deterministic judgement rules (gap type, breakout, …), each with its stated rule.
5. **lexicon:** surface word/phrase (English + Hinglish) → atom | operator | dim value | entity selector | period.
   - Mine it from bank question n-grams matched against column names and `xbrl_concept_map`.
   - Output a hand-check list.

**Minimality rule:** a new entry is allowed only if a case cannot be written with the existing ones, and an operator is preferred over an atom. The generator prints a **registry-size vs cases-covered curve**, and the design states the size at which coverage reaches 95%.

Every case must map, or be listed with the reason it doesn't.

### B. Database shape that removes most planner code
- **One long-format fact view:** `(entity_id, atom_id, dims, period_start, period_end, value, unit, known_at, source_ref)`.
  - It is a UNION of views over the existing stores (market, holding, OI, commodity, XBRL, metric series). No data copy where a view will do.
  - PIT is one filter everywhere: `known_at <= as_of`.
- **Entity-set membership table**, with validity dates: sector/industry PIT, index membership, market-cap bucket, theme. "Which sugar companies…" becomes a join.
- **Typed claim table** for narrative sources: `(entity, topic atom, direction, magnitude, horizon, known_at, page_ref)`.
  - Filled at ingest by the existing extraction, so at query time it is a lookup.
  - Map which existing extraction tables feed it.
- **Exposure edge table** (shared with section E).
- State which existing tables become views, which need new columns, and the migration order.

### C. Ask contract + text-only decomposer
- A typed `Ask` holds: entities + level, window(s), `as_of`, and **parts**. Each part has: atom/formula, dims, operator, output shape, judgement flag.
- The decomposer is lexicon slot-filling + entity resolution + the existing period parser (`period_bounds`).
- **Bank fields (`template`, `family`, `chain`, `period`) are NOT inputs**; they are used for evaluation only.
- When the text is ambiguous, emit all readings instead of guessing.
- **Evaluation:** per-part precision/recall against `rubric`/`chain`. It needs ≥97% on parts for the 95% end-to-end gate to be reachable. It runs without any DB.
- Include 20 worked examples from failing cases: MB0234, MB0280, MB0125, MB0996, MB0003 + 15 more spanning stock, sector, ripple and judgement cases.

### D. Executor + answer contract
- **One executor:** operator template + WHERE on the fact view. It returns **exactly one result per part**: value(s), unit, period, ISIN, source, `known_at`, OR NOT IN DATA with the registry's reason. No extra rows.
- **Special engines,** each kept small: text-claim lookup, graph walk (section E), event study.
- Map the current 8 planners onto this: what is deleted, what survives as an engine.
- **Renderer:** one block per part. The strict grader checks part coverage against the `Ask` directly.
- **The LLM's role (last step only):** prose synthesis, connections across parts, "look next" suggestions. It never sets a number or promotes a link.

### E. Discovery layer: 2nd/3rd-order links people miss
The same atoms, run as a search instead of a fixed plan. Tables:
- `edge(driver, target, origin {measured | text | llm_proposed}, strength, lag, n, fdr_q, stability_by_window, label, known_at, last_tested)`.
  - Labels: verified / measured_weak / plausible_untested / contradicted.
  - **Nothing is dropped; the grey area stays visible with its label.**
- `attention(entity|topic, day, mention_count by source)`: from our own documents. A high-impact path with low attention = what others missed.
- `hypothesis(proposed link, proposer, required test, status)`: feeds `tasks/HYPOTHESIS_REGISTER.md`.
- `reaction_lag(event, hop, entity, first_price_response_day)`: does hop-2 reprice late? This is the diffusion study, per hop.

Mechanisms to specify:
1. Measured links from driver series × company atoms (lagged, out of sample).
2. Paths = sparse matrix powers (A², A³) of the weighted, lagged edge matrix, pruned below a threshold after each multiply.
3. Attention-gap ranking.
4. Reaction-lag per hop.
5. Say-vs-do: claims vs later actuals, giving a management credibility score.
6. Edge breaks / regime change.
7. Analog search over past cycles.

Guards:
- false-discovery-rate correction across all tests;
- out-of-sample check;
- a mechanism is required for "verified" (a typed path, not correlation alone);
- every edge carries the date it became knowable, so discovery itself can be backtested without hindsight.

Propose ~20 discovery-type questions for the bank as fixed regressions (proposal only; Shivam approves before they enter the bank).

### F. Engine: fast at scale as data keeps arriving
- **Factor stripping first:** residualise company series on ~10–20 common factors (market, sector, rates, INR, commodity groups) before testing links. Correlated "n factors" collapse into a few latent ones.
- **Mechanism gate:** expensive tests run only on pairs connected by a typed link (cost share, segment mix, supplier/customer from text, policy target, membership). The cheap screen still sees everything, so a strange factor can enter the grey area only after passing the false-discovery correction.
- **Hierarchy:** test sector aggregates first, then drill into companies only where the sector link holds.
- **Shock-first walk:** when a driver moves >2σ, beam-search outward from it (top-k per hop, ≤3 hops).
- **Incremental, never recompute:**
  - per-edge running statistics (counts, sums, cross-products per lag);
  - new rows update them at a cost proportional to the new rows only.
- **Dirty propagation** (like a build system): a new filing marks only the dependent features, edges and paths stale.
- **Three tiers with budgets:**

  | tier | when | what | budget |
  |---|---|---|---|
  | hot | query time | lookups, stored edges, beam walk | <2 s |
  | warm | nightly incremental | features, stale edges, attention, reaction lags | minutes |
  | cold | weekly, off-peak | full re-tests, false-discovery pass, new candidates, LLM link proposals, regime scan | hours, capped |

  The cold tier is ordered by expected value (impact × low attention ÷ test cost).
- **Storage:**
  - Fact and feature tables in DuckDB/Parquet, partitioned by atom and month, append-only.
  - Edges, paths, hypotheses and the registry are small and hot: in-RAM sparse arrays, saved to disk.
  - Everything hot or warm on the C: SSD. D: (HDD) gets only finished archives, written sequentially.
- **GPU:** Shivam has given the GPU for this. It is a GTX 1050 Ti, **4 GB VRAM**, CUDA. System Python has no torch/cupy today. Specify:
  - which steps are dense/sparse matrix work (screen, lagged correlation, A^k);
  - VRAM tiling so each batch fits in ~3 GB;
  - fp32;
  - a CPU fallback;
  - the install needed (cupy-cuda12x or torch). **Do not install anything in this task; just name it.**

  The GPU is used where a measured benchmark beats CPU. On this card GPU OCR lost to CPU, so measure, don't assume.
- **Measured CPU benchmark** (`bench_screen.py`, numpy only, read-only):
  - On the pilot universe, build standardised daily returns (T × N) and a driver matrix (T × D) from held series.
  - Time one lag of the full screen and 10 lags.
  - Time A² and A³ on a synthetic sparse edge matrix sized to the full universe (~2,000 × ~500).
  - Report the RAM peak.
  - Extrapolate to the full universe.

  Proposed acceptance targets for the build phase (confirm or correct them from the measurements):
  - full daily screen < 5 min;
  - nightly incremental < 10 min;
  - shock walk < 2 s.

### G. Maintenance
- Ingest is idempotent.
- `known_at` is checked against the filing record on arrival; data-quality checks pass before anything is marked stale.
- A new atom = one registry row + one view, with no planner code.
- The registry and the schema are versioned together.

### H. Work packages
3–4 packages, each with disjoint files and an acceptance test:
1. Registry generator + lexicon.
2. Fact view + entity sets + claim/edge tables.
3. Decomposer + its evaluation.
4. Executor + answer contract + renderer + grader alignment.

Then a discovery/engine package after the gate passes. For each package, estimate the gate gain from the failure-reason counts.

**Data gaps:** list exactly which cases still fail because the data is absent (needs the 211-case fetch stream). The gate's 95% depends on them.

## Rules
- Read-only on all data; never read a DB from D:.
- Write only `tasks/arch_v4/*`.
- No planner code changes, no installs, no paid models.
- Run the benchmark under `.tmp/ram_guard.ps1` if it exceeds ~2 GB.

## Acceptance checks
- `python tasks/arch_v4/build_concept_registry.py --check` writes the registry and prints:
  - coverage over 1,073 cases (mapped / NOT IN DATA with reason / unmapped);
  - registry size per table;
  - the size-vs-coverage curve.
- `python tasks/arch_v4/bench_screen.py` prints the measured timings and RAM peak.
- `QUERY_V4_DESIGN.md` has sections A–H plus the 20 worked examples.

## Test command(s)
```bash
python tasks/arch_v4/build_concept_registry.py --check
python tasks/arch_v4/bench_screen.py
```

## Report
- Registry size per table, and the size at 95% coverage.
- Coverage numbers.
- Decomposer evaluation plan.
- Benchmark timings + extrapolation, and which steps go to the GPU.
- Work packages with estimated gain.
- Data-gap case list.
- Open questions for Shivam.
- Tool-call count.
