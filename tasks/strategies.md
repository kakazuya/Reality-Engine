# Strategies Document — Reality Query Engine → Quant Labels + Explanatory Power

> Purpose: extract all relevant information from collected data into a quant DB with labels that show the economy before prices do. This doc lists **candidate label strategies** and **how explanatory power gets measured later**. It does NOT promote any leg.
> Authority: `tasks/CURRENT_PLAN_2026-09-27.md` is the only execution authority. `tasks/strategy_tracker.md` verdicts (F1/F2 KILL, REVOKED list, promotion bar) still stand. Prior `plan.md` / `todo.md` / `desk_*` / `verification_*` are historical. Capital PARKED, paper only.

## 1. Ground rules (non-negotiable)

- Raw ≠ substrate. Chunks, AR text, concall prose are audit/replay only. A label counts only when quantized into a queryable row with provenance: `symbol + fiscal + event_date + source_doc_id + chunk_span`.
- Honest-NULL over synthesis. If a quantified split is absent, return NULL. NEVER synthesize ₹cr / % from `qualitative_notes`, driver lists, or keyword-hit counts.
- Trust layer first. Exclude `*_demo` / `seed_*_demo` tables wholesale + all `substrate_quarantine` keys (`SELECT DISTINCT table_name` currently: `graph_nodes, graph_causal_edges, macro_events, master_companies, ripple_effects`; NTPC/INE733E01010 = 0 rows) on every inference read.
- Fiscal/event discipline: `fiscal_confidence >= 0.5` + real `event_date`. Never substitute one for the other. Headerless tables are not quotable (see §2).
- Single SQLite writer + queue lock; ingestion parked. These strategies are distillation/query proposals, not ingest orders.

## 2. Canonical lesson: NTPC revenue segments = honest-NULL

- `annual_financials / financial_metrics / business_model_profiles / company_distilled_parameters` have **no segment columns**. Distill keys are only `business_sensitivities / capital_allocation / cyclicality_profile / geopolitical_supply_chain / order_book_metrics`.
- `business_sensitivities` / `cyclicality_profile` (conf 0.91) list drivers only: thermal regulated capacity + PLF incentives, NTPC Green solar/wind/hybrid SECI conversion, captive coal + commercial mining, power trading + GH2 pilots. Qualitative only, no ₹cr / % by segment.
- BMP `Tollbooth / 82% / pricing 5` self-labels `"deterministic industry-mapping heuristic"` — seed, not evidence.
- Raw AR text exists but is NOT distilled: `doc_id=5673` (NTPC Integrated AR 2025-26), CH 285 defines 2 standalone reportable segments (`Generation of energy` vs `Others` = consultancy/PM/trading/oil-gas/coal-mining), CH 286 holds paired ₹cr values starting mid-row at `"supervision fee * 1,59,706.46 1,64,239.99 …"`. Sweep of CH 270–286 did not recover the header row (segment × FY26/FY25 order, standalone vs consolidated). Year/column assignment from CH 286 alone is unproven — do not quote as a split.
- Implication for the engine: segment extraction needs header-validated parsing, not keyword hits (76 `segment` hits ≠ segment financials).

## 3. Candidate label strategies (S1–S6)

### S1 — `segment_revenue` (Ind AS 108, header-validated)
Why: business mix shifts (Generation vs Others; thermal vs NGEL vs mining vs trading) move before consolidated PAT does.
Extract: `symbol, fiscal, segment, revenue_cr, result_cr, assets_cr, standalone_flag, source_doc_id, chunk_span, event_date`. Require header row proving segment × year order + standalone/consolidated scope. NTPC 5673 CH 285–286 is the acceptance test: parser must refuse CH 286 alone as headerless.
Leads economy when: Others/mining/renewables inflect while Generation looks flat.

### S2 — Daily market-cap series
Why: price × shares-out turns moves into capital-weighted reality; needed for attribution, event-study weights, and slippage priors. Currently skeleton/missing.
Extract: `symbol, date, close, shares_out, mcap_cr, source`. Provenance = price delivery date + corp-action-adjusted shares.
Leads economy when: mid/small-cap breadth diverges from Nifty price action.

### S3 — Suppliers / vendors / customers graph
Why: 2nd-order fwd/back supply chain finds who benefits more than the primary (the tariff/capex/commodity transmission bet). Tables exist as skeleton (`ripple_effects` ~76 rows).
Extract: `edge(symbol_from, symbol_to, relation, criticality, severity, source_doc_id, event_date)`. Validate `causal_engine` math (PN=∏Pi, MN=Raw×PN×β, S=|MN|×20/(1+ln(1+Lag))) on steel-duty + textile-tariff cases before trusting β.
Leads economy when: input-cost / order-book shocks propagate (coal linkages, rail freight, modules, DISCOM payments).

### S4 — Event-study abnormal returns
Why: raw moves lie; market-model (Nifty beta) abnormal returns isolate the residual worth explaining. Directly feeds T2 "levels GATE, flows VOTE".
Extract: `symbol, event_date, window, expected_ret, realized_ret, abnormal_ret, beta, model`. Store per event (results, guidance, policy, auditor, promoter signal), not per day.
Leads economy when: attribution dates cluster abnormal moves by sector/regime before consensus reprices.

### S5 — Growth expectations (guidance levels + changes)
Why: concall/AR guidance diffs (capex, CUF, PLF, SECI conversion, 60 GW pipeline) are the closest thing to a forward label. N200 concall gate: chunk `doc_ids` directly (never corp ids), event trio + `fiscal >= 0.5` + guidance text + FTS/embed (2,927-row pilot).
Extract: `symbol, fiscal, metric, guided_value, prior_value, change, source_doc_id, chunk_span, event_date`. Evasiveness/tone is a separate lens, not a substitute for numbers.
Leads economy when: raises/cuts anticipate earnings revisions.

### S6 — Quarterly-table audit + industry coverage
Why: 4+ quarters × 200 N200 symbols is the minimum dense substrate for any panel test; industry coverage on chunk rows (not just masters) proves the substrate can support sector answers.
Extract: quarterly financial rows with fiscal/event provenance; chunk-level industry non-NULL rate on N200 chunks. Report degradation alongside answers (constant features, template-less policy coverage, single-country splits, unconditional `regime_tag='*'`).
Leads economy when: sector panels go from sparse anecdote to queryable history.

## 4. Explanatory-power protocol (how models earn weight later)

Each strategy plugs in as a competing peer lens. Universal test, no exceptions:

- Persist: `model_explainer_rankings(stock_id, sector_id, geo_id, regime_tag, investor_majority, lens_family, p_value, explain_power, rank)` + `lens_activation_log(temperature, fired_lenses)`. Rank per stock / sector / geo / time+conditions + investor-majority (promoter/FII/DII/retail) — dominant explainer differs by who drives price.
- Promotion bar (all required, per horizon 30/90/180/365, weekly cohorts): cohort-clustered mean ≥ +500bps net of measured costs; ≥30 cohorts (≥13 for 20D); hit-rate CI lower > 0.5 cluster-robust; same sign in both regimes; shuffle-entry placebo ≈ 0 (|≤100bps).
- Calibration `recommend_apply` gate respected; `applied:false` is a healthy refusal, not failure. F1/F2 KILL + REVOKED legs never re-quoted as edge; reopen needs pre-registration (split-adjusted prices + matched-volatility placebo), never silent re-run.
- Degradation reported with every answer: quarantine exclusions, constant-feature drops, coverage gaps. `peer_graph` rule applies: drop near-constant features, refuse neighbours below `MIN_ACTIVE_FEATURES` (log refusal in `company_peer_runs`), never impute missing → zero.

## 5. Test universe (diverse N200, verified `is_nifty200=1`)

RELIANCE (Oil/Gas LARGE), HDFCBANK (Financials LARGE), INFY (IT LARGE), M&M (Auto LARGE), NTPC (Power LARGE), LUPIN (Healthcare MID), DABUR (FMCG MID), SAIL (Metals MID), IRCTC (Consumer Services MID), BHEL (Capital Goods MID). Use for S1–S6 pilots before any universe-wide claim.

## 6. Status

PROPOSED, not started. Ingestion stays parked. Next: S1 header-validated parser spec + S6 quarterly/industry coverage queries, then S2/S4/S5 pilots on the 10-stock universe. Update this doc after every label test (extract spec + coverage + explanatory-power read + what improves it next).

## 7. Forensic audit probes (fraud + investing edge cases, answered 2026-09-27)
> Cost: 5 indexed queries, ~6ms wall, read-only. Verdicts below are evidence counts, not model outputs.

### Answerability map (corpus-wide)

| # | Probe | Verdict | Evidence |
|---|---|---|---|
| F1 | Cash follows profit (OCF/PAT, FCF) | NULL-gated | OCF/FCF zero-filled corpus-wide; no cash-flow table exists |
| F2 | Receivables vs revenue (channel stuffing) | NULL-gated | No receivables column; NTPC AR CH171 text-only (₹30.8k cr) |
| F3 | Accrual quality (Sloan/Dichev) | NULL-gated | Needs F1 inputs |
| F4 | Promoter pledge dynamics | NULL-gated | `promoter_pledge_pct=0.0` 4,284/4,284 — unfilled default, not clean |
| F5 | Insider PIT vs tone | BLOCKED | `insider_trades` 0 rows corpus-wide (schema ready) |
| F6 | Related-party leakage | NULL-gated | `related_party=0.0` 4,284/4,284 — unfilled, not clean |
| F7 | Auditor qualify/resign/rotate | NULL-gated | `auditor_name` NULL 4,284/4,284; NTPC Sep-2026 auditor-change sits in chunks unextracted |
| F8 | Altman/Beneish/Piotroski | NULL-gated | Altman 3.2 on 3,473/4,284 (flat fill); Beneish/Piotroski need missing inputs |
| F9 | Bulk/block front-run | Thin but live | 228 rows / 44 symbols; NTPC 0 |
| F10 | Delivery spike × abnormal returns | Half-live | Delivery % present (1,269 NTPC rows); S4 abnormal-return layer missing |
| F11 | Dividend reality (payout vs OCF) | NULL-gated | Dividend actions live (NTPC 10, IRCTC 9, HDFCBANK 5); `dividend_yield_pct` garbage 443/4,284 rows >100 (NTPC 375, INFY 464) — never display; OCF missing |
| F12 | Solvency-gate honesty | Suspect input | Gate runs but IC input is the flat-8.5× fill |

### What IS scorable today (10-stock probe, FY24→FY26 + actions)

- Promoter dispersion: DMART 78.9 / DLF 74.1 / SAIL 65.1 / IRCTC 62.4 / BHEL 59.8 / NTPC 54.0 / RELIANCE 51.8 / LUPIN 47.0 / INFY 16.5 / HDFCBANK 0.15 (bank — dispersed by design).
- D/E + margin trend: NTPC 1.48→1.33 with OPM 31.5→33.3 / NPM 11.8→14.7; LUPIN turnaround OPM 19.8→31.5 / NPM 9.7→19.4 with D/E 0.2→0.29; BHEL recovery OPM 5.3→9.9 / NPM 1.2→5.0, D/E 0.36→0.31; DLF delevered 0.12→0.01 with NPM ~55 (reval-driven, not operating); DMART D/E 0.03→0.10 creep while NPM 5.0→4.3 fades — the one negative operating drift in the set.
- Dividend actions: NTPC 10 / IRCTC 9 / HDFCBANK+SAIL 5 / rest 4. Distribution intent visible; funding honesty needs OCF.
- FII/DII present and varying (HDFCBANK 36.7/24.5 … DMART 8.1/5.4) — usable as investor-majority conditioning inputs.
- NTPC promoter mismatch: forensic 54.0 vs AR Note-23 President-of-India 51.10 — provenance open, do not average.

### Forensic build list (ordered by unlock)

1. Cash-flow + balance-sheet ingestion → F1–F3, F8-inputs, F11, F12-honesty.
2. `insider_trades` fill (schema ready, 0 rows) → F5, highest fraud-signal-per-row.
3. Auditor fee/tenure + RPT notes → F6, F7.
4. S4 abnormal returns + bulk/event join → F9, F10.
5. Pack-gated forensic scoring (never uniform) → F8, F12.

Rule: every forensic flag ships with its named false-positive control (DISCOM-structural dues, ESOP-sale filter, group-synergy vs siphon, captured-auditor fee join, expiry-flow filter). A flag without its control is a rumor, not a label. Forensic probes double as SELL-leg fuel (backlog item 1: Beneish/accrual veto) — each carries lens_family + per-pack control before any §4 promotion.

## 8. Munger lattice → watchlist rule (answered 2026-09-27)

Twelve models mapped to substrate: incentives (promoter/pledge/SBC — pledge NULL-gated), circle of competence (pack whitelist, live in `n200_valuation.allowed`), base rates (pack tables from resolved cohorts — pending), margin of safety (multiple + cycle flag — cycle pending S4), compounding vs parked-cash hurdle (PEG-guarded, 107 N200 rows live), inversion kill-flags (all NULL-gated → gate OPEN, no avoidance credit claimed), second-order ripple β (skeleton 76 rows, unvalidated), temperament (F1/F2 KILL encoded), checklist/journaling (promotion log), lollapalooza confluence (T6 gate), skin-in-the-game PIT (blocked), via negativa quarantine+NULL discipline (live).

Watchlist rule: track = (a) substrate-complete (196/200 N200) + (b) no kill-flag + (c) live compounding/dislocation thesis with falsifier. Status: (a) holds; (b) provisional — forensic scaffold NULLs mean inversion gate is open for ALL names, everything stays monitor-only until cash/PIT/auditor fill; (c) shaped but unpromoted (LUPIN turnaround, BHEL trough, NTPC compression). Moat/culture/management-quality stay qualitative distill with confidence, never a number.
## 9. Fix + trial-run learnings (answered 2026-09-27)

> Fixes applied to `/tmp/n200_valuation.db` (8ms): bank EV banned (31 rows nulled — money is inventory), P/E gated to eps>0 (4 negatives nulled: GMRAIRPORT/PAYTM/SWIGGY/IDEA). Coverage now 200 rows: 144 P/E, 114 EV-gross, 107 PEG. PEG already guarded (NULL unless cagr>0; BHEL −9.8 → NULL correct).

> Trial run, 10-stock universe, 17ms wall (~0.4–3.3ms/symbol, 8 indexed counts each): every name has 4–5 FYs + 1,269 price rows + forensic row + dividends; quarterly 3–7 rows; PIT 0/10; bulk 0/10. Adjust-held: RELIANCE (BONUS), HDFCBANK (BONUS), INFY (BUYBACK) — multiples NULL pending split-adjust; M&M clean (no adj, P/E 25.9×, PEG 2.18).

> Trial valuations (FY25 EPS × 2026-09-24 close, EV gross cash=NULL): NTPC 13.5×/9.4×/PEG 0.76; LUPIN 29.3×/PEG 0.17 (turnaround); DABUR 38.8×/PEG 21.5 (growth near zero — PEG correctly screams); SAIL 32.1×/9.7× (mid-cycle, not cheap); IRCTC 28.1×/PEG 1.95; BHEL 271×/87× (trough earnings — cyclical-inversion trap live); M&M 25.9×.

> Learnings for all-stock scripts: (1) never reuse one kernel conn across a failed write — stale tx locks the /tmp DB (bg_27 + lock cascade; fix = close/rollback, fresh conn, 8ms); (2) Apr-1 FY step is provisional until declare-date table exists — TTM from 4 consecutive quarters is the ship rule; (3) split/bonus-adjuster frees 49/200; (4) INFY unit-gate ($-scale) before multiples; (5) `q.total_changes` doesn't exist on cursors — count first, then update.




