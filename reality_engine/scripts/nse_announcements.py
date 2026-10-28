"""NSE corporate-announcements raw fetcher (one symbol at a time, resumable).

Endpoint (the JSON behind nseindia.com -> Companies -> Corporate Filings ->
Announcements)::

    GET https://www.nseindia.com/api/corporate-announcements
        ?index=equities&symbol=RELIANCE&from_date=01-04-2024&to_date=28-10-2026

Session handling: ``reality_engine.ingestion.nse_client.NSEClient`` -- curl_cffi
Chrome TLS impersonation, then GET the home page once for the cookies. NSE
answers 200 to the API only with that cookie + a normal User-Agent and Referer;
a 401/403 means the cookie is gone, so the session is rebuilt and the call is
retried with exponential back-off (also for 429/503).

``known_at`` is NSE's own dissemination clock, taken from the row in this order:
``exchdisstime`` (exchange dissemination, when present) -> ``an_dt`` (the
announcement date/time NSE shows) -> ``sort_date`` (NSE's display sort key, the
same clock rounded to the minute). ``sm_isin`` is used when the row carries it,
otherwise the ISIN is resolved from ``master_companies`` (read-only).

Per announcement the JSONL keeps the raw row plus symbol, isin, subject, desc,
known_at, attachment_url and the download ``bucket``. Nothing but raw bytes is
downloaded.

Every row is metadata-bucketed before any download (Shivam, 2026-10-28):
``transcript`` (transcript/meet filings), ``material`` (orders, management/
auditor changes, acquisitions, results, presentations, press releases, ratings,
capex, fund raises, litigation, insolvency, ...), ``procedural`` (newspaper ads,
share-certificate paperwork, trading window, record date, AGM/scrutinizer
paperwork, ESOP mechanics, RTA/compliance certificates) and ``unclear``.
Only the buckets in ``--download-buckets`` (default ``transcript,material``)
are fetched; the JSONL row is always kept.

Usage::

    python -m reality_engine.scripts.nse_announcements --symbols RELIANCE,TCS \\
        --from 2024-04-01 --to 2026-10-28 --out .tmp/nse_ann --download

    # the two raw runs the rulings are for (default buckets: transcript,material)
    python -m reality_engine.scripts.nse_announcements --nse-only 114 \\
        --from 2024-04-01 --download --out D:/RealityEngine/raw/nse_announcements/run_2026-10-28
    python -m reality_engine.scripts.nse_announcements --transcript-gap 273 \\
        --from 2024-04-01 --download --download-buckets transcript \\
        --out D:/RealityEngine/raw/nse_announcements/transcript_gap_2026-10-28

    # recall against the old corpus (read-only)
    python -m reality_engine.scripts.nse_announcements --recall .tmp/nse_ann
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from reality_engine.config import DATA_DIR, NSE_HEADERS
from reality_engine.ingestion.nse_client import NSEClient

logger = logging.getLogger("reality_engine.nse_announcements")

API = "https://www.nseindia.com/api/corporate-announcements"
BOARD_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
INDEX_FOR_SEGMENT = {"SME": "sme"}
DEFAULT_OUT = r"D:\RealityEngine\raw\nse_announcements"
MIN_INTERVAL = 0.5          # floor; NSE probe 2026-10-28 took 400/min bursts with no block, back-off handles 403/429
BACKOFF_BASE = 3.0
BACKOFF_CAP = 120.0
# (connect, read). A plain float only bounds connect in curl_cffi; NSE also
# sometimes accepts the connection and then never answers (seen 2026-10-28), so
# the read timeout is what actually ends a silent drop.
HTTP_TIMEOUT = (10.0, 45.0)
BLOCK_STATUSES = (401, 403, 429, 503)

# What a transcript / meet filing looks like in NSE's subject or description.
# ("Con. Call" is NSE's own abbreviation in the subject line.)
DOWNLOAD_PATTERN = re.compile(
    r"con[\s.\-]?call|transcript|analyst|investor\s*(meet|call|conference)|"
    r"earnings\s*(call|conference)|institutional\s*investor",
    re.I,
)
# The tight signal: the document itself says transcript. The broader meet
# family also carries intimations, audio links and cancellations.
TRANSCRIPT_PATTERN = re.compile(r"transcript|con[\s.\-]?call|earnings\s*call", re.I)

# Download buckets (Shivam, 2026-10-28): the attachment is judged from the
# metadata alone, before any byte is fetched.
BUCKETS = ("transcript", "material", "procedural", "unclear")
DEFAULT_DOWNLOAD_BUCKETS = ("transcript", "material")

TRANSCRIPT_BUCKET = re.compile(
    r"transcri|con\.?\s*call|conference\s+call|earnings?\s*call|analyst|"
    r"investor\s+meet|institutional\s+investor|audio\s+(recording|link)|"
    r"recording of (the )?(call|meet)",
    re.I,
)
# NSE's own filing vocabulary: routine paperwork whatever the attachment says.
PROCEDURAL_FILING = re.compile(
    r"^(copy of newspaper|loss of share certificates?|issue of duplicate share|"
    r"trading window|record date|revised record date|book closure|"
    r"shareholders meeting|committee meeting updates|esop/esos/esps|"
    r"monitoring agency report|corrigendum|integrated filing- governance|"
    r"structural digital database|address change|"
    r"change in company secretary|disclosure under sebi takeover|"
    r"certificate under sebi \(depositories|quarterly compliance report|"
    r"declaration for audit reports|statement of deviation)",
    re.I,
)
# Routine wording that outranks a material-looking word (newspaper publication
# of results is still an ad, an ESOP allotment is still an exercise, an
# exchange clarification is still a query response).
PROCEDURAL_EARLY = re.compile(
    r"newspaper|copy of newspaper|"
    r"loss of share cert|duplicate share cert|share certificate[s]?\b|"
    r"trading window|depositor(y|ies) (and|&) participants|"
    r"esop|esos|esps|employee stock option|sweat equity|"
    r"structural digital database|monitoring agency|"
    r"deviation[\(\s]|utilisation of (the )?(proceeds|issue)|"
    r"takeover regulation|\bsast\b|substantial acquisition|"
    r"registered office|registrar|\brta\b|contact detail|functional website|"
    r"compliance (report|audit|certificate)|corporate governance|"
    r"unmodified opinion|clarification|news verification|spurt in volume|"
    r"price movement|investor grievance|74\s*\(5\)",
    re.I,
)
# Filing types that are material even when the text also carries takeover
# boilerplate (an open offer is the event, not the disclosure paperwork).
MATERIAL_FILING = re.compile(
    r"^(public announcement|open offer|offers? for sale|rights issue|"
    r"qualified institutional placement|preferential issue|buy ?back|bonus|"
    r"dividend|acquisition|amalgamation|merger|scheme of arrangement|demerger)",
    re.I,
)
# Business / ownership / financial / regulatory events worth a download.
MATERIAL_EVENT = re.compile(
    r"bagging|receiv\w* of orders?|receipt of orders?|orders? received|"
    r"award\w* of orders?|orders?/contracts?|orders? passed|"
    r"action\(s\) (taken|initiated)|penalt|fines? levied|"
    r"appoint\w*|re-?appoint\w*|resign\w*|cessation|retire\w*|"
    r"change in designation|change[s]? in (senior )?(management|director|auditor)|"
    r"senior management|"
    r"\bsmps?\b|senior managerial|promoter group|authori[sz]ed capital|forfeiture|"
    r"product registration|repeat order|rescission|termination|revocation|"
    r"\bkmp\b|demise|ultimate holding|holding company|"
    r"acqui(re|sition)|amalgamat|merger|demerg|scheme of arrangement|"
    r"financial results?|financial statements|integrated filing- financial|"
    r"outcome of board meeting|"
    r"investor presentation|presentation|press release|"
    r"credit rating|\brating\b|capacity (addition|expansion)|\bplant\b|"
    r"commissioning|product launch|stock split|share split|"
    r"commercial production|manufacturing (facility|plant)|securing order|"
    r"work order|media release|dissolution of a promoter|promoter group entity|"
    r"memorandum of understanding|\bagreements?\b|joint venture|"
    r"litigation|dispute|insolvency|\bcirp\b|committee of creditors|"
    r"fund ?rais|debenture|issuance of (securities|shares)|letter of offer|\bqip\b|"
    r"rights? issue|qualified institutional|preferential|"
    r"allotment|issue of securities|bonus|dividend|buy ?back|open offer|"
    r"offer for sale|diversif|disinvest|stake|subsidiar|restructur|"
    r"fraud|default|fire|shutdown|resumption|strike|suspension of trading|"
    r"assessment order|demand notice|tax appellate|notice of hearing|"
    r"highest ever|turnover of|operational highlights|\bcci\b|\blaunch(ed|es)?\b|"
    r"\bleas(e|ed|ing)\b|"
    r"monthly business|business update|guidance|reclassif|"
    r"material issue|material event",
    re.I,
)
# Routine wording that only wins when nothing material was said.
PROCEDURAL_LATE = re.compile(
    r"record date|book closure|scrutini[sz]er|postal ballot|voting result|"
    r"notice of (the )?[\w\s]*general meeting|annual general meeting|"
    r"extra(ordinary)? general meeting|shareholders? meeting|committee meeting|"
    r"corrigendum|integrated filing.? governance|re-lodgement|transfer request|"
    r"physical shareholder|letters? to shareholders|dispatch of (a )?letter|"
    r"utilisation of funds",
    re.I,
)
# "Outcome of Board Meeting" is material unless the outcome is AGM/holding
# paperwork or a trading-window closure (Shivam, 2026-10-28).
OUTCOME_IS_PROCEDURAL = re.compile(
    r"trading window|(annual|extra(ordinary)?) general meeting|scrutini[sz]er|"
    r"postal ballot|voting result",
    re.I,
)

_KNOWN_AT_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d-%b-%Y %H:%M:%S",
    "%d-%b-%Y %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d-%b-%Y",
    "%Y-%m-%d",
    "%d-%m-%Y",
)


# --------------------------------------------------------------------- parse
def parse_known_at(value: Any) -> Optional[str]:
    """NSE timestamp ('03-Aug-2026 17:56:28', '2026-08-03 17:56:28', ...) -> ISO, or None.

    The date stays a date (no midnight invented) when the payload has no clock.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in _KNOWN_AT_FORMATS:
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            continue
    return None


def known_at_of(row: Dict[str, Any]) -> Optional[str]:
    """NSE dissemination timestamp for one announcement row."""
    for key in ("exchdisstime", "an_dt", "sort_date"):
        got = parse_known_at(row.get(key))
        if got:
            return got
    return None


def is_valid_isin(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 12 and value.startswith("IN") and value.isalnum()


def attachment_url(row: Dict[str, Any]) -> Optional[str]:
    att = str(row.get("attchmntFile") or "").strip()
    if not att:
        return None
    if att.startswith("http"):
        return att
    return "https://www.nseindia.com" + (att if att.startswith("/") else "/" + att)


def normalize(row: Dict[str, Any], symbol: str, isin_map: Dict[str, str]) -> Dict[str, Any]:
    """One raw NSE row -> the stored record (raw row preserved under ``raw``).

    ``subject`` is empty on this endpoint for the equity feed; NSE's own subject
    vocabulary (the values the site's Subject dropdown filters on) is carried in
    ``desc`` -- e.g. 'Analysts/Institutional Investor Meet/Con. Call Updates'.
    So ``subject`` falls back to ``desc`` and both are kept.
    """
    sym = str(row.get("symbol") or symbol or "").strip().upper()
    raw_isin = str(row.get("sm_isin") or "").strip().upper()
    if is_valid_isin(raw_isin):
        isin, isin_source = raw_isin, "row"
    else:
        isin, isin_source = isin_map.get(sym), "master_companies"
    desc = str(row.get("desc") or "").strip()
    rec = {
        "symbol": sym,
        "isin": isin,
        "isin_source": isin_source if isin else None,
        "subject": str(row.get("subject") or "").strip() or desc,
        "desc": desc,
        "kind": record_kind(row),
        "known_at": known_at_of(row),
        "attachment_url": attachment_url(row),
        "seq_id": str(row.get("seq_id") or "").strip() or None,
        "file_size": row.get("attFileSize") or row.get("fileSize"),
        "raw": row,
    }
    rec["bucket"] = bucket(rec)
    return rec


def row_size_bytes(row: Dict[str, Any]) -> Optional[int]:
    """NSE's human-readable fileSize ('1.2 MB') -> bytes, when it can be trusted."""
    text = str(row.get("attFileSize") or row.get("fileSize") or "")
    m = re.match(r"([\d.]+)\s*(B|KB|MB|GB)", text.strip(), re.I)
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2).upper()
    return int(value * {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}[unit])


def needs_download(path: Path, announced_size: Optional[int]) -> bool:
    """Resume rule: an existing file is kept unless it is provably the wrong size."""
    if not path.exists():
        return True
    have = path.stat().st_size
    if have <= 0:
        return True
    if announced_size is None:
        return False
    # fileSize is rounded to 0.1 unit, so allow 5%.
    return abs(have - announced_size) > max(1024, announced_size * 0.05)


def _data_root() -> Path:
    return Path(os.environ.get("REALITY_DATA_ROOT") or DATA_DIR)


def load_isin_map() -> Dict[str, str]:
    """symbol -> isin from master_companies (read-only). Empty map on any miss."""
    from reality_engine.db.readonly import connect_ro

    path = _data_root() / "equity_intelligence.db"
    out: Dict[str, str] = {}
    try:
        con = connect_ro(path, timeout_s=30)
        try:
            for symbol, isin in con.execute(
                "SELECT nse_symbol, isin FROM master_companies WHERE nse_symbol IS NOT NULL"
            ):
                if symbol and is_valid_isin(isin):
                    out[str(symbol).strip().upper()] = isin
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001 - resolution is a nicety, never a hard stop
        logger.warning("ISIN map unavailable (%s); rows without sm_isin go ISIN-less", e)
    return out


def matches_subject(text: str, filters: Iterable[str]) -> bool:
    filters = [f for f in filters if f]
    if not filters:
        return True
    low = text.lower()
    return any(f.lower() in low for f in filters)


def is_transcript_like(record: Dict[str, Any]) -> bool:
    text = f"{record.get('subject')} {record.get('desc')} {record['raw'].get('attchmntText') or ''}"
    return bool(DOWNLOAD_PATTERN.search(text))


def record_kind(row: Dict[str, Any]) -> str:
    """'transcript' when the filing says so, 'meet' for the wider meet family, else 'other'.

    The meet family is mostly 1-page intimations / audio links / cancellations,
    so the narrow tag is what a transcript job should select on.
    """
    text = " ".join(str(row.get(k) or "") for k in ("desc", "attchmntText", "attchmntFile"))
    if TRANSCRIPT_PATTERN.search(text):
        return "transcript"
    return "meet" if DOWNLOAD_PATTERN.search(text) else "other"


def bucket(record: Dict[str, Any]) -> str:
    """'transcript' | 'material' | 'procedural' | 'unclear', from metadata only.

    The judgement uses ``desc`` plus ``raw.attchmntText`` -- never the
    attachment -- so the download happens only for rows that are already worth
    having. A row earns ``transcript`` when it is a transcript or a meet filing,
    ``procedural`` for routine paperwork, ``material`` for a business /
    ownership / financial / regulatory event, and ``unclear`` otherwise.
    """
    desc = str(record.get("desc") or record.get("subject") or "").strip()
    raw = record.get("raw")
    raw = raw if isinstance(raw, dict) else record
    text = f"{desc} {raw.get('attchmntText') or ''}"
    if TRANSCRIPT_BUCKET.search(desc):
        return "transcript"
    if PROCEDURAL_FILING.search(desc):
        return "procedural"
    if MATERIAL_FILING.search(desc):
        return "material"
    if desc.lower() in ("investor presentation", "press release", "press release (revised)"):
        return "material"                       # a deck or a press note, not a call
    if desc.lower() == "outcome of board meeting" and OUTCOME_IS_PROCEDURAL.search(text):
        return "procedural"
    if PROCEDURAL_EARLY.search(text):
        return "procedural"
    if TRANSCRIPT_BUCKET.search(text):
        return "transcript"                     # e.g. Updates: "transcript of analyst call"
    if MATERIAL_EVENT.search(text):
        return "material"
    if PROCEDURAL_LATE.search(text):
        return "procedural"
    return "unclear"


def record_bucket(record: Dict[str, Any]) -> str:
    """Bucket of a stored JSONL record; rows written before the field existed are re-judged."""
    stored = record.get("bucket")
    return str(stored) if stored in BUCKETS else bucket(record)


# --------------------------------------------------------------------- fetch
class AnnouncementFetcher:
    """Symbol-by-symbol NSE announcements fetch with pacing, back-off and resume."""

    def __init__(
        self,
        out: Path,
        interval: float = MIN_INTERVAL,
        client: Optional[NSEClient] = None,
        sleep: Callable[[float], None] = time.sleep,
        isin_map: Optional[Dict[str, str]] = None,
    ):
        self.out = Path(out)
        self.interval = max(MIN_INTERVAL, float(interval))
        self.client = client
        self.sleep = sleep
        self.isin_map = isin_map if isin_map is not None else load_isin_map()
        self.blocks: Dict[int, int] = {}
        self.requests_made = 0
        self._keys_logged = False

    # -- session / http ------------------------------------------------
    def _client(self) -> NSEClient:
        if self.client is None:
            self.client = NSEClient()
        return self.client

    def _rebuild(self, client: NSEClient) -> None:
        """Give the client a brand-new cookie/TLS session after a block.

        NSE's 401/403 means the cookie jar is dead; re-warming the same jar does
        not help, so the whole session is rebuilt.
        """
        NSEClient.__init__(client)

    def get(self, url: str, tries: int = 5):
        """GET with cookie warm-up and exponential back-off on 401/403/429/503."""
        last = None
        for attempt in range(tries):
            client = self._client()
            client._warmup_session()  # no-op after the first call
            try:
                self.requests_made += 1
                resp = client.session.get(url, headers=NSE_HEADERS, timeout=HTTP_TIMEOUT)
            except Exception as e:  # noqa: BLE001 - transient network
                last = e
                resp = None
            if resp is not None and resp.status_code == 200:
                return resp
            status = getattr(resp, "status_code", None)
            if status is not None:
                self.blocks[status] = self.blocks.get(status, 0) + 1
                if status not in BLOCK_STATUSES and status != 200:
                    logger.warning("NSE HTTP %s: %s", status, url)
                    return resp
            wait = min(BACKOFF_BASE * (2 ** attempt), BACKOFF_CAP)
            logger.warning(
                "NSE %s on %s (attempt %d/%d) - backing off %.0fs",
                status or last, url.split("?")[0], attempt + 1, tries, wait,
            )
            self.sleep(wait)
            self._rebuild(client)  # fresh cookies + TLS session
        logger.warning("NSE %s: giving up after %d attempts", url.split("?")[0], tries)
        return None

    # -- one symbol ----------------------------------------------------
    def _rows(self, resp) -> List[Dict[str, Any]]:
        payload = resp.json()
        if isinstance(payload, dict):
            rows = payload.get("data") or []
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []
        rows = [r for r in rows if isinstance(r, dict)]
        if rows and not self._keys_logged:
            logger.info("NSE announcement row fields: %s", sorted(rows[0]))
            self._keys_logged = True
        return rows

    def fetch_symbol(self, symbol: str, frm: str, to: str, index: str = "equities",
                     subject: Optional[str] = None) -> List[Dict[str, Any]]:
        a = datetime.strptime(frm, "%Y-%m-%d").strftime("%d-%m-%Y")
        b = datetime.strptime(to, "%Y-%m-%d").strftime("%d-%m-%Y")
        url = (f"{API}?index={index}&symbol={_quote(symbol)}"
               f"&from_date={a}&to_date={b}")
        if subject:
            # Server-side subject filter: NSE's own subject vocabulary for this
            # endpoint is the `desc` text (e.g. 'Analysts/Institutional Investor
            # Meet/Con. Call Updates'); a string match narrows the payload.
            url += f"&subject={_quote(subject)}"
        resp = self.get(url)
        if resp is None or getattr(resp, "status_code", 0) != 200:
            logger.warning("NSE %s: no payload (status %s)", symbol, getattr(resp, "status_code", None))
            return []
        try:
            return self._rows(resp)
        except ValueError:
            logger.warning("NSE %s: non-JSON payload", symbol)
            return []

    def write_symbol(self, symbol: str, rows: List[Dict[str, Any]], path: Optional[Path] = None) -> int:
        """Append records to ``{symbol}.jsonl``, skipping seq_ids already stored."""
        path = path or (self.out / f"{symbol}.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        seen = set()
        if path.exists():
            with path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        seen.add(json.loads(line).get("seq_id"))
                    except ValueError:
                        continue
        new = 0
        with path.open("a", encoding="utf-8") as f:
            for row in rows:
                rec = normalize(row, symbol, self.isin_map)
                key = rec["seq_id"] or rec["attachment_url"] or rec["known_at"]
                if key in seen:
                    continue
                seen.add(key)
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                new += 1
        return new

    def download(self, record: Dict[str, Any], folder: Path) -> str:
        """Fetch one attachment into ``folder``; 'ok' / 'skipped' / 'error'."""
        url = record.get("attachment_url")
        if not url:
            return "error"
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", url.rsplit("/", 1)[-1] or "attachment.pdf")[:120]
        path = folder / record["symbol"] / name
        if not needs_download(path, row_size_bytes(record["raw"])):
            return "skipped"
        resp = self.get(url)
        if resp is None or getattr(resp, "status_code", 0) != 200:
            return "error"
        body = resp.content
        if not body:
            return "error"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return "ok"

    # -- pilot run -----------------------------------------------------
    def run(
        self,
        symbols: List[str],
        frm: str,
        to: str,
        subject_filter: Optional[List[str]] = None,
        download: bool = False,
        index_by_symbol: Optional[Dict[str, str]] = None,
        download_buckets: Optional[Iterable[str]] = None,
    ) -> Dict[str, int]:
        self.out.mkdir(parents=True, exist_ok=True)
        manifest = self.out / "_manifest.csv"
        done = {}
        if manifest.exists():
            with manifest.open(newline="", encoding="utf-8") as f:
                done = {r["window"]: r["status"] for r in csv.DictReader(f)}
        stats = {"symbols": 0, "skipped": 0, "announcements": 0, "new": 0,
                 "downloaded": 0, "download_skipped": 0, "download_error": 0}
        subject = subject_filter[0] if subject_filter else None
        for symbol in symbols:
            key = f"{symbol}|{frm}|{to}"
            if done.get(key) in ("ok", "empty"):
                stats["skipped"] += 1
                continue
            self.sleep(self.interval)
            rows = self.fetch_symbol(
                symbol, frm, to, (index_by_symbol or {}).get(symbol, "equities"), subject
            )
            if not rows:
                # a company that moved board is listed under the other index
                alt = "sme" if (index_by_symbol or {}).get(symbol, "equities") == "equities" else "equities"
                self.sleep(self.interval)
                rows = self.fetch_symbol(symbol, frm, to, alt, subject)
            if subject_filter:
                rows = [r for r in rows
                        if matches_subject(f"{r.get('desc')} {r.get('subject')}", subject_filter)]
            new = self.write_symbol(symbol, rows)
            stats["symbols"] += 1
            stats["announcements"] += len(rows)
            stats["new"] += new
            for row in rows:
                bkey = "bucket_" + bucket(row)
                stats[bkey] = stats.get(bkey, 0) + 1
            if download:
                wanted = set(download_buckets or DEFAULT_DOWNLOAD_BUCKETS)
                folder = self.out / "attachments"
                for record in self.read_symbol(symbol):
                    if record_bucket(record) not in wanted:
                        continue
                    self.sleep(self.interval)
                    got = self.download(record, folder)
                    stats[{"ok": "downloaded", "skipped": "download_skipped",
                           "error": "download_error"}[got]] += 1
            with manifest.open("a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if manifest.stat().st_size == 0 or f.tell() == 0:
                    w.writerow(["window", "status", "rows", "fetched_at"])
                w.writerow([key, "ok" if rows else "empty", len(rows),
                            datetime.now().isoformat(timespec="seconds")])
            logger.info("%s: %d rows (%d new)", symbol, len(rows), new)
        return stats

    def read_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        path = self.out / f"{symbol}.jsonl"
        if not path.exists():
            return []
        out = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        return out


def _quote(text: str) -> str:
    from urllib.parse import quote
    return quote(text, safe="")


# --------------------------------------------------------------------- pilot
def pilot_lists(nse_only: int = 25, transcript: int = 25) -> Dict[str, List[str]]:
    """The two pilot groups from the live DB (read-only, bounded queries)."""
    from reality_engine.db.readonly import connect_ro

    con = connect_ro(_data_root() / "equity_intelligence.db", timeout_s=60)
    try:
        only = [r[0] for r in con.execute(
            "SELECT m.nse_symbol FROM master_companies m "
            "LEFT JOIN (SELECT symbol, COUNT(*) n FROM corporate_documents GROUP BY symbol) d "
            "  ON d.symbol = m.nse_symbol "
            "WHERE m.nse_symbol IS NOT NULL AND (m.bse_code IS NULL OR m.bse_code = '') "
            # AGENTS.md §3.13: INE_AUTO* ISINs are synthetic test fixtures, never companies.
            "AND m.isin NOT LIKE 'INE_AUTO%' "
            "AND m.nse_symbol NOT LIKE '%-%' "   # -RE / -PP are rights / partly paid, not companies
            "ORDER BY COALESCE(d.n, 0) DESC, m.nse_symbol LIMIT ?", (nse_only,))]
        gap = [r[0] for r in con.execute(
            "SELECT symbol, COUNT(*) n FROM corporate_documents "
            "WHERE doc_type = 'CONCALL_TRANSCRIPT' AND (bse_newsid IS NULL OR bse_newsid = '') "
            "GROUP BY symbol ORDER BY n DESC, symbol LIMIT ?", (transcript,))]
    finally:
        con.close()
    return {"nse_only": only, "transcript_gap": gap}


def recall(out: Path, frm: str = "2024-04-01", window_days: int = 3) -> Dict[str, Any]:
    """Old-corpus transcripts vs what the fetcher found: symbol + real call date +-window.

    The old NSE/BSE gap rows carry a crawl date in ``doc_date`` (event_source
    'doc_date', e.g. every row stamped 2026-08-28), so the match date is
    ``call_date`` -- the date the transcript says the call was held. Rows with
    no ``call_date`` cannot be matched by date at all and are counted apart.
    """
    from reality_engine.db.readonly import connect_ro

    con = connect_ro(_data_root() / "equity_intelligence.db", timeout_s=60)
    try:
        symbols = sorted(p.stem for p in Path(out).glob("*.jsonl"))
        found: Dict[str, set] = {}
        for symbol in symbols:
            found[symbol] = {str(r.get("known_at"))[:10] for r in _read_jsonl(Path(out) / f"{symbol}.jsonl")}
        rows = []
        q = ("SELECT symbol, call_date FROM corporate_documents "
             "WHERE doc_type = 'CONCALL_TRANSCRIPT' AND (bse_newsid IS NULL OR bse_newsid = '') "
             f"AND symbol IN ({','.join('?' * len(symbols))}) "
             f"AND (call_date IS NULL OR date(call_date) >= '{frm}')")
        for symbol, call_date in con.execute(q, symbols):
            if not call_date:
                rows.append({"symbol": symbol, "call_date": None, "recalled": False,
                             "days_off": None, "matchable": False})
                continue
            offsets = []
            for d in found.get(symbol, set()):
                if not d:
                    continue
                try:
                    offsets.append((date.fromisoformat(d) - date.fromisoformat(call_date)).days)
                except ValueError:
                    continue
            hits = [o for o in offsets if abs(o) <= window_days]
            rows.append({"symbol": symbol, "call_date": call_date, "recalled": bool(hits),
                         "days_off": min(hits, key=abs) if hits else None, "matchable": True})
    finally:
        con.close()
    matchable = [r for r in rows if r["matchable"]]
    matched = sum(r["recalled"] for r in matchable)
    return {"pilot_symbols": len(symbols), "old_rows": len(rows),
            "matchable": len(matchable), "no_call_date": len(rows) - len(matchable),
            "recalled": matched,
            "recall_pct": round(100.0 * matched / len(matchable), 1) if matchable else None,
            "days_off": sorted(r["days_off"] for r in matchable if r["days_off"] is not None),
            "by_symbol": rows}


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", help="comma-separated NSE symbols, or a file with one per line")
    ap.add_argument("--from", dest="frm", default="2024-04-01")
    ap.add_argument("--to", dest="to", default=date.today().isoformat())
    ap.add_argument("--subject-filter", default=None,
                    help="comma-separated case-insensitive substrings on subject+desc")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--interval", type=float, default=MIN_INTERVAL,
                    help=f"seconds between requests (floor {MIN_INTERVAL})")
    ap.add_argument("--download", action="store_true",
                    help="also download attachments in --download-buckets")
    ap.add_argument("--download-buckets", default=",".join(DEFAULT_DOWNLOAD_BUCKETS),
                    help="buckets to download (default transcript,material; "
                         f"any of {','.join(BUCKETS)})")
    ap.add_argument("--pilot", action="store_true", help="use the 25+25 pilot company lists")
    ap.add_argument("--nse-only", type=int, metavar="N",
                    help="run the N companies without a BSE listing (the pilot's first list)")
    ap.add_argument("--transcript-gap", type=int, metavar="N",
                    help="run the N companies whose old transcripts have no BSE news id")
    ap.add_argument("--recall", metavar="OUT_DIR", default=None,
                    help="print the recall table for an existing fetch directory")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.recall:
        print(json.dumps(recall(Path(args.recall), frm=args.frm), indent=1, default=str))
        return 0

    if args.pilot:
        groups = pilot_lists()
        symbols = groups["nse_only"] + groups["transcript_gap"]
        logger.info("pilot: %d nse-only + %d transcript-gap = %d symbols",
                    len(groups["nse_only"]), len(groups["transcript_gap"]), len(symbols))
    elif args.nse_only or args.transcript_gap:
        groups = pilot_lists(nse_only=args.nse_only or 0,
                             transcript=args.transcript_gap or 0)
        symbols = list(dict.fromkeys(groups["nse_only"] + groups["transcript_gap"]))
        logger.info("%d nse-only + %d transcript-gap = %d symbols",
                    len(groups["nse_only"]), len(groups["transcript_gap"]), len(symbols))
    elif args.symbols:
        p = Path(args.symbols)
        if p.exists():
            symbols = [ln.strip().upper() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        else:
            symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        ap.error("give --symbols, --pilot, --nse-only or --transcript-gap")

    filters = [s for s in (args.subject_filter or "").split(",") if s]
    download_buckets = [b.strip().lower() for b in args.download_buckets.split(",") if b.strip()]
    unknown = [b for b in download_buckets if b not in BUCKETS]
    if unknown:
        ap.error(f"unknown --download-buckets: {', '.join(unknown)} (choose from {', '.join(BUCKETS)})")
    fetcher = AnnouncementFetcher(Path(args.out), interval=args.interval)
    t0 = time.time()
    stats = fetcher.run(symbols, args.frm, args.to, filters, args.download,
                        download_buckets=download_buckets)
    stats["seconds"] = round(time.time() - t0, 1)
    stats["blocks"] = fetcher.blocks
    stats["requests"] = fetcher.requests_made
    print(json.dumps(stats, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
