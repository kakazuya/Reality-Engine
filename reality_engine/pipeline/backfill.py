"""
Historical Backfill Pipeline Module
Fetches past trading sessions of full deliverable Bhavcopy, ingests them into SQLite,
and computes historical 20-day rolling delivery baselines, SMAs, RSI, and 52W metrics.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np

from reality_engine.ingestion.nse_client import nse_client
from reality_engine.db.repository import repo
from reality_engine.processing.technical_engine import technical_engine

logger = logging.getLogger("reality_engine.backfill")


def rolling_indicators_polars(df_all):
    """Batch rolling indicators via polars; pandas in, pandas out (edge convert).

    Covers the groupby-rolling SMA/high/low legs (measured 1.55 s -> 0.51 s on
    3.12M rows). RSI stays pandas (Wilder ewm has no polars one-liner); the
    elementwise ratio legs stay pandas. Returns None when polars is missing so
    callers fall back to the pandas path (never a hard dependency).
    """
    try:
        import polars as pl
    except ImportError:
        return None
    work = pl.from_pandas(df_all[["symbol", "close", "high", "low", "deliverable_volume"]])
    out = work.with_columns([
        pl.col("deliverable_volume").rolling_mean(20, min_samples=1).over("symbol").alias("deliv_sma_20"),
        pl.col("close").rolling_mean(20, min_samples=1).over("symbol").alias("sma_20"),
        pl.col("close").rolling_mean(50, min_samples=1).over("symbol").alias("sma_50"),
        pl.col("close").rolling_mean(200, min_samples=1).over("symbol").alias("sma_200"),
        pl.col("high").rolling_max(250, min_samples=1).over("symbol").alias("high_52w"),
        pl.col("low").rolling_min(250, min_samples=1).over("symbol").alias("low_52w"),
    ]).to_pandas()
    for col in ("deliv_sma_20", "sma_20", "sma_50", "sma_200", "high_52w", "low_52w"):
        df_all[col] = out[col].to_numpy()
    return df_all


class HistoricalBackfillManager:
    """Manages multi-day Bhavcopy ingestion and technical indicator backfills."""

    def __init__(self):
        self.nse = nse_client
        self.repo = repo
        self.tech_engine = technical_engine

    def backfill_bhavcopy_history(self, days_count: int = 25, end_date: Optional[datetime] = None) -> int:
        """
        Downloads and ingests historical Bhavcopy for `days_count` active trading sessions.
        Computes rolling delivery SMAs, RSI, and technical indicators in a single high-performance pipeline.
        """
        logger.info("Starting historical Bhavcopy backfill for past %d trading sessions...", days_count)

        # 1. Identify valid trading days with Bhavcopy
        trading_days = self.nse.find_recent_trading_days(count=days_count, end_date=end_date)
        if not trading_days:
            logger.error("No valid trading days found.")
            return 0

        # Load symbol-to-ISIN lookup from master_companies
        companies = self.repo.get_all_companies(active_only=False)
        sym_to_isin = {c["nse_symbol"]: c["isin"] for c in companies if c.get("nse_symbol")}

        dfs = []
        for day in trading_days:
            date_str = day.strftime("%Y-%m-%d")
            logger.info("Processing Bhavcopy for session: %s", date_str)

            # Isolate per-day failures so one bad/malformed session cannot abort
            # the entire multi-day backfill run.
            try:
                df_bhav = self.nse.fetch_bhavcopy(day)
            except Exception as e:
                logger.warning("Bhavcopy fetch raised for %s (%s). Skipping session.", date_str, e)
                continue

            if df_bhav is None or df_bhav.empty:
                logger.warning("Bhavcopy empty for %s, skipping", date_str)
                continue
            dfs.append(df_bhav)

        if not dfs:
            return 0

        df_all = pd.concat(dfs, ignore_index=True)
        df_all["date"] = df_all["DATE"]
        df_all["symbol"] = df_all["SYMBOL"].astype(str).str.strip()

        # Check for unknown symbols and auto-register in master_companies
        unknown_syms = set(df_all["symbol"].unique()) - set(sym_to_isin.keys())
        if unknown_syms:
            new_stubs = [{
                "isin": f"INE_AUTO_{sym}",
                "nse_symbol": sym,
                "bse_code": None,
                "company_name": sym,
                "industry": "Other",
                "sector": "Other",
                "market_cap_tier": "MICRO",
                "is_fno_eligible": 0,
                "is_nifty50": 0,
                "is_nifty100": 0,
                "is_nifty200": 0,
                "is_nifty500": 0,
                "is_active": 1
            } for sym in unknown_syms if sym]
            self.repo.upsert_master_companies(new_stubs)
            for s in unknown_syms:
                sym_to_isin[s] = f"INE_AUTO_{s}"

        df_all["isin"] = df_all["symbol"].map(sym_to_isin).fillna("INE_AUTO_" + df_all["symbol"])
        df_all["series"] = df_all.get("SERIES", "EQ").astype(str).str.strip()
        df_all["open"] = pd.to_numeric(df_all["OPEN_PRICE"], errors="coerce").fillna(0.0)
        df_all["high"] = pd.to_numeric(df_all["HIGH_PRICE"], errors="coerce").fillna(0.0)
        df_all["low"] = pd.to_numeric(df_all["LOW_PRICE"], errors="coerce").fillna(0.0)
        df_all["close"] = pd.to_numeric(df_all["CLOSE_PRICE"], errors="coerce").fillna(0.0)
        df_all["prev_close"] = pd.to_numeric(df_all["PREV_CLOSE"], errors="coerce").fillna(0.0)
        df_all["change_pct"] = np.where(
            df_all["prev_close"] > 0,
            ((df_all["close"] - df_all["prev_close"]) / df_all["prev_close"]) * 100.0,
            0.0
        ).round(2)
        df_all["total_volume"] = pd.to_numeric(df_all["TTL_TRD_QNTY"], errors="coerce").fillna(0).astype(int)
        df_all["turnover_lacs"] = pd.to_numeric(df_all["TURNOVER_LACS"], errors="coerce").fillna(0.0)
        df_all["num_trades"] = pd.to_numeric(df_all["NO_OF_TRADES"], errors="coerce").fillna(0).astype(int)
        df_all["deliverable_volume"] = pd.to_numeric(df_all["DELIV_QTY"], errors="coerce").fillna(0).astype(int)
        df_all["delivery_pct"] = pd.to_numeric(df_all["DELIV_PER"], errors="coerce").fillna(0.0)

        # Sort for rolling computations
        df_all = df_all.sort_values(by=["symbol", "date"], ascending=True).reset_index(drop=True)

        # Groupby rolling indicator computations (polars fast path, pandas fallback).
        if rolling_indicators_polars(df_all) is None:
            g = df_all.groupby("symbol", sort=False)
            df_all["deliv_sma_20"] = g["deliverable_volume"].rolling(20, min_periods=1).mean().reset_index(level=0, drop=True)
            df_all["sma_20"] = g["close"].rolling(20, min_periods=1).mean().reset_index(level=0, drop=True)
            df_all["sma_50"] = g["close"].rolling(50, min_periods=1).mean().reset_index(level=0, drop=True)
            df_all["sma_200"] = g["close"].rolling(200, min_periods=1).mean().reset_index(level=0, drop=True)
            df_all["high_52w"] = g["high"].rolling(250, min_periods=1).max().reset_index(level=0, drop=True)
            df_all["low_52w"] = g["low"].rolling(250, min_periods=1).min().reset_index(level=0, drop=True)
        else:
            g = df_all.groupby("symbol", sort=False)
        for col in ("sma_20", "sma_50", "sma_200", "high_52w", "low_52w"):
            df_all[col] = df_all[col].round(2)
        df_all["delivery_spike_ratio"] = (
            df_all["deliverable_volume"] / df_all["deliv_sma_20"].replace(0, np.nan)
        ).fillna(1.0).round(2)
        df_all["delivery_conviction_score"] = (
            df_all["delivery_spike_ratio"] * df_all["delivery_pct"]
        ).round(2)
        df_all["distance_from_52w_high_pct"] = (
            ((df_all["high_52w"] - df_all["close"]) / df_all["high_52w"].replace(0, np.nan)) * 100.0
        ).fillna(0.0).round(2)

        def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
            if len(series) < 5:
                return pd.Series(50.0, index=series.index)
            delta = series.diff()
            gain = delta.clip(lower=0)
            loss = -1 * delta.clip(upper=0)
            avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
            avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            rsi = 100 - (100 / (1 + rs))
            return rsi.fillna(50.0)

        df_all["rsi_14"] = g["close"].transform(_compute_rsi).round(2)

        cols = [
            "date", "symbol", "isin", "series", "open", "high", "low", "close", "prev_close",
            "change_pct", "total_volume", "turnover_lacs", "num_trades",
            "deliverable_volume", "delivery_pct", "delivery_spike_ratio",
            "delivery_conviction_score", "sma_20", "sma_50", "sma_200", "rsi_14",
            "high_52w", "low_52w", "distance_from_52w_high_pct"
        ]

        with self.repo.db.session() as conn:
            df_all[cols].to_sql("temp_bulk_bhav", conn, if_exists="replace", index=False)
            conn.execute("""
                INSERT OR REPLACE INTO daily_price_delivery (
                    date, symbol, isin, series, open, high, low, close, prev_close,
                    change_pct, total_volume, turnover_lacs, num_trades,
                    deliverable_volume, delivery_pct, delivery_spike_ratio,
                    delivery_conviction_score, sma_20, sma_50, sma_200, rsi_14,
                    high_52w, low_52w, distance_from_52w_high_pct
                ) SELECT * FROM temp_bulk_bhav
            """)
            conn.execute("DROP TABLE IF EXISTS temp_bulk_bhav")

        total_inserted = len(df_all)
        logger.info("Ingested and calculated %d total price delivery records across %d sessions.", total_inserted, len(trading_days))

        # 2. Ingest Index Bhavcopy for the most recent trading days
        for day in trading_days[-5:]:
            try:
                df_idx = self.nse.fetch_index_bhavcopy(day)
            except Exception as e:
                logger.warning("Index Bhavcopy fetch failed for %s (%s); skipping day.", day.strftime("%Y-%m-%d"), e)
                continue
            if df_idx is not None and not df_idx.empty:
                idx_records: List[Dict[str, Any]] = []
                for _, r in df_idx.iterrows():
                    name = str(r.get("Index Name", "")).strip()
                    if not name:
                        continue

                    def safe_float(val):
                        v = pd.to_numeric(val, errors="coerce")
                        return float(v) if pd.notna(v) else 0.0

                    def safe_int(val):
                        v = pd.to_numeric(val, errors="coerce")
                        return int(v) if pd.notna(v) else 0

                    idx_rec = {
                        "date": day.strftime("%Y-%m-%d"),
                        "index_name": name,
                        "open": safe_float(r.get("Open Index Value")),
                        "high": safe_float(r.get("High Index Value")),
                        "low": safe_float(r.get("Low Index Value")),
                        "close": safe_float(r.get("Closing Index Value")),
                        "change_pct": safe_float(r.get("Change(%)")),
                        "points_change": safe_float(r.get("Points Change")),
                        "volume": safe_int(r.get("Volume")),
                        "turnover_cr": safe_float(r.get("Turnover (Rs. Cr.)")),
                        "advances_count": 0,
                        "declines_count": 0,
                        "advance_decline_ratio": 1.0,
                        "pe_ratio": safe_float(r.get("P/E")),
                        "pb_ratio": safe_float(r.get("P/B")),
                        "dividend_yield": safe_float(r.get("Div Yield")),
                    }
                    idx_records.append(idx_rec)
                self.repo.upsert_index_breadth(idx_records)

        # Refresh planner statistics while we are the writer (see DatabaseManager.optimize).
        try:
            self.repo.db.optimize()
        except Exception as exc:  # pragma: no cover - optimization must never fail the run
            logger.warning("PRAGMA optimize skipped: %s", exc)

        return total_inserted

    def recalculate_all_technical_indicators(self) -> int:
        """
        Groups time-series data by symbol and calculates rolling 20-day delivery SMAs,
        delivery spike ratios, conviction scores, SMAs (20/50/200), RSI-14, and 52W metrics.
        Optimized with vectorized pandas operations.
        """
        logger.info("Recalculating rolling indicators for all active symbols...")

        with self.repo.db.session() as conn:
            df_all = pd.read_sql_query(
                "SELECT * FROM daily_price_delivery ORDER BY symbol, date ASC",
                conn
            )

        if df_all.empty:
            logger.warning("No price delivery records to compute.")
            return 0

        # Ensure numeric columns
        for col in ["close", "high", "low", "deliverable_volume", "delivery_pct", "total_volume"]:
            if col in df_all.columns:
                df_all[col] = pd.to_numeric(df_all[col], errors="coerce").fillna(0.0)

        if rolling_indicators_polars(df_all) is None:
            g = df_all.groupby("symbol", sort=False)
            df_all["deliv_sma_20"] = g["deliverable_volume"].rolling(20, min_periods=1).mean().reset_index(level=0, drop=True)
            df_all["sma_20"] = g["close"].rolling(20, min_periods=1).mean().reset_index(level=0, drop=True)
            df_all["sma_50"] = g["close"].rolling(50, min_periods=1).mean().reset_index(level=0, drop=True)
            df_all["sma_200"] = g["close"].rolling(200, min_periods=1).mean().reset_index(level=0, drop=True)
            df_all["high_52w"] = g["high"].rolling(250, min_periods=1).max().reset_index(level=0, drop=True)
            df_all["low_52w"] = g["low"].rolling(250, min_periods=1).min().reset_index(level=0, drop=True)
        else:
            g = df_all.groupby("symbol", sort=False)
        for col in ("sma_20", "sma_50", "sma_200", "high_52w", "low_52w"):
            df_all[col] = df_all[col].round(2)
        df_all["delivery_spike_ratio"] = (
            df_all["deliverable_volume"] / df_all["deliv_sma_20"].replace(0, float("nan"))
        ).fillna(1.0).round(2)
        df_all["delivery_conviction_score"] = (
            df_all["delivery_spike_ratio"] * df_all["delivery_pct"]
        ).round(2)
        df_all["distance_from_52w_high_pct"] = (
            ((df_all["high_52w"] - df_all["close"]) / df_all["high_52w"].replace(0, float("nan"))) * 100.0
        ).fillna(0.0).round(2)

        def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
            if len(series) < 5:
                return pd.Series(50.0, index=series.index)
            delta = series.diff()
            gain = delta.clip(lower=0)
            loss = -1 * delta.clip(upper=0)
            avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
            avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
            rs = avg_gain / avg_loss.replace(0, float("nan"))
            rsi = 100 - (100 / (1 + rs))
            return rsi.fillna(50.0)

        df_all["rsi_14"] = g["close"].transform(_compute_rsi).round(2)

        # Fast bulk replace into daily_price_delivery
        with self.repo.db.session() as conn:
            df_all.to_sql("temp_daily_calc", conn, if_exists="replace", index=False)
            conn.execute("""
                INSERT OR REPLACE INTO daily_price_delivery (
                    date, symbol, isin, series, open, high, low, close, prev_close,
                    change_pct, total_volume, turnover_lacs, num_trades,
                    deliverable_volume, delivery_pct, delivery_spike_ratio,
                    delivery_conviction_score, sma_20, sma_50, sma_200, rsi_14,
                    high_52w, low_52w, distance_from_52w_high_pct
                ) SELECT 
                    date, symbol, isin, series, open, high, low, close, prev_close,
                    change_pct, total_volume, turnover_lacs, num_trades,
                    deliverable_volume, delivery_pct, delivery_spike_ratio,
                    delivery_conviction_score, sma_20, sma_50, sma_200, rsi_14,
                    high_52w, low_52w, distance_from_52w_high_pct
                FROM temp_daily_calc
            """)
            conn.execute("DROP TABLE IF EXISTS temp_daily_calc")

        logger.info("Calculated and updated indicators for %d price delivery rows.", len(df_all))
        return len(df_all)


# Singleton backfill manager
backfill_manager = HistoricalBackfillManager()
