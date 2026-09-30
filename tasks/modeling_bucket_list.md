# Modeling Bucket List — ideas to test later (do NOT start while drain owns GPU/DB)

> Filed 2026-09-22. Every idea plugs in as a competing peer lens
> (explain_power + walk-forward folds + portfolio excess as the universal test).
> NEXT (not started): momentum-vs-reversal by horizon — needs the drain to free the DB writer first.

## Statistics / econometrics
- **GARCH noise floors** — GARCH(1,1) conditional vol per scrip replaces trailing-20σ. Test: fewer stopped-out-later-winners, same material count.
- **Event-study abnormal returns** — market-model (Nifty beta) expected vs realized around attribution dates; residual becomes abnormal, not raw. Test: abnormal-residual vs raw residual as forward predictor.
- **Momentum vs reversal by horizon [NEXT]** — Jegadeesh-Titman vs De Bondt-Thaler separately on 30/90/180/365. Test: interrogates our core wound (SELL wins short, BUY loses short); find which horizon each effect owns.
- **Factor zoo discipline** — Carhart + q-factor with Harvey-Liu-Zhu haircuts before any new factor earns weight. Test: out-of-sample IC after haircut.
- **Granger / VAR spillovers** — news→price Granger tests; sector VAR validates ripple DAG β empirically. Test: estimated elasticities vs DAG assumptions.
- **Copulas for panic baskets** — tail dependence across holdings; size crisis entries by joint-crash probability. Test: drawdown depth on panic cohorts.

## Forensic accounting (SELL-leg fuel)
- **Beneish M-score + Altman Z + Piotroski F** — computable from existing financials today. Test: SELL hit-rate on flagged names.
- **Accrual quality (Sloan, Dechow-Dichev)** — cash-vs-paper divergence as a broken-thesis clause. Test: catches what moat<2.5/neg-ENI misses?
- **Receivables-vs-revenue + CCC drift** — collection deterioration as early warning. Test: lead time to negative surprises.
- **Auditor signals NLP** — qualifications/resignations/fee anomalies from annuals (needs head ingest). Test: event study around auditor events.
- **Promoter pledge dynamics** — change, not level, as distress signal. Test: forward returns post pledge-increase.

## Mathematics
- **Hawkes panic cascades** — self-exciting arrivals for crash clustering; drives sizing into capitulation. Test: entry timing vs fixed-day.
- **OU mean-reversion half-life** — per-scrip reversion speed; SELL holds only while half-life short. Test: SELL pnl vs fixed exits.
- **Kelly (fractional) sizing** — hit-rate + payoff → position weights. Test: vs equal-weight book.
- **Transfer entropy news→price** — kills dead feeds honestly. Test: ensemble IC after dropping zero-transfer feeds.
- **EVT tail sizing** — tail shape per scrip sizes stops better than σ-multiples. Test: stop-out regret rate.
- **Spectral cyclicality** — formalize Lynch-cyclical via spectral peaks. Test: cyclical vs non-cyclical excess split.

## Machine learning
- **GBM on substrate (LightGBM)** — walk-forward direction model; promotes only via apply_if_improved. Test: folds vs current ensemble.
- **Concall Q&A tone model** — evasiveness classifier on existing chunks, local small model. Test: tone IC on next-quarter moves.
- **Guidance-change detection** — diff management numbers across quarters. Test: raises/cuts as signals.
- **Isolation-forest fraud screen** — anomaly score as SELL input. Test: overlap with Beneish + forwards.
- **Survival analysis (time-to-target/SL)** — Cox model replaces fixed 60-session horizon. Test: realized vs predicted holding times.
- **Contextual bandits for lens selection** — online per-context weights. Test: cumulative regret vs static.
- **Conformal entry/target/SL bands** — intervals with coverage guarantees. Test: empirical coverage.

## Bayesian probability
- **Beta-Binomial hit-rate tracking** — per-lens posterior hit rates; retire below-chance lenses. Test: posterior vs point-estimate pruning.
- **Hierarchical sector→stock shrinkage** — small/micro borrow sector strength (attacks sparse cells). Test: smallcap cell n/stability.
- **BSTS counterfactuals (CausalImpact-style)** — model-based residual per move. Test: vs arithmetic residual as predictor.
- **Bayesian model averaging over lenses** — posterior-weighted blends vs winner-take-all. Test: out-of-sample.
- **Structural theories as informative priors** — milestones as actual priors. Test: cold-start with vs without.
- **Always-valid p-values** — sequential testing for the continuous loop. Test: false-positive rate under monitoring.

## Game theory
- **Promoter signaling (costly signals)** — buybacks/insider buys/pledge releases weighted by costliness. Test: event study on in-DB PIT buys.
- **FII/DII herding vs contrarian regimes** — condition lens weights on flow regime. Test: excess by regime.
- **Crowded-exit / squeeze risk on SELLs** — delivery + turnover + borrow proxies. Test: SELL loss attribution to squeezes.
- **IPO/OFS auction lens** — offer pipeline exists; listing-pop as event class. Test: IPO-event excess separately.
- **Execution mechanism design** — measure realized slippage vs 50bps prior. Test: shrink the prior with data.

## Psychology / sentiment
- **Prospect-theory anchoring** — formalize 52w-high value function for timing. Test: entries near vs far from high.
- **Loughran-McDonald sentiment on chunks** — finance lexicon over 662k chunks + incoming docs. Test: sentiment IC by horizon.
- **Attention proxies** — news volume, concall participants, delivery spikes; over-attention → reversal. Test: attention × residual interaction.
- **India VIX regime conditioning** — gate BUY aggression on fear; crisis thesis predicts best cells at highest VIX. Test: excess by VIX quintile.
- **Narrative momentum (Shiller)** — topic-model news flow, narrative-age vs return. Test: emerging-narrative trade curve.

## Suggested first three (cheapest, highest signal, substrate exists)
1. Momentum-vs-reversal by horizon (book + ledger already hold the data).
2. Beneish/Piotroski/accrual screens (pure SQL, feeds the 46/46 SELL leg).
3. GARCH floors + Loughran-McDonald sentiment (data in hand, targets measured weaknesses).
