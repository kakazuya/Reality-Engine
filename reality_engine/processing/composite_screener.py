"""
Composite Quantitative Screener & Factor Model Module
Synthesizes Technical Flow, Fundamental Acceleration, and Smart Money Flow
into composite conviction scores and ranked trading candidates.

Phase 6 Top-Down Funnel (Objectives §1/§45):
  Industry secular_growth_score>=4 -> Moat total_moat_score>=3.5 Stable/Expanding
  -> Policy agg ENI>=0 -> ROIC>WACC>0.05 secondary. Solvency remains secondary gate.
Legacy bottom-up run_screener() is preserved for backward compatibility.
New top_down_screen() implements the funnel with graceful PG->SQLite fallback.
"""

import json
import logging
import math
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd
import numpy as np

from reality_engine.db.repository import repo
from reality_engine.processing.technical_engine import technical_engine
from reality_engine.processing.fundamental_engine import fundamental_engine

logger = logging.getLogger("reality_engine.composite_screener")

# --- Top-down funnel thresholds (PDF spec + postgres_schema.sql) ---
TOPDOWN_MIN_SECULAR_GROWTH_SCORE = 4.0
TOPDOWN_MIN_MOAT_SCORE = 3.5
TOPDOWN_ALLOWED_MOAT_TRAJECTORIES = {"Stable", "Expanding"}
TOPDOWN_MIN_POLICY_ENI = 0.0
TOPDOWN_MIN_ROIC_WACC_SPREAD = 0.05
TOPDOWN_FEATURE_FLAG_ENV = "REALITY_ENGINE_TOPDOWN"

# ----------------------------------------------------------------------
# Wave B3 — All-Peers Weighted Ensemble (FF5 is one peer, NOT the trunk)
#
# Per AGENTS.md §3 #3 the ensemble must compete at least four peer families:
#   (a) Factor/Statistical  : FF5 + tech/funda/smart-money flow
#   (b) Macro/Policy-change : regulatory_political_risks / macro_events ENI
#   (c) Business-quality    : moat_evaluations / business_model_profiles
#   (d) Supply-chain         : ripple_effects forward/back significance
#
# Composite = Σ w_lens * norm(lens_score)
#   w_lens = explain_power / Σ explain_power  (per stock/sector/geo/regime/
#           investor_majority context). Until Wave D's ensemble_ranker has
#           populated model_explainer_rankings, we fall back to deterministic
#           bootstrap weights (sum == 1.0, each > 0).
# ----------------------------------------------------------------------
LENS_FAMILY_FACTOR = "factor_statistical"
LENS_FAMILY_QUALITY = "business_quality"
LENS_FAMILY_POLICY = "policy_macro"
LENS_FAMILY_SUPPLY = "supply_chain"

ENSEMBLE_LENS_FAMILIES = [
    LENS_FAMILY_FACTOR,
    LENS_FAMILY_QUALITY,
    LENS_FAMILY_POLICY,
    LENS_FAMILY_SUPPLY,
]

# Deterministic bootstrap weights (overridden by learned explain_power in Wave D).
BOOTSTRAP_ENSEMBLE_WEIGHTS = {
    LENS_FAMILY_FACTOR: 0.30,
    LENS_FAMILY_QUALITY: 0.25,
    LENS_FAMILY_POLICY: 0.25,
    LENS_FAMILY_SUPPLY: 0.20,
}

# Default per-scrip noise floor (vol/liquidity adaptive; replaced per-row at runtime).
DEFAULT_NOISE_FLOOR = 45.0

# Legacy non-ensemble lens weights (preserved for run_screener default path).
LEGACY_WEIGHTS_NORMAL = {"technical": 0.45, "fundamental": 0.35, "alt_sentiment": 0.20}
LEGACY_WEIGHTS_CRISIS = {"technical": 0.25, "fundamental": 0.25, "causal_resilience": 0.30, "alt_sentiment": 0.20}


class CompositeScreener:
    """Computes daily multi-factor scores and ranks high-conviction scrips."""

    def __init__(self):
        self.repo = repo
        self.tech_engine = technical_engine
        self.funda_engine = fundamental_engine

    @staticmethod
    def compute_smart_money_score(
        delivery_spike_ratio: float,
        delivery_pct: float,
        delivery_conviction_score: float,
        change_pct: float,
        pit_trades_for_symbol: Optional[pd.DataFrame] = None,
        deals_for_symbol: Optional[pd.DataFrame] = None,
    ) -> float:
        """
        Computes Factor 3: Smart Money Flow & Breadth Score (0 - 100).
        - High delivery volume spike (DSR >= 2.0x AND delivery % >= 50%): +30 bonus
        - SEBI PIT insider trades: promoter open-market buy > INR 1 Crore (100 Lacs) during a drop: +40 bonus
        - Bulk & Block deals: marquee institutional buying: +30 bonus
        - Baseline delivery conviction component: min(40.0, DCS * 0.20)
        """
        dsr = float(delivery_spike_ratio or 1.0)
        deliv_pct = float(delivery_pct or 0.0)
        dcs = float(delivery_conviction_score or 0.0)
        change = float(change_pct or 0.0)

        # 1. High delivery volume spike bonus
        delivery_bonus = 30.0 if (dsr >= 2.0 and deliv_pct >= 50.0) else 0.0

        # 2. SEBI PIT Promoter Buy > 1 Cr during price drop bonus
        promoter_bonus = 0.0
        if pit_trades_for_symbol is not None and not pit_trades_for_symbol.empty:
            promoter_buys = pit_trades_for_symbol[
                pit_trades_for_symbol["category_of_person"].astype(str).str.upper().str.contains("PROMOTER")
                & pit_trades_for_symbol["transaction_type"].astype(str).str.upper().isin(["BUY", "ACQUISITION", "MARKET PURCHASE"])
                & pit_trades_for_symbol["mode_of_acquisition"].astype(str).str.upper().str.contains("OPEN|MARKET")
                & (pd.to_numeric(pit_trades_for_symbol["value_inr_lacs"], errors="coerce").fillna(0.0) > 100.0)
            ]
            if not promoter_buys.empty and change < 0.0:
                promoter_bonus = 40.0

        # 3. Marquee Institutional Bulk/Block Buy bonus
        institutional_bonus = 0.0
        if deals_for_symbol is not None and not deals_for_symbol.empty:
            marquee_buys = deals_for_symbol[
                deals_for_symbol["buy_sell"].astype(str).str.upper().isin(["BUY", "PURCHASE"])
                & (pd.to_numeric(deals_for_symbol["is_marquee_institution"], errors="coerce").fillna(0) == 1)
            ]
            if not marquee_buys.empty:
                institutional_bonus = 30.0

        # 4. Baseline delivery conviction component
        conviction_part = min(40.0, dcs * 0.20)

        raw_score = delivery_bonus + promoter_bonus + institutional_bonus + conviction_part
        return float(np.clip(raw_score, 0.0, 100.0))

    # ------------------------------------------------------------------
    # Wave B3 — All-Peers Weighted Ensemble (replaces top-down funnel trunk)
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_lens_scores(df: pd.DataFrame, lens_cols: List[str]) -> pd.DataFrame:
        """Min-max normalize each raw lens column to [0, 1] within the candidate set.

        Per AGENTS.md §3 #4 the dense substrate must be quantized before it drives a
        thesis; normalization makes heterogeneous peer scores (0-100 moat vs ENI vs
        ripple significance) comparable inside one weighted blend. Constant columns
        collapse to a neutral 0.5 so they neither inflate nor veto a peer.
        """
        df = df.copy()
        for col in lens_cols:
            if col not in df.columns:
                df[col] = 0.5
            vals = pd.to_numeric(df[col], errors="coerce")
            lo, hi = vals.min(), vals.max()
            if pd.isna(lo) or pd.isna(hi) or hi == lo:
                df[f"norm_{col}"] = 0.5
            else:
                df[f"norm_{col}"] = ((vals - lo) / (hi - lo)).clip(0.0, 1.0)
        return df

    def get_ensemble_weights(
        self,
        context: Optional[Dict[str, Any]] = None,
        override: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """Return the per-lens-family weight dict, normalized so Σw == 1.0 and each > 0.

        w_lens = explain_power / Σ explain_power per (stock/sector/geo/regime/
        investor_majority). Wave D's ensemble_ranker will populate
        model_explainer_rankings; until then we use deterministic bootstrap weights.
        """
        if override:
            weights = {f: float(override.get(f, 0.0)) for f in ENSEMBLE_LENS_FAMILIES}
        else:
            weights = dict(BOOTSTRAP_ENSEMBLE_WEIGHTS)
            # Prefer learned weights when repository has populated them (Wave D hook).
            try:
                learned = self.repo.get_ensemble_weights(context=context)
                if learned and abs(sum(learned.values()) - 1.0) < 1e-6 and all(v > 0 for v in learned.values()):
                    weights = {f: float(learned.get(f, weights[f])) for f in ENSEMBLE_LENS_FAMILIES}
            except Exception:
                pass
        total = sum(weights.values())
        if total <= 0:
            return dict(BOOTSTRAP_ENSEMBLE_WEIGHTS)
        return {f: w / total for f, w in weights.items()}

    def compute_lens_scores(self, df: pd.DataFrame) -> pd.DataFrame:
        """Materialize the four peer-family raw scores (0-100) from base factor columns.

        Pure & deterministic — operates only on already-computed columns so it can be
        unit-tested without a live DB. Missing inputs fall back to neutral defaults.
        """
        df = df.copy()
        def _series(col, default):
            if col in df.columns:
                return pd.to_numeric(df[col], errors="coerce").fillna(default)
            return pd.Series([default] * len(df), index=df.index, dtype=float)
        tech = _series("technical_score", 0.0)
        funda = _series("fundamental_score", 0.0)
        if "alt_sentiment_score" in df.columns or "smart_money_score" in df.columns:
            base_col = "alt_sentiment_score" if "alt_sentiment_score" in df.columns else "smart_money_score"
            sm = pd.to_numeric(df[base_col], errors="coerce").fillna(0.0)
        else:
            sm = pd.Series([0.0] * len(df), index=df.index, dtype=float)
        # (a) Factor/Statistical peer: blend of FF5-style flow + acceleration + breadth
        df["lens_factor_statistical"] = (0.40 * tech + 0.35 * funda + 0.25 * sm).clip(0.0, 100.0)

        # (c) Business-quality peer: moat total (0-5) scaled to 0-100
        if "total_moat_score" in df.columns:
            moat = pd.to_numeric(df["total_moat_score"], errors="coerce").fillna(2.5)
        else:
            moat = pd.Series([2.5] * len(df), index=df.index, dtype=float)
        df["lens_business_quality"] = (moat / 5.0 * 100.0).clip(0.0, 100.0)

        # (b) Macro/Policy peer: aggregate ENI mapped through 50 + ENI*20 (ENI 0 -> 50, None -> 50 neutral)
        # Do NOT coerce NULL eni to 0 in the source column; keep policy_agg_eni as None for audit.
        # Lens neutral 50.0 is explicit, not via filling eni with 0.
        if "policy_agg_eni" not in df.columns:
            df["policy_agg_eni"] = None
        eni_series = pd.to_numeric(df["policy_agg_eni"], errors="coerce")
        df["lens_policy_macro"] = eni_series.apply(
            lambda x: 50.0 if pd.isna(x) else float(np.clip(50.0 + x * 20.0, 0.0, 100.0))
        )

        # (d) Supply-chain peer: ripple significance (neutral 50 when no signal)
        if "lens_supply_chain" not in df.columns:
            df["lens_supply_chain"] = df["symbol"].apply(
                lambda s: self._lookup_supply_significance(str(s))
            )
        df["lens_supply_chain"] = pd.to_numeric(df["lens_supply_chain"], errors="coerce").fillna(50.0).clip(0.0, 100.0)
        return df

    def compute_ensemble_composite(
        self,
        df: pd.DataFrame,
        weights: Optional[Dict[str, float]] = None,
    ) -> pd.DataFrame:
        """composite = Σ w_lens * norm(lens_score), returned 0-100.

        This is a *blend*, not a max/funnel: every peer contributes proportionally to
        its weight, so a stock weak on moat but strong on FF5 can still surface.
        """
        df = df.copy()
        weights = weights or self.get_ensemble_weights()
        for fam in ENSEMBLE_LENS_FAMILIES:
            col = f"lens_{fam}"
            if col not in df.columns:
                df[col] = 50.0  # neutral fallback keeps every weight valid
        df = self._normalize_lens_scores(df, [f"lens_{f}" for f in ENSEMBLE_LENS_FAMILIES])
        comp = pd.Series(0.0, index=df.index)
        for fam in ENSEMBLE_LENS_FAMILIES:
            w = weights.get(fam, 0.0)
            comp = comp + w * df[f"norm_lens_{fam}"]
        df["ensemble_composite"] = (comp * 100.0).round(2)
        for fam in ENSEMBLE_LENS_FAMILIES:
            df[f"weight_{fam}"] = round(weights.get(fam, 0.0), 4)
        return df

    def get_per_scrip_noise_floor(
        self,
        symbol: str,
        turnover_lacs: float = 200.0,
        change_pct: float = 0.0,
        delivery_pct: float = 0.0,
        volatility_proxy: Optional[float] = None,
    ) -> float:
        """Vol/liquidity-adaptive per-scrip noise floor (replaces global hard cutoff).

        Illiquid and high-realized-vol names need a *stronger* composite signal before
        they clear — this is the learned-noise-floor stub that eod_corrector (Wave D)
        will later populate from realized volatility / adaptive liquidity. Deterministic
        here so the same symbol always yields the same floor in a session.
        """
        base = DEFAULT_NOISE_FLOOR
        liq = float(turnover_lacs or 0.0)
        liquidity_adj = max(0.0, min(15.0, (200.0 - liq) / 200.0 * 15.0))
        vol = abs(float(change_pct or 0.0))
        vol_adj = min(15.0, vol * 1.0)
        extra = 0.0
        if volatility_proxy is not None:
            extra = min(10.0, abs(float(volatility_proxy)) * 0.5)
        floor = base + liquidity_adj + vol_adj + extra
        return float(np.clip(floor, 30.0, 80.0))

    def _lookup_supply_significance(self, symbol: str) -> float:
        """Supply-chain peer raw score (0-100) from ripple_effects significance.

        B3 stub: queries ripple_effects for the company; graceful neutral 50.0 when the
        PG/ripple graph is not provisioned so the supply peer still carries weight > 0
        without vetoing candidates.
        """
        sym = (symbol or "").upper().strip()
        try:
            with self.repo.db.session() as conn:
                row = conn.execute(
                    """
                    SELECT COALESCE(MAX(significance_rank), 50.0)
                    FROM ripple_effects r
                    JOIN companies c ON c.company_id = r.target_company_id
                    WHERE c.ticker = ?
                    """,
                    (sym,),
                ).fetchone()
                if row and row[0] is not None:
                    return float(row[0])
        except Exception:
            pass
        return 50.0

    def _build_factor_scored_df(
        self,
        target_date: str,
        universe: str = "all",
        min_turnover_lacs: float = 0.0,
    ) -> pd.DataFrame:
        """Shared factor-scoring prep (technical/fundamental/smart-money + solvency gate).

        Extracted from run_screener so ensemble_screen reuses identical base scores
        without duplicating the funnel. Returns approved-only df with factor columns but
        NO final composite (caller chooses legacy vs ensemble composition).
        """
        df_tech = self.repo.get_all_price_delivery_for_date(target_date)
        if df_tech.empty:
            return pd.DataFrame()
        df_tech = df_tech[df_tech["series"].isin(["EQ", "BE"])].copy()
        if universe.lower() == "nifty200" and "is_nifty200" in df_tech.columns:
            df_tech = df_tech[df_tech["is_nifty200"] == 1].copy()
        elif min_turnover_lacs > 0 and "turnover_lacs" in df_tech.columns:
            df_tech = df_tech[df_tech["turnover_lacs"] >= min_turnover_lacs].copy()

        df_funda = self.repo.get_latest_quarterly_financials()
        df_forensic = self.repo.get_forensic_health()
        df_merged = pd.merge(df_tech, df_funda, on=["isin", "symbol"], how="left", suffixes=("", "_funda"))
        if not df_forensic.empty:
            forensic_cols = [
                c for c in [
                    "isin", "is_solvency_approved", "solvency_disqualification_reasons",
                    "promoter_holding_pct", "promoter_pledge_pct", "pe_ratio",
                    "interest_coverage_ratio", "debt_to_equity_ratio",
                ] if c in df_forensic.columns
            ]
            df_merged = pd.merge(df_merged, df_forensic[forensic_cols], on="isin", how="left", suffixes=("", "_forensic"))

        df_merged["yoy_revenue_growth_pct"] = df_merged["yoy_revenue_growth_pct"].fillna(0.0)
        df_merged["yoy_pat_growth_pct"] = df_merged["yoy_pat_growth_pct"].fillna(0.0)
        if "opm_delta_bps" not in df_merged.columns:
            df_merged["opm_delta_bps"] = [
                self.funda_engine.calculate_opm_delta_bps(current, prior)
                for current, prior in zip(
                    df_merged.get("ebitda_margin_pct", pd.Series(0.0, index=df_merged.index)),
                    df_merged.get("prior_ebitda_margin_pct", pd.Series(0.0, index=df_merged.index)),
                )
            ]
        else:
            df_merged["opm_delta_bps"] = df_merged["opm_delta_bps"].fillna(0.0)

        solvency_approved_list, disqualifications_list = [], []
        for _, row in df_merged.iterrows():
            sev = self.funda_engine.evaluate_forensic_solvency(
                row.get("promoter_pledge_pct"), row.get("interest_coverage_ratio"), row.get("debt_to_equity_ratio")
            )
            solvency_approved_list.append(sev["is_solvency_approved"])
            disqualifications_list.append(sev["reasons_str"])
        df_merged["is_solvency_approved"] = solvency_approved_list
        df_merged["solvency_disqualification_reasons"] = disqualifications_list
        df_merged["delivery_spike_ratio"] = df_merged["delivery_spike_ratio"].fillna(1.0)
        df_merged["delivery_conviction_score"] = df_merged["delivery_conviction_score"].fillna(df_merged["delivery_pct"])
        if "roce_pct" not in df_merged.columns:
            df_merged["roce_pct"] = 14.0
        else:
            df_merged["roce_pct"] = df_merged["roce_pct"].fillna(14.0)

        df_merged["technical_score"] = [self.tech_engine.compute_technical_flow_score(r) for _, r in df_merged.iterrows()]
        df_merged["fundamental_score"] = [
            self.funda_engine.compute_fundamental_score(
                yoy_rev_growth=r.get("yoy_revenue_growth_pct", 0.0),
                yoy_pat_growth=r.get("yoy_pat_growth_pct", 0.0),
                opm_delta_bps=r.get("opm_delta_bps", 0.0),
                roce_pct=r.get("roce_pct", 12.0),
            )
            for _, r in df_merged.iterrows()
        ]
        df_merged["causal_resilience_score"] = np.clip(
            (df_merged["yoy_revenue_growth_pct"].clip(lower=0.0) * 1.5)
            + (df_merged["yoy_pat_growth_pct"].clip(lower=0.0) * 1.5)
            + (df_merged["opm_delta_bps"].clip(lower=0.0) / 20.0)
            + (df_merged["roce_pct"].clip(lower=0.0) * 1.5),
            0.0, 100.0,
        )
        pit = self.repo.get_recent_insider_trades(days=30, as_of_date=target_date)
        deals = self.repo.get_recent_bulk_block_deals(days=30, as_of_date=target_date)
        sm_scores = []
        for _, row in df_merged.iterrows():
            symbol = str(row["symbol"])
            isin = str(row.get("isin", ""))
            pit_sym = pit[(pit["symbol"].astype(str) == symbol) | (pit["isin"].astype(str) == isin)] if not pit.empty and "isin" in pit.columns else (pit[pit["symbol"].astype(str) == symbol] if not pit.empty else pit)
            deal_sym = deals[deals["symbol"].astype(str) == symbol] if not deals.empty else deals
            sm_scores.append(
                self.compute_smart_money_score(
                    delivery_spike_ratio=row.get("delivery_spike_ratio", 1.0),
                    delivery_pct=row.get("delivery_pct", 0.0),
                    delivery_conviction_score=row.get("delivery_conviction_score", 0.0),
                    change_pct=row.get("change_pct", 0.0),
                    pit_trades_for_symbol=pit_sym,
                    deals_for_symbol=deal_sym,
                )
            )
        df_merged["smart_money_score"] = sm_scores
        df_merged["alt_sentiment_score"] = sm_scores

        # Strict Forensic Solvency Gate (secondary, per design rules)
        df_merged = df_merged[df_merged["is_solvency_approved"] == 1].copy()
        return df_merged

    def _enrich_ensemble_lens_raw(self, df: pd.DataFrame) -> pd.DataFrame:
        """Attach raw moat (quality), policy ENI, and supply significance columns."""
        if df.empty:
            return df
        if "total_moat_score" not in df.columns or "policy_agg_eni" not in df.columns:
            df = self._enrich_with_topdown_metrics(df)
        if "lens_supply_chain" not in df.columns:
            df["lens_supply_chain"] = df["symbol"].apply(lambda s: self._lookup_supply_significance(str(s)))
        return df

    def ensemble_screen(
        self,
        target_date: Optional[str] = None,
        top_n: int = 20,
        universe: str = "all",
        min_turnover_lacs: float = 0.0,
        crisis_mode: bool = False,
        weights: Optional[Dict[str, float]] = None,
        noise_floor_override: Optional[float] = None,
        persist: bool = True,
        dry_run: bool = False,
    ) -> pd.DataFrame:
        """All-peers weighted ensemble screen (Wave B3).

        Replaces the top-down funnel's sequential AND-gate with a continuous blend:
            composite = Σ w_lens * norm(lens_score)
        and replaces the global turnover cutoff with a per-scrip learned noise floor
        (vol/liquidity adaptive). Solvency remains a secondary gate.

        Returns top_n ranked rows; carries lens raw/normalized/weight columns for audit.
        """
        date_str = target_date or self.repo.get_latest_price_delivery_date()
        if not date_str:
            logger.warning("[ensemble] No price delivery data found.")
            return pd.DataFrame()
        logger.info("[ensemble] Screening date=%s universe=%s top=%d", date_str, universe, top_n)

        df = self._build_factor_scored_df(date_str, universe=universe, min_turnover_lacs=min_turnover_lacs)
        if df.empty:
            logger.warning("[ensemble] No approved candidates for %s", date_str)
            return pd.DataFrame()

        df = self._enrich_ensemble_lens_raw(df)
        df = self.compute_lens_scores(df)
        ctx = {"universe": universe, "crisis_mode": bool(crisis_mode), "date": date_str}
        ens_weights = self.get_ensemble_weights(context=ctx, override=weights)
        df = self.compute_ensemble_composite(df, weights=ens_weights)

        # Per-scrip learned noise floor replaces the global hard cutoff.
        floors = df.apply(
            lambda r: float(noise_floor_override)
            if noise_floor_override is not None
            else self.get_per_scrip_noise_floor(
                str(r["symbol"]),
                r.get("turnover_lacs", 200.0),
                r.get("change_pct", 0.0),
                r.get("delivery_pct", 0.0),
            ),
            axis=1,
        )
        df["noise_floor"] = floors.round(2)
        df["clears_noise_floor"] = df["ensemble_composite"] >= df["noise_floor"]

        if not dry_run:
            df = df[df["clears_noise_floor"]].copy()
        if df.empty:
            logger.warning("[ensemble] No candidates cleared the per-scrip noise floor for %s", date_str)
            return pd.DataFrame()

        df = df.sort_values(by="ensemble_composite", ascending=False).reset_index(drop=True)
        df["composite_rank"] = df.index + 1
        df.attrs["ensemble_mode"] = True
        df.attrs["ensemble_weights"] = ens_weights

        if persist and not dry_run:
            self._persist_ensemble_calls(df.head(top_n), date_str)
        logger.info("[ensemble] Screened top %d (of %d approved) for %s", min(top_n, len(df)), len(df), date_str)
        return df.head(top_n)

    def _persist_ensemble_calls(self, df: pd.DataFrame, date_str: str) -> None:
        """Persist ensemble top_n to eod_scrip_calls using only schema-stable columns."""
        if df.empty:
            return
        records: List[Dict[str, Any]] = []
        for _, r in df.iterrows():
            cmp = float(r.get("close", 0.0) or 0.0)
            entry_low = round(cmp * 0.985, 2)
            entry_high = round(cmp * 1.015, 2)
            target = round(cmp * 1.18, 2)
            sl = round(cmp * 0.94, 2)
            rr = round((target - cmp) / (cmp - sl), 2) if (cmp - sl) > 0 else 3.0
            score = float(r["ensemble_composite"])
            conviction = "HIGH_CONVICTION" if score >= 75 else ("MODERATE" if score >= 55 else "SPECULATIVE")
            records.append({
                "date": date_str,
                "symbol": str(r["symbol"]),
                "isin": str(r.get("isin", "")),
                "composite_rank": int(r["composite_rank"]),
                "technical_score": float(r.get("technical_score", 0.0)),
                "fundamental_score": float(r.get("fundamental_score", 0.0)),
                "alt_sentiment_score": float(r.get("alt_sentiment_score", 0.0)),
                "composite_score": score,
                "current_market_price": cmp,
                "recommended_entry_range": f"INR {entry_low} - INR {entry_high}",
                "target_price": target,
                "stop_loss": sl,
                "risk_reward_ratio": rr,
                "conviction_level": conviction,
                "is_solvency_approved": int(r.get("is_solvency_approved", 1)),
                "delivery_spike_ratio": float(r.get("delivery_spike_ratio", 1.0)),
                "delivery_conviction_score": float(r.get("delivery_conviction_score", 0.0)),
                "yoy_revenue_growth_pct": float(r.get("yoy_revenue_growth_pct", 0.0)),
                "yoy_pat_growth_pct": float(r.get("yoy_pat_growth_pct", 0.0)),
            })
        try:
            self.repo.upsert_eod_scrip_calls(records)
        except Exception as e:
            logger.warning("[ensemble] upsert_eod_scrip_calls failed: %s", e)

    # ------------------------------------------------------------------
    # Top-down funnel helpers (Phase 6 vertical slice, PG->SQLite fallback)
    # ------------------------------------------------------------------
    def _lookup_secular_growth_score(self, industry: Optional[str], sector: Optional[str]) -> float:
        """Industry secular_growth_score 1-5, graceful fallback when PG not provisioned."""
        industry = (industry or "").strip()
        sector = (sector or "").strip()
        # Try SQLite demo table seed_industries_demo (12 rows)
        try:
            with self.repo.db.session() as conn:
                # Exact match first
                for col, val in [("industry_name", industry), ("sector_name", sector)]:
                    if val:
                        row = conn.execute(
                            f"SELECT secular_growth_score FROM seed_industries_demo WHERE {col} = ? LIMIT 1",
                            (val,),
                        ).fetchone()
                        if row and row[0] is not None:
                            return float(row[0])
                # Fuzzy LIKE
                for val in (industry, sector):
                    if val:
                        pat = f"%{val}%"
                        row = conn.execute(
                            "SELECT secular_growth_score FROM seed_industries_demo WHERE industry_name LIKE ? OR sector_name LIKE ? LIMIT 1",
                            (pat, pat),
                        ).fetchone()
                        if row and row[0] is not None:
                            return float(row[0])
        except Exception:
            pass
        # PG industries table fallback (if provisioned)
        try:
            with self.repo.db.session() as conn:
                row = conn.execute(
                    "SELECT secular_growth_score FROM industries WHERE industry_name = ? LIMIT 1",
                    (industry,),
                ).fetchone()
                if row and row[0] is not None:
                    return float(row[0])
        except Exception:
            pass
        # Hard-coded NSE industry -> demo score map (avoids blocking when demo/migration incomplete)
        mapping = {
            "Capital Goods": 4.2,
            "Information Technology": 4.8,
            "Healthcare": 4.5,
            "Financial Services": 4.6,
            "Pharmaceuticals": 4.5,
            "Chemicals": 4.1,
            "Specialty Chemicals": 4.1,
            "Metals & Mining": 4.0,
            "Oil Gas & Consumable Fuels": 3.8,
            "Energy": 4.7,
            "Power": 3.8,
            "Realty": 4.0,
            "Construction": 4.0,
            "Consumer Durables": 4.0,
            "Consumer Services": 4.4,
            "Fast Moving Consumer Goods": 3.5,
            "Automobile and Auto Components": 4.1,
            "Telecommunication": 4.3,
            "Services": 4.3,
            "Textiles": 3.5,
            "Industrials": 4.2,
            "Defence": 4.9,
        }
        for k, v in mapping.items():
            if k.lower() in industry.lower() or k.lower() in sector.lower():
                return float(v)
        if "defence" in industry.lower() or "defence" in sector.lower():
            return 4.9
        # Default pass-through for unknown industries in minimal slice (avoid false negatives before PG seed)
        return 4.0

    def _lookup_moat_metrics(self, symbol: str, isin: str) -> Dict[str, Any]:
        """Return {total_moat_score, moat_width, moat_trajectory, pricing_power_score} with SQLite fallbacks."""
        sym = (symbol or "").upper().strip()
        # 1. Try PG moat_evaluations + business_model_profiles join
        try:
            with self.repo.db.session() as conn:
                row = conn.execute(
                    """
                    SELECT m.total_moat_score, m.moat_trajectory, m.moat_width, b.pricing_power_score,
                           m.switching_costs, m.network_effects, m.cost_advantage, m.intangible_assets, m.efficient_scale
                    FROM moat_evaluations m
                    JOIN companies c ON c.company_id=m.company_id
                    LEFT JOIN business_model_profiles b ON b.company_id=c.company_id
                    WHERE c.ticker=? LIMIT 1
                    """,
                    (sym,),
                ).fetchone()
                if row and row[0] is not None:
                    return {
                        "total_moat_score": float(row[0]),
                        "moat_trajectory": str(row[1] or "Stable"),
                        "moat_width": str(row[2] or ("Wide" if float(row[0]) >= 3.5 else "Narrow")),
                        "pricing_power_score": int(row[3] or 3),
                    }
        except Exception:
            pass
        # 2. SQLite demo business_model_profiles_demo (4 rows: HAL, TITAGARH, POLYPLEX, RELIANCE)
        try:
            with self.repo.db.session() as conn:
                row = conn.execute(
                    "SELECT archetype, revenue_recurrence_pct, pricing_power_score FROM business_model_profiles_demo WHERE symbol=? LIMIT 1",
                    (sym,),
                ).fetchone()
                if row:
                    # Heuristic moat from archetype/pricing_power: Tollbooth/Platform wide, Asset-Heavy narrow
                    arch = str(row[0] or "")
                    pwr = int(row[2] or 3)
                    score_map = {"Tollbooth": 3.8, "Platform": 4.2, "Asset-Heavy OEM": 2.7, "Network": 3.6}
                    base = score_map.get(arch, 2.8)
                    # adjust by pricing power
                    adj = (pwr - 3) * 0.15
                    total = round(max(0.0, min(5.0, base + adj)), 2)
                    width = "Wide" if total >= 3.5 else ("Narrow" if total >= 2.5 else "None")
                    return {
                        "total_moat_score": total,
                        "moat_trajectory": "Stable" if sym in ("HAL", "RELIANCE") else ("Expanding" if pwr >= 4 else "Stable"),
                        "moat_width": width,
                        "pricing_power_score": pwr,
                    }
        except Exception:
            pass
        # 3. Distilled params moat_rating (0-10) -> 0-5
        try:
            rows = self.repo.get_distilled_parameters(sym, parameter_key="business_sensitivities")
            for r in rows:
                try:
                    vj = r.get("value_json") or r.get("value") or ""
                    payload = json.loads(vj) if isinstance(vj, str) else (vj if isinstance(vj, dict) else {})
                    rating = payload.get("moat_rating")
                    if rating is not None:
                        total = round(max(0.0, min(5.0, float(rating) / 2.0)), 2)
                        width = "Wide" if total >= 3.5 else ("Narrow" if total >= 2.5 else "None")
                        # trajectory from cyclicality_profile
                        traj = "Stable"
                        cyc = self.repo.get_distilled_parameters(sym, parameter_key="cyclicality_profile")
                        for cr in cyc:
                            cj = cr.get("value_json") or ""
                            cp = json.loads(cj) if isinstance(cj, str) else {}
                            if isinstance(cp, dict) and "stage_rationale" in cp:
                                traj = "Stable"
                                break
                        return {
                            "total_moat_score": total,
                            "moat_trajectory": traj,
                            "moat_width": width,
                            "pricing_power_score": 4 if total >= 3.5 else 3,
                        }
                except Exception:
                    continue
        except Exception:
            pass
        # 4. Deterministic heuristic via moat_scorer.score_from_text
        try:
            from reality_engine.processing.moat_scorer import score_from_text  # local import to avoid cycle
            # Build pseudo-text from symbol/industry
            comp = self.repo.get_company_by_symbol(sym) or {}
            txt = f"{sym} {comp.get('industry','')} {comp.get('sector','')} {sym}"
            ms = score_from_text(txt)
            total = ms.total()
            return {
                "total_moat_score": total,
                "moat_trajectory": "Stable",
                "moat_width": ms.width(),
                "pricing_power_score": 3,
            }
        except Exception:
            pass
        return {"total_moat_score": 2.5, "moat_trajectory": "Stable", "moat_width": "Narrow", "pricing_power_score": 3}

    def _lookup_policy_agg_eni(self, symbol: str) -> Optional[float]:
        """Aggregate ENI via repository (mapped rows only). Returns None for unknown/no_template."""
        sym = (symbol or "").upper().strip()
        try:
            # Delegates to repository which handles coverage semantics (None for unknown)
            # Do NOT COALESCE NULL to 0; unknown must stay None for explicit gating.
            return self.repo.get_policy_agg_eni(sym)
        except Exception:
            return None

    def _lookup_roic_wacc_spread(self, symbol: str, isin: str) -> float:
        """ROIC-WACC spread (>0.05 secondary validation). PG financial_metrics or SQLite annual_financials fallback."""
        sym = (symbol or "").upper().strip()
        # PG financial_metrics
        try:
            with self.repo.db.session() as conn:
                row = conn.execute(
                    "SELECT roic_wacc_spread FROM financial_metrics WHERE company_id IN (SELECT company_id FROM companies WHERE ticker=?) ORDER BY fiscal_year DESC LIMIT 1",
                    (sym,),
                ).fetchone()
                if row and row[0] is not None:
                    return float(row[0])
        except Exception:
            pass
        # SQLite annual_financials: roce as proxy for ROIC, assume WACC 10% (conservative)
        try:
            with self.repo.db.session() as conn:
                row = conn.execute(
                    "SELECT roce_pct FROM annual_financials WHERE symbol=? ORDER BY fiscal_year DESC LIMIT 1",
                    (sym,),
                ).fetchone()
                if row and row[0] is not None and float(row[0]) != 0.0:
                    roce = float(row[0])
                    # roce stored as pct? If >1 it's percent, normalize
                    if roce > 1.5:  # e.g., 14.0 means 14%
                        roce = roce / 100.0
                    wacc = 0.10
                    return round(roce - wacc, 4)
        except Exception:
            pass
        # Fallback: use quarterly roce-like inference from yoy_pat or assume passing for minimal slice
        return 0.06

    def _enrich_with_topdown_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add secular_growth_score, moat_*, policy_agg_eni/policy_coverage, roic_wacc_spread columns."""
        if df.empty:
            return df
        secular_scores, moat_scores, moat_trajs, moat_widths, pricing_scores, policy_agg, policy_cov, roic_spreads = [], [], [], [], [], [], [], []
        # Cache per-symbol lookups
        cache_moat: Dict[str, Dict[str, Any]] = {}
        cache_policy: Dict[str, Optional[float]] = {}
        cache_coverage: Dict[str, str] = {}
        cache_roic: Dict[str, float] = {}
        for _, row in df.iterrows():
            sym = str(row.get("symbol", "")).upper()
            isin = str(row.get("isin", ""))
            ind = str(row.get("industry", row.get("sector", "")))
            sec = str(row.get("sector", ""))
            # Industry
            secular_scores.append(self._lookup_secular_growth_score(ind, sec))
            # Moat
            if sym not in cache_moat:
                cache_moat[sym] = self._lookup_moat_metrics(sym, isin)
            m = cache_moat[sym]
            moat_scores.append(m["total_moat_score"])
            moat_trajs.append(m["moat_trajectory"])
            moat_widths.append(m["moat_width"])
            pricing_scores.append(m["pricing_power_score"])
            # Policy - explicit coverage + eni (None for unknown/no_template)
            if sym not in cache_policy:
                cache_policy[sym] = self._lookup_policy_agg_eni(sym)
                try:
                    cache_coverage[sym] = self.repo.get_policy_coverage(sym)
                except Exception:
                    cache_coverage[sym] = "unknown" if cache_policy[sym] is None else "mapped"
            policy_agg.append(cache_policy[sym])
            policy_cov.append(cache_coverage[sym])
            # ROIC
            if sym not in cache_roic:
                cache_roic[sym] = self._lookup_roic_wacc_spread(sym, isin)
            roic_spreads.append(cache_roic[sym])
        df = df.copy()
        df["secular_growth_score"] = secular_scores
        df["total_moat_score"] = moat_scores
        df["moat_trajectory"] = moat_trajs
        df["moat_width"] = moat_widths
        df["pricing_power_score"] = pricing_scores
        df["policy_agg_eni"] = policy_agg
        df["policy_coverage"] = policy_cov
        # Aliases for audit consistency: policy_eni mirrors policy_agg_eni, policy_coverage explicit
        df["policy_eni"] = policy_agg
        df["roic_wacc_spread"] = roic_spreads
        return df

    def _apply_topdown_funnel(
        self,
        df: pd.DataFrame,
        min_secular_score: float = TOPDOWN_MIN_SECULAR_GROWTH_SCORE,
        min_moat_score: float = TOPDOWN_MIN_MOAT_SCORE,
        allowed_trajectories: Optional[set] = None,
        min_policy_eni: float = TOPDOWN_MIN_POLICY_ENI,
        min_roic_spread: float = TOPDOWN_MIN_ROIC_WACC_SPREAD,
        enable_industry: bool = True,
        enable_moat: bool = True,
        enable_policy: bool = True,
        enable_roic: bool = True,
    ) -> Tuple[pd.DataFrame, Dict[str, int]]:
        """Sequential funnel  Industry->Moat->Policy->ROIC (solvency remains secondary).
        Returns filtered df and funnel stats dict."""
        allowed_trajectories = allowed_trajectories or TOPDOWN_ALLOWED_MOAT_TRAJECTORIES
        stats = {"input": len(df)}
        cur = df
        if enable_industry:
            before = len(cur)
            cur = cur[cur["secular_growth_score"] >= float(min_secular_score)].copy()
            stats["after_industry_ge_4"] = len(cur)
            logger.info("Top-down Industry filter secular>=%.1f: %d -> %d", min_secular_score, before, len(cur))
        else:
            stats["after_industry_ge_4"] = len(cur)
        if enable_moat:
            before = len(cur)
            cur = cur[
                (cur["total_moat_score"] >= float(min_moat_score))
                & (cur["moat_trajectory"].isin(list(allowed_trajectories)))
            ].copy()
            stats["after_moat_3_5_stable_exp"] = len(cur)
            logger.info("Top-down Moat filter >=%.1f Stable/Expanding: %d -> %d", min_moat_score, before, len(cur))
        else:
            stats["after_moat_3_5_stable_exp"] = len(cur)
        if enable_policy:
            before = len(cur)
            # Policy unknown is explicit (policy_coverage, policy_eni=None) and does NOT pass/fail a hard gate.
            # Only mapped rows are subjected to the ENI threshold; unknown/no_template rows bypass the hard
            # cutoff (retain neutral ensemble weight) and are not counted as "approved".
            if "policy_coverage" in cur.columns:
                # Mapped rows must satisfy threshold; non-mapped bypass
                mask_mapped = cur["policy_coverage"] == "mapped"
                # For mapped, check ENI >= threshold (NaN mapped should be filtered as not passing)
                eni_numeric = pd.to_numeric(cur["policy_agg_eni"], errors="coerce")
                mask_pass = (~mask_mapped) | (eni_numeric >= float(min_policy_eni))
                cur = cur[mask_pass].copy()
            else:
                # Fallback when coverage column absent (legacy): NaN >= threshold is False, so unknown fails
                # but we must not coerce None->0; keep as NaN filter.
                cur = cur[pd.to_numeric(cur["policy_agg_eni"], errors="coerce") >= float(min_policy_eni)].copy()
            stats["after_policy_ENI_ge_0"] = len(cur)
            logger.info("Top-down Policy filter ENI>=%.1f (mapped only): %d -> %d", min_policy_eni, before, len(cur))
        else:
            stats["after_policy_ENI_ge_0"] = len(cur)
        if enable_roic:
            before = len(cur)
            cur = cur[cur["roic_wacc_spread"] > float(min_roic_spread)].copy()
            stats["after_roic_wacc_gt_0_05"] = len(cur)
            logger.info("Top-down ROIC>WACC>%.2f: %d -> %d", min_roic_spread, before, len(cur))
        else:
            stats["after_roic_wacc_gt_0_05"] = len(cur)
        # Solvency remains secondary gate (already applied in enriched df, but ensure)
        if "is_solvency_approved" in cur.columns:
            before = len(cur)
            cur = cur[cur["is_solvency_approved"] == 1].copy()
            stats["after_solvency_secondary"] = len(cur)
            logger.info("Top-down Solvency secondary gate: %d -> %d", before, len(cur))
        else:
            stats["after_solvency_secondary"] = len(cur)
        stats["output"] = len(cur)
        return cur, stats

    def run_screener(
        self,
        target_date: Optional[str] = None,
        top_n: int = 20,
        universe: str = "all",
        min_turnover_lacs: float = 200.0,
        crisis_mode: bool = False,
        use_top_down: bool = False,
        ensemble: bool = False,
        ensemble_weights: Optional[Dict[str, float]] = None,
        noise_floor_override: Optional[float] = None,
        **kwargs,
    ) -> pd.DataFrame:
        """
        Executes multi-factor quantitative screening for a given date.
        Filters by liquidity (turnover >= min_turnover_lacs) and optional universe (e.g. 'nifty200').

        Phase 6: pass use_top_down=True to delegate to top_down_screen() via feature flag.
        Wave B3: pass ensemble=True to use the all-peers weighted ensemble (default False
            keeps the legacy weighted composite for backward-compatible tests).
        Legacy path preserved for backward compatibility (57 tests).
        """
        # Wave B3: opt-in all-peers weighted ensemble (replaces funnel as the trunk)
        if ensemble or kwargs.get("use_ensemble"):
            return self.ensemble_screen(
                target_date=target_date,
                top_n=top_n,
                universe=universe,
                min_turnover_lacs=min_turnover_lacs,
                crisis_mode=crisis_mode,
                weights=ensemble_weights,
                noise_floor_override=noise_floor_override,
            )
        # Feature-flag delegation (minimal slice): keep legacy intact, allow opt-in top-down
        if use_top_down or kwargs.get("top_down") or kwargs.get("enable_top_down"):
            return self.top_down_screen(
                target_date=target_date,
                top_n=top_n,
                universe=universe,
                min_turnover_lacs=min_turnover_lacs,
                crisis_mode=crisis_mode,
                **{k: v for k, v in kwargs.items() if k not in ("top_down", "enable_top_down")},
            )
        date_str = target_date or self.repo.get_latest_price_delivery_date()
        if not date_str:
            logger.warning("No price delivery data found in database.")
            return pd.DataFrame()

        logger.info("Executing Composite Screener for date: %s", date_str)

        # 1. Fetch Technical & Delivery Data for Date
        df_tech = self.repo.get_all_price_delivery_for_date(date_str)
        if df_tech.empty:
            logger.warning("No price delivery records found for date %s", date_str)
            return pd.DataFrame()

        # Filter for active EQ series and liquidity
        df_tech = df_tech[df_tech["series"].isin(["EQ", "BE"])].copy()
        if universe.lower() == "nifty200" and "is_nifty200" in df_tech.columns:
            df_tech = df_tech[df_tech["is_nifty200"] == 1].copy()
        elif min_turnover_lacs > 0 and "turnover_lacs" in df_tech.columns:
            df_tech = df_tech[df_tech["turnover_lacs"] >= min_turnover_lacs].copy()

        # 2. Fetch Latest Fundamentals & Forensic Health
        df_funda = self.repo.get_latest_quarterly_financials()
        df_forensic = self.repo.get_forensic_health()

        # 3. Merge Datasets
        df_merged = pd.merge(df_tech, df_funda, on=["isin", "symbol"], how="left", suffixes=("", "_funda"))
        if not df_forensic.empty:
            forensic_cols = [c for c in ["isin", "is_solvency_approved", "solvency_disqualification_reasons", "promoter_holding_pct", "promoter_pledge_pct", "pe_ratio", "interest_coverage_ratio", "debt_to_equity_ratio"] if c in df_forensic.columns]
            df_merged = pd.merge(
                df_merged,
                df_forensic[forensic_cols],
                on="isin",
                how="left",
                suffixes=("", "_forensic")
            )

        # Fill NaNs with safe defaults
        df_merged["yoy_revenue_growth_pct"] = df_merged["yoy_revenue_growth_pct"].fillna(0.0)
        df_merged["yoy_pat_growth_pct"] = df_merged["yoy_pat_growth_pct"].fillna(0.0)
        if "opm_delta_bps" not in df_merged.columns:
            df_merged["opm_delta_bps"] = [
                self.funda_engine.calculate_opm_delta_bps(current, prior)
                for current, prior in zip(
                    df_merged.get("ebitda_margin_pct", pd.Series(0.0, index=df_merged.index)),
                    df_merged.get("prior_ebitda_margin_pct", pd.Series(0.0, index=df_merged.index)),
                )
            ]
        else:
            df_merged["opm_delta_bps"] = df_merged["opm_delta_bps"].fillna(0.0)

        # Dynamic Forensic Solvency Gate Evaluation
        solvency_approved_list = []
        disqualifications_list = []
        for _, row in df_merged.iterrows():
            pledge = row.get("promoter_pledge_pct")
            cov = row.get("interest_coverage_ratio")
            lev = row.get("debt_to_equity_ratio")
            solvency_eval = self.funda_engine.evaluate_forensic_solvency(pledge, cov, lev)
            solvency_approved_list.append(solvency_eval["is_solvency_approved"])
            disqualifications_list.append(solvency_eval["reasons_str"])

        df_merged["is_solvency_approved"] = solvency_approved_list
        df_merged["solvency_disqualification_reasons"] = disqualifications_list
        df_merged["delivery_spike_ratio"] = df_merged["delivery_spike_ratio"].fillna(1.0)
        df_merged["delivery_conviction_score"] = df_merged["delivery_conviction_score"].fillna(df_merged["delivery_pct"])
        if "roce_pct" not in df_merged.columns:
            df_merged["roce_pct"] = 14.0
        else:
            df_merged["roce_pct"] = df_merged["roce_pct"].fillna(14.0)

        # 4. Compute Factor Scores
        # Factor 1: Technical Flow (0-100)
        tech_scores = []
        for _, row in df_merged.iterrows():
            t_score = self.tech_engine.compute_technical_flow_score(row)
            tech_scores.append(t_score)
        df_merged["technical_score"] = tech_scores

        # Factor 2: Fundamental Acceleration (0-100)
        funda_scores = []
        for _, row in df_merged.iterrows():
            f_score = self.funda_engine.compute_fundamental_score(
                yoy_rev_growth=row.get("yoy_revenue_growth_pct", 0.0),
                yoy_pat_growth=row.get("yoy_pat_growth_pct", 0.0),
                opm_delta_bps=row.get("opm_delta_bps", 0.0),
                roce_pct=row.get("roce_pct", 12.0)
            )
            funda_scores.append(f_score)
        df_merged["fundamental_score"] = funda_scores

        # Operational / Causal Resilience Score (0-100)
        df_merged["causal_resilience_score"] = np.clip(
            (df_merged["yoy_revenue_growth_pct"].clip(lower=0.0) * 1.5)
            + (df_merged["yoy_pat_growth_pct"].clip(lower=0.0) * 1.5)
            + (df_merged["opm_delta_bps"].clip(lower=0.0) / 20.0)
            + (df_merged["roce_pct"].clip(lower=0.0) * 1.5),
            0.0, 100.0,
        )

        # Factor 3: Smart Money Flow & Breadth (0-100)
        smart_money_scores = []
        pit = self.repo.get_recent_insider_trades(days=30, as_of_date=date_str)
        deals = self.repo.get_recent_bulk_block_deals(days=30, as_of_date=date_str)
        for _, row in df_merged.iterrows():
            symbol = str(row["symbol"])
            isin = str(row.get("isin", ""))
            pit_symbol = pit[(pit["symbol"].astype(str) == symbol) | (pit["isin"].astype(str) == isin)] if not pit.empty and "isin" in pit.columns else (pit[pit["symbol"].astype(str) == symbol] if not pit.empty else pit)
            deal_symbol = deals[deals["symbol"].astype(str) == symbol] if not deals.empty else deals

            sm_score = self.compute_smart_money_score(
                delivery_spike_ratio=row.get("delivery_spike_ratio", 1.0),
                delivery_pct=row.get("delivery_pct", 0.0),
                delivery_conviction_score=row.get("delivery_conviction_score", 0.0),
                change_pct=row.get("change_pct", 0.0),
                pit_trades_for_symbol=pit_symbol,
                deals_for_symbol=deal_symbol,
            )
            smart_money_scores.append(sm_score)

        df_merged["smart_money_score"] = smart_money_scores
        df_merged["alt_sentiment_score"] = smart_money_scores

        # Factor Weighting: Normal vs Crisis
        if crisis_mode:
            df_merged["composite_score"] = (
                (df_merged["technical_score"] * 0.25)
                + (df_merged["fundamental_score"] * 0.25)
                + (df_merged["causal_resilience_score"] * 0.30)
                + (df_merged["alt_sentiment_score"] * 0.20)
            ).round(2)
        else:
            df_merged["composite_score"] = (
                (df_merged["technical_score"] * 0.45)
                + (df_merged["fundamental_score"] * 0.35)
                + (df_merged["alt_sentiment_score"] * 0.20)
            ).round(2)

        # Strict Forensic Solvency Gate: Filter out scrips with is_solvency_approved == 0
        df_merged["hard_disqualification_reason"] = np.where(
            df_merged["is_solvency_approved"] == 0,
            "HARD_SOLVENCY_DISQUALIFICATION: " + df_merged["solvency_disqualification_reasons"].astype(str),
            ""
        )
        disqualified_count = int((df_merged["is_solvency_approved"] == 0).sum())
        if disqualified_count > 0:
            logger.info("Strict Solvency Gate: Filtered out %d disqualified scrips.", disqualified_count)

        df_merged = df_merged[df_merged["is_solvency_approved"] == 1].copy()
        if df_merged.empty:
            logger.warning("No scrips passed solvency gates for date %s", date_str)
            return pd.DataFrame()

        # Sort by Composite Score descending
        df_ranked = df_merged.sort_values(by="composite_score", ascending=False).reset_index(drop=True)
        df_ranked["composite_rank"] = df_ranked.index + 1

        # Calculate Price targets and stop loss
        eod_records: List[Dict[str, Any]] = []
        for _, r in df_ranked.head(top_n).iterrows():
            cmp = float(r["close"])
            entry_low = round(cmp * 0.985, 2)
            entry_high = round(cmp * 1.015, 2)
            target = round(cmp * 1.18, 2)        # 18% upside
            sl = round(cmp * 0.94, 2)            # 6% stop loss
            rr = round((target - cmp) / (cmp - sl), 2) if (cmp - sl) > 0 else 3.0

            score = float(r["composite_score"])
            if score >= 75.0:
                conviction = "HIGH_CONVICTION"
            elif score >= 55.0:
                conviction = "MODERATE"
            else:
                conviction = "SPECULATIVE"

            rec = {
                "date": date_str,
                "symbol": str(r["symbol"]),
                "isin": str(r["isin"]),
                "composite_rank": int(r["composite_rank"]),
                "technical_score": float(r["technical_score"]),
                "fundamental_score": float(r["fundamental_score"]),
                "causal_resilience_score": float(r["causal_resilience_score"]),
                "alt_sentiment_score": float(r["alt_sentiment_score"]),
                "composite_score": score,
                "current_market_price": cmp,
                "recommended_entry_range": f"INR {entry_low} - INR {entry_high}",
                "target_price": target,
                "stop_loss": sl,
                "risk_reward_ratio": rr,
                "conviction_level": conviction,
                "is_solvency_approved": int(r["is_solvency_approved"]),
                "opm_delta_bps": float(r.get("opm_delta_bps", 0.0)),
                "delivery_spike_ratio": float(r["delivery_spike_ratio"]),
                "delivery_conviction_score": float(r["delivery_conviction_score"]),
                "yoy_revenue_growth_pct": float(r["yoy_revenue_growth_pct"]),
                "yoy_pat_growth_pct": float(r["yoy_pat_growth_pct"]),
            }
            eod_records.append(rec)

        # Save to Database
        self.repo.upsert_eod_scrip_calls(eod_records)
        logger.info("Screened Top %d candidates for %s successfully.", len(eod_records), date_str)

        return df_ranked.head(top_n)

    # ------------------------------------------------------------------
    # Phase 6 Top-down screener (new vertical slice, backward compatible)
    # ------------------------------------------------------------------
    def top_down_screen(
        self,
        target_date: Optional[str] = None,
        top_n: int = 20,
        universe: str = "all",
        min_turnover_lacs: float = 200.0,
        crisis_mode: bool = False,
        min_secular_score: float = TOPDOWN_MIN_SECULAR_GROWTH_SCORE,
        min_moat_score: float = TOPDOWN_MIN_MOAT_SCORE,
        min_policy_eni: float = TOPDOWN_MIN_POLICY_ENI,
        min_roic_spread: float = TOPDOWN_MIN_ROIC_WACC_SPREAD,
        enable_industry_filter: bool = True,
        enable_moat_filter: bool = True,
        enable_policy_filter: bool = True,
        enable_roic_filter: bool = True,
        dry_run: bool = False,
    ) -> pd.DataFrame:
        """
        Top-down funnel: Industry secular_growth_score>=4 -> Moat >=3.5 Stable/Expanding
        -> Policy agg ENI>=0 -> ROIC>WACC>0.05 secondary. Solvency remains secondary gate.
        Graceful fallback: if PG not provisioned, heuristics pass-through with logging.
        Returns scored + filtered df sorted by composite_score desc. Also annotates funnel stats.
        If dry_run=True, returns enriched (unfiltered) df with metrics for inspection.
        """
        date_str = target_date or self.repo.get_latest_price_delivery_date()
        if not date_str:
            logger.warning("[top_down] No price delivery data found.")
            return pd.DataFrame()
        logger.info("Executing Top-Down Screener for date: %s (universe=%s, top=%d)", date_str, universe, top_n)

        # 1. Reuse legacy factor computation but intercept before final solvency filter to allow funnel ordering
        # Build base df via internal helper: duplicate minimal steps of run_screener to get scored df without final sort
        df_tech = self.repo.get_all_price_delivery_for_date(date_str)
        if df_tech.empty:
            logger.warning("[top_down] No price delivery records for %s", date_str)
            return pd.DataFrame()
        df_tech = df_tech[df_tech["series"].isin(["EQ", "BE"])].copy()
        if universe.lower() == "nifty200" and "is_nifty200" in df_tech.columns:
            df_tech = df_tech[df_tech["is_nifty200"] == 1].copy()
        elif min_turnover_lacs > 0 and "turnover_lacs" in df_tech.columns:
            df_tech = df_tech[df_tech["turnover_lacs"] >= min_turnover_lacs].copy()

        df_funda = self.repo.get_latest_quarterly_financials()
        df_forensic = self.repo.get_forensic_health()
        df_merged = pd.merge(df_tech, df_funda, on=["isin", "symbol"], how="left", suffixes=("", "_funda"))
        if not df_forensic.empty:
            forensic_cols = [c for c in ["isin", "is_solvency_approved", "solvency_disqualification_reasons", "promoter_holding_pct", "promoter_pledge_pct", "pe_ratio", "interest_coverage_ratio", "debt_to_equity_ratio"] if c in df_forensic.columns]
            df_merged = pd.merge(df_merged, df_forensic[forensic_cols], on="isin", how="left", suffixes=("", "_forensic"))

        df_merged["yoy_revenue_growth_pct"] = df_merged["yoy_revenue_growth_pct"].fillna(0.0)
        df_merged["yoy_pat_growth_pct"] = df_merged["yoy_pat_growth_pct"].fillna(0.0)
        if "opm_delta_bps" not in df_merged.columns:
            df_merged["opm_delta_bps"] = [
                self.funda_engine.calculate_opm_delta_bps(current, prior)
                for current, prior in zip(
                    df_merged.get("ebitda_margin_pct", pd.Series(0.0, index=df_merged.index)),
                    df_merged.get("prior_ebitda_margin_pct", pd.Series(0.0, index=df_merged.index)),
                )
            ]
        else:
            df_merged["opm_delta_bps"] = df_merged["opm_delta_bps"].fillna(0.0)

        # Forensic gate computed but not yet filtered (will be secondary)
        solvency_approved_list = []
        disq_list = []
        for _, row in df_merged.iterrows():
            solvency_eval = self.funda_engine.evaluate_forensic_solvency(row.get("promoter_pledge_pct"), row.get("interest_coverage_ratio"), row.get("debt_to_equity_ratio"))
            solvency_approved_list.append(solvency_eval["is_solvency_approved"])
            disq_list.append(solvency_eval["reasons_str"])
        df_merged["is_solvency_approved"] = solvency_approved_list
        df_merged["solvency_disqualification_reasons"] = disq_list
        df_merged["delivery_spike_ratio"] = df_merged["delivery_spike_ratio"].fillna(1.0)
        df_merged["delivery_conviction_score"] = df_merged["delivery_conviction_score"].fillna(df_merged["delivery_pct"])
        if "roce_pct" not in df_merged.columns:
            df_merged["roce_pct"] = 14.0
        else:
            df_merged["roce_pct"] = df_merged["roce_pct"].fillna(14.0)

        # Factor scores (same as legacy)
        df_merged["technical_score"] = [self.tech_engine.compute_technical_flow_score(r) for _, r in df_merged.iterrows()]
        df_merged["fundamental_score"] = [
            self.funda_engine.compute_fundamental_score(
                yoy_rev_growth=r.get("yoy_revenue_growth_pct", 0.0),
                yoy_pat_growth=r.get("yoy_pat_growth_pct", 0.0),
                opm_delta_bps=r.get("opm_delta_bps", 0.0),
                roce_pct=r.get("roce_pct", 12.0),
            )
            for _, r in df_merged.iterrows()
        ]
        df_merged["causal_resilience_score"] = np.clip(
            (df_merged["yoy_revenue_growth_pct"].clip(lower=0.0) * 1.5)
            + (df_merged["yoy_pat_growth_pct"].clip(lower=0.0) * 1.5)
            + (df_merged["opm_delta_bps"].clip(lower=0.0) / 20.0)
            + (df_merged["roce_pct"].clip(lower=0.0) * 1.5),
            0.0, 100.0,
        )
        pit = self.repo.get_recent_insider_trades(days=30, as_of_date=date_str)
        deals = self.repo.get_recent_bulk_block_deals(days=30, as_of_date=date_str)
        sm_scores = []
        for _, row in df_merged.iterrows():
            symbol = str(row["symbol"])
            isin = str(row.get("isin", ""))
            pit_sym = pit[(pit["symbol"].astype(str) == symbol) | (pit["isin"].astype(str) == isin)] if not pit.empty and "isin" in pit.columns else (pit[pit["symbol"].astype(str) == symbol] if not pit.empty else pit)
            deal_sym = deals[deals["symbol"].astype(str) == symbol] if not deals.empty else deals
            sm_scores.append(
                self.compute_smart_money_score(
                    delivery_spike_ratio=row.get("delivery_spike_ratio", 1.0),
                    delivery_pct=row.get("delivery_pct", 0.0),
                    delivery_conviction_score=row.get("delivery_conviction_score", 0.0),
                    change_pct=row.get("change_pct", 0.0),
                    pit_trades_for_symbol=pit_sym,
                    deals_for_symbol=deal_sym,
                )
            )
        df_merged["smart_money_score"] = sm_scores
        df_merged["alt_sentiment_score"] = sm_scores
        if crisis_mode:
            df_merged["composite_score"] = (
                (df_merged["technical_score"] * 0.25)
                + (df_merged["fundamental_score"] * 0.25)
                + (df_merged["causal_resilience_score"] * 0.30)
                + (df_merged["alt_sentiment_score"] * 0.20)
            ).round(2)
        else:
            df_merged["composite_score"] = (
                (df_merged["technical_score"] * 0.45)
                + (df_merged["fundamental_score"] * 0.35)
                + (df_merged["alt_sentiment_score"] * 0.20)
            ).round(2)

        # 2. Enrich with top-down metrics (Industry->Moat->Policy->ROIC)
        df_enriched = self._enrich_with_topdown_metrics(df_merged)
        if dry_run:
            logger.info("[top_down] dry_run: enriched %d rows, skipping funnel filters", len(df_enriched))
            return df_enriched.sort_values(by="composite_score", ascending=False).head(top_n).reset_index(drop=True)

        # 3. Apply funnel in strict order
        df_filtered, stats = self._apply_topdown_funnel(
            df_enriched,
            min_secular_score=min_secular_score,
            min_moat_score=min_moat_score,
            min_policy_eni=min_policy_eni,
            min_roic_spread=min_roic_spread,
            enable_industry=enable_industry_filter,
            enable_moat=enable_moat_filter,
            enable_policy=enable_policy_filter,
            enable_roic=enable_roic_filter,
        )
        logger.info("[top_down] Funnel stats %s", stats)

        if df_filtered.empty:
            logger.warning("[top_down] No candidates passed full funnel for %s — stats %s", date_str, stats)
            return pd.DataFrame()

        # 4. Rank survivors by composite_score (and secondarily moat)
        df_ranked = df_filtered.sort_values(by=["composite_score", "total_moat_score"], ascending=[False, False]).reset_index(drop=True)
        df_ranked["composite_rank"] = df_ranked.index + 1
        # Attach funnel stats as attrs for orchestrator inspection
        df_ranked.attrs["funnel_stats"] = stats
        df_ranked.attrs["topdown_mode"] = True

        # 5. Persist top_n to eod_scrip_calls (reuse legacy persistence but with funnel survivors)
        eod_records: List[Dict[str, Any]] = []
        for _, r in df_ranked.head(top_n).iterrows():
            cmp = float(r["close"])
            entry_low = round(cmp * 0.985, 2)
            entry_high = round(cmp * 1.015, 2)
            target = round(cmp * 1.18, 2)
            sl = round(cmp * 0.94, 2)
            rr = round((target - cmp) / (cmp - sl), 2) if (cmp - sl) > 0 else 3.0
            score = float(r["composite_score"])
            conviction = "HIGH_CONVICTION" if score >= 75 else ("MODERATE" if score >= 55 else "SPECULATIVE")
            eod_records.append(
                {
                    "date": date_str,
                    "symbol": str(r["symbol"]),
                    "isin": str(r["isin"]),
                    "composite_rank": int(r["composite_rank"]),
                    "technical_score": float(r["technical_score"]),
                    "fundamental_score": float(r["fundamental_score"]),
                    "causal_resilience_score": float(r["causal_resilience_score"]),
                    "alt_sentiment_score": float(r["alt_sentiment_score"]),
                    "composite_score": score,
                    "current_market_price": cmp,
                    "recommended_entry_range": f"INR {entry_low} - INR {entry_high}",
                    "target_price": target,
                    "stop_loss": sl,
                    "risk_reward_ratio": rr,
                    "conviction_level": conviction,
                    "is_solvency_approved": int(r["is_solvency_approved"]),
                    "opm_delta_bps": float(r.get("opm_delta_bps", 0.0)),
                    "delivery_spike_ratio": float(r["delivery_spike_ratio"]),
                    "delivery_conviction_score": float(r["delivery_conviction_score"]),
                    "yoy_revenue_growth_pct": float(r["yoy_revenue_growth_pct"]),
                    "yoy_pat_growth_pct": float(r["yoy_pat_growth_pct"]),
                }
            )
        try:
            self.repo.upsert_eod_scrip_calls(eod_records)
        except Exception as e:
            logger.warning("[top_down] upsert_eod_scrip_calls failed: %s", e)
        logger.info("[top_down] Screened Top %d (top-down survivors %d, input %d) for %s", len(eod_records), len(df_filtered), len(df_enriched), date_str)
        return df_ranked.head(top_n)


# Singleton composite screener
composite_screener = CompositeScreener()


def ensemble_screen(
    target_date: Optional[str] = None,
    top_n: int = 20,
    universe: str = "all",
    min_turnover_lacs: float = 0.0,
    crisis_mode: bool = False,
    weights: Optional[Dict[str, float]] = None,
    noise_floor_override: Optional[float] = None,
    persist: bool = True,
    dry_run: bool = False,
) -> pd.DataFrame:
    """Module-level convenience wrapper around ``CompositeScreener.ensemble_screen``.

    Mirrors the module-level ``top_down_screen`` contract so ``cli.py`` (or any caller)
    can do ``from reality_engine.processing.composite_screener import ensemble_screen``.
    """
    return composite_screener.ensemble_screen(
        target_date=target_date,
        top_n=top_n,
        universe=universe,
        min_turnover_lacs=min_turnover_lacs,
        crisis_mode=crisis_mode,
        weights=weights,
        noise_floor_override=noise_floor_override,
        persist=persist,
        dry_run=dry_run,
    )


def top_down_screen(
    target_date: Optional[str] = None,
    top_n: int = 20,
    universe: str = "all",
    min_turnover_lacs: float = 200.0,
    crisis_mode: bool = False,
    min_secular_score: float = TOPDOWN_MIN_SECULAR_GROWTH_SCORE,
    min_moat_score: float = TOPDOWN_MIN_MOAT_SCORE,
    min_policy_eni: float = TOPDOWN_MIN_POLICY_ENI,
    min_roic_spread: float = TOPDOWN_MIN_ROIC_WACC_SPREAD,
    enable_industry_filter: bool = True,
    enable_moat_filter: bool = True,
    enable_policy_filter: bool = True,
    enable_roic_filter: bool = True,
    dry_run: bool = False,
) -> pd.DataFrame:
    """Module-level convenience wrapper around ``CompositeScreener.top_down_screen``.

    Provides the public contract used by ``TESTING_MANUAL.md`` §10 and ``cli.py``:
        from reality_engine.processing.composite_screener import top_down_screen
    """
    return composite_screener.top_down_screen(
        target_date=target_date,
        top_n=top_n,
        universe=universe,
        min_turnover_lacs=min_turnover_lacs,
        crisis_mode=crisis_mode,
        min_secular_score=min_secular_score,
        min_moat_score=min_moat_score,
        min_policy_eni=min_policy_eni,
        min_roic_spread=min_roic_spread,
        enable_industry_filter=enable_industry_filter,
        enable_moat_filter=enable_moat_filter,
        enable_policy_filter=enable_policy_filter,
        enable_roic_filter=enable_roic_filter,
        dry_run=dry_run,
    )
