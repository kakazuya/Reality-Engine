"""
Configuration Module for Reality Engine (Phase 1)
Defines file paths, database PRAGMAs, API headers, network timeouts, and constants.
"""

from pathlib import Path
import os

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = Path(__file__).resolve().parent

DATA_DIR = Path(os.environ.get("REALITY_ENGINE_DATA_DIR", ENGINE_DIR / "data"))
DB_PATH = Path(os.environ.get("REALITY_ENGINE_DB_PATH", DATA_DIR / "equity_intelligence.db"))
BHAVCOPY_DIR = Path(os.environ.get("REALITY_ENGINE_BHAVCOPY_DIR", DATA_DIR / "bhavcopy"))
PDFS_DIR = Path(os.environ.get("REALITY_ENGINE_PDFS_DIR", DATA_DIR / "pdfs"))
REPORTS_DIR = Path(os.environ.get("REALITY_ENGINE_REPORTS_DIR", DATA_DIR / "reports"))
INBOX_DIR = Path(os.environ.get("REALITY_ENGINE_INBOX_DIR", DATA_DIR / "inbox"))
TELEGRAM_IMAGES_DIR = INBOX_DIR / "images"
BROWSER_PROFILE_DIR = DATA_DIR / "browser_profile"
FIXTURES_DIR = Path(os.environ.get("REALITY_ENGINE_FIXTURES_DIR", DATA_DIR / "fixtures"))
LANCEDB_DIR = Path(os.environ.get("REALITY_ENGINE_LANCEDB_DIR", DATA_DIR / "lancedb"))

# Ingestion URLs & Endpoints
FINANCIALLY_FREE_BASE_URL = "https://www.financiallyfree.in/tools/market-overview"

# Ensure runtime directories exist
for path in [DATA_DIR, BHAVCOPY_DIR, PDFS_DIR, REPORTS_DIR, INBOX_DIR, TELEGRAM_IMAGES_DIR, FIXTURES_DIR, LANCEDB_DIR]:
    path.mkdir(parents=True, exist_ok=True)

# Database Configuration
SQLITE_PRAGMAS = [
    "PRAGMA journal_mode = WAL;",
    "PRAGMA synchronous = NORMAL;",
    "PRAGMA cache_size = -64000;",      # 64 MB page cache
    "PRAGMA temp_store = MEMORY;",
    "PRAGMA foreign_keys = ON;",
    "PRAGMA busy_timeout = 5000;"       # 5 second timeout on locks
]

# Network Request Headers & Defaults
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bseindia.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Ingestion URL Endpoints
NSE_EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_NIFTY50_LIST_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
NSE_NIFTY100_LIST_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv"
NSE_NIFTY200_LIST_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv"
NSE_NIFTY500_LIST_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"

NSE_BHAVCOPY_URL_TEMPLATE = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
NSE_INDEX_BHAVCOPY_URL_TEMPLATE = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{date_str}.csv"
NSE_PIT_URL = "https://www.nseindia.com/api/corporates-pit"
NSE_BULK_DEALS_URL = "https://www.nseindia.com/api/snapshot-capital-market-bulk-deals"

BSE_SCRIP_LIST_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active"
BSE_BHAVCOPY_URL_TEMPLATE = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{date_str}_F_0000.CSV"
BSE_ANNOUNCEMENTS_URL_TEMPLATE = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"

SCREENER_COMPANY_URL_TEMPLATE = "https://www.screener.in/company/{symbol}/consolidated/"
SCREENER_STANDALONE_URL_TEMPLATE = "https://www.screener.in/company/{symbol}/"

# Target Top Universe Size
TOP_UNIVERSE_LIMIT = 200

# Quantitative Screening Thresholds
MIN_DELIVERY_PCT = 40.0
MIN_DELIVERY_SPIKE_RATIO = 1.5
MIN_TURNOVER_CR = 5.0
MAX_PROMOTER_PLEDGE_PCT = 15.0
MIN_INTEREST_COVERAGE = 2.5
MAX_DEBT_TO_EQUITY = 1.5
