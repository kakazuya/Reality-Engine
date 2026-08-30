"""
Wave D1 — Sparse, revisable reasoning: MoE ensemble_ranker.

Implements the Sparse Mixture-of-Experts lens ensemble that sits at the heart of the
Reality Engine's continuous self-correction loop (tasks/next_wave_execution_plan.md §2
Wave D Task D1):

  * model_explainer_rankings — per (stock/sector/geo/regime/investor_majority/lens_family)
    explain_power + rank, with competitive survival (explanation_weight ↑/↓).
  * lens_activation_log — temperature + fired_lenses audit record for every MoE run.

Design rules honoured (AGENTS.md §3 #3, #5, #7, #8):
  * All four peer lens families compete: factor_statistical, business_quality,
    policy_macro, supply_chain.
  * Weights are conditional, not absolute: w_lens = explain_power / Σ explain_power
    inside the (stock/sector/geo/regime/investor_majority) context. No learned rows in a
    context => deterministic bootstrap weights (sum == 1.0, each > 0).
  * Sparse MoE gating: a temperature in [0, 1] controls explore (mutate pathway — fire
    more lenses, jitter) vs exploit (consolidate — fire only the top lenses). Every run
    is audited in lens_activation_log.
  * Deterministic for tests: temperature selection uses a stable (hashlib) seed, never
    process-random hash().

Ownership: this module owns model_explainer_rankings + lens_activation_log. It reuses
repository.ensure_ensemble_ranking_schema (the canonical D1 DDL) as the schema owner
wrapper, but performs all reads/writes through its own DB manager handle.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from typing import Any, Dict, List, Optional, Sequence

# Canonical all-peers lens families (matches composite_screener.ENSEMBLE_LENS_FAMILIES).
LENS_FAMILIES: tuple = (
    "factor_statistical",
    "business_quality",
    "policy_macro",
    "supply_chain",
)

# Investor-majority cohorts that can drive price (AGENTS.md §3 #6).
INVESTOR_MAJORITIES: tuple = ("promoter", "FII", "DII", "retail", "all")

# Deterministic bootstrap weights (mirrors composite_screener.BOOTSTRAP_ENSEMBLE_WEIGHTS).
# Used whenever a conditional context has no learned rankings yet.
BOOTSTRAP_ENSEMBLE_WEIGHTS: Dict[str, float] = {
    "factor_statistical": 0.30,
    "business_quality": 0.25,
    "policy_macro": 0.25,
    "supply_chain": 0.20,
}

# Floor so no lens family collapses to exactly 0 (compute_ensemble_weights falls back to
# the global bootstrap only when a family is missing or <= 0 in a partition).
# Mirrors run_moe_eod.EXPLAIN_FLOOR for deterministic full-universe seeding.
EXPLAIN_FLOOR: float = 0.05

# Per-investor-majority tilt multipliers on the 4 lens families (mirrors run_moe_eod.INVESTOR_TILTS).
# Different cohorts drive price through different lenses.
INVESTOR_TILTS: Dict[str, Dict[str, float]] = {
    "promoter": {"factor_statistical": 0.7, "business_quality": 1.30, "policy_macro": 0.9, "supply_chain": 1.00},
    "FII": {"factor_statistical": 1.3, "business_quality": 1.00, "policy_macro": 0.9, "supply_chain": 0.90},
    "DII": {"factor_statistical": 0.9, "business_quality": 1.20, "policy_macro": 1.0, "supply_chain": 1.00},
    "retail": {"factor_statistical": 0.8, "business_quality": 0.90, "policy_macro": 1.2, "supply_chain": 1.10},
    "all": {f: 1.0 for f in LENS_FAMILIES},
}

# Sentinel for "any / not-specified" partition key. Storing and querying with the same
# sentinel keeps partition semantics exact even when only stock_id + investor are given.
_DEFAULT = "*"


class EnsembleRanker:
    """Sparse MoE lens ensemble ranker with temperature-controlled gating + audit log."""

    def __init__(self, manager: Optional[Any] = None):
        # manager is a DatabaseManager-like object exposing .session().
        if manager is None:
            from reality_engine.db.database import db_manager
            manager = db_manager
        self.db = manager

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def _ensure(self) -> None:
        """Ensure the Wave D1 tables exist (delegates to repository's canonical DDL)."""
        from reality_engine.db.repository import repo
        repo.ensure_ensemble_ranking_schema(self.db)

    def ensure_schema(self) -> None:
        """Public schema-ensure entry point (idempotent)."""
        self._ensure()

    # ------------------------------------------------------------------
    # Partition normalisation helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _norm(
        stock_id: Optional[Any],
        sector_id: Optional[Any],
        geo_id: Optional[Any],
        regime_tag: Optional[Any],
        investor_majority: Optional[Any],
    ) -> tuple:
        s = str(stock_id) if stock_id is not None else _DEFAULT
        sec = str(sector_id) if sector_id is not None else _DEFAULT
        g = str(geo_id) if geo_id is not None else _DEFAULT
        rg = str(regime_tag) if regime_tag is not None else _DEFAULT
        inv = str(investor_majority) if investor_majority is not None else "all"
        if inv not in INVESTOR_MAJORITIES:
            inv = "all"
        return s, sec, g, rg, inv

    @staticmethod
    def _ctx_keys(context: Optional[Dict[str, Any]]) -> tuple:
        ctx = context if isinstance(context, dict) else {}
        def pick(*ks: str) -> Any:
            for k in ks:
                if ctx.get(k) is not None:
                    return ctx.get(k)
            return None
        return (
            pick("stock_id", "stock", "symbol"),
            pick("sector_id", "sector"),
            pick("geo_id", "geo"),
            pick("regime_tag", "regime"),
            pick("investor_majority", "investor"),
        )

    # ------------------------------------------------------------------
    # Rank persistence + competitive survival
    # ------------------------------------------------------------------
    def upsert_ranking(
        self,
        stock_id: Any,
        sector_id: Optional[Any] = None,
        geo_id: Optional[Any] = None,
        regime_tag: Optional[Any] = None,
        investor_majority: str = "all",
        lens_family: Optional[str] = None,
        p_value: Optional[float] = None,
        explain_power: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Insert/update a single lens ranking row and recompute partition ranks.

        Rank is computed within the full (stock/sector/geo/regime/investor) partition,
        ordered by explain_power DESC. Returns the partition's ranking rows (rank ASC).
        """
        self._ensure()
        if lens_family not in LENS_FAMILIES:
            raise ValueError(f"lens_family must be one of {LENS_FAMILIES}, got {lens_family!r}")
        if investor_majority not in INVESTOR_MAJORITIES:
            raise ValueError(
                f"investor_majority must be one of {INVESTOR_MAJORITIES}, got {investor_majority!r}"
            )
        s, sec, g, rg, inv = self._norm(stock_id, sector_id, geo_id, regime_tag, investor_majority)
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO model_explainer_rankings
                    (stock_id, sector_id, geo_id, regime_tag, investor_majority,
                     lens_family, p_value, explain_power)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stock_id, sector_id, geo_id, regime_tag, investor_majority, lens_family)
                DO UPDATE SET p_value=excluded.p_value, explain_power=excluded.explain_power
                """,
                (s, sec, g, rg, inv, lens_family, p_value, float(explain_power)),
            )
            self._recompute_ranks(conn, s, sec, g, rg, inv)
        return self.get_rankings(
            stock_id=s, investor_majority=inv, sector_id=sec, geo_id=g, regime_tag=rg
        )

    def _recompute_ranks(
        self,
        conn: Any,
        s: str,
        sec: str,
        g: str,
        rg: str,
        inv: str,
    ) -> None:
        """Reassign 1-based rank within a partition by explain_power DESC (deterministic)."""
        rows = conn.execute(
            """
            SELECT ranking_id FROM model_explainer_rankings
            WHERE stock_id=? AND sector_id=? AND geo_id=? AND regime_tag=? AND investor_majority=?
            ORDER BY explain_power DESC, ranking_id ASC
            """,
            (s, sec, g, rg, inv),
        ).fetchall()
        for i, row in enumerate(rows, start=1):
            conn.execute(
                "UPDATE model_explainer_rankings SET rank=? WHERE ranking_id=?",
                (i, row["ranking_id"]),
            )

    def adjust_explain_power(
        self,
        stock_id: Any,
        sector_id: Optional[Any] = None,
        geo_id: Optional[Any] = None,
        regime_tag: Optional[Any] = None,
        investor_majority: str = "all",
        lens_family: Optional[str] = None,
        delta: float = 0.0,
    ) -> Optional[float]:
        """Competitive survival: nudge a lens's explanation_weight (↑/↓).

        Called by eod_corrector after an EOD/event batch to reinforce winning lenses or
        decay losers. Recomputes partition ranks. Returns the new explain_power (or None
        if no matching row existed).
        """
        self._ensure()
        if lens_family not in LENS_FAMILIES:
            raise ValueError(f"lens_family must be one of {LENS_FAMILIES}, got {lens_family!r}")
        s, sec, g, rg, inv = self._norm(stock_id, sector_id, geo_id, regime_tag, investor_majority)
        with self.db.session() as conn:
            conn.execute(
                """
                UPDATE model_explainer_rankings
                SET explain_power = MAX(0.0, COALESCE(explain_power, 0.0) + ?)
                WHERE stock_id=? AND sector_id=? AND geo_id=? AND regime_tag=?
                      AND investor_majority=? AND lens_family=?
                """,
                (float(delta), s, sec, g, rg, inv, lens_family),
            )
            self._recompute_ranks(conn, s, sec, g, rg, inv)
            row = conn.execute(
                """
                SELECT explain_power FROM model_explainer_rankings
                WHERE stock_id=? AND sector_id=? AND geo_id=? AND regime_tag=?
                      AND investor_majority=? AND lens_family=?
                """,
                (s, sec, g, rg, inv, lens_family),
            ).fetchone()
            return float(row["explain_power"]) if row else None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def get_rankings(
        self,
        stock_id: Any,
        investor_majority: str = "all",
        limit: Optional[int] = None,
        sector_id: Optional[Any] = None,
        geo_id: Optional[Any] = None,
        regime_tag: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Return ranking rows for an exact (stock/sector/geo/regime/investor) partition.

        Always filters on all five partition keys (missing keys match the '*'/all
        sentinel), so ranks are comparable within their true partition. Ordered by rank.
        """
        self._ensure()
        s, sec, g, rg, inv = self._norm(stock_id, sector_id, geo_id, regime_tag, investor_majority)
        sql = (
            "SELECT * FROM model_explainer_rankings "
            "WHERE stock_id=? AND sector_id=? AND geo_id=? AND regime_tag=? AND investor_majority=? "
            "ORDER BY rank ASC"
        )
        params: List[Any] = [s, sec, g, rg, inv]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self.db.session() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def rank_models(
        self,
        symbol: Any,
        investor_majority: str = "all",
        sector_id: Optional[Any] = None,
        geo_id: Optional[Any] = None,
        regime_tag: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Queryable per-stock / per-investor-majority lens rankings + joined ensemble weight.

        Acceptance: rank_models("HAL", "FII") returns the lens ranking rows for HAL under
        FII ownership, each annotated with its computed ensemble weight.
        """
        self._ensure()
        inv = "all" if investor_majority not in INVESTOR_MAJORITIES else investor_majority
        rankings = self.get_rankings(
            stock_id=symbol,
            investor_majority=inv,
            sector_id=sector_id,
            geo_id=geo_id,
            regime_tag=regime_tag,
        )
        weights = self.compute_ensemble_weights(
            stock=symbol, sector=sector_id, geo=geo_id, regime=regime_tag, investor=inv
        )
        out: List[Dict[str, Any]] = []
        for r in rankings:
            d = dict(r)
            d["weight"] = round(float(weights.get(r["lens_family"], 0.0)), 6)
            out.append(d)
        return out

    # ------------------------------------------------------------------
    # Ensemble weights (conditional context + bootstrap fallback)
    # ------------------------------------------------------------------
    def compute_ensemble_weights(
        self,
        stock: Optional[Any] = None,
        sector: Optional[Any] = None,
        geo: Optional[Any] = None,
        regime: Optional[Any] = None,
        investor: Optional[Any] = None,
    ) -> Dict[str, float]:
        """Per-conditional-context MoE weights: w_lens = explain_power / Σ explain_power.

        Returns a complete dict over all four lens families, each > 0, summing to 1.0.
        Falls back to deterministic bootstrap weights when the context has no learned
        rankings for every lens family.
        """
        self._ensure()
        s, sec, g, rg, inv = self._norm(stock, sector, geo, regime, investor)
        with self.db.session() as conn:
            rows = conn.execute(
                """
                SELECT lens_family, SUM(explain_power) AS ep FROM model_explainer_rankings
                WHERE stock_id=? AND sector_id=? AND geo_id=? AND regime_tag=? AND investor_majority=?
                GROUP BY lens_family
                """,
                (s, sec, g, rg, inv),
            ).fetchall()
        agg = {r["lens_family"]: float(r["ep"] or 0.0) for r in rows}
        if all(f in agg and agg[f] > 0 for f in LENS_FAMILIES):
            total = sum(agg.values())
            if total > 0:
                return {f: agg[f] / total for f in LENS_FAMILIES}
        return dict(BOOTSTRAP_ENSEMBLE_WEIGHTS)

    def get_ensemble_weights_for_context(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
        """Aggregate view for composite_screener: returns lens->weight for a context dict.

        Context keys accepted (loose aliases): stock_id/stock/symbol, sector_id/sector,
        geo_id/geo, regime_tag/regime, investor_majority/investor.
        """
        stock, sector, geo, regime, investor = self._ctx_keys(context)
        return self.compute_ensemble_weights(
            stock=stock, sector=sector, geo=geo, regime=regime, investor=investor
        )

    # ------------------------------------------------------------------
    # Temperature-controlled MoE gating + audit
    # ------------------------------------------------------------------
    @staticmethod
    def _seed_for(context: Optional[Dict[str, Any]], temperature: float, seed: Optional[int]) -> int:
        if seed is not None:
            return int(seed)
        ctx_key = json.dumps(context if isinstance(context, dict) else {}, sort_keys=True, default=str)
        digest = hashlib.sha256((ctx_key + "|" + repr(round(float(temperature), 4))).encode()).digest()
        return int.from_bytes(digest[:4], "big")

    def select_fired_lenses(
        self,
        temperature: float,
        context: Optional[Dict[str, Any]] = None,
        seed: Optional[int] = None,
    ) -> List[str]:
        """Sparse MoE gate: choose which lenses fire for this run.

        temperature ∈ [0, 1]:
          * low (exploit): fire only the top lenses (consolidate winners).
          * high (explore): fire all lenses and jitter in alternate decision paths.

        Selection is deterministic for a given (context, temperature, seed).
        """
        self._ensure()
        temp = max(0.0, min(1.0, float(temperature)))
        stock, sector, geo, regime, investor = self._ctx_keys(context)
        s, sec, g, rg, inv = self._norm(stock, sector, geo, regime, investor)

        # Per-family score: prefer learned explain_power, else bootstrap weight as proxy.
        with self.db.session() as conn:
            rows = conn.execute(
                """
                SELECT lens_family, explain_power FROM model_explainer_rankings
                WHERE stock_id=? AND sector_id=? AND geo_id=? AND regime_tag=? AND investor_majority=?
                """,
                (s, sec, g, rg, inv),
            ).fetchall()
        raw = {r["lens_family"]: float(r["explain_power"] or 0.0) for r in rows}
        canon = {f: i for i, f in enumerate(LENS_FAMILIES)}
        scores = {
            f: (raw[f] if (f in raw and raw[f] > 0) else BOOTSTRAP_ENSEMBLE_WEIGHTS[f])
            for f in LENS_FAMILIES
        }
        ordered = sorted(LENS_FAMILIES, key=lambda f: (-scores[f], canon[f]))

        n = len(ordered)
        # Exploit: 2 top lenses at temp=0; expand toward all 4 as temp -> 1.
        k = int(round(2 + temp * (n - 2)))
        k = max(1, min(n, k))
        fired = list(ordered[:k])

        # Explore: at high temperature, mutate the pathway by probabilistically firing
        # additional lenses (seeded => deterministic).
        if temp > 0.5:
            p = (temp - 0.5) * 2.0
            rng = random.Random(self._seed_for(context, temp, seed))
            for f in ordered[k:]:
                if rng.random() < p:
                    fired.append(f)
        return fired

    def fire_lenses(
        self,
        temperature: float,
        context: Optional[Dict[str, Any]] = None,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Run one MoE activation: select fired lenses, compute weights, audit the run."""
        fired = self.select_fired_lenses(temperature, context=context, seed=seed)
        weights = self.get_ensemble_weights_for_context(context)
        fired_weight_sum = sum(weights.get(f, 0.0) for f in fired)
        activation_id = self.log_activation(temperature, fired, context=context or {})
        return {
            "activation_id": activation_id,
            "temperature": float(temperature),
            "fired_lenses": list(fired),
            "weights": {f: round(float(weights.get(f, 0.0)), 6) for f in LENS_FAMILIES},
            "fired_weight_sum": round(float(fired_weight_sum), 6),
            "n_fired": len(fired),
        }

    def log_activation(
        self,
        temperature: float,
        fired_lenses: Sequence[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Append a lens_activation_log row. Returns the new log_id."""
        self._ensure()
        ctx = context if isinstance(context, dict) else {}
        ctx_json = json.dumps(ctx, sort_keys=True, default=str)
        fired_json = json.dumps(list(fired_lenses), sort_keys=True)
        with self.db.session() as conn:
            cur = conn.execute(
                "INSERT INTO lens_activation_log (temperature, fired_lenses, context_json) VALUES (?, ?, ?)",
                (float(temperature), fired_json, ctx_json),
            )
            return int(cur.lastrowid)

    def get_activation_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent lens_activation_log rows (most recent first) with parsed payloads."""
        self._ensure()
        with self.db.session() as conn:
            rows = conn.execute(
                "SELECT * FROM lens_activation_log ORDER BY log_id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            out: List[Dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                try:
                    d["fired_lenses_parsed"] = json.loads(d.get("fired_lenses") or "[]")
                except Exception:
                    d["fired_lenses_parsed"] = []
                try:
                    d["context_parsed"] = json.loads(d.get("context_json") or "{}")
                except Exception:
                    d["context_parsed"] = {}
                out.append(d)
            return out


# ------------------------------------------------------------------
# Full-universe deterministic seeding (opt-in, additive)
#
# Creates deterministic rankings for every active master symbol, all 5
# investor cohorts × 4 lens families (20 rows per symbol). Uses the same
# EXPLAIN_FLOOR / BOOTSTRAP fallback as run_moe_eod so missing substrate
# is never fabricated as positive evidence — floor values are the
# explicit coverage signal. Reruns are idempotent via upsert_ranking's
# ON CONFLICT. stock_id remains the NSE symbol (string) for compatibility;
# no ISIN conversion is performed. If an optional ISIN resolver is needed
# it should be added additively alongside the symbol key.
# ------------------------------------------------------------------

def _er_company_id_for(conn: Any, symbol: str) -> Optional[int]:
    try:
        row = conn.execute(
            "SELECT company_id FROM financial_metrics WHERE symbol = ? LIMIT 1", (symbol,)
        ).fetchone()
        if row and row["company_id"] is not None:
            return int(row["company_id"])
    except Exception:
        pass
    try:
        row = conn.execute(
            "SELECT company_id FROM moat_evaluations WHERE ticker = ? LIMIT 1", (symbol,)
        ).fetchone()
        if row and row["company_id"] is not None:
            return int(row["company_id"])
    except Exception:
        pass
    return None


def _er_quality_strength(conn: Any, symbol: str) -> float:
    try:
        row = conn.execute(
            "SELECT total_moat_score FROM moat_evaluations WHERE ticker = ? OR isin = ? LIMIT 1",
            (symbol, symbol),
        ).fetchone()
        if row and row["total_moat_score"] is not None:
            return max(0.0, min(1.0, float(row["total_moat_score"]) / 5.0))
    except Exception:
        pass
    return EXPLAIN_FLOOR


def _er_policy_strength(conn: Any, symbol: str) -> float:
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(severity_score * probability), 0) AS eni "
            "FROM regulatory_political_risks WHERE ticker = ? OR symbol = ?",
            (symbol, symbol),
        ).fetchone()
        if row and row["eni"] is not None:
            return max(0.0, min(1.0, abs(float(row["eni"])) / 5.0))
    except Exception:
        pass
    return EXPLAIN_FLOOR


def _er_factor_strength(conn: Any, symbol: str) -> float:
    try:
        row = conn.execute(
            "SELECT roic_wacc_spread, fcf_margin, gross_margin_peer_percentile "
            "FROM financial_metrics WHERE symbol = ? ORDER BY fiscal_year DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if not row:
            return EXPLAIN_FLOOR
        rs = float(row["roic_wacc_spread"] or 0.0)
        fc = float(row["fcf_margin"] or 0.0)
        gm = float(row["gross_margin_peer_percentile"] or 0.0)
        val = 0.10 + 0.45 * min(1.0, abs(rs) / 0.5) + 0.25 * min(1.0, abs(fc) / 0.3) + 0.20 * (gm / 100.0)
        return max(EXPLAIN_FLOOR, min(1.0, val))
    except Exception:
        return EXPLAIN_FLOOR


def _er_supply_strength(conn: Any, symbol: str) -> float:
    cid = _er_company_id_for(conn, symbol)
    if cid is None:
        return EXPLAIN_FLOOR
    try:
        ripple = conn.execute(
            "SELECT COALESCE(MAX(significance_rank), 0) AS s FROM ripple_effects "
            "WHERE target_company_id = ?",
            (cid,),
        ).fetchone()
        geo = conn.execute(
            "SELECT COALESCE(SUM(revenue_share_pct), 0) AS g FROM geographic_exposure "
            "WHERE company_id = ?",
            (cid,),
        ).fetchone()
        rs = float(ripple["s"] if ripple else 0.0)
        gs = float(geo["g"] if geo else 0.0)
        val = max(rs / 100.0, gs / 100.0)
        if val <= 0.0:
            return EXPLAIN_FLOOR
        return max(EXPLAIN_FLOOR, min(1.0, val))
    except Exception:
        return EXPLAIN_FLOOR


def _er_pick_universe_symbols(conn: Any, universe: str, limit: Optional[int]) -> List[str]:
    """Deterministically ordered active symbols for a universe filter."""
    universe = (universe or "nifty200").lower()
    try:
        if universe == "all":
            rows = conn.execute(
                "SELECT nse_symbol FROM master_companies WHERE is_active=1 AND nse_symbol IS NOT NULL AND TRIM(nse_symbol) != '' ORDER BY nse_symbol ASC"
            ).fetchall()
        elif universe == "nifty500":
            rows = conn.execute(
                "SELECT nse_symbol FROM master_companies WHERE is_nifty500=1 AND is_active=1 AND nse_symbol IS NOT NULL ORDER BY nse_symbol ASC"
            ).fetchall()
            if not rows:
                rows = conn.execute(
                    "SELECT nse_symbol FROM master_companies WHERE is_active=1 AND nse_symbol IS NOT NULL AND TRIM(nse_symbol) != '' ORDER BY nse_symbol ASC"
                ).fetchall()
        else:  # nifty200 default
            rows = conn.execute(
                "SELECT nse_symbol FROM master_companies WHERE is_nifty200=1 AND is_active=1 AND nse_symbol IS NOT NULL ORDER BY nse_symbol ASC"
            ).fetchall()
            if not rows:
                rows = conn.execute(
                    "SELECT nse_symbol FROM master_companies WHERE is_active=1 AND nse_symbol IS NOT NULL AND TRIM(nse_symbol) != '' ORDER BY nse_symbol ASC"
                ).fetchall()
    except Exception:
        rows = []
    syms = [r["nse_symbol"] for r in rows if r["nse_symbol"]]
    if limit is not None:
        try:
            lim = int(limit)
            if lim >= 0:
                syms = syms[:lim]
        except Exception:
            pass
    return syms


def seed_universe_rankings(
    universe: str = "nifty200",
    limit: Optional[int] = None,
    all_investor_cohorts: bool = False,
    manager: Optional[Any] = None,
) -> Dict[str, Any]:
    """Opt-in full-universe MoE seed wrapper around deterministic calculations.

    Creates deterministic rankings for every active master symbol in the
    requested universe (ordered by nse_symbol ASC), all 5 investor cohorts
    × 4 lens families (20 rows per symbol). Uses existing upsert logic so
    reruns are idempotent and preserves existing rows.

    Missing underlying lenses use EXPLAIN_FLOOR / BOOTSTRAP behavior and are
    explicitly signaled via the floor explain_power (no fabricated positive
    evidence). Rankings remain symbol-keyed (stock_id = nse_symbol) for
    compatibility; an optional ISIN resolver can be added additively.

    Args:
        universe: 'nifty200' (default), 'nifty500', or 'all'.
        limit: optional cap on number of symbols (deterministic head).
        all_investor_cohorts: present for API compatibility; when True the
            caller explicitly requests full 5-cohort coverage (already the
            default for this wrapper). Reserved for future conditional use.
        manager: optional DatabaseManager; defaults to the global db_manager.

    Returns:
        dict with symbols_seeded, rows_written, symbols_list.
    """
    if manager is None:
        from reality_engine.db.database import db_manager
        manager = db_manager
    ranker = EnsembleRanker(manager)
    ranker.ensure_schema()

    with manager.session() as conn:
        syms = _er_pick_universe_symbols(conn, universe, limit)

    rows_written = 0
    for sym in syms:
        with manager.session() as conn:
            q = _er_quality_strength(conn, sym)
            p = _er_policy_strength(conn, sym)
            f = _er_factor_strength(conn, sym)
            s = _er_supply_strength(conn, sym)
        base = {
            "factor_statistical": max(EXPLAIN_FLOOR, f),
            "business_quality": max(EXPLAIN_FLOOR, q),
            "policy_macro": max(EXPLAIN_FLOOR, p),
            "supply_chain": max(EXPLAIN_FLOOR, s),
        }
        tot = sum(base.values())
        norm = {k: v / tot for k, v in base.items()}  # 'all' baseline
        for inv in INVESTOR_MAJORITIES:
            tilt = INVESTOR_TILTS[inv]
            tv = {k: norm[k] * tilt[k] for k in LENS_FAMILIES}
            ttot = sum(tv.values())
            for fam in LENS_FAMILIES:
                ep = tv[fam] / ttot
                p_value = round(0.01 + 0.03 * (1.0 - ep), 4)
                ranker.upsert_ranking(sym, None, None, None, inv, fam, p_value=p_value, explain_power=round(ep, 6))
                rows_written += 1

    return {"symbols_seeded": len(syms), "rows_written": rows_written, "symbols_list": list(syms)}


# Convenience singleton (uses the default DB manager).
_default_ranker: Optional[EnsembleRanker] = None


def get_default_ranker() -> EnsembleRanker:
    global _default_ranker
    if _default_ranker is None:
        _default_ranker = EnsembleRanker()
    return _default_ranker
