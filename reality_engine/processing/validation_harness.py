"""
Wave B — Model-testing loop: score past predictions vs realized prices.

Owns ONLY this file (+ additive repository helpers). Never touches
``eod_corrector.py`` scoring, ``cli.py``, or ``pipeline/nightly*``.

Pipeline
--------
1. ``score_predictions(asof_date, horizon_days, mode, mode_symbols)``
   reads one prediction run for ``asof_date`` from ``eod_scrip_calls`` plus
   the alpha theses (entry/target/SL) from
   ``data/reports/<date>/daily_alpha_{ensemble,legacy}.json``, joins forward
   realized returns from ``daily_price_delivery`` close prices, and persists
   per-(horizon × mode × lens × regime × investor) rows to
   ``model_validation_scores``.
2. ``fit_lens_weights(regime_tag, investor_majority)`` derives empirical lens
   weights from those scores and writes a *proposal* to
   ``model_lens_weight_proposals`` — it never touches rankings.
3. ``apply_calibration(proposal)`` is the deliberate, separately-invoked step
   that writes a proposal into ``model_explainer_rankings`` via
   ``EnsembleRanker.upsert_ranking``.

Conventions (documented so the numbers are reproducible)
-------------------------------------------------------
* Horizons are **trading days**, counted per symbol over dates actually present
  in ``daily_price_delivery`` for that symbol — calendar days are never assumed.
  A symbol lacking the h-th subsequent bar is excluded from horizon h only.
* Predicted direction is always long (+1): every screened call is a bullish
  candidate. ``hit = 1`` when the forward return is positive, ``0`` when
  negative, ``0.5`` on an exactly-flat print.
* ``mean_fwd_ret`` is the mean forward return of the **top-20** (by
  ``composite_rank``; fewer when the run is smaller); ``universe_mean_ret`` is
  the mean over every scored symbol with data at that horizon.
* ``ic`` is the Spearman rank correlation between ``composite_score``
  (falling back to ``-composite_rank``) and the forward return.
* Thesis scoring is conservative: bars after ``asof_date`` (up to the largest
  requested horizon, capped at 60 trading days) are walked in order and the
  **stop is checked before the target** on each bar, so a same-bar touch of
  both counts as a miss. Theses never resolved inside the window count as
  misses. ``thesis_hit_rate`` is attached to the whole-cohort row of the
  largest scored horizon only (``None`` elsewhere).
* ``regime_tag`` is derived from ``nse_index_breadth`` on ``asof_date``
  (mean A/D ratio across indices; counts preferred over the stored ratio):
  ``>=1.5`` → ``bullish``, ``<=0.67`` → ``bearish``, else ``neutral``;
  no breadth row → ``unknown``.
* ``investor_majority`` comes from ``company_forensic_health`` holdings
  (``promoter`` / ``FII`` / ``DII`` / ``retail`` for public); symbols with no
  health row score under ``all`` only.
* Per-lens buckets use the symbol's dominant (rank-1 / max ``explain_power``)
  lens from ``model_explainer_rankings`` (``all``-cohort rows preferred);
  symbols with no ranking stay in the whole-cohort rows only.
"""

from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("reality_engine.validation_harness")

LENS_FAMILIES: Tuple[str, ...] = (
    "factor_statistical",
    "business_quality",
    "policy_macro",
    "supply_chain",
)

# Mirrors ensemble_ranker.EXPLAIN_FLOOR: no lens may calibrate to exactly 0.
EXPLAIN_FLOOR: float = 0.05

TOP_N: int = 20
THESIS_WINDOW_CAP: int = 60

_ENTRY_RANGE_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*-\s*([\d,]+(?:\.\d+)?)")


# ----------------------------------------------------------------------
# Small pure-python statistics helpers (no third-party deps)
# ----------------------------------------------------------------------
def _mean(xs: Sequence[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None and math.isfinite(float(x))]
    if not xs:
        return None
    return float(sum(float(x) for x in xs) / len(xs))


def _average_ranks(vals: Sequence[float]) -> List[float]:
    """1-based average ranks (ties share the mean rank), ascending order."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Spearman rank correlation; None when undefined (n<3 or zero variance)."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _average_ranks(list(xs)), _average_ranks(list(ys))
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx)
    dy = sum((b - my) ** 2 for b in ry)
    if dx <= 0 or dy <= 0:
        return None
    return num / math.sqrt(dx * dy)


def _parse_entry_mid(entry_range: Any, fallback: Any) -> Optional[float]:
    """Midpoint of 'INR a - INR b'; falls back to ``fallback`` (CMP)."""
    try:
        m = _ENTRY_RANGE_RE.search(str(entry_range or ""))
        if m:
            a = float(m.group(1).replace(",", ""))
            b = float(m.group(2).replace(",", ""))
            return (a + b) / 2.0
    except Exception:
        pass
    try:
        return float(fallback) if fallback is not None else None
    except Exception:
        return None


class ValidationHarness:
    """Wave B scoring + calibration harness (temp-DB friendly)."""

    def __init__(self, manager: Optional[Any] = None, reports_dir: Optional[Any] = None):
        if manager is None:
            from reality_engine.db.database import db_manager
            manager = db_manager
        self.db = manager
        if reports_dir is None:
            from reality_engine.config import REPORTS_DIR
            reports_dir = REPORTS_DIR
        self.reports_dir = Path(reports_dir)
        from reality_engine.db.repository import Repository
        self.repo = Repository(manager)

    # ------------------------------------------------------------------
    # Internal loaders (raw SQL: no master_companies JOIN so sparse/temp
    # DBs without a seeded master still score).
    # ------------------------------------------------------------------
    def _load_predictions(
        self, conn: Any, asof_date: str, mode_symbols: Optional[Sequence[str]] = None
    ) -> List[Dict[str, Any]]:
        cols = {c[1] for c in conn.execute("PRAGMA table_info('eod_scrip_calls')").fetchall()}
        want = ("date", "symbol", "isin", "composite_rank", "composite_score",
                "current_market_price", "target_price", "stop_loss",
                "recommended_entry_range")
        sel = [c for c in want if c in cols]
        rows = conn.execute(
            f"SELECT {', '.join(sel)} FROM eod_scrip_calls WHERE date = ?", (asof_date,)
        ).fetchall()
        preds = [dict(r) for r in rows]
        if mode_symbols is not None:
            keep = {str(s).upper() for s in mode_symbols}
            preds = [p for p in preds if str(p.get("symbol", "")).upper() in keep]
        preds.sort(key=lambda p: (p.get("composite_rank") is None,
                                  p.get("composite_rank") or 0))
        return preds

    def _load_price_bars(
        self, conn: Any, symbols: Sequence[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """symbol -> ascending [(date, close, high, low)] bars (all history)."""
        bars: Dict[str, List[Dict[str, Any]]] = {s: [] for s in symbols}
        if not symbols:
            return bars
        cols = {c[1] for c in conn.execute("PRAGMA table_info('daily_price_delivery')").fetchall()}
        if not cols:
            return bars
        price_col = "close" if "close" in cols else None
        if price_col is None:
            return bars
        hi = "high" if "high" in cols else None
        lo = "low" if "low" in cols else None
        sel = f"symbol, date, close{(f', {hi}') if hi else ''}{(f', {lo}') if lo else ''}"
        chunk = 500
        syms = list(symbols)
        for i in range(0, len(syms), chunk):
            part = syms[i:i + chunk]
            ph = ", ".join("?" for _ in part)
            for r in conn.execute(
                f"SELECT {sel} FROM daily_price_delivery WHERE symbol IN ({ph}) "
                f"ORDER BY symbol ASC, date ASC", part,
            ).fetchall():
                d = dict(r)
                try:
                    close = float(d["close"])
                except Exception:
                    continue
                if not math.isfinite(close) or close <= 0:
                    continue
                bars.setdefault(d["symbol"], []).append({
                    "date": str(d["date"]),
                    "close": close,
                    "high": float(d[hi]) if hi and d[hi] is not None else close,
                    "low": float(d[lo]) if lo and d[lo] is not None else close,
                })
        return bars

    def _derive_regime(self, conn: Any, asof_date: str) -> str:
        """bullish / neutral / bearish from index breadth A/D, else unknown."""
        try:
            cols = {c[1] for c in conn.execute("PRAGMA table_info('nse_index_breadth')").fetchall()}
            if not cols:
                return "unknown"
            row = conn.execute(
                "SELECT MAX(date) AS d FROM nse_index_breadth WHERE date <= ?", (asof_date,)
            ).fetchone()
            if not row or not row["d"]:
                return "unknown"
            rows = conn.execute(
                "SELECT * FROM nse_index_breadth WHERE date = ?", (row["d"],)
            ).fetchall()
            ratios: List[float] = []
            for r in rows:
                d = dict(r)
                try:
                    adv, dec = d.get("advances_count"), d.get("declines_count")
                    if adv is not None and dec is not None and float(dec) > 0:
                        ratios.append(float(adv) / float(dec))
                    elif d.get("advance_decline_ratio") is not None:
                        ratios.append(float(d["advance_decline_ratio"]))
                except Exception:
                    continue
            if not ratios:
                return "unknown"
            ad = sum(ratios) / len(ratios)
            if ad >= 1.5:
                return "bullish"
            if ad <= 0.67:
                return "bearish"
            return "neutral"
        except Exception:
            return "unknown"

    def _investor_map(self, conn: Any, symbols: Sequence[str]) -> Dict[str, str]:
        """symbol -> promoter/FII/DII/retail from forensic holdings; default all."""
        out = {s: "all" for s in symbols}
        try:
            cols = {c[1] for c in conn.execute("PRAGMA table_info('company_forensic_health')").fetchall()}
            if not cols or "symbol" not in cols:
                return out
            for s in symbols:
                try:
                    r = conn.execute(
                        "SELECT * FROM company_forensic_health WHERE symbol = ? LIMIT 1", (s,)
                    ).fetchone()
                except Exception:
                    continue
                if not r:
                    continue
                d = dict(r)
                try:
                    holdings = [
                        ("promoter", float(d.get("promoter_holding_pct") or 0.0)),
                        ("FII", float(d.get("fii_holding_pct") or 0.0)),
                        ("DII", float(d.get("dii_holding_pct") or 0.0)),
                        ("retail", float(d.get("public_holding_pct") or 0.0)),
                    ]
                except Exception:
                    continue
                if all(h <= 0 for _, h in holdings):
                    continue
                out[s] = max(holdings, key=lambda kv: kv[1])[0]
        except Exception:
            pass
        return out

    def _dominant_lens_map(self, conn: Any) -> Dict[str, str]:
        """symbol -> dominant lens (max explain_power; 'all'-cohort preferred)."""
        out: Dict[str, str] = {}
        try:
            cols = {c[1] for c in conn.execute(
                "PRAGMA table_info('model_explainer_rankings')").fetchall()}
            if not cols:
                return out
            rows = [dict(r) for r in conn.execute(
                "SELECT stock_id, investor_majority, lens_family, explain_power, rank "
                "FROM model_explainer_rankings").fetchall()]
        except Exception:
            return out
        best: Dict[str, Tuple[float, str]] = {}
        fallback: Dict[str, Tuple[float, str]] = {}
        for r in rows:
            fam = r.get("lens_family")
            if fam not in LENS_FAMILIES:
                continue
            try:
                ep = float(r.get("explain_power") or 0.0)
            except Exception:
                continue
            # rank=1 short-circuits: it IS the dominant lens by definition.
            bonus = 1e9 if (r.get("rank") == 1) else 0.0
            key = str(r.get("stock_id"))
            slot = best if str(r.get("investor_majority")) == "all" else fallback
            cur = slot.get(key)
            if cur is None or (ep + bonus) > cur[0]:
                slot[key] = (ep + bonus, str(fam))
        for key, (_, fam) in best.items():
            out[key] = fam
        for key, (_, fam) in fallback.items():
            out.setdefault(key, fam)
        return out

    def _load_theses(self, asof_date: str, mode: str) -> List[Dict[str, Any]]:
        """Alpha theses for (date, mode); [] when the report file is absent."""
        day_dir = self.reports_dir / asof_date
        candidates = [day_dir / f"daily_alpha_{mode}.json", day_dir / "daily_alpha.json"]
        for path in candidates:
            try:
                if not path.exists():
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                theses = data.get("high_conviction_theses") or []
                return [t for t in theses if isinstance(t, dict)]
            except Exception:
                continue
        return []

    # ------------------------------------------------------------------
    # Public API: scoring
    # ------------------------------------------------------------------
    def score_predictions(
        self,
        asof_date: str,
        horizon_days: Sequence[int] = (5, 20, 60),
        mode: str = "ensemble",
        mode_symbols: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Score one prediction run and persist rows to model_validation_scores.

        Args:
            asof_date: prediction date (YYYY-MM-DD) present in eod_scrip_calls.
            horizon_days: trading-day horizons (per-symbol bars, not calendar).
            mode: 'ensemble' or 'legacy' — labels the rows and selects the
                thesis file (daily_alpha_{mode}.json).
            mode_symbols: symbols belonging to this run. Same-date rows mix
                modes, so when given only these symbols are scored.

        Returns a summary dict; persists rows even for partial horizons.
        """
        horizons = sorted({int(h) for h in horizon_days if int(h) > 0})
        if not horizons:
            raise ValueError("horizon_days must contain at least one positive horizon")
        self.repo.ensure_validation_schema()
        with self.db.session() as conn:
            preds = self._load_predictions(conn, asof_date, mode_symbols)
            if not preds:
                return {"asof_date": asof_date, "mode": mode, "horizons": {},
                        "rows_written": 0, "n_predictions": 0,
                        "note": "no predictions for asof_date"}
            symbols = [str(p["symbol"]) for p in preds if p.get("symbol")]
            bars = self._load_price_bars(conn, symbols)
            regime = self._derive_regime(conn, asof_date)
            investors = self._investor_map(conn, symbols)
            lenses = self._dominant_lens_map(conn)
        theses = self._load_theses(asof_date, mode)

        # Per-symbol base bar (last bar on/before asof) + forward closes.
        fwd: Dict[str, Dict[int, float]] = {}
        skipped: List[str] = []
        for p in preds:
            s = str(p["symbol"])
            blist = bars.get(s, [])
            idx0 = -1
            for i, b in enumerate(blist):
                if b["date"] <= asof_date:
                    idx0 = i
                else:
                    break
            if idx0 < 0:
                skipped.append(s)
                continue
            base = blist[idx0]["close"]
            per_h: Dict[int, float] = {}
            for h in horizons:
                j = idx0 + h
                if j < len(blist):
                    per_h[h] = blist[j]["close"] / base - 1.0
            if not per_h:
                skipped.append(s)
                continue
            fwd[s] = per_h

        def _score_of(p: Dict[str, Any]) -> Optional[float]:
            try:
                if p.get("composite_score") is not None:
                    return float(p["composite_score"])
            except Exception:
                pass
            try:
                if p.get("composite_rank") is not None:
                    return -float(p["composite_rank"])
            except Exception:
                pass
            return None

        records: List[Dict[str, Any]] = []
        horizon_summary: Dict[int, Dict[str, Any]] = {}
        scored_horizons: List[int] = []
        for h in horizons:
            have = [(p, fwd[str(p["symbol"])][h]) for p in preds
                    if str(p.get("symbol")) in fwd and h in fwd[str(p["symbol"])]]
            if not have:
                continue
            scored_horizons.append(h)
            uni = _mean([r for _, r in have])
            ranked = sorted(have, key=lambda t: (t[0].get("composite_rank") is None,
                                                 t[0].get("composite_rank") or 0))
            top = ranked[:TOP_N]
            top_mean = _mean([r for _, r in top])
            sx = [s for s, _ in (( _score_of(p), r) for p, r in have) if s is not None]
            sy = [r for p, r in have if _score_of(p) is not None]
            ic = _spearman(sx, sy)
            hits = [(1.0 if r > 0 else (0.0 if r < 0 else 0.5)) for _, r in have]
            row0: Dict[str, Any] = {
                "asof_date": asof_date, "horizon_days": h, "mode": mode,
                "lens_family": None, "regime_tag": regime, "investor_majority": "all",
                "n": len(have), "hit_rate": _mean(hits),
                "mean_fwd_ret": top_mean, "universe_mean_ret": uni, "ic": ic,
                "thesis_hit_rate": None, "thesis_n": None,
            }
            records.append(row0)
            # Investor-majority split (whole-cohort lens=NULL rows).
            cohorts: Dict[str, List[Tuple[Dict[str, Any], float]]] = {}
            for p, r in have:
                cohorts.setdefault(investors.get(str(p["symbol"]), "all"), []).append((p, r))
            for inv, items in sorted(cohorts.items()):
                if inv == "all":
                    continue
                ihits = [(1.0 if r > 0 else (0.0 if r < 0 else 0.5)) for _, r in items]
                iranked = sorted(items, key=lambda t: (t[0].get("composite_rank") is None,
                                                       t[0].get("composite_rank") or 0))
                records.append({
                    "asof_date": asof_date, "horizon_days": h, "mode": mode,
                    "lens_family": None, "regime_tag": regime, "investor_majority": inv,
                    "n": len(items), "hit_rate": _mean(ihits),
                    "mean_fwd_ret": _mean([r for _, r in iranked[:TOP_N]]),
                    "universe_mean_ret": uni, "ic": None,
                    "thesis_hit_rate": None, "thesis_n": None,
                })
            # Per-dominant-lens buckets (investor='all' rows).
            buckets: Dict[str, List[float]] = {}
            for p, r in have:
                fam = lenses.get(str(p["symbol"]))
                if fam in LENS_FAMILIES:
                    buckets.setdefault(fam, []).append(r)
            for fam in sorted(buckets):
                rs = buckets[fam]
                bhits = [(1.0 if r > 0 else (0.0 if r < 0 else 0.5)) for r in rs]
                records.append({
                    "asof_date": asof_date, "horizon_days": h, "mode": mode,
                    "lens_family": fam, "regime_tag": regime, "investor_majority": "all",
                    "n": len(rs), "hit_rate": _mean(bhits),
                    "mean_fwd_ret": _mean(rs), "universe_mean_ret": uni, "ic": None,
                    "thesis_hit_rate": None, "thesis_n": None,
                })
            horizon_summary[h] = {
                "n": len(have), "hit_rate": row0["hit_rate"],
                "mean_fwd_ret_top20": top_mean, "universe_mean_ret": uni, "ic": ic,
            }

        # Thesis hit (target-before-stop) — attach to largest scored horizon.
        thesis_rate: Optional[float] = None
        thesis_n = 0
        if theses and scored_horizons:
            window = min(max(scored_horizons), THESIS_WINDOW_CAP)
            outcomes: List[float] = []
            for t in theses:
                sym = str(t.get("symbol", ""))
                blist = bars.get(sym, [])
                entry = _parse_entry_mid(t.get("recommended_entry_range"),
                                         t.get("current_market_price"))
                try:
                    tgt = float(t.get("target_price")) if t.get("target_price") is not None else None
                    sl = float(t.get("stop_loss")) if t.get("stop_loss") is not None else None
                except Exception:
                    tgt, sl = None, None
                if entry is None or tgt is None or sl is None:
                    continue
                if not math.isfinite(entry) or entry <= 0:
                    continue
                direction = 1.0 if tgt >= entry else -1.0
                future = [b for b in blist if b["date"] > asof_date][:window]
                if not future:
                    continue
                thesis_n += 1
                hit = 0.0
                for b in future:
                    if direction > 0:
                        if b["low"] <= sl:
                            hit = 0.0
                            break
                        if b["high"] >= tgt:
                            hit = 1.0
                            break
                    else:
                        if b["high"] >= sl:
                            hit = 0.0
                            break
                        if b["low"] <= tgt:
                            hit = 1.0
                            break
                outcomes.append(hit)
            if outcomes:
                thesis_rate = float(sum(outcomes) / len(outcomes))
            for rec in records:
                if (rec["horizon_days"] == max(scored_horizons)
                        and rec["lens_family"] is None
                        and rec["investor_majority"] == "all"):
                    rec["thesis_hit_rate"] = thesis_rate
                    rec["thesis_n"] = thesis_n

        rows_written = self.repo.upsert_validation_scores(records)
        return {
            "asof_date": asof_date,
            "mode": mode,
            "regime_tag": regime,
            "n_predictions": len(preds),
            "n_scored": len(fwd),
            "skipped_no_forward_data": sorted(set(skipped)),
            "horizons": horizon_summary,
            "thesis_hit_rate": thesis_rate,
            "thesis_n": thesis_n,
            "rows_written": rows_written,
        }

    # ------------------------------------------------------------------
    # Calibration: empirical weights (proposal only) + deliberate apply
    # ------------------------------------------------------------------
    def fit_lens_weights(
        self,
        regime_tag: str,
        investor_majority: str = "all",
        horizon_days: Optional[Sequence[int]] = None,
    ) -> Dict[str, Any]:
        """Derive empirical lens weights from validation scores.

        Weight ∝ positive part of each lens's mean edge (``mean_fwd_ret -
        universe_mean_ret``) averaged over matching score rows, floored at
        ``EXPLAIN_FLOOR`` and normalized to sum 1 (returned dict uses
        largest-remainder rounding to 6 decimals so weights sum exactly 1.0).
        Writes a proposal row set to ``model_lens_weight_proposals``; NEVER
        updates ``model_explainer_rankings`` (see :meth:`apply_calibration`).
        """
        inv = str(investor_majority or "all")
        rows = self.repo.get_validation_scores(regime_tag=str(regime_tag),
                                               investor_majority=inv)
        lens_rows = [r for r in rows if r.get("lens_family") in LENS_FAMILIES]
        fallback_used = False
        if not lens_rows and inv != "all":
            rows = self.repo.get_validation_scores(regime_tag=str(regime_tag),
                                                   investor_majority="all")
            lens_rows = [r for r in rows if r.get("lens_family") in LENS_FAMILIES]
            fallback_used = True
        if horizon_days is not None:
            hs = {int(h) for h in horizon_days}
            lens_rows = [r for r in lens_rows if r.get("horizon_days") in hs]
        edges: Dict[str, float] = {}
        for fam in LENS_FAMILIES:
            vals = []
            for r in lens_rows:
                if r.get("lens_family") != fam:
                    continue
                try:
                    if r.get("mean_fwd_ret") is None or r.get("universe_mean_ret") is None:
                        continue
                    vals.append(float(r["mean_fwd_ret"]) - float(r["universe_mean_ret"]))
                except Exception:
                    continue
            edges[fam] = float(sum(vals) / len(vals)) if vals else 0.0
        pos = {fam: max(0.0, e) for fam, e in edges.items()}
        total = sum(pos.values())
        if total > 0:
            shares = {fam: v / total for fam, v in pos.items()}
        else:
            shares = {fam: 1.0 / len(LENS_FAMILIES) for fam in LENS_FAMILIES}
        floored = {fam: max(EXPLAIN_FLOOR, s) for fam, s in shares.items()}
        ftot = sum(floored.values())
        weights = {fam: floored[fam] / ftot for fam in LENS_FAMILIES}
        # Largest-remainder rounding to 6 decimals so returned weights sum to exactly 1.0.
        scaled = {fam: float(w) * 1_000_000 for fam, w in weights.items()}
        units = {fam: int(s) for fam, s in scaled.items()}
        remainders = {fam: scaled[fam] - units[fam] for fam in LENS_FAMILIES}
        leftover = 1_000_000 - sum(units.values())
        order = sorted(LENS_FAMILIES, key=lambda fam: remainders[fam], reverse=True)
        for i in range(leftover):
            units[order[i % len(order)]] += 1
        rounded_weights = {fam: units[fam] / 1_000_000 for fam in LENS_FAMILIES}
        basis = json.dumps({"edges": edges, "n_rows": len(lens_rows),
                            "fallback_to_all": fallback_used}, default=str)
        self.repo.upsert_lens_weight_proposals([
            {"regime_tag": str(regime_tag), "investor_majority": inv,
             "lens_family": fam, "weight": float(w), "basis_json": basis}
            for fam, w in weights.items()
        ])
        return {
            "regime_tag": str(regime_tag),
            "investor_majority": inv,
            "weights": rounded_weights,
            "edges": {fam: round(float(e), 6) for fam, e in edges.items()},
            "n_rows": len(lens_rows),
            "fallback_to_all": fallback_used,
        }

    def apply_calibration(
        self,
        proposal: Dict[str, Any],
        stock_ids: Optional[Sequence[Any]] = None,
        sector_id: Optional[Any] = None,
        geo_id: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Deliberately apply a proposal to ``model_explainer_rankings``.

        This is the ONLY path that mutates rankings from calibration output —
        it is never called automatically by scoring or fitting. Each
        (stock × lens) cell is written via ``EnsembleRanker.upsert_ranking``
        (which recomputes partition ranks). When ``stock_ids`` is omitted,
        every stock already present in ``model_explainer_rankings`` is updated.
        """
        from reality_engine.processing.ensemble_ranker import EnsembleRanker

        weights = dict(proposal.get("weights") or {})
        unknown = [f for f in weights if f not in LENS_FAMILIES]
        if unknown:
            raise ValueError(f"proposal has unknown lens families: {unknown}")
        if not weights:
            raise ValueError("proposal has no weights to apply")
        regime = proposal.get("regime_tag")
        inv = proposal.get("investor_majority", "all")
        if stock_ids is None:
            with self.db.session() as conn:
                try:
                    rows = conn.execute(
                        "SELECT DISTINCT stock_id FROM model_explainer_rankings").fetchall()
                    stock_ids = [r["stock_id"] for r in rows if r["stock_id"] is not None]
                except Exception:
                    stock_ids = []
        ranker = EnsembleRanker(self.db)
        n_rows = 0
        for stock in list(stock_ids or []):
            for fam, w in weights.items():
                ranker.upsert_ranking(stock, sector_id, geo_id, regime, inv,
                                      fam, p_value=None, explain_power=float(w))
                n_rows += 1
        return {"stocks_updated": len(list(stock_ids or [])),
                "rows_written": n_rows,
                "regime_tag": regime, "investor_majority": inv,
                "weights": weights}


# ----------------------------------------------------------------------
# Module-level convenience wrappers (default DB manager)
# ----------------------------------------------------------------------
def score_predictions(
    asof_date: str,
    horizon_days: Sequence[int] = (5, 20, 60),
    mode: str = "ensemble",
    mode_symbols: Optional[Sequence[str]] = None,
    manager: Optional[Any] = None,
    reports_dir: Optional[Any] = None,
) -> Dict[str, Any]:
    """Score one prediction run (see :meth:`ValidationHarness.score_predictions`)."""
    return ValidationHarness(manager, reports_dir).score_predictions(
        asof_date, horizon_days, mode, mode_symbols)


def fit_lens_weights(
    regime_tag: str,
    investor_majority: str = "all",
    horizon_days: Optional[Sequence[int]] = None,
    manager: Optional[Any] = None,
) -> Dict[str, Any]:
    """Fit empirical lens weights (proposal only; see harness method)."""
    return ValidationHarness(manager).fit_lens_weights(
        regime_tag, investor_majority, horizon_days)


def apply_calibration(
    proposal: Dict[str, Any],
    stock_ids: Optional[Sequence[Any]] = None,
    manager: Optional[Any] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Deliberately apply a calibration proposal to the rankings."""
    return ValidationHarness(manager).apply_calibration(
        proposal, stock_ids, **kwargs)
