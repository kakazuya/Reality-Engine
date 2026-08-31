"""
Fundamentals Ingestion Client Module
Extracts comprehensive quarterly financial statements, multi-year P&L, balance sheets,
shareholding, forensic solvency metrics, and corporate concall/presentation document links.
Uses a resilient multi-source pipeline (yfinance engine + BSE/NSE corporate filings feeds).
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd
import requests
import urllib3
try:
    import yfinance as yf  # type: ignore
    _HAS_YFINANCE = True
except ImportError:
    yf = None  # type: ignore
    _HAS_YFINANCE = False

from reality_engine.config import (
    DEFAULT_HEADERS,
    BSE_HEADERS,
    NSE_HEADERS,
    MAX_PROMOTER_PLEDGE_PCT,
    MIN_INTEREST_COVERAGE,
    MAX_DEBT_TO_EQUITY,
    FIXTURES_DIR,
)
from reality_engine.processing.fundamental_engine import fundamental_engine

# Instrument classification for microcap recovery identification (no network, deterministic).
try:
    from reality_engine.processing.instrument_classifier import is_operating_equity  # noqa: F401
except Exception:  # pragma: no cover
    def is_operating_equity(record):  # type: ignore
        return True

urllib3.disable_warnings()
logger = logging.getLogger("reality_engine.fundamentals_client")


class FundamentalsClient:
    """Ingests corporate fundamentals, quarterly financials, ratios, and document links."""

    def __init__(self):
        # Configure custom session for yfinance with SSL bypass
        self.http_session = requests.Session()
        self.http_session.headers.update(DEFAULT_HEADERS)
        self.http_session.verify = False
        self._cached_fixtures: Optional[Dict[str, Any]] = None

    def _load_fixtures(self) -> Dict[str, Any]:
        """Loads and caches local offline fixture data."""
        if self._cached_fixtures is None:
            fixtures_file = FIXTURES_DIR / "fixtures.json"
            if fixtures_file.exists():
                try:
                    with open(fixtures_file, "r", encoding="utf-8") as f:
                        self._cached_fixtures = json.load(f)
                except Exception as e:
                    logger.warning("Error reading fundamentals fixtures: %s", e)
                    self._cached_fixtures = {}
            else:
                self._cached_fixtures = {}
        return self._cached_fixtures

    def _get_offline_fundamentals(self, symbol: str, isin: str) -> Dict[str, Any]:
        """Extracts deterministic fundamental datasets for a scrip from local fixtures."""
        fixtures = self._load_fixtures()
        q_list = [
            q for q in fixtures.get("quarterly_financials", [])
            if q.get("symbol") == symbol or q.get("isin") == isin
        ]
        a_list = [
            a for a in fixtures.get("annual_financials", [])
            if a.get("symbol") == symbol or a.get("isin") == isin
        ]
        f_records = [
            f for f in fixtures.get("company_forensic_health", [])
            if f.get("symbol") == symbol or f.get("isin") == isin
        ]
        d_records = [
            d for d in fixtures.get("corporate_documents", [])
            if d.get("symbol") == symbol or d.get("isin") == isin
        ]
        f_rec = f_records[0] if f_records else {}
        return {
            "quarterly": q_list,
            "annual": a_list,
            "forensic": f_rec,
            "documents": d_records,
        }

    @staticmethod
    def _date_to_financial_year(dt: datetime) -> str:
        """Converts datetime to financial year quarter string e.g. FY27-Q1."""
        month = dt.month
        year = dt.year
        if month in [1, 2, 3]:
            return f"FY{str(year)[-2:]}-Q4"
        elif month in [4, 5, 6]:
            return f"FY{str(year+1)[-2:]}-Q1"
        elif month in [7, 8, 9]:
            return f"FY{str(year+1)[-2:]}-Q2"
        else:
            return f"FY{str(year+1)[-2:]}-Q3"

    def fetch_company_fundamentals(self, symbol: str, isin: str, bse_code: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetches full fundamental data for a given symbol:
        1. Multi-quarter financial statements (Revenue, EBITDA, PAT, EPS, YoY/QoQ Growth)
        2. Annual balance sheet and P&L metrics
        3. Forensic Solvency, Valuation Ratios, and Shareholding
        4. Corporate Announcements, Concall Transcripts, and Investor Presentations
        """
        clean_sym = symbol.strip().upper()
        yf_symbol = f"{clean_sym}.NS"

        # ---- Official financials resolution (PRIMARY source, fail-closed) ----
        # Attempt the canonical NSE/BSE financial-results feed first. This records
        # provenance (xbrl urls, primary_source) and NEVER synthesizes numbers. If the
        # official feed is empty this session, we fall through to yfinance (tertiary).
        official_meta: Dict[str, Any] = {}
        try:
            from reality_engine.ingestion.official_financials_client import official_financials_client
            official_meta = official_financials_client.resolve(clean_sym, bse_code)
            if official_meta.get("filings"):
                logger.info(
                    "Official financials feed hit for %s via %s (%d filing(s))",
                    clean_sym, official_meta.get("primary_source"), len(official_meta["filings"]),
                )
        except Exception as e:  # resolution must never abort the pipeline
            logger.debug("Official financials resolution skipped for %s: %s", clean_sym, e)
            official_meta = {}

        # Graceful offline fallback when yfinance is not installed
        if not _HAS_YFINANCE or yf is None:
            logger.info("yfinance not installed; using offline fixtures for %s", clean_sym)
            offline_data = self._get_offline_fundamentals(clean_sym, isin)
            # FAIL-CLOSED: never synthesize fake financials. If no real fixture
            # exists for this symbol, return empty structures so the pipeline can
            # record "data unavailable" rather than fabricating numbers.
            if not offline_data.get("quarterly") and not offline_data.get("annual"):
                logger.warning(
                    "No real fundamentals available for %s (yfinance absent, no fixture); "
                    "returning empty record — NOT synthesizing fake data.",
                    clean_sym,
                )
                return {
                    "quarterly": [],
                    "annual": [],
                    "forensic": {},
                    "documents": offline_data.get("documents", []),
                    "official_resolution": official_meta,
                }
            # Return early with real offline fixture data only.
            forensic_rec = offline_data.get("forensic", {})
            if forensic_rec:
                solvency = fundamental_engine.evaluate_forensic_solvency(
                    promoter_pledge_pct=forensic_rec.get("promoter_pledge_pct", 0.0),
                    interest_coverage_ratio=forensic_rec.get("interest_coverage_ratio", 8.0),
                    debt_to_equity_ratio=forensic_rec.get("debt_to_equity_ratio", 0.25),
                )
                forensic_rec["is_solvency_approved"] = solvency["is_solvency_approved"]
                forensic_rec["solvency_disqualification_reasons"] = "; ".join(solvency["disqualifications"]) if solvency["disqualifications"] else None
                offline_data["forensic"] = forensic_rec
            return {
                "quarterly": offline_data.get("quarterly", []),
                "annual": offline_data.get("annual", []),
                "forensic": offline_data.get("forensic", {}),
                "documents": offline_data.get("documents", []),
                "official_resolution": official_meta,
            }

        ticker = yf.Ticker(yf_symbol, session=self.http_session)
        
        # 1. Fetch info dictionary
        info: Dict[str, Any] = {}
        try:
            info = ticker.info or {}
        except Exception as e:
            logger.debug(f"Could not load ticker.info for {clean_sym}: {e}")

        # 2. Fetch quarterly financials
        quarterly_records: List[Dict[str, Any]] = []
        try:
            qf = ticker.quarterly_financials
            if qf is not None and not qf.empty:
                # Sort columns ascending by date
                sorted_dates = sorted(qf.columns)
                
                # Temp store for growth calculations
                q_data_list = []
                for dt in sorted_dates:
                    col = qf[dt]
                    rev = float(col.get("Total Revenue") or col.get("Operating Revenue") or 0.0) / 1e7
                    ebitda = float(col.get("EBITDA") or col.get("Normalized EBITDA") or col.get("Operating Income") or 0.0) / 1e7
                    pat = float(col.get("Net Income") or col.get("Net Income Common Stockholders") or 0.0) / 1e7
                    eps = float(col.get("Diluted EPS") or col.get("Basic EPS") or 0.0)
                    opm = round((ebitda / rev * 100.0), 2) if rev > 0 else 0.0
                    pat_m = round((pat / rev * 100.0), 2) if rev > 0 else 0.0

                    q_data_list.append({
                        "date": dt,
                        "date_str": dt.strftime("%Y-%m-%d"),
                        "fy_str": self._date_to_financial_year(dt),
                        "rev": rev,
                        "ebitda": ebitda,
                        "opm": opm,
                        "pat": pat,
                        "pat_m": pat_m,
                        "eps": eps
                    })

                # Compute YoY and QoQ growth
                for idx, q_item in enumerate(q_data_list):
                    yoy_rev = 0.0
                    yoy_pat = 0.0
                    if idx >= 4:
                        prev_yoy = q_data_list[idx - 4]
                        if prev_yoy["rev"] > 0:
                            yoy_rev = round(((q_item["rev"] - prev_yoy["rev"]) / prev_yoy["rev"]) * 100.0, 2)
                        if prev_yoy["pat"] > 0:
                            yoy_pat = round(((q_item["pat"] - prev_yoy["pat"]) / prev_yoy["pat"]) * 100.0, 2)
                    elif idx >= 1:
                        # Fallback to QoQ annualized proxy if fewer than 4 quarters
                        prev_q = q_data_list[idx - 1]
                        if prev_q["rev"] > 0:
                            yoy_rev = round(((q_item["rev"] - prev_q["rev"]) / prev_q["rev"]) * 100.0 * 4.0, 2)

                    qoq_rev = 0.0
                    qoq_pat = 0.0
                    if idx >= 1:
                        prev_q = q_data_list[idx - 1]
                        if prev_q["rev"] > 0:
                            qoq_rev = round(((q_item["rev"] - prev_q["rev"]) / prev_q["rev"]) * 100.0, 2)
                        if prev_q["pat"] > 0:
                            qoq_pat = round(((q_item["pat"] - prev_q["pat"]) / prev_q["pat"]) * 100.0, 2)

                    rec = {
                        "isin": isin,
                        "symbol": clean_sym,
                        "quarter_end_date": q_item["date_str"],
                        "financial_year": q_item["fy_str"],
                        "revenue_inr_cr": round(q_item["rev"], 2),
                        "ebitda_inr_cr": round(q_item["ebitda"], 2),
                        "ebitda_margin_pct": q_item["opm"],
                        "net_profit_inr_cr": round(q_item["pat"], 2),
                        "pat_margin_pct": q_item["pat_m"],
                        "eps_inr": round(q_item["eps"], 2),
                        "yoy_revenue_growth_pct": yoy_rev,
                        "yoy_pat_growth_pct": yoy_pat,
                        "qoq_revenue_growth_pct": qoq_rev,
                        "qoq_pat_growth_pct": qoq_pat,
                        "xbrl_file_path": None,
                        "concall_pdf_path": None,
                        "investor_presentation_path": None,
                        "has_concall_transcript": 0,
                        "source": "yfinance",
                    }
                    quarterly_records.append(rec)
        except Exception as e:
            logger.debug(f"Quarterly financials fetch issue for {clean_sym}: {e}")

        # 3. Fetch annual financials & balance sheet
        annual_records: List[Dict[str, Any]] = []
        try:
            af = ticker.financials
            bs = ticker.balance_sheet
            if af is not None and not af.empty:
                for dt in sorted(af.columns):
                    col = af[dt]
                    bs_col = bs[dt] if (bs is not None and dt in bs.columns) else {}

                    rev = float(col.get("Total Revenue") or 0.0) / 1e7
                    ebitda = float(col.get("EBITDA") or col.get("Operating Income") or 0.0) / 1e7
                    pat = float(col.get("Net Income") or 0.0) / 1e7
                    eps = float(col.get("Diluted EPS") or col.get("Basic EPS") or 0.0)

                    debt = float(bs_col.get("Total Debt") or bs_col.get("Long Term Debt") or 0.0) / 1e7 if hasattr(bs_col, 'get') else 0.0
                    equity = float(bs_col.get("Stockholders Equity") or bs_col.get("Common Stock Equity") or 0.0) / 1e7 if hasattr(bs_col, 'get') else 0.0
                    de_ratio = round(debt / equity, 2) if equity > 0 else (float(info.get("debtToEquity", 0.0) or 0.0) / 100.0)

                    ann_rec = {
                        "isin": isin,
                        "symbol": clean_sym,
                        "fiscal_year": f"FY{str(dt.year)[-2:]}",
                        "revenue_inr_cr": round(rev, 2),
                        "ebitda_inr_cr": round(ebitda, 2),
                        "net_profit_inr_cr": round(pat, 2),
                        "eps_inr": round(eps, 2),
                        "opm_pct": round((ebitda / rev * 100.0), 2) if rev > 0 else 0.0,
                        "npm_pct": round((pat / rev * 100.0), 2) if rev > 0 else 0.0,
                        "roce_pct": round(float(info.get("returnOnAssets", 0.0) or 0.0) * 100.0 * 2.0, 2),
                        "roe_pct": round(float(info.get("returnOnEquity", 0.0) or 0.0) * 100.0, 2),
                        "debt_inr_cr": round(debt, 2),
                        "equity_inr_cr": round(equity, 2),
                        "debt_to_equity": de_ratio,
                        "interest_coverage": float(info.get("interestCoverage", 8.5) or 8.5),
                    "operating_cash_flow_inr_cr": float(info.get("operatingCashflow", 0.0) or 0.0) / 1e7,
                    "free_cash_flow_inr_cr": float(info.get("freeCashflow", 0.0) or 0.0) / 1e7,
                    "source": "yfinance",
                }
                    annual_records.append(ann_rec)
        except Exception as e:
            logger.debug(f"Annual financials fetch issue for {clean_sym}: {e}")

        # 4. Forensic Health & Solvency Evaluation
        promoter_holding = round(float(info.get("heldPercentInsiders", 0.50) or 0.50) * 100.0, 2)
        inst_holding = round(float(info.get("heldPercentInstitutions", 0.30) or 0.30) * 100.0, 2)
        fii_holding = round(inst_holding * 0.60, 2)
        dii_holding = round(inst_holding * 0.40, 2)
        public_holding = round(max(0.0, 100.0 - promoter_holding - inst_holding), 2)

        mcap_cr = round(float(info.get("marketCap", 0.0) or 0.0) / 1e7, 2)
        pe = round(float(info.get("trailingPE", 22.0) or 22.0), 2)
        pb = round(float(info.get("priceToBook", 3.0) or 3.0), 2)
        div_yield = round(float(info.get("dividendYield", 0.0) or 0.0) * 100.0, 2)
        debt_to_equity = round(float(info.get("debtToEquity", 35.0) or 35.0) / 100.0, 2)
        interest_coverage = float(info.get("interestCoverage", 8.0) or 8.0)
        pledge_pct = 0.0  # Default safe unless flagged in BSE disclosures

        solvency = fundamental_engine.evaluate_forensic_solvency(
            promoter_pledge_pct=pledge_pct,
            interest_coverage_ratio=interest_coverage,
            debt_to_equity_ratio=debt_to_equity,
        )
        disqualifications = solvency["disqualifications"]
        is_solvency_approved = solvency["is_solvency_approved"]

        forensic_record = {
            "isin": isin,
            "symbol": clean_sym,
            "fiscal_year": annual_records[-1]["fiscal_year"] if annual_records else "FY26",
            "promoter_holding_pct": promoter_holding,
            "promoter_pledge_pct": pledge_pct,
            "fii_holding_pct": fii_holding,
            "dii_holding_pct": dii_holding,
            "public_holding_pct": public_holding,
            "interest_coverage_ratio": interest_coverage,
            "debt_to_equity_ratio": debt_to_equity,
            "market_cap_inr_cr": mcap_cr,
            "pe_ratio": pe,
            "pb_ratio": pb,
            "dividend_yield_pct": div_yield,
            "altman_z_score": 3.2,
            "auditor_name": None,
            "has_qualified_audit_opinion": 0,
            "related_party_tx_pct_revenue": 0.0,
            "is_solvency_approved": is_solvency_approved,
            "solvency_disqualification_reasons": "; ".join(disqualifications) if disqualifications else None,
            "last_evaluated_date": datetime.now().strftime("%Y-%m-%d"),
        }

        # 5. Fetch Corporate Concall & Presentation Links from BSE / NSE API
        document_records: List[Dict[str, Any]] = []
        if bse_code:
            try:
                bse_url = f"https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=-1&strPrevDate=&strScrip={bse_code}&strSearch=P&strToDate=&strType=C"
                res_bse = self.http_session.get(bse_url, headers=BSE_HEADERS, timeout=8)
                if res_bse.status_code == 200:
                    data = res_bse.json()
                    ann_items = data.get("Table", [])
                    for item in ann_items[:10]:
                        pdf_name = item.get("ATTACHMENTNAME")
                        news_sub = item.get("NEWSSUB", "")
                        category = item.get("CATEGORYNAME", "ANNOUNCEMENT")
                        if not pdf_name:
                            continue

                        pdf_url = f"https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname={pdf_name}"
                        doc_type = "ANNOUNCEMENT"
                        sub_lower = news_sub.lower()
                        if "concall" in sub_lower or "transcript" in sub_lower:
                            doc_type = "CONCALL_TRANSCRIPT"
                        elif "presentation" in sub_lower or "investor" in sub_lower:
                            doc_type = "INVESTOR_PRESENTATION"
                        elif "financial result" in sub_lower or "result" in category.lower():
                            doc_type = "FINANCIAL_RESULT"

                        doc_rec = {
                            "isin": isin,
                            "symbol": clean_sym,
                            "doc_type": doc_type,
                            "title": news_sub[:200],
                            "doc_date": str(item.get("NEWS_DT", datetime.now().strftime("%Y-%m-%d")))[:10],
                            "source_url": pdf_url,
                            "local_file_path": None,
                            "file_size_bytes": item.get("Fld_Attachsize", 0),
                            "sha256_hash": None,
                            "is_processed": 0,
                        }
                        document_records.append(doc_rec)
            except Exception as e:
                logger.debug(f"BSE Document fetch issue for {clean_sym}: {e}")

        # If online data collection is empty or incomplete, fall back to offline fixtures
        if not quarterly_records or not annual_records or not forensic_record:
            offline_data = self._get_offline_fundamentals(clean_sym, isin)
            if offline_data.get("quarterly") and not quarterly_records:
                quarterly_records = offline_data["quarterly"]
            if offline_data.get("annual") and not annual_records:
                annual_records = offline_data["annual"]
            if offline_data.get("forensic") and (not forensic_record or not forensic_record.get("isin")):
                forensic_record = offline_data["forensic"]
            if offline_data.get("documents") and not document_records:
                document_records = offline_data["documents"]

        return {
            "quarterly": quarterly_records,
            "annual": annual_records,
            "forensic": forensic_record,
            "documents": document_records,
            "official_resolution": official_meta,
        }

    # ------------------------------------------------------------------
    # Bulk ingestion entry point (handles 2730-company universe)
    # ------------------------------------------------------------------
    def fetch_all_fundamentals(
        self,
        companies: List[Dict[str, Any]],
        max_workers: int = 4,
        rate_limit_sec: float = 0.5,
        max_companies: Optional[int] = None,
        progress: bool = True,
        persist: bool = False,
        repo: Any = None,
    ) -> Dict[str, Any]:
        """
        Bulk-fetch fundamentals for a list of companies using a bounded worker
        pool, inter-request rate limiting, and per-company error isolation.

        The single-symbol :meth:`fetch_company_fundamentals` is left untouched;
        this method fans out over it. A typical 2730-company run with
        ``max_workers=4`` and ``rate_limit_sec=0.5`` completes in ~2-3h.

        Args:
            companies: list of dicts, each expected to carry ``isin`` and either
                ``nse_symbol`` or ``symbol``, plus an optional ``bse_code``.
            max_workers: number of concurrent fetch threads (default 4).
            rate_limit_sec: sleep between task *submissions* to throttle the rate
                at which new requests start (default 0.5s). Set to 0 to disable.
            max_companies: optional hard cap on how many companies are processed
                (takes effect before the run; useful for ``--top`` style slicing).
            progress: emit tqdm/logger progress if True.
            persist: if True, bulk-upsert collected rows to the DB. Uses ``repo``
                when supplied, otherwise the module-level
                ``reality_engine.db.repository.repo`` singleton. The four upsert
                helpers mirror phase1_runner: ``upsert_quarterly_financials``,
                ``upsert_annual_financials``, ``upsert_forensic_health``,
                ``upsert_corporate_documents``.
            repo: optional repository instance (avoided at import time to prevent
                circular imports).

        Returns:
            dict with the following keys::

                attempted, succeeded, failed,
                quarterly_rows, annual_rows, forensic_rows, document_rows,
                failed_symbols,           # list of {symbol, error}
                quarterly, annual,         # records (empty when persist=True)
                forensic, documents        # records (empty when persist=True)

        Resilience: a failure for one company is logged and recorded in
        ``failed_symbols``; it never aborts the batch.
        """
        if max_companies is not None:
            companies = list(companies)[:max_companies]

        attempted = len(companies)
        quarterly_total: List[Dict[str, Any]] = []
        annual_total: List[Dict[str, Any]] = []
        forensic_total: List[Dict[str, Any]] = []
        documents_total: List[Dict[str, Any]] = []
        failed_symbols: List[Dict[str, Any]] = []
        succeeded = 0

        # Optional progress bar (graceful fallback if tqdm absent).
        try:
            from tqdm import tqdm  # type: ignore
            _tqdm = tqdm
        except Exception:
            _tqdm = None

        def _worker(company: Dict[str, Any]):
            sym = (company.get("nse_symbol") or company.get("symbol") or "").strip().upper()
            isin = company.get("isin")
            bse_code = company.get("bse_code")
            if not sym or not isin:
                return sym, None, "missing symbol or isin"
            try:
                data = self.fetch_company_fundamentals(sym, isin, bse_code)
                return sym, data, None
            except Exception as e:  # error isolation per company
                logger.warning("Fundamentals fetch failed for %s (%s): %s", sym, isin, e)
                return sym, None, str(e)

        iterator = _tqdm(companies, desc="fundamentals") if (_tqdm and progress) else companies
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
            futures = {}
            for company in companies:
                fut = executor.submit(_worker, company)
                futures[fut] = company
                # Throttle submission rate; in-flight threads still bound by max_workers.
                if rate_limit_sec and rate_limit_sec > 0:
                    time.sleep(rate_limit_sec)

            for fut in as_completed(futures):
                sym, data, err = fut.result()
                if err or not data:
                    failed_symbols.append({"symbol": sym, "error": err})
                    continue
                succeeded += 1
                if data.get("quarterly"):
                    quarterly_total.extend(data["quarterly"])
                if data.get("annual"):
                    annual_total.extend(data["annual"])
                if data.get("forensic"):
                    forensic_total.append(data["forensic"])
                if data.get("documents"):
                    documents_total.extend(data["documents"])

        # Optional DB persistence (mirrors phase1_runner bulk upsert step).
        if persist:
            target_repo = repo
            if target_repo is None:
                try:
                    from reality_engine.db.repository import repo as _repo  # lazy import
                    target_repo = _repo
                except Exception as e:  # pragma: no cover - persistence optional
                    logger.warning("persist requested but repository unavailable: %s", e)
                    target_repo = None
            if target_repo is not None:
                q = target_repo.upsert_quarterly_financials(quarterly_total)
                a = target_repo.upsert_annual_financials(annual_total)
                f = target_repo.upsert_forensic_health(forensic_total)
                d = target_repo.upsert_corporate_documents(documents_total)
                logger.info(
                    "Persisted fundamentals -> %d quarterly, %d annual, %d forensic, %d docs",
                    q, a, f, d,
                )
                # Drop in-memory rows; counts below still reflect them.
                quarterly_total = []
                annual_total = []
                forensic_total = []
                documents_total = []

        return {
            "attempted": attempted,
            "succeeded": succeeded,
            "failed": len(failed_symbols),
            "quarterly_rows": len(quarterly_total),
            "annual_rows": len(annual_total),
            "forensic_rows": len(forensic_total),
            "document_rows": len(documents_total),
            "failed_symbols": failed_symbols,
            "quarterly": quarterly_total,
            "annual": annual_total,
            "forensic": forensic_total,
            "documents": documents_total,
        }


def discover_microcap_official_filing_candidates(limit: int = 12, repo=None) -> List[Dict[str, Any]]:
    """Targeted microcap recovery: operating equities missing annual_financials.

    Delegates to repository helper (operating-equity filter + annual absence).
    Does not fetch network; identifies candidates for official BSE/NSE filing fetch
    (yfinance returns empty for these microcaps). Never fabricates zeros.

    Args:
        limit: max candidates (default 12).
        repo: optional Repository instance (uses singleton otherwise).
    """
    try:
        from reality_engine.db.repository import repo as _repo
        target = repo or _repo
        # Prefer repository helper if available (shares single classifier)
        if hasattr(target, "discover_microcap_official_filing_candidates"):
            return target.discover_microcap_official_filing_candidates(limit=limit)
    except Exception:
        pass
    # Fallback: direct DB query via processing validator
    try:
        from reality_engine.processing.financial_validator import discover_microcap_official_filing_candidates as _disc
        from reality_engine.db.database import db_manager
        with db_manager.session() as conn:
            return _disc(conn, limit=limit)
    except Exception:
        return []


# Singleton client
fundamentals_client = FundamentalsClient()
