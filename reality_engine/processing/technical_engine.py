"""
Technical Processing Engine Module
Vectorized computation of 20-day Delivery SMAs, Delivery Spike Ratios,
Delivery Conviction Scores, 20/50/200 SMAs, 14-period RSI, 52-Week Highs/Lows,
and Technical Flow Momentum Factor Scores (S_TechFlow).
"""

import logging
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

logger = logging.getLogger("reality_engine.technical_engine")


class TechnicalEngine:
    """Calculates rolling delivery analytics, technical momentum indicators, and factor scores."""

    @staticmethod
    def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """Computes Wilder's Relative Strength Index (RSI)."""
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -1 * delta.clip(upper=0)

        # Exponential moving average with com = period - 1 (Wilder's smoothing)
        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50.0)

    def calculate_indicators_for_symbol(self, df_history: pd.DataFrame) -> pd.DataFrame:
        """
        Takes historical price & delivery rows for a single symbol (sorted by date ASC),
        and computes all rolling technical and delivery indicators.
        """
        if df_history.empty:
            return df_history

        df = df_history.sort_values(by="date", ascending=True).copy()

        # Ensure numeric types
        for col in ["close", "high", "low", "deliverable_volume", "delivery_pct", "total_volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        # 1. 20-Day SMA of Deliverable Volume
        # If fewer than 20 rows, use available min_periods=1
        df["deliv_sma_20"] = df["deliverable_volume"].rolling(window=20, min_periods=1).mean()
        
        # 2. Delivery Spike Ratio (DSR)
        df["delivery_spike_ratio"] = (
            df["deliverable_volume"] / df["deliv_sma_20"].replace(0, np.nan)
        ).fillna(1.0).round(2)

        # 3. Delivery Conviction Score (DCS) = DSR * Delivery %
        df["delivery_conviction_score"] = (
            df["delivery_spike_ratio"] * df["delivery_pct"]
        ).round(2)

        # 4. Moving Averages (20, 50, 200)
        df["sma_20"] = df["close"].rolling(window=20, min_periods=1).mean().round(2)
        df["sma_50"] = df["close"].rolling(window=50, min_periods=1).mean().round(2)
        df["sma_200"] = df["close"].rolling(window=200, min_periods=1).mean().round(2)

        # 5. RSI (14)
        if len(df) >= 5:
            df["rsi_14"] = self.compute_rsi(df["close"], period=14).round(2)
        else:
            df["rsi_14"] = 50.0

        # 6. 52-Week High & Low (250 trading sessions)
        df["high_52w"] = df["high"].rolling(window=250, min_periods=1).max().round(2)
        df["low_52w"] = df["low"].rolling(window=250, min_periods=1).min().round(2)

        # 7. Distance from 52-Week High (%)
        df["distance_from_52w_high_pct"] = (
            ((df["high_52w"] - df["close"]) / df["high_52w"].replace(0, np.nan)) * 100.0
        ).fillna(0.0).round(2)

        return df

    def compute_technical_flow_score(self, row: pd.Series) -> float:
        """
        Computes Factor 1: Technical Flow & Institutional Delivery Momentum Score (0 - 100).
        Formula:
        S_TechFlow = min(100, (DCS * 0.35) + (max(0, 15 - Dist52W) * 2.5) + (Trend * 15) + (RSI_Mom * 15))
        """
        dcs = float(row.get("delivery_conviction_score", 0.0) or 0.0)
        dist_52w = float(row.get("distance_from_52w_high_pct", 15.0) or 15.0)
        close = float(row.get("close", 0.0) or 0.0)
        sma20 = float(row.get("sma_20", 0.0) or 0.0)
        sma50 = float(row.get("sma_50", 0.0) or 0.0)
        sma200 = float(row.get("sma_200", 0.0) or 0.0)
        rsi = float(row.get("rsi_14", 50.0) or 50.0)

        # Trend Filter: Close > SMA20 > SMA50 > SMA200 (or Close > SMA20 > SMA50)
        is_trending = 1.0 if (close > sma20 and sma20 >= sma50) else 0.0
        if sma200 > 0 and sma50 >= sma200:
            is_trending += 0.5

        # RSI Momentum: Sweet spot between 55 and 72
        rsi_momentum = 1.0 if (55.0 <= rsi <= 75.0) else (0.5 if (45.0 <= rsi < 55.0) else 0.0)

        score = (
            (dcs * 0.35)
            + (max(0.0, 15.0 - dist_52w) * 2.5)
            + (is_trending * 15.0)
            + (rsi_momentum * 15.0)
        )
        return float(np.clip(score, 0.0, 100.0))


# Singleton technical engine
technical_engine = TechnicalEngine()
