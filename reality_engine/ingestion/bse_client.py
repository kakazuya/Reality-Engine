"""
BSE Ingestion Client Module
Handles downloading and parsing of BSE Scrip Master, BSE Bhavcopy, and Corporate Disclosures.
"""

import io
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
import pandas as pd
try:
    from curl_cffi import requests as _curl_requests  # type: ignore
    _HAS_CURL_CFFI = True
except ImportError:
    import requests as _curl_requests  # type: ignore
    _HAS_CURL_CFFI = False
import urllib3

from reality_engine.config import (
    BSE_HEADERS,
    BSE_SCRIP_LIST_URL,
    BSE_BHAVCOPY_URL_TEMPLATE,
    BSE_ANNOUNCEMENTS_URL_TEMPLATE,
    BHAVCOPY_DIR
)

urllib3.disable_warnings()
logger = logging.getLogger("reality_engine.bse_client")


class BSEClient:
    """Client for fetching BSE official equity master and bhavcopy files."""

    def __init__(self):
        if _HAS_CURL_CFFI:
            self.session = _curl_requests.Session(impersonate="chrome120", verify=False)  # type: ignore[call-arg]
        else:
            self.session = _curl_requests.Session()
            try:
                self.session.verify = False  # type: ignore[attr-defined]
            except Exception:
                pass
        self._warmed_up = False

    def _warmup_session(self):
        if not self._warmed_up:
            try:
                self.session.get("https://www.bseindia.com", headers=BSE_HEADERS, timeout=10)
                self._warmed_up = True
            except Exception as e:
                logger.warning(f"BSE Session warmup note: {e}")

    def fetch_scrip_master(self) -> pd.DataFrame:
        """Fetches the official BSE Active Equity Scrip list."""
        self._warmup_session()
        logger.info("Fetching BSE Scrip Master from %s", BSE_SCRIP_LIST_URL)
        res = self.session.get(BSE_SCRIP_LIST_URL, headers=BSE_HEADERS, timeout=20)
        if res.status_code != 200:
            raise RuntimeError(f"Failed to fetch BSE Scrip Master: HTTP {res.status_code}")

        try:
            data = res.json()
        except Exception as e:
            raise RuntimeError(f"Failed to parse BSE Scrip Master JSON: {e}")

        df = pd.DataFrame(data)
        if df.empty:
            return df

        # Clean columns and strings
        df.columns = df.columns.str.strip()
        for col in df.select_dtypes(include="object").columns:
            df[col] = df[col].astype(str).str.strip()

        # Rename standard columns
        rename_map = {
            "SCRIP_CD": "bse_code",
            "Scrip_Name": "bse_name",
            "ISIN_NUMBER": "isin",
            "scrip_id": "bse_symbol",
            "GROUP": "bse_group",
            "Mktcap": "bse_mktcap_cr"
        }
        df = df.rename(columns=rename_map)
        logger.info("Loaded %d active BSE equity records", len(df))
        return df

    def fetch_bhavcopy(self, target_date: datetime) -> Optional[pd.DataFrame]:
        """Fetches the daily BSE Bhavcopy CSV."""
        self._warmup_session()
        date_str = target_date.strftime("%Y%m%d")
        url = BSE_BHAVCOPY_URL_TEMPLATE.format(date_str=date_str)
        local_file = BHAVCOPY_DIR / f"BhavCopy_BSE_{date_str}.csv"

        if local_file.exists() and local_file.stat().st_size > 1000:
            logger.info("Loading cached BSE Bhavcopy from %s", local_file)
            return pd.read_csv(local_file)

        logger.info("Downloading BSE Bhavcopy for %s", target_date.strftime('%Y-%m-%d'))
        res = self.session.get(url, headers=BSE_HEADERS, timeout=20)
        if res.status_code != 200:
            logger.warning("BSE Bhavcopy for %s not found (HTTP %d)", date_str, res.status_code)
            return None

        with open(local_file, "w", encoding="utf-8") as f:
            f.write(res.text)

        df = pd.read_csv(io.StringIO(res.text))
        df.columns = df.columns.str.strip()
        return df

    def fetch_corporate_announcements(self, scrip_code: str = "", category: str = "Result",
                                     from_date: str = "", to_date: str = "") -> List[Dict[str, Any]]:
        """Fetches corporate announcements for a scrip."""
        self._warmup_session()
        params = {
            "scrip_code": scrip_code,
            "category": category,
            "from_date": from_date or datetime.now().strftime("%Y%m%d"),
            "to_date": to_date or datetime.now().strftime("%Y%m%d")
        }
        try:
            res = self.session.get(BSE_ANNOUNCEMENTS_URL_TEMPLATE, params=params, headers=BSE_HEADERS, timeout=15)
            if res.status_code == 200:
                data = res.json()
                return data if isinstance(data, list) else data.get("Table", [])
            return []
        except Exception as e:
            logger.error(f"Error fetching BSE announcements for {scrip_code}: {e}")
            return []


# Singleton client
bse_client = BSEClient()
