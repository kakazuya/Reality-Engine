"""
Reality Engine Ingestion Subsystem
Provides modular clients for exchange masters, corporate fundamentals,
Bhavcopy archives, multi-threaded Telegram channels, and FinanciallyFree breadth scraper.
Isolation guards ensure offline/mock test suites import cleanly even when optional
network dependencies (curl_cffi, yfinance) are absent.
"""

import logging

logger = logging.getLogger("reality_engine.ingestion")

try:
    from reality_engine.ingestion.nse_client import NSEClient, nse_client
except Exception as _e:  # pragma: no cover - import isolation
    logger.warning("NSEClient import fallback due to: %s", _e)
    NSEClient = None  # type: ignore
    nse_client = None  # type: ignore

try:
    from reality_engine.ingestion.bse_client import BSEClient, bse_client
except Exception as _e:  # pragma: no cover
    logger.warning("BSEClient import fallback due to: %s", _e)
    BSEClient = None  # type: ignore
    bse_client = None  # type: ignore

try:
    from reality_engine.ingestion.fundamentals_client import FundamentalsClient, fundamentals_client
except Exception as _e:  # pragma: no cover
    logger.warning("FundamentalsClient import fallback due to: %s", _e)
    FundamentalsClient = None  # type: ignore
    fundamentals_client = None  # type: ignore

try:
    from reality_engine.ingestion.master_sync import MasterSync, MasterSyncManager, master_sync
except Exception as _e:  # pragma: no cover
    logger.warning("MasterSync import fallback due to: %s", _e)
    MasterSync = None  # type: ignore
    MasterSyncManager = None  # type: ignore
    master_sync = None  # type: ignore

try:
    from reality_engine.ingestion.telegram_client import TelegramListener, telegram_listener
except Exception as _e:  # pragma: no cover
    logger.warning("TelegramListener import fallback due to: %s", _e)
    TelegramListener = None  # type: ignore
    telegram_listener = None  # type: ignore

try:
    from reality_engine.ingestion.financially_free_client import FinanciallyFreeClient, financially_free_client
except Exception as _e:  # pragma: no cover
    logger.warning("FinanciallyFreeClient import fallback due to: %s", _e)
    FinanciallyFreeClient = None  # type: ignore
    financially_free_client = None  # type: ignore

__all__ = [
    "NSEClient",
    "nse_client",
    "BSEClient",
    "bse_client",
    "FundamentalsClient",
    "fundamentals_client",
    "MasterSync",
    "MasterSyncManager",
    "master_sync",
    "TelegramListener",
    "telegram_listener",
    "FinanciallyFreeClient",
    "financially_free_client",
]
