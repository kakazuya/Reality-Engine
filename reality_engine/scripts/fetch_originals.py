"""One downloader for every missing raw original (annual reports, decks, material
announcements, RBI) -- Drive first, then NSE, then BSE.

Input is a list CSV with ``url`` and ``key`` and, optionally, ``dest``; the
lists this job builds (``.tmp/missing_*.csv``, ``.tmp/nse_match.csv``) carry
``source_url``/``key``/``kind``/``symbol`` and are read as they are. Downloads
land under ``--dest-root`` (``D:\\RealityEngine\\raw`` by default) in
``<kind>/<symbol>/<key>.pdf``; **no database is touched**.

Pacing is per exchange and enforced in one stream: NSE >= 3 s (<= 20/min), BSE
>= 2.5 s (<= 24/min per stream). The totals the boxes allow are 20/min for NSE
and 76/min for BSE, shared with the other jobs; give each stream its own
``--interval`` so the sum stays under the cap.

Resume: a destination that already starts with ``%PDF`` is skipped, a damaged
one is fetched again. 403/429/503 back off exponentially and (BSE/Akamai) put
the whole stream in a penalty box; other 4xx are final errors.

Usage::

    python -m reality_engine.scripts.fetch_originals .tmp/missing_deck.csv \\
        --exchange bse --interval 4.0

    python -m reality_engine.scripts.fetch_originals .tmp/nse_match.csv \\
        --exchange nse --dest-root D:/RealityEngine/raw/nse_originals
"""

import argparse
import csv
import hashlib
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("reality_engine.fetch_originals")

DEFAULT_DEST_ROOT = Path(r"D:\RealityEngine\raw")
# Floors per stream. Probes 2026-10-28: NSE took 400/min and BSE +199/min bursts unblocked; back-off handles 403/429.
FLOOR = {"nse": 0.25, "bse": 0.25, "any": 0.25}
BLOCK_STATUSES = (403, 429, 503)
BACKOFF_BASE = 3.0
BACKOFF_CAP = 300.0
PDF_MAGIC = b"%PDF"
HOST = {"nse": re.compile(r"nseindia\.com", re.I), "bse": re.compile(r"bseindia\.com", re.I)}
MANIFEST_FIELDS = ["key", "kind", "symbol", "exchange", "url", "path", "status",
                   "http_status", "bytes", "sha256", "error", "fetched_at"]
URL_COLS = ("url", "source_url")
DEST_COLS = ("dest", "dest_path", "local_path")


def exchange_of(url):
    """'nse' / 'bse' for an attachment URL, else ''."""
    for name, pat in HOST.items():
        if pat.search(url or ""):
            return name
    return ""


def is_pdf(path):
    try:
        with Path(path).open("rb") as f:
            return f.read(4) == PDF_MAGIC
    except OSError:
        return False


def safe_name(text, limit=96):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(text))[:limit] or "file"


def load_rows(list_path, dest_root):
    """List CSV -> rows with url/key/kind/symbol/dest; dest is absolute."""
    rows = []
    with Path(list_path).open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        url_col = next((c for c in URL_COLS if c in fields), None)
        if not url_col:
            raise ValueError(f"{list_path} has no url/{'/'.join(URL_COLS)} column: {fields}")
        dest_col = next((c for c in DEST_COLS if c in fields), None)
        for i, raw in enumerate(reader):
            url = (raw.get(url_col) or "").strip()
            if not url:
                continue
            key = (raw.get("key") or "").strip() or hashlib.sha1(url.encode()).hexdigest()[:16]
            kind = (raw.get("kind") or "misc").strip() or "misc"
            symbol = (raw.get("symbol") or "").strip()
            dest = (raw.get(dest_col) or "").strip() if dest_col else ""
            path = Path(dest) if dest else (
                Path(dest_root) / kind / safe_name(symbol or "_all") / f"{safe_name(key)}.pdf")
            rows.append({"row": i, "url": url, "key": key, "kind": kind,
                         "symbol": symbol, "dest": path, "exchange": exchange_of(url)})
    return rows


class OriginalFetcher:
    """Sequential, paced, resumable downloader for one exchange stream."""

    def __init__(self, rows, manifest, exchange="any", interval=None, penalty=600.0,
                 backoff=BACKOFF_BASE, tries=4, timeout=120.0, fetch=None,
                 sleep=time.sleep, clock=time.monotonic):
        self.rows = rows
        self.manifest = Path(manifest)
        self.exchange = exchange
        self.interval = max(float(interval or 0.0), FLOOR.get(exchange, 3.0))
        self.penalty = float(penalty)
        self.backoff = float(backoff)
        self.tries = int(tries)
        self.timeout = float(timeout)
        self._fetch = fetch
        self.sleep = sleep
        self.clock = clock
        self._last_at = None
        self._blocked_until = 0.0
        self.requests = 0
        self.stats = {"ok": 0, "skipped": 0, "skipped_exchange": 0, "error": 0,
                      "bytes": 0, "blocked": 0}

    # -- http ---------------------------------------------------------
    def fetch(self, url):
        if self._fetch is None:
            from curl_cffi import requests as cr
            self._fetch = cr.Session(impersonate="chrome120")
        return self._fetch.get(url, timeout=self.timeout)

    def _wait(self):
        """Interval since the previous request, plus any active penalty box."""
        now = self.clock()
        ready = max((self._last_at or 0.0) + self.interval, self._blocked_until)
        if now < ready:
            self.sleep(ready - now)
        self._last_at = self.clock()

    def get(self, url):
        """One file with back-off. Returns (bytes|None, http_status|None, error)."""
        last = None
        for attempt in range(self.tries):
            self._wait()
            self.requests += 1
            try:
                resp = self.fetch(url)
            except Exception as e:                      # noqa: BLE001 - transient network
                last, status, body = f"{type(e).__name__}: {e}", None, None
            else:
                status = getattr(resp, "status_code", None)
                body = getattr(resp, "content", b"") or b""
                if status == 200:
                    return body, status, None
                last = f"HTTP {status}"
                if status not in BLOCK_STATUSES:
                    return None, status, last
            self.stats["blocked"] += 1
            wait = min(self.backoff * (2 ** attempt), BACKOFF_CAP)
            if status == 403:                            # Akamai: give the whole stream a rest
                self._blocked_until = max(self._blocked_until,
                                          self.clock() + max(wait, self.penalty))
                wait = 0.0                               # _wait() sleeps the box down
            logger.warning("%s on %s (attempt %d/%d) - backing off %.0fs",
                           last, url.split("?")[0], attempt + 1, self.tries,
                           wait or max(self.backoff * (2 ** attempt), self.penalty))
            if wait:
                self.sleep(wait)
        return None, status, last

    # -- one file -----------------------------------------------------
    def one(self, row):
        path = Path(row["dest"])
        if path.exists():
            if is_pdf(path):
                self.stats["skipped"] += 1
                return self.record(row, "skipped", None, path.stat().st_size, None, None)
            logger.warning("%s exists but is not a PDF; fetching again", path)
        body, status, error = self.get(row["url"])
        if body is None:
            self.stats["error"] += 1
            return self.record(row, "error", status, None, None, error)
        if not body.startswith(PDF_MAGIC):
            self.stats["error"] += 1
            return self.record(row, "error", status, len(body), None,
                               f"not a PDF ({body[:16]!r})")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        self.stats["ok"] += 1
        self.stats["bytes"] += len(body)
        return self.record(row, "ok", status, len(body), hashlib.sha256(body).hexdigest(), None)

    def record(self, row, status, http_status, size, sha, error):
        return {"key": row["key"], "kind": row["kind"], "symbol": row["symbol"],
                "exchange": row["exchange"], "url": row["url"], "path": str(row["dest"]),
                "status": status, "http_status": http_status, "bytes": size,
                "sha256": sha, "error": error,
                "fetched_at": datetime.now().isoformat(timespec="seconds")}

    # -- the stream ---------------------------------------------------
    def run(self):
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        new = not self.manifest.exists() or self.manifest.stat().st_size == 0
        with self.manifest.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            if new:
                w.writeheader()
            for row in self.rows:
                if self.exchange != "any" and row["exchange"] != self.exchange:
                    self.stats["skipped_exchange"] += 1
                    continue
                w.writerow(self.one(row))
                f.flush()
                done = self.stats["ok"] + self.stats["error"]
                if done and done % 100 == 0:
                    logger.info("%d files: ok %d, skipped %d, error %d, %.2f GB",
                                done + self.stats["skipped"], self.stats["ok"],
                                self.stats["skipped"], self.stats["error"],
                                self.stats["bytes"] / 1e9)
        return self.stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("list_csv", help="list CSV with url/key (and optional dest)")
    ap.add_argument("--exchange", choices=["nse", "bse", "any"], default="any")
    ap.add_argument("--interval", type=float, default=None,
                    help="seconds between requests; floored at 0.25 s")
    ap.add_argument("--dest-root", default=str(DEFAULT_DEST_ROOT),
                    help=f"download root (default {DEFAULT_DEST_ROOT})")
    ap.add_argument("--manifest", default=None, help="manifest CSV (default <list>.manifest.csv)")
    ap.add_argument("--penalty", type=float, default=600.0, help="403 penalty box in seconds")
    ap.add_argument("--tries", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--limit", type=int, default=0, help="stop after N rows (0 = all)")
    ap.add_argument("--force-root", action="store_true",
                    help="allow a destination root outside D: (tests/dry runs)")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(message)s")

    root = Path(args.dest_root)
    if not args.force_root and str(root)[:2].upper() != "D:":
        ap.error(f"downloads go to D: only; {root} is elsewhere (use --force-root for a test)")

    rows = load_rows(args.list_csv, root)
    if args.limit:
        rows = rows[:args.limit]
    manifest = args.manifest or str(Path(args.list_csv).with_suffix("")) + ".manifest.csv"
    fetcher = OriginalFetcher(rows, manifest, exchange=args.exchange, interval=args.interval,
                              penalty=args.penalty, tries=args.tries, timeout=args.timeout)
    logger.info("%d rows from %s, exchange=%s, interval=%.1fs",
                len(rows), args.list_csv, args.exchange, fetcher.interval)
    t0 = time.monotonic()
    stats = fetcher.run()
    stats["requests"] = fetcher.requests
    stats["seconds"] = round(time.monotonic() - t0, 1)
    print(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
