"""
Master Company Synchronization Module
Synchronizes company listings across NSE and BSE, merges ISINs, maps industry taxonomy,
and assigns NIFTY index memberships (Nifty 50, 100, 200, 500) and market cap tiers.
"""

import logging
from typing import Dict, Any, List
import pandas as pd

from reality_engine.ingestion.nse_client import nse_client
from reality_engine.ingestion.bse_client import bse_client
from reality_engine.db.repository import repo

logger = logging.getLogger("reality_engine.master_sync")


class MasterSyncManager:
    """Orchestrates cross-exchange symbol discovery and universe categorization."""

    def __init__(self):
        self.repo = repo
        self.nse = nse_client
        self.bse = bse_client

    def sync_all(self) -> Dict[str, int]:
        """
        Executes complete multi-exchange symbol master synchronization:
        1. Ingests NSE Equity Master (EQUITY_L.csv)
        2. Ingests BSE Scrip Master
        3. Cross-references Nifty 50, 100, 200, 500 constituents
        4. Upserts merged records into master_companies
        """
        logger.info("Starting Master Company Synchronization...")

        # 1. Fetch NSE Equity Master
        df_nse = self.nse.fetch_equity_master()
        
        # 2. Fetch Index Constituent Sets
        df_n50 = self.nse.fetch_nifty_index_constituents("NIFTY50")
        df_n100 = self.nse.fetch_nifty_index_constituents("NIFTY100")
        df_n200 = self.nse.fetch_nifty_index_constituents("NIFTY200")
        df_n500 = self.nse.fetch_nifty_index_constituents("NIFTY500")

        n50_symbols = set(df_n50["Symbol"].str.strip().tolist()) if not df_n50.empty else set()
        n100_symbols = set(df_n100["Symbol"].str.strip().tolist()) if not df_n100.empty else set()
        n200_symbols = set(df_n200["Symbol"].str.strip().tolist()) if not df_n200.empty else set()
        n500_symbols = set(df_n500["Symbol"].str.strip().tolist()) if not df_n500.empty else set()

        # Map industry taxonomy from Nifty 200 / Nifty 500
        industry_map: Dict[str, str] = {}
        for df_idx in [df_n500, df_n200, df_n100, df_n50]:
            if not df_idx.empty and "Industry" in df_idx.columns:
                for _, r in df_idx.iterrows():
                    sym = str(r["Symbol"]).strip()
                    ind = str(r["Industry"]).strip()
                    if sym and ind:
                        industry_map[sym] = ind

        # 3. Fetch BSE Scrip Master
        df_bse = pd.DataFrame()
        try:
            df_bse = self.bse.fetch_scrip_master()
        except Exception as e:
            logger.warning("BSE Scrip master fetch issue (continuing with NSE): %s", e)

        # Build ISIN -> BSE info mapping
        bse_isin_map: Dict[str, Dict[str, Any]] = {}
        if not df_bse.empty and "isin" in df_bse.columns:
            for _, r in df_bse.iterrows():
                isin_code = str(r.get("isin", "")).strip()
                if isin_code and isin_code != "nan":
                    bse_isin_map[isin_code] = {
                        "bse_code": str(r.get("bse_code", "")).strip(),
                        "bse_symbol": str(r.get("bse_symbol", "")).strip(),
                        "bse_name": str(r.get("bse_name", "")).strip(),
                        "bse_mktcap": r.get("bse_mktcap_cr"),
                    }

        # 4. Detect Lifecycle Events (New IPOs, Delistings, Renames)
        existing_companies = self.repo.get_all_companies(active_only=False)
        existing_isin_map = {c["isin"]: c for c in existing_companies}
        
        new_listings: List[str] = []
        renamed_symbols: List[Dict[str, str]] = []
        active_isin_set = set()

        master_records: List[Dict[str, Any]] = []
        for _, row in df_nse.iterrows():
            sym = str(row["SYMBOL"]).strip()
            isin = str(row["ISIN NUMBER"]).strip()
            name = str(row["NAME OF COMPANY"]).strip()

            if not isin or isin == "nan":
                continue

            active_isin_set.add(isin)

            # Check for new IPOs / Demergers
            if isin not in existing_isin_map:
                new_listings.append(f"{sym} ({name})")
            else:
                old_sym = existing_isin_map[isin].get("nse_symbol")
                if old_sym and old_sym != sym:
                    renamed_symbols.append({"isin": isin, "old_symbol": old_sym, "new_symbol": sym})

            # Check index memberships
            is_n50 = 1 if sym in n50_symbols else 0
            is_n100 = 1 if sym in n100_symbols else 0
            is_n200 = 1 if sym in n200_symbols else 0
            is_n500 = 1 if sym in n500_symbols else 0

            # Determine Market Cap Tier
            if is_n100:
                tier = "LARGE"
            elif is_n200:
                tier = "MID"
            elif is_n500:
                tier = "SMALL"
            else:
                tier = "MICRO"

            industry = industry_map.get(sym, "General Diversified")
            bse_info = bse_isin_map.get(isin, {})
            bse_code = bse_info.get("bse_code")

            record = {
                "isin": isin,
                "nse_symbol": sym,
                "bse_code": bse_code,
                "company_name": name,
                "industry": industry,
                "sector": industry,
                "market_cap_tier": tier,
                "is_fno_eligible": 1 if (is_n100 or is_n200) else 0,
                "is_nifty50": is_n50,
                "is_nifty100": is_n100,
                "is_nifty200": is_n200,
                "is_nifty500": is_n500,
                "is_active": 1,
            }
            master_records.append(record)

        # 5. Detect and Flag Delisted / Suspended Scrips
        delisted_count = 0
        with self.repo.db.session() as conn:
            for isin_id, ex_rec in existing_isin_map.items():
                if isin_id not in active_isin_set and not isin_id.startswith("INE_AUTO_") and ex_rec.get("is_active") == 1:
                    conn.execute("UPDATE master_companies SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE isin = ?", (isin_id,))
                    delisted_count += 1
                    logger.info("Flagged Delisted/Suspended company: %s (%s)", ex_rec.get("nse_symbol"), isin_id)

        # 6. Persist to SQLite
        inserted_count = self.repo.upsert_master_companies(master_records)
        nifty200_count = sum(1 for r in master_records if r["is_nifty200"] == 1)

        logger.info("Master Sync Complete: Upserted %d active companies (%d new listings, %d delisted, %d renamed)",
                    inserted_count, len(new_listings), delisted_count, len(renamed_symbols))

        return {
            "total_upserted": inserted_count,
            "new_listings_discovered": len(new_listings),
            "delisted_flagged": delisted_count,
            "renamed_symbols_count": len(renamed_symbols),
            "nifty50_count": len(n50_symbols),
            "nifty100_count": len(n100_symbols),
            "nifty200_count": nifty200_count,
            "nifty500_count": len(n500_symbols),
        }


# Alias for MasterSyncManager
MasterSync = MasterSyncManager

# Singleton sync manager
master_sync = MasterSyncManager()
