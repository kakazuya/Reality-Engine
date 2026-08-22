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
            concall_pdf_path, investor_presentation_path, has_concall_transcript
        ) VALUES (
            :isin, :symbol, :quarter_end_date, :financial_year, :revenue_inr_cr,
            :ebitda_inr_cr, :ebitda_margin_pct, :net_profit_inr_cr, :pat_margin_pct,
            :eps_inr, :yoy_revenue_growth_pct, :yoy_pat_growth_pct,
            :qoq_revenue_growth_pct, :qoq_pat_growth_pct, :xbrl_file_path,
            :concall_pdf_path, :investor_presentation_path, :has_concall_transcript
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
            has_concall_transcript = COALESCE(excluded.has_concall_transcript, quarterly_financials.has_concall_transcript);
        """
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
            interest_coverage, operating_cash_flow_inr_cr, free_cash_flow_inr_cr
        ) VALUES (
            :isin, :symbol, :fiscal_year, :revenue_inr_cr, :ebitda_inr_cr,
            :net_profit_inr_cr, :eps_inr, :opm_pct, :npm_pct, :roce_pct,
            :roe_pct, :debt_inr_cr, :equity_inr_cr, :debt_to_equity,
            :interest_coverage, :operating_cash_flow_inr_cr, :free_cash_flow_inr_cr
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
            free_cash_flow_inr_cr = excluded.free_cash_flow_inr_cr;
        """
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

        query = """
        INSERT INTO corporate_documents (
            isin, symbol, doc_type, title, doc_date, source_url,
            local_file_path, file_size_bytes, sha256_hash, is_processed
        ) VALUES (
            :isin, :symbol, :doc_type, :title, :doc_date, :source_url,
            :local_file_path, :file_size_bytes, :sha256_hash, :is_processed
        )
        """
        with self.db.session() as conn:
            cursor = conn.executemany(query, records)
            return cursor.rowcount

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
        query = """
        INSERT INTO macro_events (
            event_id, event_name, category, event_date, raw_document_path,
            summary, affected_nodes_json
        ) VALUES (
            :event_id, :event_name, :category, :event_date, :raw_document_path,
            :summary, :affected_nodes_json
        )
        ON CONFLICT(event_id) DO UPDATE SET
            event_name = excluded.event_name, category = excluded.category,
            event_date = excluded.event_date, raw_document_path = excluded.raw_document_path,
            summary = excluded.summary, affected_nodes_json = excluded.affected_nodes_json
        """
        values = {key: record.get(key) for key in (
            "event_id", "event_name", "category", "event_date", "raw_document_path", "summary"
        )}
        values["affected_nodes_json"] = self._json_value(record.get("affected_nodes_json"))
        with self.db.session() as conn:
            return conn.execute(query, values).rowcount

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


# Singleton repository instance
repo = Repository()
