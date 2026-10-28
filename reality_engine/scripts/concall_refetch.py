"""Concall PDF re-fetch pilot over the BSE earnings-call-transcript feed.

Candidates: ``bse_announcements.ann`` rows with
``SUBCATNAME = 'Earnings Call Transcript'`` and ``DissemDT >= 2024-04-01``
(~9,390).  The PDF URL is built from ``ATTACHMENTNAME``; ``known_at`` is
``DissemDT``, never a crawl date.

Two passes:

* **analysis** (no network): candidate mix, old ``corporate_documents`` coverage
  both ways, headline classes, duplicate proxies, and the classification of
  every PDF the earlier probe already staged;
* **pilot**: 200 rows stratified by fiscal quarter x symbol initial (A-P / Q-Z),
  reusing staged probe PDFs by sha256 and fetching the rest behind one shared
  pacer (>= ``--interval`` s between requests across all workers, back-off on
  403/429/503, which pauses every worker), then validating, classifying and
  deduping each file.  ``--workers N`` fetches through a thread pool with one
  ``requests`` session per thread; the PDF inspection stays in the main thread.

``--widen`` adds the other BSE subcategories the old crawl filed real transcripts
under ("Analyst / Investor Meet", "General", "Investor Presentation",
"Press Release / Media Release"), keeps the rows whose headline signals a
transcript, dedupes them against the earnings-call set by (ISIN, fiscal quarter)
and by attachment name, measures recall against the pilot's 1,771 old rows and
classifies a precision sample of PDFs already on disk.  It is report-only until
``--fetch`` is passed.  ``--widen --transcript-word``
fetches only the fresh rows whose headline or attachment name carries the word
*transcript* (invites, outcomes and schedules are left out; Shivam, 2026-10-28).

The dedupe-rescue list is its own run: ``--rescue-file`` takes the JSON array
of rows (e.g. ``dedupe_rescue_214.json``) and fetches exactly those newsids
through the same validate / classify / dedupe path.  ``--dry-run`` prints the
counts and fetches nothing.

Every run is **resumable**: one JSON line per finished candidate goes to
``<root>/_journal_<mode>.jsonl`` (mode = full | widen | rescue, flushed per
line).  A restart skips every newsid the journal holds as ``ok`` or as a
permanent failure, retries the transient ones, and writes the manifest from
journal + new rows before the existing dedupe.  ``--seed-journal-from-log``
parses the ``[i/9390] SYMBOL quarter status source class chars`` lines of a
previous run's stdout log, maps ``i`` back to the same seeded sample and
journals the ok rows whose PDF is already in the store, so the live full run
can be killed and restarted wide without redoing what it finished.

Rate: probes on 2026-10-28 saw no block at ~200 extra requests/min on BSE or
~400/min on NSE, so the old 76/min cap is stale.  ``--interval`` floors at
0.15 s (400/min) and defaults to 2.5 s (24/min, the cautious setting); the
pacer keeps the *total* across workers at ``60/interval`` per minute.

Writes go only to ``RAW_ROOT/concall_pdfs/`` (content-addressed PDFs, manifest,
probe classification) and the worktree.  Every database and the probe store is
opened read-only.

    python -m reality_engine.scripts.concall_refetch --analyze-only
    python -m reality_engine.scripts.concall_refetch --n 200 --report tasks/concall_refetch/report.md
    python -m reality_engine.scripts.concall_refetch --widen --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import random
import re
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from reality_engine.config import BSE_HEADERS, DEFAULT_HEADERS, NSE_HEADERS, RAW_ROOT
from reality_engine.db.readonly import connect_ro

SUBCAT = "Earnings Call Transcript"
#: Other BSE subcategories the old crawl filed real transcripts under (pilot §1).
WIDEN_SUBCATS = ("Analyst / Investor Meet", "General",
                 "Investor Presentation", "Press Release / Media Release")
WINDOW_START = "2024-04-01"
PDF_URL = "https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname={name}"
#: Hard floor on ``--interval``: 400 requests/min.  Probes on 2026-10-28 saw no
#: block at ~400/min on NSE or ~200/min on BSE, so the old 76/min cap is stale.
MIN_INTERVAL = 0.15                   # hard floor: 400 requests/min
CLASSES = ("transcript", "audio_link", "intimation", "cover_letter", "other")
TRANSCRIPT_MIN_CHARS = 8000
TRANSCRIPT_MIN_PAGES = 3
IMAGE_ONLY_PAGE_CHARS = 200
PRECISION_SAMPLE = 40                 # widened docs with bytes on disk to classify

ANN_SQL = """
select NEWSID, SCRIP_CD, ATTACHMENTNAME, HEADLINE, SUBCATNAME, DissemDT,
       Fld_Attachsize, symbol
from ann
where SUBCATNAME = ? and DissemDT >= ?
order by DissemDT, NEWSID
"""

WIDEN_ANN_SQL = """
select NEWSID, SCRIP_CD, ATTACHMENTNAME, HEADLINE, SUBCATNAME, DissemDT,
       Fld_Attachsize, symbol
from ann
where SUBCATNAME in (?,?,?,?) and DissemDT >= ?
order by DissemDT, NEWSID
"""

OLD_SQL = """
select id, bse_newsid, sha256_hash, title, isin,
       coalesce(nullif(bse_dissem_ts, ''), nullif(publication_date, ''),
                nullif(call_date, ''), nullif(event_date, '')) as known_dt
from corporate_documents
where doc_type = 'CONCALL_TRANSCRIPT'
"""

CHUNKED_SQL = ("select sha256_hash, doc_id from raw_documents "
               "where source_type = 'CONCALL_TRANSCRIPT'")

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")
_FY_Q = re.compile(r"\bQ\s*([1-4])\s*[-\s]*(?:FY|F\.Y\.?)\s*(\d{2,4})\b", re.I)
_FY = re.compile(r"\b(?:FY|F\.Y\.?)\s*(\d{2,4})\b", re.I)
_DMY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+(" + "|".join(_MONTHS) + r")[\s,\-]+(\d{4})\b", re.I)
_NUM_DMY = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_BARE_YEAR = re.compile(r"\b(20[12]\d)\b")

_AUDIO = re.compile(r"audio|voice\s*record|recording|webcast|dial[\s-]?in|link to (the )?(call|recording)", re.I)
_INTIMATION = re.compile(
    r"intimation|prior intimation|advance intimation|notice of|invite|invitation|reminder"
    r"|schedule of|conference call on|to be held on|will be held", re.I)
_TRANSCRIPT_HINT = re.compile(r"transcript|concall|earnings call|analyst call|q\s*&\s*a", re.I)
# Widen mode: what a headline (or attachment name) must say to be worth fetching.
_WIDEN_TRANSCRIPT = re.compile(r"transcript", re.I)
_WIDEN_CALL = re.compile(
    r"\bcon[\s-]*call\b|\bearnings?\s+call\b|\bconference\s+call\b|\binvestor'?s?\s+call\b",
    re.I)
_WIDEN_REG46OA = re.compile(r"46\s*\(\s*2\s*\)\s*\(\s*o\s*a\s*\)", re.I)
_WIDEN_AUDIO = re.compile(
    r"audio|video|recording|webcast|dial[\s-]?in|youtube|\blink\b|\blink of\b|transcript\s+link",
    re.I)
_WIDEN_SCHEDULE = re.compile(
    r"schedule|intimat|to be held|will be held|proposed|prior\s+notice|advance\s+notice",
    re.I)
_CLOSING = re.compile(
    r"thank(?:ing)? you|yours (?:faithfully|sincerely)|please find enclosed|kindly find"
    r"|for your (?:kind )?(?:information|reference)|enclosed herewith", re.I)
_MODERATOR = re.compile(r"\bmoderator\b|\bquestion[\s-]*(?:and|&)[\s-]*answer\b|\bq\s*&\s*a\b", re.I)
_SPEAKER = re.compile(r"^[ \t]*(?:[A-Z][A-Za-z.&'\-]*(?:[ \t]+[A-Z][A-Za-z.&'\-]*){0,4})[ \t]*:", re.M)
_METADATA = re.compile(r"^\[Metadata:[^\]]*\]\s*", re.M)


# ---------------------------------------------------------------------------
# paths


def out_dir() -> Path:
    """Root of the pilot store (``RAW_ROOT/concall_pdfs`` unless overridden)."""
    return Path(os.environ.get("CONCALL_PDF_DIR") or (RAW_ROOT / "concall_pdfs"))


def probe_dir() -> Path:
    """Where the earlier probe staged content-addressed PDFs (read-only)."""
    return Path(os.environ.get("CONCALL_PROBE_DIR") or (RAW_ROOT / "concall_pdfs_probe"))


def pdf_path(sha256: str, root: Path | None = None) -> Path:
    """Content-addressed destination for one PDF."""
    sha = str(sha256).lower()
    return (root or out_dir()) / sha[:2] / f"{sha}.pdf"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _chunks(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


# ---------------------------------------------------------------------------
# journal: one JSON line per finished candidate, so a restart resumes


def journal_path(root: Path | None = None, mode: str = "full") -> Path:
    """The run's journal: ``<root>/_journal_<mode>.jsonl``."""
    return (Path(root) if root else out_dir()) / f"_journal_{mode}.jsonl"


def load_journal(path: str | Path) -> dict[str, dict[str, Any]]:
    """``{newsid: entry}`` from the journal; a later line for a newsid wins.

    A truncated last line (killed mid-write) is skipped, never fatal.
    """
    out: dict[str, dict[str, Any]] = {}
    path = Path(path)
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("newsid"):
            out[str(record["newsid"])] = record
    return out


def is_permanent_failure(entry: dict[str, Any]) -> bool:
    """Will a retry of this URL plausibly give a different answer?

    Permanent: an unreadable PDF, a body that is not a PDF, and a 4xx that is
    not a block (403/429 are the server asking us to slow down, so transient).
    """
    if entry.get("status") == "invalid":
        return True
    reason = str(entry.get("reason") or "")
    if reason.startswith("pymupdf") or reason in ("not a PDF", "stored file is not a PDF"):
        return True
    code = entry.get("http_status")
    return isinstance(code, int) and 400 <= code < 500 and code not in (403, 429)


def journal_done(entry: dict[str, Any]) -> bool:
    """Skip this newsid on a restart: finished ok, or failed for good."""
    return entry.get("status") == "ok" or bool(entry.get("permanent"))


class JournalWriter:
    """Append-only JSONL journal, flushed after every line."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")
        self.lines = 0

    def append(self, entry: dict[str, Any]) -> None:
        self._handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        self._handle.flush()
        self.lines += 1

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> "JournalWriter":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# dates and candidates


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def fiscal_quarter(value: Any) -> str | None:
    """Indian fiscal quarter of a timestamp: Apr-Jun = Q1 of the next FY."""
    day = _parse_date(value)
    if day is None:
        return None
    fy = day.year + 1 if day.month >= 4 else day.year
    quarter = ((day.month - 4) % 12) // 3 + 1
    return f"FY{fy % 100:02d}Q{quarter}"


def group_of(symbol: Any) -> str:
    """A-P vs Q-Z stratification cell from the ticker's first letter."""
    first = str(symbol or "").strip()[:1].upper()
    return "A-P" if "A" <= first <= "P" else "Q-Z"


def pdf_url(attachment: Any) -> str | None:
    name = str(attachment or "").strip()
    return PDF_URL.format(name=name) if name else None


def load_identity(con, codes: Iterable[Any]) -> dict[str, dict[str, str | None]]:
    """BSE scrip code -> {isin, symbol}; ``master_companies`` then bhavcopy."""
    wanted = sorted({str(int(code)) for code in codes if code is not None})
    identity: dict[str, dict[str, str | None]] = {}
    for part in _chunks(wanted, 900):
        sql = ("select bse_code, isin, nse_symbol from master_companies "
               "where bse_code in (%s)" % ",".join("?" * len(part)))
        for code, isin, symbol in con.execute(sql, part):
            if isin:
                identity[str(code).strip()] = {"isin": isin, "symbol": symbol}
    missing = [code for code in wanted if code not in identity]
    for part in _chunks(missing, 900):
        sql = ("select sc_code, isin, max(date) from mkt_bse_eq_daily "
               "where sc_code in (%s) group by sc_code, isin" % ",".join("?" * len(part)))
        rows = con.execute(sql, [int(code) for code in part]).fetchall()
        best: dict[int, tuple[str, str]] = {}
        for sc_code, isin, last_date in rows:
            if isin and (sc_code not in best or (last_date or "") > best[sc_code][1]):
                best[int(sc_code)] = (isin, last_date or "")
        for code, (isin, _) in best.items():
            identity[str(code)] = {"isin": isin, "symbol": None}
        by_isin = [isin for isin, _ in best.values()]
        if by_isin:
            sql = ("select isin, nse_symbol from master_companies "
                   "where isin in (%s)" % ",".join("?" * len(by_isin)))
            names = {isin: symbol for isin, symbol in con.execute(sql, by_isin)}
            for code, (isin, _) in best.items():
                identity[str(code)]["symbol"] = names.get(isin)
    return identity


def load_old_docs(con) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Old ``CONCALL_TRANSCRIPT`` rows: newsid index plus the whole list."""
    by_news: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for rid, newsid, sha, title, isin, known_dt in con.execute(OLD_SQL):
        item = {"id": int(rid), "newsid": newsid, "sha256": str(sha or "").lower() or None,
                "title": title, "isin": isin, "known_dt": known_dt}
        rows.append(item)
        if newsid:
            by_news[str(newsid)] = item
    return by_news, rows


def load_chunked(con) -> dict[str, int]:
    """sha256 -> raw_documents.doc_id for transcripts we already chunked."""
    return {str(sha).lower(): int(doc_id) for sha, doc_id in con.execute(CHUNKED_SQL) if sha}


def build_candidates(ann_rows: Sequence[Sequence[Any]],
                     identity: dict[str, dict[str, str | None]],
                     old_by_news: dict[str, dict[str, Any]],
                     chunked: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Turn ``ann`` rows into candidate dicts with ISIN, quarter and stratum."""
    chunked = chunked or {}
    out: list[dict[str, Any]] = []
    for (newsid, scrip, attach, headline, subcat, dissem, size, symbol) in ann_rows:
        code = str(int(scrip)) if scrip is not None else ""
        ident = identity.get(code) or {}
        ticker = str(symbol or ident.get("symbol") or "").strip().upper()
        old = old_by_news.get(str(newsid)) or {}
        sha = old.get("sha256")
        out.append({
            "newsid": str(newsid), "scrip_cd": code, "attachment": attach,
            "url": pdf_url(attach), "headline": headline, "subcat": subcat,
            "known_at": dissem, "size": size, "symbol": ticker,
            "isin": ident.get("isin"), "group": group_of(ticker),
            "quarter": fiscal_quarter(dissem), "cd_id": old.get("id"),
            "cd_sha": sha, "cd_title": old.get("title"),
            "chunked": bool(sha and sha in chunked),
            "chunk_doc_id": chunked.get(sha) if sha else None,
        })
    return out


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def load_rescue(path: Path) -> list[dict[str, Any]]:
    """Rescue list (JSON array, e.g. ``dedupe_rescue_214.json``) -> pilot candidates.

    The dedupe-rescue list already carries the fields the pilot path needs;
    missing ones are derived from the attachment name / dissemination time.
    Rows without a newsid, a URL or a duplicate newsid are dropped, so a fetch
    is exactly the listed set (and never the same row twice).
    """
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected a JSON array of rows")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        newsid = str(row.get("newsid") or "").strip()
        url = row.get("url") or pdf_url(row.get("attachment"))
        if not newsid or newsid in seen or not url:
            continue
        seen.add(newsid)
        symbol = str(row.get("symbol") or "").strip().upper()
        known_at = row.get("known_at")
        chunked = row.get("chunked")
        out.append({
            "newsid": newsid,
            "scrip_cd": str(row.get("scrip_cd") or ""),
            "attachment": row.get("attachment"),
            "url": str(url),
            "headline": row.get("headline") or "",
            "subcat": row.get("subcat") or "",
            "known_at": known_at,
            "size": row.get("size"),
            "symbol": symbol,
            "isin": row.get("isin"),
            "group": row.get("group") or group_of(symbol),
            "quarter": row.get("quarter") or fiscal_quarter(known_at),
            "cd_id": _as_int(row.get("cd_id")),
            "cd_sha": str(row.get("cd_sha") or "").lower() or None,
            "cd_title": row.get("cd_title"),
            "chunked": chunked if isinstance(chunked, bool)
            else str(chunked or "").lower() in ("1", "true", "yes"),
            "chunk_doc_id": _as_int(row.get("chunk_doc_id")),
        })
    return out


# ---------------------------------------------------------------------------
# probe store


def probe_index(directory: Path | None = None) -> dict[str, Any]:
    """Content-addressed probe PDFs: ``{sha256: path}`` plus integrity stats."""
    directory = Path(directory or probe_dir())
    index: dict[str, Path] = {}
    bad = 0
    total = 0
    if directory.is_dir():
        for path in sorted(directory.rglob("*.pdf")):
            total += 1
            try:
                sha = sha256_of(path.read_bytes())
            except OSError:
                bad += 1
                continue
            if sha != path.stem.lower():
                bad += 1
            index[sha] = path
    return {"dir": str(directory), "files": total, "bad_name": bad, "by_sha": index}


# ---------------------------------------------------------------------------
# sampling


def allocate(sizes: dict[Any, int], total: int) -> dict[Any, int]:
    """Proportional allocation with a floor of one per non-empty cell."""
    sizes = {k: v for k, v in sizes.items() if v > 0}
    if not sizes or total <= 0:
        return {}
    if total <= len(sizes):
        keys = sorted(sizes, key=lambda k: (-sizes[k], str(k)))
        return {k: 1 for k in keys[:total]}
    pool = sum(sizes.values())
    exact = {k: total * v / pool for k, v in sizes.items()}
    quota = {k: min(sizes[k], max(1, int(exact[k]))) for k in sizes}
    while sum(quota.values()) < total:
        open_ = [k for k in sizes if quota[k] < sizes[k]]
        if not open_:
            break
        key = max(open_, key=lambda k: (exact[k] - quota[k], str(k)))
        quota[key] += 1
    while sum(quota.values()) > total:
        closed = sorted((k for k in quota if quota[k] > 1),
                        key=lambda k: (exact[k] - quota[k], str(k)))
        if not closed:
            break
        quota[closed[0]] -= 1
    return {k: v for k, v in quota.items() if v}


def stratified_sample(rows: Sequence[dict[str, Any]], n: int,
                      seed: int = 20261027) -> list[dict[str, Any]]:
    """``n`` rows spread over quarter x symbol initial, deterministic per seed."""
    cells: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        cells[(row["quarter"], row["group"])].append(row)
    quota = allocate({key: len(value) for key, value in cells.items()}, n)
    picks: list[dict[str, Any]] = []
    for key in sorted(quota, key=str):
        pool = sorted(cells[key], key=lambda r: (str(r["known_at"]), r["newsid"]))
        rnd = random.Random(f"{seed}:{key[0]}:{key[1]}")
        picks.extend(rnd.sample(pool, min(quota[key], len(pool))))
    if len(picks) < n:                       # top up if a cell ran short
        taken = {p["newsid"] for p in picks}
        rest = sorted((r for r in rows if r["newsid"] not in taken),
                      key=lambda r: (str(r["known_at"]), r["newsid"]))
        picks.extend(random.Random(f"{seed}:topup").sample(rest, min(n - len(picks), len(rest))))
    return sorted(picks, key=lambda r: (r["quarter"], r["group"], str(r["known_at"]), r["newsid"]))


# ---------------------------------------------------------------------------
# network


class Pacer:
    """Shared rate limiter: one request every ``interval`` seconds, all threads.

    Each caller reserves the next free slot under a lock (so N workers cannot
    exceed ``60/interval`` requests/min together) and then sleeps until its
    slot outside the lock.
    """

    def __init__(self, interval: float = MIN_INTERVAL, clock=time.monotonic, sleep=time.sleep):
        self.interval = max(0.0, float(interval))
        self.clock = clock
        self.sleep = sleep
        self._lock = threading.Lock()
        self._next: float | None = None
        self.requests = 0

    def wait(self) -> None:
        with self._lock:
            now = self.clock()
            slot = now if self._next is None else max(now, self._next)
            self._next = slot + self.interval
            self.requests += 1
        delay = slot - now
        if delay > 0:
            self.sleep(delay)


class Cooldown:
    """A shared block: one worker's 403/429 stops every worker.

    ``pause()`` extends the block (never shortens it); ``wait()`` holds each
    caller until it expires.  Mirrors ``fetch_decks.BseDownloader``.
    """

    def __init__(self, clock=time.monotonic, sleep=time.sleep):
        self.clock = clock
        self.sleep = sleep
        self._lock = threading.Lock()
        self._until = 0.0
        self.hits = 0

    @property
    def until(self) -> float:
        return self._until

    def pause(self, seconds: float) -> float:
        """Hold every worker for ``seconds`` from now (or longer, if already held)."""
        with self._lock:
            self._until = max(self._until, self.clock() + max(0.0, float(seconds)))
            self.hits += 1
            return self._until

    def wait(self) -> float:
        """Block until the current pause ends; returns the seconds slept."""
        slept = 0.0
        while True:
            gap = self._until - self.clock()
            if gap <= 0:
                return slept
            self.sleep(gap)
            slept += gap


def headers_for(url: str) -> dict[str, str]:
    host = (url.split("/")[2] if "//" in url and len(url.split("/")) > 2 else "").lower()
    if host.endswith("nseindia.com"):
        return dict(NSE_HEADERS)
    if host.endswith("bseindia.com"):
        return dict(BSE_HEADERS)
    return dict(DEFAULT_HEADERS)


def is_pdf(data: bytes | None) -> bool:
    return bool(data) and data[:5] == b"%PDF-"


def sha_match_status(recorded: str | None, actual: str | None) -> str | None:
    """``yes``/``no`` only when the old crawl recorded a sha; ``None`` otherwise."""
    if not recorded or not actual:
        return None
    return "yes" if str(recorded).lower() == str(actual).lower() else "no"


def fetch_url(url: str, *, pacer: Pacer, session=None, attempts: int = 3,
              backoff: float = 30.0, timeout: float = 120.0, sleep=time.sleep,
              cooldown: "Cooldown | None" = None) -> dict[str, Any]:
    """One URL, politely; retries 403/429/5xx with exponential back-off.

    With a ``cooldown`` (the parallel runs), a 403/429/503 from any worker
    pauses every worker for the back-off before the next request.
    """
    import requests

    own = session is None
    session = session or requests.Session()
    record: dict[str, Any] = {"status": "failed", "http_status": None, "bytes": 0,
                              "reason": "", "attempts": 0, "content_type": None,
                              "content": None}
    try:
        for attempt in range(1, attempts + 1):
            if cooldown is not None:
                cooldown.wait()                            # held by another worker
            pacer.wait()
            record["attempts"] = attempt
            try:
                got = session.get(url, headers=headers_for(url), timeout=timeout,
                                  allow_redirects=True)
            except Exception as exc:                       # noqa: BLE001 - network
                record["reason"] = f"network: {type(exc).__name__}: {exc}"[:300]
                if attempt == attempts:
                    break
                sleep(backoff * (2 ** (attempt - 1)))
                continue
            record["http_status"] = got.status_code
            record["content_type"] = (got.headers or {}).get("Content-Type")
            if got.status_code in (403, 429, 503) or got.status_code >= 500:
                record["reason"] = f"http {got.status_code}"
                if attempt == attempts:
                    break
                wait = backoff * (2 ** (attempt - 1))
                if cooldown is not None and got.status_code in (403, 429, 503):
                    cooldown.pause(wait)                   # a block pauses everyone
                else:
                    sleep(wait)
                continue
            if got.status_code != 200:
                record["reason"] = f"http {got.status_code}"
                break
            body = got.content or b""
            record["bytes"] = len(body)
            if not is_pdf(body):
                record["reason"] = "not a PDF"
                break
            record.update(status="ok", content=body)
            break
    finally:
        if own:
            session.close()
    return record


# ---------------------------------------------------------------------------
# validation


def casing_ratio(text: str) -> float | None:
    """Share of letters that are uppercase; ~0.03-0.08 in a normal transcript."""
    text = text or ""
    letters = sum(1 for ch in text if ch.isalpha())
    if not letters:
        return None
    return sum(1 for ch in text if ch.isalpha() and ch.isupper()) / letters


def image_only_share(page_texts: Sequence[str], threshold: int = IMAGE_ONLY_PAGE_CHARS) -> float | None:
    texts = list(page_texts or [])
    if not texts:
        return None
    return sum(1 for t in texts if len(t or "") < threshold) / len(texts)


def pdf_meta(path: str | Path) -> dict[str, Any]:
    """Page/char/casing stats for one file."""
    try:
        import pymupdf as fitz
    except ImportError:                                     # older wheels
        import fitz
    with fitz.open(str(path)) as doc:
        pages = doc.page_count
        texts = [(page.get_text() or "") for page in doc]
    text = "\n".join(texts)
    return {"pages": pages, "chars": len(text), "page_texts": texts, "text": text,
            "uppercase_ratio": casing_ratio(text),
            "image_only_share": image_only_share(texts),
            "speaker_turns": len(_SPEAKER.findall(text)),
            "has_moderator": bool(_MODERATOR.search(text))}


def classify_document(*, title: str, subcat: str | None, pages: int, chars: int,
                      text: str, size_bytes: int | None = None) -> str:
    """``transcript | audio_link | intimation | cover_letter | other``."""
    title = title or ""
    turns = len(_SPEAKER.findall(text or ""))
    moderator = bool(_MODERATOR.search(text or ""))
    transcript_hint = bool(_TRANSCRIPT_HINT.search(title))
    if (chars >= TRANSCRIPT_MIN_CHARS and pages >= TRANSCRIPT_MIN_PAGES
            and (moderator or turns >= 8)
            and (transcript_hint or turns >= 8)):
        return "transcript"
    if _AUDIO.search(title) and chars < TRANSCRIPT_MIN_CHARS:
        return "audio_link"
    if _INTIMATION.search(title) and chars < TRANSCRIPT_MIN_CHARS:
        return "intimation"
    if chars < 3000 and pages <= 3:
        return "cover_letter" if (_CLOSING.search(text or "") or turns <= 2) else "other"
    if _AUDIO.search((text or "")[:2000]) and chars < TRANSCRIPT_MIN_CHARS:
        return "audio_link"
    return "other"


def title_only_class(title: str, subcat: str | None = None) -> str:
    """Pre-fetch guess from the headline (``unknown`` when unsure)."""
    title = title or ""
    if _AUDIO.search(title):
        return "audio_link"
    if _INTIMATION.search(title):
        return "intimation"
    if _TRANSCRIPT_HINT.search(title):
        return "transcript?"
    return "unknown"


def normalize(text: str) -> str:
    """Case-folded, punctuation-free, single-spaced — for the same-document check."""
    text = _METADATA.sub(" ", text or "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.casefold())).strip()


def same_document(pdf_text: str, chunk_text: str, windows: int = 20, length: int = 8) -> float | None:
    """Share of the PDF's sampled 8-word shingles that appear in our stored chunks."""
    haystack = normalize(chunk_text)
    words = normalize(pdf_text).split()
    if not words or not haystack:
        return None
    usable = len(words) - length + 1
    if usable <= 0:
        return 1.0 if " ".join(words) in haystack else 0.0
    span = max(1, usable // windows)
    offsets = list(range(0, usable, span))[:windows]
    hits = sum(1 for i in offsets if " ".join(words[i:i + length]) in haystack)
    return hits / len(offsets)


def chunk_text_for(con, doc_id: int | None, limit: int = 80) -> str:
    if not doc_id:
        return ""
    try:
        rows = con.execute(
            "select content from document_chunks where doc_id = ? order by chunk_index limit ?",
            (int(doc_id), int(limit))).fetchall()
    except Exception:                                       # noqa: BLE001 - read-only guard
        return ""
    return "\n".join(row[0] or "" for row in rows)


# ---------------------------------------------------------------------------
# dedupe


def dedupe(entries: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Mark duplicates: identical bytes first, then the same (isin, quarter).

    Returns ``{newsid: {"dup_of": kept newsid, "dup_kind": "sha256"|"same_call"}}``
    for the entries that duplicate another transcript (fullest transcript kept).
    """
    marks: dict[str, dict[str, Any]] = {}
    by_sha: dict[str, dict[str, Any]] = {}
    for entry in entries:
        sha = entry.get("sha256")
        if not sha or entry.get("doc_class") != "transcript" or entry["newsid"] in marks:
            continue
        kept = by_sha.get(sha)
        if kept is not None:
            marks[entry["newsid"]] = {"dup_of": kept["newsid"], "dup_kind": "sha256"}
        else:
            by_sha[sha] = entry
    by_call: dict[tuple, dict[str, Any]] = {}
    for entry in sorted(entries, key=lambda e: (-(e.get("chars") or 0), e["newsid"])):
        if entry.get("doc_class") != "transcript" or entry["newsid"] in marks:
            continue
        key = (entry.get("isin"), entry.get("quarter"))
        if not key[1]:
            continue
        kept = by_call.get(key)
        if kept is not None:
            marks[entry["newsid"]] = {"dup_of": kept["newsid"], "dup_kind": "same_call"}
        else:
            by_call[key] = entry
    return marks


# ---------------------------------------------------------------------------
# widen mode: the other BSE subcategories real transcripts hide in (no network)


def is_widened_transcript(headline: Any, attachment: Any = None) -> bool:
    """Does this headline (or attachment name) signal a conference-call transcript?

    A plain "schedule of analyst meet" intimation or an audio/video/recording
    link is rejected unless the same text also says *transcript*.  Otherwise a
    transcript needs the word itself, a call synonym (concall / earnings call /
    conference call / investor call) or the Reg. 46(2)(oa) disclosure clause.
    """
    text = f"{headline or ''} {attachment or ''}"
    transcript = bool(_WIDEN_TRANSCRIPT.search(text))
    if not transcript and (_WIDEN_AUDIO.search(text) or _WIDEN_SCHEDULE.search(text)):
        return False
    return transcript or bool(_WIDEN_CALL.search(text) or _WIDEN_REG46OA.search(text))


def widen_rows(ann_rows: Sequence[Sequence[Any]]) -> list[Sequence[Any]]:
    """``WIDEN_ANN_SQL`` rows whose headline or attachment name signals a transcript."""
    return [row for row in ann_rows if is_widened_transcript(row[3], row[2])]


def has_transcript_word(headline: Any, attachment: Any = None) -> bool:
    """Does the headline or attachment name carry the word *transcript*?

    Shivam (2026-10-28): of the fresh widened rows, fetch only those that do.
    The rest are invites, outcomes and schedules; an audio link is still not a
    transcript however the wider widen filter reads it.
    """
    return bool(_WIDEN_TRANSCRIPT.search(f"{headline or ''} {attachment or ''}"))


def transcript_word_rows(candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Candidates whose headline or attachment name carries the word transcript."""
    return [c for c in candidates
            if has_transcript_word(c.get("headline"), c.get("attachment"))]


def overlap_analysis(widened: Sequence[dict[str, Any]],
                     earnings: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Widened candidates the 9,390 Earnings Call set already covers."""
    ec_keys = {(c["isin"], c["quarter"]) for c in earnings
               if c.get("isin") and c.get("quarter")}
    ec_attach = {c["attachment"] for c in earnings if c.get("attachment")}
    by_call = [c for c in widened if (c.get("isin"), c.get("quarter")) in ec_keys]
    by_attach = [c for c in widened if c.get("attachment") and c["attachment"] in ec_attach]
    seen = {c["newsid"] for c in by_call} | {c["newsid"] for c in by_attach}
    keys = [(c["isin"], c["quarter"]) for c in widened
            if c.get("isin") and c.get("quarter")]
    examples = [" | ".join(str(c.get(f) or "")[:70]
                           for f in ("newsid", "symbol", "quarter", "headline"))
                for c in (by_call or by_attach)[:5]]
    return {"widened": len(widened), "earnings": len(earnings),
            "by_call": len(by_call), "by_attachment": len(by_attach),
            "either": len(seen), "fresh": len(widened) - len(seen),
            "internal_call_dupes": len(keys) - len(set(keys)),
            "earnings_without_isin": sum(1 for c in earnings if not c.get("isin")),
            "covered_newsids": seen, "examples": examples}


def _miss_bucket(meta: dict[str, Any] | None) -> str:
    if meta is None:
        return "not in the BSE announcement feed"
    subcat = meta.get("subcat")
    headline = meta.get("headline") or ""
    if subcat not in WIDEN_SUBCATS:
        return "other subcategory"
    if _WIDEN_AUDIO.search(headline):
        return "audio/video or recording link"
    if _WIDEN_SCHEDULE.search(headline):
        return "schedule / intimation only"
    return "no transcript signal in the headline"


def recall_analysis(widened: Sequence[dict[str, Any]],
                    old_rows: Sequence[dict[str, Any]],
                    earnings_newsids: set[str], ann_meta, limit: int = 20) -> dict[str, Any]:
    """How much of the pilot's 1,771 other-subcategory old rows the filter catches."""
    old_fy = [d for d in old_rows if str(d.get("known_dt") or "") >= WINDOW_START]
    others = [d for d in old_fy if d["newsid"] and str(d["newsid"]) not in earnings_newsids]
    meta = ann_meta([str(d["newsid"]) for d in others]) if others else {}
    in_scope = [d for d in others
                if (meta.get(str(d["newsid"])) or {}).get("subcat") in WIDEN_SUBCATS]
    caught_ids = {c["newsid"] for c in widened}
    caught = [d for d in in_scope if str(d["newsid"]) in caught_ids]
    misses = [d for d in others if str(d["newsid"]) not in caught_ids]
    buckets = Counter(_miss_bucket(meta.get(str(d["newsid"]))) for d in misses)
    # list the misses this mode could have caught first; the rest are out of scope
    ordered = ([d for d in misses
                if (meta.get(str(d["newsid"])) or {}).get("subcat") in WIDEN_SUBCATS]
               + [d for d in misses if str(d["newsid"]) not in caught_ids
                  and (meta.get(str(d["newsid"])) or {}).get("subcat")
                  not in WIDEN_SUBCATS])
    lines = []
    for row in ordered[:limit]:
        info = meta.get(str(row["newsid"])) or {}
        fields = (row["newsid"], info.get("subcat") or "(not in ann)",
                  info.get("headline") or row.get("title"))
        lines.append(" | ".join(" ".join(str(x or "").split())[:75] for x in fields))
    return {"others": len(others), "in_scope": len(in_scope), "caught": len(caught),
            "missed": len(misses), "recall": len(caught) / len(others) if others else None,
            "recall_in_scope": len(caught) / len(in_scope) if in_scope else None,
            "miss_buckets": dict(buckets.most_common()),
            "miss_lines": lines}


def staged_path(cand: dict[str, Any], dirs: Sequence[Path]) -> Path | None:
    """Content-addressed PDF for this candidate if either store already holds it."""
    sha = str(cand.get("cd_sha") or "").lower()
    if not sha:
        return None
    for directory in dirs:
        path = pdf_path(sha, Path(directory))
        if path.is_file():
            return path
    return None


def precision_sample(widened: Sequence[dict[str, Any]], dirs: Sequence[Path],
                     n: int = PRECISION_SAMPLE, seed: int = 20261028) -> dict[str, Any]:
    """Classify up to ``n`` widened docs whose PDFs are already on disk."""
    dirs = [Path(d) for d in dirs]
    staged = [(c, staged_path(c, dirs)) for c in widened]
    staged = [(c, path) for c, path in staged if path is not None]
    paths = {c["newsid"]: path for c, path in staged}
    picks = stratified_sample([c for c, _ in staged], n, seed)
    records: list[dict[str, Any]] = []
    for cand in picks:
        record = {"newsid": cand["newsid"], "symbol": cand.get("symbol"),
                  "subcat": cand.get("subcat"), "quarter": cand.get("quarter"),
                  "headline": cand.get("headline"), "status": "invalid"}
        try:
            meta = pdf_meta(paths[cand["newsid"]])
        except Exception as exc:                            # noqa: BLE001 - broken PDF
            record["reason"] = f"pymupdf: {type(exc).__name__}"
        else:
            record.update(
                status="ok", pages=meta["pages"], chars=meta["chars"],
                doc_class=classify_document(
                    title=cand.get("headline") or "", subcat=cand.get("subcat"),
                    pages=meta["pages"], chars=meta["chars"], text=meta["text"]))
        records.append(record)
    ok = [r for r in records if r.get("status") == "ok"]
    transcripts = [r for r in ok if r.get("doc_class") == "transcript"]
    headline_only = len(staged) < n
    if headline_only:                   # fewer than n PDFs: fall back to the headline
        classes = Counter(title_only_class(c.get("headline") or "", c.get("subcat"))
                          for c in stratified_sample(widened, n, seed))
    else:
        classes = Counter(r.get("doc_class") or "invalid" for r in records)
    return {"available": len(staged), "sampled": len(records), "ok": len(ok),
            "headline_only": headline_only, "classes": dict(classes),
            "transcripts": len(transcripts),
            "precision": len(transcripts) / len(records) if records else None,
            "precision_ok": len(transcripts) / len(ok) if ok else None,
            "records": records}


def analyze_widen(*, db_ann: Path | None = None, db_eq: Path | None = None,
                  probe: Path | None = None, root: Path | None = None,
                  n_precision: int = PRECISION_SAMPLE, transcript_word: bool = False,
                  log=print) -> dict[str, Any]:
    """Widen-mode analysis: candidate set, overlap, recall and classifier precision."""
    data = Path(os.environ["REALITY_DATA_ROOT"])
    db_ann = Path(db_ann or data / "bse_announcements.db")
    db_eq = Path(db_eq or data / "equity_intelligence.db")
    con_ann = connect_ro(db_ann, timeout_s=120)
    con_eq = connect_ro(db_eq, timeout_s=240)
    try:
        ec_rows = con_ann.execute(ANN_SQL, (SUBCAT, WINDOW_START)).fetchall()
        wide_raw = con_ann.execute(WIDEN_ANN_SQL,
                                   WIDEN_SUBCATS + (WINDOW_START,)).fetchall()
        kept = widen_rows(wide_raw)
        log(f"widen: {len(wide_raw)} announcements in the four subcategories, "
            f"{len(kept)} whose headline/attachment signals a transcript")
        identity = load_identity(con_eq, [row[1] for row in ec_rows]
                                 + [row[1] for row in kept])
        old_by_news, old_rows = load_old_docs(con_eq)
        chunked = load_chunked(con_eq)
        earnings = build_candidates(ec_rows, identity, old_by_news, chunked)
        widened = build_candidates(kept, identity, old_by_news, chunked)

        def ann_meta(newsids: Sequence[str]) -> dict[str, dict[str, Any]]:
            out: dict[str, dict[str, Any]] = {}
            for part in _chunks(list(newsids), 900):
                sql = ("select NEWSID, SUBCATNAME, CATEGORYNAME, HEADLINE, DissemDT from ann "
                       "where NEWSID in (%s)" % ",".join("?" * len(part)))
                for newsid, subcat, category, headline, dissem in con_ann.execute(sql, part):
                    out[str(newsid)] = {"subcat": subcat, "category": category,
                                        "headline": headline, "known_at": dissem}
            return out

        overlap = overlap_analysis(widened, earnings)
        recall = recall_analysis(widened, old_rows,
                                 {c["newsid"] for c in earnings}, ann_meta)
        fresh_all = [c for c in widened if c["newsid"] not in overlap["covered_newsids"]]
        worded = transcript_word_rows(fresh_all)
        fresh = worded if transcript_word else fresh_all
        dirs = [Path(probe or probe_dir()), Path(root or out_dir())]
        precision = precision_sample(widened, dirs, n_precision)
        return {"window_start": WINDOW_START, "subcats": list(WIDEN_SUBCATS),
                "raw_rows": len(wide_raw), "total": len(widened),
                "attachment_only": sum(1 for row in kept
                                       if not is_widened_transcript(row[3])),
                "earnings_total": len(earnings),
                "transcript_word": {"applied": transcript_word,
                                    "fresh": len(fresh_all), "kept": len(worded)},
                "by_subcat": dict(Counter(c["subcat"] for c in widened)),
                "by_quarter": dict(Counter(c["quarter"] for c in widened)),
                "by_cell": dict(Counter((c["subcat"], c["quarter"]) for c in widened)),
                "overlap": overlap, "recall": recall, "precision": precision,
                "dirs": [str(d) for d in dirs],
                "candidates": widened, "fresh_candidates": fresh}
    finally:
        con_ann.close()
        con_eq.close()


def project_widen(widen: dict[str, Any], interval: float,
                  measured_per_min: float = 18.2) -> dict[str, Any]:
    """Fetch time for the fresh part of the widened set at the enforced rate."""
    fresh = widen["overlap"]["fresh"]
    interval = max(interval, MIN_INTERVAL)
    rate = 60.0 / interval
    precision = widen["precision"].get("precision")
    return {"total": widen["total"], "fresh": fresh,
            "covered": widen["total"] - fresh, "interval": interval,
            "rate_per_min": rate, "requests": fresh,
            "fetch_minutes": fresh * interval / 60.0,
            "fetch_hours": fresh * interval / 3600.0,
            "measured_per_min": measured_per_min,
            "measured_hours": fresh / measured_per_min / 60.0
            if measured_per_min else None,
            "est_transcripts": round(fresh * (precision or 0.0))}


def format_widen_report(widen: dict[str, Any], projection: dict[str, Any]) -> str:
    """Markdown report for every widen acceptance check."""
    lines: list[str] = []
    add = lines.append
    add(f"# Widened BSE concall candidates — FY25+ — {now_iso()}")
    add("")
    add(f"- window: BSE dissemination date >= {widen['window_start']}; known_at = DissemDT")
    add(f"- subcategories: {', '.join(widen['subcats'])}")
    add(f"- announcements read: {widen['raw_rows']:,}; they yield "
        f"**{widen['total']:,}** transcript-signalling candidates")
    add(f"- attachment names are BSE UUIDs, so they add "
        f"{widen['attachment_only']} candidates; the headline does the work")
    add(f"- no network: this is the `--widen --dry-run` report")
    add("")

    add("## 1. Widened candidates by subcategory")
    add("")
    add("| subcategory | rows |")
    add("|---|---|")
    for subcat, count in sorted(widen["by_subcat"].items(), key=lambda kv: -kv[1]):
        add(f"| {subcat} | {count} |")
    add(f"| **total** | **{widen['total']}** |")
    add("")
    add("By fiscal quarter:")
    add("")
    add("| quarter | rows |")
    add("|---|---|")
    for quarter, count in sorted(widen["by_quarter"].items()):
        add(f"| {quarter} | {count} |")
    add("")
    add("Subcategory x quarter:")
    add("")
    add("| subcategory | quarter | rows |")
    add("|---|---|---|")
    for (subcat, quarter), count in sorted(widen["by_cell"].items(),
                                           key=lambda kv: (str(kv[0][1]), str(kv[0][0]))):
        add(f"| {subcat} | {quarter} | {count} |")
    add("")

    add("## 2. Overlap with the 9,390 Earnings Call candidates")
    add("")
    ov = widen["overlap"]
    add(f"- same (ISIN, fiscal quarter): **{ov['by_call']}**")
    add(f"- same attachment name: **{ov['by_attachment']}**")
    add(f"- either key: **{ov['either']}** ({ov['either'] / max(1, ov['widened']):.1%} "
        f"of the widened set already covered)")
    add(f"- fresh rows to fetch: **{ov['fresh']}**")
    tw = widen.get("transcript_word") or {}
    if tw.get("applied"):
        add(f"- fresh rows carrying a transcript word (headline or attachment name): "
            f"**{tw['kept']}** of {tw['fresh']} — only these are fetched")
    add(f"- duplicates inside the widened set by (ISIN, quarter): "
        f"{ov['internal_call_dupes']}; earnings-call rows without an ISIN: "
        f"{ov['earnings_without_isin']}")
    add("")
    add("(ISIN, quarter) is a proxy, not proof of the same document: every covered row has "
        "a different attachment name, so some are different events in a quarter that also "
        "had an Earnings Call transcript. The dedupe drops them anyway, as specified.")
    add("")
    if ov["examples"]:
        add("```")
        lines.extend(ov["examples"])
        add("```")
        add("")

    add("## 3. Recall against the pilot's 1,771 other-subcategory old rows")
    add("")
    rec = widen["recall"]
    add(f"- old rows outside the Earnings Call set: {rec['others']:,}")
    add(f"- of those inside the four subcategories (the widest this mode can reach): "
        f"{rec['in_scope']:,}")
    add(f"- caught by the widened filter: **{rec['caught']:,}** "
        f"({_pct(rec['recall'])} of all {rec['others']:,}, "
        f"{_pct(rec['recall_in_scope'])} of the in-scope {rec['in_scope']:,})")
    add(f"- missed: {rec['missed']:,}")
    add(f"- why the misses missed: {rec['miss_buckets']}")
    add("")
    add("20 misses (newsid | subcategory | headline):")
    add("")
    add("```")
    lines.extend(rec["miss_lines"] or ["(none)"])
    add("```")
    add("")

    add("## 4. Classifier precision on widened docs already on disk")
    add("")
    pr = widen["precision"]
    add(f"- stores checked: {', '.join(widen['dirs'])}")
    add(f"- widened candidates with bytes on disk: {pr['available']}")
    add(f"- sampled and classified: {pr['sampled']} (ok {pr['ok']})")
    if pr["headline_only"]:
        add(f"- fewer than the requested {PRECISION_SAMPLE} PDFs exist, so the sample "
            f"is headline-only (pilot real-transcript test cannot run)")
    else:
        add(f"- precision (real transcripts / sampled): **{_pct(pr['precision'])}** "
            f"({pr['transcripts']}/{pr['sampled']}); over readable PDFs: "
            f"{_pct(pr['precision_ok'])}")
    add(f"- classes: {pr['classes']}")
    add("")
    transcript_share = pr.get("precision")
    if pr["headline_only"]:
        transcript_share = None

    add("## 5. Fetch time for the fresh rows")
    add("")
    add("| metric | value |")
    add("|---|---|")
    add(f"| widened candidates | {projection['total']} |")
    add(f"| already in the Earnings Call set (no fetch) | {projection['covered']} |")
    add(f"| fresh fetches | {projection['fresh']} |")
    add(f"| pacing floor | 1 request / {projection['interval']:.1f} s "
        f"(<= {projection['rate_per_min']:.1f}/min) |")
    add(f"| wall time at the pacing floor | {projection['fetch_hours']:.1f} h "
        f"({projection['fetch_minutes']:.0f} min) |")
    add(f"| wall time at the measured {projection['measured_per_min']:.1f}/min | "
        f"{projection['measured_hours']:.1f} h |")
    add(f"| expected real transcripts (precision {_pct(transcript_share)}) | "
        f"{projection['est_transcripts'] if transcript_share is not None else 'n/a'} |")
    add("")
    add("Run it later, only after the 9,390 fetch has finished:")
    add("")
    add("```bash")
    add("python -m reality_engine.scripts.concall_refetch --widen --fetch --interval 2.5")
    add("```")
    add("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# analysis (no network)


def coverage_analysis(cands: Sequence[dict[str, Any]], old_rows: Sequence[dict[str, Any]],
                      ann_meta) -> dict[str, Any]:
    """Old ``corporate_documents`` CONCALL_TRANSCRIPT rows vs the ann candidates."""
    ann_ids = {c["newsid"] for c in cands}
    old_fy = [d for d in old_rows if str(d.get("known_dt") or "") >= WINDOW_START]
    covered = [d for d in old_fy if d["newsid"] and str(d["newsid"]) in ann_ids]
    nse_only = [d for d in old_fy if not d["newsid"]]
    other = [d for d in old_fy if d["newsid"] and str(d["newsid"]) not in ann_ids]
    meta = ann_meta([str(d["newsid"]) for d in other]) if other else {}
    subcats = Counter((meta.get(str(d["newsid"])) or {}).get("subcat") or "(not in ann)" for d in other)
    missing_from_old = [c for c in cands if not c["cd_id"]]
    cand_keys = {(c["isin"], c["quarter"]) for c in cands if c["isin"] and c["quarter"]}
    cross_dupes = [d for d in (nse_only + other)
                   if d.get("isin") and (d["isin"], fiscal_quarter(d["known_dt"])) in cand_keys]

    def sample(rows, fields):
        out = []
        for row in rows[:5]:
            out.append(" | ".join(str(row.get(f) or "")[:60] for f in fields))
        return out

    return {
        "old_rows_total": len(old_rows),
        "old_fy_rows": len(old_fy),
        "covered_by_ann": len(covered),
        "missing_from_old": len(missing_from_old),
        "missing_from_old_examples": sample(missing_from_old,
                                            ("newsid", "symbol", "known_at", "headline")),
        "old_not_covered": len(other),
        "old_not_covered_subcats": dict(subcats.most_common(10)),
        "old_not_covered_examples": sample(other, ("id", "newsid", "title", "known_dt")),
        "nse_only": len(nse_only),
        "nse_only_examples": sample(nse_only, ("id", "title", "known_dt")),
        "cross_source_dupes": len(cross_dupes),
        "cross_source_examples": sample(cross_dupes, ("id", "title", "known_dt")),
    }


def duplicate_analysis(cands: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Duplicate proxies computable from metadata alone (sha, size, headline)."""
    by_sha: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cand in cands:
        if cand.get("cd_sha"):
            by_sha[cand["cd_sha"]].append(cand)
    sha_groups = [g for g in by_sha.values() if len(g) > 1]

    def group_stats(key_fn) -> tuple[int, int, int, int]:
        groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
        for cand in cands:
            key = key_fn(cand)
            if all(part not in (None, "") for part in key):
                groups[key].append(cand)
        dup_groups = [g for g in groups.values() if len(g) > 1]
        rows = sum(len(g) - 1 for g in dup_groups)
        checked = same = 0
        for group in dup_groups:
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    if a.get("cd_sha") and b.get("cd_sha"):
                        checked += 1
                        same += a["cd_sha"] == b["cd_sha"]
        return len(dup_groups), rows, checked, same

    size_groups, size_rows, size_checked, size_same = group_stats(
        lambda c: (c.get("isin"), c.get("quarter"), c.get("size")))
    call_groups, call_rows, call_checked, call_same = group_stats(
        lambda c: (c.get("isin"), c.get("quarter")))
    wide_groups, wide_rows, _, _ = group_stats(lambda c: (c.get("isin"), c.get("size")))
    head_groups, head_rows, _, _ = group_stats(
        lambda c: (re.sub(r"[^a-z0-9]+", " ", str(c.get("headline") or "").casefold()).strip(),
                   c.get("size")))
    headlines = Counter(re.sub(r"[^a-z0-9]+", " ", str(c.get("headline") or "").casefold()).strip()
                        for c in cands)
    headline_dups = sum(count - 1 for count in headlines.values() if count > 1)
    total = len(cands)
    sha_dup_rows = sum(len(g) - 1 for g in sha_groups)
    return {
        "total": total,
        "sha_groups": len(sha_groups), "sha_dup_rows": sha_dup_rows,
        "sha_dup_share": sha_dup_rows / total if total else None,
        "size_groups": size_groups, "size_dup_rows": size_rows,
        "size_precision_checked": size_checked, "size_precision_same": size_same,
        "size_precision": (size_same / size_checked) if size_checked else None,
        "size_dup_share": size_rows / total if total else None,
        "call_groups": call_groups, "call_dup_rows": call_rows,
        "call_dup_share": call_rows / total if total else None,
        "wide_size_groups": wide_groups, "wide_size_dup_rows": wide_rows,
        "headline_size_groups": head_groups, "headline_size_rows": head_rows,
        "headline_dups": headline_dups,
        "headline_distinct": len(headlines),
    }


def headline_analysis(cands: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """What the 9,390 headlines alone say the document class is (no fetch)."""
    classes = Counter(title_only_class(c.get("headline") or "", c.get("subcat")) for c in cands)
    literal = Counter((c.get("headline") or "").strip() for c in cands)
    return {"classes": dict(classes),
            "distinct_headlines": len(literal),
            "top_headlines": [[h, n] for h, n in literal.most_common(12)],
            "empty_headlines": literal.get("", 0)}


def probe_analysis(index: dict[str, Any], cands: Sequence[dict[str, Any]],
                   old_by_news: dict[str, dict[str, Any]], log=print) -> dict[str, Any]:
    """Classify every staged probe PDF and say how many FY25+ candidates it covers."""
    by_sha = index["by_sha"]
    matched = [c for c in cands if c.get("cd_sha") and c["cd_sha"] in by_sha]
    matched_rows = len(matched)
    matched_sha = {c["cd_sha"] for c in matched}
    rows_by_sha: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cand in matched:
        rows_by_sha[cand["cd_sha"]].append(cand)

    records: list[dict[str, Any]] = []
    for sha, path in sorted(by_sha.items()):
        cand = (rows_by_sha.get(sha) or [None])[0]
        title = (cand or {}).get("headline") or ""
        if not title:
            old = old_by_news.get(str((cand or {}).get("newsid"))) or {}
            title = old.get("title") or ""
        record = {"sha256": sha, "isdir": str(path.parent.name), "bytes": path.stat().st_size,
                  "fy25_match": bool(cand), "symbol": (cand or {}).get("symbol"),
                  "newsid": (cand or {}).get("newsid")}
        try:
            meta = pdf_meta(path)
        except Exception as exc:                            # noqa: BLE001 - broken PDF
            record.update(status="invalid", reason=f"pymupdf: {type(exc).__name__}")
        else:
            record.update(status="ok", pages=meta["pages"], chars=meta["chars"],
                          uppercase_ratio=meta["uppercase_ratio"],
                          image_only_share=meta["image_only_share"],
                          doc_class=classify_document(
                              title=title, subcat=(cand or {}).get("subcat"),
                              pages=meta["pages"], chars=meta["chars"], text=meta["text"]))
            record["sample_text"] = " ".join(meta["text"].split())[:300]
        records.append(record)
        if len(records) % 200 == 0:
            log(f"  probe classified {len(records)}/{len(by_sha)}")

    ok = [r for r in records if r.get("status") == "ok"]
    fy_ok = [r for r in ok if r["fy25_match"]]
    # unique transcripts already held: probe sha + (isin, quarter) collapse
    transcripts = [r for r in fy_ok if r.get("doc_class") == "transcript"]
    kept: dict[tuple | str, dict[str, Any]] = {}
    for record in sorted(transcripts, key=lambda r: (-(r.get("chars") or 0), r["sha256"])):
        cand = (rows_by_sha.get(record["sha256"]) or [{}])[0]
        keys: list[Any] = [("sha", record["sha256"])]
        if cand.get("isin") and cand.get("quarter"):
            keys.append(("call", cand["isin"], cand["quarter"]))
        if any(key in kept for key in keys):
            record["dup_of"] = next(kept[key]["sha256"] for key in keys if key in kept)
            continue
        for key in keys:
            kept[key] = record
    unique_held = [r for r in transcripts if not r.get("dup_of")]
    return {
        "files": index["files"], "bad_name": index["bad_name"],
        "candidates_with_probe": matched_rows,
        "distinct_probe_sha_matched": len(matched_sha),
        "probe_class_all": dict(Counter(r.get("doc_class") or "invalid" for r in records)),
        "probe_class_fy25": dict(Counter(r.get("doc_class") or "invalid" for r in fy_ok)),
        "probe_ok": len(ok), "probe_fy_ok": len(fy_ok),
        "probe_transcripts": len(transcripts),
        "probe_unique_transcripts": len(unique_held),
        "probe_transcript_share": len(transcripts) / len(fy_ok) if fy_ok else None,
        "probe_dup_share": 1 - (len(unique_held) / len(transcripts)) if transcripts else None,
        "probe_records": records,
    }


# ---------------------------------------------------------------------------
# pilot


def _entry_for(cand: dict[str, Any]) -> dict[str, Any]:
    return {
        "newsid": cand["newsid"], "cd_id": cand["cd_id"], "isin": cand["isin"],
        "symbol": cand["symbol"], "headline": cand["headline"],
        "quarter": cand["quarter"], "group": cand["group"],
        "known_at": cand["known_at"], "url": cand["url"],
        "recorded_sha256": cand["cd_sha"], "chunked": cand["chunked"],
        "source": None, "http_status": None, "content_type": None,
        "status": "skipped", "reason": "", "bytes": 0, "sha256": None,
        "recorded_sha256_match": None, "reused": False, "permanent": False,
        "fetched_at": None, "pages": None, "chars": None,
        "uppercase_ratio": None, "image_only_share": None, "doc_class": None,
        "same_doc": None, "sample_text": "",
    }


def inspect_pdf(entry: dict[str, Any], path: Path, cand: dict[str, Any],
                con_eq, log=print) -> None:
    """Fill the validation/classification fields for one stored PDF."""
    try:
        meta = pdf_meta(path)
    except Exception as exc:                                # noqa: BLE001 - broken PDF
        entry.update(status="invalid", reason=f"pymupdf: {type(exc).__name__}")
        return
    entry.update(
        status="ok", pages=meta["pages"], chars=meta["chars"],
        uppercase_ratio=meta["uppercase_ratio"],
        image_only_share=meta["image_only_share"],
        doc_class=classify_document(title=cand.get("headline") or "",
                                    subcat=cand.get("subcat"),
                                    pages=meta["pages"], chars=meta["chars"],
                                    text=meta["text"]),
        sample_text=" ".join(meta["text"].split())[:300])
    if cand.get("chunked"):
        entry["same_doc"] = same_document(meta["text"],
                                          chunk_text_for(con_eq, cand.get("chunk_doc_id")))


def _finish(entry: dict[str, Any], cand: dict[str, Any], data_bytes: bytes | None,
            root: Path, con_eq, dry_run: bool = False) -> None:
    """Store the bytes, validate/classify the PDF, settle the journal status."""
    if data_bytes and is_pdf(data_bytes):
        sha = sha256_of(data_bytes)
        entry.update(bytes=len(data_bytes), sha256=sha)
        entry["recorded_sha256_match"] = sha_match_status(cand.get("cd_sha"), sha)
        target = pdf_path(sha, root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data_bytes)
        entry["path"] = str(target)
        if not entry["reused"]:
            entry["fetched_at"] = now_iso()
        inspect_pdf(entry, target, cand, con_eq)
    elif not dry_run:
        entry.update(status="failed", reason=entry.get("reason") or (
            "stored file is not a PDF" if entry.get("reused") else "no bytes"))
    entry["permanent"] = (entry["status"] in ("failed", "invalid")
                          and is_permanent_failure(entry))


def _new_session():
    """One ``requests`` session per worker thread (connection reuse per thread)."""
    import requests
    return requests.Session()


def run_pilot(*, n: int = 200, seed: int = 20261027, interval: float = 2.5,
              backoff: float = 30.0, dry_run: bool = False,
              db_ann: Path | None = None, db_eq: Path | None = None,
              root: Path | None = None, probe: Path | None = None,
              limit: int | None = None, analysis: dict[str, Any] | None = None,
              candidates: Sequence[dict[str, Any]] | None = None,
              manifest: str | None = None, mode: str = "full",
              workers: int = 1, journal: Path | None = None,
              fetch=None, log=print) -> dict[str, Any]:
    """Sample, resume, fetch (optionally in parallel), journal, dedupe, write.

    The journal at ``<root>/_journal_<mode>.jsonl`` is loaded first: newsids
    it holds as ok or permanently failed are skipped, transient failures are
    retried, and every finished candidate is appended (and flushed) at once.
    The manifest is the journal's rows for this sample plus the new ones.
    """
    data = Path(os.environ["REALITY_DATA_ROOT"])
    db_ann = Path(db_ann or data / "bse_announcements.db")
    db_eq = Path(db_eq or data / "equity_intelligence.db")
    root = Path(root or out_dir())
    started = time.monotonic()
    journal = Path(journal or journal_path(root, mode))
    workers = max(1, int(workers))
    fetch_one = fetch or fetch_url

    con_ann = connect_ro(db_ann, timeout_s=120)
    con_eq = connect_ro(db_eq, timeout_s=240)
    writer: JournalWriter | None = None
    try:
        if candidates is None:
            ann_rows = con_ann.execute(ANN_SQL, (SUBCAT, WINDOW_START)).fetchall()
            identity = load_identity(con_eq, [row[1] for row in ann_rows])
            old_by_news, _ = load_old_docs(con_eq)
            chunked = load_chunked(con_eq)
            cands = build_candidates(ann_rows, identity, old_by_news, chunked)
        else:
            cands = list(candidates)
        index = (analysis or {}).get("_probe_index") or probe_index(probe)
        by_sha = index["by_sha"]
        picks = stratified_sample(cands, n, seed)
        if limit:
            picks = picks[:limit]
        reused_n = sum(1 for p in picks if p.get("cd_sha") in by_sha)
        prior = {newsid: entry for newsid, entry in load_journal(journal).items()
                 if journal_done(entry)}
        entries: dict[str, dict[str, Any]] = {
            c["newsid"]: prior[c["newsid"]] for c in picks if c["newsid"] in prior}
        skipped_journal = sum(1 for c in picks if c["newsid"] in entries)
        log(f"candidates={len(cands)} sampled={len(picks)} probe_reusable={reused_n} "
            f"resumed={skipped_journal} journal={journal}")

        pacer = Pacer(interval)
        cooldown = Cooldown() if workers > 1 else None
        if not dry_run:
            writer = JournalWriter(journal)

        def finish(i: int, cand: dict[str, Any], entry: dict[str, Any],
                   data_bytes: bytes | None) -> None:
            _finish(entry, cand, data_bytes, root, con_eq, dry_run)
            entries[cand["newsid"]] = entry
            if writer is not None:
                writer.append(entry)
            log(f"[{i:>3}/{len(picks)}] {cand['symbol'] or '?':<12} {entry['quarter']} "
                f"{entry['status']:<7} {entry['source'] or '-':<5} "
                f"{entry['doc_class'] or '-':<12} {entry.get('chars') or 0:>7}c "
                f"{entry['reason'][:40]}")

        remote: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
        for i, cand in enumerate(picks, 1):
            if cand["newsid"] in entries:
                continue
            entry = _entry_for(cand)
            probe_path = by_sha.get(cand.get("cd_sha") or "")
            if probe_path is not None:
                entry.update(source="probe", reused=True)
                try:
                    data_bytes = probe_path.read_bytes()
                except OSError:
                    data_bytes = None
                finish(i, cand, entry, data_bytes)
            elif dry_run:
                entry.update(status="skipped", reason="dry_run")
                finish(i, cand, entry, None)
            else:
                remote.append((i, cand, entry))

        if remote and workers > 1:
            sessions: queue.Queue = queue.Queue()
            for _ in range(workers):
                sessions.put(_new_session())

            def one(cand: dict[str, Any]) -> dict[str, Any]:
                session = sessions.get()
                try:
                    return fetch_one(cand["url"], pacer=pacer, session=session,
                                     backoff=backoff, cooldown=cooldown)
                finally:
                    sessions.put(session)

            try:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {pool.submit(one, cand): (i, cand, entry)
                               for i, cand, entry in remote}
                    for future in as_completed(futures):
                        i, cand, entry = futures[future]
                        try:
                            got = future.result()
                        except Exception as exc:            # noqa: BLE001 - worker died
                            entry.update(reason=f"worker: {type(exc).__name__}: {exc}"[:300])
                            finish(i, cand, entry, None)
                            continue
                        entry.update(source="bse", http_status=got.get("http_status"),
                                     content_type=got.get("content_type"),
                                     reason=got.get("reason") or "")
                        finish(i, cand, entry, got.get("content"))
            finally:
                while not sessions.empty():
                    sessions.get().close()
        else:
            session = _new_session() if remote else None
            try:
                for i, cand, entry in remote:
                    got = fetch_one(cand["url"], pacer=pacer, session=session,
                                    backoff=backoff, cooldown=cooldown)
                    entry.update(source="bse", http_status=got.get("http_status"),
                                 content_type=got.get("content_type"),
                                 reason=got.get("reason") or "")
                    finish(i, cand, entry, got.get("content"))
            finally:
                if session is not None:
                    session.close()
        ordered = [entries[c["newsid"]] for c in picks if c["newsid"] in entries]
    finally:
        if writer is not None:
            writer.close()
        con_ann.close()
        con_eq.close()

    marks = dedupe(ordered)
    for entry in ordered:
        if entry["newsid"] in marks:
            entry.update(marks[entry["newsid"]])
    elapsed = time.monotonic() - started
    report = summarize(ordered, elapsed=elapsed, pacer_requests=pacer.requests,
                       interval=interval, dry_run=dry_run)
    report["skipped_journal"] = skipped_journal
    report["workers"] = workers
    report["journal"] = str(journal)
    if not dry_run:
        write_manifest(root, ordered,
                       manifest or ("_manifest_widen.jsonl" if mode == "widen"
                                    else "_manifest.jsonl"))
    report["entries"] = ordered
    return report


# ---------------------------------------------------------------------------
# seeding the journal from a previous run's stdout log

LOG_ROW = re.compile(
    r"^\[\s*(\d+)/(\d+)\][ \t]+(\S+)[ \t]+(\S+)[ \t]+(\S+)[ \t]+(\S+)[ \t]+(\S+)"
    r"[ \t]+(\d+)c(.*)$")


def parse_log_rows(text: str) -> list[dict[str, Any]]:
    """The ``[i/9390] SYMBOL quarter status source class chars reason`` log lines."""
    rows: list[dict[str, Any]] = []
    for line in (text or "").splitlines():
        match = LOG_ROW.match(line)
        if not match:
            continue
        index, total, symbol, quarter, status, source, doc_class, chars, reason = match.groups()
        rows.append({"index": int(index), "total": int(total),
                     "symbol": "" if symbol == "?" else symbol,
                     "quarter": quarter, "status": status,
                     "source": None if source == "-" else source,
                     "doc_class": None if doc_class == "-" else doc_class,
                     "chars": int(chars), "reason": reason.strip()})
    return rows


def _log_candidate(row: dict[str, Any], picks: Sequence[dict[str, Any]],
                   by_cell: dict[tuple, list[dict[str, Any]]],
                   claimed: set[str]) -> tuple[dict[str, Any] | None, bool]:
    """Which sampled candidate a log row fetched: by position, else by cell.

    The position is exact while the announcement feed is unchanged; a new
    announcement shifts every later ``i``, so a row whose symbol/quarter
    disagree with the pick at its index is matched to the first unclaimed
    candidate of its (symbol, quarter) cell instead.
    """
    i = row["index"]
    cand = picks[i - 1] if 0 < i <= len(picks) else None
    if cand is not None and str(cand.get("quarter")) == row["quarter"] \
            and (cand.get("symbol") or "") == row["symbol"]:
        return cand, False
    for other in by_cell.get((row["symbol"], row["quarter"]), ()):
        if other["newsid"] not in claimed:
            return other, True
    return None, False


def seed_entries(rows: Sequence[dict[str, Any]], picks: Sequence[dict[str, Any]],
                 root: Path | str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Journal entries for the ok log rows whose PDF is already in ``root``."""
    by_cell: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for cand in picks:
        by_cell[(cand.get("symbol") or "", str(cand.get("quarter")))].append(cand)
    claimed: set[str] = set()
    entries: list[dict[str, Any]] = []
    counts = {"log_rows": len(rows), "ok_rows": 0, "seeded": 0, "realigned": 0,
              "unmapped": 0}
    for row in rows:
        if row["status"] != "ok":
            continue
        counts["ok_rows"] += 1
        cand, realigned = _log_candidate(row, picks, by_cell, claimed)
        sha = str((cand or {}).get("cd_sha") or "").lower()
        path = pdf_path(sha, Path(root)) if sha else None
        if cand is None or path is None or not path.is_file():
            counts["unmapped"] += 1
            continue
        claimed.add(cand["newsid"])
        counts["seeded"] += 1
        counts["realigned"] += int(realigned)
        entries.append(_seeded_entry(cand, row, path))
    return entries, counts


def _seeded_entry(cand: dict[str, Any], row: dict[str, Any], path: Path) -> dict[str, Any]:
    """A journal entry for a candidate whose PDF the log says was fetched."""
    entry = _entry_for(cand)
    entry.update(status="ok", source=row.get("source") or "bse",
                 reused=row.get("source") == "probe", bytes=path.stat().st_size,
                 sha256=path.stem.lower(), chars=row.get("chars"),
                 doc_class=row.get("doc_class"), path=str(path),
                 reason="", seeded_from_log=True)
    return entry


def seed_journal_from_log(log_path: str | Path, *, candidates=None, seed: int = 20261027,
                          root: Path | None = None, db_ann: Path | None = None,
                          db_eq: Path | None = None, mode: str = "full",
                          log=print) -> dict[str, Any]:
    """Rebuild a run's journal from its stdout log (no network, no re-fetch).

    ``i`` in the log is the position in the run's ``stratified_sample``, so the
    same candidate set and seed reproduce it; the sample size is the log's own
    ``/9390``.  Only ok rows whose PDF (the candidate's recorded sha256) is in
    the store are journalled; the rest are left to re-fetch.
    """
    data = Path(os.environ["REALITY_DATA_ROOT"])
    db_ann = Path(db_ann or data / "bse_announcements.db")
    db_eq = Path(db_eq or data / "equity_intelligence.db")
    root = Path(root or out_dir())
    rows = parse_log_rows(Path(log_path).read_text(encoding="utf-8", errors="replace"))
    con_ann = connect_ro(db_ann, timeout_s=120)
    con_eq = connect_ro(db_eq, timeout_s=240)
    try:
        if candidates is None:
            ann_rows = con_ann.execute(ANN_SQL, (SUBCAT, WINDOW_START)).fetchall()
            identity = load_identity(con_eq, [row[1] for row in ann_rows])
            old_by_news, _ = load_old_docs(con_eq)
            chunked = load_chunked(con_eq)
            cands = build_candidates(ann_rows, identity, old_by_news, chunked)
        else:
            cands = list(candidates)
    finally:
        con_ann.close()
        con_eq.close()
    picks = stratified_sample(cands, rows[0]["total"] if rows else len(cands), seed)
    entries, counts = seed_entries(rows, picks, root)
    journal = journal_path(root, mode)
    if entries:
        with JournalWriter(journal) as writer:
            for entry in entries:
                writer.append(entry)
    log(f"seed: {len(cands)} candidates, {counts['ok_rows']} ok log rows -> "
        f"{counts['seeded']} journalled ({counts['realigned']} matched by "
        f"symbol+quarter), {counts['unmapped']} to re-fetch, journal={journal}")
    return {"journal": str(journal), "mode": mode, "sample": len(picks),
            "candidates": len(cands), "root": str(root), **counts}


def write_manifest(root: Path, entries: Sequence[dict[str, Any]],
                   name: str = "_manifest.jsonl") -> Path:
    """One JSON line per row, rewritten whole."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def summarize(entries: Sequence[dict[str, Any]], *, elapsed: float, pacer_requests: int,
              interval: float, dry_run: bool = False) -> dict[str, Any]:
    """Pilot acceptance data as plain values."""
    ok = [e for e in entries if e.get("status") == "ok"]
    transcripts = [e for e in ok if e.get("doc_class") == "transcript"]
    unique = [e for e in transcripts if not e.get("dup_of")]
    by_source: dict[str, Counter] = defaultdict(Counter)
    for entry in entries:
        source = entry.get("source") or "none"
        by_source[source]["tried"] += 1
        if entry.get("source") == "probe":
            by_source[source]["reused"] += 1
        if entry.get("status") == "ok":
            by_source[source]["ok"] += 1
        else:
            by_source[source]["failed"] += 1
            by_source[source][entry.get("reason") or "unknown"] += 1
    by_cell: dict[tuple, Counter] = defaultdict(Counter)
    for entry in entries:
        cell = (entry.get("quarter"), entry.get("group"))
        by_cell[cell]["tried"] += 1
        by_cell[cell]["ok" if entry.get("status") == "ok" else "failed"] += 1
        if entry.get("doc_class") == "transcript" and not entry.get("dup_of"):
            by_cell[cell]["transcript"] += 1
    classes = Counter(e.get("doc_class") or ("skipped" if e.get("status") == "skipped" else "failed")
                      for e in entries)
    casing = [e["uppercase_ratio"] for e in ok if e.get("uppercase_ratio") is not None]
    matches = [e["same_doc"] for e in ok if e.get("same_doc") is not None]
    pages = [e["pages"] for e in ok if e.get("pages")]
    chars = [e["chars"] for e in ok if e.get("chars") is not None]
    image_only = [e["image_only_share"] for e in ok if e.get("image_only_share") is not None]
    minutes = max(elapsed, 1e-9) / 60.0
    return {
        "sampled": len(entries), "ok": len(ok), "failed": sum(1 for e in entries
                                                             if e.get("status") not in ("ok", "skipped")),
        "skipped": sum(1 for e in entries if e.get("status") == "skipped"),
        "transcripts": len(transcripts), "unique_transcripts": len(unique),
        "duplicates": len(transcripts) - len(unique),
        "duplicate_share": (len(transcripts) - len(unique)) / len(transcripts) if transcripts else None,
        "transcript_share": len(transcripts) / len(ok) if ok else None,
        "reused": sum(1 for e in entries if e.get("reused")),
        "by_source": {k: dict(v) for k, v in by_source.items()},
        "by_cell": {f"{q}-{g}": dict(v) for (q, g), v in sorted(by_cell.items(), key=str)},
        "classes": dict(classes), "elapsed_min": minutes,
        "pdf_per_min": len(ok) / minutes if minutes else None,
        "pacer_requests": pacer_requests, "interval": interval, "dry_run": dry_run,
        "pages": _stats(pages), "chars": _stats(chars),
        "image_only_share": _stats(image_only),
        "uppercase_ratio": _stats(casing),
        "same_doc": _stats(matches),
        "same_doc_rate": (sum(1 for m in matches if m and m >= 0.5) / len(matches))
        if matches else None,
        "lowercased": sum(1 for c in casing if c < 0.005),
        "sha_match": Counter(e.get("recorded_sha256_match") for e in entries
                             if e.get("recorded_sha256_match")).most_common(),
        "documented_sha": sum(1 for e in entries if e.get("recorded_sha256")),
    }


def _stats(values: Sequence[float]) -> dict[str, Any]:
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return {"n": 0}
    mid = vals[len(vals) // 2]

    def pct(q: float) -> float:
        return vals[min(len(vals) - 1, int(q * (len(vals) - 1)))]

    return {"n": len(vals), "min": round(vals[0], 4), "median": round(mid, 4),
            "mean": round(sum(vals) / len(vals), 4), "p90": round(pct(0.9), 4),
            "max": round(vals[-1], 4)}


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def project(analysis: dict[str, Any], pilot: dict[str, Any] | None, interval: float) -> dict[str, Any]:
    """Full-run projection, counting only unique real transcripts."""
    total = analysis["total"]
    reuse = analysis["probe"]["candidates_with_probe"]
    fetch_needed = total - reuse
    share = (pilot or {}).get("transcript_share") or analysis["probe"].get("probe_transcript_share")
    dup = (pilot or {}).get("duplicate_share")
    if dup is None:
        dup = (analysis["duplicates"].get("call_dup_share")
               or analysis["duplicates"].get("size_dup_share") or 0.0)
    success = ((pilot or {}).get("ok") or 0) / max(1, (pilot or {}).get("sampled") or 1)
    est_transcripts = total * (share or 0.0)
    unique = est_transcripts * (1 - (dup or 0.0))
    already = analysis["probe"].get("probe_unique_transcripts") or 0
    effective_fetches = fetch_needed / success if success else fetch_needed
    seconds = effective_fetches * max(interval, MIN_INTERVAL)
    return {
        "total": total, "reuse": reuse, "fetch_needed": fetch_needed,
        "transcript_share": share, "duplicate_share": dup, "success_rate": success,
        "est_transcripts": round(est_transcripts), "est_unique_transcripts": round(unique),
        "already_held_unique": already, "still_to_fetch_unique": max(0, round(unique) - already),
        "fetch_minutes": seconds / 60.0, "fetch_hours": seconds / 3600.0,
        "requests": round(effective_fetches), "interval": max(interval, MIN_INTERVAL),
        "rate_per_min": 60.0 / max(interval, MIN_INTERVAL),
    }


def format_report(analysis: dict[str, Any], pilot: dict[str, Any] | None,
                  projection: dict[str, Any]) -> str:
    """Markdown report for every acceptance check."""
    lines: list[str] = []
    add = lines.append
    add(f"# Concall PDF refetch — FY25+ BSE transcripts — {now_iso()}")
    add("")
    add(f"- window: BSE dissemination date >= {WINDOW_START} (ann.SUBCATNAME = "
        f"'{SUBCAT}'), known_at = DissemDT, never a crawl date")
    add(f"- candidates: {analysis['total']} announcements, "
        f"{len(analysis['by_quarter'])} fiscal quarters x A-P/Q-Z")
    add(f"- rate enforced: >= "
        f"{max(pilot['interval'] if pilot else MIN_INTERVAL, MIN_INTERVAL):.2f} s between "
        f"requests across {(pilot or {}).get('workers') or 1} worker(s) "
        f"(<= {projection['rate_per_min']:.1f} requests/min); a 403/429/503 pauses every worker")
    add("")

    add("## 1. Candidate set")
    add("")
    add("| quarter | A-P | Q-Z | total |")
    add("|---|---|---|---|")
    for quarter in sorted({q for q, _ in analysis["by_cell"]}):
        cell = analysis["by_cell"]
        ap = cell.get((quarter, "A-P"), 0)
        qz = cell.get((quarter, "Q-Z"), 0)
        add(f"| {quarter} | {ap} | {qz} | {ap + qz} |")
    add("")
    add(f"Attachment sizes: min={analysis['sizes']['min']:,} median={analysis['sizes']['median']:,} "
        f"p90={analysis['sizes']['p90']:,} max={analysis['sizes']['max']:,} bytes; "
        f"{analysis['sizes']['n']} rows")
    add("")

    add("## 2. Old `corporate_documents` coverage (FY25+)")
    add("")
    cov = analysis["coverage"]
    add(f"- old CONCALL_TRANSCRIPT rows with a usable filing date in the window: {cov['old_fy_rows']}")
    add(f"- of them covered by this ann candidate set (bse_newsid): {cov['covered_by_ann']}")
    add(f"- candidates missing from corporate_documents: {cov['missing_from_old']}")
    add(f"- old rows NOT in this candidate set: {cov['old_not_covered']} filed under another BSE "
        f"subcategory + {cov['nse_only']} with no bse_newsid (NSE-sourced)")
    add(f"- of those old rows, same (isin, fiscal quarter) as a candidate "
        f"(BSE/NSE or refiled duplicate): {cov['cross_source_dupes']}")
    if cov["old_not_covered_subcats"]:
        add(f"- their BSE subcategories: {cov['old_not_covered_subcats']}")
    add("")
    add("Missing from the old side (examples):")
    add("")
    add("```")
    lines.extend(cov["missing_from_old_examples"] or ["(none)"])
    add("```")
    add("")
    add("Missing from the candidate set (examples):")
    add("")
    add("```")
    lines.extend(cov["old_not_covered_examples"] or ["(none)"])
    add("```")
    add("")

    add("## 3. Probe store (read-only reuse)")
    add("")
    probe = analysis["probe"]
    add(f"- staged PDFs: {probe['files']} (bad sha/name: {probe['bad_name']})")
    add(f"- candidates with bytes already on disk: {probe['candidates_with_probe']} "
        f"({probe['candidates_with_probe'] / max(1, analysis['total']):.1%}) "
        f"across {probe['distinct_probe_sha_matched']} distinct files")
    add(f"- classification of those (all {probe['probe_fy_ok']} readable): "
        f"{probe['probe_class_fy25']}")
    add(f"- unique real transcripts already held: {probe['probe_unique_transcripts']} "
        f"of {probe['probe_transcripts']} transcripts "
        f"(transcript share {_pct(probe['probe_transcript_share'])}, "
        f"duplicate share {_pct(probe['probe_dup_share'])})")
    add("")

    add("## 4. Headlines (all candidates, no fetch)")
    add("")
    add(f"- distinct headlines: {analysis['headlines']['distinct_headlines']}; "
        f"repeat-headline rows: {analysis['duplicates']['headline_dups']}")
    add("")
    add("| guessed class | rows |")
    add("|---|---|")
    for name, count in sorted(analysis["headlines"]["classes"].items(), key=lambda kv: -kv[1]):
        add(f"| {name} | {count} |")
    add("")
    add("Top headlines:")
    add("")
    add("```")
    for headline, count in analysis["headlines"]["top_headlines"]:
        add(f"{count:>5}  {headline[:100]}")
    add("```")
    add("")

    add("## 5. Duplicates from metadata alone (no fetch)")
    add("")
    dup = analysis["duplicates"]
    add(f"- identical sha256 among rows that carry one: {dup['sha_dup_rows']} duplicate rows "
        f"in {dup['sha_groups']} groups ({dup['sha_dup_share']:.2%})")
    add(f"- same (isin, quarter, attachment size): {dup['size_dup_rows']} duplicate rows in "
        f"{dup['size_groups']} groups ({_pct(dup['size_dup_share'])}); "
        f"size-rule precision where both rows carry a sha256: "
        f"{dup['size_precision_same']}/{dup['size_precision_checked']} pairs")
    add(f"- same (isin, quarter) — the same call refiled under another newsid: "
        f"{dup['call_dup_rows']} duplicate rows in {dup['call_groups']} groups "
        f"({_pct(dup['call_dup_share'])})")
    add(f"- same (isin, attachment size) ignoring quarter: {dup['wide_size_dup_rows']} rows")
    add(f"- same (headline, size): {dup['headline_size_rows']} rows in "
        f"{dup['headline_size_groups']} groups")
    add("")

    if pilot is not None:
        add("## 6. Pilot (200 docs)")
        add("")
        add(f"- sampled {pilot['sampled']}, ok {pilot['ok']}, failed {pilot['failed']}, "
            f"reused {pilot['reused']}, skipped {pilot['skipped']}")
        if pilot.get("skipped_journal"):
            add(f"- resumed from the journal (not fetched again): "
                f"{pilot['skipped_journal']}")
        add(f"- wall clock {pilot['elapsed_min']:.1f} min, {pilot['pacer_requests']} HTTP "
            f"requests, {pilot['pdf_per_min'] or 0:.2f} PDFs/min end-to-end")
        add(f"- classes: {pilot['classes']}")
        add(f"- transcript share on fetched docs: {_pct(pilot['transcript_share'])}; "
            f"duplicates: {pilot['duplicates']} "
            f"({_pct(pilot['duplicate_share'])} of transcripts)")
        add("")
        add("| source | tried | reused | ok | failed | reasons |")
        add("|---|---|---|---|---|---|")
        for source, cell in sorted(pilot["by_source"].items()):
            reasons = ", ".join(f"{k}={v}" for k, v in sorted(cell.items())
                                if k not in ("tried", "ok", "failed", "reused")) or "-"
            add(f"| {source} | {cell.get('tried', 0)} | {cell.get('reused', 0)} | "
                f"{cell.get('ok', 0)} | {cell.get('failed', 0)} | {reasons} |")
        add("")
        add("| cell | tried | ok | failed | unique transcripts |")
        add("|---|---|---|---|---|")
        for cell, counts in pilot["by_cell"].items():
            add(f"| {cell} | {counts.get('tried', 0)} | {counts.get('ok', 0)} | "
                f"{counts.get('failed', 0)} | {counts.get('transcript', 0)} |")
        add("")
        for key, label in (("pages", "pages"), ("chars", "text chars"),
                           ("image_only_share", "image-only page share"),
                           ("uppercase_ratio", "uppercase letter share"),
                           ("same_doc", "same-document shingle match")):
            stats = pilot[key]
            if not stats.get("n"):
                add(f"- {label}: no data")
                continue
            add(f"- {label}: n={stats['n']} min={stats['min']} median={stats['median']} "
                f"mean={stats['mean']} p90={stats['p90']} max={stats['max']}")
        if pilot.get("same_doc_rate") is not None:
            add(f"- same-document match rate (>= 0.5 shingles): {pilot['same_doc_rate']:.1%}")
        add(f"- lowercased sources (uppercase < 0.5%): {pilot['lowercased']}")
        add(f"- recorded sha256 matched the fetched bytes: {pilot['sha_match']} "
            f"of {pilot['documented_sha']} rows carrying one")
        add("")

    add("## 7. Projection for the full FY25+ window (unique real transcripts)")
    add("")
    pr = projection
    add("| metric | value |")
    add("|---|---|")
    add(f"| candidates | {pr['total']} |")
    add(f"| already on disk (reuse, no fetch) | {pr['reuse']} |")
    add(f"| fetches still needed | {pr['fetch_needed']} |")
    add(f"| measured transcript share | {_pct(pr['transcript_share'])} |")
    add(f"| measured duplicate share | {_pct(pr['duplicate_share'])} |")
    add(f"| estimated unique real transcripts | {pr['est_unique_transcripts']} |")
    add(f"| already held unique transcripts | {pr['already_held_unique']} |")
    add(f"| unique transcripts still to fetch | {pr['still_to_fetch_unique']} |")
    add(f"| fetch wall time at {pr['rate_per_min']:.1f} req/min | "
        f"{pr['fetch_hours']:.1f} h ({pr['fetch_minutes']:.0f} min) |")
    add(f"| requests incl. retries (success {pr['success_rate']:.0%}) | {pr['requests']} |")
    add("")

    if pilot is not None:
        add("## 8. Samples")
        add("")
        for entry in [e for e in pilot.get("entries") or [] if e.get("status") == "ok"][:5]:
            add(f"### {entry['symbol']} {entry['quarter']} — {entry['doc_class']} "
                f"({entry['known_at']})")
            add("")
            add(f"- source={entry['source']} reused={entry['reused']} bytes={entry['bytes']} "
                f"sha256 `{str(entry['sha256'])[:16]}…` pages={entry['pages']} "
                f"chars={entry['chars']} upper={entry['uppercase_ratio']}")
            add(f"- headline: {entry['headline']}")
            add("")
            add("```")
            add((entry.get("sample_text") or "")[:300])
            add("```")
            add("")
    return "\n".join(lines)


def analyze(*, db_ann: Path | None = None, db_eq: Path | None = None,
            probe: Path | None = None, classify_probe: bool = True,
            probe_json: Path | None = None, log=print) -> dict[str, Any]:
    """Full-set analysis with no network access."""
    data = Path(os.environ["REALITY_DATA_ROOT"])
    db_ann = Path(db_ann or data / "bse_announcements.db")
    db_eq = Path(db_eq or data / "equity_intelligence.db")
    con_ann = connect_ro(db_ann, timeout_s=120)
    con_eq = connect_ro(db_eq, timeout_s=240)
    try:
        ann_rows = con_ann.execute(ANN_SQL, (SUBCAT, WINDOW_START)).fetchall()
        identity = load_identity(con_eq, [row[1] for row in ann_rows])
        old_by_news, old_rows = load_old_docs(con_eq)
        chunked = load_chunked(con_eq)
        cands = build_candidates(ann_rows, identity, old_by_news, chunked)
        log(f"candidates={len(cands)} distinct_isin={len({c['isin'] for c in cands})}")

        def ann_meta(newsids: Sequence[str]) -> dict[str, dict[str, Any]]:
            out: dict[str, dict[str, Any]] = {}
            for part in _chunks(list(newsids), 900):
                sql = ("select NEWSID, SUBCATNAME, CATEGORYNAME, HEADLINE, DissemDT from ann "
                       "where NEWSID in (%s)" % ",".join("?" * len(part)))
                for newsid, subcat, category, headline, dissem in con_ann.execute(sql, part):
                    out[str(newsid)] = {"subcat": subcat, "category": category,
                                        "headline": headline, "known_at": dissem}
            return out

        coverage = coverage_analysis(cands, old_rows, ann_meta)
        index = probe_index(probe)
        if classify_probe:
            log(f"classifying {index['files']} staged probe PDFs (no network)…")
            probe_data = probe_analysis(index, cands, old_by_news, log=log)
        else:
            probe_data = {"files": index["files"], "bad_name": index["bad_name"],
                          "candidates_with_probe": 0, "distinct_probe_sha_matched": 0,
                          "probe_class_all": {}, "probe_class_fy25": {}, "probe_ok": 0,
                          "probe_fy_ok": 0, "probe_transcripts": 0,
                          "probe_unique_transcripts": 0, "probe_transcript_share": None,
                          "probe_dup_share": None, "probe_records": []}
        by_quarter = Counter(c["quarter"] for c in cands)
        by_cell = Counter((c["quarter"], c["group"]) for c in cands)
        sizes = [int(c["size"]) for c in cands if c["size"]]
        sizes.sort()
        size_stats = {"n": len(sizes), "min": sizes[0] if sizes else 0,
                      "median": sizes[len(sizes) // 2] if sizes else 0,
                      "p90": sizes[int(0.9 * (len(sizes) - 1))] if sizes else 0,
                      "max": sizes[-1] if sizes else 0}
        result = {
            "total": len(cands), "by_quarter": dict(by_quarter),
            "by_cell": dict(by_cell), "sizes": size_stats,
            "coverage": coverage, "duplicates": duplicate_analysis(cands),
            "headlines": headline_analysis(cands), "probe": probe_data,
            "_probe_index": index,
        }
        if probe_json:
            Path(probe_json).parent.mkdir(parents=True, exist_ok=True)
            with Path(probe_json).open("w", encoding="utf-8") as handle:
                for record in probe_data["probe_records"]:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return result
    finally:
        con_ann.close()
        con_eq.close()


# ---------------------------------------------------------------------------
# CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m reality_engine.scripts.concall_refetch",
        description="FY25+ BSE concall PDF refetch: analysis + 200-doc pilot.")
    ap.add_argument("--n", type=int, default=None,
                    help="sample size (default 200; --widen --fetch defaults to all)")
    ap.add_argument("--seed", type=int, default=20261027, help="sampling seed")
    ap.add_argument("--interval", type=float, default=2.5,
                    help=f"seconds between requests across all workers "
                         f"(hard floor {MIN_INTERVAL} = {60 / MIN_INTERVAL:.0f}/min)")
    ap.add_argument("--workers", type=int, default=1,
                    help="concurrent fetchers (default 1); one session per worker and "
                         "one shared pacer keep the total at 60/interval per minute")
    ap.add_argument("--backoff", type=float, default=30.0, help="first 403/429/503 back-off (s)")
    ap.add_argument("--limit", type=int, help="only process the first N sampled rows")
    ap.add_argument("--analyze-only", action="store_true", help="no network, no pilot")
    ap.add_argument("--no-probe-classify", action="store_true",
                    help="skip classifying the staged probe PDFs (faster)")
    ap.add_argument("--dry-run", action="store_true",
                    help="no network/writes; reports what the journal already covers")
    ap.add_argument("--seed-journal-from-log", metavar="PATH",
                    help="journal the ok rows of a previous full run from its stdout "
                         "log (its [i/9390] lines) and exit; no network")
    ap.add_argument("--widen", action="store_true",
                    help="widen mode: the other four BSE subcategories "
                         "(report only unless --fetch)")
    ap.add_argument("--transcript-word", action="store_true",
                    help="with --widen: keep only rows whose headline or attachment "
                         "name carries the word transcript")
    ap.add_argument("--rescue-file", metavar="PATH",
                    help="fetch exactly the newsids in this JSON list "
                         "(the dedupe-rescue mode)")
    ap.add_argument("--fetch", action="store_true",
                    help="with --widen: download the widened set")
    ap.add_argument("--root", help=f"PDF store (default {out_dir()})")
    ap.add_argument("--probe-dir", help=f"staged probe PDFs (default {probe_dir()})")
    ap.add_argument("--db-ann", help="bse_announcements.db (default REALITY_DATA_ROOT)")
    ap.add_argument("--db-eq", help="equity_intelligence.db (default REALITY_DATA_ROOT)")
    ap.add_argument("--report", help="write the markdown report here")
    args = ap.parse_args(argv)
    if args.interval < MIN_INTERVAL:
        ap.error(f"--interval must be >= {MIN_INTERVAL}s "
                 f"({60 / MIN_INTERVAL:.0f} requests/min)")
    if args.workers < 1:
        ap.error("--workers must be >= 1")
    if args.transcript_word and not args.widen:
        ap.error("--transcript-word needs --widen")
    if args.rescue_file and args.widen:
        ap.error("--rescue-file and --widen are separate runs; pick one")
    if args.seed_journal_from_log and (args.widen or args.rescue_file):
        ap.error("--seed-journal-from-log seeds the full run's journal; "
                 "widen and rescue build other candidate sets")

    if args.seed_journal_from_log:
        path = Path(args.seed_journal_from_log)
        if not path.is_file():
            ap.error(f"--seed-journal-from-log not found: {path}")
        seeded = seed_journal_from_log(
            path, seed=args.seed,
            root=Path(args.root) if args.root else None,
            db_ann=Path(args.db_ann) if args.db_ann else None,
            db_eq=Path(args.db_eq) if args.db_eq else None)
        print(json.dumps(seeded, indent=2, default=str))
        return 0

    if args.rescue_file:
        path = Path(args.rescue_file)
        if not path.is_file():
            ap.error(f"--rescue-file not found: {path}")
        try:
            rescue = load_rescue(path)
        except (OSError, ValueError) as exc:
            ap.error(str(exc))
        if not rescue:
            ap.error(f"no usable newsid rows in {path}")
        pilot = run_pilot(n=len(rescue), seed=args.seed, interval=args.interval,
                          backoff=args.backoff, limit=args.limit, dry_run=args.dry_run,
                          db_ann=Path(args.db_ann) if args.db_ann else None,
                          db_eq=Path(args.db_eq) if args.db_eq else None,
                          root=Path(args.root) if args.root else None,
                          probe=Path(args.probe_dir) if args.probe_dir else None,
                          candidates=rescue, manifest="_manifest_rescue.jsonl",
                          mode="rescue", workers=args.workers)
        print(json.dumps({k: v for k, v in pilot.items() if k != "entries"},
                         indent=2, default=str))
        return 0

    if args.widen:
        widen = analyze_widen(db_ann=Path(args.db_ann) if args.db_ann else None,
                              db_eq=Path(args.db_eq) if args.db_eq else None,
                              probe=Path(args.probe_dir) if args.probe_dir else None,
                              root=Path(args.root) if args.root else None,
                              transcript_word=args.transcript_word)
        projection = project_widen(widen, args.interval)
        text = format_widen_report(widen, projection)
        print(text)
        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(text, encoding="utf-8")
        if args.dry_run or not args.fetch:
            return 0
        pilot = run_pilot(n=args.n if args.n is not None else len(widen["fresh_candidates"]),
                          seed=args.seed, interval=args.interval,
                          backoff=args.backoff, limit=args.limit,
                          root=Path(args.root) if args.root else None,
                          probe=Path(args.probe_dir) if args.probe_dir else None,
                          candidates=widen["fresh_candidates"], mode="widen",
                          workers=args.workers)
        print(json.dumps({k: v for k, v in pilot.items() if k != "entries"},
                         indent=2, default=str))
        return 0

    analysis = analyze(db_ann=Path(args.db_ann) if args.db_ann else None,
                       db_eq=Path(args.db_eq) if args.db_eq else None,
                       probe=Path(args.probe_dir) if args.probe_dir else None,
                       classify_probe=not args.no_probe_classify,
                       probe_json=(out_dir() / "_probe_classes.jsonl")
                       if not args.analyze_only and not args.dry_run else None)
    pilot = None
    if not args.analyze_only:
        pilot = run_pilot(n=args.n if args.n is not None else 200,
                          seed=args.seed, interval=args.interval,
                          backoff=args.backoff, limit=args.limit,
                          db_ann=Path(args.db_ann) if args.db_ann else None,
                          db_eq=Path(args.db_eq) if args.db_eq else None,
                          root=Path(args.root) if args.root else None,
                          probe=Path(args.probe_dir) if args.probe_dir else None,
                          analysis=analysis, dry_run=args.dry_run,
                          workers=args.workers)
        print(json.dumps({k: v for k, v in pilot.items() if k != "entries"},
                         indent=2, default=str))
    projection = project(analysis, pilot, args.interval)
    text = format_report(analysis, pilot, projection)
    print(text)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
