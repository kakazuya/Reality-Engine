"""
Wave D3 — Continuous Self-Correction (EOD + Event).

Implements the continuous self-correction loop described in
tasks/next_wave_execution_plan.md §2 Wave D Task D3:

  * Cadence = EOD price + FII/DII + major event -- NOT intraday noise. Every correction
    batch runs only against a closed-session EOD date; an intraday/partial date is
    rejected so the brain never learns from sub-session chatter (AGENTS.md §3 #5).
  * Per-scrip learned noise floor (vol/liquidity adaptive) replaces the global hard
    cutoff. Learned floors persist in ``noise_floors`` and are reused by
    ``composite_screener`` via ``repository.get_per_scrip_noise_floor``.
  * Re-rank peer lenses with competitive survival (AGENTS.md §3 #7): explain_power is
    nudged UP for lenses that correctly predicted the realized direction and DOWN for
    losers, via ``ensemble_ranker.adjust_explain_power`` (which recomputes ranks).
  * Mutate embeddings (brain/transformer): the per-lens explanation_weight IS the
    embedding that competes; adjusting explain_power is the mutation. We also re-fire
    the MoE gate (temperature audit) so the pathway selection is revisable.
  * Update the dense substrate: drift between realized direction and the quality-moat
    substrate is detected and recorded; if ``update_substrate`` is set, the moat
    trajectory is nudged toward the realized regime (revisable, never a hard overwrite).
  * Event-driven correction (material news only): refresh the transient 2nd-order graph
    via ``event_graph`` and then revise the 2nd-order ripples (recompute significance,
    stamp revision_count), plus reinforce the policy_macro / supply_chain lenses for the
    event's impacted symbols.

Design rules honoured: SQLite fallback compatible (uses ``db_manager.session``); PG-aware
graceful fallbacks; no edits to other waves' modules -- this module owns ONLY
``eod_corrector.py`` and the additive repository helpers it depends on.

CLI wrappers ``cmd_correct_eod`` / ``cmd_correct_event`` / ``cmd_noise_floor`` are exposed
for later wiring into ``cli.py`` (this module does NOT edit ``cli.py``).
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("reality_engine.eod_corrector")

# Lens-family constants mirror ensemble_ranker / composite_screener (imported lazily to
# avoid an import cycle at module load time). Kept here for self-containment.
LENS_FAMILY_FACTOR = "factor_statistical"
LENS_FAMILY_QUALITY = "business_quality"
LENS_FAMILY_POLICY = "policy_macro"
LENS_FAMILY_SUPPLY = "supply_chain"
LENS_FAMILIES: Tuple[str, ...] = (
    LENS_FAMILY_FACTOR,
    LENS_FAMILY_QUALITY,
    LENS_FAMILY_POLICY,
    LENS_FAMILY_SUPPLY,
)

# Competitive-survival deltas (explain_power units). Tuned to be clearly observable in a
# single EOD batch while bounded so repeated batches cannot blow up the weights.
_REWARD = 0.05      # correct prediction -> reinforce
_PENALTY = 0.05     # wrong prediction  -> decay
_EXPLAIN_CAP = 2.0  # hard ceiling on explain_power after any adjustment

# Event-driven correction reinforces the macro/policy/supply lenses (an event is a
# macro signal) and lightly penalizes the pure factor lens.
_EVENT_POLICY_REWARD = 0.06
_EVENT_SUPPLY_REWARD = 0.04
_EVENT_FACTOR_PENALTY = 0.02

# Noise-floor learn parameters (vol/liquidity adaptive).
_FLOOR_BASE = 45.0
_FLOOR_MIN = 30.0
_FLOOR_MAX = 80.0


class EODCorrector:
    """Continuous self-correction engine (EOD price + FII/DII + major event)."""

    def __init__(self, manager: Optional[Any] = None):
        if manager is None:
            from reality_engine.db.database import db_manager
            manager = db_manager
        self.db = manager
        from reality_engine.db.repository import Repository
        self.repo = Repository(self.db)
        from reality_engine.processing.ensemble_ranker import EnsembleRanker
        self.ranker = EnsembleRanker(self.db)
        # Lazy composite_screener import (used only for the noise-floor + substrate
        # signal lookups; we never mutate it). Wrapped so a missing module is non-fatal.
        self._composite = None
        try:
            from reality_engine.processing.composite_screener import composite_screener
            self._composite = composite_screener
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("composite_screener unavailable: %s", exc)

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------
    def correct_eod(
        self,
        universe: Any = "nifty200",
        target_date: Optional[str] = None,
        dry_run: bool = False,
        update_substrate: bool = False,
        symbols: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Run an EOD self-correction batch for ``universe`` on ``target_date``.

        Cadence guard: requires a closed-session EOD date (daily_price_delivery has rows
        for it). An intraday/partial date raises ``ValueError`` -- the brain never learns
        from sub-session noise.

        For each symbol:
          * learn a vol/liquidity-adaptive per-scrip noise floor;
          * re-rank peer lenses by competitive survival (correct lens -> reward, loser ->
            penalty) using the realized EOD direction;
          * re-fire the MoE gate (temperature audit) so the pathway is revisable;
          * detect substrate drift (realized vs quality-moat substrate).

        Returns a summary dict:
          {universe, target_date, dry_run, symbols_corrected, noise_floors_updated,
           lens_rank_changes, substrate_drifts, details}
        """
        self.repo.ensure_eod_corrector_schema(self.db)
        self.ranker.ensure_schema()

        target_date = target_date or self.repo.get_latest_price_delivery_date()
        if not target_date:
            raise ValueError("correct_eod: no EOD price data available to anchor the batch.")
        # --- Cadence gate: must be a real closed-session EOD date, not intraday noise.
        self._require_eod_session(target_date)

        sym_list = list(symbols) if symbols else self._resolve_universe(universe)
        if not sym_list:
            return self._empty_summary("eod", universe, target_date, dry_run,
                                       "universe resolved to zero symbols")

        symbols_corrected = 0
        noise_floors_updated = 0
        lens_rank_changes = 0
        substrate_drifts: List[str] = []
        per_symbol: List[Dict[str, Any]] = []

        for sym in sym_list:
            eod = self._get_eod_row(sym, target_date)
            if not eod:
                # No EOD row for this symbol on the closed date -> cannot correct it.
                continue
            realized_dir = self._sign(eod.get("change_pct"))
            if realized_dir == 0:
                # Flat session: nothing to learn direction from; still learn the floor.
                pass

            # 1. Learn + persist the per-scrip noise floor.
            realized_vol = self._compute_realized_volatility(sym, target_date)
            liquidity = float(eod.get("turnover_lacs") or 0.0)
            floor = self._learn_noise_floor(realized_vol, liquidity)
            if not dry_run:
                self.repo.set_per_scrip_noise_floor(
                    sym, floor, realized_vol=realized_vol,
                    liquidity=liquidity, sample_days=self._vol_window,
                )
                noise_floors_updated += 1

            # 2. Re-rank lenses (competitive survival).
            rank_changes = self._re_rank_lenses(
                sym, realized_dir, dry_run=dry_run,
                prev_change=self._get_prev_day_change(sym, target_date),
            )
            lens_rank_changes += rank_changes

            # 3. Re-fire MoE gate (temperature audit) -> revisable pathway.
            if not dry_run:
                try:
                    self.ranker.fire_lenses(
                        temperature=0.4,
                        context={"stock": sym, "date": target_date},
                        seed=abs(hash(sym)) % (2 ** 31),
                    )
                except Exception as exc:  # pragma: no cover - audit best-effort
                    logger.debug("MoE re-fire for %s skipped: %s", sym, exc)

            # 4. Substrate drift detection (realized vs quality-moat substrate).
            drift = self._detect_substrate_drift(sym, realized_dir, update_substrate and not dry_run)
            if drift:
                substrate_drifts.append(drift)

            symbols_corrected += 1
            per_symbol.append({
                "symbol": sym,
                "realized_direction": realized_dir,
                "noise_floor": round(floor, 4),
                "realized_vol": round(realized_vol, 6),
                "liquidity": liquidity,
                "lens_rank_changes": rank_changes,
            })

        if not dry_run:
            self.repo.log_eod_correction(
                correction_type="eod",
                universe=str(universe),
                target_date=target_date,
                symbols_corrected=symbols_corrected,
                noise_floors_updated=noise_floors_updated,
                lens_rank_changes=lens_rank_changes,
                details={"symbols": per_symbol, "substrate_drifts": substrate_drifts},
                manager=self.db,
            )

        return {
            "universe": str(universe),
            "target_date": target_date,
            "dry_run": bool(dry_run),
            "symbols_corrected": symbols_corrected,
            "noise_floors_updated": noise_floors_updated,
            "lens_rank_changes": lens_rank_changes,
            "substrate_drifts": substrate_drifts,
            "details": per_symbol,
        }

    def correct_event(
        self,
        event_id: str,
        symbols: Optional[Sequence[str]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Event-driven correction (material news only).

        Revises the 2nd-order graph for ``event_id`` and re-ranks the lenses of the
        event's impacted symbols. Steps:
          1. Refresh the transient graph from the latest event nuance via ``event_graph``
             (re-quantizes the 2nd-order forward/back supply chain). Skipped gracefully
             for unknown events that have no registered spawner.
          2. Revise the 2nd-order ripples (``repository.apply_event_revision``): recompute
             significance_rank via the causal S formula and stamp ``revision_count``.
          3. Reinforce policy_macro / supply_chain lenses and lightly penalize the pure
             factor lens for each impacted symbol (event = macro/supply signal).

        Returns a summary dict including the revision + re-rank deltas.
        """
        self.repo.ensure_eod_corrector_schema(self.db)
        self.ranker.ensure_schema()

        # 1. Refresh the transient graph (re-quantize 2nd-order). Material news only.
        respawn = None
        try:
            from reality_engine.processing.event_graph import spawn_event_graph
            respawn = spawn_event_graph(event_id, manager=self.db)
        except NotImplementedError:
            # Unknown transient event: rely on any existing ripples in the substrate.
            logger.debug("correct_event: no spawner for %s; revising existing ripples", event_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("correct_event respawn skipped: %s", exc)

        # 2. Revise the 2nd-order graph.
        revision = self.repo.apply_event_revision(event_id, manager=self.db)

        # 3. Re-rank impacted symbols' lenses (event = macro/policy/supply signal).
        impacted = list(symbols) if symbols else []
        if not impacted:
            impacted = self._symbols_from_event(event_id)
        lens_changes = 0
        rerank_detail: List[Dict[str, Any]] = []
        if not dry_run:
            for sym in impacted:
                self._ensure_ranking_rows(sym)
                before = {f: self._current_explain_power(sym, f) for f in LENS_FAMILIES}
                self.ranker.adjust_explain_power(sym, None, None, None, "all",
                                                 LENS_FAMILY_POLICY, delta=_EVENT_POLICY_REWARD)
                self.ranker.adjust_explain_power(sym, None, None, None, "all",
                                                 LENS_FAMILY_SUPPLY, delta=_EVENT_SUPPLY_REWARD)
                self.ranker.adjust_explain_power(sym, None, None, None, "all",
                                                 LENS_FAMILY_FACTOR, delta=-_EVENT_FACTOR_PENALTY)
                after = {f: self._current_explain_power(sym, f) for f in LENS_FAMILIES}
                changed = sum(1 for f in LENS_FAMILIES if before[f] != after[f])
                lens_changes += changed
                rerank_detail.append({"symbol": sym, "before": before, "after": after})
        else:
            # Dry-run: report the intended direction without writing.
            rerank_detail = [{"symbol": s, "intended": "policy_macro/supply_chain up, factor down"}
                             for s in impacted]

        if not dry_run:
            self.repo.log_eod_correction(
                correction_type="event",
                event_id=event_id,
                symbols_corrected=len(impacted),
                lens_rank_changes=lens_changes,
                details={"revision": revision, "rerank": rerank_detail,
                         "respawned": bool(respawn)},
                manager=self.db,
            )

        return {
            "event_id": event_id,
            "dry_run": bool(dry_run),
            "graph_respawned": bool(respawn),
            "ripple_revision": revision,
            "impacted_symbols": impacted,
            "lens_rank_changes": lens_changes,
            "rerank_detail": rerank_detail,
        }

    def get_noise_floor(
        self,
        symbol: str,
        turnover_lacs: Optional[float] = None,
        change_pct: Optional[float] = None,
        realized_vol: Optional[float] = None,
    ) -> float:
        """Return the vol/liquidity-adaptive per-scrip noise floor for ``symbol``.

        If a floor has been learned (``noise_floors`` table), return it. Otherwise compute
        the deterministic adaptive floor from ``composite_screener.get_per_scrip_noise_floor``
        (or the local learner when no DB substrate is available). This is per-scrip and
        adaptive, never a global hard cutoff.
        """
        learned = self.repo.get_per_scrip_noise_floor(symbol)
        if learned is not None:
            return float(learned)
        # No learned floor yet -> compute the deterministic adaptive stub.
        if self._composite is not None:
            try:
                return float(self._composite.get_per_scrip_noise_floor(
                    symbol,
                    turnover_lacs=float(turnover_lacs if turnover_lacs is not None else 200.0),
                    change_pct=float(change_pct if change_pct is not None else 0.0),
                    volatility_proxy=realized_vol,
                ))
            except Exception:
                pass
        # Last-resort local learner (no composite_screener): pure vol/illiquidity model.
        return float(self._learn_noise_floor(realized_vol or 0.0, float(turnover_lacs or 0.0)))

    # ------------------------------------------------------------------
    # Cadence / universe helpers
    # ------------------------------------------------------------------
    def _require_eod_session(self, target_date: str) -> None:
        """Raise ``ValueError`` unless ``target_date`` is a closed-session EOD date.

        Prevents the self-correction loop from learning from intraday/sub-session noise
        (AGENTS.md §3 #5: correct EOD + FII/DII + event, NOT intraday 99% noise).
        """
        try:
            with self.db.session() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM daily_price_delivery WHERE date = ?",
                    (target_date,),
                ).fetchone()
                has = bool(row and row["c"])
        except Exception:
            has = False
        if not has:
            raise ValueError(
                f"correct_eod requires a closed-session EOD date with daily_price_delivery "
                f"rows for {target_date!r}; intraday/partial sessions are not corrected."
            )

    def _resolve_universe(self, universe: Any) -> List[str]:
        """Map a universe selector to a list of symbols (graceful SQLite/PG fallback)."""
        if isinstance(universe, (list, tuple, set)):
            return [str(s) for s in universe if s]
        u = str(universe).lower().strip()
        try:
            if u in ("nifty200", "nifty 200", "nifty200_universe"):
                comps = self.repo.get_nifty200_companies()
            elif u in ("all", "*", "universe_all"):
                comps = self.repo.get_all_companies()
            else:
                # Treat as a single symbol/isin.
                comps = self.repo.get_company_by_symbol(universe)
                return [str(universe).upper()] if comps else [str(universe).upper()]
            syms = []
            for c in comps:
                s = c.get("nse_symbol") or c.get("symbol") or c.get("bse_code")
                if s:
                    syms.append(str(s).upper())
            return syms
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("universe resolution failed: %s", exc)
            return [str(universe).upper()] if universe else []

    # ------------------------------------------------------------------
    # Noise-floor learning
    # ------------------------------------------------------------------
    def _compute_realized_volatility(self, symbol: str, target_date: Optional[str] = None,
                                     window: int = 20) -> float:
        """Realized volatility proxy from daily close returns (annualized fraction).

        Falls back to the single-day |change_pct| when fewer than two history points exist
        so the learner still produces an adaptive value on minimal test data.
        """
        self._vol_window = min(window, max(2, window))
        try:
            hist = self.repo.get_price_history(symbol, limit=window + 1)
            if hist is None or len(hist) < 2:
                eod = self._get_eod_row(symbol, target_date)
                cp = abs(float(eod.get("change_pct") or 0.0)) if eod else 0.0
                return cp / 100.0
            closes = [float(r.get("close") or 0.0) for r in hist if (r.get("close") is not None)]
            if len(closes) < 2:
                return 0.0
            rets = []
            for i in range(1, len(closes)):
                if closes[i - 1]:
                    rets.append((closes[i] - closes[i - 1]) / closes[i - 1])
            if not rets:
                return 0.0
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / len(rets)
            daily = math.sqrt(var)
            return daily * math.sqrt(252)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("realized vol for %s failed: %s", symbol, exc)
            return 0.0

    def _learn_noise_floor(self, realized_vol: float, liquidity: float) -> float:
        """Vol/liquidity-adaptive noise floor.

        Higher realized vol and lower liquidity => a stronger composite signal is required
        before a name clears (higher floor). Clamped to [``_FLOOR_MIN``, ``_FLOOR_MAX``].
        """
        vol_comp = min(25.0, abs(realized_vol) * 100.0 * 0.6)
        liq = float(liquidity or 0.0)
        illiq_comp = max(0.0, (100.0 - liq) / 100.0 * 15.0)
        floor = _FLOOR_BASE + vol_comp + illiq_comp
        return float(max(_FLOOR_MIN, min(_FLOOR_MAX, floor)))

    # ------------------------------------------------------------------
    # Lens re-ranking (competitive survival)
    # ------------------------------------------------------------------
    def _re_rank_lenses(
        self,
        symbol: str,
        realized_dir: int,
        dry_run: bool = False,
        prev_change: Optional[float] = None,
    ) -> int:
        """Adjust each lens's explain_power by competitive survival and report # changes.

        For every lens family we derive its *predicted* direction from the densest
        available substrate signal (factor->prior-day price action; quality->moat score;
        policy->macro ENI; supply->ripple significance). If the prediction matches the
        realized EOD direction we reward it; if it conflicts we penalize it; if the
        substrate carries no signal we stay neutral (no change). Returns the number of
        families whose explain_power actually moved.
        """
        self._ensure_ranking_rows(symbol)
        before = {f: self._current_explain_power(symbol, f) for f in LENS_FAMILIES}

        predicted = {
            LENS_FAMILY_FACTOR: self._predict_factor(symbol, prev_change),
            LENS_FAMILY_QUALITY: self._predict_quality(symbol),
            LENS_FAMILY_POLICY: self._predict_policy(symbol),
            LENS_FAMILY_SUPPLY: self._predict_supply(symbol),
        }
        for fam, pred in predicted.items():
            delta = 0.0
            if pred != 0 and realized_dir != 0:
                delta = _REWARD if pred == realized_dir else -_PENALTY
            elif pred != 0 and realized_dir == 0:
                # Flat session: slightly relax conviction (no directional evidence).
                delta = -_PENALTY * 0.5
            if delta != 0.0 and not dry_run:
                # Clamp the post-adjustment explain_power to [0, _EXPLAIN_CAP] so repeated
                # EOD batches cannot let a lens dominate the brain unboundedly.
                cur = before[fam] or 0.0
                new_val = max(0.0, min(_EXPLAIN_CAP, cur + delta))
                clamped_delta = new_val - cur
                if clamped_delta != 0.0:
                    self.ranker.adjust_explain_power(symbol, None, None, None, "all", fam, delta=clamped_delta)

        after = {f: self._current_explain_power(symbol, f) for f in LENS_FAMILIES}
        return sum(1 for f in LENS_FAMILIES if before[f] != after[f])

    def _predict_factor(self, symbol: str, prev_change: Optional[float]) -> int:
        """Factor/statistical lens predicted direction = sign of prior-day change (momentum)."""
        if prev_change is not None:
            return self._sign(prev_change)
        # No explicit prior given: derive from price history.
        try:
            hist = self.repo.get_price_history(symbol, limit=3)
            if hist and len(hist) >= 2:
                prev = hist[-2]
                return self._sign(prev.get("change_pct"))
        except Exception:
            pass
        return 0

    def _predict_quality(self, symbol: str) -> int:
        """Business-quality lens predicted direction = sign(moat_score - 3.0)."""
        try:
            m = self.repo.get_moat_evaluation(symbol)
            if m and m.get("total_moat_score") is not None:
                return self._sign(float(m["total_moat_score"]) - 3.0)
        except Exception:
            pass
        return 0

    def _predict_policy(self, symbol: str) -> int:
        """Policy/macro lens predicted direction = sign(aggregate regulatory ENI).

        Queries the ACTIVE database (``self.db``), not the global composite_screener repo, so
        the correction stays isolated to the substrate it is correcting (deterministic in
        tests, correct in production). ``regulatory_political_risks`` carries ``ticker`` and
        ``symbol`` columns directly (no ``companies`` join needed), so the prediction works on
        both the PostgreSQL and the SQLite WAL fallback. Returns 0 (neutral) when no policy
        signal exists.
        """
        try:
            with self.db.session() as conn:
                row = conn.execute(
                    """
                    SELECT COALESCE(SUM(severity_score * probability), 0) AS eni
                    FROM regulatory_political_risks
                    WHERE ticker = ? OR symbol = ?
                    """,
                    (symbol, symbol),
                ).fetchone()
                if row is not None and row["eni"] is not None:
                    return self._sign(row["eni"])
        except Exception:
            pass
        return 0

    def _predict_supply(self, symbol: str) -> int:
        """Supply-chain lens predicted direction = sign(ripple significance - 50).

        Queries the ACTIVE database (``self.db``) so the correction stays isolated to the
        substrate it is correcting. ``ripple_effects.target_company_id`` is an integer
        ``company_id``; the symbol is bridged to ``company_id`` via ``financial_metrics``
        (``company_id``, ``symbol``) and ``moat_evaluations`` (``company_id``, ``ticker``)
        -- there is no ``companies`` table on the SQLite WAL fallback, so we bridge directly
        off the peer tables that already carry both keys. Returns 0 (neutral) when no supply
        signal exists.
        """
        try:
            with self.db.session() as conn:
                row = conn.execute(
                    """
                    SELECT COALESCE(MAX(r.significance_rank), 0) AS s
                    FROM ripple_effects r
                    WHERE r.target_company_id IN (
                        SELECT company_id FROM financial_metrics WHERE symbol = ?
                        UNION
                        SELECT company_id FROM moat_evaluations WHERE ticker = ?
                    )
                    """,
                    (symbol, symbol),
                ).fetchone()
                if row is not None and row["s"] is not None:
                    return self._sign(float(row["s"]) - 50.0)
        except Exception:
            pass
        return 0

    def _detect_substrate_drift(self, symbol: str, realized_dir: int, update: bool) -> Optional[str]:
        """Detect a divergence between realized direction and the quality substrate.

        If a strong negative realized move contradicts a bullish moat substrate (or vice
        versa), record it. With ``update`` True, nudge the moat trajectory toward the
        realized regime (revisable, never a hard overwrite).
        """
        if realized_dir == 0:
            return None
        try:
            m = self.repo.get_moat_evaluation(symbol)
            if not m:
                return None
            traj = str(m.get("moat_trajectory") or "Stable")
            score = float(m.get("total_moat_score") or 0.0)
            # Bullish substrate: high score or Expanding trajectory.
            substrate_bullish = (score >= 3.0) or (traj == "Expanding")
            # Strong realized move: |change_pct| implies a clear direction.
            eod = self._get_eod_row(symbol, None)
            move = abs(float(eod.get("change_pct") or 0.0)) if eod else 0.0
            if move < 3.0:
                return None  # not a strong enough move to flag drift
            if substrate_bullish and realized_dir < 0:
                drift = f"{symbol}:bullish_substrate_vs_bearish_price"
            elif (not substrate_bullish) and realized_dir > 0:
                drift = f"{symbol}:bearish_substrate_vs_bullish_price"
            else:
                return None
            if update:
                new_traj = "Expanding" if realized_dir > 0 else "Deteriorating"
                try:
                    with self.db.session() as conn:
                        conn.execute(
                            "UPDATE moat_evaluations SET moat_trajectory=? WHERE ticker=? OR isin=?",
                            (new_traj, symbol, symbol),
                        )
                except Exception:
                    pass
            return drift
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Low-level DB helpers (per-scrip, transaction-safe via db_manager.session)
    # ------------------------------------------------------------------
    def _get_eod_row(self, symbol: str, target_date: Optional[str]) -> Optional[Dict[str, Any]]:
        date_filter = target_date
        if date_filter is None:
            date_filter = self.repo.get_latest_price_delivery_date()
        if not date_filter:
            return None
        try:
            with self.db.session() as conn:
                row = conn.execute(
                    "SELECT * FROM daily_price_delivery WHERE symbol = ? AND date = ? LIMIT 1",
                    (symbol, date_filter),
                ).fetchone()
                return dict(row) if row else None
        except Exception:
            return None

    def _get_prev_day_change(self, symbol: str, target_date: str) -> Optional[float]:
        """Return the change_pct of the trading day immediately before ``target_date``."""
        try:
            with self.db.session() as conn:
                row = conn.execute(
                    "SELECT change_pct FROM daily_price_delivery "
                    "WHERE symbol = ? AND date < ? ORDER BY date DESC LIMIT 1",
                    (symbol, target_date),
                ).fetchone()
                if row and row["change_pct"] is not None:
                    return float(row["change_pct"])
        except Exception:
            pass
        return None

    def _ensure_ranking_rows(self, symbol: str) -> None:
        """Ensure all four lens families have a ranking row (seed bootstrap if absent)."""
        from reality_engine.processing.ensemble_ranker import BOOTSTRAP_ENSEMBLE_WEIGHTS
        for fam in LENS_FAMILIES:
            cur = self._current_explain_power(symbol, fam)
            if cur is None:
                self.ranker.upsert_ranking(
                    symbol, None, None, None, "all", fam,
                    p_value=None, explain_power=float(BOOTSTRAP_ENSEMBLE_WEIGHTS.get(fam, 0.25)),
                )

    def _current_explain_power(self, symbol: str, fam: str) -> Optional[float]:
        rows = self.ranker.get_rankings(symbol, "all")
        for r in rows:
            if r.get("lens_family") == fam:
                return float(r.get("explain_power") or 0.0)
        return None

    def _symbols_from_event(self, event_id: str) -> List[str]:
        """Resolve symbols impacted by an event via ripple_effects -> peer-table bridge.

        ``ripple_effects.target_company_id`` is an integer ``company_id``. The symbol is
        bridged off the peer tables that already carry both ``company_id`` and a symbol/ticker
        (``financial_metrics.symbol`` / ``moat_evaluations.ticker``); there is no ``companies``
        table on the SQLite WAL fallback, so we bridge directly. Sector/industry-targeted
        ripples (``target_company_id IS NULL``) resolve to no company symbols here -- callers
        may pass an explicit ``symbols`` list to ``correct_event`` to reinforce those.
        """
        out: List[str] = []
        try:
            with self.db.session() as conn:
                rows = conn.execute(
                    """
                    SELECT DISTINCT sym FROM (
                        SELECT fm.symbol AS sym
                        FROM ripple_effects r
                        JOIN financial_metrics fm ON fm.company_id = r.target_company_id
                        WHERE r.event_id = ? AND r.target_company_id IS NOT NULL
                        UNION
                        SELECT m.ticker AS sym
                        FROM ripple_effects r
                        JOIN moat_evaluations m ON m.company_id = r.target_company_id
                        WHERE r.event_id = ? AND r.target_company_id IS NOT NULL
                    )
                    """,
                    (event_id, event_id),
                ).fetchall()
                for r in rows:
                    if r["sym"]:
                        out.append(str(r["sym"]).upper())
        except Exception:
            pass
        return out

    @staticmethod
    def _sign(x: Any) -> int:
        try:
            v = float(x)
        except (TypeError, ValueError):
            return 0
        if v > 0:
            return 1
        if v < 0:
            return -1
        return 0

    @staticmethod
    def _empty_summary(kind: str, universe: Any, target_date: Optional[str], dry_run: bool, note: str):
        return {
            "universe": str(universe),
            "target_date": target_date,
            "dry_run": bool(dry_run),
            "symbols_corrected": 0,
            "noise_floors_updated": 0,
            "lens_rank_changes": 0,
            "substrate_drifts": [],
            "note": note,
            "details": [],
        }


# ----------------------------------------------------------------------
# Module-level convenience
# ----------------------------------------------------------------------
_default_corrector: Optional[EODCorrector] = None


def get_default_corrector() -> EODCorrector:
    global _default_corrector
    if _default_corrector is None:
        _default_corrector = EODCorrector()
    return _default_corrector


# ----------------------------------------------------------------------
# CLI wrappers (importable by cli.py; this module does NOT edit cli.py)
# ----------------------------------------------------------------------
def cmd_correct_eod(args) -> Dict[str, Any]:
    """CLI handler for ``correct-eod --universe nifty200 [--date YYYY-MM-DD] [--dry-run]``.

    ``args`` is expected to expose: universe (str), date (Optional[str]), dry_run (bool),
    symbols (Optional[str] comma-separated), update-substrate (bool). Missing attributes
    fall back to sensible defaults.
    """
    universe = getattr(args, "universe", "nifty200")
    target_date = getattr(args, "date", None) or getattr(args, "target_date", None)
    dry_run = bool(getattr(args, "dry_run", False))
    update_substrate = bool(getattr(args, "update_substrate", False))
    symbols = getattr(args, "symbols", None)
    sym_list = None
    if symbols:
        sym_list = [s.strip().upper() for s in str(symbols).split(",") if s.strip()]

    corrector = get_default_corrector()
    result = corrector.correct_eod(
        universe=universe,
        target_date=target_date,
        dry_run=dry_run,
        update_substrate=update_substrate,
        symbols=sym_list,
    )
    print(json.dumps(result, indent=2, default=str))
    return result


def cmd_correct_event(args) -> Dict[str, Any]:
    """CLI handler for ``correct-event --event US_TARIFF_TEXTILE_RELIEF [--symbols HAL]``."""
    event_id = getattr(args, "event", None) or getattr(args, "event_id", None)
    if not event_id:
        raise SystemExit("correct-event requires --event <event_id>")
    dry_run = bool(getattr(args, "dry_run", False))
    symbols = getattr(args, "symbols", None)
    sym_list = None
    if symbols:
        sym_list = [s.strip().upper() for s in str(symbols).split(",") if s.strip()]

    corrector = get_default_corrector()
    result = corrector.correct_event(event_id, symbols=sym_list, dry_run=dry_run)
    print(json.dumps(result, indent=2, default=str))
    return result


def cmd_noise_floor(args) -> float:
    """CLI handler for ``noise-floor --symbol TITAGARH [--turnover N] [--change N]``."""
    symbol = getattr(args, "symbol", None) or getattr(args, "symbols", None)
    if not symbol:
        raise SystemExit("noise-floor requires --symbol <SYMBOL>")
    turnover = getattr(args, "turnover", None)
    change = getattr(args, "change", None)
    corrector = get_default_corrector()
    floor = corrector.get_noise_floor(
        str(symbol).upper(),
        turnover_lacs=float(turnover) if turnover is not None else None,
        change_pct=float(change) if change is not None else None,
    )
    print(f"{str(symbol).upper()} noise_floor = {floor}")
    return floor
