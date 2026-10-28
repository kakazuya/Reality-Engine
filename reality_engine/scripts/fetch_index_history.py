"""Dated Nifty index constituent-change notices (Shivam decision 6, 2026-10-27). Raw fetch only.

Sources (niftyindices.com):
  notices  ``https://www.niftyindices.com/media`` lists every press release 1998 -> today (one
           1,520-entry HTML page). The constituent-change notices are the "Changes in indices",
           "Replacements in indices", "Inclusion/Exclusion ... w.e.f." and semi-annual review
           releases; each PDF names the index, the excluded/included companies and the effective
           date. Equity notices from 2019-01-01: about 444 (fixed-income/SDL/G-Sec excluded).
  anchors  ``https://www.niftyindices.com/IndexConstituent/ind_<index>list.csv``: today's
           constituents for Nifty 50 / 100 / 200 / 500 / Midcap 150 / Smallcap 250, columns
           ``Company Name, Industry, Symbol, Series, ISIN Code``. The rebuild reverses the dated
           changes from the 2026-09-30 snapshot (``equity_intelligence.index_membership``) to get
           valid_from/valid_to intervals per index; the fetch itself does not build intervals.

Earliest notice: press releases reach 1998 (change notices from 2004). 444 notices + 7 requests at
a 2-3 s interval is about 20-25 min, under the 3-hour rule.

    python -m reality_engine.scripts.fetch_index_history --from 2019-01-01 --out .tmp/index_history
    python -m reality_engine.scripts.fetch_index_history --sample 30  # timed test
"""
import argparse
import datetime as dt
import html as htmllib
import json
import re
import sys
import time
from pathlib import Path

import requests

from reality_engine.config import RAW_ROOT

BASE = "https://www.niftyindices.com"
MEDIA = BASE + "/media"
CURRENT = {
    "nifty50": "NIFTY 50",
    "nifty100": "NIFTY 100",
    "nifty200": "NIFTY 200",
    "nifty500": "NIFTY 500",
    "niftymidcap150": "NIFTY MIDCAP 150",
    "niftysmallcap250": "NIFTY SMALLCAP 250",
}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
RETRY_STATUS = (403, 429, 503)
MAX_ATTEMPTS = 4

CHANGE = re.compile(r"change|replace|inclusion|exclusion|reconstitut|review|defer", re.I)
FIXED = re.compile(r"fixed income|sdl|g-?sec|t-?bill|money market|bond|benchmark|prc|aif|sovereign", re.I)
HEADERS = {"Sr. No.", "Company Name", "Symbol"}
SYMBOL = re.compile(r"[A-Z0-9&\-]{1,20}")
MONTH_DATE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")


def even_sample(items, n):
    items = list(items)
    if n is None or n >= len(items):
        return items
    if n <= 0:
        return []
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def parse_media_page(text):
    """The /media page -> [{published, title, url}] (one per press-release PDF)."""
    out = []
    for body in re.findall(r'<li data-publishdate="[^"]*">(.*?)</li>', text, re.S):
        d = re.search(r"<span>\s*([A-Za-z]+ \d{2}, \d{4})\s*</span>", body)
        a = re.search(r'href="(/Press_Release/[^"]+\.pdf)"[^>]*>\s*(.*?)\s*</a>', body, re.S)
        if not (d and a):
            continue
        try:
            published = dt.datetime.strptime(d.group(1), "%B %d, %Y").date().isoformat()
        except ValueError:
            continue
        out.append({"published": published, "title": re.sub(r"\s+", " ",
                                                           htmllib.unescape(a.group(2))).strip(),
                    "url": a.group(1)})
    return out


def select_notices(entries, start, end, include_fixed=False):
    """Constituent-change notices in [start, end]; fixed-income releases are dropped."""
    start, end = start.isoformat(), end.isoformat()
    return [e for e in entries
            if start <= e["published"] <= end and CHANGE.search(e["title"])
            and (include_fixed or not FIXED.search(e["title"]))]


def clean_index(name):
    name = re.sub(r"^\s*(?:\d{1,3}[\).]|[A-Za-z][\).])\s*", "", name)
    name = re.sub(r"\s+", " ", name).strip(" .:-")
    name = re.sub(r"\s+index$", "", name, flags=re.I)
    name = re.sub(r"^(NIFTY)(\d)", r"\1 \2", name, flags=re.I)
    return name.upper()


def is_heading(line, title=None):
    """A short line naming an index (not a sentence about one)."""
    if len(line) > 90 or not re.search(r"nifty", line, re.I):
        return False
    low = line.lower().lstrip("0123456789.()abcdefghij) ").strip()
    return not low.startswith(("the ", "this ", "these ", "note", "nse ", "in ", "no "))


def heading_index(line):
    m = re.search(r"nifty[0-9a-z &\-\.]*", line, re.I)
    return clean_index(m.group(0)) if m else None


def _terminator(line):
    low = line.lower()
    return (line.startswith("*") or bool(re.fullmatch(r"\d{1,3}[\).]", line))
            or low.startswith(("note", "the above", "the following", "source",
                               "no ", "this ", "these ", "in case")))


def parse_notice(text, announced_date, source_url=None, title=None):
    """One press-release text -> tidy rows.

    Rows: {index_name, company_name, symbol, change_type, effective_date, announced_date, source_url}.
    ``announced_date`` is the media-page publication date (ISO), the effective date comes from the
    notice body ("effective from September 30, 2026"), falling back to the title's "w.e.f.".
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    head = " ".join(lines[:12])
    eff = re.search(r"effective from\s+" + MONTH_DATE.pattern, head + " " + " ".join(lines[12:40]))
    if not eff:
        eff = re.search(r"w\.e\.f\.\s*" + MONTH_DATE.pattern, title or " ".join(lines[:12]))
    effective = None
    if eff:
        try:
            effective = dt.datetime.strptime(eff.group(1), "%B %d, %Y").date().isoformat()
        except ValueError:
            effective = None
    rows, index, mode, i = [], None, None, 0
    while i < len(lines):
        line = lines[i]
        if is_heading(line):
            index, mode = heading_index(line), None
            i += 1
            continue
        if index and re.match(r"the following .*(exclu|inclu)", line, re.I):
            mode = "exclusion" if re.search(r"exclu", line, re.I) else "inclusion"
            i += 1
            while i < len(lines) and lines[i] in HEADERS:
                i += 1
            continue
        if mode and index and re.fullmatch(r"\d{1,3}", line):
            cells, j = [], i + 1
            while (j < len(lines) and not re.fullmatch(r"\d{1,3}", lines[j])
                   and not _terminator(lines[j]) and not is_heading(lines[j])):
                cells.append(lines[j])
                j += 1
            # a sentence after the table is picked up as extra cells: end the row at the first
            # symbol-like line (the symbol column is the only all-caps token in a row)
            k = next((n for n, c in enumerate(cells) if n and SYMBOL.fullmatch(c)), None)
            if k is not None:
                name = " ".join(cells[:k]).rstrip("*").strip()
                if name:
                    rows.append({"index_name": index, "company_name": name, "symbol": cells[k],
                                 "change_type": mode, "effective_date": effective,
                                 "announced_date": announced_date, "source_url": source_url})
            i = j
            continue
        if _terminator(line) or is_heading(line):
            mode = None
        i += 1
    return rows


def pdf_text(path):
    import pymupdf
    with pymupdf.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "text/html,application/pdf,*/*",
                      "Accept-Language": "en-US,en;q=0.9", "Referer": BASE + "/"})
    return s


class Fetcher:
    def __init__(self, out, interval):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.interval = interval
        self.s = session()
        self.latencies = []
        self.counts = {"ok": 0, "absent": 0, "skipped": 0}
        self.missing = self.out / "_missing.txt"
        self.manifest = self.out / "_manifest.jsonl"

    def record(self, url, status, size, seconds):
        with self.manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"url": url, "status": status, "bytes": size,
                                "seconds": round(seconds, 3),
                                "at": dt.datetime.now().isoformat(timespec="seconds")}) + "\n")

    def get(self, url, required=False):
        for attempt in range(MAX_ATTEMPTS):
            t0 = time.monotonic()
            try:
                r = self.s.get(url, timeout=90)
            except requests.RequestException:
                r = None
            self.latencies.append(time.monotonic() - t0)
            if r is not None and r.status_code == 200:
                return r
            if r is not None and r.status_code == 404 and not required:
                return None
            if r is None or r.status_code in RETRY_STATUS or r.status_code == 404:
                if attempt + 1 < MAX_ATTEMPTS:
                    time.sleep(min(90, 10 * 2 ** attempt))
                    self.s = session()
                    continue
            code = "network" if r is None else r.status_code
            raise SystemExit(f"BLOCKED by niftyindices on {url}: {code}. Stopped after "
                             f"{MAX_ATTEMPTS} attempts; re-run later (files present are kept).")
        raise SystemExit(f"BLOCKED by niftyindices on {url}")

    def fetch_file(self, url, path, magic=None):
        if path.exists() and path.stat().st_size > 0:
            self.counts["skipped"] += 1
            return "skipped"
        r = self.get(BASE + url if url.startswith("/") else url)
        if r is None:
            with self.missing.open("a", encoding="utf-8") as f:
                f.write(url + "\n")
            self.counts["absent"] += 1
            self.record(url, "absent", 0, self.latencies[-1])
            return "absent"
        body = r.content
        if magic and not body.lstrip()[:len(magic)] == magic:
            # A soft-404 HTML page for a missing notice: log it and go on, but stop
            # if several come in a row (that looks like a block page, not a gap).
            self.bad_streak = getattr(self, "bad_streak", 0) + 1
            if self.bad_streak >= 5:
                raise SystemExit(f"unexpected content x5 in a row, last {url}: {body[:80]!r}")
            print(f"unexpected content for {url} (logged as missing): {body[:60]!r}", flush=True)
            with self.missing.open("a", encoding="utf-8") as f:
                f.write(url + "\n")
            self.counts["absent"] += 1
            self.record(url, "not_pdf", len(body), self.latencies[-1])
            return "absent"
        self.bad_streak = 0
        path.write_bytes(body)
        self.counts["ok"] += 1
        self.record(url, "ok", len(body), self.latencies[-1])
        return "ok"


def project(full, interval, latencies):
    mean = sum(latencies) / len(latencies) if latencies else 0.0
    return mean, full * (interval + mean)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", default="2019-01-01")
    ap.add_argument("--to", dest="end", default=dt.date.today().isoformat())
    ap.add_argument("--out", default=str(RAW_ROOT / "index_history"))
    ap.add_argument("--interval", type=float, default=3.0, help="seconds between requests (>=2)")
    ap.add_argument("--sample", type=int, default=None, help="fetch only N notices spread over the range")
    ap.add_argument("--include-fixed", action="store_true", help="also fetch fixed-income index notices")
    ap.add_argument("--no-current", action="store_true", help="skip the current constituent CSVs")
    a = ap.parse_args()
    if a.interval < 2:
        ap.error("--interval must be >= 2 s")
    start, end = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    f = Fetcher(a.out, a.interval)
    t0 = time.monotonic()

    r = f.get(MEDIA, required=True)
    (f.out / "_media_page.html").write_bytes(r.content)
    entries = parse_media_page(r.content.decode("utf-8", "replace"))
    notices = select_notices(entries, start, end, a.include_fixed)
    (f.out / "_notices.json").write_text(json.dumps(notices, indent=1), encoding="utf-8")
    print(f"media page: {len(entries)} press releases; {len(notices)} change notices "
          f"{start}..{end}", flush=True)
    by_year = {}
    for e in notices:
        by_year[e["published"][:4]] = by_year.get(e["published"][:4], 0) + 1
    print("by year:", by_year, flush=True)

    todo = even_sample(notices, a.sample)
    parsed, examples, indexes = [], [], set()
    for n, e in enumerate(todo, 1):
        path = f.out / e["url"].rsplit("/", 1)[-1]
        status = f.fetch_file(e["url"], path, magic=b"%PDF")
        if status == "ok" and a.sample:
            for row in parse_notice(pdf_text(path), e["published"], BASE + e["url"], e["title"]):
                parsed.append(row)
                indexes.add(row["index_name"])
                if len(examples) < 3:
                    examples.append(row)
        if n % 10 == 0 or n == len(todo):
            print(f"{n}/{len(todo)} {e['published']} {f.counts}", flush=True)
        if n < len(todo) and status != "skipped":
            time.sleep(a.interval)

    if not a.no_current:
        for slug in CURRENT:
            status = f.fetch_file(f"/IndexConstituent/ind_{slug}list.csv",
                                  f.out / f"current_{slug}.csv")
            if status != "skipped":
                time.sleep(a.interval)

    elapsed = time.monotonic() - t0
    full = len(notices) + (0 if a.no_current else len(CURRENT)) + 1
    if len(f.latencies) <= 1 and f.counts["skipped"]:
        print(f"\nno new files: media page only ({len(f.latencies)} request); "
              f"{f.counts['skipped']} files already present; {elapsed:.1f}s")
        return
    mean, seconds = project(full, a.interval, f.latencies)
    print(f"\nrequests {len(f.latencies)} ({f.counts}); wall {elapsed:.1f}s; "
          f"mean latency {mean:.3f}s/request at {a.interval:.1f}s interval")
    print(f"projected full run: {full} requests x ({a.interval:.1f}+{mean:.3f}) s = "
          f"{seconds / 3600:.2f} h -> {'<= 3 h: fetch from 2019' if seconds <= 3 * 3600 else '> 3 h: FY25 only'}")
    if parsed:
        (f.out / "_sample_rows.jsonl").write_text(
            "\n".join(json.dumps(r) for r in parsed) + "\n", encoding="utf-8")
        print(f"parsed {len(parsed)} tidy rows across {len(indexes)} indices; examples:")
        for row in examples:
            print("  ", row)
    print("earliest change notice in the index: see _notices.json "
          "(press releases reach 1998; change notices from 2004)", flush=True)
    if f.counts["absent"] and f.counts["ok"] == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
