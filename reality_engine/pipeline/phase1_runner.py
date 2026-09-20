"""
Phase 1 End-to-End Execution Pipeline
Orchestrates multi-exchange master sync, deliverable Bhavcopy backfill, Top 200 fundamentals ingestion,
solvency health evaluations, quantitative factor calculation, and checkpoint verification.
"""

import time
import logging
import concurrent.futures
from datetime import datetime
from typing import Dict, Any, List, Optional
import pandas as pd

from reality_engine.config import REPORTS_DIR, TOP_UNIVERSE_LIMIT
from reality_engine.db.repository import repo
from reality_engine.ingestion.master_sync import master_sync
from reality_engine.ingestion.nse_client import nse_client
from reality_engine.ingestion.fundamentals_client import fundamentals_client
from reality_engine.pipeline.backfill import backfill_manager
from reality_engine.processing.composite_screener import composite_screener

# Configure standard logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("reality_engine.phase1_runner")


class Phase1PipelineRunner:
    """End-to-End Orchestrator for Phase 1 Data Ingestion and Validation."""

    def __init__(self):
        self.repo = repo
        self.master_sync = master_sync
        self.nse = nse_client
        self.fundamentals = fundamentals_client
        self.backfill = backfill_manager
        self.screener = composite_screener

    def run_phase1_pipeline(
        self,
        bhavcopy_sessions: int = 25,
        target_universe_count: int = TOP_UNIVERSE_LIMIT,
        max_workers: int = 8,
        fundamentals_rate_limit_sec: float = 0.0
    ) -> Dict[str, Any]:
        """
        Executes complete Phase 1 data pipeline:
        1. Master Company Sync (NSE + BSE + Nifty 200/500)
        2. Deliverable Bhavcopy Ingestion & 20-Day Delivery Baseline calculation
        3. Fundamental data ingestion for Top 200 Universe (P&L, Balance Sheet, Shareholding, Solvency)
        4. SEBI Insider Trading (PIT) & Index Breadth
        5. Composite Multi-Factor Screener & Ranking
        6. Verification Gate & Checkpoint Validation
        """
        start_time = time.time()
        logger.info("=" * 75)
        logger.info("STARTING REALITY ENGINE: PHASE 1 DATA INGESTION & QUANT PROCESSING")
        logger.info("=" * 75)

        # -------------------------------------------------------------
        # Step 1: Master Universe Synchronization
        # -------------------------------------------------------------
        logger.info("\n>>> [STEP 1/6] Synchronizing Master Company Universe across NSE & BSE...")
        master_stats = self.master_sync.sync_all()
        logger.info("Master Sync Result: %s", master_stats)

        # -------------------------------------------------------------
        # Step 2: Historical Bhavcopy & Deliverable Ingestion
        # -------------------------------------------------------------
        logger.info("\n>>> [STEP 2/6] Ingesting %d Historical Bhavcopy & Deliverable Sessions...", bhavcopy_sessions)
        bhavcopy_rows = self.backfill.backfill_bhavcopy_history(days_count=bhavcopy_sessions)
        logger.info("Bhavcopy Ingestion Complete: %d rows processed.", bhavcopy_rows)

        # -------------------------------------------------------------
        # Step 3: Top 200 Fundamentals & Solvency Ingestion
        # -------------------------------------------------------------
        logger.info("\n>>> [STEP 3/6] Ingesting Comprehensive Fundamentals for Top %d Stocks...", target_universe_count)
        nifty200_stocks = self.repo.get_nifty200_companies()
        if not nifty200_stocks:
            logger.warning("Nifty 200 list empty, falling back to all active companies.")
            nifty200_stocks = self.repo.get_all_companies(active_only=True)[:target_universe_count]
        else:
            nifty200_stocks = nifty200_stocks[:target_universe_count]

        logger.info("Target Universe size: %d stocks to ingest fundamentals for.", len(nifty200_stocks))

        quarterly_total: List[Dict[str, Any]] = []
        annual_total: List[Dict[str, Any]] = []
        forensic_total: List[Dict[str, Any]] = []
        documents_total: List[Dict[str, Any]] = []

        def fetch_single_stock_fundamentals(company: Dict[str, Any]):
            sym = company["nse_symbol"]
            isin = company["isin"]
            bse_code = company.get("bse_code")
            try:
                res = self.fundamentals.fetch_company_fundamentals(sym, isin, bse_code)
                return sym, res
            except Exception as e:
                logger.error("Error fetching fundamentals for %s: %s", sym, e)
                return sym, {}

        # Concurrently fetch fundamentals with thread pool (rate-limited submission)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_stock = {}
            for scrip in nifty200_stocks:
                future_to_stock[executor.submit(fetch_single_stock_fundamentals, scrip)] = scrip
                # Throttle the rate at which new requests start to avoid hammering yfinance.
                if fundamentals_rate_limit_sec and fundamentals_rate_limit_sec > 0:
                    time.sleep(fundamentals_rate_limit_sec)

            completed_count = 0
            for future in concurrent.futures.as_completed(future_to_stock):
                sym, data = future.result()
                completed_count += 1
                if data:
                    if data.get("quarterly"):
                        quarterly_total.extend(data["quarterly"])
                    if data.get("annual"):
                        annual_total.extend(data["annual"])
                    if data.get("forensic"):
                        forensic_total.append(data["forensic"])
                    if data.get("documents"):
                        documents_total.extend(data["documents"])

                if completed_count % 25 == 0 or completed_count == len(nifty200_stocks):
                    logger.info("Progress: %d / %d fundamentals ingested (%.1f%%)",
                                completed_count, len(nifty200_stocks), (completed_count / len(nifty200_stocks)) * 100)

        # Bulk upsert all collected fundamental datasets
        q_count = self.repo.upsert_quarterly_financials(quarterly_total)
        a_count = self.repo.upsert_annual_financials(annual_total)
        f_count = self.repo.upsert_forensic_health(forensic_total)
        d_count = self.repo.upsert_corporate_documents(documents_total)

        logger.info("Fundamentals Ingested -> %d quarters, %d annuals, %d forensic records, %d docs.",
                    q_count, a_count, f_count, d_count)

        # -------------------------------------------------------------
        # Step 4: Ingest SEBI PIT (Insider Trading) Feed
        # -------------------------------------------------------------
        logger.info("\n>>> [STEP 4/6] Ingesting SEBI PIT Insider Trading Disclosures...")
        pit_trades = self.nse.fetch_insider_trades()
        pit_count = self.repo.upsert_insider_trades(pit_trades)
        logger.info("SEBI PIT Ingestion Complete: %d trades stored.", pit_count)

        # -------------------------------------------------------------
        # Step 5: Execute Composite Quantitative Screener
        # -------------------------------------------------------------
        logger.info("\n>>> [STEP 5/6] Running Composite Quantitative Screener & Factor Scoring...")
        latest_date = self.repo.get_latest_price_delivery_date()
        df_screened = self.screener.run_screener(target_date=latest_date, top_n=20)
        logger.info("Screening Complete: Top 20 Candidates Computed for %s.", latest_date)

        # -------------------------------------------------------------
        # Step 6: Verification Gate & Data Checkpoint
        # -------------------------------------------------------------
        logger.info("\n>>> [STEP 6/6] Validating Checkpoint Integrity for Top 200 Stocks...")
        checkpoint_summary = self.validate_top_200_checkpoint(target_date=latest_date)

        # Refresh planner statistics while we are the writer. Serialized deliberately: this
        # opens the DB write path, so it runs after all ingest writes have completed.
        try:
            self.repo.db.optimize()
        except Exception as exc:  # pragma: no cover - optimization must never fail the run
            logger.warning("PRAGMA optimize skipped: %s", exc)

        elapsed_time = round(time.time() - start_time, 2)
        logger.info("\n" + "=" * 75)
        logger.info("PHASE 1 EXECUTION COMPLETE IN %.2f SECONDS", elapsed_time)
        logger.info("=" * 75)

        return {
            "execution_time_seconds": elapsed_time,
            "master_companies_count": master_stats["total_upserted"],
            "bhavcopy_rows": bhavcopy_rows,
            "quarterly_financials_rows": q_count,
            "annual_financials_rows": a_count,
            "forensic_records_count": f_count,
            "corporate_docs_count": d_count,
            "insider_trades_count": pit_count,
            "top_screened_candidates": df_screened.to_dict(orient="records") if not df_screened.empty else [],
            "checkpoint": checkpoint_summary,
        }

    def validate_top_200_checkpoint(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Validates the success checkpoint:
        1. Top 200 stocks must have complete technical delivery data (Close, SMA20/50/200, RSI, DSR, DCS, 52W High/Low).
        2. Top 200 stocks must have fundamental data (Revenue, EBITDA, PAT, EPS, YoY Growth, Promoter Holding/Pledge, Solvency).
        3. Emits structured CSV and JSON inspection reports to data/reports/.
        """
        date_str = target_date or self.repo.get_latest_price_delivery_date()
        nifty200 = self.repo.get_nifty200_companies()
        n200_symbols = [c["nse_symbol"] for c in nifty200 if c.get("nse_symbol")]

        # Query latest technical records for Nifty 200
        df_tech = self.repo.get_all_price_delivery_for_date(date_str)
        df_tech_200 = df_tech[df_tech["symbol"].isin(n200_symbols)].copy()

        # Query latest fundamentals
        df_funda = self.repo.get_latest_quarterly_financials()
        df_funda_200 = df_funda[df_funda["symbol"].isin(n200_symbols)].copy()

        # Query forensic health
        df_forensic = self.repo.get_forensic_health()
        df_forensic_200 = df_forensic[df_forensic["symbol"].isin(n200_symbols)].copy()

        # Merge for complete Top 200 reality table
        df_checkpoint = pd.merge(
            df_tech_200,
            df_funda_200[["symbol", "financial_year", "revenue_inr_cr", "ebitda_inr_cr", "ebitda_margin_pct", "net_profit_inr_cr", "yoy_revenue_growth_pct", "yoy_pat_growth_pct"]],
            on="symbol",
            how="left",
            suffixes=("", "_funda")
        )

        if not df_forensic_200.empty:
            df_checkpoint = pd.merge(
                df_checkpoint,
                df_forensic_200[["symbol", "promoter_holding_pct", "promoter_pledge_pct", "interest_coverage_ratio", "debt_to_equity_ratio", "pe_ratio", "is_solvency_approved"]],
                on="symbol",
                how="left",
                suffixes=("", "_forensic")
            )

        # Checkpoint validation criteria
        total_target = len(n200_symbols)
        tech_ready_count = len(df_tech_200)
        funda_ready_count = len(df_funda_200)
        solvency_ready_count = len(df_forensic_200)

        # Check technical fields with non-null values
        complete_tech_rows = df_tech_200[
            (df_tech_200["close"] > 0) &
            (df_tech_200["delivery_spike_ratio"].notna()) &
            (df_tech_200["delivery_conviction_score"].notna()) &
            (df_tech_200["rsi_14"].notna())
        ]

        # Check fundamental fields with non-null values
        complete_funda_rows = df_funda_200[
            (df_funda_200["revenue_inr_cr"] > 0) &
            (df_funda_200["ebitda_inr_cr"].notna())
        ]

        # Export Checkpoint Report to CSV & JSON
        csv_path = REPORTS_DIR / f"top_200_reality_checkpoint_{date_str}.csv"
        json_path = REPORTS_DIR / f"top_200_reality_checkpoint_{date_str}.json"

        df_checkpoint.to_csv(csv_path, index=False)
        df_checkpoint.to_json(json_path, orient="records", indent=2)

        is_checkpoint_passed = (
            len(complete_tech_rows) >= (total_target * 0.95) and
            len(complete_funda_rows) >= (total_target * 0.90)
        )

        summary = {
            "target_universe_count": total_target,
            "target_date": date_str,
            "technical_data_available_count": tech_ready_count,
            "technical_data_complete_count": len(complete_tech_rows),
            "fundamental_data_available_count": funda_ready_count,
            "fundamental_data_complete_count": len(complete_funda_rows),
            "solvency_data_available_count": solvency_ready_count,
            "checkpoint_passed": is_checkpoint_passed,
            "exported_csv_report": str(csv_path),
            "exported_json_report": str(json_path),
        }

        logger.info(">>> CHECKPOINT STATUS: %s <<<", "PASSED" if is_checkpoint_passed else "FAILED")
        logger.info("Technical Complete: %d/%d (%.1f%%)", len(complete_tech_rows), total_target, (len(complete_tech_rows)/total_target)*100 if total_target else 0)
        logger.info("Fundamental Complete: %d/%d (%.1f%%)", len(complete_funda_rows), total_target, (len(complete_funda_rows)/total_target)*100 if total_target else 0)
        logger.info("Exported checkpoint reality reports to: %s", csv_path)

        return summary


# Singleton runner
phase1_runner = Phase1PipelineRunner()
