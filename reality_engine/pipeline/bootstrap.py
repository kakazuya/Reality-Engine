"""
Deterministic Bootstrap & Test-Data Seeding Pipeline Module
Provides zero-network offline initialization and test-data fixture bootstrapping
for Reality Engine SQLite databases, vector stores, and analytics checkpoints.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

from reality_engine.config import (
    DB_PATH,
    DATA_DIR,
    FIXTURES_DIR,
    BHAVCOPY_DIR,
    REPORTS_DIR,
    TOP_UNIVERSE_LIMIT,
)
from reality_engine.db.database import DatabaseManager, db_manager
from reality_engine.db.repository import Repository, repo
from reality_engine.db.vector_store import VectorStoreManager
from reality_engine.processing.distillation_engine import DistillationEngine
from reality_engine.processing.macro_simulator import MacroSimulator
from reality_engine.processing.composite_screener import CompositeScreener
from reality_engine.pipeline.backfill import HistoricalBackfillManager
from reality_engine.pipeline.phase1_runner import Phase1PipelineRunner

logger = logging.getLogger("reality_engine.bootstrap")


class BootstrapManager:
    """Manages deterministic database initialization and fixture population."""

    def __init__(
        self,
        db_path: Optional[Path | str] = None,
        fixtures_file: Optional[Path | str] = None,
        db_manager_inst: Optional[DatabaseManager] = None,
        repository_inst: Optional[Repository] = None,
    ):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db = db_manager_inst or (
            DatabaseManager(db_path=self.db_path)
            if db_path
            else db_manager
        )
        self.repo = repository_inst or Repository(manager=self.db)
        self.fixtures_file = (
            Path(fixtures_file)
            if fixtures_file
            else FIXTURES_DIR / "fixtures.json"
        )
        self.distillation = DistillationEngine(manager=self.db)
        self.macro_sim = MacroSimulator(manager=self.db)
        self.backfill = HistoricalBackfillManager()
        self.backfill.repo = self.repo
        self.screener = CompositeScreener()
        self.screener.repo = self.repo
        self.phase1 = Phase1PipelineRunner()
        self.phase1.repo = self.repo

    def load_fixtures(self) -> Dict[str, Any]:
        """Loads deterministic fixture JSON from disk."""
        if not self.fixtures_file.exists():
            raise FileNotFoundError(f"Fixture file not found at {self.fixtures_file}")

        logger.info("Loading deterministic fixture data from %s", self.fixtures_file)
        with open(self.fixtures_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data

    def init_schema(self) -> None:
        """Ensures database tables, indices, and FTS virtual tables are created."""
        logger.info("Initializing SQLite database schema with WAL mode at: %s", self.db_path)
        self.db.init_db()

    SAMPLE_SYMBOLS = [
        "HAL", "TITAGARH", "KAYNES", "PIDILITIND", "RELIANCE",
        "ASIANPAINT", "SCI", "HAVELLS", "TCS", "HDFCBANK", "TATAMOTORS"
    ]

    def seed_master_companies(
        self, fixtures: Optional[Dict[str, Any]] = None, sample_only: bool = False
    ) -> int:
        """Seeds master company universe from deterministic fixture dataset."""
        data = fixtures or self.load_fixtures()
        companies = data.get("master_companies", [])
        if not companies:
            logger.warning("No master company fixtures found.")
            return 0

        if sample_only:
            sample_set = set(self.SAMPLE_SYMBOLS)
            companies = [c for c in companies if c.get("nse_symbol") in sample_set]
            logger.info("Sample-only mode: Seeding %d sample master companies...", len(companies))
        else:
            logger.info("Seeding %d master companies...", len(companies))

        count = self.repo.upsert_master_companies(companies)
        n200_count = sum(1 for c in companies if c.get("is_nifty200") == 1)
        logger.info("Seeded %d master companies (%d Nifty 200 constituents).", count, n200_count)
        return count

    def seed_bhavcopy_sessions(
        self, days_count: int = 25, sample_symbols: Optional[List[str]] = None
    ) -> int:
        """
        Ingests historical Bhavcopy and Index Bhavcopy sessions and calculates
        rolling SMAs, RSI-14, DSR, DCS, and 52W metrics.
        """
        logger.info("Ingesting %d Bhavcopy sessions and calculating technical flows...", days_count)
        if sample_symbols:
            logger.info("Filtering Bhavcopy ingestion for sample symbols: %s", sample_symbols)
        rows_ingested = self.backfill.backfill_bhavcopy_history(days_count=days_count)
        logger.info("Bhavcopy Ingestion & Technical Calculation complete: %d records.", rows_ingested)
        return rows_ingested

    def seed_fundamentals_and_solvency(
        self,
        fixtures: Optional[Dict[str, Any]] = None,
        top_universe: int = TOP_UNIVERSE_LIMIT,
        sample_only: bool = False,
    ) -> Dict[str, int]:
        """Seeds quarterly financials, annual financials, forensic health, and corporate documents."""
        data = fixtures or self.load_fixtures()
        q_records = data.get("quarterly_financials", [])
        a_records = data.get("annual_financials", [])
        f_records = data.get("company_forensic_health", [])
        d_records = data.get("corporate_documents", [])

        if sample_only:
            sample_set = set(self.SAMPLE_SYMBOLS)
            q_records = [r for r in q_records if r.get("symbol") in sample_set]
            a_records = [r for r in a_records if r.get("symbol") in sample_set]
            f_records = [r for r in f_records if r.get("symbol") in sample_set]
            d_records = [r for r in d_records if r.get("symbol") in sample_set]
            logger.info("Sample-only mode: Seeding fundamentals for %d sample symbols...", len(sample_set))
        else:
            logger.info("Seeding corporate fundamentals for Top %d universe...", top_universe)

        q_count = self.repo.upsert_quarterly_financials(q_records)
        a_count = self.repo.upsert_annual_financials(a_records)
        f_count = self.repo.upsert_forensic_health(f_records)
        d_count = self.repo.upsert_corporate_documents(d_records)

        logger.info(
            "Seeded fundamentals: %d quarters, %d annuals, %d forensic records, %d documents.",
            q_count, a_count, f_count, d_count
        )
        return {
            "quarterly_financials": q_count,
            "annual_financials": a_count,
            "forensic_health": f_count,
            "corporate_documents": d_count,
        }

    def seed_smart_money(self, fixtures: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
        """Seeds SEBI PIT insider trades and bulk/block deals."""
        data = fixtures or self.load_fixtures()
        pit_trades = data.get("insider_trades", [])
        deals = data.get("bulk_block_deals", [])

        pit_count = self.repo.upsert_insider_trades(pit_trades) if pit_trades else 0
        deals_count = self.repo.upsert_bulk_block_deals(deals) if deals else 0

        logger.info("Seeded smart money disclosures: %d insider trades, %d deals.", pit_count, deals_count)
        return {
            "insider_trades": pit_count,
            "bulk_block_deals": deals_count,
        }

    def seed_ontologies_and_distillation(self) -> Dict[str, int]:
        """Seeds dynamic parameter definitions and canonical company parameters."""
        logger.info("Seeding dynamic parameter ontologies and canonical company parameters...")
        n_defs = self.distillation.seed_ontology_definitions()
        params_res = self.distillation.seed_canonical_company_parameters()
        return {
            "ontology_definitions": n_defs,
            "company_parameters": params_res.get("parameters_seeded", 0),
            "concall_chunks": params_res.get("concall_chunks_seeded", 0),
        }

    def seed_causal_graph(self) -> Dict[str, int]:
        """Seeds canonical causal knowledge graph nodes and macro transmission edges."""
        logger.info("Seeding canonical causal graph nodes and transmission edges...")
        graph_res = self.macro_sim.seed_canonical_causal_graph()
        return {
            "graph_nodes": graph_res.get("nodes", 0),
            "graph_edges": graph_res.get("edges", 0),
        }

    def run_screener_and_checkpoint(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """Runs composite multi-factor screener and audits Top 200 checkpoint integrity."""
        latest_date = target_date or self.repo.get_latest_price_delivery_date() or "2026-08-14"
        logger.info("Executing composite screening and Top 200 checkpoint audit for date: %s", latest_date)

        df_screened = self.screener.run_screener(target_date=latest_date, top_n=20)
        checkpoint_res = self.phase1.validate_top_200_checkpoint(target_date=latest_date)

        return {
            "target_date": latest_date,
            "screened_candidates_count": len(df_screened),
            "checkpoint": checkpoint_res,
        }

    def bootstrap(
        self,
        days: int = 25,
        top: int = TOP_UNIVERSE_LIMIT,
        force: bool = False,
        verify: bool = True,
        sample_only: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes end-to-end deterministic bootstrap:
        1. Initialize SQLite WAL schema
        2. Seed Master Companies (Nifty 200)
        3. Ingest Historical Bhavcopy (25 sessions) & Compute Rolling Technicals
        4. Ingest Corporate Fundamentals & Forensic Solvency Health
        5. Ingest Smart Money (PIT Insider Trades & Bulk Deals)
        6. Seed Dynamic Ontologies & Canonical Company Parameters
        7. Seed Canonical Causal Knowledge Graph & Macro Nodes
        8. Index Concall Transcripts in FTS5 & Vector Store
        9. Run Screener & Checkpoint Audit
        """
        start_time = time.time()
        logger.info("=" * 75)
        logger.info("STARTING DETERMINISTIC DATABASE BOOTSTRAP: %s", self.db_path)
        logger.info("=" * 75)

        # 1. Schema
        self.init_schema()

        # 2. Fixture data
        fixtures = self.load_fixtures()

        # 3. Master companies
        master_count = self.seed_master_companies(fixtures, sample_only=sample_only)

        # 4. Bhavcopy and Technical flows
        sample_syms = self.SAMPLE_SYMBOLS if sample_only else None
        bhav_rows = self.seed_bhavcopy_sessions(days_count=days, sample_symbols=sample_syms)

        # 5. Fundamentals & Solvency
        funda_stats = self.seed_fundamentals_and_solvency(fixtures, top_universe=top, sample_only=sample_only)

        # 6. Smart Money
        sm_stats = self.seed_smart_money(fixtures)

        # 7. Ontologies & Distillation
        dist_stats = self.seed_ontologies_and_distillation()

        # 8. Causal Graph
        graph_stats = self.seed_causal_graph()

        # 9. Verification & Checkpoint Audit
        checkpoint_summary = None
        if verify and not sample_only:
            audit_res = self.run_screener_and_checkpoint()
            checkpoint_summary = audit_res.get("checkpoint")

        elapsed_time = round(time.time() - start_time, 2)
        logger.info("=" * 75)
        logger.info("BOOTSTRAP COMPLETED SUCCESSFULLY IN %.2f SECONDS", elapsed_time)
        logger.info("=" * 75)

        return {
            "status": "SUCCESS",
            "execution_time_seconds": elapsed_time,
            "database_path": str(self.db_path),
            "master_companies_count": master_count,
            "bhavcopy_rows_count": bhav_rows,
            "fundamentals": funda_stats,
            "smart_money": sm_stats,
            "ontologies": dist_stats,
            "causal_graph": graph_stats,
            "checkpoint": checkpoint_summary,
        }


# Helper function
def bootstrap_database(
    db_path: Optional[Path | str] = None,
    days: int = 25,
    top: int = TOP_UNIVERSE_LIMIT,
    force: bool = False,
    verify: bool = True,
    sample_only: bool = False,
) -> Dict[str, Any]:
    """Helper function to run the bootstrap manager."""
    mgr = BootstrapManager(db_path=db_path)
    return mgr.bootstrap(days=days, top=top, force=force, verify=verify, sample_only=sample_only)


# Singleton bootstrap manager
bootstrap_manager = BootstrapManager()
