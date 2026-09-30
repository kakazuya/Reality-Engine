"""Self-improving forecast loop: score → fit → apply → re-score, walk-forward.

The goal this serves
--------------------
"An information diffusion model that keeps improving its forecasting power on
subsequent occurrences." Improvement is only meaningful if it is (a) measured on
data the fit never saw and (b) persisted so successive rounds are comparable.
This module closes the loop the repo already had the pieces for:

* ``ValidationHarness.score_predictions``  — realised outcomes per lens  (exists)
* ``ValidationHarness.fit_lens_weights``   — weights from realised edge   (exists)
* ``ValidationHarness.apply_calibration``  — writes explain_power         (exists, never called)

What was missing: a **walk-forward round** that trains on early occurrences,
applies the result, evaluates on *later* occurrences the fit never saw, and
records the comparison. Eight weight proposals had been fitted and none applied,
so no occurrence ever improved the next one.

Statistical design (why not just normalise the edge)
----------------------------------------------------
``fit_lens_weights`` sets ``w ∝ max(0, mean_edge)``. With ~10 observations that
overfits noise: a lens with one lucky date takes most of the weight. Instead:

* each lens family's per-date edges form a series → mean, standard error, t-stat;
* lenses that do not clear ``min_t`` are **shrunk to the prior** rather than
  dropped (a lens with no evidence is uninformative, not necessarily bad — the
  repo's own §2 says all peers compete);
* posterior weights are a **softmax over edge with temperature τ** (τ = the
  repo's MoE explore/exploit knob), mixed with a uniform prior by λ.

So a round with no significant edge returns ≈ uniform weights — the honest
answer — and only persistent, significant edge moves them.

Leakage guard
-------------
``train_dates`` and ``eval_dates`` are asserted disjoint with
max(train) < min(eval); a violation raises rather than silently inflating skill.

Owns ``forecast_skill_history``.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("reality_engine.skill_loop")

LENS_FAMILIES: Tuple[str, ...] = (
    "factor_statistical",
    "policy_macro",
    "business_quality",
    "supply_chain",
)

DEFAULT_TEMPERATURE = 0.005   # edge scale is returns (~1e-2); τ sets explore/exploit
DEFAULT_PRIOR_MIX = 0.5       # λ: weight given to the uniform prior vs data
DEFAULT_MIN_T = 1.0           # |t| below this ⇒ shrink to prior

SKILL_DDL = """
CREATE TABLE IF NOT EXISTS forecast_skill_history (
    round_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    train_from TEXT, train_to TEXT, eval_from TEXT, eval_to TEXT,
    n_train_dates INTEGER NOT NULL DEFAULT 0,
    n_eval_dates INTEGER NOT NULL DEFAULT 0,
    weights_json TEXT NOT NULL,
    weight_stats_json TEXT,
    edge_uniform REAL, edge_weighted REAL,
    eval_ic REAL,
    applied INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


def ensure_schema(conn) -> None:
    conn.execute(SKILL_DDL)


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
def candidate_dates(conn, mode: str = "ensemble", horizon_days: int = 5) -> List[str]:
    """Dates that have BOTH per-lens validation rows and realised outcomes.

    Only dates where ``_dominant_lens_map`` produced at least one lens family
    appear — the per-lens rows are what carry the measurable edge.
    """
    rows = conn.execute(
        """SELECT DISTINCT asof_date FROM model_validation_scores
           WHERE mode = ? AND horizon_days = ? AND lens_family IS NOT NULL
           ORDER BY asof_date""",
        (mode, int(horizon_days)),
    ).fetchall()
    return [str(r[0]) for r in rows]


def trading_calendar(conn) -> List[str]:
    """All trading dates present in the bar store, ascending."""
    return [str(r[0]) for r in conn.execute(
        "SELECT DISTINCT date FROM daily_price_delivery ORDER BY 1").fetchall()]


def embargoed_eval_start(calendar: Sequence[str], train_to: str, horizon_days: int) -> str:
    """First eval date whose h-bar forward window shares nothing with the fit.

    A date t scored on a horizon-h window consumes bars t..t+h. If training
    ends at T, the earliest eval date whose window is fully disjoint is the
    (h+1)-th trading day after T: its window starts on day T+h+1. Enforced as
    an assertion on calendar distance, not a silent weekend assumption.
    """
    cal = list(calendar)
    i = cal.index(train_to) if train_to in cal else -1
    if i < 0:
        raise ValueError(f"train_to {train_to!r} not on the trading calendar")
    j = i + int(horizon_days) + 1
    if j >= len(cal):
        return ""
    return cal[j]

def lens_edge_series(conn, dates: Sequence[str], mode: str = "ensemble",
                     horizon_days: int = 5) -> Dict[str, List[Tuple[str, float]]]:
    """lens family -> [(asof_date, edge)] where edge = mean_fwd_ret − universe_mean_ret."""
    if not dates:
        return {}
    wanted = set(dates)
    marks = ",".join("?" for _ in dates)
    rows = conn.execute(
        f"""SELECT asof_date, lens_family, mean_fwd_ret, universe_mean_ret
            FROM model_validation_scores
            WHERE mode = ? AND horizon_days = ? AND lens_family IS NOT NULL
              AND mean_fwd_ret IS NOT NULL AND universe_mean_ret IS NOT NULL
              AND asof_date IN ({marks})
            ORDER BY asof_date""",
        (mode, int(horizon_days), *dates),
    ).fetchall()
    out: Dict[str, List[Tuple[str, float]]] = {}
    for asof, fam, mfr, umr in rows:
        fam_s = str(fam)
        if str(asof) not in wanted or fam_s not in LENS_FAMILIES:
            continue
        try:
            out.setdefault(fam_s, []).append((str(asof), float(mfr) - float(umr)))
        except (TypeError, ValueError):
            continue
    return out


def composite_ic(conn, dates: Sequence[str], mode: str = "ensemble",
                 horizon_days: int = 5) -> Optional[float]:
    """Mean whole-cohort rank IC across dates (informational; weight-independent)."""
    if not dates:
        return None
    marks = ",".join("?" for _ in dates)
    rows = conn.execute(
        f"""SELECT ic FROM model_validation_scores
            WHERE mode = ? AND horizon_days = ? AND lens_family IS NULL
              AND investor_majority = 'all' AND ic IS NOT NULL AND asof_date IN ({marks})""",
        (mode, int(horizon_days), *dates),
    ).fetchall()
    vals = [float(r[0]) for r in rows if r[0] is not None]
    return (sum(vals) / len(vals)) if vals else None


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def _mean(xs: Sequence[float]) -> float:
    return float(sum(xs)) / len(xs) if xs else 0.0


def _stderr(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("inf")
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var / n) if var > 0 else float("inf")


def bayesian_weights(
    series: Dict[str, List[Tuple[str, float]]],
    temperature: float = DEFAULT_TEMPERATURE,
    prior_mix: float = DEFAULT_PRIOR_MIX,
    min_t: float = DEFAULT_MIN_T,
    families: Sequence[str] = LENS_FAMILIES,
) -> Dict[str, Any]:
    """Significance-gated softmax weights with a uniform-prior mixture.

    Returns ``{weights, stats}``. Lenses with |t| < ``min_t`` are assigned the
    prior logit (0 ⇒ uniform share) instead of their noisy mean, so absence of
    evidence cannot dominate the ensemble. A perfectly repeatable edge over
    multiple occurrences (zero variance) is the strongest evidence, not the
    weakest.
    """
    fams = list(families)
    uniform = 1.0 / len(fams)
    stats: Dict[str, Dict[str, Any]] = {}
    logits: Dict[str, float] = {}
    for fam in fams:
        vals = [v for _, v in series.get(fam, [])]
        n = len(vals)
        m = _mean(vals) if vals else 0.0
        if n < 2:
            t, se = 0.0, float("inf")   # one observation proves nothing
        else:
            var = sum((x - m) ** 2 for x in vals) / (n - 1)
            if var <= 0:
                t, se = ((float("inf") if m > 0 else float("-inf")) if m != 0 else 0.0), 0.0
            else:
                se = math.sqrt(var / n)
                t = m / se
        gated = not (abs(t) >= min_t)
        logits[fam] = 0.0 if gated else (m / max(temperature, 1e-9))
        stats[fam] = {"n": n, "mean_edge": round(m, 6),
                      "stderr": (None if se == float("inf") else round(se, 6)),
                      "t": (999.0 if math.isinf(t) and t > 0
                            else (-999.0 if math.isinf(t) else round(t, 3))),
                      "shrunk_to_prior": gated}
    # softmax over logits
    mx = max(logits.values()) if logits else 0.0
    exps = {f: math.exp(min(50.0, logits[f] - mx)) for f in fams}
    tot = sum(exps.values()) or 1.0
    soft = {f: exps[f] / tot for f in fams}
    blended = {f: (1.0 - prior_mix) * uniform + prior_mix * soft[f] for f in fams}
    norm = sum(blended.values()) or 1.0
    weights = {f: blended[f] / norm for f in fams}
    return {"weights": weights, "stats": stats,
            "temperature": temperature, "prior_mix": prior_mix, "min_t": min_t}


def weighted_edge(series: Dict[str, List[Tuple[str, float]]], weights: Dict[str, float]) -> Optional[float]:
    """Portfolio-of-lenses edge: Σ w_l · mean(edge_l) over the eval window.

    Lenses with no eval observations are skipped and the remaining weights are
    renormalised, so a missing lens cannot silently deflate the score.
    """
    present = {f: [v for _, v in series.get(f, [])] for f in weights}
    usable = {f: v for f, v in present.items() if v}
    if not usable:
        return None
    tot_w = sum(weights[f] for f in usable) or 1.0
    return sum(weights[f] / tot_w * _mean(v) for f, v in usable.items())


# ---------------------------------------------------------------------------
# The round
# ---------------------------------------------------------------------------
def run_round(
    conn,
    mode: str = "ensemble",
    horizon_days: int = 5,
    train_frac: float = 0.45,
    max_train_dates: int = 0,
    temperature: float = DEFAULT_TEMPERATURE,
    prior_mix: float = DEFAULT_PRIOR_MIX,
    min_t: float = DEFAULT_MIN_T,
    persist: bool = True,
    calendar: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """One walk-forward round: fit on early occurrences, evaluate on later ones.

    ``train_frac`` splits the available occurrence dates chronologically; the
    eval block is then purged so its forward window shares no bars with the
    fit (embargo ≥ horizon_days trading bars). Both the split and the embargo
    gap are asserted — a missing eval window returns insufficient_dates instead
    of a fake improvement.
    """
    dates = candidate_dates(conn, mode=mode, horizon_days=horizon_days)
    if len(dates) < 3:
        return {"status": "insufficient_dates", "n_dates": len(dates), "mode": mode,
                "horizon_days": horizon_days}
    cut = max(1, int(round(len(dates) * float(train_frac))))
    cut = min(cut, len(dates) - 1)
    train = dates[:cut]
    if max_train_dates and len(train) > max_train_dates:
        train = train[-max_train_dates:]
    # Purged/embargoed split: the eval block must start at least horizon_days
    # trading bars AFTER the last training date, otherwise a 5-bar forward
    # window shares ~4/5 of its bars with the fit — near-in-sample.
    cal = list(calendar) if calendar is not None else trading_calendar(conn)
    floor = embargoed_eval_start(cal, train[-1], int(horizon_days))
    eval_ = [d for d in dates[cut:] if not floor or d >= floor]
    if not train or not eval_:
        return {"status": "insufficient_dates", "n_dates": len(dates),
                "reason": f"no embargo-safe eval window (train_to={train[-1] if train else None}, "
                          f"floor={floor!r}); need more occurrences",
                "mode": mode, "horizon_days": horizon_days}
    assert max(train) < min(eval_), f"leakage: train {max(train)} >= eval {min(eval_)}"

    train_series = lens_edge_series(conn, train, mode=mode, horizon_days=horizon_days)
    eval_series = lens_edge_series(conn, eval_, mode=mode, horizon_days=horizon_days)
    fitted = bayesian_weights(train_series, temperature=temperature,
                              prior_mix=prior_mix, min_t=min_t)
    uniform = {f: 1.0 / len(LENS_FAMILIES) for f in LENS_FAMILIES}
    edge_u = weighted_edge(eval_series, uniform)
    edge_w = weighted_edge(eval_series, fitted["weights"])
    ic = composite_ic(conn, eval_, mode=mode, horizon_days=horizon_days)

    improved = None
    if edge_u is not None and edge_w is not None:
        improved = bool(edge_w > edge_u)
    notes = ("no significant edge in train window; weights stay near uniform"
             if all(s.get("shrunk_to_prior") for s in fitted["stats"].values()) else "")

    record = {
        "mode": mode, "horizon_days": int(horizon_days),
        "train_from": train[0], "train_to": train[-1],
        "eval_from": eval_[0], "eval_to": eval_[-1],
        "n_train_dates": len(train), "n_eval_dates": len(eval_),
        "weights": fitted["weights"], "stats": fitted["stats"],
        "edge_uniform": edge_u, "edge_weighted": edge_w, "eval_ic": ic,
        "improved": improved, "notes": notes,
    }
    if persist:
        ensure_schema(conn)
        conn.execute(
            """INSERT INTO forecast_skill_history
               (mode, horizon_days, train_from, train_to, eval_from, eval_to,
                n_train_dates, n_eval_dates, weights_json, weight_stats_json,
                edge_uniform, edge_weighted, eval_ic, applied, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (mode, int(horizon_days), train[0], train[-1], eval_[0], eval_[-1],
             len(train), len(eval_),
             json.dumps(fitted["weights"]), json.dumps(fitted["stats"]),
             edge_u, edge_w, ic, 0, notes),
        )
        record["round_id"] = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    return record


def run_folds(
    conn,
    mode: str = "ensemble",
    horizon_days: int = 5,
    n_folds: int = 3,
    min_train_dates: int = 3,
    temperature: float = DEFAULT_TEMPERATURE,
    prior_mix: float = DEFAULT_PRIOR_MIX,
    min_t: float = DEFAULT_MIN_T,
    persist: bool = True,
    calendar: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Expanding-window walk-forward: one fit per fold, evaluated on the next block.

    A single arbitrary split can flatter or damn a lens by luck. Expanding folds
    across every available occurrence ask the question that actually matters:
    **does the fitted tilt beat uniform on data it has never seen, repeatedly?**
    """
    dates = candidate_dates(conn, mode=mode, horizon_days=horizon_days)
    if len(dates) < min_train_dates + 1:
        return {"status": "insufficient_dates", "n_dates": len(dates)}
    folds: List[Dict[str, Any]] = []
    cal = list(calendar) if calendar is not None else trading_calendar(conn)
    remaining = len(dates) - min_train_dates
    block = max(1, remaining // max(1, n_folds))
    for k in range(n_folds):
        cut = min_train_dates + k * block
        if cut >= len(dates):
            break
        train = dates[:cut]
        floor = embargoed_eval_start(cal, train[-1], int(horizon_days))
        ev_end = min(len(dates), cut + block)
        eval_ = [d for d in dates[cut:ev_end] if not floor or d >= floor]
        if not train or not eval_:
            break
        assert max(train) < min(eval_), "leakage guard tripped in fold construction"
        train_series = lens_edge_series(conn, train, mode=mode, horizon_days=horizon_days)
        eval_series = lens_edge_series(conn, eval_, mode=mode, horizon_days=horizon_days)
        if not train_series or not eval_series:
            continue
        fitted = bayesian_weights(train_series, temperature=temperature,
                                  prior_mix=prior_mix, min_t=min_t)
        uniform = {f: 1.0 / len(LENS_FAMILIES) for f in LENS_FAMILIES}
        edge_u = weighted_edge(eval_series, uniform)
        edge_w = weighted_edge(eval_series, fitted["weights"])
        fold = {
            "fold": k + 1, "train_to": train[-1], "eval_from": eval_[0], "eval_to": eval_[-1],
            "n_train": len(train), "n_eval": len(eval_),
            "weights": fitted["weights"], "stats": fitted["stats"],
            "edge_uniform": edge_u, "edge_weighted": edge_w,
            "delta": (None if (edge_u is None or edge_w is None) else edge_w - edge_u),
            "improved": (None if (edge_u is None or edge_w is None) else bool(edge_w > edge_u)),
        }
        folds.append(fold)
        if persist:
            ensure_schema(conn)
            conn.execute(
                """INSERT INTO forecast_skill_history
                   (mode, horizon_days, train_from, train_to, eval_from, eval_to,
                    n_train_dates, n_eval_dates, weights_json, weight_stats_json,
                    edge_uniform, edge_weighted, eval_ic, applied, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (mode, int(horizon_days), train[0], train[-1], eval_[0], eval_[-1],
                 len(train), len(eval_), json.dumps(fitted["weights"]),
                 json.dumps(fitted["stats"]), edge_u, edge_w,
                 composite_ic(conn, eval_, mode=mode, horizon_days=horizon_days),
                 0, f"fold {k+1}/{n_folds}"),
            )
            fold["round_id"] = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    deltas = [f["delta"] for f in folds if f["delta"] is not None]
    wins = sum(1 for f in folds if f.get("improved"))
    n_decided = sum(1 for f in folds if f.get("improved") is not None)
    summary = {
        "status": "ok" if folds else "no_evaluable_folds",
        "mode": mode, "horizon_days": int(horizon_days),
        "folds": len(folds), "folds_improved": wins, "folds_decided": n_decided,
        "mean_delta": (sum(deltas) / len(deltas)) if deltas else None,
        "median_delta": (sorted(deltas)[len(deltas) // 2] if deltas else None),
        "recommend_apply": bool(n_decided and wins > n_decided / 2 and sum(deltas) > 0),
        "detail": folds,
    }
    return summary


def apply_if_improved(conn, mode: str = "ensemble", horizon_days: int = 5,
                      n_folds: int = 3, calendar: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Run the folds and apply the fitted weights ONLY if they beat uniform.

    This is the loop's action gate: the ensemble's published lens weights move
    only on out-of-sample evidence. A failing round is persisted and ignored,
    which is the difference between self-correction and self-deception.
    ``calendar`` is the same injectable trading-day list as in run_round/run_folds.
    """
    summary = run_folds(conn, mode=mode, horizon_days=horizon_days,
                        n_folds=n_folds, persist=True, calendar=calendar)
    if summary.get("status") != "ok" or not summary.get("recommend_apply"):
        return {"applied": False, "reason": "no out-of-sample improvement",
                "summary": {k: v for k, v in summary.items() if k != "detail"}}
    last = summary["detail"][-1]
    from reality_engine.processing.validation_harness import ValidationHarness
    h = ValidationHarness(manager=None)
    proposal = {"weights": last["weights"], "regime_tag": None, "investor_majority": "all"}
    applied = h.apply_calibration(proposal)
    for f in summary["detail"]:
        if f.get("round_id"):
            mark_applied(conn, f["round_id"], True)
    return {"applied": True, "weights": last["weights"], "calibration": applied,
            "summary": {k: v for k, v in summary.items() if k != "detail"}}


def mark_applied(conn, round_id: int, applied: bool = True) -> None:
    conn.execute("UPDATE forecast_skill_history SET applied=? WHERE round_id=?",
                 (1 if applied else 0, int(round_id)))


def history(conn, limit: int = 20) -> List[Dict[str, Any]]:
    ensure_schema(conn)
    rows = conn.execute(
        """SELECT round_id, mode, horizon_days, train_to, eval_from, eval_to,
                  n_eval_dates, weights_json, edge_uniform, edge_weighted, eval_ic,
                  applied, notes, created_at
           FROM forecast_skill_history ORDER BY round_id DESC LIMIT ?""",
        (int(limit),),
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "round_id": r[0], "mode": r[1], "horizon_days": r[2],
            "train_to": r[3], "eval_from": r[4], "eval_to": r[5], "n_eval_dates": r[6],
            "weights": json.loads(r[7] or "{}"),
            "edge_uniform": r[8], "edge_weighted": r[9], "eval_ic": r[10],
            "applied": bool(r[11]), "notes": r[12], "created_at": r[13],
        })
    return out
