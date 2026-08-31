"""
Macro PDF Fetcher for Reality Engine (second-tier peer data below core company data)
====================================================================================

Ingests macro-policy PDFs that act as peer context for Indian-equity intelligence:

  * Central Budget speeches (Union Budget 2024-25 / 2025-26)
  * Economic Surveys (2024-25 / 2025-26)
  * 8 State Budgets (UP, Tamil Nadu, Maharashtra, Karnataka, Telangana,
    Gujarat, Haryana, Andhra Pradesh) for FY2024-25 / FY2025-26
  * PIB circulars (static.pib.gov.in / archive.pib.gov.in)
  * RBI Annual Reports / Financial Stability Reports

Design rules (AGENTS.md):
  * Dense substrate, raw_documents audit trail. Every downloaded file is recorded in
    ``raw_documents`` via ``repository.upsert_raw_document`` (sha256 dedup -> no
    double-counting of the same PDF even across fiscal years).
  * Graceful fallbacks: plain ``requests`` GET for allow-listed hosts
    (indiabudget.gov.in, static.pib.gov.in, *.nic.in, *.s3waas.gov.in, PreviewPage.do).
    Hosts behind JS/TSPD challenges (Gujarat, Andhra Pradesh) try the
    Playwright ``headless_fetcher.fetch_with_browser`` fallback if available; else
    they are logged + skipped — never crash. Tamil Nadu and Karnataka now serve
    direct (verified) budget-speech PDFs and use plain GET.
  * All writes are transactional through ``db_manager.session()``.

Fail-closed: any network/auth failure returns a structured result and is logged;
the CLI command still completes and reports counts.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse, parse_qs

import requests

try:  # Graceful: BeautifulSoup is preferred for robust link extraction.
    from bs4 import BeautifulSoup  # type: ignore
    _HAS_BS4 = True
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore
    _HAS_BS4 = False

from reality_engine.config import (
    MACRO_PDFS_DIR,
    CENTRAL_BUDGET_URLS,
    STATE_BUDGET_URLS,
    PIB_CIRCULAR_URLS,
    RBI_REPORT_URLS,
    RBI_LISTING_URLS,
    DEFAULT_HEADERS,
    macro_host_requires_browser,
)

logger = logging.getLogger("reality_engine.macro_pdf_fetcher")

# Browser-like User-Agent for document hosts that sniff.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Creator/ministry attribution per source_type.
_CREATOR_BY_SOURCE = {
    "Union_Budget": "Ministry of Finance (GoI)",
    "Economic_Survey": "Ministry of Finance (GoI)",
    "PIB_Circular": "Press Information Bureau (GoI)",
    "RBI_Annual_Report": "Reserve Bank of India",
    "RBI_Financial_Stability_Report": "Reserve Bank of India",
}


class MacroPDFFetcher:
    """Fetch and register macro-policy PDFs into the raw_documents audit trail."""

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        repo=None,
        rate_limit_sec: float = 1.0,
        max_retries: int = 3,
        timeout: int = 60,
        use_browser_fallback: bool = True,
    ):
        self.data_dir = Path(data_dir) if data_dir else MACRO_PDFS_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.repo = repo
        self.rate_limit_sec = max(0.0, float(rate_limit_sec))
        self.max_retries = max(1, int(max_retries))
        self.timeout = int(timeout)
        self.use_browser_fallback = use_browser_fallback
        self._last_call_ts = 0.0

    # -- repo access (lazy import to avoid circular imports) ----------------
    def _repo(self):
        if self.repo is not None:
            return self.repo
        from reality_engine.db.repository import repo as _repo

        self.repo = _repo
        return self.repo

    # -- capability / branching ---------------------------------------------
    def _browser_available(self) -> bool:
        """True only when the Playwright fallback can be used."""
        if not self.use_browser_fallback:
            return False
        try:
            from reality_engine.ingestion.headless_fetcher import is_playwright_available

            return bool(is_playwright_available())
        except Exception:
            return False

    @staticmethod
    def needs_browser(url: str) -> bool:
        """Exposed pure helper: does ``url`` require the browser fallback?"""
        return macro_host_requires_browser(url)

    # -- internal plumbing ---------------------------------------------------
    def _throttle(self) -> None:
        wait = self.rate_limit_sec - (time.monotonic() - self._last_call_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_call_ts = time.monotonic()

    def _category_dir(self, category: str, year: str) -> Path:
        d = self.data_dir / category / (year or "unknown")
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _sha256_file(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for blk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(blk)
        return h.hexdigest()

    def _download(self, url: str, dest: Path) -> Dict[str, Any]:
        """Download ``url`` to ``dest`` returning a structured result dict."""
        headers = {**DEFAULT_HEADERS, "User-Agent": _BROWSER_UA}
        last_err: Optional[str] = None
        for attempt in range(self.max_retries):
            try:
                self._throttle()
                resp = requests.get(url, headers=headers, timeout=self.timeout, stream=False)
                status = getattr(resp, "status_code", 0)
                body = resp.content if hasattr(resp, "content") else b""
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if status != 200 or len(body) < 100:
                    return {
                        "ok": False,
                        "status": status,
                        "is_pdf": False,
                        "reason": f"bad_status_or_empty(status={status},bytes={len(body)})",
                    }
                is_pdf = ("application/pdf" in ctype) or body[:5] == b"%PDF-"
                if not is_pdf:
                    # HTML listing page, not a direct PDF — treat as a soft skip.
                    return {
                        "ok": False,
                        "status": status,
                        "is_pdf": False,
                        "reason": "html_not_pdf",
                    }
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("wb") as f:
                    f.write(body)
                return {
                    "ok": True,
                    "status": status,
                    "is_pdf": True,
                    "path": str(dest),
                    "size": len(body),
                }
            except Exception as exc:  # pragma: no cover - network dependent
                last_err = str(exc)
                backoff = min(self.rate_limit_sec * (2 ** attempt), 10.0)
                time.sleep(backoff)
        return {"ok": False, "is_pdf": False, "reason": f"exception:{last_err}"}

    def _download_via_browser(self, url: str, dest: Path) -> Dict[str, Any]:
        """Best-effort browser download via headless_fetcher (fail-closed)."""
        try:
            from reality_engine.ingestion.headless_fetcher import fetch_with_browser
        except Exception as exc:  # pragma: no cover
            return {"ok": False, "is_pdf": False, "reason": f"import_error:{exc}"}
        try:
            self._throttle()
            resp = fetch_with_browser(url, headers={"User-Agent": _BROWSER_UA}, timeout=self.timeout)
        except Exception as exc:  # pragma: no cover
            return {"ok": False, "is_pdf": False, "reason": f"browser_error:{exc}"}
        if resp is None:
            return {"ok": False, "is_pdf": False, "reason": "browser_returned_none"}
        try:
            body = getattr(resp, "content", None) or getattr(resp, "body", None) or b""
            if isinstance(body, str):
                body = body.encode("utf-8", "ignore")
            headers = getattr(resp, "headers", {}) or {}
            ctype = (headers.get("Content-Type") if isinstance(headers, dict) else "").lower()
            is_pdf = ("application/pdf" in ctype) or (body[:5] == b"%PDF-")
            if not is_pdf or len(body) < 100:
                return {"ok": False, "is_pdf": False, "reason": "browser_html_not_pdf"}
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as f:
                f.write(body)
            return {"ok": True, "is_pdf": True, "path": str(dest), "size": len(body)}
        except Exception as exc:  # pragma: no cover
            return {"ok": False, "is_pdf": False, "reason": f"browser_write_error:{exc}"}

    # -- listing / link discovery helpers -----------------------------------
    @staticmethod
    def _sanitize_filename(url: str, fallback: str = "document.pdf") -> str:
        """Derive a legal Windows filename from a (possibly query-laden) URL.

        * Strips the query string / fragment.
        * If the URL carries a ``fileName=`` query param (Telangana PreviewPage.do),
          uses that value as the base name.
        * Removes illegal Windows characters: ``< > : " / \\ | ? * %`` and any
          leftover ``? & =`` so paths like ``PreviewPage.do?filePath=...&fileName=...``
          no longer raise ``Errno 22``.
        * Guarantees a ``.pdf`` extension.
        """
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "fileName" in qs and qs["fileName"]:
            name = qs["fileName"][0]
        else:
            name = parsed.path.rstrip("/").split("/")[-1]
        # Drop query/fragment remnants and illegal Windows characters.
        name = name.split("?")[0].split("#")[0]
        name = re.sub(r'[<>:"/\\|?*%]', "", name)
        name = name.replace("&", "").replace("=", "")
        if not name:
            name = fallback
        if not name.lower().endswith(".pdf"):
            # Avoid double extension if a stray .pdf-ish token existed.
            if ".pdf" in name.lower():
                name = name[: name.lower().rindex(".pdf") + 4]
            else:
                name = f"{name}.pdf"
        return name

    @classmethod
    def _extract_pdf_links(cls, html: str, base_url: str) -> List[str]:
        """Return absolute PDF URLs found in ``html`` (order-preserving, deduped)."""
        if not html:
            return []
        links: List[str] = []
        if _HAS_BS4 and BeautifulSoup is not None:
            try:
                soup = BeautifulSoup(html, "html.parser")
                for tag in soup.find_all(["a", "area"], href=True):
                    href = tag["href"].strip()
                    if href.lower().endswith(".pdf"):
                        links.append(urljoin(base_url, href))
            except Exception:  # pragma: no cover - fall through to regex
                links = []
        if not links:  # regex fallback
            for m in re.findall(r'href=["\']([^"\']+\.pdf)["\']', html, re.IGNORECASE):
                links.append(urljoin(base_url, m))
        # Dedupe preserving order.
        seen: set = set()
        out: List[str] = []
        for l in links:
            if l not in seen:
                seen.add(l)
                out.append(l)
        return out

    @classmethod
    def _extract_sublinks(cls, html: str, base_url: str, max_links: int = 8) -> List[str]:
        """Return absolute sub-page links (html/aspx/do/php) for one-level crawl."""
        if not html:
            return []
        subs: List[str] = []
        if _HAS_BS4 and BeautifulSoup is not None:
            try:
                soup = BeautifulSoup(html, "html.parser")
                for tag in soup.find_all("a", href=True):
                    href = tag["href"].strip()
                    low = href.lower()
                    if any(low.endswith(ext) for ext in (".html", ".htm", ".aspx", ".do", ".php")):
                        abs_href = urljoin(base_url, href)
                        if abs_href not in subs:
                            subs.append(abs_href)
            except Exception:  # pragma: no cover
                subs = []
        if not subs:  # regex fallback
            for m in re.findall(r'href=["\']([^"\']+\.(?:html|htm|aspx|do|php))["\']', html, re.IGNORECASE):
                abs_href = urljoin(base_url, m)
                if abs_href not in subs:
                    subs.append(abs_href)
        return subs[:max_links]

    def _fetch_listing_html(self, listing_url: str) -> Optional[str]:
        """Fetch a listing page's HTML: plain GET first, browser fallback if needed.

        Returns the decoded HTML string, or None if neither path succeeds. This is
        used by ``_fetch_from_listing`` so HTML->PDF discovery works for both
        server-rendered pages (plain GET) and JS-rendered pages (browser navigate).
        """
        headers = {**DEFAULT_HEADERS, "User-Agent": _BROWSER_UA}
        # 1) Plain GET (works for server-rendered listings such as AP/MH/HR).
        try:
            self._throttle()
            resp = requests.get(listing_url, headers=headers, timeout=self.timeout)
            if getattr(resp, "status_code", 0) == 200:
                body = resp.content if hasattr(resp, "content") else b""
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "text" in ctype or body[:1] in (b"<", b"{", b" "):
                    return body.decode("utf-8", "ignore")
        except Exception:
            pass
        # 2) Browser fallback (JS-rendered listings such as TN/GJ when available).
        if self._browser_available():
            try:
                from reality_engine.ingestion.headless_fetcher import fetch_with_browser
                resp = fetch_with_browser(listing_url, headers={"User-Agent": _BROWSER_UA}, timeout=self.timeout)
                if resp is not None:
                    body = getattr(resp, "content", None) or b""
                    if isinstance(body, str):
                        return body
                    if body:
                        return body.decode("utf-8", "ignore")
            except Exception:
                pass
        return None

    def _fetch_from_listing(
        self,
        listing_url: str,
        *,
        title: str,
        source_type: str,
        year: str,
        fiscal_period: Optional[str],
        creator: Optional[str],
        category: str,
        published_date: Optional[str] = None,
        keyword: Optional[str] = None,
        max_pdfs: int = 3,
    ) -> List[Dict[str, Any]]:
        """Discover PDFs from a listing page and download the relevant ones.

        Strategy:
          * Fetch the listing HTML (plain GET, browser fallback).
          * Extract *.pdf links. If none, follow up to 8 sub-pages one level deep and
            collect their PDF links (handles JS/click-navigated budgets such as TN/GJ).
          * Optionally filter by ``keyword`` (e.g. 'budget' / 'ANNUALREPORT').
          * Download up to ``max_pdfs`` (closest to the top of the listing).
        Fail-closed: returns an empty list (or a single failure dict) on any error.
        """
        html = self._fetch_listing_html(listing_url)
        if not html:
            logger.warning("Listing fetch failed for %s (skipped)", listing_url)
            return [{"ok": False, "skipped": False, "reason": "listing_fetch_failed", "url": listing_url}]
        pdfs = self._extract_pdf_links(html, listing_url)
        if not pdfs:
            for sub in self._extract_sublinks(html, listing_url):
                sub_html = self._fetch_listing_html(sub)
                if sub_html:
                    pdfs.extend(self._extract_pdf_links(sub_html, sub))
        if not pdfs:
            return [{"ok": False, "skipped": False, "reason": "no_pdf_links_found", "url": listing_url}]
        if keyword:
            filtered = [p for p in pdfs if keyword.lower() in p.lower()]
            if filtered:
                pdfs = filtered
        pdfs = pdfs[: max(0, int(max_pdfs))]
        results: List[Dict[str, Any]] = []
        for p in pdfs:
            dest = self._category_dir(category, year or "unknown") / self._sanitize_filename(p, fallback=f"{source_type}_{year}.pdf")
            res = self._fetch_one(
                url=p,
                dest=dest,
                title=title,
                source_type=source_type,
                published_date=published_date or self._published_date_for_year(year),
                fiscal_period=fiscal_period,
                creator=creator,
            )
            res["url"] = p
            results.append(res)
        return results

    def _fetch_one(
        self,
        url: str,
        dest: Path,
        *,
        title: str,
        source_type: str,
        published_date: str,
        fiscal_period: Optional[str],
        creator: Optional[str],
    ) -> Dict[str, Any]:
        """Fetch one URL, dedup by sha256, and register in raw_documents."""
        # Skip if the same file already registered (audit-trail dedup).
        if dest.exists():
            try:
                sha = self._sha256_file(dest)
                existing = self._repo().get_raw_document_by_hash(sha)
                if existing:
                    return {
                        "ok": True,
                        "skipped": True,
                        "reason": "already_registered",
                        "doc_id": existing.get("doc_id"),
                        "path": str(dest),
                        "source_type": source_type,
                        "title": title,
                        "fiscal_period": fiscal_period,
                        "published_date": published_date,
                        "source_url": url,
                        "creator_or_ministry": creator or _CREATOR_BY_SOURCE.get(source_type),
                    }
            except Exception:
                pass

        if self.needs_browser(url):
            if self._browser_available():
                res = self._download_via_browser(url, dest)
            else:
                logger.warning("Skipping %s: requires browser and fallback unavailable", url)
                return {"ok": False, "skipped": False, "reason": "browser_required_unavailable"}
        else:
            res = self._download(url, dest)

        if not res.get("ok"):
            logger.warning("Fetch failed for %s: %s", url, res.get("reason"))
            return res

        try:
            sha = self._sha256_file(dest)
            record = {
                "title": title,
                "source_type": source_type,
                "published_date": published_date,
                "fiscal_period": fiscal_period,
                "source_url": url,
                "creator_or_ministry": creator or _CREATOR_BY_SOURCE.get(source_type),
                "sha256_hash": sha,
                "local_file_path": str(dest),
                "file_size_bytes": res.get("size", dest.stat().st_size if dest.exists() else 0),
            }
            doc_id = self._repo().upsert_raw_document(record)
            res["doc_id"] = doc_id
            res["sha256"] = sha
            # Carry attribution metadata so callers (e.g. CLI --ingest) can push
            # the file into the dense substrate without re-deriving it.
            res.update(
                {
                    "source_type": source_type,
                    "title": title,
                    "fiscal_period": fiscal_period,
                    "published_date": published_date,
                    "source_url": url,
                    "creator_or_ministry": creator or _CREATOR_BY_SOURCE.get(source_type),
                    "path": str(dest),
                }
            )
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to register %s in raw_documents: %s", url, exc)
            res["register_error"] = str(exc)
        return res

    # -- public fetchers -----------------------------------------------------
    def fetch_central_budgets(self, years: Optional[List[str]] = None) -> Dict[str, Any]:
        """Download Union Budget speeches + Economic Surveys for ``years``."""
        years = years or ["2024-25", "2025-26"]
        results: List[Dict[str, Any]] = []
        for entry in CENTRAL_BUDGET_URLS:
            if entry.get("year") not in years:
                continue
            st = entry["source_type"]
            cat = "central_budgets" if st == "Union_Budget" else "central_surveys"
            dest = self._category_dir(cat, entry.get("year", "unknown")) / Path(entry["url"]).name
            res = self._fetch_one(
                url=entry["url"],
                dest=dest,
                title=entry["title"],
                source_type=st,
                published_date=self._published_date_for(entry),
                fiscal_period=entry.get("fiscal_period"),
                creator=None,
            )
            res["url"] = entry["url"]
            results.append(res)
        return self._summarize(results)

    def fetch_state_budgets(
        self,
        states: Optional[List[str]] = None,
        years: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Download the 8 state budgets for requested ``states`` x ``years``."""
        years = years or ["2024-25", "2025-26"]
        states = states or list(STATE_BUDGET_URLS.keys())
        results: List[Dict[str, Any]] = []
        for state_code in states:
            state = STATE_BUDGET_URLS.get(state_code)
            if not state:
                logger.warning("Unknown state code: %s (skipped)", state_code)
                continue
            for yr in years:
                yr_entry = state.get(yr)
                if not yr_entry:
                    continue
                # max_pdfs override (default 2). A value <= 0 is an explicit,
                # intentional skip — used when a listing page yields only
                # non-budget documents (e.g. org charts / notifications) and no
                # reliable direct speech PDF could be discovered, so we avoid
                # polluting raw_documents with mislabeled files.
                max_pdfs = int(yr_entry.get("max_pdfs", 2))
                if max_pdfs <= 0:
                    logger.info(
                        "Skipping %s %s: max_pdfs=0 (no reliable direct budget PDF discovered)",
                        state_code, yr,
                    )
                    continue
                url = yr_entry["url"]
                listing_url = yr_entry.get("listing_url")
                headless_ok = yr_entry.get("headless_ok", True)
                cat = f"state_{state_code}"
                is_direct_pdf = url.lower().endswith(".pdf") and headless_ok
                common = dict(
                    title=f"{state['name']} Budget {yr}",
                    source_type=f"State_Budget_{state_code}",
                    published_date=self._published_date_for_year(yr),
                    fiscal_period=f"FY{yr}",
                    creator=f"{state['name']} Finance Dept",
                )
                if is_direct_pdf:
                    # Direct GET; if it fails (e.g. stale hashed s3waas URL 404s),
                    # fall back to listing discovery when a listing_url is provided.
                    dest = self._category_dir(cat, yr) / self._sanitize_filename(url, fallback=f"budget_{state_code}_{yr}.pdf")
                    res = self._fetch_one(url=url, dest=dest, **common)
                    res["url"] = url
                    res["headless_ok"] = headless_ok
                    results.append(res)
                    if (not res.get("ok")) and listing_url:
                        logger.info("Direct %s failed; discovering via listing %s", url, listing_url)
                        for r in self._fetch_from_listing(
                            listing_url, category=cat, year=yr, keyword="budget", max_pdfs=max_pdfs, **common
                        ):
                            r["headless_ok"] = headless_ok
                            results.append(r)
                else:
                    # HTML listing (JS-rendered or server-rendered). Discover PDFs.
                    lu = listing_url or url
                    for r in self._fetch_from_listing(
                        lu, category=cat, year=yr, keyword="budget", max_pdfs=max_pdfs, **common
                    ):
                        r["headless_ok"] = headless_ok
                        results.append(r)
        return self._summarize(results)

    def fetch_pib_circulars(
        self,
        limit: int = 10,
        since_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Download PIB circular PDFs from the configured allow-list.

        ``limit`` caps the number processed; ``since_date`` (YYYY-MM-DD) filters by
        the date parsed from the PIB URL path. Hosts on the allow-list use plain
        GET; PIB is headless-friendly so this rarely needs the browser path.
        """
        candidates = list(PIB_CIRCULAR_URLS)
        if since_date:
            candidates = [
                c for c in candidates
                if (self._parse_pib_date(c["url"]) or "0000-00-00") >= since_date
            ]
        candidates = candidates[: max(0, int(limit))]
        results: List[Dict[str, Any]] = []
        for entry in candidates:
            url = entry["url"]
            dest = self._category_dir("pib", (self._published_date_for(entry) or "unknown")[:4]) / Path(url).name
            res = self._fetch_one(
                url=url,
                dest=dest,
                title=entry.get("title", "PIB Circular"),
                source_type="PIB_Circular",
                published_date=self._parse_pib_date(url) or self._published_date_for(entry),
                fiscal_period=None,
                creator=None,
            )
            res["url"] = url
            results.append(res)
        return self._summarize(results)

    def fetch_rbi_reports(self, years: Optional[List[str]] = None) -> Dict[str, Any]:
        """Download RBI annual / stability reports for ``years`` via listing discovery.

        The rbidocs.rbi.org.in PDF URLs use volatile hashed filenames that 404 between
        publishing cycles, so we resolve the live PDF by parsing the RBI listing page
        (``RBI_LISTING_URLS``) and downloading via plain GET — verified to return real
        ``%PDF-1.6`` bytes with no TSPD challenge. Falls back to the hardcoded URL only
        if discovery yields nothing (graceful — never crashes).
        """
        years = years or ["2024-25", "2025-26"]
        results: List[Dict[str, Any]] = []
        for entry in RBI_REPORT_URLS:
            if entry.get("year") not in years:
                continue
            st = entry["source_type"]
            cfg = RBI_LISTING_URLS.get(st)
            discovered = False
            if cfg:
                year_numeric = cfg.get("year_map", {}).get(entry.get("year")) or entry.get("year")
                listing_url = cfg["url_template"].format(year_numeric=year_numeric)
                lst = self._fetch_from_listing(
                    listing_url,
                    title=entry.get("title", "RBI Report"),
                    source_type=st,
                    year=entry.get("year", "unknown"),
                    fiscal_period=entry.get("fiscal_period"),
                    creator=None,
                    category="rbi",
                    keyword=cfg.get("keyword"),
                    max_pdfs=cfg.get("max_pdfs", 1),
                )
                for r in lst:
                    results.append(r)
                discovered = any(r.get("ok") for r in lst)
            if not discovered:
                # Fallback: try the (possibly stale) hardcoded URL directly.
                url = entry["url"]
                dest = self._category_dir("rbi", entry.get("year", "unknown")) / self._sanitize_filename(url)
                res = self._fetch_one(
                    url=url,
                    dest=dest,
                    title=entry.get("title", "RBI Report"),
                    source_type=st,
                    published_date=self._published_date_for_year(entry.get("year")),
                    fiscal_period=entry.get("fiscal_period"),
                    creator=None,
                )
                res["url"] = url
                results.append(res)
        return self._summarize(results)

    def run_all(
        self,
        years: Optional[List[str]] = None,
        states: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Fetch every macro source (central, states, PIB, RBI)."""
        years = years or ["2024-25", "2025-26"]
        out: Dict[str, Any] = {}
        out["central"] = self.fetch_central_budgets(years=years)
        out["states"] = self.fetch_state_budgets(states=states, years=years)
        out["pib"] = self.fetch_pib_circulars(limit=10)
        out["rbi"] = self.fetch_rbi_reports(years=years)
        return out

    # -- dry-run planning ----------------------------------------------------
    def plan(
        self,
        source: str = "all",
        years: Optional[List[str]] = None,
        states: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Return the planned URL set without downloading (for --dry-run)."""
        years = years or ["2024-25", "2025-26"]
        states = states or list(STATE_BUDGET_URLS.keys())
        plan: Dict[str, List[Dict[str, str]]] = {}
        if source in ("central", "all"):
            plan["central"] = [
                {"url": e["url"], "source_type": e["source_type"], "year": e.get("year")}
                for e in CENTRAL_BUDGET_URLS if e.get("year") in years
            ]
        if source in ("states", "all"):
            st_plan = []
            for sc in states:
                st = STATE_BUDGET_URLS.get(sc)
                if not st:
                    continue
                for yr in years:
                    ye = st.get(yr)
                    if ye:
                        st_plan.append({
                            "url": ye["url"], "source_type": f"State_Budget_{sc}",
                            "year": yr, "headless_ok": str(ye.get("headless_ok", True)),
                        })
            plan["states"] = st_plan
        if source in ("pib", "all"):
            plan["pib"] = [{"url": e["url"], "source_type": "PIB_Circular"} for e in PIB_CIRCULAR_URLS]
        if source in ("rbi", "all"):
            plan["rbi"] = [
                {"url": e["url"], "source_type": e["source_type"], "year": e.get("year")}
                for e in RBI_REPORT_URLS if e.get("year") in years
            ]
        plan["_total"] = sum(len(v) for k, v in plan.items() if k != "_total")
        return plan

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _published_date_for_year(yr: Optional[str]) -> str:
        if not yr:
            return "2026-08-14"
        # Budget-day assumptions: 2024-25 -> 2024-07-23, 2025-26 -> 2025-02-01.
        return "2024-07-23" if yr == "2024-25" else ("2025-02-01" if yr == "2025-26" else "2026-08-14")

    @staticmethod
    def _published_date_for(entry: Dict[str, Any]) -> str:
        # Allow explicit published_date in entry; else derive from year.
        if entry.get("published_date"):
            return entry["published_date"]
        return MacroPDFFetcher._published_date_for_year(entry.get("year"))

    @staticmethod
    def _parse_pib_date(url: str) -> Optional[str]:
        """Best-effort parse of YYYY/mon from a static.pib.gov.in URL path."""
        import re

        m = re.search(r"/(\d{4})/([a-z]{3})/", url)
        if not m:
            return None
        year = int(m.group(1))
        mon = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }.get(m.group(2).lower())
        if not mon:
            return None
        return f"{year:04d}-{mon:02d}-01"

    @staticmethod
    def _summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
        fetched = sum(1 for r in results if r.get("ok") and not r.get("skipped"))
        skipped = sum(1 for r in results if r.get("skipped"))
        failed = sum(1 for r in results if not r.get("ok") and not r.get("skipped"))
        return {
            "total": len(results),
            "fetched": fetched,
            "skipped": skipped,
            "failed": failed,
            "details": results,
        }


# Convenience module-level helpers ------------------------------------------------
def fetch_all_macro(
    years: Optional[List[str]] = None,
    states: Optional[List[str]] = None,
    rate_limit_sec: float = 1.0,
) -> Dict[str, Any]:
    """Module-level entry point: fetch all macro PDF sources."""
    fetcher = MacroPDFFetcher(rate_limit_sec=rate_limit_sec)
    return fetcher.run_all(years=years, states=states)


__all__ = ["MacroPDFFetcher", "fetch_all_macro"]
