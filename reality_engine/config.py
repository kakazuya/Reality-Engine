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
INBOX_LIKES_DIR = INBOX_DIR / "likes"
BROWSER_PROFILE_DIR = DATA_DIR / "browser_profile"

# Verified Indian financial-news Telegram channels (handles checked live
# 2026-09-19 via t.me/s previews; every one posted that day). Media-house
# channels — news, not anonymous tips — so they outrank the general Tier-2
# rumor layer. Pass explicitly via `--channels "@ndtvprofitnews,@livemint,..."`
# or TELEGRAM_TARGET_CHANNELS. Deliberately NOT a listener default: bulk-joining
# channels stays an explicit operator choice.
# Handles that LOOK right but are NOT these outlets (do not add):
#   cnbctv18, ndtvprofit, businessstandardnews, ZeeBusinessOfficial -> do not exist
#   ETMarkets -> squatted (Ethiopian marketplace); the_economic_times_0 -> e-paper clone
#   EconomictimesOfficial -> dead (last post 2023-02); OfficialZeeBusiness -> stale clone
TELEGRAM_NEWS_CHANNELS = [
    "@ndtvprofitnews",       # NDTV Profit
    "@HinduBusinessLine",    # BusinessLine (The Hindu)
    "@livemint",             # Mint Business News (official)
    "@bsindiaofficial",      # Business Standard Official
    "@moneycontrolcom",      # Moneycontrol
]
FIXTURES_DIR = Path(os.environ.get("REALITY_ENGINE_FIXTURES_DIR", DATA_DIR / "fixtures"))
LANCEDB_DIR = Path(os.environ.get("REALITY_ENGINE_LANCEDB_DIR", DATA_DIR / "lancedb"))

# Macro PDF ingestion (second-tier peer data below core company data):
# Central Budget speeches, 8 state budgets, PIB circulars, RBI reports/surveys.
MACRO_PDFS_DIR = Path(os.environ.get("REALITY_ENGINE_MACRO_PDFS_DIR", DATA_DIR / "macro_pdfs"))

# Ingestion URLs & Endpoints
FINANCIALLY_FREE_BASE_URL = "https://www.financiallyfree.in/tools/market-overview"

# Headless-browser JWT/cookie fetcher endpoints (blocked BSE/NSE APIs).
# These require a browser-issued cookie/JWT, obtained via
# reality_engine/ingestion/headless_fetcher.py. Fail-closed when unreachable.
BSE_HOME_URL = "https://www.bseindia.com"
NSE_HOME_URL = "https://www.nseindia.com"
BSE_RESULTS_URL = "https://api.bseindia.com/BseIndiaAPI/api/ComWinQuery/w"
BSE_DELISTED_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListOfDelistedScrips/w"
BSE_SUSPENDED_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListOfSuspendedScrips/w"
BROWSER_HEADLESS = True
BROWSER_LAUNCH_TIMEOUT_MS = 20000
BROWSER_NAV_TIMEOUT_MS = 20000
BROWSER_RATE_LIMIT_SEC = 1.0

# ---------------------------------------------------------------------------
# Macro PDF ingestion endpoints (second-tier peer data below core company data)
# These are authoritative, headless-fetchable URLs verified during the research
# wave. Hosts are split into two allow-lists:
#   * DIRECT_ALLOW_HOSTS  -> plain requests GET (no browser cookie needed)
#   * BROWSER_REQUIRED_HOSTS -> need Playwright fallback (else skip gracefully)
# ---------------------------------------------------------------------------
from urllib.parse import urlparse as _urlparse  # noqa: E402

# Central Budget speeches + Economic Surveys (FY2024-25, FY2025-26)
# Each entry: source_type, fiscal_period, year, title, url
CENTRAL_BUDGET_URLS = [
    {
        "source_type": "Union_Budget",
        "fiscal_period": "FY2024-25",
        "year": "2024-25",
        "title": "Union Budget 2024-25 Speech (Part I)",
        "url": "https://www.indiabudget.gov.in/doc/bspeech/bs2024_25(I).pdf",
    },
    {
        "source_type": "Union_Budget",
        "fiscal_period": "FY2024-25",
        "year": "2024-25",
        "title": "Union Budget 2024-25 Speech (Part II)",
        "url": "https://www.indiabudget.gov.in/doc/bspeech/bs2024_25.pdf",
    },
    {
        "source_type": "Union_Budget",
        "fiscal_period": "FY2025-26",
        "year": "2025-26",
        "title": "Union Budget 2025-26 Speech",
        "url": "https://www.indiabudget.gov.in/doc/bspeech/bs2025_26.pdf",
    },
    {
        "source_type": "Economic_Survey",
        "fiscal_period": "FY2024-25",
        "year": "2024-25",
        "title": "Economic Survey 2024-25",
        "url": "https://www.indiabudget.gov.in/budget2024-25/economicsurvey/doc/echapter.pdf",
    },
    {
        "source_type": "Economic_Survey",
        "fiscal_period": "FY2025-26",
        "year": "2025-26",
        "title": "Economic Survey 2025-26",
        "url": "https://www.indiabudget.gov.in/budget2025-26/economicsurvey/doc/echapter.pdf",
    },
    {
        "source_type": "Economic_Survey",
        "fiscal_period": "FY2023-24",
        "year": "2023-24",
        "title": "Economic Survey (Consolidated)",
        "url": "https://www.indiabudget.gov.in/economicsurvey/doc/echapter.pdf",
    },
]

# 8 State Budgets. headless_ok=True -> plain GET works; False -> JS-rendered /
# obfuscated listing that needs the Playwright fallback (else skipped gracefully).
STATE_BUDGET_URLS = {
    "UP": {
        "name": "Uttar Pradesh",
        "2024-25": {"url": "https://budget.up.nic.in/budgetbhashan/budgetbhashan_2024_2025.pdf", "headless_ok": True},
        "2025-26": {"url": "https://budget.up.nic.in/budgetbhashan/budgetbhashan_2025_2026.pdf", "headless_ok": True},
    },
    "Tamil_Nadu": {
        "name": "Tamil Nadu",
        # Verified direct PDFs (HTTP 200, application/pdf) — plain GET works, no JS.
        # English is the primary variant (Tamil variants exist but are not used here).
        "2024-25": {"url": "https://financedept.tn.gov.in/en/my-documents/2020/07/A4-BS_2024-25_Eng_Final.pdf", "headless_ok": True},
        "2025-26": {"url": "https://financedept.tn.gov.in/en/my-documents/2020/07/BS_2025-26_English_A4_Final.pdf", "headless_ok": True},
    },
    "Maharashtra": {
        "name": "Maharashtra",
        "2024-25": {"url": "https://cdnbbsr.s3waas.gov.in/20240313133390883/uploads/financial_budget_2024_25.pdf", "headless_ok": True},
        "2025-26": {"url": "https://cdnbbsr.s3waas.gov.in/20250313303390883/uploads/financial_budget_2025_26.pdf", "headless_ok": True},
    },
    "Karnataka": {
        "name": "Karnataka",
        # 2024-25: the canonical info-2 listing (HTTP 200) is JS-rendered and exposes
        # no static PDF links in its HTML, so it is kept as a browser/listing target
        # (graceful skip if the browser fallback cannot resolve the speech PDF). No
        # stable direct 2024-25 speech URL was discovered.
        # max_pdfs=0 → explicit skip: the info-2 listing only yields non-budget
        # documents (ORGANISATION CHART / Notification) so avoid polluting
        # raw_documents with mislabeled files.
        "2024-25": {"url": "https://finance.karnataka.gov.in/info-2/2024-25/Budget+Volumes+2024-25/en", "headless_ok": False, "max_pdfs": 0},
        # 2025-26: verified direct PDF (HTTP 200, application/pdf) — plain GET works.
        "2025-26": {"url": "https://finance.karnataka.gov.in/uploads/media_to_upload1741332694.pdf", "headless_ok": True},
    },
    "Telangana": {
        "name": "Telangana",
        # PreviewPage.do serves the PDF directly but the URL carries a ?fileName=
        # query that produces an illegal Windows filename; the fetcher sanitizes the
        # destination name (strips the query, keeps english.pdf).
        "2024-25": {"url": "https://finance.telangana.gov.in/PreviewPage.do?filePath=budget-2024-25-books&fileName=english.pdf", "headless_ok": True},
        "2025-26": {"url": "https://finance.telangana.gov.in/PreviewPage.do?filePath=budget-2025-26-books&fileName=english.pdf", "headless_ok": True},
    },
    "Gujarat": {
        "name": "Gujarat",
        # JS-rendered WebForms listing (no static .pdf links in the served HTML) that
        # requires a browser click-walk via headless_fetcher (Playwright) to resolve
        # the speech PDF(s). Graceful skip when the browser fallback cannot resolve
        # them. No stable direct PDF was discovered (web search unavailable in this
        # environment), so financedepartment.gujarat.gov.in remains in
        # MACRO_BROWSER_REQUIRED_HOSTS. Best-effort — expected to skip cleanly.
        "2024-25": {"url": "https://financedepartment.gujarat.gov.in/budget.html", "headless_ok": False},
        "2025-26": {"url": "https://financedepartment.gujarat.gov.in/budget.html", "headless_ok": False},
    },
    "Haryana": {
        "name": "Haryana",
        # The hashed s3waas URLs 404 (timestamp segment changed). Discovery falls back
        # to the finhry.gov.in budget landing pages, which list the live s3waas PDFs.
        "2024-25": {"url": "https://cdnbbsr.s3waas.gov.in/20240223804121868/uploads/financial_budget_2024_25.pdf", "headless_ok": True,
                    "listing_url": "https://finhry.gov.in/budget-2024-25"},
        "2025-26": {"url": "https://cdnbbsr.s3waas.gov.in/202503221525770346/uploads/financial_budget_2025_26.pdf", "headless_ok": True,
                    "listing_url": "https://finhry.gov.in/budget-2025-26"},
    },
    "Andhra_Pradesh": {
        "name": "Andhra Pradesh",
        # budget-speech.html is a server-rendered listing that links to
        # SpeechEnglish.pdf / SpeechTelugu.pdf (no JS challenge).
        "2024-25": {"url": "https://apfinance.gov.in/budget-speech.html", "headless_ok": False},
        "2025-26": {"url": "https://apfinance.gov.in/budget-speech.html", "headless_ok": False},
    },
}

# Maharashtra's hashed s3waas URLs 404; discovery falls back to the
# finance.maharashtra.gov.in budget-speech landing page (server-rendered, lists the
# live s3waas PDFs). The 2024-25 landing 404s upstream, so it is best-effort.
STATE_BUDGET_URLS["Maharashtra"]["2024-25"]["listing_url"] = "https://finance.maharashtra.gov.in/en/budget-speech-2025-26"
STATE_BUDGET_URLS["Maharashtra"]["2025-26"]["listing_url"] = "https://finance.maharashtra.gov.in/en/budget-speech-2025-26"

# PIB (Press Information Bureau) circular / press-release PDFs.
PIB_LISTING_BASE = "https://pib.gov.in/PressReleasePage.aspx?PRID="
PIB_DIRECT_BASE = "https://static.pib.gov.in/WriteReadData/specificdocs/documents/"
PIB_ARCHIVE_BASE = "https://archive.pib.gov.in/"
# Seed with the research-verified direct PDF; more can be appended at runtime.
PIB_CIRCULAR_URLS = [
    {
        "source_type": "PIB_Circular",
        "title": "PIB Circular (static direct sample)",
        "url": "https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/feb/doc202521492801.pdf",
    },
]

# RBI Annual Report / Financial Stability Report etc. PDFs.
#
# The rbidocs.rbi.org.in PDF URLs are NOT stable: the hashed filenames change every
# publishing cycle (e.g. 0ANNUALREPORT202425DA4AE...PDF), so the hardcoded 2024-25
# names 404. Instead we DISCOVER the live PDFs by parsing the RBI listing pages and
# downloading via plain GET (no Imperva TSPD challenge on the rbidocs host — verified).
# RBI_REPORT_URLS is kept for planning/metadata (source_type, year, title); the actual
# PDF is resolved at fetch time via RBI_LISTING_URLS below.
RBI_LISTING_BASE = "https://rbi.org.in/Scripts/AnnualReportPublications.aspx?year="
RBI_REPORT_URLS = [
    {
        "source_type": "RBI_Annual_Report",
        "fiscal_period": "FY2024-25",
        "year": "2024-25",
        "title": "RBI Annual Report 2024-25",
        "url": "https://rbi.org.in/Scripts/AnnualReportPublications.aspx?year=2025",
    },
    {
        "source_type": "RBI_Financial_Stability_Report",
        "fiscal_period": "FY2025-26",
        "year": "2025-26",
        "title": "RBI Financial Stability Report (Dec 2025)",
        "url": "https://rbi.org.in/Scripts/FsReports.aspx",
    },
]

# Discovery config: for each RBI report source_type, how to find the live PDF on the
# RBI site. ``year_map`` maps our FY label to the ``?year=`` query param the RBI
# listing expects (year=2025 -> FY2024-25, year=2026 -> FY2025-26). ``keyword`` filters
# the discovered *.pdf links to the primary document. Plain GET — no browser needed.
RBI_LISTING_URLS = {
    "RBI_Annual_Report": {
        "url_template": "https://rbi.org.in/Scripts/AnnualReportPublications.aspx?year={year_numeric}",
        "year_map": {"2024-25": "2025", "2025-26": "2026"},
        "keyword": "ANNUALREPORT",
        "max_pdfs": 1,
    },
    "RBI_Financial_Stability_Report": {
        "url_template": "https://rbi.org.in/Scripts/FsReports.aspx",
        "year_map": {},
        "keyword": "FSR",
        "max_pdfs": 1,
    },
}

# Hosts that allow a plain requests GET (no browser cookie / JS).
# rbi.org.in / rbidocs.rbi.org.in are included: the listing pages and the rbidocs PDFs
# are served without the Imperva TSPD challenge (verified via plain GET -> %PDF-1.6),
# so the RBI discovery path uses direct GET and no longer needs the browser fallback.
# financedept.tn.gov.in and finance.karnataka.gov.in were promoted here: their budget
# speech PDFs are now served as direct (verified) downloads, so plain GET is used and
# they no longer need the Playwright fallback.
MACRO_DIRECT_ALLOW_HOSTS = (
    "indiabudget.gov.in",
    "static.pib.gov.in",
    "archive.pib.gov.in",
    "pib.gov.in",
    "budget.up.nic.in",
    "finance.telangana.gov.in",
    "apfinance.gov.in",
    "financedept.tn.gov.in",
    "finance.karnataka.gov.in",
    "s3waas.gov.in",
    "nic.in",
    "rbi.org.in",
    "rbidocs.rbi.org.in",
)

# Hosts that require the Playwright browser fallback (JS-rendered listing that hides
# the PDF links until the page is navigated/rendered in a real browser). When
# unavailable, the fetcher logs a warning and SKIPS (graceful — never crashes).
# RBI was removed (no longer TSPD-blocked). TN and Karnataka were removed once their
# direct budget-speech PDF URLs were verified (see MACRO_DIRECT_ALLOW_HOSTS above).
# Only Gujarat remains browser-required in this wave.
MACRO_BROWSER_REQUIRED_HOSTS = (
    "financedepartment.gujarat.gov.in",
)


def macro_host_requires_browser(url: str) -> bool:
    """Return True if ``url`` is on a host that needs the browser fallback."""
    try:
        host = _urlparse(url).netloc.lower()
        host = host[4:] if host.startswith("www.") else host
    except Exception:
        return False
    return any(host == h or host.endswith("." + h) for h in MACRO_BROWSER_REQUIRED_HOSTS)


# Ensure runtime directories exist
for path in [DATA_DIR, BHAVCOPY_DIR, PDFS_DIR, REPORTS_DIR, INBOX_DIR, TELEGRAM_IMAGES_DIR, INBOX_LIKES_DIR, FIXTURES_DIR, LANCEDB_DIR, MACRO_PDFS_DIR]:
    path.mkdir(parents=True, exist_ok=True)

# Database Configuration
SQLITE_PRAGMAS = [
    "PRAGMA journal_mode = WAL;",
    "PRAGMA synchronous = NORMAL;",
    "PRAGMA cache_size = -64000;",      # 64 MB page cache
    "PRAGMA temp_store = MEMORY;",
    "PRAGMA foreign_keys = ON;",
    "PRAGMA busy_timeout = 30000;",       # 30 second timeout on locks (raised for concurrent fetcher)
    "PRAGMA mmap_size = 1073741824;",     # 1 GB file-backed mmap (OS-evictable, not pinned RAM)
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
