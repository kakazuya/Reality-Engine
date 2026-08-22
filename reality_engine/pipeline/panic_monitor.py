"""
Panic Monitor Module
Detects macro drawdown panic triggers across benchmark and sectoral indices,
and executes crisis bargain screening to identify resilient, solvent companies
experiencing institutional delivery absorption.
"""

import re
import logging
from typing import Any, Dict, List, Optional
import pandas as pd
import numpy as np

from reality_engine.db.repository import repo
from reality_engine.processing.composite_screener import CompositeScreener, composite_screener

logger = logging.getLogger("reality_engine.panic_monitor")


class PanicMonitor:
    """Detects index drawdowns and screens for solvent, operationally resilient bargains."""

    def __init__(self, repository=repo, screener: Optional[CompositeScreener] = None):
        self.repo = repository
        self.screener = screener or composite_screener

    def latest_session(self, session_date: Optional[str] = None) -> pd.DataFrame:
        """
        Retrieves index performance for the latest session or specified date.
        Queries nse_index_breadth first; falls back to computing index proxies from
        daily_price_delivery if nse_index_breadth is unavailable.
        """
        target_date = session_date
        with self.repo.db.session() as conn:
            if not target_date:
                row = conn.execute("SELECT MAX(date) FROM nse_index_breadth").fetchone()
                date_breadth = row[0] if row and row[0] else None
                date_price = self.repo.get_latest_price_delivery_date()
                target_date = date_breadth or date_price

            if not target_date:
                logger.warning("No session date found in database.")
                return pd.DataFrame()

            # 1. Primary: query nse_index_breadth
            df_breadth = pd.read_sql_query(
                "SELECT * FROM nse_index_breadth WHERE date = ?", conn, params=[target_date]
            )
            if not df_breadth.empty:
                return df_breadth

            # 2. Fallback: compute index and sector performance from daily_price_delivery
            df_delivery = pd.read_sql_query(
                """
                SELECT p.symbol, p.change_pct, p.turnover_lacs,
                       m.sector, m.industry, m.market_cap_tier,
                       m.is_nifty50, m.is_nifty100, m.is_nifty200
                FROM daily_price_delivery p
                JOIN master_companies m ON p.isin = m.isin
                WHERE p.date = ? AND p.series IN ('EQ', 'BE')
                """,
                conn,
                params=[target_date]
            )
            if df_delivery.empty:
                return pd.DataFrame()

            index_records = []

            # Nifty 50 Proxy
            n50 = df_delivery[df_delivery["is_nifty50"] == 1]
            if not n50.empty:
                index_records.append({
                    "date": target_date,
                    "index_name": "Nifty 50",
                    "change_pct": round(float(n50["change_pct"].mean()), 2),
                    "advances_count": int((n50["change_pct"] > 0).sum()),
                    "declines_count": int((n50["change_pct"] < 0).sum()),
                })

            # Nifty Midcap 100 Proxy
            mid = df_delivery[
                (df_delivery["market_cap_tier"] == "MID")
                | ((df_delivery["is_nifty200"] == 1) & (df_delivery["is_nifty100"] == 0))
            ]
            if not mid.empty:
                index_records.append({
                    "date": target_date,
                    "index_name": "NIFTY Midcap 100",
                    "change_pct": round(float(mid["change_pct"].mean()), 2),
                    "advances_count": int((mid["change_pct"] > 0).sum()),
                    "declines_count": int((mid["change_pct"] < 0).sum()),
                })

            # Sector Indices Proxies
            for sector, grp in df_delivery.groupby("sector"):
                if not sector or pd.isna(sector):
                    continue
                sector_str = str(sector).strip()
                sector_name = f"Nifty {sector_str}" if not sector_str.lower().startswith("nifty") else sector_str
                index_records.append({
                    "date": target_date,
                    "index_name": sector_name,
                    "change_pct": round(float(grp["change_pct"].mean()), 2),
                    "advances_count": int((grp["change_pct"] > 0).sum()),
                    "declines_count": int((grp["change_pct"] < 0).sum()),
                })

            return pd.DataFrame(index_records)

    @staticmethod
    def is_sector_index(index_name: str) -> bool:
        """Determines whether an index is a sectoral / thematic industry index."""
        name_lower = index_name.lower().strip()
        sector_keywords = [
            "auto", "bank", "financial", "fmcg", "it", "media", "metal",
            "pharma", "realty", "energy", "oil & gas", "healthcare",
            "consumer durables", "cpse", "infra", "commodities", "telecom",
            "cement", "chemicals", "services", "manufacturing", "defence",
            "hospital", "housing", "psu bank", "private bank", "retail"
        ]
        # Exclude broad market benchmark indices
        broad_benchmarks = ["nifty 50", "nifty 100", "nifty 200", "nifty 500", "nifty next 50", "midcap 100", "smallcap 100", "india vix"]
        if any(b in name_lower for b in broad_benchmarks):
            return False
        return any(k in name_lower for k in sector_keywords)

    @classmethod
    def drawdown_triggers(cls, indices: pd.DataFrame) -> List[str]:
        """
        Detects Drawdown Panic Triggers:
        - Nifty 50 <= -1.5%
        - Nifty Midcap 100 <= -1.5%
        - Any Sector Index <= -3.0%
        """
        triggers: List[str] = []
        if indices.empty:
            return triggers

        for _, row in indices.iterrows():
            name = str(row.get("index_name", "")).strip()
            name_lower = name.lower()
            try:
                change = float(row.get("change_pct", 0.0) or 0.0)
            except (ValueError, TypeError):
                continue

            # Nifty 50 check (<= -1.5%)
            is_nifty50 = (
                name_lower in ["nifty 50", "nifty50"]
                or (
                    re.search(r"\bnifty\s*50\b", name_lower)
                    and not any(w in name_lower for w in ["equal", "inverse", "leverage", "futures", "usd", "value", "shariah", "dividend"])
                )
            )
            if is_nifty50:
                if change <= -1.5:
                    triggers.append(f"{name} {change:.2f}% (Trigger: Nifty 50 <= -1.5%)")
                continue

            # Nifty Midcap 100 check (<= -1.5%)
            is_midcap100 = "midcap 100" in name_lower or "midcap100" in name_lower
            if is_midcap100:
                if change <= -1.5:
                    triggers.append(f"{name} {change:.2f}% (Trigger: Nifty Midcap 100 <= -1.5%)")
                continue

            # Any Sector Index (or broader index) check (<= -3.0%)
            if cls.is_sector_index(name) or change <= -3.0:
                if change <= -3.0:
                    triggers.append(f"{name} {change:.2f}% (Trigger: Sector Index <= -3.0%)")

        return triggers

    def run_crisis_screener(self, session_date: Optional[str] = None) -> pd.DataFrame:
        """
        Identifies resilient companies with delivery absorption (institutions soaking panic)
        and zero operational impairment (non-negative YoY revenue & PAT growth, solvency approved).
        Outputs the Crisis Bargain List ranked by Crisis Factor Weighting.
        """
        date = session_date or self.repo.get_latest_price_delivery_date()
        if not date:
            return pd.DataFrame()

        candidates = self.screener.run_screener(
            target_date=date, top_n=100, universe="all", crisis_mode=True
        )
        if candidates.empty:
            return candidates

        # Criteria:
        # 1. Delivery absorption: DSR >= 2.0x AND Delivery % >= 50%
        # 2. Zero operational impairment: YoY Rev Growth >= 0% AND YoY PAT Growth >= 0%
        # 3. Strict Solvency Gate: is_solvency_approved == 1
        mask = (
            (candidates["delivery_spike_ratio"] >= 2.0)
            & (candidates["delivery_pct"] >= 50.0)
            & (candidates["yoy_revenue_growth_pct"] >= 0.0)
            & (candidates["yoy_pat_growth_pct"] >= 0.0)
            & (candidates["is_solvency_approved"] == 1)
        )
        crisis_bargains = candidates[mask].copy()
        if not crisis_bargains.empty:
            crisis_bargains = crisis_bargains.assign(crisis_bargain_list="Crisis Bargain List")
            crisis_bargains["crisis_rank"] = range(1, len(crisis_bargains) + 1)
        return crisis_bargains

    def evaluate(self, session_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Evaluates panic conditions for a session and executes crisis bargain screening
        if drawdown triggers are activated.
        """
        target_date = session_date or self.repo.get_latest_price_delivery_date()
        indices = self.latest_session(target_date)
        triggers = self.drawdown_triggers(indices)
        bargains = self.run_crisis_screener(target_date) if triggers else pd.DataFrame()

        logger.info(
            "Panic Monitor Evaluation for %s: Triggered=%s, Triggers Count=%d, Crisis Bargains Found=%d",
            target_date, bool(triggers), len(triggers), len(bargains)
        )

        return {
            "date": target_date,
            "triggered": bool(triggers),
            "triggers": triggers,
            "indices_count": len(indices),
            "crisis_bargain_list": bargains,
        }


# Singleton panic monitor instance
panic_monitor = PanicMonitor()
