"""
Delisting / NCLT (Insolvency) Status Client.

GOAL (user request): determine how to fetch whether a stock is delisted or has
gone into NCLT (National Company Law Tribunal) insolvency proceedings (CIRP/IBC).

REALITY OF SOURCES (probed 2026-08-28):
    * NSE delisted/suspended API endpoints return 404 (no public JSON feed).
    * BSE ListOfDelistedScrips / ListOfSuspendedScrips JSON APIs return an HTML
      error page WITHOUT the browser-issued JWT cookie (same blocker as the
      financials route) — not bulk-reachable from this environment.
    * IBBI (the statutory insolvency registry) has no open bulk API.
    => The canonical "delisted list" / "NCLT list" feeds are NOT reachable here.
       We do NOT fabricate them.

WORKING SIGNAL WE CAN BUILD (rule-compliant, no fabrication):
    1. DERIVED flag: any scrip absent from the active NSE/BSE master (or marked
       is_active=0) is effectively delisted/suspended in our universe.
    2. ANNOUNCEMENT SCAN: NCLT / CIRP / insolvency disclosures arrive as exchange
       corporate announcements. We scan already-ingested `corporate_documents`
       (concall/annual-report/presentation links + titles) and `corporate_actions`
       subjects for insolvency keywords and emit an NCLT_CIRP / INSOLVENCY_RISK flag
       with the source document reference. This reuses data we already pulled.

This client is therefore a COMPOSER: it attempts the official feed (fail-closed)
and, as the reliable path, derives/scan flags from our own ingested data.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from reality_engine.db.repository import repo as _repo

logger = logging.getLogger("reality_engine.delisting_nclt_client")

SOURCE_DERIVED = "derived"
SOURCE_ANNOUNCEMENT_SCAN = "announcement_scan"
SOURCE_NSE = "nse_official"
SOURCE_BSE = "bse_official"

# Insolvency / NCLT keyword patterns (case-insensitive, word-boundary-ish).
_NCLT_PATTERNS = [
    r"\bNCLT\b",
    r"\bCIRP\b",
    r"\bIBC\b",
    r"insolvency",
    r"resolution professional",
    r"corporate insolvency",
    r"moratorium",
    r"\bNCLAT\b",
]
_DELIST_PATTERNS = [
    r"delist",
    r"voluntary delisting",
    r"compulsory delisting",
    r"exit from listing",
    r"revocation of listing",
]
_SUSPEND_PATTERNS = [
    r"suspend",
    r"trading suspended",
    r"under suspension",
]

_COMPILED = {
    "NCLT_CIRP": [re.compile(p, re.IGNORECASE) for p in _NCLT_PATTERNS],
    "DELISTED": [re.compile(p, re.IGNORECASE) for p in _DELIST_PATTERNS],
    "SUSPENDED": [re.compile(p, re.IGNORECASE) for p in _SUSPEND_PATTERNS],
}


def _match_status(text: str) -> Optional[str]:
    if not text:
        return None
    for status, pats in _COMPILED.items():
        if any(p.search(text) for p in pats):
            return status
    return None


class DelistingNCLTClient:
    """Composes delisting/NCLT status from derived + announcement-scan signals."""

    # ------------------------------------------------------------------
    # 1. Attempt official delisted feed (fail-closed; documented blocked)
    # ------------------------------------------------------------------
    def fetch_official_delisted(self) -> List[Dict[str, Any]]:
        """Attempt the canonical BSE delisted/suspended lists via headless browser.

        The BSE ``ListOfDelistedScrips`` / ``ListOfSuspendedScrips`` JSON APIs return
        an HTML error page WITHOUT the browser-issued JWT cookie. We attempt a
        headless-browser fetch (which replays the browser cookie/JWT) so the endpoint
        is reachable when Playwright is installed. Fail-closed: if Playwright is
        unavailable, or the fetch/parse fails, we return [] and callers fall back to
        the derived + announcement-scan signals. We never fabricate records.
        """
        try:  # Lazy, fail-closed import — module import never breaks without playwright.
            from reality_engine.ingestion.headless_fetcher import (
                is_playwright_available,
                fetch_json_with_browser,
            )
            from reality_engine.config import BSE_DELISTED_URL, BSE_SUSPENDED_URL
        except Exception as exc:  # pragma: no cover
            logger.debug("delisting_nclt: headless_fetcher unavailable: %s", exc)
            return []

        if not is_playwright_available():
            logger.info(
                "Official delisted/suspended feeds need a browser-issued JWT; "
                "Playwright not available -> skipping (rely on derived + scan signals)."
            )
            return []

        flags: List[Dict[str, Any]] = []
        endpoints = [
            (BSE_DELISTED_URL, "DELISTED"),
            (BSE_SUSPENDED_URL, "SUSPENDED"),
        ]
        for url, status_type in endpoints:
            try:
                payload = fetch_json_with_browser(url, timeout=30)
                if not payload:
                    continue
                for r in self._normalize_bse_list(payload):
                    flags.append({
                        "isin": None,
                        "symbol": r.get("symbol"),
                        "status_type": status_type,
                        "source": SOURCE_BSE,
                        "detail": r.get("detail", ""),
                    })
            except Exception as exc:  # pragma: no cover - network/parse dependent
                logger.debug("delisting_nclt: BSE %s fetch failed: %s", status_type, exc)
        return flags

    @staticmethod
    def _normalize_bse_list(payload: Any) -> List[Dict[str, str]]:
        """Best-effort normalization of a BSE delisted/suspended JSON payload.

        BSE returns ``{"Table": [...]}`` (or a bare list) where each row carries a
        scrip-code field and a company-name field under varying key names. Extraction
        is defensive: any row lacking both a code and a name is skipped (fail-closed,
        no fabrication).
        """
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = payload.get("Table") or payload.get("table") or []
        else:
            return []
        if not isinstance(rows, list):
            return []

        out: List[Dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = (
                row.get("SCRIP_CODE") or row.get("Scrip_Cd") or row.get("scrip_code")
                or row.get("Scrip_Code") or row.get("CODE") or row.get("Code")
                or row.get("scripCd") or ""
            )
            name = (
                row.get("SCRIP_NAME") or row.get("Company_Name") or row.get("NAME")
                or row.get("CompanyName") or row.get("COMPANY_NAME") or ""
            )
            reason = (
                row.get("REASON_FOR_DELISTING") or row.get("Reason") or row.get("reason")
                or row.get("REASON") or ""
            )
            code = str(code).strip()
            name = str(name).strip()
            if not code and not name:
                continue
            detail = name
            if reason:
                detail = f"{name} :: {reason}" if name else str(reason)
            out.append({"symbol": code or name, "detail": detail[:200]})
        return out

    # ------------------------------------------------------------------
    # 2. Derived flag: scrips not in active master = delisted/suspended
    # ------------------------------------------------------------------
    def derive_from_master(self) -> List[Dict[str, Any]]:
        """Flag scrips that are inactive or missing from the active universe."""
        flags: List[Dict[str, Any]] = []
        with _repo.db.session() as conn:
            rows = conn.execute(
                "SELECT isin, nse_symbol, bse_code, company_name, is_active "
                "FROM master_companies WHERE is_active = 0"
            ).fetchall()
            for r in rows:
                sym = r["nse_symbol"] or r["bse_code"] or "UNKNOWN"
                flags.append({
                    "isin": r["isin"],
                    "symbol": sym,
                    "status_type": "DELISTED",
                    "source": SOURCE_DERIVED,
                    "detail": "isin absent from active NSE/BSE master (is_active=0)",
                })
        return flags

    # ------------------------------------------------------------------
    # 3. Announcement scan: NCLT/CIRP mentions in ingested documents/actions
    # ------------------------------------------------------------------
    def scan_announcements(self) -> List[Dict[str, Any]]:
        """Scan corporate_documents titles + corporate_actions subjects for insolvency keywords."""
        flags: List[Dict[str, Any]] = []
        with _repo.db.session() as conn:
            # Scanned document titles we have discovered links for.
            docs = conn.execute(
                "SELECT DISTINCT symbol, title, doc_type FROM corporate_documents "
                "WHERE title IS NOT NULL"
            ).fetchall()
            for d in docs:
                st = _match_status(d["title"])
                if st:
                    flags.append({
                        "isin": None,
                        "symbol": d["symbol"],
                        "status_type": st,
                        "source": SOURCE_ANNOUNCEMENT_SCAN,
                        "detail": f"{d['doc_type']}: {d['title'][:120]}",
                    })
            # Corporate action subjects (e.g. delisting/exit notices).
            acts = conn.execute(
                "SELECT DISTINCT symbol, subject FROM corporate_actions WHERE subject IS NOT NULL"
            ).fetchall()
            for a in acts:
                st = _match_status(a["subject"])
                if st:
                    flags.append({
                        "isin": None,
                        "symbol": a["symbol"],
                        "status_type": st,
                        "source": SOURCE_ANNOUNCEMENT_SCAN,
                        "detail": f"corporate_action: {a['subject'][:120]}",
                    })
        return flags

    # ------------------------------------------------------------------
    # Compose all signals
    # ------------------------------------------------------------------
    def build_flags(self) -> Dict[str, Any]:
        official = self.fetch_official_delisted()
        derived = self.derive_from_master()
        scanned = self.scan_announcements()
        all_flags = official + derived + scanned
        return {
            "official": official,
            "derived": derived,
            "scanned": scanned,
            "all": all_flags,
            "counts": {
                "official": len(official),
                "derived_delisted": len(derived),
                "scanned": len(scanned),
                "total": len(all_flags),
            },
        }

    def persist_flags(self) -> int:
        """Persist composed flags to corporate_status_flags (idempotent upsert)."""
        result = self.build_flags()
        if not result["all"]:
            return 0
        defaults = {"isin": None, "symbol": None, "status_type": "OTHER",
                    "source": "derived", "detail": None}
        records = [{**defaults, **f} for f in result["all"]]
        # Dedupe by (symbol, status_type, source)
        seen = set()
        uniq = []
        for r in records:
            k = (r["symbol"], r["status_type"], r["source"])
            if k not in seen:
                seen.add(k)
                uniq.append(r)
        try:
            # Preferred path: typed repository upsert (handles defaults + idempotency).
            return _repo.upsert_corporate_status_flags(uniq)
        except Exception as exc:
            # Fallback to raw SQL if the repository method is unavailable or fails
            # (e.g. table missing on a very old DB not covered by runtime migration).
            logger.warning(
                "repo.upsert_corporate_status_flags failed (%s); using raw SQL fallback",
                exc,
            )
            with _repo.db.session() as conn:
                conn.executemany(
                    """
                    INSERT INTO corporate_status_flags (isin, symbol, status_type, source, detail)
                    VALUES (:isin, :symbol, :status_type, :source, :detail)
                    ON CONFLICT(symbol, status_type, source) DO UPDATE SET
                        detail = excluded.detail,
                        detected_at = CURRENT_TIMESTAMP;
                    """,
                    uniq,
                )
                return len(uniq)


# Singleton
delisting_nclt_client = DelistingNCLTClient()
