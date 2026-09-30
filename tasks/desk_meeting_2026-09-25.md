# Prop Desk Kickoff Meeting — CEO Verdict + 10cr Deployment Decision — 2026-09-25

> Attendees: DeskQuant-2, DeskForensic-2, DeskData-2, DeskBacktest-2, DeskMacroPsych-2.
> Ground truth: tasks/SESSION_HANDOVER_2026-09-25.md + test_findings §§1-14 + strategy_tracker.md + next_wave_plan §5 bar.
> Live-verified this session (commands below). No DB/schema edits, no reseeds, no weight changes.

## 1. CEO verdict: NO tradable edge today — do NOT open live 10cr book

- P1 grid + placebo: reject/reject (BUY −328bps, SELL +285bps, placebos ≈0). Rebuild 09-26: still reject.
- Live `portfolio-ledger --horizons 30,90,180,365 --universes nifty50,midcap150,smallcap250,microcap250` (run this session): Nifty50 mean −20bps (n=14, 4 cohorts), Midcap −335bps (n=46, 5 cohorts). All horizons identical per universe (realized-window min(close,entry+h) — exits are stop/target dates, T9 diagnostic). Nothing ≥ +500bps.
- Book: 681 closed / 160 open; closed BUY 58 / SELL 8 / HOLD 615. ≥30 closed BUY/SELL count is met (66), but excess is negative — count without edge is not promotion.
- Calibration `run-calibration`: folds 3, decided 3, improved 1, recommend_apply false. Gate healthy (starved single-voter, refuses — T8).
- Residual structurally constant (explained 0.11, residual 0.89; quality/policy/supply dirs 0/0/25 with SBIN −1 the lone quality vote). Scoring strategies against it is uninformative until P2 breadth.
- REVOKED stays revoked: SELL +527bps (closes: −20bps), blended +29.8, confirmation 1W/29L, trend 6/34. Never re-quote.

## 2. 10cr deployment decision (Oct-2021 lump sum, 40% buffer liberty exercised)

- **Live capital: PARKED.** 40% defensive sleeve (cash/listed gold+silver ETFs only — one 12-month clock) armed; 0% into unproven legs. Drawdown tolerance 40%, operating cap simulated worst-DD <25%.
- **Paper only:** F1 forensic avoidance, F2 vol-scaled continuation-momentum, F3 regime-carry (specs in desk_quant §3, harness in desk_backtest §1, sizing/exits gated per desk_macro_psych M4).
- Go-live requires the full bar per horizon: cohort-clustered ≥+500bps net of measured costs, ≥30 weekly cohorts, 2 regimes same sign, hit CI lower >0.5, placebo ≈0. F2 has a pre-registered kill rule (30D net <+500bps after measured costs → kill fast, no k-tuning).
- Cost stack (desk_forensic §9 + desk_backtest §1.8, engine-owned sip_backtest): STT 0.1%/side, impact 50bps prior → measured slippage audit, STCG 20% / LTCG 12.5% above ₹1.25L/FY post Finance (No.2) Act 2024, FIFO, >365d long clock, intra-FY March harvest (LTCG sweep + ST-loss harvest + clock guard). Every exit scored stock−index−costs−taxes.

## 3. What each desk delivered (one line + file)

- Quant (`tasks/desk_quant_2026-09-25.md`): TRUE-vs-REVOKED table + F1/F2/F3 families + honest recipe (XS control, vol brackets, placebo, taxes).
- Forensic (`tasks/desk_forensic_2026-09-25.md`, 550 lines): Gate0 (AGENTS §11) + Gate1 F1–F7 (F-5 broad, placeholder-zero redesign), live bites measured (F1 12–18%, F2 2.5%, F5≤1 21%), PIT lag rules, tax schedule source-cited, 40% buffer mechanics.
- Data (`tasks/desk_data_2026-09-25.md`): chunks 1,653,367 / index 1,398,908 dim384 (stale ~10.5k) / fiscal 292,246 / annual pending 26,263 (broad; handover 24,185 = N200-scoped) / concall pending 10,456. CONDITIONAL HOLD stands; fiscal-only flows.
- Backtest (`tasks/desk_backtest_2026-09-25.md`): 10cr PIT spec + vol brackets + XS-matched control + ≥30 cohorts + placebo + forward-OHLC≥30 + 40% sweep + 4×4 shell (30/90/180/365 × 4 universes) + calibration plan + verification commands.
- MacroPsych (`tasks/desk_macro_psych_2026-09-25.md`, 236 lines): M1 VIX regimes, M2 GARCH floors (stop-share <70% + excess gain, fallback-void >10%), M3 FII/promoter (1.8% honesty), M4 Kelly/OU/EVT strictly post-bar, B1 guidance drift, B2 fear-displacement, kill-table + REVOKED tripwire.

## 4. Live infra (verified this session — corrects handover §2)

- `embed-server` was DOWN (exited 23h55m, :8099 refused — DeskData-2 catch). Restarted via hub: now **ready pid=24008**. Do not launch any drain stage while :8099 is down (re-check first).
- DB: EOD max 2026-09-24; document_chunks 1,653,367; fiscal 292,246; chunk_index_meta source_chunks_at_build 1,642,865 (rebuild due after next drain stage).
- Event-date/version columns: PRAGMA-verified ABSENT on document_chunks (15 cols) + corporate_documents/raw path — bulk 26k stays HELD (handover §4 item 1 still open).
- Writer FREE (shm 32KB/wal 0B, lock 000000). Single-writer + queue lock; never co-run GPU/DB jobs.

## 5. Next actions (ordered, writer-safe)

1. Event-date/version additive columns + insert-stamping (same pattern as fiscal) — unblocks 24k release. No bulk joins until then.
2. Guidance-change diff writer on concalls (dated deltas — the only mechanism proven on-ledger, SBIN −1).
3. F1 forensic screen (pure SQL, no GPU) → F2 price-only grid (read-only, drain-safe) → F3 breadth/VIX assembly. P3/P4/P5 only past the bar.
4. Calibration re-run post-P0b (SELL regime + ≥2 lenses voting); bandit only if batch folds keep refusing.
5. Slippage audit (measured costs replace 50bps prior) + universe-map fix (≥80% on right benchmark + printed unmapped list).

## 6. Verification commands (scoped proof)

```powershell
python reality_engine/cli.py portfolio-ledger --horizons 30,90,180,365 --universes nifty50,midcap150,smallcap250,microcap250
python reality_engine/cli.py run-calibration
python -c "import json; print(json.load(open('reality_engine/data/vector_index/chunk_index_meta.json')))"
# sqlite read-only: max(daily_price_delivery.date), portfolio_actions status/action splits, document_chunks count + fiscal_labeled, PRAGMA table_info(document_chunks)
python -m pytest reality_engine/tests/test_sip_backtest.py -q
git status --porcelain
```
