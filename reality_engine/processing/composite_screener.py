"""
Composite Quantitative Screener & Factor Model Module
Synthesizes Technical Flow, Fundamental Acceleration, and Smart Money Flow
into composite conviction scores and ranked trading candidates.
"""

import logging
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

from reality_engine.db.repository import repo
from reality_engine.processing.technical_engine import technical_engine
from reality_engine.processing.fundamental_engine import fundamental_engine

logger = logging.getLogger("reality_engine.composite_screener")


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

    def run_screener(self, target_date: Optional[str] = None, top_n: int = 20,
                     universe: str = "all", min_turnover_lacs: float = 200.0,
                     crisis_mode: bool = False) -> pd.DataFrame:
        """
        Executes multi-factor quantitative screening for a given date.
        Filters by liquidity (turnover >= min_turnover_lacs) and optional universe (e.g. 'nifty200').
        """
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


# Singleton composite screener
composite_screener = CompositeScreener()
