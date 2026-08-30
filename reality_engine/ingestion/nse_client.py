"""
NSE Ingestion Client Module
Handles downloading and parsing of NSE Equity Master, Nifty Index constituents,
Full Security Deliverable Bhavcopy (sec_bhavdata_full), Index Bhavcopy, and PIT Insider Trading data.
"""

import io
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd
try:
    from curl_cffi import requests as _curl_requests  # type: ignore
    _HAS_CURL_CFFI = True
except ImportError:
    import requests as _curl_requests  # type: ignore
    _HAS_CURL_CFFI = False
import urllib3

from reality_engine.config import (
    NSE_HEADERS,
    NSE_EQUITY_L_URL,
    NSE_NIFTY50_LIST_URL,
    NSE_NIFTY100_LIST_URL,
    NSE_NIFTY200_LIST_URL,
    NSE_NIFTY500_LIST_URL,
    NSE_BHAVCOPY_URL_TEMPLATE,
    NSE_INDEX_BHAVCOPY_URL_TEMPLATE,
    NSE_PIT_URL,
    BHAVCOPY_DIR,
    FIXTURES_DIR
)

urllib3.disable_warnings()
logger = logging.getLogger("reality_engine.nse_client")


class NSEClient:
    """Robust client for fetching NSE exchange data using TLS fingerprint impersonation."""

    def __init__(self):
        if _HAS_CURL_CFFI:
            self.session = _curl_requests.Session(impersonate="chrome120", verify=False)  # type: ignore[call-arg]
        else:
            self.session = _curl_requests.Session()
            # For plain requests, disable verification to mimic curl_cffi verify=False behaviour where possible
            try:
                self.session.verify = False  # type: ignore[attr-defined]
            except Exception:
                pass
        self._warmed_up = False

    def _warmup_session(self):
        """Initializes cookies and session headers by visiting the home page."""
        if not self._warmed_up:
            try:
                self.session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=10)
                self._warmed_up = True
            except Exception as e:
                logger.warning(f"Session warmup note: {e}")

    # -----------------------------------------------------------------
    # 1. Master & Index Lists
    # -----------------------------------------------------------------
    def fetch_equity_master(self) -> pd.DataFrame:
        """Fetches the official NSE Equity Master (EQUITY_L.csv) with offline fixture fallback."""
        logger.info("Fetching NSE Equity Master from %s", NSE_EQUITY_L_URL)
        try:
            res = self.session.get(NSE_EQUITY_L_URL, headers=NSE_HEADERS, timeout=15)
            if res.status_code == 200 and "SYMBOL" in res.text:
                df = pd.read_csv(io.StringIO(res.text))
                df.columns = df.columns.str.strip()
                for col in df.select_dtypes(include="object").columns:
                    df[col] = df[col].astype(str).str.strip()

                df = df[df["SERIES"] == "EQ"].copy()
                logger.info("Loaded %d active NSE EQ records from network", len(df))
                return df
        except Exception as e:
            logger.warning("NSE Equity Master network request failed (%s). Attempting local fixture fallback...", e)

        # Offline fallback: load from fixtures.json
        fixtures_file = FIXTURES_DIR / "fixtures.json"
        if fixtures_file.exists():
            try:
                with open(fixtures_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                master_list = data.get("master_companies", [])
                if master_list:
                    df_eq = pd.DataFrame([{
                        "SYMBOL": c.get("nse_symbol", ""),
                        "NAME OF COMPANY": c.get("company_name", ""),
                        "SERIES": "EQ",
                        "ISIN NUMBER": c.get("isin", ""),
                    } for c in master_list if c.get("nse_symbol") and c.get("is_active", 1) == 1])
                    logger.info("Loaded %d active NSE EQ records from offline fixtures", len(df_eq))
                    return df_eq
            except Exception as fe:
                logger.warning("Error reading offline master fixtures: %s", fe)

        raise RuntimeError("Failed to fetch NSE Equity Master from network or local fixtures")

    def fetch_nifty_index_constituents(self, index_name: str = "NIFTY200") -> pd.DataFrame:
        """Fetches constituents for standard Nifty indices with offline fixture fallback."""
        url_map = {
            "NIFTY50": NSE_NIFTY50_LIST_URL,
            "NIFTY100": NSE_NIFTY100_LIST_URL,
            "NIFTY200": NSE_NIFTY200_LIST_URL,
            "NIFTY500": NSE_NIFTY500_LIST_URL,
        }
        url = url_map.get(index_name.upper(), NSE_NIFTY200_LIST_URL)
        logger.info("Fetching %s constituents from %s", index_name, url)

        try:
            res = self.session.get(url, headers=NSE_HEADERS, timeout=15)
            if res.status_code == 200 and ("Symbol" in res.text or "SYMBOL" in res.text):
                df = pd.read_csv(io.StringIO(res.text))
                df.columns = df.columns.str.strip()
                for col in df.select_dtypes(include="object").columns:
                    df[col] = df[col].astype(str).str.strip()

                logger.info("Loaded %d constituents for %s from network", len(df), index_name)
                return df
        except Exception as e:
            logger.warning("Failed to fetch %s constituents from network (%s). Attempting offline fallback...", index_name, e)

        # Offline fallback: load from fixtures.json
        fixtures_file = FIXTURES_DIR / "fixtures.json"
        if fixtures_file.exists():
            try:
                with open(fixtures_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                master_list = data.get("master_companies", [])
                col_flag = f"is_{index_name.lower()}"
                matched = [c for c in master_list if c.get(col_flag) == 1]
                if matched:
                    df_idx = pd.DataFrame([{
                        "Symbol": c.get("nse_symbol", ""),
                        "Company Name": c.get("company_name", ""),
                        "Industry": c.get("industry", "General"),
                        "ISIN Code": c.get("isin", "")
                    } for c in matched])
                    logger.info("Loaded %d constituents for %s from offline fixtures", len(df_idx), index_name)
                    return df_idx
            except Exception as fe:
                logger.warning("Error reading offline constituents fixture: %s", fe)

        return pd.DataFrame()

    # -----------------------------------------------------------------
    # 2. Security Deliverable Bhavcopy
    # -----------------------------------------------------------------
    def fetch_bhavcopy(self, target_date: datetime) -> Optional[pd.DataFrame]:
        """
        Fetches the full deliverable bhavcopy (sec_bhavdata_full_DDMMYYYY.csv) for a given date.
        Saves a local backup copy in DATA/bhavcopy.
        """
        date_str = target_date.strftime("%d%m%Y")
        url = NSE_BHAVCOPY_URL_TEMPLATE.format(date_str=date_str)
        local_file = BHAVCOPY_DIR / f"sec_bhavdata_full_{date_str}.csv"

        # Minimum expected schema for a valid full deliverable bhavcopy.
        # NOTE: the raw NSE file has no literal 'DATE' column (it ships 'DATE1'),
        # so validation targets the columns that are actually present plus a
        # column-count floor. 'DATE' is synthesized later in this method.
        REQUIRED_COLUMNS = ["SYMBOL", "SERIES", "CLOSE_PRICE", "DELIV_QTY", "DELIV_PER"]
        MIN_COLUMNS = 10

        def _validate_bhavcopy(frame: pd.DataFrame) -> bool:
            """Validates that a parsed bhavcopy has the expected schema."""
            if frame is None or len(frame) == 0:
                return False
            cols = frame.columns.str.strip().tolist() if hasattr(frame.columns, "str") else list(frame.columns)
            if len(cols) < MIN_COLUMNS:
                return False
            for needed in REQUIRED_COLUMNS:
                if needed not in cols:
                    return False
            return True

        def _quarantine_cache(path):
            """Deletes a corrupted cached bhavcopy so it is not reused."""
            try:
                path.unlink()
                logger.warning("Quarantined (deleted) corrupted Bhavcopy cache: %s", path)
            except Exception as ue:  # pragma: no cover - best-effort cleanup
                logger.warning("Could not delete corrupted Bhavcopy cache %s: %s", path, ue)

        def _download_and_parse() -> Optional[pd.DataFrame]:
            """Downloads the bhavcopy from NSE, writes an atomic cache, and parses it."""
            try:
                res = self.session.get(url, headers=NSE_HEADERS, timeout=20)
            except Exception as e:
                logger.warning("Network error fetching Bhavcopy for %s: %s", date_str, e)
                return None
            if res.status_code != 200:
                logger.warning("Bhavcopy for %s not found (HTTP %d)", date_str, res.status_code)
                return None

            text = res.text.strip()
            if not text or "SYMBOL" not in text:
                logger.warning("Invalid or empty Bhavcopy payload for %s", date_str)
                return None

            # Write cache atomically: temp file then atomic rename.
            tmp_file = local_file.with_name(local_file.name + ".tmp")
            try:
                with open(tmp_file, "w", encoding="utf-8") as f:
                    f.write(text)
                tmp_file.replace(local_file)
            except Exception as we:
                logger.warning("Failed to write Bhavcopy cache for %s: %s", date_str, we)
                # Cache write is best-effort; continue with in-memory text below.

            try:
                return pd.read_csv(io.StringIO(text))
            except (pd.errors.ParserError, ValueError, KeyError, Exception) as e:
                logger.warning("Failed to parse downloaded Bhavcopy for %s: %s", date_str, e)
                return None

        df: Optional[pd.DataFrame] = None
        used_cache = False

        # 1. Try local cache first (guarded read)
        if local_file.exists() and local_file.stat().st_size > 1000:
            logger.info("Loading cached Bhavcopy from %s", local_file)
            try:
                df = pd.read_csv(local_file)
                used_cache = True
            except (pd.errors.ParserError, ValueError, KeyError, Exception) as e:
                logger.warning("Failed to parse cached Bhavcopy %s (%s). Quarantining and re-downloading.", local_file, e)
                _quarantine_cache(local_file)
                df = None

        # 2. If cache missing/corrupt, download from network
        if df is None:
            logger.info("Downloading Bhavcopy for %s from %s", target_date.strftime('%Y-%m-%d'), url)
            df = _download_and_parse()

        # 3. Validate schema; on cache path, quarantine and attempt exactly one re-download
        if not _validate_bhavcopy(df):
            if used_cache and df is not None:
                # Cache parsed but failed schema validation -> retry from network once.
                logger.warning(
                    "Bhavcopy for %s parsed from cache but failed schema validation "
                    "(cols=%d). Quarantining cache and attempting one re-download.",
                    date_str, len(df.columns),
                )
                _quarantine_cache(local_file)
                df = _download_and_parse()
            else:
                logger.warning(
                    "Bhavcopy for %s failed schema validation or could not be obtained; skipping.",
                    date_str,
                )
                return None

        if not _validate_bhavcopy(df):
            logger.warning("Re-downloaded Bhavcopy for %s still failed schema validation; skipping.", date_str)
            return None

        # Standardize columns and whitespace
        df.columns = df.columns.str.strip()
        for col in df.select_dtypes(include="object").columns:
            df[col] = df[col].astype(str).str.strip()

        # Clean numeric fields
        numeric_cols = [
            "PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "LAST_PRICE",
            "CLOSE_PRICE", "AVG_PRICE", "TTL_TRD_QNTY", "TURNOVER_LACS",
            "NO_OF_TRADES", "DELIV_QTY", "DELIV_PER"
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", "").str.replace("-", "0"), errors="coerce").fillna(0)

        # Standardize date format YYYY-MM-DD
        df["DATE"] = target_date.strftime("%Y-%m-%d")

        # Filter for equities (EQ, BE)
        df_eq = df[df["SERIES"].isin(["EQ", "BE"])].copy()
        logger.info("Successfully parsed Bhavcopy for %s (%d equity rows)", df["DATE"].iloc[0], len(df_eq))
        return df_eq

    # -----------------------------------------------------------------
    # 3. Index Bhavcopy & Breadth
    # -----------------------------------------------------------------
    def fetch_index_bhavcopy(self, target_date: datetime) -> Optional[pd.DataFrame]:
        """Fetches official NSE Index Bhavcopy (ind_close_all_DDMMYYYY.csv)."""
        date_str = target_date.strftime("%d%m%Y")
        url = NSE_INDEX_BHAVCOPY_URL_TEMPLATE.format(date_str=date_str)
        local_file = BHAVCOPY_DIR / f"ind_close_all_{date_str}.csv"

        df: Optional[pd.DataFrame] = None
        try:
            if local_file.exists() and local_file.stat().st_size > 500:
                df = pd.read_csv(local_file)
            else:
                res = self.session.get(url, headers=NSE_HEADERS, timeout=15)
                if res.status_code != 200:
                    logger.warning("Index Bhavcopy for %s returned HTTP %d", date_str, res.status_code)
                    return None

                with open(local_file, "w", encoding="utf-8") as f:
                    f.write(res.text)

                df = pd.read_csv(io.StringIO(res.text))
        except (pd.errors.ParserError, ValueError, KeyError, OSError, Exception) as e:
            logger.warning("Failed to fetch/parse Index Bhavcopy for %s (%s); skipping.", date_str, e)
            return None

        df.columns = df.columns.str.strip()
        for col in df.select_dtypes(include="object").columns:
            df[col] = df[col].astype(str).str.strip()

        df["DATE"] = target_date.strftime("%Y-%m-%d")
        return df

    # -----------------------------------------------------------------
    # 4. SEBI Insider Trading (PIT) Feed
    # -----------------------------------------------------------------
    def fetch_insider_trades(self) -> List[Dict[str, Any]]:
        """Fetches the latest SEBI PIT (Prohibition of Insider Trading) feed from NSE."""
        self._warmup_session()
        logger.info("Fetching SEBI PIT feed from %s", NSE_PIT_URL)
        try:
            res = self.session.get(NSE_PIT_URL, headers=NSE_HEADERS, timeout=15)
            if res.status_code != 200:
                logger.warning("SEBI PIT endpoint returned HTTP %d", res.status_code)
                return []

            data = res.json()
            items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            
            parsed_trades = []
            for item in items:
                # Build unique ID
                trade_id = f"PIT_{item.get('symbol')}_{item.get('secAcq')}_{item.get('pid', '')}_{item.get('anndate', '')}"
                trade_record = {
                    "id": trade_id,
                    "symbol": item.get("symbol", "").strip(),
                    "isin": item.get("secAcqIsin", "").strip() or item.get("isin", "").strip(),
                    "acquirer_name": item.get("personCategory", item.get("acqName", "")).strip(),
                    "category_of_person": item.get("personCategory", "PROMOTER").strip(),
                    "transaction_type": item.get("tdpTransactionType", item.get("acqMode", "BUY")).strip().upper(),
                    "num_shares": int(pd.to_numeric(item.get("secVal", item.get("tdpSecVal", 0)), errors="coerce") or 0),
                    "value_inr_lacs": float(pd.to_numeric(item.get("secValInLacs", 0), errors="coerce") or 0.0),
                    "mode_of_acquisition": item.get("tdpModeOfAcq", item.get("acqMode", "OPEN_MARKET")),
                    "acquisition_date": item.get("acqFromDt", datetime.now().strftime("%Y-%m-%d")),
                    "intimation_date": item.get("dateOfInit", datetime.now().strftime("%Y-%m-%d")),
                }
                parsed_trades.append(trade_record)

            logger.info("Extracted %d SEBI PIT insider trades from network", len(parsed_trades))
            return parsed_trades
        except Exception as e:
            logger.warning("Error fetching SEBI PIT data from network (%s). Attempting local fixture fallback...", e)

        # Offline fallback: load from fixtures.json
        fixtures_file = FIXTURES_DIR / "fixtures.json"
        if fixtures_file.exists():
            try:
                with open(fixtures_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                insider_list = data.get("insider_trades", [])
                if insider_list:
                    logger.info("Loaded %d SEBI PIT insider trades from offline fixtures", len(insider_list))
                    return insider_list
            except Exception as fe:
                logger.warning("Error reading offline insider trades fixture: %s", fe)

        return []

    # -----------------------------------------------------------------
    # Helper: Scan Recent Active Trading Days
    # -----------------------------------------------------------------
    def find_recent_trading_days(self, count: int = 25, end_date: Optional[datetime] = None) -> List[datetime]:
        """Scans backwards from end_date to find valid trading days with Bhavcopy data available."""
        current = end_date or datetime.now()
        found_days: List[datetime] = []
        lookback_limit = count * 3  # safety window
        checked = 0

        logger.info("Scanning for %d most recent NSE trading days from %s...", count, current.strftime('%Y-%m-%d'))
        while len(found_days) < count and checked < lookback_limit:
            # Skip Saturday (5) and Sunday (6)
            if current.weekday() < 5:
                # Check if Bhavcopy exists for this date
                date_str = current.strftime("%d%m%Y")
                local_file = BHAVCOPY_DIR / f"sec_bhavdata_full_{date_str}.csv"
                if local_file.exists() and local_file.stat().st_size > 1000:
                    found_days.append(current)
                else:
                    # Quick HEAD/GET probe
                    url = NSE_BHAVCOPY_URL_TEMPLATE.format(date_str=date_str)
                    try:
                        res = self.session.get(url, headers=NSE_HEADERS, timeout=8)
                        if res.status_code == 200 and len(res.text) > 1000:
                            # Save locally
                            with open(local_file, "w", encoding="utf-8") as f:
                                f.write(res.text)
                            found_days.append(current)
                    except Exception:
                        pass

            current -= timedelta(days=1)
            checked += 1

        # Sort ascending
        found_days.sort()
        logger.info("Found %d trading days: %s to %s", len(found_days), 
                    found_days[0].strftime('%Y-%m-%d') if found_days else 'None',
                    found_days[-1].strftime('%Y-%m-%d') if found_days else 'None')
        return found_days


# Singleton client
nse_client = NSEClient()
