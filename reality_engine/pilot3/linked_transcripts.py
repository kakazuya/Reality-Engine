"""T-157: resolve one-page transcript cover letters and fetch the calls with no transcript document.

Two halves, one plan:

* **linked stubs** -- a ``doc`` of ``doc_type='transcript'`` with ``pages <= 2`` is a cover letter, not a
  call.  Its page text and its PDF link annotations carry the URL of the real transcript.  The text layer
  splits that URL mid-token (Adani Ports: ``.../Q2-FY25-`` then ``Earnings-Call.pdf``), so the fragments are
  joined until ``.pdf``.  Link annotations win when both exist (IHCL's text points at the wrong file, its
  annotation at the right one).
* **missing calls** -- a ``results`` filing since 2024-04-01 whose 21-day window holds no transcript of
  three pages or more is a call we cannot answer.  The transcript announcement is looked for on BSE first
  (subject says *transcript*), then on the investor page named by the company's earlier stub links.

``--apply`` stores each downloaded PDF through :func:`reality_engine.raw_store.store_bytes` and inserts one
``doc`` row and one ``doc_page`` row per page, keeping ``doc_page_fts`` in step exactly as
``statements._import_pages`` does.  Without ``--apply`` nothing is written: the plan is printed (PDFs are
still downloaded so the plan can report real page counts).  Point it at a copy; the live store waits for
the controller's review.

    python -m reality_engine.pilot3.linked_transcripts --store D:/RealityEngine/p20/p20new.db \
        --raw-out .tmp/transcripts_raw
    python -m reality_engine.pilot3.linked_transcripts --store .tmp/p20_copy.db \
        --raw-out .tmp/transcripts_raw --apply
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from reality_engine import raw_store
from reality_engine.config import DEFAULT_HEADERS
from reality_engine.pilot3 import schema

STUB_MAX_PAGES = 2
TRANSCRIPT_MIN_PAGES = 3
RESULTS_FROM = "2024-04-01"
CALL_WINDOW_DAYS = 21
#: Results filings for one call (intimation, outcome, audio link) can be 4-6 weeks apart (Pidilite files the
#: call intimation a month before the results); a quarter between two calls is ~90 days.
CLUSTER_GAP_DAYS = 45
BSE_PDF_URL = "https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname={name}"
MIN_INTERVAL_S = 1.0                      # <= one request a second per host
LAST_REQUEST: dict[str, float] = {}


# --------------------------------------------------------------------------- URLs
def urls_from_text(text: str) -> list[str]:
    """Every http(s) URL in ``text``, rebuilding one the text layer split across lines.

    A fragment is joined to the next whitespace-separated fragment until the URL ends in ``.pdf``
    (``https://.../Q2-FY25-`` + ``Earnings-Call.pdf``), and prose after the URL is never swallowed.
    """
    text = text or ""
    out: list[str] = []
    for match in re.finditer(r"https?://", text, re.I):
        parts = text[match.start():].split()
        if not parts:
            continue
        url = parts[0]
        for nxt in parts[1:6]:
            if url.lower().endswith(".pdf"):
                break
            if not (nxt.startswith(("_", "-", "/", ".")) or "/" in nxt or nxt.lower().endswith(".pdf")):
                break
            url += nxt
        url = url.rstrip(".,;:)]}\"'")
        if url not in out:
            out.append(url)
    return out


def urls_from_links(links: Iterable[Any]) -> list[str]:
    """PDF URIs from pymupdf ``page.get_links()`` dicts (other link kinds are ignored)."""
    out: list[str] = []
    for link in links:
        uri = str((link or {}).get("uri") or "") if isinstance(link, dict) else str(link or "")
        if uri.lower().startswith(("http://", "https://")) and ".pdf" in uri.lower():
            if uri not in out:
                out.append(uri)
    return out


def _pdf_module():
    try:
        import pymupdf
    except ImportError:                       # older wheels
        import fitz as pymupdf
    return pymupdf


def pdf_info(data: bytes) -> tuple[list[str], list[str]]:
    """Page texts and PDF link URIs of an in-memory PDF."""
    pymupdf = _pdf_module()
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        texts: list[str] = [str(page.get_text() or "") for page in doc]
        uris: list[str] = [str(link.get("uri")) for page in doc for link in page.get_links()
                           if link.get("uri")]
    return texts, uris


def pdf_urls(source_key: str | None) -> list[str]:
    """PDF link annotations of a stored stub PDF (empty when the file is gone or unreadable)."""
    path = Path(source_key) if source_key else None
    if not path or not path.is_file():
        return []
    try:
        with _pdf_module().open(str(path)) as doc:
            return urls_from_links([link for page in doc for link in page.get_links()])
    except Exception:                         # noqa: BLE001 - a broken PDF has no links
        return []


def stub_urls(conn: sqlite3.Connection, doc_key: str, source_key: str | None) -> list[str]:
    """Transcript candidates for one stub: link annotations first, then the page text."""
    links = pdf_urls(source_key)
    texts = [row[0] or "" for row in conn.execute(
        "SELECT text FROM doc_page WHERE doc_key=? ORDER BY page", (doc_key,))]
    urls = links + [url for url in urls_from_text("\n".join(texts)) if ".pdf" in url.lower()]
    return list(dict.fromkeys(urls))


# --------------------------------------------------------------------------- scan
def scan_stubs(conn: sqlite3.Connection, symbols: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """One-page/two-page transcript covers held in the store, with the URLs they name."""
    sql = ("SELECT doc_key, symbol, isin, title, filing_date, known_at, source_key FROM doc "
           "WHERE doc_type='transcript' AND pages<=? ")
    args: list[Any] = [STUB_MAX_PAGES]
    symbols = list(symbols or [])
    if symbols:
        sql += f"AND symbol IN ({','.join('?' * len(symbols))}) "
        args.extend(symbols)
    stubs = []
    for doc_key, symbol, isin, title, filing_date, known_at, source_key in conn.execute(
            sql + "ORDER BY symbol, filing_date", args):
        stubs.append({"doc_key": doc_key, "symbol": symbol, "isin": isin, "title": title,
                      "filing_date": filing_date, "known_at": known_at, "source_key": source_key,
                      "urls": stub_urls(conn, doc_key, source_key)})
    return stubs


def _clusters(rows: list[str]) -> list[list[str]]:
    """Group a symbol's results dates that are within the call window of each other (one event)."""
    clusters: list[list[str]] = []
    for day in rows:
        if clusters and (date.fromisoformat(day) - date.fromisoformat(clusters[-1][-1])).days <= CLUSTER_GAP_DAYS:
            clusters[-1].append(day)
        else:
            clusters.append([day])
    return clusters


def missing_calls(conn: sqlite3.Connection, symbols: Iterable[str] | None = None,
                  since: str = RESULTS_FROM, extra_transcripts: Iterable[tuple[str, str]] = ()
                  ) -> list[dict[str, Any]]:
    """Results filings whose call has no transcript of ``TRANSCRIPT_MIN_PAGES`` pages within 21 days.

    Results filings for one event cluster (the intimation, the outcome, the audio link); the call counts as
    covered when a transcript falls inside the cluster or the 21 days after its last filing.
    """
    symbols = list(symbols or [])
    held: dict[str, list[str]] = defaultdict(list)
    sql = ("SELECT symbol, filing_date FROM doc WHERE doc_type='transcript' AND pages>=? "
           "AND filing_date IS NOT NULL")
    args: list[Any] = [TRANSCRIPT_MIN_PAGES]
    if symbols:
        sql += f" AND symbol IN ({','.join('?' * len(symbols))})"
        args.extend(symbols)
    for symbol, filing_date in conn.execute(sql, args):
        held[symbol].append(filing_date[:10])
    for symbol, filing_date in extra_transcripts:
        if filing_date:
            held[symbol].append(filing_date[:10])

    sql = "SELECT symbol, filing_date, doc_key, title FROM doc WHERE doc_type='results' AND filing_date>=? "
    args = [since]
    if symbols:
        sql += f" AND symbol IN ({','.join('?' * len(symbols))})"
        args.extend(symbols)
    by_symbol: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for symbol, filing_date, doc_key, title in conn.execute(sql + "ORDER BY symbol, filing_date", args):
        by_symbol[symbol].append((filing_date[:10], doc_key, title or ""))
    out = []
    for symbol in sorted(by_symbol):
        ordered = sorted(by_symbol[symbol])
        groups = _clusters([day for day, _, _ in ordered])
        for group in groups:
            last = group[-1]
            until = (date.fromisoformat(last) + timedelta(days=CALL_WINDOW_DAYS)).isoformat()
            if any(group[0] <= day <= until for day in held.get(symbol, [])):
                continue
            first_row = next(item for item in ordered if item[0] == group[0])
            out.append({"symbol": symbol, "filing_date": group[0], "last_filing": last,
                        "until": until, "doc_key": first_row[1], "title": first_row[2]})
    return out


# --------------------------------------------------------------------------- network
def download_pdf(url: str, *, attempts: int = 3, backoff: float = 5.0, timeout: float = 90.0,
                 sleep=time.sleep) -> bytes | None:
    """One PDF, politely: <= one request a second per host, retries on 429/5xx, PDF bytes only."""
    import requests

    host = (url.split("/")[2] if "//" in url and len(url.split("/")) > 2 else "").lower()
    session = requests.Session()
    try:
        for attempt in range(1, attempts + 1):
            gap = LAST_REQUEST.get(host, 0.0) + MIN_INTERVAL_S - time.monotonic()
            if gap > 0:
                sleep(gap)
            LAST_REQUEST[host] = time.monotonic()
            try:
                got = session.get(url, headers=DEFAULT_HEADERS, timeout=timeout, allow_redirects=True)
            except Exception:                 # noqa: BLE001 - network
                if attempt == attempts:
                    return None
                sleep(backoff * attempt)
                continue
            if got.status_code == 429 or got.status_code >= 500:
                if attempt == attempts:
                    return None
                sleep(backoff * (2 ** (attempt - 1)))
                continue
            if got.status_code != 200:
                return None
            body = got.content or b""
            return body if body[:5] == b"%PDF-" else None
        return None
    finally:
        session.close()


def resolve_pdf(url: str, fetch=None) -> dict[str, Any] | None:
    """A real transcript from ``url``; a one-page cover letter is followed through its own link once."""
    fetch = fetch or download_pdf
    data = fetch(url)
    if data is None:
        return None
    try:
        texts, uris = pdf_info(data)
    except Exception:                         # noqa: BLE001 - not a readable PDF
        return None
    if len(texts) >= TRANSCRIPT_MIN_PAGES:
        return {"url": url, "data": data, "texts": texts, "pages": len(texts)}
    following = [u for u in uris if u.lower().startswith(("http://", "https://")) and ".pdf" in u.lower()]
    following += [u for u in urls_from_text("\n".join(texts)) if ".pdf" in u.lower()]
    for nxt in dict.fromkeys(following):
        if nxt == url:
            continue
        more = fetch(nxt)
        if more is None:
            continue
        try:
            texts, _ = pdf_info(more)
        except Exception:                     # noqa: BLE001
            continue
        if len(texts) >= TRANSCRIPT_MIN_PAGES:
            return {"url": nxt, "data": more, "texts": texts, "pages": len(texts), "via": url}
    return None


def bse_transcript(symbol: str, bse_code: str | None, start: str, end: str, client=None
                   ) -> dict[str, Any] | None:
    """Earliest BSE announcement whose subject says *transcript* in the window; its PDF URL and time."""
    if not bse_code:
        return None
    end = min(end, date.today().isoformat())      # BSE answers HTTP 400 for a future window end
    if end < start:
        return None
    if client is None:
        from reality_engine.ingestion.bse_client import BSEClient
        client = BSEClient()
    found = bse_candidates(bse_code, start, end, client)
    return found[0] if found and "transcript" in found[0]["title"].lower() else None


# Some companies (HAVELLS 2024-25) file the transcript as "Analyst / Investor Meet - Outcome", 15-17 pages,
# about six days after results; the one-page outcome on results day is the audio link (checked 9 Nov 2026).
MEET_OUTCOME = re.compile(r"(analyst|investor)\s*/?\s*(investor\s*)?meet\s*-\s*outcome", re.I)
TRANSCRIPT_TEXT = re.compile(r"\bmoderator\b|\btranscript\b|conference call", re.I)


def bse_candidates(bse_code: str | None, start: str, end: str, client=None) -> list[dict[str, Any]]:
    """BSE announcements in the window that may hold the call: subject *transcript* first (earliest
    first), then *Analyst / Investor Meet - Outcome* filings (earliest first), each with its PDF URL."""
    if not bse_code:
        return []
    end = min(end, date.today().isoformat())      # BSE answers HTTP 400 for a future window end
    if end < start:
        return []
    if client is None:
        from reality_engine.ingestion.bse_client import BSEClient
        client = BSEClient()
    rows = client.fetch_corporate_announcements(
        str(bse_code), category="-1", from_date=start.replace("-", ""), to_date=end.replace("-", ""))
    named, meets = [], []
    for row in rows:
        subject = " ".join(str(row.get("NEWSSUB") or row.get("HEADLINE") or "").split())
        attachment = str(row.get("ATTACHMENTNAME") or "")
        known_at = str(row.get("DissemDT") or row.get("News_submission_dt") or "")
        if not attachment.lower().endswith(".pdf") or not known_at:
            continue
        item = {"url": BSE_PDF_URL.format(name=attachment), "title": subject, "known_at": known_at,
                "newsid": str(row.get("NEWSID") or "")}
        if "transcript" in subject.lower():
            named.append(item)
        elif MEET_OUTCOME.search(subject):
            meets.append(item)
    return sorted(named, key=lambda i: i["known_at"]) + sorted(meets, key=lambda i: i["known_at"])


def quarter_tag(day: str) -> str | None:
    """``Q2FY27`` for a results filing date (Apr-Jun files Q4 of the FY just ended)."""
    try:
        when = date.fromisoformat(day[:10])
    except ValueError:
        return None
    quarter = {1: 3, 2: 3, 3: 3, 4: 4, 5: 4, 6: 4, 7: 1, 8: 1, 9: 1, 10: 2, 11: 2, 12: 2}[when.month]
    fy = when.year + 1 if when.month >= 7 else when.year
    return f"Q{quarter}FY{fy % 100:02d}"


def _page_links(url: str) -> list[str]:
    """PDF links on the investor page that contains ``url`` (the stub's own folder)."""
    import requests

    page = url.rsplit("/", 1)[0] + "/"
    try:
        got = requests.get(page, headers=DEFAULT_HEADERS, timeout=45)
        if got.status_code != 200:
            return []
        html = got.text or ""
    except Exception:                         # noqa: BLE001 - network
        return []
    links = [re.sub(r"&amp;", "&", href) for href in re.findall(r'href="([^"]+)"', html, re.I)]
    return [link if link.lower().startswith("http") else page.rstrip("/") + "/" + link.lstrip("/")
            for link in links if ".pdf" in link.lower()]


def investor_transcript(symbol: str, stubs: list[dict[str, Any]], anchor: str) -> dict[str, Any] | None:
    """Fallback: a PDF on the company's investor page (named by an earlier stub) for this quarter."""
    tag = quarter_tag(anchor)
    if not tag:
        return None
    q, fy = tag.split("FY")
    want_q = re.compile(rf"(?<![a-z]){q.lower()}(?![a-z])", re.I)
    want_fy = re.compile(rf"fy\s*{fy}", re.I)
    for stub in stubs:
        for url in stub.get("urls") or []:
            for link in _page_links(url):
                name = link.rsplit("/", 1)[-1]
                if want_q.search(name) and want_fy.search(name):
                    return {"url": link, "title": f"{symbol} {tag} earnings call transcript",
                            "known_at": datetime.now().isoformat(timespec="seconds")}
    return None


# --------------------------------------------------------------------------- plan
def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _held_shas(conn: sqlite3.Connection) -> set[str]:
    return {str(sha).lower() for (sha,) in conn.execute("SELECT sha256 FROM doc WHERE sha256 IS NOT NULL")}


def _identity(conn: sqlite3.Connection, symbol: str) -> tuple[str | None, str | None]:
    row = conn.execute(
        "SELECT isin, bse_code FROM company WHERE symbol=? "
        "ORDER BY (bse_code IS NULL), (isin IS NULL) LIMIT 1", (symbol,)).fetchone()
    return (row[0], str(row[1]) if row and row[1] else None) if row else (None, None)


def call_label(url: str, fallback: str | None) -> str:
    """A readable call name from the transcript URL's file name, else the stub's title."""
    name = url.rsplit("/", 1)[-1].split("?")[0]
    name = re.sub(r"\.pdf$", "", name, flags=re.I)
    name = " ".join(re.sub(r"[-_]+", " ", name).split())
    return name or (fallback or "Earnings call")


def _linked_item(stub: dict[str, Any], held: set[str], fetch) -> dict[str, Any]:
    base = {k: stub[k] for k in ("doc_key", "symbol", "isin", "title", "known_at", "filing_date")}
    base["stub"] = stub["doc_key"]
    if not stub["urls"]:
        return {**base, "kind": "stub", "status": "no_link", "url": None}
    for url in stub["urls"]:
        found = resolve_pdf(url, fetch)
        if found is None:
            continue
        sha = _sha256(found["data"])
        known_at = stub["known_at"] or stub["filing_date"] or ""
        if sha in held:
            return {**base, "kind": "stub", "status": "held", "url": found["url"], "sha256": sha,
                    "pages": found["pages"]}
        return {**base, "kind": "stub", "status": "planned", "url": found["url"], "sha256": sha,
                "pages": found["pages"], "texts": found["texts"], "data": found["data"],
                "source": "linked_transcript", "filing_date": known_at[:10],
                "known_at": known_at, "doc_key": f"linked_transcripts/{stub['symbol']}/{sha}.pdf",
                "title": f"{call_label(found['url'], stub['title'])} transcript (linked from {stub['doc_key']})"}
    return {**base, "kind": "stub", "status": "unreachable", "url": stub["urls"][0]}


def _missing_item(rec: dict[str, Any], conn, held: set[str], stubs, fetch, client=None) -> dict[str, Any]:
    symbol = rec["symbol"]
    isin, bse_code = _identity(conn, symbol)
    base = {"kind": "call", "symbol": symbol, "isin": isin, "anchor": rec["filing_date"],
            "anchor_doc": rec["doc_key"], "anchor_title": rec["title"]}
    found, got, source = None, None, "bse_announcement"
    for cand in bse_candidates(bse_code, rec["filing_date"], rec["until"], client):
        pdf = resolve_pdf(cand["url"], fetch)
        if pdf is None:
            continue
        # a meet-outcome PDF counts only when its text reads as a call transcript
        if "transcript" in cand["title"].lower() or TRANSCRIPT_TEXT.search("\n".join(pdf["texts"][:3])):
            found, got = cand, pdf
            break
    if found is None:
        found = investor_transcript(symbol, stubs, rec["filing_date"])
        source = "investor_page"
        if found is None:
            return {**base, "status": "not_found", "url": None,
                    "searched": "bse" if not bse_code else "bse+investor"}
        got = resolve_pdf(found["url"], fetch)
        if got is None:
            return {**base, "status": "not_found", "url": found["url"], "reason": "no PDF transcript"}
    sha = _sha256(got["data"])
    if sha in held:
        return {**base, "status": "held", "url": got["url"], "sha256": sha, "pages": got["pages"]}
    known_at = found["known_at"]
    return {**base, "status": "planned", "url": got["url"], "sha256": sha, "pages": got["pages"],
            "texts": got["texts"], "data": got["data"], "source": source,
            "doc_key": f"linked_transcripts/{symbol}/{sha}.pdf",
            "filing_date": known_at[:10], "known_at": known_at,
            "title": found["title"] or f"{symbol} earnings call transcript",
            "via": got.get("via")}


def build_plan(conn: sqlite3.Connection, symbols: Iterable[str] | None = None, *, since: str = RESULTS_FROM,
               fetch=None, client=None) -> dict[str, Any]:
    """What ``apply`` would add: linked stubs resolved and missing calls looked up (no store writes)."""
    symbols = list(symbols or [])
    held = _held_shas(conn)
    stubs = scan_stubs(conn, symbols or None)
    stub_items = [_linked_item(stub, held, fetch) for stub in stubs]
    planned = [item for item in stub_items if item["status"] == "planned"]
    extra = [(item["symbol"], item.get("known_at") or "") for item in planned]
    missing = missing_calls(conn, symbols or None, since=since, extra_transcripts=extra)
    call_items = [_missing_item(rec, conn, held, stubs, fetch, client) for rec in missing]
    return {"stubs": stub_items, "calls": call_items,
            "totals": {"stubs": len(stub_items), "planned": len(planned),
                       "calls": len(call_items),
                       "calls_planned": sum(1 for item in call_items if item["status"] == "planned")}}


def _items(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return list(plan["stubs"]) + list(plan["calls"])


# --------------------------------------------------------------------------- apply
def apply_plan(conn: sqlite3.Connection, plan: dict[str, Any], raw_out: str | Path,
               store=None) -> dict[str, int]:
    """Store each planned PDF and insert its ``doc`` / ``doc_page`` rows plus the FTS entries."""
    store = store or raw_store.store_bytes
    raw_out = Path(raw_out)
    index = raw_out / "_dedupe" / "sha_index.db"
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='doc_page_fts'").fetchone():
        conn.execute(schema.FTS)
    counts = {"added": 0, "pages": 0, "skipped": 0}
    for item in _items(plan):
        if item.get("status") != "planned":
            continue
        sha = item["sha256"]
        if conn.execute("SELECT 1 FROM doc WHERE sha256=? OR doc_key=?", (sha, item["doc_key"])).fetchone():
            item["status"] = "held"
            counts["skipped"] += 1
            continue
        dest = raw_out / sha[:2] / f"{sha}.pdf"
        store(dest, item["data"], index_path=index)
        with conn:
            conn.execute(
                "INSERT INTO doc (doc_key, symbol, isin, doc_type, doc_family, title, filing_date, known_at, "
                "pages, sha256, source, source_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (item["doc_key"], item["symbol"], item.get("isin"), "transcript", "transcript",
                 item["title"], item["filing_date"], item["known_at"], item["pages"], sha,
                 item["source"], str(dest)))
            for page, text in enumerate(item["texts"], 1):
                method = "script_text" if text.strip() else "needs_ocr"
                conn.execute(
                    "INSERT INTO doc_page (doc_key, symbol, page, text, method, chars, known_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (item["doc_key"], item["symbol"], page, text, method, len(text), item["known_at"]))
                conn.execute("INSERT INTO doc_page_fts(rowid, text) VALUES (last_insert_rowid(), ?)", (text,))
        item["status"] = "added"
        counts["added"] += 1
        counts["pages"] += item["pages"]
    return counts


# --------------------------------------------------------------------------- report
def report(plan: dict[str, Any]) -> str:
    """Per-company table plus one line per stub and per missing call."""
    rows: dict[str, dict[str, int]] = defaultdict(lambda: {"stubs": 0, "resolved": 0, "pages": 0,
                                                            "calls": 0, "calls_found": 0})
    for item in plan["stubs"]:
        row = rows[item["symbol"]]
        row["stubs"] += 1
        if item["status"] in ("planned", "held", "added"):
            row["resolved"] += 1
            row["pages"] += int(item.get("pages") or 0)
    for item in plan["calls"]:
        row = rows[item["symbol"]]
        row["calls"] += 1
        if item["status"] in ("planned", "held", "added"):
            row["calls_found"] += 1
            row["pages"] += int(item.get("pages") or 0)
    lines = ["| symbol | stubs | resolved | missing calls looked | calls found | pages |",
             "|---|---|---|---|---|---|"]
    for symbol in sorted(rows):
        row = rows[symbol]
        lines.append(f"| {symbol} | {row['stubs']} | {row['resolved']} | {row['calls']} | "
                     f"{row['calls_found']} | {row['pages']} |")
    lines.append("")
    for item in plan["stubs"]:
        detail = item.get("url") or ""
        lines.append(f"STUB {item['symbol']:11} {str(item.get('known_at'))[:10]} {item['status']:11} "
                     f"{int(item.get('pages') or 0):>2}p {detail}")
    for item in plan["calls"]:
        detail = item.get("url") or item.get("reason") or ""
        lines.append(f"CALL {item['symbol']:11} {item['anchor']} {item['status']:11} "
                     f"{int(item.get('pages') or 0):>2}p {detail}")
    totals = plan["totals"]
    lines.append("")
    lines.append(f"stubs {totals['stubs']}, resolved {totals['planned']}, missing calls {totals['calls']}, "
                 f"calls found {totals['calls_planned']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve linked transcript stubs and missing call transcripts")
    parser.add_argument("--store", required=True, help="pilot3 database (use a copy with --apply)")
    parser.add_argument("--raw-out", required=True, help="where --apply stores the PDFs")
    parser.add_argument("--symbols", default="", help="comma-separated symbols (default: every company)")
    parser.add_argument("--since", default=RESULTS_FROM, help="results-filing window start")
    parser.add_argument("--apply", action="store_true", help="download, store and insert into the database")
    parser.add_argument("--json", default="", help="write the plan to this JSON file")
    args = parser.parse_args(argv)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    path = Path(args.store)
    conn = sqlite3.connect(str(path)) if args.apply else sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        plan = build_plan(conn, symbols or None, since=args.since)
        if args.apply:
            counts = apply_plan(conn, plan, args.raw_out)
            print(f"applied: {counts['added']} docs, {counts['pages']} pages, {counts['skipped']} skipped")
        print(report(plan))
        if args.json:
            import json
            payload = [{k: v for k, v in item.items() if k not in ("data", "texts")} for item in _items(plan)]
            Path(args.json).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
