"""
Master Company Synchronization Module
Synchronizes company listings across NSE and BSE, merges ISINs, maps industry taxonomy,
and assigns NIFTY index memberships (Nifty 50, 100, 200, 500) and market cap tiers.

Universe provenance (additive):
  * ``listing_source`` — 'NSE' | 'DUAL' | 'BSE_ONLY'
  * ``is_screenable``  — 1 for NSE-verified rows, 0 for BSE-only admissions

Liveness (``is_active``) is exchange-aware: a scrip is deactivated only when its
ISIN is absent from *every* source — NSE EQUITY_L, the BSE active scrip master
(all groups/segments), and the currently-active exempt-synthetic set (real-ISIN
ETF/BEES/index-fund instruments that NSE EQUITY_L never carries). The legacy
INE_AUTO placeholder carve-out is retained on top of that.
"""

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from reality_engine.ingestion.nse_client import nse_client
from reality_engine.ingestion.bse_client import bse_client
from reality_engine.db.repository import repo
from reality_engine.processing.instrument_classifier import is_synthetic_instrument

logger = logging.getLogger("reality_engine.master_sync")

# Market-cap tier cutoffs in ₹ crore, aligned with the approximate Nifty
# 100 / 200 / 500 membership boundaries used by the tier assignment below
# (NSE rows take their tier from index membership; BSE-only rows have no index
# membership, so BSE market cap is the only available signal).
_TIER_LARGE_CR = 30_000.0
_TIER_MID_CR = 9_000.0
_TIER_SMALL_CR = 2_500.0

# BSE scrip master is already fetched with status=Active, but the column is
# re-checked so a suspended/delisted row can never enter the universe.
_BSE_ACTIVE_STATUS = "active"
_BSE_EQUITY_SEGMENT = "equity"
# BSE group 'Z' = non-compliant / trade-for-trade shells; never admitted.
_BSE_EXCLUDED_GROUPS = {"Z"}


def _clean_text(value: Any) -> Optional[str]:
    """NaN-safe text normalizer; returns None for NaN/NaT/''/'nan'/'None'.

    ``str(float('nan')) == 'nan'`` used to poison text columns (the BSE client
    stringifies every object column, so missing cells arrive as the literal
    string 'nan'), hence the explicit guards.
    """
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat", "n/a", "na", "<na>"}:
        return None
    return text


def _clean_number(value: Any) -> Optional[float]:
    """NaN-safe numeric coercion (BSE market cap arrives as a '153319.95' string)."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.replace(",", "").strip()
        if text.lower() in {"", "nan", "none", "-", "na"}:
            return None
        value = text
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    return num


def tier_from_market_cap(mktcap_cr: Any) -> str:
    """Map a market cap in ₹ crore to the master_companies tier CHECK domain."""
    cap = _clean_number(mktcap_cr)
    if cap is None or cap < _TIER_SMALL_CR:
        return "MICRO"
    if cap >= _TIER_LARGE_CR:
        return "LARGE"
    if cap >= _TIER_MID_CR:
        return "MID"
    return "SMALL"


def _bse_row_info(row: Any) -> Dict[str, Any]:
    """Normalize one BSE scrip-master row into JSON-safe primitives."""
    return {
        "bse_code": _clean_text(row.get("bse_code")),
        "bse_symbol": _clean_text(row.get("bse_symbol")),
        "bse_name": _clean_text(row.get("bse_name")),
        "bse_group": _clean_text(row.get("bse_group")),
        "bse_segment": _clean_text(row.get("Segment")),
        "bse_status": _clean_text(row.get("Status")),
        "bse_industry": _clean_text(row.get("INDUSTRY")),
        "bse_mktcap_cr": _clean_number(row.get("bse_mktcap_cr")),
    }


def _bse_is_active(status: Optional[str]) -> bool:
    """True when the BSE status is active (or absent — the fetch filtered it)."""
    if status is None:
        return True
    return status.strip().lower() == _BSE_ACTIVE_STATUS


def _is_screenable_flag(value: Any) -> int:
    """Coerce a stored is_screenable cell to 0/1 (NULL means 'pre-provenance' → 1)."""
    if value is None:
        return 1
    try:
        return 1 if int(value) else 0
    except (TypeError, ValueError):
        return 1


class MasterSyncManager:
    """Orchestrates cross-exchange symbol discovery and universe categorization."""

    def __init__(self):
        self.repo = repo
        self.nse = nse_client
        self.bse = bse_client

    def sync_all(self) -> Dict[str, Any]:
        """
        Executes complete multi-exchange symbol master synchronization:
        1. Ingests NSE Equity Master (EQUITY_L.csv)
        2. Ingests BSE Scrip Master
        3. Cross-references Nifty 50, 100, 200, 500 constituents
        4. Admits BSE-only actives with listing_source='BSE_ONLY', is_screenable=0
        5. Deactivates a scrip only when absent from every liveness source
        6. Upserts merged records into master_companies
        """
        logger.info("Starting Master Company Synchronization...")

        # 0. Additive provenance columns (idempotent; no-op if already present)
        self.repo.ensure_universe_provenance_schema()

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

        # Build ISIN -> BSE info mapping (active rows only) plus the BSE liveness
        # set. Liveness is deliberately permissive: *every* active BSE row counts,
        # regardless of group/segment, so a strict admission guard can never turn
        # into a spurious delisting.
        bse_isin_map: Dict[str, Dict[str, Any]] = {}
        bse_active_isins: set = set()
        bse_rows: List[Tuple[str, Dict[str, Any]]] = []
        #: A failed/empty scrip master means one liveness source was never read,
        #: so absence from "every source" cannot be established this run.
        bse_available = bool(not df_bse.empty and "isin" in df_bse.columns)
        if not bse_available:
            logger.warning("BSE scrip master unavailable — BSE-only admission and the delisting sweep are skipped "
                           "for this run (absence from every exchange source is unproven)")
        if bse_available:
            for _, r in df_bse.iterrows():
                isin_code = _clean_text(r.get("isin"))
                info = _bse_row_info(r)
                if not _bse_is_active(info["bse_status"]):
                    logger.debug("BSE row %s ignored: status=%s", isin_code, info["bse_status"])
                    continue
                if isin_code:
                    bse_active_isins.add(isin_code)
                    bse_isin_map[isin_code] = info
                bse_rows.append((isin_code or "", info))

        # 4. Detect Lifecycle Events (New IPOs, Delistings, Renames)
        existing_companies = self.repo.get_all_companies(active_only=False)
        existing_isin_map = {c["isin"]: c for c in existing_companies}

        new_listings: List[str] = []
        renamed_symbols: List[Dict[str, str]] = []
        active_isin_set: set = set()
        # isin -> (listing_source, is_screenable) for every row this sync owns
        provenance: Dict[str, Tuple[str, int]] = {}

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
            # Provenance: dual-listed when the BSE master corroborates the ISIN.
            listing_source = "DUAL" if bse_info else "NSE"

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
                "listing_source": listing_source,
                "is_screenable": 1,
            }
            master_records.append(record)
            provenance[isin] = (listing_source, 1)

        # 4b. BSE-only admission. NSE wins on any ISIN it carries; a BSE-only
        # row joins the liveness set (so it is never swept as delisted) but not
        # the screened universe (is_screenable=0).
        bse_only_records: List[Dict[str, Any]] = []
        bse_only_skipped = {"known": 0, "collision": 0, "group": 0, "no_isin": 0}
        #: A ticker is unique across the universe: never emit a BSE symbol that
        #: already belongs to another company's nse_symbol (UNIQUE constraint).
        taken_symbols = {
            str(c["nse_symbol"]).strip().upper()
            for c in existing_companies
            if c.get("nse_symbol") and str(c["nse_symbol"]).strip()
        }
        taken_symbols |= {
            str(r["nse_symbol"]).strip().upper()
            for r in master_records
            if r.get("nse_symbol") and str(r["nse_symbol"]).strip()
        }
        known_isins = set(existing_isin_map) | set(provenance)

        for isin_code, info in bse_rows:
            if not isin_code:
                bse_only_skipped["no_isin"] += 1
                continue
            if isin_code in known_isins:
                # NSE (or a previous sync) already owns this ISIN.
                bse_only_skipped["known"] += 1
                continue
            if (info["bse_segment"] or "").lower() != _BSE_EQUITY_SEGMENT:
                # Non-equity segment (preference shares, debt…) — not the universe.
                bse_only_skipped["group"] += 1
                continue
            if (info["bse_group"] or "").strip().upper() in _BSE_EXCLUDED_GROUPS:
                bse_only_skipped["group"] += 1
                continue
            sym = info["bse_symbol"]
            if sym and sym.upper() in taken_symbols:
                bse_only_skipped["collision"] += 1
                continue

            company_name = info["bse_name"] or sym or isin_code
            industry = info["bse_industry"]  # NaN-safe → None when BSE has none
            bse_only_records.append({
                "isin": isin_code,
                "nse_symbol": sym,
                "bse_code": info["bse_code"],
                "company_name": company_name,
                "industry": industry,
                "sector": industry,
                "market_cap_tier": tier_from_market_cap(info["bse_mktcap_cr"]),
                "is_fno_eligible": 0,
                "is_nifty50": 0,
                "is_nifty100": 0,
                "is_nifty200": 0,
                "is_nifty500": 0,
                "is_active": 1,
                "listing_source": "BSE_ONLY",
                "is_screenable": 0,
            })
            provenance[isin_code] = ("BSE_ONLY", 0)
            if sym:
                taken_symbols.add(sym.upper())

        # 5. Detect and Flag Delisted / Suspended Scrips. A scrip is deactivated
        # only when its ISIN is absent from EVERY liveness source: NSE EQUITY_L,
        # the BSE active master (all groups/segments), and the currently-active
        # exempt-synthetic set (real-ISIN ETFs/index funds EQUITY_L omits).
        exempt_active_isins = {
            isin for isin, rec in existing_isin_map.items()
            if rec.get("is_active") == 1 and is_synthetic_instrument(rec)
        }
        liveness_isins = active_isin_set | bse_active_isins | exempt_active_isins

        delisted_count = 0
        if not bse_available:
            # Undecidable this run: an ISIN absent from NSE EQUITY_L may still be
            # alive on BSE, which we could not read. Never flag on partial evidence.
            logger.warning("Delisting sweep skipped: the BSE active scrip master was not read")
        else:
            with self.repo.db.session() as conn:
                for isin_id, ex_rec in existing_isin_map.items():
                    if ex_rec.get("is_active") != 1:
                        continue
                    if isin_id in liveness_isins:
                        continue
                    if str(isin_id).startswith("INE_AUTO_"):
                        continue
                    conn.execute("UPDATE master_companies SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE isin = ?", (isin_id,))
                    delisted_count += 1
                    logger.info("Flagged Delisted/Suspended company: %s (%s)", ex_rec.get("nse_symbol"), isin_id)

        if delisted_count:
            logger.info("Deactivated %d scrip(s) absent from NSE EQ, BSE active master and the exempt synthetic set",
                        delisted_count)

        # 6. Persist to SQLite
        inserted_count = self.repo.upsert_master_companies(master_records + bse_only_records)
        nifty200_count = sum(1 for r in master_records if r["is_nifty200"] == 1)

        # 6b. Persist provenance. Only counted when the stored value actually
        # changes, so a no-op re-sync reports 0.
        provenance_updated = 0
        if provenance:
            updates: List[Tuple[str, int, str]] = []
            for isin_code, (source, screenable) in provenance.items():
                ex_rec = existing_isin_map.get(isin_code)
                if (ex_rec is None
                        or ex_rec.get("listing_source") != source
                        or _is_screenable_flag(ex_rec.get("is_screenable")) != screenable):
                    provenance_updated += 1
                updates.append((source, screenable, isin_code))
            with self.repo.db.session() as conn:
                conn.executemany(
                    "UPDATE master_companies SET listing_source = ?, is_screenable = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE isin = ?",
                    updates,
                )

        logger.info("Master Sync Complete: Upserted %d active companies (%d new listings, %d delisted, %d renamed, "
                    "%d BSE-only added [skip: %s], %d provenance rows updated)",
                    inserted_count, len(new_listings), delisted_count, len(renamed_symbols),
                    len(bse_only_records), bse_only_skipped, provenance_updated)

        return {
            "total_upserted": inserted_count,
            "new_listings_discovered": len(new_listings),
            "delisted_flagged": delisted_count,
            "renamed_symbols_count": len(renamed_symbols),
            "bse_only_added": len(bse_only_records),
            "bse_only_skipped": bse_only_skipped,
            "provenance_updated": provenance_updated,
            "nifty50_count": len(n50_symbols),
            "nifty100_count": len(n100_symbols),
            "nifty200_count": nifty200_count,
            "nifty500_count": len(n500_symbols),
        }


# Alias for MasterSyncManager
MasterSync = MasterSyncManager

# Singleton sync manager
master_sync = MasterSyncManager()
