"""
Repository Module
Provides typed data access, bulk upserts, and specialized query methods for all database entities.
"""

import json
from datetime import date
from typing import List, Dict, Any, Optional
import pandas as pd

from reality_engine.db.database import db_manager


class Repository:
    """Handles CRUD operations and analytical queries across the database schema."""

    def __init__(self, manager=None):
        self.db = manager or db_manager
        # in-instance cache for _resolve_isin: (company_id, normalized_symbol) -> isin|None
        self._resolve_isin_cache: Dict[Any, Optional[str]] = {}

    # -------------------------------------------------------------
    # 1. Master Companies
    # -------------------------------------------------------------
    def upsert_master_companies(self, companies: List[Dict[str, Any]]) -> int:
        """Bulk upserts master company records."""
        if not companies:
            return 0

        # Keep the repository boundary tolerant of sparse fixture/test records.
        # SQLite named bindings require every placeholder to be present even when
        # the corresponding schema column is nullable.
        defaults = {
            "nse_symbol": None,
            "bse_code": None,
            "company_name": None,
            "industry": None,
            "sector": None,
            "market_cap_tier": None,
            "is_fno_eligible": 0,
            "is_nifty50": 0,
            "is_nifty100": 0,
            "is_nifty200": 0,
            "is_nifty500": 0,
            "is_active": 1,
        }
        companies = [{**defaults, **company} for company in companies]

        query = """
        INSERT INTO master_companies (
            isin, nse_symbol, bse_code, company_name, industry, sector,
            market_cap_tier, is_fno_eligible, is_nifty50, is_nifty100, 
            is_nifty200, is_nifty500, is_active, updated_at
        ) VALUES (
            :isin, :nse_symbol, :bse_code, :company_name, :industry, :sector,
            :market_cap_tier, :is_fno_eligible, :is_nifty50, :is_nifty100,
            :is_nifty200, :is_nifty500, :is_active, CURRENT_TIMESTAMP
        )
        ON CONFLICT(isin) DO UPDATE SET
            nse_symbol = COALESCE(excluded.nse_symbol, master_companies.nse_symbol),
            bse_code = COALESCE(excluded.bse_code, master_companies.bse_code),
            company_name = excluded.company_name,
            industry = COALESCE(excluded.industry, master_companies.industry),
            sector = COALESCE(excluded.sector, master_companies.sector),
            market_cap_tier = COALESCE(excluded.market_cap_tier, master_companies.market_cap_tier),
            is_fno_eligible = COALESCE(excluded.is_fno_eligible, master_companies.is_fno_eligible),
            is_nifty50 = COALESCE(excluded.is_nifty50, master_companies.is_nifty50),
            is_nifty100 = COALESCE(excluded.is_nifty100, master_companies.is_nifty100),
            is_nifty200 = COALESCE(excluded.is_nifty200, master_companies.is_nifty200),
            is_nifty500 = COALESCE(excluded.is_nifty500, master_companies.is_nifty500),
            is_active = excluded.is_active,
            updated_at = CURRENT_TIMESTAMP;
        """
        with self.db.session() as conn:
            cursor = conn.executemany(query, companies)
            return cursor.rowcount

    def get_all_companies(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Retrieves list of all master companies."""
        query = "SELECT * FROM master_companies"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY nse_symbol ASC"

        with self.db.session() as conn:
            rows = conn.execute(query).fetchall()
            return [dict(r) for r in rows]

    def get_nifty200_companies(self) -> List[Dict[str, Any]]:
        """Retrieves Top 200 (Nifty 200) companies."""
        query = """
        SELECT * FROM master_companies 
        WHERE is_nifty200 = 1 AND is_active = 1
        ORDER BY nse_symbol ASC
        """
        with self.db.session() as conn:
            rows = conn.execute(query).fetchall()
            return [dict(r) for r in rows]

    def get_company_by_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch company by NSE symbol or BSE code."""
        query = """
        SELECT * FROM master_companies 
        WHERE nse_symbol = ? OR bse_code = ? OR isin = ?
        """
        with self.db.session() as conn:
            row = conn.execute(query, (symbol, symbol, symbol)).fetchone()
            return dict(row) if row else None

    # -------------------------------------------------------------
    # 2. Daily Price & Delivery Ingestion
    # -------------------------------------------------------------
    def upsert_daily_price_delivery(self, records: List[Dict[str, Any]]) -> int:
        """Bulk upserts daily OHLCV and delivery metrics."""
        if not records:
            return 0

        query = """
        INSERT INTO daily_price_delivery (
            date, symbol, isin, series, open, high, low, close, prev_close,
            change_pct, total_volume, turnover_lacs, num_trades,
            deliverable_volume, delivery_pct, delivery_spike_ratio,
            delivery_conviction_score, sma_20, sma_50, sma_200, rsi_14,
            high_52w, low_52w, distance_from_52w_high_pct
        ) VALUES (
            :date, :symbol, :isin, :series, :open, :high, :low, :close, :prev_close,
            :change_pct, :total_volume, :turnover_lacs, :num_trades,
            :deliverable_volume, :delivery_pct, :delivery_spike_ratio,
            :delivery_conviction_score, :sma_20, :sma_50, :sma_200, :rsi_14,
            :high_52w, :low_52w, :distance_from_52w_high_pct
        )
        ON CONFLICT(date, symbol) DO UPDATE SET
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            prev_close = excluded.prev_close,
            change_pct = excluded.change_pct,
            total_volume = excluded.total_volume,
            turnover_lacs = excluded.turnover_lacs,
            num_trades = excluded.num_trades,
            deliverable_volume = excluded.deliverable_volume,
            delivery_pct = excluded.delivery_pct,
            delivery_spike_ratio = COALESCE(excluded.delivery_spike_ratio, daily_price_delivery.delivery_spike_ratio),
            delivery_conviction_score = COALESCE(excluded.delivery_conviction_score, daily_price_delivery.delivery_conviction_score),
            sma_20 = COALESCE(excluded.sma_20, daily_price_delivery.sma_20),
            sma_50 = COALESCE(excluded.sma_50, daily_price_delivery.sma_50),
            sma_200 = COALESCE(excluded.sma_200, daily_price_delivery.sma_200),
            rsi_14 = COALESCE(excluded.rsi_14, daily_price_delivery.rsi_14),
            high_52w = COALESCE(excluded.high_52w, daily_price_delivery.high_52w),
            low_52w = COALESCE(excluded.low_52w, daily_price_delivery.low_52w),
            distance_from_52w_high_pct = COALESCE(excluded.distance_from_52w_high_pct, daily_price_delivery.distance_from_52w_high_pct);
        """
        values = [{
            "date": r.get("date"),
            "symbol": r.get("symbol"),
            "isin": r.get("isin"),
            "series": r.get("series", "EQ"),
            "open": float(r.get("open", 0.0) or 0.0),
            "high": float(r.get("high", 0.0) or 0.0),
            "low": float(r.get("low", 0.0) or 0.0),
            "close": float(r.get("close", 0.0) or 0.0),
            "prev_close": float(r.get("prev_close", 0.0) or 0.0),
            "change_pct": float(r.get("change_pct", 0.0) or 0.0),
            "total_volume": int(r.get("total_volume", 0) or 0),
            "turnover_lacs": r.get("turnover_lacs"),
            "num_trades": r.get("num_trades"),
            "deliverable_volume": int(r.get("deliverable_volume", 0) or 0),
            "delivery_pct": float(r.get("delivery_pct", 0.0) or 0.0),
            "delivery_spike_ratio": r.get("delivery_spike_ratio"),
            "delivery_conviction_score": r.get("delivery_conviction_score"),
            "sma_20": r.get("sma_20"),
            "sma_50": r.get("sma_50"),
            "sma_200": r.get("sma_200"),
            "rsi_14": r.get("rsi_14"),
            "high_52w": r.get("high_52w"),
            "low_52w": r.get("low_52w"),
            "distance_from_52w_high_pct": r.get("distance_from_52w_high_pct"),
        } for r in (records if isinstance(records, list) else [records])]
        with self.db.session() as conn:
            cursor = conn.executemany(query, values)
            return cursor.rowcount

    def get_latest_price_delivery_date(self) -> Optional[str]:
        """Returns the most recent date for which price delivery data exists."""
        query = "SELECT MAX(date) as max_date FROM daily_price_delivery"
        with self.db.session() as conn:
            row = conn.execute(query).fetchone()
            return row["max_date"] if row and row["max_date"] else None

    def get_price_history(self, symbol: str, limit: int = 250) -> pd.DataFrame:
        """Fetches historical price and delivery records for a symbol."""
        query = """
        SELECT * FROM daily_price_delivery
        WHERE symbol = ?
        ORDER BY date ASC
        """
        with self.db.session() as conn:
            df = pd.read_sql_query(query, conn, params=[symbol])
            return df.tail(limit)

    def get_all_price_delivery_for_date(self, target_date: str) -> pd.DataFrame:
        """Fetches all price & delivery records for a specific date."""
        query = """
        SELECT p.*, m.company_name, m.industry, m.sector, m.market_cap_tier, m.is_nifty200
        FROM daily_price_delivery p
        JOIN master_companies m ON p.isin = m.isin
        WHERE p.date = ?
        """
        with self.db.session() as conn:
            return pd.read_sql_query(query, conn, params=[target_date])

    # -------------------------------------------------------------
    # 3. Quarterly & Annual Financials
    # -------------------------------------------------------------
    def upsert_quarterly_financials(self, records: List[Dict[str, Any]]) -> int:
        """Bulk upserts quarterly financial results."""
        if not records:
            return 0

        query = """
        INSERT INTO quarterly_financials (
            isin, symbol, quarter_end_date, financial_year, revenue_inr_cr,
            ebitda_inr_cr, ebitda_margin_pct, net_profit_inr_cr, pat_margin_pct,
            eps_inr, yoy_revenue_growth_pct, yoy_pat_growth_pct,
            qoq_revenue_growth_pct, qoq_pat_growth_pct, xbrl_file_path,
            concall_pdf_path, investor_presentation_path, has_concall_transcript, source
        ) VALUES (
            :isin, :symbol, :quarter_end_date, :financial_year, :revenue_inr_cr,
            :ebitda_inr_cr, :ebitda_margin_pct, :net_profit_inr_cr, :pat_margin_pct,
            :eps_inr, :yoy_revenue_growth_pct, :yoy_pat_growth_pct,
            :qoq_revenue_growth_pct, :qoq_pat_growth_pct, :xbrl_file_path,
            :concall_pdf_path, :investor_presentation_path, :has_concall_transcript, :source
        )
        ON CONFLICT(isin, quarter_end_date) DO UPDATE SET
            symbol = excluded.symbol,
            financial_year = excluded.financial_year,
            revenue_inr_cr = excluded.revenue_inr_cr,
            ebitda_inr_cr = excluded.ebitda_inr_cr,
            ebitda_margin_pct = excluded.ebitda_margin_pct,
            net_profit_inr_cr = excluded.net_profit_inr_cr,
            pat_margin_pct = excluded.pat_margin_pct,
            eps_inr = excluded.eps_inr,
            yoy_revenue_growth_pct = excluded.yoy_revenue_growth_pct,
            yoy_pat_growth_pct = excluded.yoy_pat_growth_pct,
            qoq_revenue_growth_pct = excluded.qoq_revenue_growth_pct,
            qoq_pat_growth_pct = excluded.qoq_pat_growth_pct,
            xbrl_file_path = COALESCE(excluded.xbrl_file_path, quarterly_financials.xbrl_file_path),
            concall_pdf_path = COALESCE(excluded.concall_pdf_path, quarterly_financials.concall_pdf_path),
            investor_presentation_path = COALESCE(excluded.investor_presentation_path, quarterly_financials.investor_presentation_path),
            has_concall_transcript = COALESCE(excluded.has_concall_transcript, quarterly_financials.has_concall_transcript),
            source = excluded.source;
        """
        # Guarantee the provenance `source` binding (default 'yfinance' per the
        # quarterly_financials.source migration) so raw fixture dicts without it
        # do not raise a missing-named-parameter error.
        records = [{**r, "source": r.get("source", "yfinance")} for r in records]
        with self.db.session() as conn:
            cursor = conn.executemany(query, records)
            return cursor.rowcount

    def upsert_annual_financials(self, records: List[Dict[str, Any]]) -> int:
        """Bulk upserts annual financial statements and balance sheet metrics."""
        if not records:
            return 0

        query = """
        INSERT INTO annual_financials (
            isin, symbol, fiscal_year, revenue_inr_cr, ebitda_inr_cr,
            net_profit_inr_cr, eps_inr, opm_pct, npm_pct, roce_pct,
            roe_pct, debt_inr_cr, equity_inr_cr, debt_to_equity,
            interest_coverage, operating_cash_flow_inr_cr, free_cash_flow_inr_cr, source
        ) VALUES (
            :isin, :symbol, :fiscal_year, :revenue_inr_cr, :ebitda_inr_cr,
            :net_profit_inr_cr, :eps_inr, :opm_pct, :npm_pct, :roce_pct,
            :roe_pct, :debt_inr_cr, :equity_inr_cr, :debt_to_equity,
            :interest_coverage, :operating_cash_flow_inr_cr, :free_cash_flow_inr_cr, :source
        )
        ON CONFLICT(isin, fiscal_year) DO UPDATE SET
            symbol = excluded.symbol,
            revenue_inr_cr = excluded.revenue_inr_cr,
            ebitda_inr_cr = excluded.ebitda_inr_cr,
            net_profit_inr_cr = excluded.net_profit_inr_cr,
            eps_inr = excluded.eps_inr,
            opm_pct = excluded.opm_pct,
            npm_pct = excluded.npm_pct,
            roce_pct = excluded.roce_pct,
            roe_pct = excluded.roe_pct,
            debt_inr_cr = excluded.debt_inr_cr,
            equity_inr_cr = excluded.equity_inr_cr,
            debt_to_equity = excluded.debt_to_equity,
            interest_coverage = excluded.interest_coverage,
            operating_cash_flow_inr_cr = excluded.operating_cash_flow_inr_cr,
            free_cash_flow_inr_cr = excluded.free_cash_flow_inr_cr,
            source = excluded.source;
        """
        # Guarantee the provenance `source` binding (default 'yfinance' per the
        # annual_financials.source migration) so raw fixture dicts without it
        # do not raise a missing-named-parameter error.
        records = [{**r, "source": r.get("source", "yfinance")} for r in records]
        with self.db.session() as conn:
            cursor = conn.executemany(query, records)
            return cursor.rowcount

    def get_latest_quarterly_financials(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """Fetches the latest quarterly result for each company (or a specific symbol)."""
        query = """
        WITH RankedQuarters AS (
            SELECT *,
                ROW_NUMBER() OVER(PARTITION BY isin ORDER BY quarter_end_date DESC) as rn
            FROM quarterly_financials
        )
            SELECT latest.*, prior.ebitda_margin_pct AS prior_ebitda_margin_pct
            FROM RankedQuarters latest
            LEFT JOIN RankedQuarters prior
              ON prior.isin = latest.isin AND prior.rn = 2
            WHERE latest.rn = 1
        """
        params: List[Any] = []
        if symbol:
            query += " AND (latest.symbol = ?)"
            params.append(symbol)

        with self.db.session() as conn:
            return pd.read_sql_query(query, conn, params=params if params else None)

    # -------------------------------------------------------------
    # 4. Forensic Health & Solvency Gate
    # -------------------------------------------------------------
    def upsert_forensic_health(self, records: List[Dict[str, Any]]) -> int:
        """Bulk upserts forensic solvency and governance metrics."""
        if not records:
            return 0

        query = """
        INSERT INTO company_forensic_health (
            isin, symbol, fiscal_year, promoter_holding_pct, promoter_pledge_pct,
            fii_holding_pct, dii_holding_pct, public_holding_pct,
            interest_coverage_ratio, debt_to_equity_ratio, market_cap_inr_cr,
            pe_ratio, pb_ratio, dividend_yield_pct, altman_z_score,
            auditor_name, has_qualified_audit_opinion, related_party_tx_pct_revenue,
            is_solvency_approved, solvency_disqualification_reasons, last_evaluated_date
        ) VALUES (
            :isin, :symbol, :fiscal_year, :promoter_holding_pct, :promoter_pledge_pct,
            :fii_holding_pct, :dii_holding_pct, :public_holding_pct,
            :interest_coverage_ratio, :debt_to_equity_ratio, :market_cap_inr_cr,
            :pe_ratio, :pb_ratio, :dividend_yield_pct, :altman_z_score,
            :auditor_name, :has_qualified_audit_opinion, :related_party_tx_pct_revenue,
            :is_solvency_approved, :solvency_disqualification_reasons, :last_evaluated_date
        )
        ON CONFLICT(isin) DO UPDATE SET
            symbol = excluded.symbol,
            fiscal_year = excluded.fiscal_year,
            promoter_holding_pct = excluded.promoter_holding_pct,
            promoter_pledge_pct = excluded.promoter_pledge_pct,
            fii_holding_pct = excluded.fii_holding_pct,
            dii_holding_pct = excluded.dii_holding_pct,
            public_holding_pct = excluded.public_holding_pct,
            interest_coverage_ratio = excluded.interest_coverage_ratio,
            debt_to_equity_ratio = excluded.debt_to_equity_ratio,
            market_cap_inr_cr = excluded.market_cap_inr_cr,
            pe_ratio = excluded.pe_ratio,
            pb_ratio = excluded.pb_ratio,
            dividend_yield_pct = excluded.dividend_yield_pct,
            altman_z_score = excluded.altman_z_score,
            auditor_name = excluded.auditor_name,
            has_qualified_audit_opinion = excluded.has_qualified_audit_opinion,
            related_party_tx_pct_revenue = excluded.related_party_tx_pct_revenue,
            is_solvency_approved = excluded.is_solvency_approved,
            solvency_disqualification_reasons = excluded.solvency_disqualification_reasons,
            last_evaluated_date = excluded.last_evaluated_date;
        """
        with self.db.session() as conn:
            cursor = conn.executemany(query, records)
            return cursor.rowcount

    def get_forensic_health(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """Fetches forensic health status."""
        query = "SELECT * FROM company_forensic_health"
        if symbol:
            query += f" WHERE symbol = '{symbol}'"
        with self.db.session() as conn:
            return pd.read_sql_query(query, conn)

    # -------------------------------------------------------------
    # 5. Insider Trading & Bulk/Block Deals & Index Breadth
    # -------------------------------------------------------------
    def upsert_insider_trades(self, records: List[Dict[str, Any]]) -> int:
        """Bulk upserts SEBI PIT insider trading disclosures."""
        if not records:
            return 0

        query = """
        INSERT INTO insider_trades (
            id, symbol, isin, acquirer_name, category_of_person,
            transaction_type, num_shares, value_inr_lacs,
            mode_of_acquisition, acquisition_date, intimation_date
        ) VALUES (
            :id, :symbol, :isin, :acquirer_name, :category_of_person,
            :transaction_type, :num_shares, :value_inr_lacs,
            :mode_of_acquisition, :acquisition_date, :intimation_date
        )
        ON CONFLICT(id) DO NOTHING;
        """
        with self.db.session() as conn:
            cursor = conn.executemany(query, records)
            return cursor.rowcount

    def upsert_bulk_block_deals(self, records: List[Dict[str, Any]]) -> int:
        """Bulk upserts Bulk and Block deals."""
        if not records:
            return 0

        query = """
        INSERT INTO bulk_block_deals (
            id, deal_date, symbol, client_name, deal_type, buy_sell,
            quantity, trade_price, is_marquee_institution
        ) VALUES (
            :id, :deal_date, :symbol, :client_name, :deal_type, :buy_sell,
            :quantity, :trade_price, :is_marquee_institution
        )
        ON CONFLICT(id) DO NOTHING;
        """
        with self.db.session() as conn:
            cursor = conn.executemany(query, records)
            return cursor.rowcount

    def upsert_index_breadth(self, records: List[Dict[str, Any]]) -> int:
        """Bulk upserts NSE Sector and Index breadth."""
        if not records:
            return 0

        query = """
        INSERT INTO nse_index_breadth (
            date, index_name, open, high, low, close, change_pct,
            points_change, volume, turnover_cr, advances_count,
            declines_count, advance_decline_ratio, pe_ratio, pb_ratio, dividend_yield
        ) VALUES (
            :date, :index_name, :open, :high, :low, :close, :change_pct,
            :points_change, :volume, :turnover_cr, :advances_count,
            :declines_count, :advance_decline_ratio, :pe_ratio, :pb_ratio, :dividend_yield
        )
        ON CONFLICT(date, index_name) DO UPDATE SET
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            change_pct = excluded.change_pct,
            points_change = excluded.points_change,
            volume = excluded.volume,
            turnover_cr = excluded.turnover_cr,
            advances_count = excluded.advances_count,
            declines_count = excluded.declines_count,
            advance_decline_ratio = excluded.advance_decline_ratio,
            pe_ratio = excluded.pe_ratio,
            pb_ratio = excluded.pb_ratio,
            dividend_yield = excluded.dividend_yield;
        """
        with self.db.session() as conn:
            cursor = conn.executemany(query, records)
            return cursor.rowcount

    # -------------------------------------------------------------
    # 6. EOD Factor Calls & Screening Persistence
    # -------------------------------------------------------------
    def upsert_eod_scrip_calls(self, records: List[Dict[str, Any]]) -> int:
        """Bulk upserts screened candidate ranks and factors."""
        if not records:
            return 0

        query = """
        INSERT INTO eod_scrip_calls (
            date, symbol, isin, composite_rank, technical_score,
            fundamental_score, alt_sentiment_score, composite_score,
            current_market_price, recommended_entry_range, target_price,
            stop_loss, risk_reward_ratio, conviction_level, is_solvency_approved,
            delivery_spike_ratio, delivery_conviction_score,
            yoy_revenue_growth_pct, yoy_pat_growth_pct
        ) VALUES (
            :date, :symbol, :isin, :composite_rank, :technical_score,
            :fundamental_score, :alt_sentiment_score, :composite_score,
            :current_market_price, :recommended_entry_range, :target_price,
            :stop_loss, :risk_reward_ratio, :conviction_level, :is_solvency_approved,
            :delivery_spike_ratio, :delivery_conviction_score,
            :yoy_revenue_growth_pct, :yoy_pat_growth_pct
        )
        ON CONFLICT(date, symbol) DO UPDATE SET
            composite_rank = excluded.composite_rank,
            technical_score = excluded.technical_score,
            fundamental_score = excluded.fundamental_score,
            alt_sentiment_score = excluded.alt_sentiment_score,
            composite_score = excluded.composite_score,
            current_market_price = excluded.current_market_price,
            recommended_entry_range = excluded.recommended_entry_range,
            target_price = excluded.target_price,
            stop_loss = excluded.stop_loss,
            risk_reward_ratio = excluded.risk_reward_ratio,
            conviction_level = excluded.conviction_level,
            is_solvency_approved = excluded.is_solvency_approved,
            delivery_spike_ratio = excluded.delivery_spike_ratio,
            delivery_conviction_score = excluded.delivery_conviction_score,
            yoy_revenue_growth_pct = excluded.yoy_revenue_growth_pct,
            yoy_pat_growth_pct = excluded.yoy_pat_growth_pct;
        """
        with self.db.session() as conn:
            cursor = conn.executemany(query, records)
            return cursor.rowcount

    def get_eod_scrip_calls(self, target_date: str) -> pd.DataFrame:
        """Fetches screened scrip rankings for a specific date."""
        query = """
        SELECT e.*, m.company_name, m.industry, m.sector, m.market_cap_tier
        FROM eod_scrip_calls e
        JOIN master_companies m ON e.isin = m.isin
        WHERE e.date = ?
        ORDER BY e.composite_rank ASC
        """
        with self.db.session() as conn:
            return pd.read_sql_query(query, conn, params=[target_date])

    # -------------------------------------------------------------
    # 7. Corporate Documents Registry
    # -------------------------------------------------------------
    def upsert_corporate_documents(self, records: List[Dict[str, Any]]) -> int:
        """Bulk registers corporate documents (concalls, presentations, annual reports)."""
        if not records:
            return 0

        # Tolerant of sparse records (e.g. bootstrap fixtures): missing bind keys
        # default to NULL so the query never fails on absent provenance columns.
        defaults = {
            "isin": None, "symbol": None, "doc_type": None, "title": None,
            "doc_date": None, "source_url": None, "source": None,
            "discovery_source": None, "local_file_path": None,
            "file_size_bytes": 0, "sha256_hash": None, "is_processed": 0,
        }
        records = [{**defaults, **record} for record in records]

        query = """
        INSERT INTO corporate_documents (
            isin, symbol, doc_type, title, doc_date, source_url, source,
            discovery_source, local_file_path, file_size_bytes, sha256_hash, is_processed
        ) VALUES (
            :isin, :symbol, :doc_type, :title, :doc_date, :source_url, :source,
            :discovery_source, :local_file_path, :file_size_bytes, :sha256_hash, :is_processed
        )
        ON CONFLICT(source_url) DO UPDATE SET
            isin = COALESCE(excluded.isin, corporate_documents.isin),
            symbol = COALESCE(excluded.symbol, corporate_documents.symbol),
            doc_type = COALESCE(excluded.doc_type, corporate_documents.doc_type),
            title = COALESCE(excluded.title, corporate_documents.title),
            doc_date = COALESCE(excluded.doc_date, corporate_documents.doc_date),
            source = COALESCE(excluded.source, corporate_documents.source),
            discovery_source = COALESCE(excluded.discovery_source, corporate_documents.discovery_source),
            local_file_path = COALESCE(excluded.local_file_path, corporate_documents.local_file_path),
            file_size_bytes = COALESCE(excluded.file_size_bytes, corporate_documents.file_size_bytes),
            sha256_hash = COALESCE(excluded.sha256_hash, corporate_documents.sha256_hash),
            is_processed = COALESCE(excluded.is_processed, corporate_documents.is_processed);
        """
        with self.db.session() as conn:
            cursor = conn.executemany(query, records)
            return cursor.rowcount

    # -------------------------------------------------------------
    # 7b. Corporate Actions (official NSE feed)
    # -------------------------------------------------------------
    def upsert_corporate_actions(self, records: List[Dict[str, Any]]) -> int:
        """Bulk registers corporate actions (bonus/split/rights/buyback/merger/demerger/dividend)."""
        if not records:
            return 0
        defaults = {
            "isin": None, "symbol": None, "company_name": None, "subject": None,
            "action_type": "OTHER", "ex_date": None, "rec_date": None,
            "bc_start_date": None, "bc_end_date": None, "nd_start_date": None,
            "nd_end_date": None, "broadcast_date": None, "face_value": None,
            "series": None, "industry": None, "source": "nse_official",
        }
        records = [{**defaults, **record} for record in records]
        query = """
        INSERT INTO corporate_actions (
            isin, symbol, company_name, subject, action_type, ex_date, rec_date,
            bc_start_date, bc_end_date, nd_start_date, nd_end_date, broadcast_date,
            face_value, series, industry, source
        ) VALUES (
            :isin, :symbol, :company_name, :subject, :action_type, :ex_date, :rec_date,
            :bc_start_date, :bc_end_date, :nd_start_date, :nd_end_date, :broadcast_date,
            :face_value, :series, :industry, :source
        )
        ON CONFLICT(isin, subject, ex_date, action_type) DO UPDATE SET
            company_name = COALESCE(excluded.company_name, corporate_actions.company_name),
            rec_date = COALESCE(excluded.rec_date, corporate_actions.rec_date),
            bc_start_date = COALESCE(excluded.bc_start_date, corporate_actions.bc_start_date),
            bc_end_date = COALESCE(excluded.bc_end_date, corporate_actions.bc_end_date),
            nd_start_date = COALESCE(excluded.nd_start_date, corporate_actions.nd_start_date),
            nd_end_date = COALESCE(excluded.nd_end_date, corporate_actions.nd_end_date),
            face_value = COALESCE(excluded.face_value, corporate_actions.face_value),
            series = COALESCE(excluded.series, corporate_actions.series),
            industry = COALESCE(excluded.industry, corporate_actions.industry),
            fetched_at = CURRENT_TIMESTAMP;
        """
        with self.db.session() as conn:
            cursor = conn.executemany(query, records)
            return cursor.rowcount

    # -------------------------------------------------------------
    # 7c. Corporate Status Flags (delisting / NCLT / suspension)
    # -------------------------------------------------------------
    def upsert_corporate_status_flags(self, records: List[Dict[str, Any]]) -> int:
        """Bulk upserts corporate status flags (delisted / NCLT_CIRP / suspended)."""
        if not records:
            return 0

        # Tolerant of sparse records (e.g. derived flags missing isin). Missing
        # bind keys default so the named INSERT never fails on absent columns.
        defaults = {
            "isin": None, "symbol": None, "status_type": "OTHER",
            "source": "derived", "detail": None,
        }
        records = [{**defaults, **record} for record in records]

        query = """
        INSERT INTO corporate_status_flags (isin, symbol, status_type, source, detail)
        VALUES (:isin, :symbol, :status_type, :source, :detail)
        ON CONFLICT(symbol, status_type, source) DO UPDATE SET
            detail = excluded.detail,
            detected_at = CURRENT_TIMESTAMP;
        """
        with self.db.session() as conn:
            cursor = conn.executemany(query, records)
            return cursor.rowcount

    def get_corporate_status_flags(
        self,
        status_type: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves corporate status flags, optionally filtered by status_type/symbol."""
        query = "SELECT * FROM corporate_status_flags WHERE 1=1"
        params: List[Any] = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if status_type:
            query += " AND status_type = ?"
            params.append(status_type)
        query += " ORDER BY detected_at DESC, symbol ASC"
        with self.db.session() as conn:
            return [dict(row) for row in conn.execute(query, params)]

    # -------------------------------------------------------------
    # 8. Knowledge Graph, Dynamic Parameters, and Macro Events
    # -------------------------------------------------------------
    @staticmethod
    def _json_value(value: Any) -> Optional[str]:
        """Serialize structured values while preserving already encoded JSON."""
        if value is None or isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def upsert_graph_nodes(self, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        query = """
        INSERT INTO graph_nodes (node_id, node_type, name, metadata_json)
        VALUES (:node_id, :node_type, :name, :metadata_json)
        ON CONFLICT(node_id) DO UPDATE SET
            node_type = excluded.node_type,
            name = excluded.name,
            metadata_json = excluded.metadata_json
        """
        values = [{**record, "metadata_json": self._json_value(record.get("metadata_json", {}))}
                  for record in records]
        with self.db.session() as conn:
            return conn.executemany(query, values).rowcount

    def upsert_causal_edges(self, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        query = """
        INSERT INTO graph_causal_edges (
            edge_id, source_node_id, target_node_id, relationship_type,
            impact_direction, elasticity_score, transmission_mechanism,
            evidence_document_ref, confidence_score
        ) VALUES (
            :edge_id, :source_node_id, :target_node_id, :relationship_type,
            :impact_direction, :elasticity_score, :transmission_mechanism,
            :evidence_document_ref, COALESCE(:confidence_score, 1.0)
        )
        ON CONFLICT(edge_id) DO UPDATE SET
            source_node_id = excluded.source_node_id,
            target_node_id = excluded.target_node_id,
            relationship_type = excluded.relationship_type,
            impact_direction = excluded.impact_direction,
            elasticity_score = excluded.elasticity_score,
            transmission_mechanism = excluded.transmission_mechanism,
            evidence_document_ref = excluded.evidence_document_ref,
            confidence_score = excluded.confidence_score
        """
        values = [{
            "edge_id": record.get("edge_id"),
            "source_node_id": record.get("source_node_id"),
            "target_node_id": record.get("target_node_id"),
            "relationship_type": record.get("relationship_type"),
            "impact_direction": record.get("impact_direction"),
            "elasticity_score": record.get("elasticity_score"),
            "transmission_mechanism": record.get("transmission_mechanism"),
            "evidence_document_ref": record.get("evidence_document_ref"),
            "confidence_score": record.get("confidence_score"),
        } for record in records]
        with self.db.session() as conn:
            return conn.executemany(query, values).rowcount

    def upsert_macro_event(self, record: Dict[str, Any]) -> int:
        """Insert/update a macro_events row, tolerant of SQLite vs PostgreSQL schemas.

        SQLite (schema.sql): ``event_id`` TEXT PK, plus ``event_name``, ``category``,
        ``event_date``, ``raw_document_path``, ``summary``, ``affected_nodes_json``
        and a ``doc_id`` column (added idempotently by :meth:`ensure_macro_event_doc_id`).
        PostgreSQL (postgres_schema.sql): ``event_id`` SERIAL, ``doc_id``,
        ``event_name``, ``event_category``, ``announcement_date`` (no summary /
        affected_nodes_json columns — they are skipped on PG).
        """
        event_id = record.get("event_id")
        event_name = record.get("event_name")
        category = record.get("category") or record.get("event_category")
        event_date = record.get("event_date") or record.get("announcement_date")
        summary = record.get("summary") or ""
        affected = self._json_value(record.get("affected_nodes_json"))
        doc_id = record.get("doc_id")
        raw_document_path = record.get("raw_document_path")

        with self.db.session() as conn:
            cols = self._macro_event_columns(conn)
            if cols is None:
                # ----- PostgreSQL branch (no PRAGMA support) -----
                existing = None
                if doc_id is not None and event_name:
                    try:
                        row = conn.execute(
                            "SELECT event_id FROM macro_events WHERE doc_id=:d AND event_name=:n",
                            {"d": doc_id, "n": event_name},
                        ).fetchone()
                        existing = row["event_id"] if row else None
                    except Exception:
                        existing = None
                if existing is not None:
                    conn.execute(
                        "UPDATE macro_events SET event_category=:c, announcement_date=:dt WHERE event_id=:e",
                        {"c": category, "dt": event_date, "e": existing},
                    )
                else:
                    conn.execute(
                        "INSERT INTO macro_events (doc_id, event_name, event_category, announcement_date) "
                        "VALUES (:d, :n, :c, :dt)",
                        {"d": doc_id, "n": event_name, "c": category, "dt": event_date},
                    )
                return 1

            # ----- SQLite branch (schema-tolerant to present columns) -----
            if "doc_id" not in cols:
                try:
                    conn.execute("ALTER TABLE macro_events ADD COLUMN doc_id INTEGER")
                    cols = self._macro_event_columns(conn) or cols
                except Exception:
                    pass
            field_map = {
                "event_id": event_id,
                "event_name": event_name,
                "category": category,
                "event_date": event_date,
                "raw_document_path": raw_document_path,
                "summary": summary,
                "affected_nodes_json": affected,
                "doc_id": doc_id,
            }
            present = {k: v for k, v in field_map.items() if k in cols}
            # event_id is the SQLite PK (TEXT); derive if the caller omitted it.
            if "event_id" in cols and not present.get("event_id"):
                present["event_id"] = (
                    f"MEV_{doc_id}" if doc_id is not None else f"MEV_{abs(hash(event_name))}"
                )
            keys = list(present.keys())
            col_sql = ", ".join(keys)
            ph_sql = ", ".join(f":{k}" for k in keys)
            upd_sql = ", ".join(f"{k}=excluded.{k}" for k in keys if k != "event_id")
            if upd_sql:
                conflict_sql = f"ON CONFLICT(event_id) DO UPDATE SET {upd_sql}"
            else:
                conflict_sql = ""
            conn.execute(
                f"INSERT INTO macro_events ({col_sql}) VALUES ({ph_sql}) {conflict_sql}",
                present,
            )
            return 1

    # ------------------------------------------------------------------
    # Macro substrate schema helpers + ripple_effects persistence
    # ------------------------------------------------------------------
    def _macro_event_columns(self, conn) -> Optional[set]:
        """Return macro_events column names, or ``None`` for non-SQLite (PG) backends."""
        try:
            return {r[1] for r in conn.execute("PRAGMA table_info('macro_events')").fetchall()}
        except Exception:
            return None

    def ensure_macro_event_doc_id(self, manager=None) -> None:
        """Ensure the SQLite ``macro_events.doc_id`` column exists (idempotent migration).

        PostgreSQL already defines ``doc_id`` in ``postgres_schema.sql``; the SQLite
        fallback (schema.sql) lacks it, so we add it so a single doc can be linked
        from both ``macro_events`` and ``raw_documents`` for acceptance queries such
        as ``SELECT count(*) FROM macro_events WHERE doc_id = ?``.
        """
        mgr = manager or self.db
        try:
            with mgr.session() as conn:
                cols = self._macro_event_columns(conn)
                if cols is None:
                    return  # PG path: column already present
                if "doc_id" not in cols:
                    try:
                        conn.execute("ALTER TABLE macro_events ADD COLUMN doc_id INTEGER")
                    except Exception:
                        pass
        except Exception:
            pass

    def get_raw_document_by_id(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """Return a raw_documents row by its integer doc_id, or None if absent."""
        with self.db.session() as conn:
            row = conn.execute("SELECT * FROM raw_documents WHERE doc_id = ?", (doc_id,)).fetchone()
            return dict(row) if row else None

    def get_document_chunks_for_doc(self, doc_id: int, limit: int = 20) -> List[str]:
        """Return document_chunks.content texts for a doc (used as LLM context).

        Returns an empty list when the table or rows are missing so the caller can
        fall back to using only the raw_documents metadata for extraction.
        """
        with self.db.session() as conn:
            try:
                rows = conn.execute(
                    "SELECT content FROM document_chunks WHERE doc_id = ? "
                    "ORDER BY chunk_index ASC LIMIT ?",
                    (doc_id, int(limit)),
                ).fetchall()
            except Exception:
                return []
            return [r["content"] for r in rows if r["content"]]

    def list_macro_raw_documents(self, source_type_prefix: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return raw_documents that are macro-policy sources.

        Matches Union/State budgets, Economic Survey, PIB circulars and RBI reports
        by source_type prefix (case-insensitive LIKE). Pass ``source_type_prefix`` to
        narrow the set (e.g. ``Union_Budget``).
        """
        macro_prefixes = ("union_budget", "state_budget", "economic_survey", "pib", "rbi")
        with self.db.session() as conn:
            if source_type_prefix:
                rows = conn.execute(
                    "SELECT * FROM raw_documents WHERE LOWER(source_type) LIKE ? "
                    "ORDER BY published_date DESC",
                    (f"{source_type_prefix.lower()}%",),
                ).fetchall()
                return [dict(r) for r in rows]
            like_clauses = " OR ".join("LOWER(source_type) LIKE ?" for _ in macro_prefixes)
            rows = conn.execute(
                f"SELECT * FROM raw_documents WHERE {like_clauses} ORDER BY published_date DESC",
                [f"{p}%" for p in macro_prefixes],
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_ripple_effects(self, event_id: Any, ripples: List[Dict[str, Any]]) -> int:
        """Replace all ripple_effects for ``event_id`` with the supplied ordered list.

        Idempotent: existing rows for the event are deleted first, then re-inserted
        in *insertion order* (parents before children). Each ripple dict may carry a
        private ``_ref`` and ``_parent_ref`` (referencing a parent's ``_ref``) so the
        self-referential ``parent_ripple_id`` is resolved to the freshly assigned
        autoincrement id. Column usage is schema-tolerant (SQLite vs PostgreSQL).
        """
        if not ripples:
            with self.db.session() as conn:
                try:
                    conn.execute("DELETE FROM ripple_effects WHERE event_id = ?", (event_id,))
                except Exception:
                    pass
            return 0

        with self.db.session() as conn:
            try:
                cols = {c[1] for c in conn.execute("PRAGMA table_info('ripple_effects')").fetchall()}
            except Exception:
                cols = None  # PG path
            conn.execute("DELETE FROM ripple_effects WHERE event_id = ?", (event_id,))
            ref_map: Dict[Any, int] = {}
            inserted = 0
            for r in ripples:
                parent_ripple_id = ref_map.get(r["_parent_ref"]) if r.get("_parent_ref") is not None else None
                base = {
                    "event_id": event_id,
                    "parent_ripple_id": parent_ripple_id,
                    "order_level": r.get("order_level"),
                    "target_type": r.get("target_type"),
                    "target_sector_id": r.get("target_sector_id"),
                    "target_industry_id": r.get("target_industry_id"),
                    "target_company_id": r.get("target_company_id"),
                    "transmission_channel": r.get("transmission_channel"),
                    "transmission_elasticity": r.get("transmission_elasticity", 1.0),
                    "raw_magnitude": r.get("raw_magnitude"),
                    "probability": r.get("probability"),
                    "lag_time_months": r.get("lag_time_months", 0),
                    "significance_rank": r.get("significance_rank"),
                }
                if cols is not None:
                    base = {k: v for k, v in base.items() if k in cols}
                keys = list(base.keys())
                cur = conn.execute(
                    f"INSERT INTO ripple_effects ({', '.join(keys)}) "
                    f"VALUES ({', '.join('?' for _ in keys)})",
                    [base[k] for k in keys],
                )
                if r.get("_ref") is not None:
                    ref_map[r["_ref"]] = cur.lastrowid
                inserted += 1
            return inserted

    def get_graph_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        with self.db.session() as conn:
            row = conn.execute("SELECT * FROM graph_nodes WHERE node_id = ?", (node_id,)).fetchone()
            return dict(row) if row else None

    def get_all_graph_nodes(self) -> List[Dict[str, Any]]:
        with self.db.session() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM graph_nodes ORDER BY name")]

    def get_all_causal_edges(self) -> List[Dict[str, Any]]:
        with self.db.session() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM graph_causal_edges ORDER BY created_at")]

    def get_macro_events(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM macro_events"
        params: List[Any] = []
        if category:
            query += " WHERE category = ?"
            params.append(category)
        query += " ORDER BY event_date DESC, created_at DESC"
        with self.db.session() as conn:
            return [dict(row) for row in conn.execute(query, params)]

    def upsert_parameter_definitions(self, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        query = """
        INSERT INTO dynamic_parameter_definitions
            (parameter_key, display_name, data_type, description, category)
        VALUES (:parameter_key, :display_name, :data_type, :description, :category)
        ON CONFLICT(parameter_key) DO UPDATE SET
            display_name = excluded.display_name, data_type = excluded.data_type,
            description = excluded.description, category = excluded.category
        """
        with self.db.session() as conn:
            return conn.executemany(query, records).rowcount

    def get_parameter_definitions(self, parameter_key: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM dynamic_parameter_definitions"
        params: List[Any] = []
        if parameter_key:
            query += " WHERE parameter_key = ?"
            params.append(parameter_key)
        query += " ORDER BY parameter_key"
        with self.db.session() as conn:
            return [dict(row) for row in conn.execute(query, params)]

    def upsert_distilled_parameters(self, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        query = """
        INSERT INTO company_distilled_parameters
            (isin, symbol, parameter_key, value_json, confidence_score,
             source_document_ref, last_updated_date)
        VALUES (:isin, :symbol, :parameter_key, :value_json, :confidence_score,
                :source_document_ref, :last_updated_date)
        ON CONFLICT(isin, parameter_key) DO UPDATE SET
            symbol = excluded.symbol, value_json = excluded.value_json,
            confidence_score = excluded.confidence_score,
            source_document_ref = excluded.source_document_ref,
            last_updated_date = excluded.last_updated_date
        """
        values = [{**record, "confidence_score": record.get("confidence_score", 1.0),
                   "value_json": self._json_value(record.get("value_json", {}))}
                  for record in records]
        with self.db.session() as conn:
            return conn.executemany(query, values).rowcount

    def get_distilled_parameters(self, symbol: str, parameter_key: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM company_distilled_parameters WHERE symbol = ?"
        params: List[Any] = [symbol]
        if parameter_key:
            query += " AND parameter_key = ?"
            params.append(parameter_key)
        query += " ORDER BY parameter_key"
        with self.db.session() as conn:
            return [dict(row) for row in conn.execute(query, params)]

    # -------------------------------------------------------------
    # 9. Full-Text Search, History, PIT, Deals, and Inbox Manifest
    # -------------------------------------------------------------
    def insert_fts_chunks(self, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        query = """
        INSERT INTO intelligence_fts
            (chunk_id, symbol, isin, source_type, document_date, document_text)
        VALUES (:chunk_id, :symbol, :isin, :source_type, :document_date, :document_text)
        """
        with self.db.session() as conn:
            return conn.executemany(query, records).rowcount

    def search_fts(self, query: str, symbol: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        sql = "SELECT chunk_id, symbol, isin, source_type, document_date, document_text, bm25(intelligence_fts) AS rank " \
              "FROM intelligence_fts WHERE intelligence_fts MATCH ?"
        params: List[Any] = [query]
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
        sql += " ORDER BY rank LIMIT ?"
        params.append(max(1, int(limit)))
        with self.db.session() as conn:
            return [dict(row) for row in conn.execute(sql, params)]

    def delete_fts_document(self, chunk_id: str) -> int:
        with self.db.session() as conn:
            return conn.execute("DELETE FROM intelligence_fts WHERE chunk_id = ?", (chunk_id,)).rowcount

    def get_quarterly_financials_history(self, symbol: str, quarters: int = 8) -> pd.DataFrame:
        query = """
        SELECT * FROM quarterly_financials
        WHERE symbol = ? ORDER BY quarter_end_date DESC LIMIT ?
        """
        with self.db.session() as conn:
            return pd.read_sql_query(query, conn, params=[symbol, max(1, int(quarters))])

    def get_recent_insider_trades(self, symbol: Optional[str] = None, days: int = 30,
                                  as_of_date: Optional[str] = None) -> pd.DataFrame:
        query = """SELECT * FROM insider_trades
                   WHERE acquisition_date >= date(COALESCE(?, 'now'), ?)
                """
        params: List[Any] = [as_of_date, f"-{max(0, int(days))} days"]
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        query += " ORDER BY acquisition_date DESC"
        with self.db.session() as conn:
            return pd.read_sql_query(query, conn, params=params)

    def get_recent_bulk_block_deals(self, symbol: Optional[str] = None, days: int = 30,
                                    as_of_date: Optional[str] = None) -> pd.DataFrame:
        query = """SELECT * FROM bulk_block_deals
                   WHERE deal_date >= date(COALESCE(?, 'now'), ?)
                """
        params: List[Any] = [as_of_date, f"-{max(0, int(days))} days"]
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        query += " ORDER BY deal_date DESC"
        with self.db.session() as conn:
            return pd.read_sql_query(query, conn, params=params)

    def upsert_inbox_manifest(self, records: Any) -> int:
        batch = records if isinstance(records, list) else [records]
        if not batch:
            return 0
        query = """
        INSERT INTO inbox_ingestion_manifest (
            file_hash, original_filename, file_type, detected_entity_type,
            target_entity_key, summary, extracted_parameters_json,
            associated_graph_nodes_json, processed_file_path
        ) VALUES (
            :file_hash, :original_filename, :file_type, :detected_entity_type,
            :target_entity_key, :summary, :extracted_parameters_json,
            :associated_graph_nodes_json, :processed_file_path
        )
        ON CONFLICT(file_hash) DO UPDATE SET
            original_filename = excluded.original_filename, file_type = excluded.file_type,
            detected_entity_type = excluded.detected_entity_type,
            target_entity_key = excluded.target_entity_key, summary = excluded.summary,
            extracted_parameters_json = excluded.extracted_parameters_json,
            associated_graph_nodes_json = excluded.associated_graph_nodes_json,
            processed_file_path = excluded.processed_file_path,
            ingested_timestamp = CURRENT_TIMESTAMP
        """
        values = [{**record,
                   "target_entity_key": record.get("target_entity_key"),
                   "summary": record.get("summary"),
                   "extracted_parameters_json": self._json_value(record.get("extracted_parameters_json")),
                   "associated_graph_nodes_json": self._json_value(record.get("associated_graph_nodes_json"))}
                  for record in batch]
        with self.db.session() as conn:
            return conn.executemany(query, values).rowcount

    def get_inbox_manifest(self, file_hash: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM inbox_ingestion_manifest"
        params: List[Any] = []
        if file_hash:
            query += " WHERE file_hash = ?"
            params.append(file_hash)
        query += " ORDER BY ingested_timestamp DESC"
        with self.db.session() as conn:
            return [dict(row) for row in conn.execute(query, params)]

    # -------------------------------------------------------------
    # 10c. Moat & Business Model Profile (Wave A2 — quality peer of the
    #      all-peers ensemble). Adds canonical dense-substrate tables for the
    #      moat/quality lens. NEW methods only; does not touch other sections.
    # -------------------------------------------------------------
    def ensure_moat_schema(self, manager=None) -> None:
        """Create moat_evaluations (SQLite fallback) if absent; align with pruning_engine.

        Idempotent across runs. Adds ``isin``/``eval_date`` columns if an earlier
        pruning_engine.ensure_pruning_schema created the table without them.
        """
        mgr = manager or self.db
        _MOAT_DDL = """
        CREATE TABLE IF NOT EXISTS moat_evaluations (
            company_id INTEGER PRIMARY KEY,
            ticker TEXT UNIQUE,
            isin TEXT,
            eval_date TEXT DEFAULT CURRENT_TIMESTAMP,
            switching_costs INTEGER CHECK (switching_costs BETWEEN 0 AND 5),
            network_effects INTEGER CHECK (network_effects BETWEEN 0 AND 5),
            cost_advantage INTEGER CHECK (cost_advantage BETWEEN 0 AND 5),
            intangible_assets INTEGER CHECK (intangible_assets BETWEEN 0 AND 5),
            efficient_scale INTEGER CHECK (efficient_scale BETWEEN 0 AND 5),
            total_moat_score REAL,
            moat_width TEXT,
            moat_trajectory TEXT CHECK (moat_trajectory IN ('Deteriorating','Stable','Expanding'))
        );
        """
        with mgr.session() as conn:
            conn.execute(_MOAT_DDL)
            try:
                cols = {r[1] for r in conn.execute("PRAGMA table_info('moat_evaluations')").fetchall()}
            except Exception:
                cols = set()
            for col, ddl in (("isin", "TEXT"), ("eval_date", "TEXT")):
                if col not in cols:
                    try:
                        conn.execute(f"ALTER TABLE moat_evaluations ADD COLUMN {col} {ddl}")
                    except Exception:
                        pass

    def ensure_business_profile_schema(self, manager=None) -> None:
        """Create canonical business_model_profiles (SQLite fallback) if absent.

        Also maintains a backward-compatible ``business_model_profiles_demo`` mirror so
        the existing composite_screener (out of this wave's edit scope) keeps resolving
        archetype/pricing_power by symbol. Remove the mirror once composite_screener is
        migrated to the canonical table.
        """
        mgr = manager or self.db
        _BP_DDL = """
        CREATE TABLE IF NOT EXISTS business_model_profiles (
            company_id INTEGER PRIMARY KEY,
            isin TEXT,
            symbol TEXT UNIQUE,
            archetype TEXT CHECK (archetype IN ('Platform','Tollbooth','Subscription SaaS','Asset-Heavy OEM','Asset-Light OEM','Network','Marketplace','Commodity')),
            revenue_recurrence_pct REAL,
            pricing_power_score INTEGER,
            capital_intensity_score INTEGER,
            operating_leverage_score INTEGER,
            qualitative_notes TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
        _BP_DEMO_DDL = """
        CREATE TABLE IF NOT EXISTS business_model_profiles_demo (
            symbol TEXT PRIMARY KEY,
            archetype TEXT,
            revenue_recurrence_pct REAL,
            pricing_power_score INTEGER,
            capital_intensity_score INTEGER,
            operating_leverage_score INTEGER,
            notes TEXT
        );
        """
        with mgr.session() as conn:
            conn.execute(_BP_DDL)
            conn.execute(_BP_DEMO_DDL)

    def _resolve_company_id(self, conn, symbol: Optional[str], isin: Optional[str]):
        """Resolve master_companies.rowid (integer surrogate) by ISIN then symbol.

        Returns int or None when the entity is not yet in the master directory.
        """
        try:
            if isin:
                row = conn.execute(
                    "SELECT rowid FROM master_companies WHERE isin = ?", (isin,)
                ).fetchone()
                if row:
                    return int(row["rowid"])
            if symbol:
                row = conn.execute(
                    "SELECT rowid FROM master_companies WHERE nse_symbol = ? OR bse_code = ?",
                    (symbol, symbol),
                ).fetchone()
                if row:
                    return int(row["rowid"])
        except Exception:
            return None
        return None

    def _resolve_isin(self, conn, company_id=None, symbol=None) -> Optional[str]:
        """Resolve ISIN from master_companies by rowid then symbol (strip/upper-case).

        In-instance dict cache: key is (company_id, normalized_symbol). Resolves
        ``isin`` from ``master_companies`` by ``rowid=company_id`` first, then by
        ``nse_symbol=symbol`` (strip/upper-case compare, also checks bse_code for
        robustness). Returns ``isin`` or ``None``. Never raises.
        """
        # Normalize symbol for cache key / comparison
        norm_symbol = None
        if isinstance(symbol, str):
            norm_symbol = symbol.strip().upper()
            if norm_symbol == "":
                norm_symbol = None
        elif symbol is not None:
            try:
                norm_symbol = str(symbol).strip().upper()
                if norm_symbol == "":
                    norm_symbol = None
            except Exception:
                norm_symbol = None
        cache_key = (company_id, norm_symbol)
        if cache_key in self._resolve_isin_cache:
            return self._resolve_isin_cache[cache_key]
        isin: Optional[str] = None
        try:
            if company_id is not None:
                try:
                    # company_id is expected to be master_companies.rowid
                    row = conn.execute(
                        "SELECT isin FROM master_companies WHERE rowid = ?", (int(company_id),)
                    ).fetchone()
                    if row and row["isin"]:
                        isin = str(row["isin"]).strip()
                        if isin == "":
                            isin = None
                except Exception:
                    isin = None
            if isin is None and norm_symbol:
                # strip/upper-case compare against both nse_symbol and bse_code
                try:
                    row = conn.execute(
                        "SELECT isin FROM master_companies WHERE UPPER(TRIM(nse_symbol)) = ? OR UPPER(TRIM(bse_code)) = ? LIMIT 1",
                        (norm_symbol, norm_symbol),
                    ).fetchone()
                    if row and row["isin"]:
                        isin = str(row["isin"]).strip()
                        if isin == "":
                            isin = None
                except Exception:
                    # Fallback to simple case-sensitive lookup if TRIM/UPPER unavailable
                    try:
                        row = conn.execute(
                            "SELECT isin FROM master_companies WHERE nse_symbol = ? OR bse_code = ? LIMIT 1",
                            (symbol.strip() if isinstance(symbol, str) else symbol, symbol),
                        ).fetchone()
                        if row and row["isin"]:
                            isin = str(row["isin"]).strip()
                    except Exception:
                        isin = None
        except Exception:
            isin = None
        self._resolve_isin_cache[cache_key] = isin
        return isin

    def upsert_moat_evaluation(self, ticker: str, switching_costs: int,
                               network_effects: int, cost_advantage: int,
                               intangible_assets: int, efficient_scale: int,
                               moat_trajectory: str = "Stable", isin=None,
                               company_id=None, manager=None) -> float:
        """Upsert a moat evaluation, computing total_moat_score and moat_width in Python.

        SQLite fallback has no GENERATED columns, so the score/width are computed here.
        Keyed by ticker (UNIQUE); company_id resolves via master_companies when present.
        Returns the computed total_moat_score.
        """
        total = round(
            float(switching_costs) * 0.25 + float(network_effects) * 0.25
            + float(cost_advantage) * 0.20 + float(intangible_assets) * 0.20
            + float(efficient_scale) * 0.10, 2
        )
        width = "Wide" if total >= 3.5 else ("Narrow" if total >= 2.5 else "None")
        mgr = manager or self.db
        with mgr.session() as conn:
            if isin is None or (isinstance(isin, str) and not isin.strip()):
                isin = self._resolve_isin(conn, company_id=company_id, symbol=ticker)
            cid = company_id if company_id is not None else self._resolve_company_id(conn, ticker, isin)
            conn.execute(
                """
                INSERT INTO moat_evaluations
                    (company_id, ticker, isin, switching_costs, network_effects,
                     cost_advantage, intangible_assets, efficient_scale,
                     total_moat_score, moat_width, moat_trajectory)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    company_id = COALESCE(excluded.company_id, moat_evaluations.company_id),
                    isin = excluded.isin,
                    switching_costs = excluded.switching_costs,
                    network_effects = excluded.network_effects,
                    cost_advantage = excluded.cost_advantage,
                    intangible_assets = excluded.intangible_assets,
                    efficient_scale = excluded.efficient_scale,
                    total_moat_score = excluded.total_moat_score,
                    moat_width = excluded.moat_width,
                    moat_trajectory = excluded.moat_trajectory
                """,
                (cid, ticker, isin, switching_costs, network_effects, cost_advantage,
                 intangible_assets, efficient_scale, total, width, moat_trajectory),
            )
            return total

    def upsert_business_model_profile(self, symbol: str, archetype: str,
                                      revenue_recurrence_pct: float,
                                      pricing_power_score: int,
                                      capital_intensity_score: int,
                                      operating_leverage_score: int,
                                      qualitative_notes: str = "", isin=None,
                                      company_id=None, manager=None) -> None:
        """Upsert a business_model_profiles row (keyed by symbol)."""
        mgr = manager or self.db
        with mgr.session() as conn:
            if isin is None or (isinstance(isin, str) and not isin.strip()):
                isin = self._resolve_isin(conn, company_id=company_id, symbol=symbol)
            cid = company_id if company_id is not None else self._resolve_company_id(conn, symbol, isin)
            conn.execute(
                """
                INSERT INTO business_model_profiles
                    (company_id, isin, symbol, archetype, revenue_recurrence_pct,
                     pricing_power_score, capital_intensity_score, operating_leverage_score,
                     qualitative_notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    company_id = COALESCE(excluded.company_id, business_model_profiles.company_id),
                    isin = excluded.isin,
                    archetype = excluded.archetype,
                    revenue_recurrence_pct = excluded.revenue_recurrence_pct,
                    pricing_power_score = excluded.pricing_power_score,
                    capital_intensity_score = excluded.capital_intensity_score,
                    operating_leverage_score = excluded.operating_leverage_score,
                    qualitative_notes = excluded.qualitative_notes
                """,
                (cid, isin, symbol, archetype, revenue_recurrence_pct, pricing_power_score,
                 capital_intensity_score, operating_leverage_score, qualitative_notes),
            )
            # Backward-compatible mirror for composite_screener (read-only consumer of
            # business_model_profiles_demo). Idempotent; safe to keep until migration.
            try:
                conn.execute(
                    """
                    INSERT INTO business_model_profiles_demo
                        (symbol, archetype, revenue_recurrence_pct, pricing_power_score,
                         capital_intensity_score, operating_leverage_score, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol) DO UPDATE SET
                        archetype = excluded.archetype,
                        revenue_recurrence_pct = excluded.revenue_recurrence_pct,
                        pricing_power_score = excluded.pricing_power_score,
                        capital_intensity_score = excluded.capital_intensity_score,
                        operating_leverage_score = excluded.operating_leverage_score,
                        notes = excluded.notes
                    """,
                    (symbol, archetype, revenue_recurrence_pct, pricing_power_score,
                     capital_intensity_score, operating_leverage_score, qualitative_notes),
                )
            except Exception:
                # If the demo mirror is absent, the canonical table is sufficient.
                pass

    def get_moat_evaluation(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch a moat evaluation by ticker or isin (None if absent)."""
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT * FROM moat_evaluations WHERE ticker = ? OR isin = ?",
                (symbol, symbol),
            ).fetchone()
            return dict(row) if row else None

    def list_moat_evaluations(self) -> List[Dict[str, Any]]:
        """Return all moat evaluations ordered by ticker."""
        with self.db.session() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM moat_evaluations ORDER BY ticker ASC")]

    def get_business_model_profile(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch a business model profile by symbol or isin (None if absent)."""
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT * FROM business_model_profiles WHERE symbol = ? OR isin = ?",
                (symbol, symbol),
            ).fetchone()
            return dict(row) if row else None

    def list_business_model_profiles(self) -> List[Dict[str, Any]]:
        """Return all business model profiles ordered by symbol."""
        with self.db.session() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM business_model_profiles ORDER BY symbol ASC")]

    # -------------------------------------------------------------
    # 10b. Raw Document Registry (macro PDF audit trail)
    # -------------------------------------------------------------
    def upsert_raw_document(self, record: Dict[str, Any]) -> int:
        """Insert or update a raw_documents row (Central/State budgets, PIB, RBI).

        Dedup key: sha256_hash first, then source_url. Works for both SQLite WAL
        (runtime) and PostgreSQL (same portable SQL: SELECT -> UPDATE/INSERT).
        Returns the doc_id of the inserted/updated row.
        """
        if not record:
            return 0
        defaults = {
            "title": None,
            "source_type": None,
            "published_date": None,
            "fiscal_period": None,
            "source_url": None,
            "creator_or_ministry": None,
            "sha256_hash": None,
            "local_file_path": None,
            "file_size_bytes": 0,
        }
        rec = {**defaults, **record}

        with self.db.session() as conn:
            existing_id = None
            if rec["sha256_hash"]:
                row = conn.execute(
                    "SELECT doc_id FROM raw_documents WHERE sha256_hash = ?",
                    (rec["sha256_hash"],),
                ).fetchone()
                if row:
                    existing_id = int(row["doc_id"])
            if existing_id is None and rec["source_url"]:
                row = conn.execute(
                    "SELECT doc_id FROM raw_documents WHERE source_url = ?",
                    (rec["source_url"],),
                ).fetchone()
                if row:
                    existing_id = int(row["doc_id"])

            if existing_id is not None:
                conn.execute(
                    """
                    UPDATE raw_documents
                    SET title = ?, source_type = ?, published_date = ?, fiscal_period = ?,
                        source_url = ?, creator_or_ministry = ?, sha256_hash = ?,
                        local_file_path = ?, file_size_bytes = ?
                    WHERE doc_id = ?
                    """,
                    (
                        rec["title"], rec["source_type"], rec["published_date"], rec["fiscal_period"],
                        rec["source_url"], rec["creator_or_ministry"], rec["sha256_hash"],
                        rec["local_file_path"], rec["file_size_bytes"], existing_id,
                    ),
                )
                return existing_id

            cur = conn.execute(
                """
                INSERT INTO raw_documents
                    (title, source_type, published_date, fiscal_period, source_url,
                     creator_or_ministry, sha256_hash, local_file_path, file_size_bytes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec["title"], rec["source_type"], rec["published_date"], rec["fiscal_period"],
                    rec["source_url"], rec["creator_or_ministry"], rec["sha256_hash"],
                    rec["local_file_path"], rec["file_size_bytes"],
                ),
            )
            return int(cur.lastrowid)

    def get_raw_document_by_hash(self, sha256: str) -> Optional[Dict[str, Any]]:
        """Return a raw_documents row by sha256, or None if absent."""
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT * FROM raw_documents WHERE sha256_hash = ?", (sha256,)
            ).fetchone()
            return dict(row) if row else None

    def list_raw_documents_by_source(self, source_type_prefix: str) -> List[Dict[str, Any]]:
        """Return raw_documents whose source_type starts with ``source_type_prefix``."""
        with self.db.session() as conn:
            rows = conn.execute(
                "SELECT * FROM raw_documents WHERE source_type LIKE ? ORDER BY published_date DESC",
                (f"{source_type_prefix}%",),
            ).fetchall()
            return [dict(r) for r in rows]

    # -------------------------------------------------------------
    # 10d. Policy / Regulatory ENI (Wave B1 — policy peer of the
    #      all-peers ensemble). Adds canonical dense-substrate table
    #      regulatory_political_risks. NEW methods only; does not
    #      touch other sections. Coordinated with B2/B3 via additive,
    #      distinctly-named helpers (get_policy_*, upsert_regulatory_*).
    # -------------------------------------------------------------
    # Canonical coverage-only sentinel for industries without a template.
    _NO_POLICY_TEMPLATE = "__NO_POLICY_TEMPLATE__"

    def ensure_regulatory_political_risks_schema(self, manager=None) -> None:
        """Create regulatory_political_risks (SQLite fallback) if absent; align with postgres_schema.sql.

        PostgreSQL already defines it (with a GENERATED net_impact_score). The SQLite WAL
        fallback has no GENERATED columns, so net_impact_score is computed in Python and
        stored explicitly. Idempotent; also adds any missing columns if a partial earlier
        table exists.

        Migration (Task: policy coverage): adds nullable ``coverage_status`` TEXT with
        allowed values ``mapped`` / ``no_template`` / ``unknown`` and DEFAULT ``mapped``.
        For an existing table the column is added via ``ALTER TABLE ... ADD COLUMN`` only
        when absent (PRAGMA inspect); never recreates/drops data. PostgreSQL path uses
        ``ADD COLUMN IF NOT EXISTS``.
        """
        mgr = manager or self.db
        _DDL = """
        CREATE TABLE IF NOT EXISTS regulatory_political_risks (
            risk_id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER,
            ticker TEXT,
            isin TEXT,
            symbol TEXT,
            policy_name TEXT NOT NULL,
            risk_type TEXT,
            factor_type TEXT,
            severity_score REAL,
            probability REAL,
            net_impact_score REAL,
            time_horizon TEXT,
            coverage_status TEXT CHECK (coverage_status IN ('mapped','no_template','unknown')) DEFAULT 'mapped',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, policy_name)
        );
        """
        with mgr.session() as conn:
            conn.execute(_DDL)
            # Idempotent column additions for forward-compat / migration.
            _cols = None
            _is_pg = False
            try:
                _cols = {r[1] for r in conn.execute("PRAGMA table_info('regulatory_political_risks')").fetchall()}
            except Exception:
                _cols = None
                _is_pg = True
            if _is_pg or _cols is None:
                # PostgreSQL: migration-safe IF NOT EXISTS
                try:
                    conn.execute(
                        "ALTER TABLE regulatory_political_risks ADD COLUMN IF NOT EXISTS coverage_status VARCHAR(20) "
                        "CHECK (coverage_status IN ('mapped','no_template','unknown')) DEFAULT 'mapped'"
                    )
                except Exception:
                    pass
            else:
                cols = _cols
                for col, ddl in (
                    ("company_id", "INTEGER"),
                    ("ticker", "TEXT"),
                    ("isin", "TEXT"),
                    ("symbol", "TEXT"),
                    ("policy_name", "TEXT"),
                    ("risk_type", "TEXT"),
                    ("factor_type", "TEXT"),
                    ("severity_score", "REAL"),
                    ("probability", "REAL"),
                    ("net_impact_score", "REAL"),
                    ("time_horizon", "TEXT"),
                    ("coverage_status", "TEXT CHECK (coverage_status IN ('mapped','no_template','unknown')) DEFAULT 'mapped'"),
                    ("created_at", "TEXT"),
                ):
                    if col not in cols:
                        try:
                            conn.execute(f"ALTER TABLE regulatory_political_risks ADD COLUMN {col} {ddl}")
                        except Exception:
                            # Fallback without CHECK/DEFAULT for older SQLite
                            try:
                                base_type = ddl.split()[0]
                                conn.execute(f"ALTER TABLE regulatory_political_risks ADD COLUMN {col} {base_type}")
                            except Exception:
                                pass

    @staticmethod
    def _policy_risk_type_for(severity: float) -> str:
        """Map signed severity to canonical risk_type (positive=Tailwind, negative=Headwind, zero=Auxiliary)."""
        if severity > 0:
            return "Tailwind"
        if severity < 0:
            return "Headwind"
        return "Auxiliary"

    def upsert_regulatory_political_risk(self, symbol, policy_name, severity_score=None, probability=None,
                                         risk_type=None, factor_type=None, net_impact_score=None,
                                         time_horizon="Mid-term", isin=None, company_id=None,
                                         manager=None, coverage_status=None) -> Optional[float]:
        """Upsert a policy/regulatory risk row keyed by (symbol, policy_name).

        Clamps severity to [-5, +5] and probability to [0, 1]. Computes net_impact_score
        (ENI = severity * probability) in Python for SQLite (no GENERATED column). Resolves
        company_id via master_companies when present; synthetic -1 when absent (still
        queryable by symbol). Returns the computed net_impact_score, or ``None`` for a
        coverage-only row.

        Coverage-only rows (``policy_name == '__NO_POLICY_TEMPLATE__'``) MUST have
        ``severity_score is None``, ``probability is None``, ``net_impact_score is None``
        and ``coverage_status == 'no_template'``; they are stored with NULL impact fields
        and never fabricate a risk. Mapped rows retain numeric constraints and default
        ``coverage_status='mapped'``.
        """
        mgr = manager or self.db
        _NO_TMPL = self._NO_POLICY_TEMPLATE
        is_coverage_row = (policy_name == _NO_TMPL) or (coverage_status == "no_template")
        # --- Validation at the boundary ---
        if is_coverage_row:
            if policy_name != _NO_TMPL:
                raise ValueError("coverage_status='no_template' requires policy_name='__NO_POLICY_TEMPLATE__'")
            if severity_score is not None or probability is not None or net_impact_score is not None:
                raise ValueError("coverage-only row MUST use severity_score=None, probability=None, net_impact_score=None")
            # coverage row: all impact fields stay NULL
            sev = None
            prob = None
            net = None
            rt = None
            ft = None
            # time_horizon is not meaningful for coverage rows; store NULL
            th = None
            cov = "no_template"
        else:
            # Mapped row: require numeric severity/probability
            if coverage_status == "no_template":
                raise ValueError("coverage_status='no_template' requires policy_name='__NO_POLICY_TEMPLATE__'")
            if severity_score is None or probability is None:
                raise ValueError("mapped rows require numeric severity_score and probability")
            try:
                sev = max(-5.0, min(5.0, float(severity_score)))
            except Exception as e:
                raise ValueError(f"severity_score must be numeric: {e}")
            try:
                prob = max(0.0, min(1.0, float(probability)))
            except Exception as e:
                raise ValueError(f"probability must be numeric: {e}")
            if net_impact_score is None:
                net = round(sev * prob, 2)
            else:
                # Explicit net provided must be numeric; validate
                try:
                    net = float(net_impact_score)
                except Exception as e:
                    raise ValueError(f"net_impact_score must be numeric or None: {e}")
            rt = risk_type or self._policy_risk_type_for(sev)
            ft = factor_type or "Tariff"
            th = time_horizon
            cov = coverage_status or "mapped"
            if cov not in ("mapped", "unknown", "no_template"):
                raise ValueError(f"coverage_status must be one of mapped/no_template/unknown, got {cov!r}")
            # mapped rows must not use sentinel policy name
            if policy_name == _NO_TMPL:
                raise ValueError("mapped rows cannot use policy_name='__NO_POLICY_TEMPLATE__'")

        with mgr.session() as conn:
            # Ensure coverage_status column exists (migration idempotent)
            try:
                cols = {r[1] for r in conn.execute("PRAGMA table_info('regulatory_political_risks')").fetchall()}
                if "coverage_status" not in cols:
                    try:
                        conn.execute(
                            "ALTER TABLE regulatory_political_risks ADD COLUMN coverage_status TEXT "
                            "CHECK (coverage_status IN ('mapped','no_template','unknown')) DEFAULT 'mapped'"
                        )
                    except Exception:
                        pass
            except Exception:
                pass
            if isin is None or (isinstance(isin, str) and not isin.strip()):
                isin = self._resolve_isin(conn, company_id=company_id, symbol=symbol)
            cid = company_id if company_id is not None else self._resolve_company_id(conn, symbol, isin)
            if cid is None:
                cid = -1
            conn.execute(
                """
                INSERT INTO regulatory_political_risks
                    (company_id, ticker, isin, symbol, policy_name, risk_type, factor_type,
                     severity_score, probability, net_impact_score, time_horizon, coverage_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(symbol, policy_name) DO UPDATE SET
                    company_id = COALESCE(excluded.company_id, regulatory_political_risks.company_id),
                    ticker = excluded.ticker,
                    isin = excluded.isin,
                    risk_type = excluded.risk_type,
                    factor_type = excluded.factor_type,
                    severity_score = excluded.severity_score,
                    probability = excluded.probability,
                    net_impact_score = excluded.net_impact_score,
                    time_horizon = excluded.time_horizon,
                    coverage_status = excluded.coverage_status
                """,
                (cid, symbol, isin, symbol, policy_name, rt, ft, sev, prob, net, th, cov),
            )
            return net

    def get_policy_risks_for_symbol(self, symbol, manager=None) -> List[Dict[str, Any]]:
        """Return all regulatory_political_risks rows for a symbol/isin (empty list if none)."""
        rows: List[Dict[str, Any]] = []
        with (manager or self.db).session() as conn:
            cid = self._resolve_company_id(conn, symbol, None)
            rows = conn.execute(
                "SELECT * FROM regulatory_political_risks WHERE symbol=? OR isin=? OR company_id=? "
                "ORDER BY net_impact_score DESC",
                (symbol, symbol, cid if cid is not None else -1),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_policy_agg_eni(self, symbol, manager=None) -> Optional[float]:
        """Aggregate ENI (sum of net_impact_score) for a symbol/isin.

        Returns ``None`` when the symbol has no *mapped* risk (only a coverage-only
        ``__NO_POLICY_TEMPLATE__`` row or no rows at all). Returns the numeric sum
        (rounded to 2dp) when at least one mapped row exists. This replaces the old
        ``COALESCE(...,0)`` behavior which incorrectly turned unknown into a positive
        signal.

        Mapped rows are those with ``policy_name != '__NO_POLICY_TEMPLATE__'`` and a
        non-NULL ``net_impact_score`` (and, when the ``coverage_status`` column exists,
        ``coverage_status='mapped'``). Coverage-only rows are intentionally excluded.
        """
        with (manager or self.db).session() as conn:
            cid = self._resolve_company_id(conn, symbol, None)
            # Detect whether coverage_status column exists to filter correctly
            has_cov = False
            try:
                cols = {r[1] for r in conn.execute("PRAGMA table_info('regulatory_political_risks')").fetchall()}
                has_cov = "coverage_status" in cols
            except Exception:
                has_cov = False
            if has_cov:
                # Prefer coverage_status aware query
                try:
                    row = conn.execute(
                        "SELECT SUM(net_impact_score) AS agg, COUNT(*) AS cnt "
                        "FROM regulatory_political_risks "
                        "WHERE (symbol=? OR isin=? OR company_id=?) "
                        "AND policy_name != ? AND net_impact_score IS NOT NULL "
                        "AND (coverage_status='mapped' OR coverage_status IS NULL)",
                        (symbol, symbol, cid if cid is not None else -1, self._NO_POLICY_TEMPLATE),
                    ).fetchone()
                except Exception:
                    row = conn.execute(
                        "SELECT SUM(net_impact_score) AS agg, COUNT(*) AS cnt "
                        "FROM regulatory_political_risks "
                        "WHERE (symbol=? OR isin=? OR company_id=?) "
                        "AND policy_name != ? AND net_impact_score IS NOT NULL",
                        (symbol, symbol, cid if cid is not None else -1, self._NO_POLICY_TEMPLATE),
                    ).fetchone()
            else:
                row = conn.execute(
                    "SELECT SUM(net_impact_score) AS agg, COUNT(*) AS cnt "
                    "FROM regulatory_political_risks "
                    "WHERE (symbol=? OR isin=? OR company_id=?) "
                    "AND policy_name != ? AND net_impact_score IS NOT NULL",
                    (symbol, symbol, cid if cid is not None else -1, self._NO_POLICY_TEMPLATE),
                ).fetchone()
            if not row or row["cnt"] is None or int(row["cnt"]) == 0 or row["agg"] is None:
                return None
            return round(float(row["agg"]), 2)

    def get_policy_coverage(self, symbol, manager=None) -> str:
        """Return policy coverage status for a symbol/isin.

        Returns ``mapped`` if at least one mapped risk exists,
        ``no_template`` if only a coverage-only ``__NO_POLICY_TEMPLATE__`` row exists,
        otherwise ``unknown`` (no rows).
        """
        with (manager or self.db).session() as conn:
            cid = self._resolve_company_id(conn, symbol, None)
            try:
                cols = {r[1] for r in conn.execute("PRAGMA table_info('regulatory_political_risks')").fetchall()}
                has_cov = "coverage_status" in cols
            except Exception:
                has_cov = False
                cols = set()
            # Fetch all rows for this symbol to classify
            try:
                rows = conn.execute(
                    "SELECT policy_name, coverage_status, net_impact_score FROM regulatory_political_risks "
                    "WHERE symbol=? OR isin=? OR company_id=?",
                    (symbol, symbol, cid if cid is not None else -1),
                ).fetchall()
            except Exception:
                rows = []
            if not rows:
                return "unknown"
            # Has at least one mapped row?
            for r in rows:
                pn = r["policy_name"]
                cov = r["coverage_status"] if has_cov else None
                net = r["net_impact_score"]
                # Mapped: not sentinel, net not null, coverage mapped or null (legacy)
                if pn != self._NO_POLICY_TEMPLATE and net is not None:
                    if cov is None or cov == "mapped":
                        return "mapped"
                    # Even if cov is not mapped but pn is not sentinel, treat as mapped (legacy)
                    if cov not in ("no_template",):
                        return "mapped"
            # No mapped, check for coverage-only
            for r in rows:
                pn = r["policy_name"]
                cov = r["coverage_status"] if has_cov else None
                if pn == self._NO_POLICY_TEMPLATE and (cov == "no_template" or cov is None):
                    return "no_template"
            # Rows exist but neither classification -> treat as unknown? But fallback to mapped if any row has coverage no_template?
            # Check any no_template cov
            for r in rows:
                cov = r["coverage_status"] if has_cov else None
                if cov == "no_template":
                    return "no_template"
            return "unknown"

    def query_policy_adjusted_screen(self, min_agg_eni: float = 0.0, manager=None) -> List[Dict[str, Any]]:
        """Emulate PostgreSQL v_policy_adjusted_screen for SQLite (graceful fallback).

        Aggregates ``net_policy_score`` per company from *mapped* rows only
        (excludes ``__NO_POLICY_TEMPLATE__`` / ``coverage_status='no_template'`` rows).
        Unknown / coverage-only symbols have ``net_policy_score=None`` and
        ``policy_coverage`` in ``{'no_template','unknown'}`` and are **not** treated as
        ``>=0`` — they do not pass/fail a hard policy gate.

        LEFT JOINs ``moat_evaluations`` / ``financial_metrics`` when present for enrichment.
        Filters to rows where the mapped aggregate exists and ``agg >= min_agg_eni``.
        Rows with no mapped aggregate (``None``) are excluded from the >= filter but
        callers can inspect coverage via ``get_policy_coverage``.
        """
        mgr = manager or self.db
        out: List[Dict[str, Any]] = []
        with mgr.session() as conn:
            try:
                # Detect coverage_status column to filter correctly
                try:
                    cols = {r[1] for r in conn.execute("PRAGMA table_info('regulatory_political_risks')").fetchall()}
                    has_cov = "coverage_status" in cols
                except Exception:
                    has_cov = False
                if has_cov:
                    pa_rows = conn.execute(
                        "SELECT company_id, symbol, "
                        "SUM(CASE WHEN policy_name != ? AND net_impact_score IS NOT NULL "
                        "AND (coverage_status='mapped' OR coverage_status IS NULL) THEN net_impact_score ELSE NULL END) AS agg, "
                        "COUNT(CASE WHEN policy_name != ? AND net_impact_score IS NOT NULL "
                        "AND (coverage_status='mapped' OR coverage_status IS NULL) THEN 1 END) AS mapped_cnt, "
                        "MAX(CASE WHEN policy_name = ? THEN 1 ELSE 0 END) AS has_no_template "
                        "FROM regulatory_political_risks GROUP BY company_id, symbol",
                        (self._NO_POLICY_TEMPLATE, self._NO_POLICY_TEMPLATE, self._NO_POLICY_TEMPLATE),
                    ).fetchall()
                else:
                    pa_rows = conn.execute(
                        "SELECT company_id, symbol, "
                        "SUM(CASE WHEN policy_name != ? AND net_impact_score IS NOT NULL THEN net_impact_score END) AS agg, "
                        "COUNT(CASE WHEN policy_name != ? AND net_impact_score IS NOT NULL THEN 1 END) AS mapped_cnt, "
                        "MAX(CASE WHEN policy_name = ? THEN 1 ELSE 0 END) AS has_no_template "
                        "FROM regulatory_political_risks GROUP BY company_id, symbol",
                        (self._NO_POLICY_TEMPLATE, self._NO_POLICY_TEMPLATE, self._NO_POLICY_TEMPLATE),
                    ).fetchall()
            except Exception:
                return []
            # Schema-agnostic presence checks; degrade gracefully when absent.
            def _has(t: str) -> bool:
                try:
                    return conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)
                    ).fetchone() is not None
                except Exception:
                    return False
            moat_ok = _has("moat_evaluations")
            fin_ok = _has("financial_metrics")
            for r in pa_rows:
                mapped_cnt = int(r["mapped_cnt"] or 0)
                has_no_template = int(r["has_no_template"] or 0)
                agg_raw = r["agg"]
                # Determine coverage and net_policy_score
                if mapped_cnt > 0 and agg_raw is not None:
                    agg = float(agg_raw)
                    coverage = "mapped"
                    net_policy_score = round(agg, 2)
                    # Hard gate: only mapped aggregates are filtered >= threshold
                    if net_policy_score < min_agg_eni:
                        continue
                elif has_no_template:
                    # Coverage-only row: explicit unknown, do not pass hard gate
                    coverage = "no_template"
                    net_policy_score = None
                    # Do not treat as >=0: skip when filtering for >=0 (positive screen)
                    # The policy_adjusted_screen is defined as net_policy_score >=0, so coverage-only
                    # rows must not be returned for min_agg_eni >=0.
                    continue
                else:
                    # No mapped rows and no coverage row? Should not happen in GROUP BY, but treat as unknown
                    coverage = "unknown"
                    net_policy_score = None
                    continue
                symbol = r["symbol"]
                moat = None
                spread = None
                if symbol and moat_ok:
                    try:
                        mrow = conn.execute(
                            "SELECT total_moat_score FROM moat_evaluations WHERE ticker=? OR symbol=? LIMIT 1",
                            (symbol, symbol),
                        ).fetchone()
                        if mrow:
                            moat = mrow["total_moat_score"]
                    except Exception:
                        pass
                if fin_ok and r["company_id"] is not None:
                    try:
                        frow = conn.execute(
                            "SELECT roic_wacc_spread FROM financial_metrics WHERE company_id=? LIMIT 1",
                            (r["company_id"],),
                        ).fetchone()
                        if frow:
                            spread = frow["roic_wacc_spread"]
                    except Exception:
                        pass
                out.append({
                    "symbol": symbol,
                    "net_policy_score": net_policy_score,
                    "policy_coverage": coverage,
                    "policy_eni": net_policy_score,
                    "total_moat_score": moat,
                    "roic_wacc_spread": spread,
                })
        out.sort(key=lambda x: (x["symbol"] or ""))
        return out

    def ensure_v_policy_adjusted_screen(self, manager=None) -> bool:
        """Best-effort creation of a SQLite VIEW v_policy_adjusted_screen mirroring PG.

        Only references relations that actually exist (regulatory_political_risks is
        required; moat_evaluations / financial_metrics are LEFT JOINed when present).
        Filters to net_policy_score >= 0 over *mapped* rows only (excludes coverage-only
        ``__NO_POLICY_TEMPLATE__``). Coverage-only rows have ``net_policy_score`` NULL
        and are not considered ``>=0``. Returns True if the view exists/was created.
        Wrapped so it never raises.
        """
        mgr = manager or self.db
        try:
            with mgr.session() as conn:
                self.ensure_regulatory_political_risks_schema(mgr)

                def _has(t: str) -> bool:
                    try:
                        return conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)
                        ).fetchone() is not None
                    except Exception:
                        return False

                moat_ok = _has("moat_evaluations")
                fin_ok = _has("financial_metrics")

                # Aggregate only mapped rows: exclude sentinel and NULL net_impact_score
                # Also respect coverage_status when present.
                try:
                    cols = {r[1] for r in conn.execute("PRAGMA table_info('regulatory_political_risks')").fetchall()}
                    has_cov = "coverage_status" in cols
                except Exception:
                    has_cov = False
                if has_cov:
                    sum_expr = f"SUM(CASE WHEN r.policy_name != '{self._NO_POLICY_TEMPLATE}' AND r.net_impact_score IS NOT NULL AND (r.coverage_status='mapped' OR r.coverage_status IS NULL) THEN r.net_impact_score END)"
                else:
                    sum_expr = f"SUM(CASE WHEN r.policy_name != '{self._NO_POLICY_TEMPLATE}' AND r.net_impact_score IS NOT NULL THEN r.net_impact_score END)"
                sel = f"SELECT r.symbol, {sum_expr} AS net_policy_score"
                joins = "FROM regulatory_political_risks r"
                if moat_ok:
                    sel += ", m.total_moat_score"
                    joins += " LEFT JOIN moat_evaluations m ON (m.ticker=r.symbol OR m.symbol=r.symbol)"
                else:
                    sel += ", NULL AS total_moat_score"
                if fin_ok:
                    sel += ", f.roic_wacc_spread"
                    joins += " LEFT JOIN financial_metrics f ON f.company_id=r.company_id"
                else:
                    sel += ", NULL AS roic_wacc_spread"
                sel += (
                    f" {joins} GROUP BY r.symbol, r.company_id "
                    f"HAVING {sum_expr} >= 0"
                )
                # Drop existing view to ensure updated definition (IF NOT EXISTS would keep old COALESCE version)
                try:
                    conn.execute("DROP VIEW IF EXISTS v_policy_adjusted_screen")
                except Exception:
                    pass
                conn.execute(f"CREATE VIEW v_policy_adjusted_screen AS {sel}")
                return True
        except Exception:
            return False

    # -------------------------------------------------------------
    # 15. Telegram Posts & Transcriptions
    # -------------------------------------------------------------
    def upsert_telegram_posts(self, records: Any) -> int:
        batch = records if isinstance(records, list) else [records]
        if not batch:
            return 0
        query = """
        INSERT INTO telegram_posts (
            id, channel_id, channel_title, thread_topic_id, thread_topic_name,
            message_id, raw_message_text, has_media, media_file_path,
            ocr_extracted_text, detected_symbols_json, button_links_json, post_timestamp
        ) VALUES (
            :id, :channel_id, :channel_title, :thread_topic_id, :thread_topic_name,
            :message_id, :raw_message_text, :has_media, :media_file_path,
            :ocr_extracted_text, :detected_symbols_json, :button_links_json, :post_timestamp
        )
        ON CONFLICT(id) DO UPDATE SET
            channel_id = excluded.channel_id,
            channel_title = excluded.channel_title,
            thread_topic_id = excluded.thread_topic_id,
            thread_topic_name = excluded.thread_topic_name,
            message_id = excluded.message_id,
            raw_message_text = excluded.raw_message_text,
            has_media = excluded.has_media,
            media_file_path = excluded.media_file_path,
            ocr_extracted_text = excluded.ocr_extracted_text,
            detected_symbols_json = excluded.detected_symbols_json,
            button_links_json = excluded.button_links_json,
            post_timestamp = excluded.post_timestamp;
        """
        values = [{
            "id": r.get("id", f"{r.get('channel_id', 'tg')}_{r.get('message_id', 0)}"),
            "channel_id": str(r.get("channel_id", "")),
            "channel_title": str(r.get("channel_title", "")),
            "thread_topic_id": int(r.get("thread_topic_id", 0) or 0),
            "thread_topic_name": r.get("thread_topic_name"),
            "message_id": int(r.get("message_id", 0)),
            "raw_message_text": r.get("raw_message_text", ""),
            "has_media": 1 if r.get("has_media") else 0,
            "media_file_path": r.get("media_file_path"),
            "ocr_extracted_text": r.get("ocr_extracted_text", ""),
            "detected_symbols_json": self._json_value(r.get("detected_symbols_json", [])),
            "button_links_json": self._json_value(r.get("button_links_json", [])),
            "post_timestamp": str(r.get("post_timestamp", ""))
        } for r in batch]
        with self.db.session() as conn:
            return conn.executemany(query, values).rowcount

    def get_telegram_posts(self, symbol: Optional[str] = None, channel_id: Optional[str] = None, thread_topic_id: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
        query = "SELECT * FROM telegram_posts WHERE 1=1"
        params: List[Any] = []
        if channel_id:
            query += " AND channel_id = ?"
            params.append(channel_id)
        if thread_topic_id:
            query += " AND thread_topic_id = ?"
            params.append(int(thread_topic_id))
        if symbol:
            query += " AND (detected_symbols_json LIKE ? OR raw_message_text LIKE ? OR ocr_extracted_text LIKE ?)"
            pat = f"%{symbol}%"
            params.extend([pat, pat, pat])
        query += " ORDER BY post_timestamp DESC LIMIT ?"
        params.append(limit)
        with self.db.session() as conn:
            return [dict(row) for row in conn.execute(query, params)]

    # -------------------------------------------------------------
    # 16. FinanciallyFree Sector & Breadth Snapshot
    # -------------------------------------------------------------
    def upsert_financially_free_breadth(self, records: Any) -> int:
        batch = records if isinstance(records, list) else [records]
        if not batch:
            return 0
        query = """
        INSERT INTO financially_free_breadth (
            date, sector_name, advances_count, declines_count,
            advance_decline_ratio, sector_momentum_score,
            top_gainers_json, top_losers_json
        ) VALUES (
            :date, :sector_name, :advances_count, :declines_count,
            :advance_decline_ratio, :sector_momentum_score,
            :top_gainers_json, :top_losers_json
        )
        ON CONFLICT(date, sector_name) DO UPDATE SET
            advances_count = excluded.advances_count,
            declines_count = excluded.declines_count,
            advance_decline_ratio = excluded.advance_decline_ratio,
            sector_momentum_score = excluded.sector_momentum_score,
            top_gainers_json = excluded.top_gainers_json,
            top_losers_json = excluded.top_losers_json;
        """
        values = [{
            "date": str(r.get("date", "")),
            "sector_name": str(r.get("sector_name", "")),
            "advances_count": int(r.get("advances_count", 0)),
            "declines_count": int(r.get("declines_count", 0)),
            "advance_decline_ratio": float(r.get("advance_decline_ratio", 1.0)),
            "sector_momentum_score": float(r.get("sector_momentum_score", 0.0)) if r.get("sector_momentum_score") is not None else None,
            "top_gainers_json": self._json_value(r.get("top_gainers_json", r.get("top_gainers", []))),
            "top_losers_json": self._json_value(r.get("top_losers_json", r.get("top_losers", []))),
        } for r in batch]
        with self.db.session() as conn:
            return conn.executemany(query, values).rowcount

    def get_financially_free_breadth(self, target_date: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM financially_free_breadth"
        params: List[Any] = []
        if target_date:
            query += " WHERE date = ?"
            params.append(target_date)
        query += " ORDER BY date DESC, sector_momentum_score DESC"
        with self.db.session() as conn:
            return [dict(row) for row in conn.execute(query, params)]

    # -------------------------------------------------------------
    # 10e. Ripple Effects + Geographic Exposure (Wave B2 — supply-chain
    #      peer of the all-peers ensemble). Adds canonical dense-substrate
    #      tables for the causal DAG. NEW additive methods only; does not
    #      touch other sections (B1/B3 coordinate via distinct helpers).
    # -------------------------------------------------------------
    def ensure_ripple_effects_schema(self, manager=None) -> None:
        """Create ripple_effects (SQLite fallback) if absent; align with postgres_schema.sql.

        PostgreSQL already defines it (with SERIAL pk + FK to macro_events). The
        SQLite WAL fallback lacks SERIAL/FK enforcement, so we define a portable
        schema with ``event_id TEXT`` and a self-referencing ``parent_ripple_id``.
        Idempotent; also ensures indexes for the DAG traversal.
        """
        mgr = manager or self.db
        _DDL = """
        CREATE TABLE IF NOT EXISTS ripple_effects (
            ripple_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT,
            parent_ripple_id INTEGER,
            order_level INTEGER NOT NULL DEFAULT 1,
            target_type TEXT,
            target_sector_id INTEGER,
            target_industry_id INTEGER,
            target_company_id INTEGER,
            transmission_channel TEXT NOT NULL DEFAULT 'direct',
            transmission_elasticity REAL DEFAULT 1.0,
            raw_magnitude REAL,
            probability REAL,
            lag_time_months INTEGER DEFAULT 0,
            significance_rank REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(parent_ripple_id) REFERENCES ripple_effects(ripple_id)
        );
        """
        with mgr.session() as conn:
            conn.execute(_DDL)
            try:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ripple_hierarchy "
                    "ON ripple_effects(event_id, parent_ripple_id, order_level)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ripple_targets "
                    "ON ripple_effects(target_company_id, target_industry_id)"
                )
            except Exception:
                pass

    def get_ripple_effects_for_event(self, event_id: Any) -> List[Dict[str, Any]]:
        """Return all ripple_effects rows for an event_id (empty list if none)."""
        with self.db.session() as conn:
            rows = conn.execute(
                "SELECT * FROM ripple_effects WHERE event_id = ? ORDER BY order_level, ripple_id",
                (event_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_ripple_effects(self) -> List[Dict[str, Any]]:
        """Return every ripple_effects row (used by trace/spawn pipelines)."""
        with self.db.session() as conn:
            rows = conn.execute(
                "SELECT * FROM ripple_effects ORDER BY event_id, order_level, ripple_id"
            ).fetchall()
            return [dict(r) for r in rows]

    # -------------------------------------------------------------
    # 11b. Wave D2 — Transient Event-Graph atomic spawn helper
    #      (additive; distinct from every other wave's helpers).
    # -------------------------------------------------------------
    def upsert_event_graph(self, event_id: Any, macro_record: Dict[str, Any],
                           ripples: List[Dict[str, Any]], manager=None) -> int:
        """Atomically create/update a ``macro_events`` row + its full ``ripple_effects`` DAG.

        Both writes happen inside ONE transaction so an invalid extraction (validated by
        the caller via ``MacroEventExtraction``) or any insert failure rolls back cleanly
        — never a half-written transient graph in the dense substrate. Schema-tolerant to
        SQLite (event_id TEXT PK, doc_id added idempotently) and PostgreSQL.
        """
        self.ensure_ripple_effects_schema(manager or self.db)
        self.ensure_macro_event_doc_id(manager or self.db)

        event_name = macro_record.get("event_name")
        category = macro_record.get("category") or macro_record.get("event_category")
        event_date = macro_record.get("event_date") or macro_record.get("announcement_date") or date.today().isoformat()
        summary = macro_record.get("summary") or ""
        affected = self._json_value(macro_record.get("affected_nodes_json"))
        doc_id = macro_record.get("doc_id")
        raw_document_path = macro_record.get("raw_document_path")

        with (manager or self.db).session() as conn:
            cols = self._macro_event_columns(conn)
            if cols is None:
                # PostgreSQL branch (no PRAGMA support) — simple insert/update.
                existing = None
                if doc_id is not None and event_name:
                    try:
                        row = conn.execute(
                            "SELECT event_id FROM macro_events WHERE doc_id=:d AND event_name=:n",
                            {"d": doc_id, "n": event_name},
                        ).fetchone()
                        existing = row["event_id"] if row else None
                    except Exception:
                        existing = None
                if existing is not None:
                    conn.execute(
                        "UPDATE macro_events SET event_category=:c, announcement_date=:dt WHERE event_id=:e",
                        {"c": category, "dt": event_date, "e": existing},
                    )
                else:
                    conn.execute(
                        "INSERT INTO macro_events (doc_id, event_name, event_category, announcement_date) "
                        "VALUES (:d, :n, :c, :dt)",
                        {"d": doc_id, "n": event_name, "c": category, "dt": event_date},
                    )
            else:
                if "doc_id" not in cols:
                    try:
                        conn.execute("ALTER TABLE macro_events ADD COLUMN doc_id INTEGER")
                        cols = self._macro_event_columns(conn) or cols
                    except Exception:
                        pass
                field_map = {
                    "event_id": event_id,
                    "event_name": event_name,
                    "category": category,
                    "event_date": event_date,
                    "raw_document_path": raw_document_path,
                    "summary": summary,
                    "affected_nodes_json": affected,
                    "doc_id": doc_id,
                }
                present = {k: v for k, v in field_map.items() if k in cols}
                if "event_id" in cols and not present.get("event_id"):
                    present["event_id"] = (
                        f"MEV_{doc_id}" if doc_id is not None else f"MEV_{abs(hash(event_name))}"
                    )
                keys = list(present.keys())
                col_sql = ", ".join(keys)
                ph_sql = ", ".join(f":{k}" for k in keys)
                upd_sql = ", ".join(f"{k}=excluded.{k}" for k in keys if k != "event_id")
                conflict_sql = f"ON CONFLICT(event_id) DO UPDATE SET {upd_sql}" if upd_sql else ""
                conn.execute(
                    f"INSERT INTO macro_events ({col_sql}) VALUES ({ph_sql}) {conflict_sql}",
                    present,
                )

            # Replace the entire ripple DAG for this event inside the same transaction.
            conn.execute("DELETE FROM ripple_effects WHERE event_id = ?", (event_id,))
            rcols = None
            if cols is not None:
                try:
                    rcols = {c[1] for c in conn.execute("PRAGMA table_info('ripple_effects')").fetchall()}
                except Exception:
                    rcols = None
            ref_map: Dict[Any, int] = {}
            inserted = 0
            for r in ripples:
                parent_ripple_id = ref_map.get(r["_parent_ref"]) if r.get("_parent_ref") is not None else None
                base = {
                    "event_id": event_id,
                    "parent_ripple_id": parent_ripple_id,
                    "order_level": r.get("order_level"),
                    "target_type": r.get("target_type"),
                    "target_sector_id": r.get("target_sector_id"),
                    "target_industry_id": r.get("target_industry_id"),
                    "target_company_id": r.get("target_company_id"),
                    "transmission_channel": r.get("transmission_channel"),
                    "transmission_elasticity": r.get("transmission_elasticity", 1.0),
                    "raw_magnitude": r.get("raw_magnitude"),
                    "probability": r.get("probability"),
                    "lag_time_months": r.get("lag_time_months", 0),
                    "significance_rank": r.get("significance_rank"),
                }
                if rcols is not None:
                    base = {k: v for k, v in base.items() if k in rcols}
                bkeys = list(base.keys())
                cur = conn.execute(
                    f"INSERT INTO ripple_effects ({', '.join(bkeys)}) "
                    f"VALUES ({', '.join('?' for _ in bkeys)})",
                    [base[k] for k in bkeys],
                )
                if r.get("_ref") is not None:
                    ref_map[r["_ref"]] = cur.lastrowid
                inserted += 1
        return inserted

    def ensure_geographic_exposure_schema(self, manager=None) -> None:
        """Create geographic_exposure (SQLite fallback) if absent; align with postgres_schema.sql.

        PostgreSQL defines ``countries`` / ``geographic_exposure`` with integer
        ``country_id`` FK. The SQLite fallback keeps ``country_id`` as TEXT (the
        ISO code, e.g. 'IND', 'USA') so it is usable without a separate countries
        seed table while remaining policy/peer-queryable.
        """
        mgr = manager or self.db
        _DDL = """
        CREATE TABLE IF NOT EXISTS geographic_exposure (
            company_id INTEGER NOT NULL,
            country_id TEXT NOT NULL,
            revenue_share_pct REAL DEFAULT 0.0,
            asset_exposure_pct REAL DEFAULT 0.0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (company_id, country_id)
        );
        """
        with mgr.session() as conn:
            conn.execute(_DDL)

    def upsert_geographic_exposure(self, company_id: int, country_id: Any,
                                   revenue_share_pct: float = 0.0,
                                   asset_exposure_pct: float = 0.0,
                                   manager=None) -> None:
        """Upsert a geographic_exposure row (company × country revenue/asset share)."""
        mgr = manager or self.db
        with mgr.session() as conn:
            conn.execute(
                """
                INSERT INTO geographic_exposure
                    (company_id, country_id, revenue_share_pct, asset_exposure_pct, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(company_id, country_id) DO UPDATE SET
                    revenue_share_pct = excluded.revenue_share_pct,
                    asset_exposure_pct = excluded.asset_exposure_pct,
                    created_at = CURRENT_TIMESTAMP
                """,
                (company_id, str(country_id), float(revenue_share_pct), float(asset_exposure_pct)),
            )

    def get_geographic_exposure(self, company_id: int) -> List[Dict[str, Any]]:
        """Return all geographic_exposure rows for a company (empty list if none)."""
        with self.db.session() as conn:
            rows = conn.execute(
                "SELECT * FROM geographic_exposure WHERE company_id = ? ORDER BY revenue_share_pct DESC",
                (company_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # -------------------------------------------------------------
    # 11. Wave B3 — All-Peers Ensemble helpers (additive; Wave D fills these)
    # -------------------------------------------------------------
    def ensure_ensemble_ranking_schema(self, manager=None) -> None:
        """Create model_explainer_rankings + lens_activation_log (Wave D tables).

        Uses the canonical Wave D1 DDL: stock_id/sector_id/geo_id/regime_tag as TEXT,
        investor_majority ∈ {promoter,FII,DII,retail,all}, and lens_family constrained to
        the four all-peers families. Idempotent; migrates away the Wave B3 placeholder
        schema (which used ``stock_id INTEGER`` and a different ``lens_activation_log``
        shape) by recreating the tables. The B3 tables were never populated, so the
        recreation is lossless.
        """
        mgr = manager or self.db
        _MER_DDL = """
        CREATE TABLE IF NOT EXISTS model_explainer_rankings (
            ranking_id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id TEXT,
            sector_id TEXT,
            geo_id TEXT,
            regime_tag TEXT,
            investor_majority TEXT CHECK (investor_majority IN ('promoter','FII','DII','retail','all')),
            lens_family TEXT CHECK (lens_family IN ('factor_statistical','business_quality','policy_macro','supply_chain')),
            p_value REAL,
            explain_power REAL,
            rank INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_id, sector_id, geo_id, regime_tag, investor_majority, lens_family)
        );
        """
        _LAL_DDL = """
        CREATE TABLE IF NOT EXISTS lens_activation_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            temperature REAL,
            fired_lenses TEXT,
            context_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
        with mgr.session() as conn:
            # Migrate a pre-existing Wave B3 placeholder schema (different column types /
            # shapes) so the Wave D1 DDL applies cleanly. The B3 tables were never
            # populated, so dropping + recreating is lossless.
            try:
                mer_cols = {
                    r[1]: r[2]
                    for r in conn.execute("PRAGMA table_info(model_explainer_rankings)").fetchall()
                }
                if mer_cols and mer_cols.get("stock_id", "").upper() == "INTEGER":
                    conn.execute("DROP TABLE IF EXISTS model_explainer_rankings")
            except Exception:
                pass
            try:
                lal_cols = {
                    r[1]
                    for r in conn.execute("PRAGMA table_info(lens_activation_log)").fetchall()
                }
                if lal_cols and "run_date" in lal_cols and "created_at" not in lal_cols:
                    conn.execute("DROP TABLE IF EXISTS lens_activation_log")
            except Exception:
                pass
            conn.execute(_MER_DDL)
            conn.execute(_LAL_DDL)

    def get_ensemble_weights(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
        """Return per-lens-family ensemble weights normalized to Σ==1.0.

        Wave D delegates to ``ensemble_ranker.EnsembleRanker``, which returns learned
        weights aggregated per conditional context (stock/sector/geo/regime/
        investor_majority) or, when no learned rankings exist, deterministic bootstrap
        weights. Falls back to the legacy aggregate-everything behaviour if the ranker
        cannot be imported.
        """
        try:
            from reality_engine.processing.ensemble_ranker import EnsembleRanker
            return EnsembleRanker(self.db).get_ensemble_weights_for_context(context)
        except Exception:
            # Legacy fallback (Wave B3 behaviour): aggregate all rows, ignoring context.
            if context is None:
                context = {}
            try:
                self.ensure_ensemble_ranking_schema()
                with self.db.session() as conn:
                    rows = conn.execute(
                        "SELECT lens_family, explain_power FROM model_explainer_rankings"
                    ).fetchall()
                    if not rows:
                        return {}
                    agg: Dict[str, float] = {}
                    for r in rows:
                        fam = r["lens_family"]
                        ep = float(r["explain_power"] or 0.0)
                        agg[fam] = agg.get(fam, 0.0) + ep
                    total = sum(agg.values())
                    if total <= 0:
                        return {}
                    return {fam: ep / total for fam, ep in agg.items()}
            except Exception:
                return {}

    def get_model_explainer_rankings(
        self,
        stock_id: Optional[Any] = None,
        sector_id: Optional[Any] = None,
        geo_id: Optional[Any] = None,
        regime_tag: Optional[Any] = None,
        investor_majority: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return learned lens rankings filtered by any provided context keys (Wave D)."""
        try:
            self.ensure_ensemble_ranking_schema()
            sql = "SELECT * FROM model_explainer_rankings WHERE 1=1"
            params: List[Any] = []
            for col, val in (
                ("stock_id", stock_id),
                ("sector_id", sector_id),
                ("geo_id", geo_id),
                ("regime_tag", regime_tag),
                ("investor_majority", investor_majority),
            ):
                if val is not None:
                    sql += f" AND {col}=?"
                    params.append(str(val))
            sql += " ORDER BY rank ASC"
            with self.db.session() as conn:
                rows = conn.execute(sql, params).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def upsert_model_explainer_rankings(self, records: List[Dict[str, Any]]) -> int:
        """Persist learned lens explain_power/rank (Wave D)."""
        if not records:
            return 0
        try:
            self.ensure_ensemble_ranking_schema()
            with self.db.session() as conn:
                conn.executemany(
                    """
                    INSERT INTO model_explainer_rankings
                        (stock_id, sector_id, geo_id, regime_tag, investor_majority,
                         lens_family, p_value, explain_power, rank)
                    VALUES (:stock_id, :sector_id, :geo_id, :regime_tag, :investor_majority,
                            :lens_family, :p_value, :explain_power, :rank)
                    ON CONFLICT(stock_id, sector_id, geo_id, regime_tag, investor_majority, lens_family)
                    DO UPDATE SET p_value=excluded.p_value, explain_power=excluded.explain_power,
                                  rank=excluded.rank
                    """,
                    records,
                )
                return len(records)
        except Exception:
            return 0

    def log_lens_activation(
        self, temperature: float, fired_lenses: List[str], context: Optional[Dict[str, Any]] = None
    ) -> int:
        """Audit hook: record a lens-activation run (delegates to ensemble_ranker)."""
        try:
            from reality_engine.processing.ensemble_ranker import EnsembleRanker
            return EnsembleRanker(self.db).log_activation(temperature, list(fired_lenses), context)
        except Exception:
            return -1

    def get_lens_activation_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return lens-activation audit log (delegates to ensemble_ranker)."""
        try:
            from reality_engine.processing.ensemble_ranker import EnsembleRanker
            return EnsembleRanker(self.db).get_activation_log(limit)
        except Exception:
            return []

    def get_per_scrip_noise_floor(self, symbol: str) -> Optional[float]:
        """Return the EOD-learned per-scrip noise floor, or None when not yet learned.

        eod_corrector (Wave D) persists learned floors into the ``noise_floors`` table via
        :meth:`set_per_scrip_noise_floor`. When no learned floor exists callers fall back to
        the deterministic vol/liquidity-adaptive floor in ``composite_screener``.
        """
        self.ensure_eod_corrector_schema()
        try:
            with self.db.session() as conn:
                row = conn.execute(
                    "SELECT floor FROM noise_floors WHERE symbol = ?", (symbol,)
                ).fetchone()
                if row and row["floor"] is not None:
                    return float(row["floor"])
        except Exception:
            pass
        return None

    def set_per_scrip_noise_floor(self, symbol: str, floor: float,
                                  realized_vol: Optional[float] = None,
                                  liquidity: Optional[float] = None,
                                  sample_days: Optional[int] = None) -> None:
        """Persist a learned per-scrip noise floor (Wave D hook).

        Idempotent: re-upserts the floor for ``symbol`` and records the realized-vol /
        liquidity metrics that produced it so the learning is auditable and revisable.
        """
        self.ensure_eod_corrector_schema()
        try:
            with self.db.session() as conn:
                conn.execute(
                    """
                    INSERT INTO noise_floors
                        (symbol, floor, realized_vol, liquidity, sample_days, learned_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(symbol) DO UPDATE SET
                        floor = excluded.floor,
                        realized_vol = excluded.realized_vol,
                        liquidity = excluded.liquidity,
                        sample_days = excluded.sample_days,
                        learned_at = CURRENT_TIMESTAMP
                    """,
                    (symbol, float(floor), realized_vol, liquidity, sample_days),
                )
        except Exception:
            pass

    def get_noise_floors(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Return all learned per-scrip noise floors (newest/alphabetical), [] if none."""
        self.ensure_eod_corrector_schema()
        try:
            with self.db.session() as conn:
                rows = conn.execute(
                    "SELECT * FROM noise_floors ORDER BY symbol ASC LIMIT ?",
                    (int(limit),),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def ensure_eod_corrector_schema(self, manager=None) -> None:
        """Create EOD-corrector support tables (Wave D3, additive).

        * ``noise_floors`` — per-scrip learned noise floor + the realized-vol / liquidity
          metrics that produced it (auditable, revisable).
        * ``eod_correction_log`` — every EOD / event correction batch for audit.
        * Adds ``revision_count`` / ``last_revised_at`` to ``ripple_effects`` so event-driven
          corrections can mark which 2nd-order rows were revised (`correct_event`).

        Idempotent; safe to call repeatedly. Does not touch any other wave's tables.
        """
        mgr = manager or self.db
        self.ensure_ensemble_ranking_schema(mgr)  # rankings are the re-rank target
        _NOISE_DDL = """
        CREATE TABLE IF NOT EXISTS noise_floors (
            symbol TEXT PRIMARY KEY,
            floor REAL NOT NULL,
            realized_vol REAL,
            liquidity REAL,
            sample_days INTEGER,
            learned_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
        _LOG_DDL = """
        CREATE TABLE IF NOT EXISTS eod_correction_log (
            correction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            correction_type TEXT,
            universe TEXT,
            target_date TEXT,
            symbols_corrected INTEGER,
            noise_floors_updated INTEGER,
            lens_rank_changes INTEGER,
            event_id TEXT,
            details_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
        with mgr.session() as conn:
            conn.execute(_NOISE_DDL)
            conn.execute(_LOG_DDL)
            # Revision tracking on the transient-graph ripples (event-driven correction).
            try:
                cols = {r[1] for r in conn.execute("PRAGMA table_info('ripple_effects')").fetchall()}
                if "revision_count" not in cols:
                    conn.execute("ALTER TABLE ripple_effects ADD COLUMN revision_count INTEGER DEFAULT 0")
                if "last_revised_at" not in cols:
                    conn.execute("ALTER TABLE ripple_effects ADD COLUMN last_revised_at TEXT")
            except Exception:
                pass

    def log_eod_correction(self, correction_type: str, universe: Optional[str] = None,
                           target_date: Optional[str] = None, symbols_corrected: int = 0,
                           noise_floors_updated: int = 0, lens_rank_changes: int = 0,
                           event_id: Optional[str] = None, details: Optional[Any] = None,
                           manager=None) -> int:
        """Append an EOD/event correction audit row; returns the new correction_id."""
        self.ensure_eod_corrector_schema(manager or self.db)
        try:
            with (manager or self.db).session() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO eod_correction_log
                        (correction_type, universe, target_date, symbols_corrected,
                         noise_floors_updated, lens_rank_changes, event_id, details_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (correction_type, universe, target_date, symbols_corrected,
                     noise_floors_updated, lens_rank_changes, event_id, self._json_value(details)),
                )
                return int(cur.lastrowid)
        except Exception:
            return -1

    def get_eod_correction_log(self, limit: int = 50, manager=None) -> List[Dict[str, Any]]:
        """Return EOD/event correction audit rows (newest first), [] if none."""
        self.ensure_eod_corrector_schema(manager or self.db)
        try:
            with (manager or self.db).session() as conn:
                rows = conn.execute(
                    "SELECT * FROM eod_correction_log ORDER BY correction_id DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def apply_event_revision(self, event_id: Any, manager=None) -> Dict[str, Any]:
        """Revise the 2nd-order (and deeper) ripple_effects for ``event_id``.

        Recomputes each order_level >= 2 ripple's ``significance_rank`` from the canonical
        causal S = |raw*prob*beta| * 20 / (1 + ln(1 + lag)) formula and stamps
        ``revision_count`` / ``last_revised_at`` so ``correct_event`` produces a durable,
        auditable change to the 2nd-order graph. Returns a summary with the per-row deltas.

        This is the additive event-correction primitive; ``eod_corrector.correct_event``
        calls it after refreshing the graph via ``event_graph``.
        """
        import math

        self.ensure_eod_corrector_schema(manager or self.db)
        mgr = manager or self.db
        n_revised = 0
        rows_out: List[Dict[str, Any]] = []
        with mgr.session() as conn:
            try:
                cols = {r[1] for r in conn.execute("PRAGMA table_info('ripple_effects')").fetchall()}
                has_rev = "revision_count" in cols
            except Exception:
                has_rev = False
            ripples = conn.execute(
                "SELECT ripple_id, raw_magnitude, probability, transmission_elasticity, "
                "lag_time_months, significance_rank, order_level, revision_count "
                "FROM ripple_effects WHERE event_id = ?",
                (event_id,),
            ).fetchall()
            for r in ripples:
                if int(r["order_level"] or 1) < 2:
                    continue
                raw = float(r["raw_magnitude"] or 0.0)
                prob = float(r["probability"] or 0.0)
                beta = float(r["transmission_elasticity"] or 1.0)
                lag = int(r["lag_time_months"] or 0)
                mn = raw * prob * beta
                denom = (1.0 + math.log(1.0 + lag)) if lag > 0 else 1.0
                s = abs(mn) * 20.0 / denom
                prior = float(r["significance_rank"]) if r["significance_rank"] is not None else 0.0
                new_rev = (int(r["revision_count"] or 0) + 1) if has_rev else 1
                if has_rev:
                    conn.execute(
                        "UPDATE ripple_effects SET significance_rank=?, revision_count=?, "
                        "last_revised_at=CURRENT_TIMESTAMP WHERE ripple_id=?",
                        (round(s, 4), new_rev, r["ripple_id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE ripple_effects SET significance_rank=? WHERE ripple_id=?",
                        (round(s, 4), r["ripple_id"]),
                    )
                n_revised += 1
                rows_out.append({
                    "ripple_id": r["ripple_id"],
                    "order_level": int(r["order_level"]),
                    "prior_significance": round(prior, 4),
                    "revised_significance": round(s, 4),
                    "revision_count": new_rev,
                })
        return {"event_id": event_id, "n_revised": n_revised, "rows": rows_out}

    # -------------------------------------------------------------
    # 12. Wave C — Lifecycle: structural-milestone survival + distillation log
    #     (additive helpers only; distinct from prior waves).
    # -------------------------------------------------------------
    def ensure_is_structural_milestone_schema(self, manager=None) -> None:
        """Idempotent migration: add ``is_structural_milestone`` survival flags.

        Wave C: STRUCTURAL_THEORY milestones (profit-jump spotting, cheap-value traps)
        carry ``is_structural_milestone=1`` with half-life INF — permanent priors that are
        never decayed and never pruned. The flag lives on both ``pruning_decay_config``
        (a decay *category* marked permanent) and ``raw_documents`` (a single document
        flagged permanent). PostgreSQL seeds these columns in postgres_schema.sql; this
        helper back-fills them on the SQLite WAL fallback. Safe to call repeatedly.
        """
        mgr = manager or self.db
        with mgr.session() as conn:
            for tbl, col, ddl in (
                ("pruning_decay_config", "is_structural_milestone", "INTEGER DEFAULT 0"),
                ("raw_documents", "is_structural_milestone", "INTEGER DEFAULT 0"),
            ):
                try:
                    exists = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
                    ).fetchone()
                    if not exists:
                        continue
                    cols = {r[1] for r in conn.execute(f"PRAGMA table_info('{tbl}')").fetchall()}
                    if col not in cols:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {ddl}")
                except Exception:
                    # Best-effort; ignore if the backend does not support the ALTER.
                    pass

    def get_distillation_runs(self, limit: int = 10, manager=None) -> List[Dict[str, Any]]:
        """Return the most recent distillation_runs rows (newest first). [] if table absent."""
        mgr = manager or self.db
        with mgr.session() as conn:
            try:
                rows = conn.execute(
                    "SELECT * FROM distillation_runs ORDER BY run_id DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
                return [dict(r) for r in rows]
            except Exception:
                return []

    def get_latest_distillation_run(self, manager=None) -> Optional[Dict[str, Any]]:
        """Return the newest distillation_runs row, or None if none logged yet."""
        runs = self.get_distillation_runs(limit=1, manager=manager)
        return runs[0] if runs else None

    # -------------------------------------------------------------
    # 13. Peer 1 — Factor/Statistical dense substrate (financial_metrics)
    #     Additive helpers ONLY for the factor-statistical peer. Does not
    #     touch moat / policy / ripple tables. Mirrors postgres_schema.sql
    #     financial_metrics (company_id, fiscal_year, roic, wacc,
    #     roic_wacc_spread GENERATED, fcf_margin, debt_to_ebitda,
    #     gross_margin_peer_percentile). SQLite has no GENERATED columns, so
    #     roic_wacc_spread is computed in Python and stored explicitly.
    # -------------------------------------------------------------
    def ensure_financial_metrics_schema(self, manager=None) -> None:
        """Create the financial_metrics dense-substrate table (SQLite fallback) if absent.

        Idempotent. Schema matches the task DDL so the Factor/Statistical peer is
        queryable for ensemble weighting (roic_wacc_spread, fcf_margin, etc.).
        """
        mgr = manager or self.db
        _DDL = """
        CREATE TABLE IF NOT EXISTS financial_metrics (
            company_id INTEGER,
            isin TEXT,
            symbol TEXT,
            fiscal_year INTEGER,
            roic REAL,
            wacc REAL,
            roic_wacc_spread REAL,
            fcf_margin REAL,
            debt_to_ebitda REAL,
            gross_margin_peer_percentile INTEGER,
            PRIMARY KEY(company_id, fiscal_year)
        );
        """
        with mgr.session() as conn:
            conn.execute(_DDL)

    def upsert_financial_metrics(self, records: List[Dict[str, Any]]) -> int:
        """Bulk upsert Factor/Statistical financial_metrics rows (keyed by company_id+fiscal_year)."""
        if not records:
            return 0
        query = """
        INSERT INTO financial_metrics (
            company_id, isin, symbol, fiscal_year, roic, wacc,
            roic_wacc_spread, fcf_margin, debt_to_ebitda, gross_margin_peer_percentile
        ) VALUES (
            :company_id, :isin, :symbol, :fiscal_year, :roic, :wacc,
            :roic_wacc_spread, :fcf_margin, :debt_to_ebitda, :gross_margin_peer_percentile
        )
        ON CONFLICT(company_id, fiscal_year) DO UPDATE SET
            isin = excluded.isin,
            symbol = excluded.symbol,
            roic = excluded.roic,
            wacc = excluded.wacc,
            roic_wacc_spread = excluded.roic_wacc_spread,
            fcf_margin = excluded.fcf_margin,
            debt_to_ebitda = excluded.debt_to_ebitda,
            gross_margin_peer_percentile = excluded.gross_margin_peer_percentile;
        """
        with self.db.session() as conn:
            cursor = conn.executemany(query, records)
            return cursor.rowcount

    def count_financial_metrics(self) -> int:
        """Return the number of financial_metrics rows (Factor/Statistical peer density)."""
        try:
            with self.db.session() as conn:
                row = conn.execute("SELECT COUNT(*) AS n FROM financial_metrics").fetchone()
                return int(row["n"]) if row and row["n"] is not None else 0
        except Exception:
            return 0

    def get_financial_metrics(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return financial_metrics rows, optionally for a single symbol/isin (for ensemble queries)."""
        try:
            with self.db.session() as conn:
                if symbol:
                    rows = conn.execute(
                        "SELECT * FROM financial_metrics WHERE symbol=? OR isin=? ORDER BY fiscal_year DESC",
                        (symbol, symbol),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM financial_metrics ORDER BY symbol ASC, fiscal_year DESC"
                    ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def get_factor_metrics_for_ensemble(self) -> pd.DataFrame:
        """Return all financial_metrics as a DataFrame for ensemble-weight aggregation.

        The Factor/Statistical peer is queryable by roic_wacc_spread / fcf_margin /
        debt_to_ebitda so the all-peers ensemble can weight this lens.
        """
        try:
            with self.db.session() as conn:
                return pd.read_sql_query(
                    "SELECT company_id, isin, symbol, fiscal_year, roic, wacc, "
                    "roic_wacc_spread, fcf_margin, debt_to_ebitda, gross_margin_peer_percentile "
                    "FROM financial_metrics ORDER BY symbol ASC",
                    conn,
                )
        except Exception:
            return pd.DataFrame()

    # -------------------------------------------------------------
    # 13b. Industries canonical table (Wave — top-down funnel layer)
    #      Ensures SQLite fallback mirrors postgres_schema.sql industries DDL.
    # -------------------------------------------------------------
    def ensure_industries_schema(self, conn=None, manager=None):
        """Create industries (SQLite fallback) if absent; align with postgres_schema.sql.

        Idempotent. Mirrors the PG industries table so the top-down funnel layer
        (secular_growth_score, lifecycle_stage, tam_growth_cagr) is queryable.
        Supports both ensure_* manager pattern and direct connection passthrough.
        """
        mgr = manager or self.db
        # If conn looks like a DatabaseManager (has .session), treat as manager override
        if conn is not None and hasattr(conn, "session"):
            mgr = conn
            conn = None
        _DDL = """CREATE TABLE IF NOT EXISTS industries (
        industry_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sector_name TEXT NOT NULL,
        industry_name TEXT NOT NULL UNIQUE,
        secular_growth_score REAL CHECK (secular_growth_score BETWEEN 1 AND 5),
        lifecycle_stage TEXT CHECK (lifecycle_stage IN ('Nascent','Growth','Mature','Declining')),
        tam_growth_cagr REAL)"""
        if conn is not None:
            conn.execute(_DDL)
            return True
        with mgr.session() as conn:
            conn.execute(_DDL)
        return True

    def seed_industries_from_seed_file(self, path=None, manager=None):
        """Seed canonical industries from fundamental_seed.json into the industries table.

        Idempotent via INSERT OR IGNORE. Maps non-conforming lifecycle_stage values to
        the SQLite CHECK constraint (default 'Mature'). Returns row count after seeding.
        """
        import json as _json
        from pathlib import Path as _Path
        p = _Path(path) if path else _Path(__file__).resolve().parent.parent / "data" / "seed" / "fundamental_seed.json"
        self.ensure_industries_schema(manager=manager)
        data = _json.loads(p.read_text(encoding="utf-8"))
        rows = data["industries"] if isinstance(data, dict) else data
        _LIFECYCLE = {"Early Adoption": "Nascent", "Nascent": "Nascent", "Consolidating": "Mature", "Mature": "Mature", "Growth": "Growth", "Declining": "Declining"}
        mgr = manager or self.db
        with mgr.session() as conn:
            for r in rows:
                conn.execute(
                    "INSERT OR IGNORE INTO industries (sector_name, industry_name, secular_growth_score, lifecycle_stage, tam_growth_cagr) VALUES (?,?,?,?,?)",
                    (
                        r.get("sector_name"),
                        r.get("industry_name"),
                        r.get("secular_growth_score"),
                        _LIFECYCLE.get(r.get("lifecycle_stage"), "Mature"),
                        r.get("tam_growth_cagr"),
                    ),
                )
            n = conn.execute("SELECT COUNT(*) FROM industries").fetchone()[0]
        return int(n)


# Singleton repository instance
repo = Repository()
