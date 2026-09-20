"""
Capacity governor — evidence-gated explainer-capacity expansion.

The forecast scheduler tests price-action forecasts (Wave B scores); this module
decides whether those scores justify moving ``model_explainer_rankings``
(explainer capacity) toward the empirically better lens mix — WITHOUT overfitting.

Anti-overfit design (all gates must pass per cohort, else SKIP with a reason):

1. **Train/holdout split in time.** Score dates for a (regime, investor) cohort
   split oldest → train, newest ``HOLDOUT_DATES`` → holdout. The winning lens
   must show ``edge >= EDGE_MIN`` on train AND ``edge > 0`` on holdout (sign
   agreement on unseen dates). Train-positive / holdout-negative ⇒ skip.
2. **Evidence-proportional step.** Blend weight ``alpha = min(ALPHA_MAX,
   n_train_lens_rows / EVIDENCE_SATURATION)`` — thin cohorts barely move the
   needle even when they pass the sign gate.
3. **Capped movement.** Per-application L1 step ``<= MAX_STEP_L1``; every family
   weight stays in ``[W_MIN, W_MAX]``. Rankings drift; they never jump.
4. **Bounded blast radius.** Writes touch only (regime, investor) partitions of
   ACTIVE symbols (recent ``eod_scrip_calls`` presence, capped at
   ``MAX_ACTIVE_STOCKS``). Investor tilts and floors are preserved because the
   move starts from current partition means and re-applies the floor.
5. **Propose by default.** ``evaluate()`` never writes rankings. ``apply()``
   is a separate, explicit call (CLI ``--apply-capacity --cohort R/I`` or a
   human in chat). The standing repo rule — never calibrate unattended — is
   honoured: no scheduled task passes ``--apply-capacity``.

Owns ONLY this file. Reads scores via ``repository.get_validation_scores``,
writes rankings only through ``EnsembleRanker.upsert_ranking``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from reality_engine.processing.ensemble_ranker import (
    BOOTSTRAP_ENSEMBLE_WEIGHTS,
    EXPLAIN_FLOOR,
    LENS_FAMILIES,
)

_REPO_OVERRIDE: Any = None  # test hook: Repository(manager) bound to the caller's temp DB

# Evidence gates
MIN_TRAIN_DATES = 4
HOLDOUT_DATES = 2
HORIZON_DAYS = 5
MODE = "ensemble"
EDGE_MIN = 0.002  # 20 bps mean edge required on train

# Step shaping
ALPHA_MAX = 0.5
EVIDENCE_SATURATION = 20  # train lens-rows at which alpha saturates
MAX_STEP_L1 = 0.10
W_MIN = 0.05  # == EXPLAIN_FLOOR: no lens collapses to exactly 0
W_MAX = 0.60  # no single lens may dominate the ensemble

# Blast-radius bound
MAX_ACTIVE_STOCKS = 500
ACTIVE_LOOKBACK_DAYS = 120


def _repo_for(db: Any) -> Any:
    """Repository bound to ``db`` (override-aware so tests never touch the live DB)."""
    if _REPO_OVERRIDE is not None:
        return _REPO_OVERRIDE(db)
    from reality_engine.db.repository import Repository

    return Repository(db)


def _cohort_rows(db, regime: str, investor: str) -> List[Dict[str, Any]]:
    rows = _repo_for(db).get_validation_scores(regime_tag=regime, investor_majority=investor, limit=10000)
    return [
        r for r in rows
        if int(r.get("horizon_days") or 0) == HORIZON_DAYS and str(r.get("mode")) == MODE
    ]


def _edge(row: Dict[str, Any]) -> Optional[float]:
    try:
        m, u = row.get("mean_fwd_ret"), row.get("universe_mean_ret")
        if m is None or u is None:
            return None
        return float(m) - float(u)
    except Exception:
        return None


def _mean_edge(rows: Sequence[Dict[str, Any]], family: str) -> Tuple[Optional[float], int]:
    vals = [_edge(r) for r in rows if r.get("lens_family") == family]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None, 0
    return sum(vals) / len(vals), len(vals)


def _empirical_weights(train_edges: Dict[str, float]) -> Dict[str, float]:
    pos = {f: max(0.0, train_edges.get(f, 0.0)) for f in LENS_FAMILIES}
    total = sum(pos.values())
    shares = {f: (v / total if total > 0 else 1.0 / len(LENS_FAMILIES)) for f, v in pos.items()}
    floored = {f: max(EXPLAIN_FLOOR, s) for f, s in shares.items()}
    ftot = sum(floored.values())
    return {f: floored[f] / ftot for f in LENS_FAMILIES}


def _current_mean_vector(db, symbols: Sequence[str], regime: str, investor: str) -> Tuple[Dict[str, float], int]:
    """Mean explain_power per family across active-stock partitions of one cohort."""
    from reality_engine.processing.ensemble_ranker import EnsembleRanker

    ranker = EnsembleRanker(db)
    acc: Dict[str, float] = {f: 0.0 for f in LENS_FAMILIES}
    covered = 0
    for sym in symbols:
        try:
            rows = ranker.get_rankings(sym, investor_majority=investor, regime_tag=regime)
        except Exception:
            continue
        vec = {r.get("lens_family"): r.get("explain_power") for r in rows or []}
        if not all(f in vec and vec[f] is not None for f in LENS_FAMILIES):
            continue
        covered += 1
        for f in LENS_FAMILIES:
            acc[f] += float(vec[f])
    if covered == 0:
        return dict(BOOTSTRAP_ENSEMBLE_WEIGHTS), 0
    return {f: acc[f] / covered for f in LENS_FAMILIES}, covered


def _bounded_step(w_cur: Dict[str, float], w_emp: Dict[str, float], alpha: float) -> Dict[str, float]:
    target = {f: w_cur[f] + alpha * (w_emp[f] - w_cur[f]) for f in LENS_FAMILIES}
    l1 = sum(abs(target[f] - w_cur[f]) for f in LENS_FAMILIES)
    if l1 > MAX_STEP_L1 and l1 > 0:
        scale = MAX_STEP_L1 / l1
        target = {f: w_cur[f] + scale * (target[f] - w_cur[f]) for f in LENS_FAMILIES}
    # Clip + renormalize (two passes converge for these bounds).
    for _ in range(3):
        target = {f: min(W_MAX, max(W_MIN, target[f])) for f in LENS_FAMILIES}
        tot = sum(target.values())
        target = {f: target[f] / tot for f in LENS_FAMILIES}
    return target


def active_symbols(db, limit: int = MAX_ACTIVE_STOCKS) -> List[str]:
    """Symbols with recent prediction calls — the capacity-expansion universe."""
    with db.session() as conn:
        try:
            rows = conn.execute(
                "SELECT DISTINCT symbol FROM eod_scrip_calls "
                f"WHERE date >= date('now', '-{int(ACTIVE_LOOKBACK_DAYS)} days') "
                "ORDER BY symbol ASC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [str(r[0]) for r in rows if r[0]]
        except Exception as exc:
            logger.debug("active_symbols probe failed: %s", exc)
            return []


def cohorts_available(db) -> List[Tuple[str, str]]:
    """Distinct (regime, investor) cohorts present in the scores table."""
    with db.session() as conn:
        try:
            rows = conn.execute(
                "SELECT DISTINCT regime_tag, investor_majority FROM model_validation_scores"
            ).fetchall()
            return [(str(r[0]), str(r[1])) for r in rows]
        except Exception:
            return []


def evaluate_cohort(db, regime: str, investor: str,
                    symbols: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Evaluate one cohort. Never writes rankings. Returns decision or skip."""
    rows = _cohort_rows(db, regime, investor)
    dates = sorted({str(r.get("asof_date"))[:10] for r in rows if r.get("asof_date")})
    base: Dict[str, Any] = {
        "regime_tag": regime, "investor_majority": investor,
        "n_dates": len(dates), "status": "skipped", "reason": "",
    }
    need = MIN_TRAIN_DATES + HOLDOUT_DATES
    if len(dates) < need:
        base["reason"] = f"thin_evidence: {len(dates)} dates < {need} required"
        return base
    holdout_set = set(dates[-HOLDOUT_DATES:])
    train_rows = [r for r in rows if str(r.get("asof_date"))[:10] not in holdout_set]
    holdout_rows = [r for r in rows if str(r.get("asof_date"))[:10] in holdout_set]

    train_edges: Dict[str, float] = {}
    n_train_lens = 0
    for fam in LENS_FAMILIES:
        mean, n = _mean_edge(train_rows, fam)
        train_edges[fam] = mean if mean is not None else 0.0
        n_train_lens += n
    if n_train_lens == 0:
        base.update(reason="no_lens_edges_on_train", train_edges=train_edges)
        return base

    winner = max(LENS_FAMILIES, key=lambda f: train_edges[f])
    if train_edges[winner] < EDGE_MIN:
        base.update(reason=f"no_edge: best {winner} {train_edges[winner]:.5f} < {EDGE_MIN}",
                    train_edges={k: round(v, 6) for k, v in train_edges.items()})
        return base
    hold_mean, hold_n = _mean_edge(holdout_rows, winner)
    holdout_edges = {f: _mean_edge(holdout_rows, f)[0] for f in LENS_FAMILIES}
    if hold_mean is None:
        base.update(reason=f"no_holdout_rows_for_{winner}",
                    train_edges={k: round(v, 6) for k, v in train_edges.items()})
        return base
    if hold_mean <= 0:
        base.update(
            reason=f"holdout_disagrees: {winner} train {train_edges[winner]:.5f} vs holdout {hold_mean:.5f}",
            train_edges={k: round(v, 6) for k, v in train_edges.items()},
            holdout_edges={k: (None if v is None else round(v, 6)) for k, v in holdout_edges.items()},
        )
        return base

    syms = list(symbols) if symbols is not None else active_symbols(db)
    w_emp = _empirical_weights(train_edges)
    alpha = min(ALPHA_MAX, n_train_lens / EVIDENCE_SATURATION)
    w_cur, coverage = _current_mean_vector(db, syms, regime, investor)
    w_new = _bounded_step(w_cur, w_emp, alpha)
    return {
        **base,
        "status": "decided",
        "reason": f"{winner} holds train {train_edges[winner]:.5f} / holdout {hold_mean:.5f}",
        "n_train_dates": len(dates) - HOLDOUT_DATES,
        "n_holdout_dates": HOLDOUT_DATES,
        "n_train_lens_rows": n_train_lens,
        "winner": winner,
        "train_edges": {k: round(v, 6) for k, v in train_edges.items()},
        "holdout_edges": {k: (None if v is None else round(v, 6)) for k, v in holdout_edges.items()},
        "alpha": round(alpha, 4),
        "w_current": {k: round(v, 6) for k, v in w_cur.items()},
        "w_empirical": {k: round(v, 6) for k, v in w_emp.items()},
        "w_decided": {k: round(v, 6) for k, v in w_new.items()},
        "coverage_partitions": coverage,
        "active_stocks": len(syms),
        "est_rows": len(syms) * len(LENS_FAMILIES),
    }


def evaluate(db, symbols: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Evaluate every cohort. Read-only. Returns decided + skipped lists."""
    decided, skipped = [], []
    for regime, investor in cohorts_available(db):
        d = evaluate_cohort(db, regime, investor, symbols=symbols)
        (decided if d["status"] == "decided" else skipped).append(d)
    return {"decided": decided, "skipped": skipped}


def apply_decision(db, decision: Dict[str, Any],
                   symbols: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Write one decided cohort into rankings. Refuses anything not decided."""
    if not isinstance(decision, dict) or decision.get("status") != "decided":
        raise ValueError(f"refusing to apply non-decided cohort: {decision.get('reason', decision)}")
    from reality_engine.processing.ensemble_ranker import EnsembleRanker

    regime, investor = decision["regime_tag"], decision["investor_majority"]
    syms = sorted(symbols) if symbols is not None else sorted(active_symbols(db))
    if not syms:
        raise ValueError("refusing to apply: empty active universe")
    weights = {f: float(decision["w_decided"][f]) for f in LENS_FAMILIES}
    unknown = [f for f in weights if f not in LENS_FAMILIES]
    if unknown or not weights:
        raise ValueError(f"bad decided weights: {weights}")
    ranker = EnsembleRanker(db)
    n_rows = 0
    for sym in syms:
        for fam, w in weights.items():
            ranker.upsert_ranking(sym, None, None, regime, investor, fam,
                                  p_value=None, explain_power=w)
            n_rows += 1
    return {"regime_tag": regime, "investor_majority": investor,
            "stocks_updated": len(syms), "rows_written": n_rows, "weights": weights}
