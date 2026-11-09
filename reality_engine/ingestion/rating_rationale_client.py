"""Credit-rating rationale fetcher (T-139).

Fetches the public rationale / press-release *text* for a company from the
Indian rating agencies, so questions about ratings, outlook, rating triggers
and the agency's stated strengths / weaknesses are answerable verbatim.

Agencies and the listing endpoint that worked (probed 2026-11-09)
------------------------------------------------------------------
CARE (CareEdge Ratings)
    listing: GET https://www.careratings.com/header/searchlistinsights?cinput=<name>
             -> JSON {"data":[{CompanyName, CommonContent:[{Title, PDf}]}]}
    doc:     https://www.careratings.com/upload/CompanyFiles/PR/<PDf>  (PDF)
    The search endpoint returns every company whose name matches the query;
    rows are filtered again by the exact company name.  File names are
    12-digit yyyymmddhhmm_<Company>.pdf (older ones 14-digit ddmmyyyyhhmmss).
CRISIL
    listing: GET https://www.crisilratings.com/bin/crisil/listing/
                rating_sme_listing_service.json?cmd=RR&start=<n>&limit=<end>
             -> JSON {"numFound":..., "docs":[{companyName, ratingDate,
                ratingFileName, prId, heading}]}, newest first.  `limit` is an
             end offset (the site's own load-more sends start=10&limit=20), and
             the list is one current release per rated entity.  No server-side
             company filter, so the whole list is scanned and filtered here.
    doc:     https://www.crisil.com/mnt/winshare/Ratings/RatingList/RatingDocs/<ratingFileName>
             (HTML)
ICRA
    listing: GET https://www.icra.in/Rating/AllRatingRationales?Keyword=<name>
             -> HTML table rows: date, sector, title, /Rationale/ShowRationaleReport?Id=<id>
    doc:     https://www.icra.in/Rating/ShowRationalReportFilePdfViewer/<id>  (PDF)
India Ratings (Ind-Ra)
    listing: GET https://www.indiaratings.co.in/home/
                GetSearchIssuerData_PressRelease_Research?searchKey=<name>&noOfShowEntry=10
             -> JSON press releases {pressReleaseID, pressReleaseTitle, effectiveDate}
    doc:     https://www.indiaratings.co.in/pressrelease/<id>
             The page is an Angular shell and the public detail JSON did not
             return text on 2026-11-09, so the announcement text is saved only
             when the site serves it as HTML; otherwise the row is skipped.
Acuite
    listing: GET https://connect.acuite.in/liveratings?page=1 paginates the
             live ratings; its company search is a POST form that answers 405
             to a direct POST, so only an exact-name match on page 1 is read
             (the pilot20 companies are not Acuite-rated; nothing is saved).
    doc:     https://connect.acuite.in/fcompany-details/<NAME>/<date> carries the
             press-release text as HTML.
Brickwork
    listing: https://www.brickworkratings.com/PressRelease.aspx is an ASP.NET
             WebForms page (__VIEWSTATE + CompanytxtSearch + btnSearch POST).
             The pilot20 companies are not Brickwork-rated, so no adapter is
             wired yet; add one when a Brickwork-rated company enters the set.
Moody's / S&P: ratings.moodys.com and disclosure.spglobal.com need a login;
    their action is read from the exchange announcement only, never fetched.

Storage is text only: HTML is stripped in memory, PDFs are read with PyMuPDF
in memory and never written to disk.  Layout:
    <out>/<SYMBOL>/<agency>_<YYYY-MM-DD>_<shortid>.txt
    <out>/index.csv

Usage:
    python -m reality_engine.ingestion.rating_rationale_client \
        --store D:/RealityEngine/p20/p20new.db --out .tmp/ratings_p20 \
        [--since 2024-04-01] [--symbols HAVELLS,TITAN] [--max-per-agency 4]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable

from reality_engine.db.readonly import connect_ro

log = logging.getLogger("rating_rationale")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
INDEX_FIELDS = [
    "symbol", "agency", "rating_date", "url", "instrument", "rating",
    "outlook", "action", "chars", "sha256", "fetched_at",
]
AGENCIES = ("CARE", "CRISIL", "ICRA", "INDRAT", "ACUITE")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def norm_name(value: str | None) -> str:
    """Company name -> lowercase alphanumerics, for robust comparison."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def company_key(value: str | None) -> str:
    """Legal name without the corporate suffix (for press-release headlines)."""
    text = norm_name(value)
    for suffix in ("limited", "ltd", "private", "pvt"):
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
    return text


def read_companies(store: Path, symbols: Iterable[str] | None = None) -> list[tuple[str, str]]:
    """Read (symbol, legal name) from the pilot store, read-only."""
    con = connect_ro(store)
    try:
        cursor = con.execute("SELECT symbol, name FROM company ORDER BY symbol")
        assert cursor is not None
        rows = cursor.fetchall() or []
    finally:
        con.close()
    wanted = {s.strip().upper() for s in symbols or [] if s.strip()}
    companies: dict[str, str] = {}
    for row in rows:
        symbol = str(row[0]).upper()
        if (not wanted or symbol in wanted) and row[1]:
            companies.setdefault(symbol, str(row[1]))
    return sorted(companies.items())


class RateLimiter:
    """Space requests to one host by at least ``min_interval`` seconds.

    ``clock`` and ``sleep`` are injectable so the test can prove the spacing
    without waiting.
    """

    def __init__(
        self,
        min_interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}

    def wait(self, host: str) -> None:
        now = self._clock()
        previous = self._last.get(host)
        if previous is not None:
            delay = self.min_interval - (now - previous)
            if delay > 0:
                self._sleep(delay)
                now = self._clock()
        self._last[host] = now


class Fetcher:
    """Tiny HTTP client: browser UA, per-host spacing and backoff on 429/5xx."""

    def __init__(self, limiter: RateLimiter | None = None, retries: int = 3) -> None:
        self.limiter = limiter or RateLimiter()
        self.retries = retries
        self._opener = urllib.request.build_opener()

    def get(self, url: str, accept: str = "*/*") -> bytes:
        host = urllib.parse.urlparse(url).netloc
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self.limiter.wait(host)
            request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
            try:
                with self._opener.open(request, timeout=60) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in (429, 500, 502, 503, 504) or attempt >= self.retries:
                    raise
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise
            time.sleep(2**attempt)
        raise RuntimeError(f"fetch failed: {url}: {last_error}")


class _TextExtractor(HTMLParser):
    """HTML -> readable text, skipping scripts, styles and navigation chrome."""

    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form"}
    BLOCK = {
        "p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "table", "thead", "tbody",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = raw.replace("\xa0", " ")
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r" *\n *", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    return parser.text()


def pdf_to_text(payload: bytes) -> str:
    """PDF bytes -> text, in memory (PyMuPDF 1.28, older fitz fallback)."""
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError:  # pragma: no cover - fallback for older installs
        import fitz  # type: ignore
    with fitz.open(stream=payload, filetype="pdf") as doc:
        return "\n\n".join(str(page.get_text()) for page in doc).strip()


_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def parse_date(value: str | None) -> str:
    """Best-effort date -> ISO yyyy-mm-dd; blank when the format is unknown."""
    if not value:
        return ""
    text = value.strip()
    for fmt in ("%d %b %Y", "%d %b %y", "%b %d, %Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    m = re.match(r"(\d{1,2})(?:st|nd|rd|th)? ([A-Za-z]{3})[a-z]* (\d{2,4})$", text)
    if m:
        day, month, year = int(m.group(1)), _MONTHS.get(m.group(2).title()), int(m.group(3))
        if month and 1 <= day <= 31:
            if year < 100:
                year += 2000
            return f"{year:04d}-{month:02d}-{day:02d}"
    return ""


def date_from_care_filename(filename: str) -> str:
    """CARE PDF name -> ISO date (12-digit ymmddhhmm or 14-digit ddmmyyyy...)."""
    stem = Path(filename).stem
    m = re.match(r"(20\d{10})_", stem)
    if m:
        return f"{m.group(1)[0:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}"
    m = re.match(r"(\d{2})(\d{2})(20\d{2})\d+_", stem)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.search(r"(\d{2})-(\d{2})-(20\d{2})", stem)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return ""


# ---------------------------------------------------------------------------
# rating / outlook / action parsing
# ---------------------------------------------------------------------------

_ACTION_WORDS = {
    "reaffirmed": "reaffirmed", "re-affirmed": "reaffirmed", "affirmed": "reaffirmed",
    "assigned": "assigned", "upgraded": "upgraded", "downgraded": "downgraded",
    "withdrawn": "withdrawn", "revised": "revised",
}

_RATING_RE = re.compile(
    r"(?P<rating>\[?(?:CRISIL|CARE|CAREEDGE|IND|ICRA|ACUITE|BWR)\]?\s*"
    r"[A-Z]{1,3}[0-9]?[A-Z0-9+\-]{0,4})"
    r"\s*(?:/\s*|;\s*|\(\s*|,?\s+)"
    r"(?P<outlook>Stable|Positive|Negative|Rating Watch (?:Positive|Negative|Developing))?"
    r"[^.;\n]{0,40}?"
    r"(?P<action>Reaffirmed|Re-affirmed|Affirmed|Assigned|Upgraded|Downgraded|Withdrawn|Revised)?",
    re.IGNORECASE,
)


def _canonical_action(word: str | None) -> str:
    return _ACTION_WORDS.get((word or "").lower().strip(" ;,()"), "")


_SCALE_RE = re.compile(
    r"^(?:\[?(?:CRISIL|CARE|CAREEDGE|IND|ICRA|ACUITE|BWR)\]?\s*)?"
    r"(AAA|AA[+-]?|A[+-]?|BBB[+-]?|BB[+-]?|B[+-]?|C|D|A[1-4]\+?)"
    r"(?:mfs|\(SO\))?$",
    re.IGNORECASE,
)


def _looks_like_rating(rating: str) -> bool:
    return bool(_SCALE_RE.match(rating))


def parse_rating_line(line: str) -> dict[str, str]:
    """Parse a single rating table line; blanks where unsure."""
    out = {"rating": "", "outlook": "", "action": "", "instrument": ""}
    match = _RATING_RE.search(line)
    if not match:
        return out
    rating = re.sub(r"\s+", " ", match.group("rating")).strip()
    if not _looks_like_rating(rating):
        return out
    outlook = (match.group("outlook") or "").strip()
    action = _canonical_action(match.group("action"))
    # an action word may sit just after the matched window
    if not action:
        for word, canonical in _ACTION_WORDS.items():
            if re.search(rf"\b{re.escape(word)}\b", line, re.IGNORECASE):
                action = canonical
                break
    out.update(rating=rating, outlook=outlook, action=action)
    instrument = re.search(
        r"((?:Long|Short)[ -]?Term[^\n:;]{0,80}?(?:Facilities|Facility|Debentures|NCDs?|"
        r"Bonds?|Ratings?|Loan))",
        line,
        re.IGNORECASE,
    )
    if instrument:
        out["instrument"] = re.sub(r"\s+", " ", instrument.group(1)).strip()
    return out


def parse_fields(text: str) -> dict[str, str]:
    """First rating line in the document -> instrument/rating/outlook/action."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for index, line in enumerate(lines[:200]):
        parsed = parse_rating_line(line)
        if not parsed["rating"]:
            continue
        if not parsed["action"]:
            for follow in lines[index + 1: index + 3]:
                action = _canonical_action(follow)
                if action:
                    parsed["action"] = action
                    break
        if not parsed["instrument"] and index:
            previous = lines[index - 1]
            if re.search(r"facilit|debenture|bond|loan|ncd|paper", previous, re.IGNORECASE):
                parsed["instrument"] = previous
        return parsed
    return {"rating": "", "outlook": "", "action": "", "instrument": ""}


# ---------------------------------------------------------------------------
# candidates
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    symbol: str
    company: str
    agency: str
    url: str
    rating_date: str
    title: str = ""
    shortid: str = ""


def _isolate(payload: bytes) -> str:
    return payload.decode("utf-8", "replace")


def care_candidates(company: str, fetcher: Fetcher, since: str, limit: int) -> list[Candidate]:
    url = "https://www.careratings.com/header/searchlistinsights?cinput=" + urllib.parse.quote(company)
    payload = json.loads(_isolate(fetcher.get(url, "application/json")))
    wanted = norm_name(company)
    found: list[Candidate] = []
    for entry in payload.get("data", []):
        if norm_name(entry.get("CompanyName")) != wanted:
            continue
        for item in entry.get("CommonContent", []):
            if norm_name(item.get("Title")) != wanted:
                continue
            pdf = str(item.get("PDf") or "").strip()
            rating_date = date_from_care_filename(pdf)
            if not pdf or not rating_date or rating_date < since:
                continue
            found.append(Candidate(
                symbol="", company=company, agency="CARE",
                url="https://www.careratings.com/upload/CompanyFiles/PR/" + urllib.parse.quote(pdf),
                rating_date=rating_date, title=item.get("Title") or company,
                shortid=Path(pdf).stem[:60],
            ))
    return sorted(found, key=lambda c: c.rating_date, reverse=True)[:limit]


_ICRA_ROW_RE = re.compile(
    r"<td[^>]*>\s*(\d{1,2} [A-Z][a-z]{2} \d{4})\s*</td>.*?"
    r'href="(/Rationale/ShowRationaleReport\?Id=(\d+))"[^>]*>\s*([^<]+?)\s*</a>',
    re.S,
)


def icra_candidates(company: str, fetcher: Fetcher, since: str, limit: int) -> list[Candidate]:
    url = "https://www.icra.in/Rating/AllRatingRationales?Keyword=" + urllib.parse.quote(company)
    markup = _isolate(fetcher.get(url))
    wanted = norm_name(company)
    found: list[Candidate] = []
    for row in _ICRA_ROW_RE.finditer(markup):
        date_text, href, report_id, title = row.group(1), row.group(2), row.group(3), row.group(4)
        title = re.sub(r"<[^>]+>", "", title).strip()
        head = norm_name(title.split(":")[0])
        if head != wanted and not head.startswith(wanted):
            continue
        rating_date = parse_date(date_text)
        if not rating_date or rating_date < since:
            continue
        found.append(Candidate(
            symbol="", company=company, agency="ICRA",
            url=f"https://www.icra.in/Rating/ShowRationalReportFilePdfViewer/{report_id}",
            rating_date=rating_date, title=title, shortid=report_id,
        ))
    return sorted(found, key=lambda c: c.rating_date, reverse=True)[:limit]


_CRISIL_URL = "https://www.crisilratings.com/bin/crisil/listing/rating_sme_listing_service.json"
_CRISIL_DOC_BASE = "https://www.crisil.com/mnt/winshare/Ratings/RatingList/RatingDocs/"


def crisil_scan(
    companies: list[str], fetcher: Fetcher, since: str, limit: int, page_size: int = 3000
) -> dict[str, list[Candidate]]:
    """Scan the CRISIL list newest-first; it has no server-side company filter.

    ``limit`` is an *end offset*, not a page size: the site's own pagination
    calls start=10&limit=20 for the second page.  So one request returns
    ``limit - start`` rows.
    """
    wanted = {norm_name(c): c for c in companies}
    found: dict[str, list[Candidate]] = {c: [] for c in companies}
    start = 0
    while start < 60_000:
        page_url = f"{_CRISIL_URL}?cmd=RR&start={start}&limit={start + page_size}&filters={{}}"
        payload = json.loads(_isolate(fetcher.get(page_url, "application/json")))
        docs = payload.get("docs") or []
        if not docs:
            break
        for doc in docs:
            key = norm_name(doc.get("companyName"))
            company = wanted.get(key)
            if company is None or len(found[company]) >= limit:
                continue
            rating_date = parse_date(doc.get("ratingDate")) or parse_date(doc.get("transDate"))
            if not rating_date or rating_date < since:
                continue
            filename = str(doc.get("ratingFileName") or "").strip()
            if not filename:
                continue
            found[company].append(Candidate(
                symbol="", company=company, agency="CRISIL",
                url=_CRISIL_DOC_BASE + urllib.parse.quote(filename).replace("%2F", "/"),
                rating_date=rating_date,
                title=str(doc.get("heading") or company),
                shortid=str(doc.get("prId") or Path(filename).stem)[:40],
            ))
        # The list is mostly newest-first but carries stray old rows, so a
        # single old row must not end the scan; scan to numFound instead.
        num_found = int(payload.get("numFound") or 0)
        if all(len(found[c]) >= limit for c in companies):
            break
        start += page_size
        if num_found and start >= num_found:
            break
    return found


_INDRAT_SEARCH = (
    "https://www.indiaratings.co.in/home/"
    "GetSearchIssuerData_PressRelease_Research?searchKey={query}&noOfShowEntry=20"
)


def indrat_candidates(company: str, fetcher: Fetcher, since: str, limit: int) -> list[Candidate]:
    # The Ind-Ra search is picky: the full legal name returns nothing, the
    # brand name (suffix removed) returns the press releases.
    query = re.sub(r"\b(?:limited|ltd|private|pvt|the)\b", "", company, flags=re.IGNORECASE)
    url = _INDRAT_SEARCH.format(query=urllib.parse.quote(re.sub(r"\s+", " ", query).strip()))
    payload = json.loads(_isolate(fetcher.get(url, "application/json")))
    key = company_key(company)
    found: list[Candidate] = []
    for item in payload if isinstance(payload, list) else []:
        title = str(item.get("pressReleaseTitle") or "")
        if key and key not in norm_name(title):
            continue
        rating_date = parse_date(item.get("effectiveDate")) or parse_date(item.get("prDate"))
        report_id = item.get("pressReleaseID")
        if not rating_date or not report_id or rating_date < since:
            continue
        found.append(Candidate(
            symbol="", company=company, agency="INDRAT",
            url=f"https://www.indiaratings.co.in/pressrelease/{report_id}",
            rating_date=rating_date, title=title, shortid=str(report_id),
        ))
    return sorted(found, key=lambda c: c.rating_date, reverse=True)[:limit]


_ACUITE_ROW_RE = re.compile(
    r'<th[^>]*class="td-date"[^>]*>\s*([^<]+?)\s*</th>\s*'
    r'<td[^>]*class="td-company"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>\s*([^<]+?)\s*</a>',
    re.S,
)


def acuite_candidates(company: str, fetcher: Fetcher, since: str, limit: int) -> list[Candidate]:
    # The site's company search is a POST form that refuses a direct POST;
    # page 1 of the live list is enough for the pilot set.
    url = "https://connect.acuite.in/liveratings?page=1"
    markup = _isolate(fetcher.get(url))
    wanted = norm_name(company)
    found: list[Candidate] = []
    for row in _ACUITE_ROW_RE.finditer(markup):
        date_text, href, title = row.group(1), row.group(2), row.group(3)
        if norm_name(title) != wanted:
            continue
        rating_date = parse_date(date_text)
        if not rating_date or rating_date < since:
            continue
        found.append(Candidate(
            symbol="", company=company, agency="ACUITE",
            url=urllib.parse.urljoin("https://connect.acuite.in/", href),
            rating_date=rating_date, title=title,
            shortid=hashlib.sha1(href.encode()).hexdigest()[:10],
        ))
    return sorted(found, key=lambda c: c.rating_date, reverse=True)[:limit]


# ---------------------------------------------------------------------------
# index + saving
# ---------------------------------------------------------------------------

def load_index(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {row.get("url", "") for row in csv.DictReader(handle) if row.get("url")}


def append_index(path: Path, row: dict[str, str]) -> None:
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INDEX_FIELDS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in INDEX_FIELDS})


def save_candidate(
    candidate: Candidate, out: Path, fetcher: Fetcher, seen: set[str]
) -> dict[str, str] | None:
    if candidate.url in seen:
        return None
    text = ""
    try:
        payload = fetcher.get(candidate.url)
        # ICRA serves its PDFs from a viewer URL without a .pdf suffix.
        if candidate.url.lower().endswith(".pdf") or payload[:5] == b"%PDF-":
            text = pdf_to_text(payload)
        else:
            text = html_to_text(_isolate(payload))
    except Exception as exc:  # one bad document must not stop the batch
        log.warning("%s %s: %s", candidate.symbol, candidate.url, exc)
        return None
    if len(text) < 200:
        log.info("%s %s: only %d chars, skipped", candidate.symbol, candidate.url, len(text))
        return None
    fields = parse_fields(text)
    folder = out / candidate.symbol
    folder.mkdir(parents=True, exist_ok=True)
    shortid = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate.shortid or "doc")[:60]
    path = folder / f"{candidate.agency}_{candidate.rating_date}_{shortid}.txt"
    if path.exists():
        seen.add(candidate.url)
        return None
    path.write_text(text + "\n", encoding="utf-8")
    row = {
        "symbol": candidate.symbol,
        "agency": candidate.agency,
        "rating_date": candidate.rating_date,
        "url": candidate.url,
        "instrument": fields["instrument"],
        "rating": fields["rating"],
        "outlook": fields["outlook"],
        "action": fields["action"],
        "chars": str(len(text)),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    append_index(out / "index.csv", row)
    seen.add(candidate.url)
    log.info("%s %s %s %s (%d chars)", candidate.symbol, candidate.agency,
             candidate.rating_date, fields.get("rating") or "-", len(text))
    return row


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _candidates_for(agency: str, company: str, fetcher: Fetcher, since: str, limit: int) -> list[Candidate]:
    if agency == "CARE":
        return care_candidates(company, fetcher, since, limit)
    if agency == "ICRA":
        return icra_candidates(company, fetcher, since, limit)
    if agency == "INDRAT":
        return indrat_candidates(company, fetcher, since, limit)
    if agency == "ACUITE":
        return acuite_candidates(company, fetcher, since, limit)
    return []


def run(
    store: Path,
    out: Path,
    since: str = "2024-04-01",
    symbols: Iterable[str] | None = None,
    max_per_agency: int = 4,
    agencies: Iterable[str] = AGENCIES,
    fetcher: Fetcher | None = None,
) -> dict[str, int]:
    """Fetch every requested company/agency pair; returns per-agency saved counts."""
    fetcher = fetcher or Fetcher(RateLimiter(1.0))
    out.mkdir(parents=True, exist_ok=True)
    seen = load_index(out / "index.csv")
    companies = read_companies(store, symbols)
    if not companies:
        raise SystemExit(f"no companies matched in {store}")
    chosen = [a.upper() for a in agencies]
    saved = {agency: 0 for agency in chosen}

    # CRISIL's list is global, so scan once for all companies.
    if "CRISIL" in chosen:
        by_company = crisil_scan([name for _, name in companies], fetcher, since, max_per_agency)
        for symbol, name in companies:
            for candidate in by_company.get(name, []):
                candidate.symbol = symbol
                if save_candidate(candidate, out, fetcher, seen):
                    saved["CRISIL"] += 1

    for symbol, name in companies:
        for agency in chosen:
            if agency == "CRISIL":
                continue
            try:
                candidates = _candidates_for(agency, name, fetcher, since, max_per_agency)
            except Exception as exc:
                log.warning("%s %s listing failed: %s", symbol, agency, exc)
                continue
            for candidate in candidates:
                candidate.symbol = symbol
                if save_candidate(candidate, out, fetcher, seen):
                    saved[agency] += 1
    return saved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch Indian credit-rating rationale text (T-139)")
    parser.add_argument("--store", required=True, help="pilot SQLite store (read-only)")
    parser.add_argument("--out", required=True, help="output directory for .txt files and index.csv")
    parser.add_argument("--since", default="2024-04-01", help="earliest rating date (YYYY-MM-DD)")
    parser.add_argument("--symbols", default="", help="comma-separated symbols; default all in the store")
    parser.add_argument("--max-per-agency", type=int, default=4, help="latest rationales per company+agency")
    parser.add_argument("--agencies", default=",".join(AGENCIES), help="comma-separated subset of " + ",".join(AGENCIES))
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    symbols = [s for s in args.symbols.split(",") if s.strip()]
    agencies = [a.strip().upper() for a in args.agencies.split(",") if a.strip()]
    saved = run(
        Path(args.store), Path(args.out), args.since, symbols,
        args.max_per_agency, agencies,
    )
    total = sum(saved.values())
    print(f"saved {total} rationale text(s) to {args.out}")
    for agency, count in saved.items():
        print(f"  {agency}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
