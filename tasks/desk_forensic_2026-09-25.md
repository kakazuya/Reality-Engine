# Desk — Forensic + risk + tax edge (2026-09-25)

> Scope: design-only. This file is the deliverable. No schema change, no
> repository edit, no backfill, no live-row delete, no new packages. Every
> rule below is implementable as **read-only SELECT over existing tables**
> with quarantine joins on reads. Vetoes are BUY-blocks / SELL-support, never
> standalone SELL triggers, and never touch SELL term framing (P0 invariant
> stands).

Ground truth: `tasks/SESSION_HANDOVER_2026-09-25.md` +
`tasks/test_findings_2026-09-24.md` §§1–14 + `tasks/strategy_tracker.md` +
`tasks/next_wave_plan_2026-09-23.md` §5 promotion bar. P2 intent: §8 P2 +
tracker P2 (Beneish/Altman/Piotroski + accrual quality, pure SQL over
existing financials, feeds the SELL leg). Solvency gate: AGENTS.md §11.

**Correction note (same-day, live-verified):** placeholder-zero probing
changed the feasible set. `operating_cash_flow` is 0 on 95.2% of non-null
annual rows (only 583/13,015 nonzero, 134 isins); `interest_coverage` is the
constant 8.5 auditing (1 distinct value); forensic `interest_coverage_ratio`
is 8.0-or-0 only; `roce_pct`/`roe_pct` are 0 on ~94% of rows. Accrual/IC/ROCE
legs therefore move to narrow-coverage or blocked status below — the broad
gate is built from columns verified real (revenue, NI, EBITDA, opm/npm sane,
debt/equity, forensic DE). Nothing in §§4–7 reads a placeholder as signal.

---

## 0. Contract and non-goals

- **Write target:** this file only. **Non-goals:** no schema edits, no new
  tables, no migration, no writes to the live DB, no new packages.
- **Read-only discipline:** single SQLite reader; queue lock respected; never
  co-run with GPU/DB jobs. All SQL in §13 is SELECT-only and SQLite-dialect.
- **Quarantine on every read** (AGENTS.md §13): financials rows keyed to
  synthetic masters must be excluded. Live-verified 2026-09-25:
  `substrate_quarantine` = 1,377 rows, of which `table_name='master_companies'`
  = 1,356 keys shaped `INE_AUTO_*` (`row_key` = isin). Joined impact:
  **2,191 annual + 2,282 quarterly rows** sit on `INE_AUTO_*` masters and must
  be filtered (predicate in §13.0).
- **REVOKED artifacts guard:** nothing here reframes SELL terms, re-seeds the
  book, blends positional pnl with HOLD agreement, or re-introduces the
  confirmation filter / trend entry. SELL ⇒ `target < entry < stop` stays
  untouched; veto output is a flag column consumed by thesis-gating, not by
  the exit layer.
- **Fail-closed:** missing forensic inputs ⇒ abstain (HOLD), never pass. This
  deliberately differs from the `quality_intact` fail-open noted in
  next_wave §2H — the forensic layer closes that hole for the names it covers.

## 1. Capital frame

- **Book:** ₹10cr cash, October 2021, no assumed inflows. May hold
  cash / listed gold ETF / listed silver ETF up to a combined **40% buffer**
  when equity exposure is not ROI-positive (§11).
- **SIP-frame note (no conflict):** the reconciled SIP benchmark (₹1L on
  2021-10-27 + ₹50k/month → ₹30.5L in; post-tax XIRR 7.06%;
  `sip_signal_legs_post_tax_2026-09-24.json`) remains the measurement harness
  for signal legs. Its engine (FIFO lots, tax schedule, sector caps, monthly
  EOD rebalance) is **reused as-is**; the 10cr book inherits its cost/tax
  constants (§§9–10) but sizes positions in whole shares (fractional shares
  stay a backtest-only convention).
- **Costs:** 50bps round-trip impact prior + STCG/LTCG + STT + harvesting-aware
  turnover budget (§§9–10). Drawdown tolerance **40%** (worst observed 11.65%).

## 2. What the DB can and cannot support (live-verified 2026-09-25)

Verified-real columns (broad gate inputs): revenue (9,077 distinct NI values;
revenue sane), `net_profit_inr_cr`, `ebitda_inr_cr`, `debt_inr_cr`/`equity_inr_cr`
(nonzero 9,741/10,184), `debt_to_equity` (mean 0.85, max 220.6 — real),
`opm_pct`/`npm_pct` sane at |.|≤100 on ~96% of rows (3.8% extremes excluded by
sanity filter), forensic `debt_to_equity_ratio` (3,357 nonzero, mean 0.60 —
real), quarterly growth/margin columns (96% sane margins).

Dead / placeholder columns (verified — never read as signal):

- `annual_financials.interest_coverage` = **8.5 on all 12,170 non-null rows**
  (1 distinct value) → coverage axis dead in annuals.
- `company_forensic_health.interest_coverage_ratio` ∈ {8.0, 0} only (3,473 at
  8.0, 811 at 0) → Gate-0 IC leg fires only on placeholder zeros; no real
  coverage information exists anywhere.
- `operating_cash_flow_inr_cr` = 0 on **11,587/12,170 (95.2%)**; only
  **583 nonzero rows, 134 isins**, 87 latest-snapshot names quar-excluded, 313
  consecutive pairs with both-OCF-nonzero. Accrual legs are narrow-coverage
  only (§7 appendix), never broad vetoes.
- `free_cash_flow_inr_cr` = 0 on 95.6% → dead.
- `roce_pct`/`roe_pct` = 0 on ~94% (748/800 nonzero) → dead as broad inputs
  (nonzero slice usable only as SELL-support ordering, never a gate).
- `company_forensic_health.altman_z_score` = 3.2 constant → never read.
- `promoter_pledge_pct` = 0 all 4,284 rows → pledge leg never fires (§8 blocked).
- `auditor_name` all NULL; `has_qualified_audit_opinion` = 0 all rows;
  `related_party_tx_pct_revenue` = 0.0 all rows → auditor/RPT legs dead.
- Missing entirely: receivables, inventory, payables, current assets/
  liabilities, total assets, retained earnings, COGS/gross profit,
  depreciation, SG&A, shares outstanding → full Beneish-8, full Altman-Z,
  full Piotroski-9, CCC drift, Dechow-Dichev not computable (§§4–7 label every
  substitution; nothing is faked).

Measured base rates (quarantine-excluded, FY26 ceiling; n=2,116 latest
consecutive pairs / 2,961 latest snapshots unless stated):

- NI<0: **11.8% of pairs, 534/2,961 snapshots (~18%)** → viable BUY-veto rate.
- DE>1.5 (annual): **8.9% of pairs** (1,204 rows all-FY) → viable.
- SGI>1.5: **8.4%** → viable triple input.
- Margin collapse (Δopm<−2pp, sane): **26.8%** → FLAG-only alone.
- Leverage jump (ΔDE>+0.3 with DE>1.0): **4.8%** → FLAG, tight.
- Margin-collapse AND leverage-jump: **2.3%** → selective conjunction.
- Growth-without-margin (SGI>1.5 + margin collapse): **52/2,116 (2.5%)** →
  selective VETO.
- Loss + margin collapse: **129**; loss + DE>1.5: **31**; loss + SGI: **25** →
  high-conviction SELL-support conjunctions.
- F-5 score (feasible five, §6) dist: 0:110 / 1:333 / 2:336 / 3:357 / 4:569 /
  5:411 → ≤1: **443 (21%)** VETO band (of which NI<0: 171, DE>1.5: 30 —
  F-5 veto overlaps but is not redundant with F1/leverage legs); =2: 336 FLAG
  band; ≥4: 980 (46%) pass.
- Loss persistence (NI<0 two consecutive FYs): **147/2,116 pairs (7.0%)** →
  selective F7 upgrade, not a broad veto.
- Cash subset (real-OCF only): 87 latest names, 313 pairs — deep-dive
  appendix, not a gate (§7).
- Quarterly corroboration coverage: **2,944 latest-quarter names**
  quarantine-excluded (45-day lag) — §13.4.

## 3. Veto architecture

Two gates in series, both fail-closed, evaluated point-in-time (§3.3):

- **Gate 0 — solvency (AGENTS.md §11, unchanged):** reject iff
  `promoter_pledge_pct > 15 OR interest_coverage_ratio < 2.5 OR
  debt_to_equity_ratio > 1.5`. Live bite: 1,026/4,284 (24%), but the IC leg
  fires only on placeholder zeros and pledge never fires — the only
  **informative** Gate-0 leg in data is **DE>1.5 (215 rejects, all
  DE-driven)**. Gate 0 stays exactly as-is; this spec adds Gate 1 beside it
  and reports overlap honestly (§12) rather than double-counting.
- **Gate 1 — forensic veto (this spec):** output per (symbol, asof) is one of
  `VETO` (hard BUY-block), `FLAG` (needs one corroborating FLAG on a
  different axis to become VETO), or `SUPPORT` (feeds the broken-thesis SELL
  leg as supporting — never sufficient — evidence). A lone `SUPPORT` never
  creates a SELL.

### 3.1 Rule table (all inputs verified-real; sanity filters in §13)

| ID | Name | Inputs (existing cols) | Output | Live bite |
|---|---|---|---|---|
| F1 | Loss-maker | latest FY NI<0 | VETO (BUY-block) / SUPPORT (SELL) | 12–18% — the primary BUY veto |
| F2 | Growth-without-margin | SGI>1.5 AND Δopm<−2pp (sane) | VETO / SUPPORT | 52 names (2.5%) — selective manipulator profile |
| F3 | Margin collapse | Δopm<−2pp AND Δnpm<0 (sane) | FLAG (VETO iff + F4/F5-weak) | 26.8% — never alone |
| F4 | Leverage jump | ΔDE>+0.3 with DE>1.0 | FLAG (VETO iff + F3 or F5-weak) | 4.8% — tight |
| F5 | F-5 broad fail | F-5 score ≤1 (§6) | VETO / SUPPORT | 443 (21%) |
| F7 | Loss persistence | NI<0 two consecutive FYs | upgrades F1 SUPPORT→strong; single corroboration suffices for VETO | 147/2,116 pairs (7.0%) — selective upgrade |

VETO resolution: any VETO ⇒ BUY-blocked. Two independent FLAGs on different
axes (margin F3 / leverage F4 / F-5-weak F6) ⇒ VETO. SUPPORT feeds SELL-leg
evidence only alongside a broken-thesis clause. Cash legs (OCF<0, OCF<NI,
Sloan rank) live in the §7 narrow-coverage appendix and can only add SUPPORT
on the 87-name real-OCF subset — they never veto the broad book.

### 3.2 Why thresholds are set here

F1/F2/F5 vetoes fire on 2–21% of names — tight enough to preserve BUY breadth
while biting on the SELL leg's flagged names. F3 alone (27%) is deliberately
a FLAG: promoting it would block a quarter of the universe on margin noise
(3.8% opm extremes already filtered). Corroboration (§3.1 resolution) is the
mechanism converting common conditions into selective vetoes. F-5 pass bar
(≥4) and F2 SGI cutoff (1.5) are priors calibrated for bite, not fitted —
recalibration happens past the bar per §12.

### 3.3 Point-in-time discipline (PIT — mandatory)

Financials carry no `published_date`. Without a lag rule, FY rows leak the
future into past actions (next_wave §2M class of bug).

- **Annuals:** FY label `FYnn` (March year-end) usable only for
  `action_date ≥ Jun-01 of calendar year 2000+nn` (FY26 ⇒ from 2026-06-01).
  Never `MAX(fiscal_year)` without the asof filter; caller binds `:fy_ceiling`.
- **Quarterlies:** latest `quarter_end_date ≤ action_date` with 45-day
  reporting lag (`quarter_end_date + 45d ≤ action_date`).
- **Forensic levels:** 1 row/isin, no history — Gate 0 is a **current**
  snapshot; backtests stamp "snapshot-as-of-2026-09, not PIT".
- **Quarantine:** every query carries §13.0 exclusion. **Sanity:** every
  opm/npm read carries `ABS(col)<=100` (drops 3.8% placeholder extremes);
  every OCF read carries `<>0 AND IS NOT NULL` (drops 95% placeholders).

## 4. Beneish-proxy rules (feasible subset — labeled)

Full M-score needs receivables, COGS, asset-quality split, depreciation,
SG&A — none exist; OCF is 95% placeholder so TATA is blocked too. Feasible:

| Beneish var | Canonical need | Feasible proxy (existing cols) | Status |
|---|---|---|---|
| SGI | sales_t/sales_{t-1} | `revenue_t / revenue_{t-1}` consecutive-FY pair | COMPUTABLE (§13.2) |
| LVGI | leverage change | `Δdebt_to_equity` (real, mean 0.85) | COMPUTABLE |
| GMI | gross-margin deterioration | `−Δopm`, `−Δnpm` with sane filter | PROXY — labeled margin-deterioration, not GMI |
| TATA | accruals/assets | needs real OCF+assets — OCF 95% zero, assets absent | BLOCKED (narrow-coverage Sloan rank in §7 appendix only) |
| DSRI/AQI/DEPI/SGAI | receivables/assets/depr/SG&A | — | BLOCKED — do not proxy; SGI already covers growth |

Rules emitted: F2 (SGI + margin-collapse pair, 2.5%), F3, F4. **No M-score
is computed or thresholded** — with 5–6 of 8 variables missing, an "M-score"
number would be fabrication. The computable legs enter as separate veto
inputs, strictly more honest than a pseudo-score.

## 5. Altman-proxy rules (feasible subset — labeled)

`altman_z_score` is constant 3.2 — never read. Canonical Z needs working
capital, retained earnings, total assets — absent; IC and ROCE are
placeholders. Feasible distress axes from verified-real columns:

- **Leverage axis:** DE level + YoY change (real) — F4.
- **Profitability axis:** NI sign/trend + sane opm/npm (real) — F1/F3.
- **Market-vs-debt axis:** `market_cap_inr_cr / NULLIF(debt_inr_cr,0)` (MVE/TL
  spirit; debt missing ⇒ abstain, never impute 0) — SELL-support ordering only.

No Z-number is produced. Distress SUPPORT = any two of (DE>1.5 or F4;
NI<0; sane-margin collapse). Single-axis weakness is FLAG-only — mirrors
F-corroboration and avoids re-vetoing Gate-0 DE rejects as "new" wins (§12
overlap accounting).

## 6. Piotroski-subset F-5 (the broad veto)

Nine needs current ratio, share count, asset turnover, real OCF — blocked.
**Five feasible criteria** (1pt each), consecutive-FY pairs + latest FY,
sane-margin filter on the opm leg:

1. `NI > 0`. 2. `ΔNI > 0` YoY. 3. `ΔEBITDA > 0` YoY (cash-flow-adjacent trend;
   labeled substitute for the OCF legs — NOT called accrual quality).
4. `ΔDE < 0` YoY. 5. `Δopm > 0` YoY with `ABS(opm)≤100` both years
   (quarterly `ebitda_margin_pct` corroboration: 2,944 latest-quarter names
   quarantine-excluded at 45-day lag).

Dropped (blocked, listed so nobody re-adds them silently): both OCF legs,
Δcurrent-ratio, share-dilution, asset-turnover. Score labeled **F-5**, never
"Piotroski F". Live dist (n=2,116): 0:110/1:333/2:336/3:357/4:569/5:411.
BUY requires F-5 ≥ 4 (candidate; 3-vs-4 is a P2 calibration choice tested past
the bar, §12); F-5 ≤ 1 ⇒ F5 VETO/SUPPORT; F-5 = 2 ⇒ F6 FLAG. Missing any
input ⇒ criterion 0 AND `f5_partial=1` (fail-closed: partial scores veto-only,
never pass).

## 7. Accrual quality (narrow-coverage appendix + NI-persistence)

- **Sloan leg (narrow, labeled):** `accrual_rev = (NI − OCF)/revenue` computed
  ONLY where both OCF prints are nonzero (313 consecutive pairs / 87 latest
  names quar-excluded). There it ranks SELL-support ordering — a continuous
  input on a deep-dive subset, never a broad veto. Broad-book queries must
  never reference OCF without the `<>0 AND IS NOT NULL` guard (§13.6).
- **Persistence leg (broad, feasible):** NI<0 on **two consecutive FYs** ⇒ F7:
  F1 SUPPORT upgrades to strong; a single corroborating FLAG suffices for
  VETO (instead of two). Same economic intuition as Dechow-Dichev (does the
  print confirm, repeatedly?) with inputs that actually exist.
- **Dechow-Dichev regression (blocked):** needs WC-accrual ↔ past/present/
  future-CFO over ≥5 seasons with WC components — not computable. F7 is its
  honest replacement, no fake regression.
- **Growth-vs-cash divergence (broad):** SGI>1.5 with ΔNI<0 in the same pair
  (paper growth, profit decline) ⇒ FLAG. Catches what levels miss without
  touching OCF.

## 8. Forensic checklist (per-name, pre-trade)

Feasible today (each maps to §13 SQL): ☐ Gate 0 pass (DE leg informative;
IC/pledge legs known-dead — record which leg fired) · ☐ F1 loss veto clear ·
☐ F-5 ≥ 4 with `f5_partial=0` for BUYs · ☐ F2 triple clear · ☐ F7 persistence
checked · ☐ PIT lag satisfied (§3.3) · ☐ quarantine + sanity filters applied ·
☐ tax lot review: holding clock, FY exemption left, harvest candidacy (§9.4) ·
☐ (real-OCF subset only) Sloan rank reviewed.

Blocked until schema/data lands (red on the checklist, never silently
skipped): ☐ receivables-vs-revenue + CCC drift · ☐ auditor NLP
(qualifications/resignations/fees — auditor columns empty; needs head ingest)
· ☐ promoter pledge dynamics (all-zero) · ☐ RPT anomaly (all-zero) · ☐
coverage axis revival (IC placeholder) · ☐ ROCE/ROE revival (94% zero) · ☐
Dechow-Dichev · ☐ full Beneish/Altman/Piotroski.

## 9. Tax-cost schedule (source-cited, engine-owned)

Authoritative implementation: `reality_engine/processing/sip_backtest.py`
(`TAX_SCHEDULE`, `rate_for`, `sell_fifo`, `tax_on_sale`; 33 tests green,
reconciled 2026-09-24). Restated here for the 10cr book — engine owns code,
this file owns policy.

### 9.1 Rates by sell date

| Sell-date regime | STCG (≤12mo) | LTCG (>12mo) | LTCG exemption/FY | Source |
|---|---|---|---|---|
| Pre Finance (No.2) Act 2024 (sell < 2024-07-23) | 15% u/s 111A | 10% above ₹1L u/s 112A | ₹1,00,000 | sip_backtest docstring; incometaxindia.gov.in "Tax on long-term capital gains" |
| Finance (No.2) Act 2024 (sell ≥ 2024-07-23) | 20% u/s 111A | 12.5% above ₹1.25L, no indexation | ₹1,25,000 | Finance (No.2) Act/Bill 2024; DSP capital-gains guide; reducetax.in FY25-26 guide; Zerodha Budget-2024 table |

- **Holding clock:** LONG iff `(sell − buy).days > 365` (exactly 365d still
  short; 364-vs-366 boundary in `test_sip_backtest.py`). Re-corroborated
  2026-09-25: listed equity/equity-MF 12-month threshold; STT-paid STCG flat
  20% u/s 111A post-reform; LTCG above ₹1.25L/yr flat 12.5% u/s 112A, no
  indexation (DSP; IndiaTax.AI AY25-26; Finance Bill 2024 primary).
- **Buffer assets:** listed gold/silver ETFs share the 12-month threshold;
  physical gold is 24-month — §11 buffer uses **listed ETFs only**, one clock.

### 9.2 Transaction costs (per fill)

- STT **0.1% buy AND sell** (statutory, delivery) — into lot cost base and net
  proceeds (`add_lot`/`sell_fifo`).
- `OTHER_CHARGE_RATE` 5bps all-in is an **ASSUMED prior**, flagged wherever it
  flows — same status as 50bps impact (§10); both shrink only via slippage
  audit (tracker backlog #6).
- FIFO lots, per-FY LTCG exemption, within-sale netting only; **no cross-FY
  loss carry-forward** — harvesting (§9.4) is intra-FY by construction.

### 9.3 Worked implication

Every exit scores `stock_ret − index_ret − costs − taxes`. Short-hold exits
pay 20% on gains + 20bps STT + 50bps impact prior before excess — a +500bps
gross short-hold winner is ≈+380bps net of tax+STT alone at full marginal
gain, tighter after impact. Promotion-bar accounting (§12) is on this net
number with the 50bps prior labeled until the slippage audit.

### 9.4 Harvesting policy (intra-FY, engine-compatible)

1. **LTCG exemption sweep (March):** realize LTCG up to remaining FY exemption
   (₹1.25L post-reform) where net-positive after STT+impact; re-establish only
   where a fresh clock clears the 20bps STT + 50bps hurdle on paper.
2. **ST-loss harvest (March):** realize short-term losses against realized ST
   gains same-FY. Never harvest a wanted holding unless tax value exceeds
   `expected_edge − round_trip_cost`.
3. **Clock guard:** within 60 days of a lot crossing >365d, selling needs
   explicit justification (20%→12.5% marginal conversion above exemption).
4. **Turnover budget:** harvesting + rebalancing ≤ 25% of book/FY unless
   drawdown rules (§11) force defensive selling (logged risk-driven).

## 10. Cost model (50bps impact prior)

- `EXCESS_COST = 0.005` = `P1_NET_COST`: 50bps round-trip impact haircut,
  ASSUMED prior, no measured cost (slippage audit = tracker backlog #6).
  Every excess table stamps the assumption.
- Per round trip: 10bps STT/side (statutory) + 5bps other/side (assumed) +
  50bps impact (assumed) + STCG/LTCG (statutory §9.1). Paper-vs-live cost gap
  closed by design (identical convention).
- Micro/small caveat (tracker backlog #2): 50bps understates small names;
  vetoes apply universe-wide but sizing (§11 ladder) is tighter outside N50
  until per-tier slippage is measured.

## 11. Drawdown guardrails + 40% cash/gold/silver buffer (10cr book)

Tolerance: **40% max drawdown** (`MAX_DD_TOLERANCE`; worst observed 11.65%).
Buffer is risk control, not return driver: up to 40% combined cash + listed
gold ETF + listed silver ETF when equity is not ROI-positive. No leverage.

### 11.1 Deployment ladder (monthly EOD rebalance + panic triggers)

| Book drawdown | Equity cap | Buffer floor | Entry rule |
|---|---|---|---|
| <10% | 100% | 0% (operational cash) | Full signal book; vetoes apply |
| 10–20% | 80% | 20% | Freeze new BUYs in F-5 ≤ 2 names; harvest ST losses |
| 20–30% | 60% | 40% (cap binding) | New BUYs only F-5 ≥ 4 + zero FLAGs; SELL needs thesis+veto-SUPPORT |
| >30% | ≤60%, review | 40% | Halt new entries; position review; 40% breach = strategy halt + human review |

### 11.2 Panic overlay

`panic_monitor.drawdown_triggers`: Nifty 50 ≤ −1.5%, Midcap 100 ≤ −1.5%, any
sector ≤ −3.0%. On trigger: no new BUYs next session except crisis-bargain
names clearing Gate 0 + Gate 1 (F-5 ≥ 4, zero VETO/FLAG) — the veto binds
hardest on exactly the days the bargain hunter wants to buy. Crisis entries
at half size until the trigger clears.

### 11.3 Buffer mechanics

- Cash (0% in-engine) + listed gold/silver ETFs; combined ≤ 40%; single
  12-month clock (§9.1); no physical metal.
- Rebuilt from exits + harvest proceeds first, never by panic-selling
  veto-passing compounders into a drawdown.
- Monthly report adds buffer-composition + drawdown-vs-ladder-band to the
  engine's cash/sector-exposure paths.

## 12. Promotion-bar wiring (how Gate 1 earns its place)

Gate 1 is P2-selection work, tested like any leg (next_wave §5):

1. Cohort-clustered mean excess ≥ **+500bps net of measured costs** (50bps
   prior labeled) **and §9 taxes**. 2. **≥30 weekly cohorts** (≥13 for 20D)
   across **≥2 regimes** (`P1_REGIMES`). 3. Hit CI lower > 0.5
   (cluster-robust). 4. Same sign both regimes. 5. Shuffle placebo ≈ 0.

Pre-registered P2 tests (none benchmarked against the residual until the
audit gate holds — test_findings §8 P2 gate):

- **T-F1:** SELL excess on F-5 ≤ 1 names vs unflagged SELL candidates,
  cohort-clustered, placebo-controlled.
- **T-F2:** BUY excess with vs without Gate-1 overlay (does the veto remove
  the −500bps BUY leg's losers?).
- **T-F3:** F2 triple (growth-without-margin, 2.5%) forward excess at
  30/90/180/365 — the horizon where paper-growth profiles unwind.
- Honesty: Gate-0 overlap reported (DE-driven rejects not double-counted as
  Gate-1 wins); quarantine-excluded n + unmapped list per universe (tracker
  backlog #7); costs/taxes per §9–10.

## 13. SQL appendix (copy-paste, read-only, SQLite)

### 13.0 Quarantine predicate (every financials read)

```sql
-- row_key = isin for master_companies.
AND NOT EXISTS (
  SELECT 1 FROM substrate_quarantine q
  WHERE q.table_name = 'master_companies' AND q.row_key = a.isin
)
```

### 13.1 Latest-FY snapshot (caller binds :fy_ceiling per §3.3)

```sql
SELECT a.*
FROM annual_financials a
JOIN (
  SELECT isin, MAX(fiscal_year) AS fy
  FROM annual_financials
  WHERE fiscal_year <= :fy_ceiling
  GROUP BY isin
) m ON m.isin = a.isin AND m.fy = a.fiscal_year
WHERE 1 = 1
  AND NOT EXISTS (
    SELECT 1 FROM substrate_quarantine q
    WHERE q.table_name = 'master_companies' AND q.row_key = a.isin
  );
-- F1 ⇔ net_profit_inr_cr < 0 (VETO/SUPPORT).
```

### 13.2 Consecutive-FY pairs (SGI / ΔDE / sane-Δopm / ΔNI / ΔEBITDA)

```sql
SELECT
  cur.isin, cur.symbol,
  cur.fiscal_year AS fy, prev.fiscal_year AS fy_prev,
  cur.revenue_inr_cr / NULLIF(prev.revenue_inr_cr, 0) AS sgi,
  cur.debt_to_equity - prev.debt_to_equity            AS d_de,
  cur.opm_pct - prev.opm_pct                          AS d_opm,   -- pp
  cur.npm_pct - prev.npm_pct                          AS d_npm,   -- pp
  cur.net_profit_inr_cr - prev.net_profit_inr_cr      AS d_ni,
  cur.ebitda_inr_cr - prev.ebitda_inr_cr              AS d_ebitda
FROM annual_financials cur
JOIN annual_financials prev
  ON prev.isin = cur.isin
 AND prev.fiscal_year = (
   SELECT MAX(fiscal_year) FROM annual_financials p
   WHERE p.isin = cur.isin AND p.fiscal_year < cur.fiscal_year
 )
WHERE cur.fiscal_year <= :fy_ceiling
  AND ABS(COALESCE(cur.opm_pct, 0)) <= 100
  AND ABS(COALESCE(prev.opm_pct, 0)) <= 100
  AND NOT EXISTS (
    SELECT 1 FROM substrate_quarantine q
    WHERE q.table_name = 'master_companies' AND q.row_key = cur.isin
  );
-- F2 ⇔ sgi > 1.5 AND d_opm < -2.  F3 ⇔ d_opm < -2 AND d_npm < 0.
-- F4 ⇔ d_de > 0.3 AND cur.debt_to_equity > 1.0.
```

### 13.3 F-5 score (fail-closed partial flag)

```sql
SELECT cur.isin, cur.symbol, cur.fiscal_year AS fy,
  (CASE WHEN cur.net_profit_inr_cr > 0 THEN 1 ELSE 0 END)
+ (CASE WHEN cur.net_profit_inr_cr > prev.net_profit_inr_cr THEN 1 ELSE 0 END)
+ (CASE WHEN cur.ebitda_inr_cr > prev.ebitda_inr_cr THEN 1 ELSE 0 END)
+ (CASE WHEN cur.debt_to_equity < prev.debt_to_equity THEN 1 ELSE 0 END)
+ (CASE WHEN cur.opm_pct > prev.opm_pct THEN 1 ELSE 0 END) AS f5_score,
  CASE WHEN cur.net_profit_inr_cr IS NULL OR prev.net_profit_inr_cr IS NULL
         OR cur.ebitda_inr_cr IS NULL OR prev.ebitda_inr_cr IS NULL
         OR cur.debt_to_equity IS NULL OR prev.debt_to_equity IS NULL
         OR cur.opm_pct IS NULL OR prev.opm_pct IS NULL THEN 1 ELSE 0 END AS f5_partial
FROM annual_financials cur
JOIN annual_financials prev
  ON prev.isin = cur.isin
 AND prev.fiscal_year = (
   SELECT MAX(fiscal_year) FROM annual_financials p
   WHERE p.isin = cur.isin AND p.fiscal_year < cur.fiscal_year
 )
WHERE cur.fiscal_year <= :fy_ceiling
  AND ABS(COALESCE(cur.opm_pct, 0)) <= 100
  AND ABS(COALESCE(prev.opm_pct, 0)) <= 100
  AND NOT EXISTS (
    SELECT 1 FROM substrate_quarantine q
    WHERE q.table_name = 'master_companies' AND q.row_key = cur.isin
  );
-- F5 ⇔ f5_score <= 1 (VETO/SUPPORT; partial rows veto-only). F6 ⇔ f5_score = 2 (FLAG).
```

### 13.4 Quarterly corroboration (2,944 latest-quarter names quar-excluded; 45-day lag)

```sql
SELECT q.symbol, q.quarter_end_date,
       q.yoy_revenue_growth_pct, q.yoy_pat_growth_pct, q.ebitda_margin_pct
FROM quarterly_financials q
JOIN (
  SELECT isin, MAX(quarter_end_date) AS d
  FROM quarterly_financials
  WHERE date(quarter_end_date, '+45 days') <= date(:action_date)
  GROUP BY isin
) m ON m.isin = q.isin AND m.d = q.quarter_end_date
WHERE ABS(COALESCE(q.ebitda_margin_pct, 0)) <= 100
  AND NOT EXISTS (
    SELECT 1 FROM substrate_quarantine qq
    WHERE qq.table_name = 'master_companies' AND qq.row_key = q.isin
  );
-- Corroborate F-5 #5 margin leg and the §7 growth-vs-profit divergence leg.
```

### 13.5 Loss persistence F7 (two consecutive loss FYs)

```sql
SELECT cur.isin, cur.symbol, cur.fiscal_year AS fy
FROM annual_financials cur
JOIN annual_financials prev
  ON prev.isin = cur.isin
 AND prev.fiscal_year = (
   SELECT MAX(fiscal_year) FROM annual_financials p
   WHERE p.isin = cur.isin AND p.fiscal_year < cur.fiscal_year
 )
WHERE cur.fiscal_year <= :fy_ceiling
  AND cur.net_profit_inr_cr < 0 AND prev.net_profit_inr_cr < 0
  AND NOT EXISTS (
    SELECT 1 FROM substrate_quarantine q
    WHERE q.table_name = 'master_companies' AND q.row_key = cur.isin
  );
```

### 13.6 Cash-quality appendix (real-OCF subset ONLY — never the broad gate)

```sql
SELECT cur.isin, cur.symbol, cur.fiscal_year AS fy,
  (cur.net_profit_inr_cr - cur.operating_cash_flow_inr_cr)
    / NULLIF(cur.revenue_inr_cr, 0) AS accrual_rev
FROM annual_financials cur
WHERE cur.fiscal_year <= :fy_ceiling
  AND cur.operating_cash_flow_inr_cr IS NOT NULL
  AND cur.operating_cash_flow_inr_cr <> 0
  AND cur.net_profit_inr_cr IS NOT NULL
  AND cur.revenue_inr_cr IS NOT NULL AND cur.revenue_inr_cr <> 0
  AND NOT EXISTS (
    SELECT 1 FROM substrate_quarantine q
    WHERE q.table_name = 'master_companies' AND q.row_key = cur.isin
  )
ORDER BY accrual_rev DESC;
-- ~87 latest names. Rank SELL-support ordering here; no veto leaves this subset.
```

## 14. Open gaps (explicit, not hidden)

1. Pledge/RPT/auditor/coverage/ROCE legs are data-dead (§2) — veto strength
   concentrates on profit/margin/leverage until ingest revives them. The
   checklist (§8) keeps them red, not dropped.
2. FY26 annuals are current-year partials for many isins; §3.3 gates usability
   but cannot create filing timestamps — a future additive `published_date` on
   financials (event-date/version pattern, same as fiscal) would harden PIT.
3. 50bps impact + 5bps other-charges priors stay assumed until the slippage
   audit; micro/small sizing stays conservative (§10).
4. F-5 pass bar (≥4), F5/F6 cutoffs (≤1/=2), F2 SGI cutoff (1.5) are priors
   with measured bite — recalibration past the bar per §12, never by tuning
   on the test window.
5. OCF-real subset (87 names) is too thin for gate duty; real cash-flow
   coverage (fundamentals re-pull distinguishing 0-vs-missing) would promote
   the Sloan leg from appendix to gate.
