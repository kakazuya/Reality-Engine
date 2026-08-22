"""
FinanciallyFree Market Breadth Ingestion Client Module (Layer 3)
Extracts sector advance/decline breadth, sector momentum, and market strength
using authenticated Playwright persistent browser sessions, with automated fallback
to official NSE index breadth datasets.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import pandas as pd

# Safe dynamic import for Playwright
try:
    import playwright
    from playwright.async_api import async_playwright, BrowserContext, Page, Response
    PLAYWRIGHT_INSTALLED = True
except (ImportError, Exception):
    playwright = None
    async_playwright = None
    BrowserContext = None
    Page = None
    Response = None
    PLAYWRIGHT_INSTALLED = False

from reality_engine.config import DATA_DIR, BROWSER_PROFILE_DIR, FINANCIALLY_FREE_BASE_URL
from reality_engine.db.database import db_manager, DatabaseManager
from reality_engine.db.repository import repo, Repository
from reality_engine.ingestion.nse_client import NSEClient

logger = logging.getLogger("reality_engine.financially_free_client")


class FinanciallyFreeClient:
    """
    Scrapes authenticated market overview and sector advance/decline ratios from
    FinanciallyFree portal using a persistent browser profile, with automatic fallback
    to local SQLite / NSE index breadth data.
    """

    def __init__(
        self,
        browser_profile_dir: Optional[Union[str, Path]] = None,
        base_url: str = FINANCIALLY_FREE_BASE_URL,
        headless: bool = True,
        timeout_ms: int = 15000,
        db: Optional[DatabaseManager] = None,
        repository: Optional[Repository] = None,
        nse_client: Optional[NSEClient] = None,
        mock_mode: bool = False,
        mock_data: Optional[Dict[str, Any]] = None,
    ):
        self.browser_profile_dir = Path(browser_profile_dir or BROWSER_PROFILE_DIR)
        self.base_url = base_url
        self.headless = headless
        self.timeout_ms = timeout_ms

        self.db = db or db_manager
        self.repo = repository or repo
        self._nse_client = nse_client

        self.mock_mode = mock_mode
        self.mock_data = mock_data

    @property
    def nse_client(self) -> NSEClient:
        """Lazy instantiated NSEClient."""
        if self._nse_client is None:
            self._nse_client = NSEClient()
        return self._nse_client

    def is_available(self) -> bool:
        """
        Checks if Playwright is installed and a persistent browser profile exists.
        In mock_mode, returns True.
        """
        if self.mock_mode:
            return True
        if not PLAYWRIGHT_INSTALLED:
            return False
        if not self.browser_profile_dir.exists():
            return False
        # Profile directory must contain session files / subdirectories
        try:
            return any(self.browser_profile_dir.iterdir())
        except (OSError, PermissionError):
            return False

    # -----------------------------------------------------------------
    # 1. Primary Market Overview Ingestion
    # -----------------------------------------------------------------
    def fetch_market_overview(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Synchronous entry point to fetch market overview data.
        1. Checks mock_mode / mock_data.
        2. If available, executes headless Playwright scraping session.
        3. If unavailable, unauthenticated, or on error, falls back automatically to official NSE index breadth.
        """
        if self.mock_mode and self.mock_data is not None:
            return self._process_overview_payload(self.mock_data, target_date=target_date, source="mock_portal")

        if not self.is_available():
            logger.info("FinanciallyFreeClient: Playwright or browser profile unavailable. Falling back to NSE breadth.")
            return self._fetch_nse_index_breadth_fallback(target_date)

        # Run async scraper via event loop
        try:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        return pool.submit(lambda: asyncio.run(self.fetch_market_overview_async(target_date))).result()
                else:
                    return loop.run_until_complete(self.fetch_market_overview_async(target_date))
            except RuntimeError:
                return asyncio.run(self.fetch_market_overview_async(target_date))
        except Exception as exc:
            logger.warning("Error running Playwright session (%s). Falling back to official NSE index breadth.", exc)
            return self._fetch_nse_index_breadth_fallback(target_date)

    async def fetch_market_overview_async(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Asynchronous Playwright session executing headless browser extraction.
        Captures JSON XHR payloads and DOM tables.
        """
        if self.mock_mode and self.mock_data is not None:
            return self._process_overview_payload(self.mock_data, target_date=target_date, source="mock_portal")

        if not self.is_available() or async_playwright is None:
            return self._fetch_nse_index_breadth_fallback(target_date)

        logger.info("Launching Playwright persistent browser context from %s...", self.browser_profile_dir)
        async with async_playwright() as p:
            try:
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=str(self.browser_profile_dir),
                    headless=self.headless,
                    viewport={"width": 1920, "height": 1080},
                    timeout=self.timeout_ms
                )
            except Exception as launch_exc:
                logger.warning("Failed to launch Playwright persistent context: %s. Falling back to NSE.", launch_exc)
                return self._fetch_nse_index_breadth_fallback(target_date)

            try:
                page = await context.new_page()
                captured_json: Dict[str, Any] = {}

                # Intercept XHR / API responses
                async def on_response(response: Any):
                    try:
                        ct = response.headers.get("content-type", "")
                        if "json" in ct and any(k in response.url for k in ["api", "market", "breadth", "sector", "overview"]):
                            captured_json[response.url] = await response.json()
                    except Exception:
                        pass

                page.on("response", on_response)

                try:
                    await page.goto(self.base_url, wait_until="networkidle", timeout=self.timeout_ms)
                except Exception as nav_exc:
                    logger.warning("Page navigation note on %s: %s", self.base_url, nav_exc)

                # Check if session redirected to OAuth / login screen
                current_url = page.url.lower()
                if any(x in current_url for x in ["login", "signin", "auth", "accounts.google"]):
                    logger.warning("FinanciallyFree session expired (redirected to %s). Profile needs re-authentication.", current_url)
                    return self._fetch_nse_index_breadth_fallback(target_date)

                # If backend API response captured, parse it
                for url, payload in captured_json.items():
                    overview = self.parse_market_overview_json(payload, target_date)
                    if overview.get("sectors"):
                        self._save_breadth_records(overview["sectors"], overview["date"])
                        return overview

                # Otherwise extract DOM HTML tables
                html_content = await page.content()
                dom_overview = self.parse_market_overview_html(html_content, target_date)
                if dom_overview.get("sectors"):
                    self._save_breadth_records(dom_overview["sectors"], dom_overview["date"])
                    return dom_overview

                # Fallback to local / NSE index breadth if portal didn't yield structured tables
                logger.warning("No structured sector data found on FinanciallyFree page. Falling back to NSE.")
                return self._fetch_nse_index_breadth_fallback(target_date)
            finally:
                await context.close()

    # -----------------------------------------------------------------
    # 2. Parsing Helpers (HTML DOM & API JSON)
    # -----------------------------------------------------------------
    def parse_market_overview_html(self, html_str: str, target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Parses rendered HTML DOM tables for sector advance/decline metrics and momentum scores.
        """
        date_str = target_date or datetime.now().strftime("%Y-%m-%d")
        sectors: List[Dict[str, Any]] = []

        # Find table rows via regex
        row_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
        cell_pattern = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
        clean_tag_pattern = re.compile(r"<[^>]+>")

        rows = row_pattern.findall(html_str)
        for row in rows:
            # Skip pure header rows without td tags
            if "<th" in row.lower() and "<td" not in row.lower():
                continue

            raw_cells = cell_pattern.findall(row)
            cells = [clean_tag_pattern.sub("", c).strip() for c in raw_cells]
            if len(cells) >= 3:
                name = cells[0].strip()
                # Skip header cell values
                if name.upper() in ["SECTOR", "SECTOR NAME", "INDEX", "INDEX NAME", "NAME", "PARTICULARS"]:
                    continue
                if cells[1].upper().strip() in ["ADVANCES", "ADV", "GAINERS", "A"]:
                    continue

                if any(kw in name.upper() for kw in ["NIFTY", "SECTOR", "BANK", "AUTO", "IT", "PHARMA", "FMCG", "METAL", "REALTY", "ENERGY", "MEDIA", "FIN"]):
                    try:
                        # Extract numbers
                        adv = int(re.sub(r"[^\d]", "", cells[1]) or 0)
                        dec = int(re.sub(r"[^\d]", "", cells[2]) or 0)
                        ratio = round(adv / max(1, dec), 2)
                        
                        # Momentum or change % if available in cell 3/4
                        momentum = 0.0
                        if len(cells) >= 4:
                            mom_match = re.search(r"[-+]?\d*\.?\d+", cells[3])
                            if mom_match:
                                momentum = float(mom_match.group(0))

                        sectors.append({
                            "sector_name": name,
                            "advances_count": adv,
                            "declines_count": dec,
                            "advance_decline_ratio": ratio,
                            "sector_momentum_score": momentum,
                            "top_gainers": [],
                            "top_losers": [],
                        })
                    except (ValueError, IndexError):
                        continue

        return self._process_overview_payload({"sectors": sectors}, target_date=date_str, source="financially_free_dom")

    def parse_market_overview_json(self, payload: Dict[str, Any], target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Parses JSON response payload intercepted from FinanciallyFree backend.
        """
        date_str = target_date or payload.get("date") or datetime.now().strftime("%Y-%m-%d")
        items = payload.get("sectors") or payload.get("data") or []
        if isinstance(items, dict):
            items = list(items.values())

        sectors: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("sector") or item.get("name") or item.get("sector_name") or ""
            if not name:
                continue
            adv = int(item.get("advances") or item.get("advances_count") or 0)
            dec = int(item.get("declines") or item.get("declines_count") or 0)
            ratio = float(item.get("ad_ratio") or item.get("advance_decline_ratio") or round(adv / max(1, dec), 2))
            mom = float(item.get("momentum") or item.get("sector_momentum_score") or item.get("change_pct") or 0.0)

            sectors.append({
                "sector_name": name,
                "advances_count": adv,
                "declines_count": dec,
                "advance_decline_ratio": ratio,
                "sector_momentum_score": mom,
                "top_gainers": item.get("top_gainers", []),
                "top_losers": item.get("top_losers", []),
            })

        return self._process_overview_payload({
            "sectors": sectors,
            "market_breadth": payload.get("market_breadth"),
            "top_gainers": payload.get("top_gainers"),
            "top_losers": payload.get("top_losers")
        }, target_date=date_str, source="financially_free_api")

    def _process_overview_payload(self, data: Dict[str, Any], target_date: Optional[str] = None, source: str = "financially_free") -> Dict[str, Any]:
        """
        Normalizes sector lists, computes market breadth totals and market regime.
        """
        date_str = target_date or data.get("date") or datetime.now().strftime("%Y-%m-%d")
        sectors: List[Dict[str, Any]] = data.get("sectors", [])

        total_adv = sum(s.get("advances_count", 0) for s in sectors)
        total_dec = sum(s.get("declines_count", 0) for s in sectors)
        overall_ad_ratio = round(total_adv / max(1, total_dec), 2) if (total_adv or total_dec) else 1.0

        if overall_ad_ratio >= 1.5:
            market_regime = "BULLISH"
        elif overall_ad_ratio >= 1.05:
            market_regime = "ACCUMULATION"
        elif 0.80 <= overall_ad_ratio < 1.05:
            market_regime = "NEUTRAL"
        elif 0.50 <= overall_ad_ratio < 0.80:
            market_regime = "DISTRIBUTION"
        else:
            market_regime = "VOLATILE"

        mb = data.get("market_breadth") or {
            "advances": total_adv,
            "declines": total_dec,
            "unchanged": 0,
            "total_stocks": total_adv + total_dec,
            "advance_decline_ratio": overall_ad_ratio,
            "market_regime": market_regime,
        }

        # Sort sectors by momentum
        sorted_sectors = sorted(sectors, key=lambda x: x.get("sector_momentum_score", 0.0) or 0.0, reverse=True)

        return {
            "date": date_str,
            "source": source,
            "status": "success",
            "market_breadth": mb,
            "sectors": sorted_sectors,
            "top_gainers": data.get("top_gainers", []),
            "top_losers": data.get("top_losers", []),
        }

    # -----------------------------------------------------------------
    # 3. Automatic NSE Index Breadth Fallback Engine
    # -----------------------------------------------------------------
    def _fetch_nse_index_breadth_fallback(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Fallback calculation pulling from official `nse_index_breadth` and `daily_price_delivery`.
        Aggregates advances, declines, momentum, and top gainers/losers by sector.
        """
        # Resolve target date
        dt = target_date
        if not dt:
            dt = self.repo.get_latest_price_delivery_date()
        if not dt:
            dt = datetime.now().strftime("%Y-%m-%d")

        logger.info("Executing NSE Index Breadth fallback aggregation for date: %s", dt)

        # 1. Query overall price action from daily_price_delivery joined with master_companies
        delivery_rows: List[Dict[str, Any]] = []
        with self.db.session() as conn:
            rows = conn.execute(
                """
                SELECT p.symbol, p.isin, p.change_pct, p.turnover_lacs, p.delivery_spike_ratio,
                       p.delivery_conviction_score, m.sector, m.industry, m.market_cap_tier,
                       m.is_nifty50, m.is_nifty100, m.is_nifty200
                FROM daily_price_delivery p
                JOIN master_companies m ON p.isin = m.isin
                WHERE p.date = ? AND p.series IN ('EQ', 'BE')
                """,
                (dt,)
            ).fetchall()
            delivery_rows = [dict(r) for r in rows]

        # 2. Query official nse_index_breadth table for standard index benchmarks
        index_benchmarks: List[Dict[str, Any]] = []
        with self.db.session() as conn:
            idx_rows = conn.execute(
                """
                SELECT index_name, open, high, low, close, change_pct,
                       advances_count, declines_count, advance_decline_ratio
                FROM nse_index_breadth
                WHERE date = ?
                ORDER BY change_pct DESC
                """,
                (dt,)
            ).fetchall()
            index_benchmarks = [dict(r) for r in idx_rows]

        # If no price delivery rows found, construct response from index_benchmarks or return empty structure
        if not delivery_rows:
            sectors_from_idx = []
            for b in index_benchmarks:
                sectors_from_idx.append({
                    "sector_name": b["index_name"],
                    "advances_count": b.get("advances_count", 0),
                    "declines_count": b.get("declines_count", 0),
                    "advance_decline_ratio": b.get("advance_decline_ratio", 1.0),
                    "sector_momentum_score": b.get("change_pct", 0.0),
                    "top_gainers": [],
                    "top_losers": [],
                })
            return self._process_overview_payload({
                "date": dt,
                "sectors": sectors_from_idx,
            }, target_date=dt, source="nse_index_breadth_fallback")

        # Compute overall market metrics
        total_advances = sum(1 for r in delivery_rows if r["change_pct"] > 0)
        total_declines = sum(1 for r in delivery_rows if r["change_pct"] < 0)
        total_unchanged = sum(1 for r in delivery_rows if r["change_pct"] == 0)
        total_stocks = len(delivery_rows)
        ad_ratio = round(total_advances / max(1, total_declines), 2)

        if ad_ratio >= 1.5:
            market_regime = "BULLISH"
        elif ad_ratio >= 1.05:
            market_regime = "ACCUMULATION"
        elif 0.80 <= ad_ratio < 1.05:
            market_regime = "NEUTRAL"
        elif 0.50 <= ad_ratio < 0.80:
            market_regime = "DISTRIBUTION"
        else:
            market_regime = "VOLATILE"

        # Group by sector
        sector_groups: Dict[str, List[Dict[str, Any]]] = {}
        for row in delivery_rows:
            sec_name = row.get("sector") or row.get("industry") or "General"
            if sec_name not in sector_groups:
                sector_groups[sec_name] = []
            sector_groups[sec_name].append(row)

        sector_records: List[Dict[str, Any]] = []
        for sec_name, scrips in sector_groups.items():
            s_adv = sum(1 for s in scrips if s["change_pct"] > 0)
            s_dec = sum(1 for s in scrips if s["change_pct"] < 0)
            s_ratio = round(s_adv / max(1, s_dec), 2)
            s_mom = round(sum(s["change_pct"] for s in scrips) / max(1, len(scrips)), 2)
            
            top_g = [{"symbol": s["symbol"], "change_pct": s["change_pct"]} for s in sorted(scrips, key=lambda x: x["change_pct"], reverse=True)[:5]]
            top_l = [{"symbol": s["symbol"], "change_pct": s["change_pct"]} for s in sorted(scrips, key=lambda x: x["change_pct"])[:5]]

            sector_records.append({
                "sector_name": sec_name,
                "advances_count": s_adv,
                "declines_count": s_dec,
                "advance_decline_ratio": s_ratio,
                "sector_momentum_score": s_mom,
                "top_gainers": top_g,
                "top_losers": top_l,
            })

        # Save to financially_free_breadth table
        self._save_breadth_records(sector_records, dt)

        # Top gainers and losers across the market
        overall_top_gainers = [{"symbol": s["symbol"], "change_pct": s["change_pct"]} for s in sorted(delivery_rows, key=lambda x: x["change_pct"], reverse=True)[:10]]
        overall_top_losers = [{"symbol": s["symbol"], "change_pct": s["change_pct"]} for s in sorted(delivery_rows, key=lambda x: x["change_pct"])[:10]]

        overview = {
            "date": dt,
            "source": "nse_index_breadth_fallback",
            "status": "success",
            "market_breadth": {
                "advances": total_advances,
                "declines": total_declines,
                "unchanged": total_unchanged,
                "total_stocks": total_stocks,
                "advance_decline_ratio": ad_ratio,
                "market_regime": market_regime,
            },
            "sectors": sorted(sector_records, key=lambda x: x["sector_momentum_score"], reverse=True),
            "top_gainers": overall_top_gainers,
            "top_losers": overall_top_losers,
        }

        return overview

    def _save_breadth_records(self, sectors: List[Dict[str, Any]], date_str: str) -> int:
        """Saves parsed sector records to financially_free_breadth table."""
        if not sectors:
            return 0
        records = []
        for s in sectors:
            records.append({
                "date": date_str,
                "sector_name": s.get("sector_name", "UNKNOWN"),
                "advances_count": s.get("advances_count", 0),
                "declines_count": s.get("declines_count", 0),
                "advance_decline_ratio": s.get("advance_decline_ratio", 1.0),
                "sector_momentum_score": s.get("sector_momentum_score", 0.0),
                "top_gainers_json": json.dumps(s.get("top_gainers", [])),
                "top_losers_json": json.dumps(s.get("top_losers", [])),
            })
        try:
            return self.repo.upsert_financially_free_breadth(records)
        except Exception as exc:
            logger.warning("Error persisting financially_free_breadth records: %s", exc)
            return 0


# Global default instance
financially_free_client = FinanciallyFreeClient()
