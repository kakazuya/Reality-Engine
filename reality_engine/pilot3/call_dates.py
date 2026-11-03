"""Transcript call dates (T-049 review, 4 Nov 2026): a transcript cannot be known before the call it transcribes.

A transcript's date comes from a filing record -- a BSE dissemination, the company site's ``_manifest.json``.  That
record dates the *filing* of a document, which can carry the wrong publish date: KEC's "Conference Call Q4 FY26"
transcript (``kec_transcripts/9203afbc...pdf``) was held on 18 May 2026 and filed on 21 May, but its company-site
record says 18 Feb 2026, so a question asked in Feb-May 2026 saw a call that had not happened.  The call date is
printed in the transcript itself, so it is read from the page text and the document's dates are raised to it:

    known_at = max(filing record, call date)     and     filing_date = max(filing date, call date)

Only the first pages are read, and a call date more than 400 days after the stored date is refused (a stray dated
comparison or a forward-looking year in a header), so the rule can only move a date to the call, never to an
arbitrary later one.  ``raise_doc_dates`` is the one place the rule is applied: ``registry.build_doc`` and
``build_pages`` (``doc`` and ``doc_page``), and the KPI extractor for a row it takes from a transcript.

    python -m reality_engine.pilot3.call_dates                       # the table for every held transcript
    python -m reality_engine.pilot3.call_dates --pages-db <pages.db>
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

PAGES_DB = Path(r"D:\RealityEngine\pilot3\pages.db")
SYMBOLS = ("KEC", "BAJFINANCE", "HINDALCO")
TRANSCRIPT_TYPES = ("transcript", "audio_link")
PAGES = 3           # the call date is printed on a title page; 3 pages covers a letterhead cover and the agenda
MAX_DAYS_LATE = 400  # a call date this far after the stored date is not this document's call

MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|December")
_MONTH = {m.lower(): i + 1 for i, m in enumerate(MONTHS.split("|"))}
RX_MDY = re.compile(rf"\b({MONTHS})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
RX_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({MONTHS})[,\s]+(\d{{4}})\b", re.I)
# "Q4 FY '26 Results Conference Call" / "earnings call held on" right before the date
CUE = re.compile(r"(?:held on|conference call|earnings call|investor call|results call|analyst call)\b[^.\n]{0,60}$",
                 re.I)


def _iso(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _dates(text: str) -> list[tuple[int, str]]:
    """``(position, ISO date)`` for every printed full date in ``text``, in text order."""
    found: list[tuple[int, str]] = []
    for m in RX_MDY.finditer(text):
        iso = _iso(int(m.group(3)), _MONTH[m.group(1).lower()], int(m.group(2)))
        if iso:
            found.append((m.start(), iso))
    for m in RX_DMY.finditer(text):
        iso = _iso(int(m.group(3)), _MONTH[m.group(2).lower()], int(m.group(1)))
        if iso:
            found.append((m.start(), iso))
    return sorted(found)


def call_date(texts: list[str], pages: int = PAGES) -> str | None:
    """The call date printed in the first pages: the date a call cue introduces, else the first date printed."""
    first: str | None = None
    for text in texts[:pages]:
        found = _dates(text)
        if not found:
            continue
        cued = [(pos, iso) for pos, iso in found if CUE.search(text[max(0, pos - 80):pos])]
        if cued:
            return cued[0][1]
        first = first or found[0][1]
    return first


def _days(iso: str) -> int:
    return date.fromisoformat(iso[:10]).toordinal()


def clamp(filing_date: str | None, known_at: str | None, texts: list[str],
          pages: int = PAGES) -> tuple[str | None, str | None, str | None]:
    """``(filing_date, known_at, call_date)`` with both dates raised to the call date of ``texts``.

    The call date is ``None`` when none prints on the first pages, or when the one that does is too far from the
    stored date to be this call; both dates then come back unchanged and the caller reports the document."""
    call = call_date(texts, pages)
    if not call:
        return filing_date, known_at, None
    ref = (known_at or filing_date or "")[:10]
    if ref and _days(call) > _days(ref) + MAX_DAYS_LATE:
        return filing_date, known_at, None
    known = max(known_at or "", call) or None      # keeps the filing timestamp when it is the later one
    filing = max(filing_date or "", call) or None
    return filing, known, call


def raise_doc_dates(con: sqlite3.Connection, rows) -> dict[str, tuple[str | None, str | None, str | None]]:
    """``{doc_key: (filing_date, known_at, call_date)}`` for every transcript in ``rows``.

    ``rows`` are ``(doc_key, doc_type, filing_date, known_at)``; ``con`` must hold ``doc_page(doc_key, page,
    text)``.  A document whose dates the call date cannot raise still comes back with its call date, so a caller
    can print every transcript and list the ones no call date was read for."""
    out: dict[str, tuple[str | None, str | None, str | None]] = {}
    for doc_key, doc_type, filing_date, known_at in rows:
        if doc_type not in TRANSCRIPT_TYPES:
            continue
        texts = [t or "" for (t,) in con.execute(
            "SELECT text FROM doc_page WHERE doc_key=? AND page<=? ORDER BY page", (doc_key, PAGES))]
        out[doc_key] = clamp(filing_date, known_at, texts)
    return out


def report(con: sqlite3.Connection, symbols=SYMBOLS) -> list[tuple]:
    """``(doc_key, symbol, filing_date, known_at, call_date, new_filing, new_known_at)`` for every transcript."""
    rows = [r for r in con.execute(
        "SELECT doc_key, symbol, doc_type, filing_date, known_at FROM doc WHERE doc_type IN "
        f"({','.join('?' * len(TRANSCRIPT_TYPES))}) ORDER BY symbol, COALESCE(known_at, filing_date)",
        TRANSCRIPT_TYPES) if not symbols or r[1] in symbols]
    dates = raise_doc_dates(con, [(r[0], r[2], r[3], r[4]) for r in rows])
    return [(r[0], r[1], r[3], r[4], dates[r[0]][2], dates[r[0]][0], dates[r[0]][1]) for r in rows]


def main(argv: list[str] | None = None) -> int:
    from reality_engine.pilot3 import profile

    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--pages-db", default=None, help="default: the profile's pages database, else the pilot3 one")
    ap.add_argument("--symbols", default=None, help="default: the profile's companies, else the pilot3 three")
    ap.add_argument("--profile", default=None, help="build profile JSON (T-056): companies and pages database")
    a = ap.parse_args(argv)
    if a.profile:
        profile.activate(profile.load(a.profile))
    path = Path(a.pages_db) if a.pages_db else profile.pages_db()
    if not path.is_file():
        print(f"STOPPED: no pages database at {path}", file=sys.stderr)
        return 2
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        symbols = tuple(s.strip().upper() for s in (a.symbols or ",".join(profile.symbols())).split(",") if s.strip())
        table = report(con, symbols)
    finally:
        con.close()
    print(f"{'doc_key':72s} {'stored filing':13s} {'stored known_at':20s} {'call date':10s} "
          f"{'new filing':13s} new known_at")
    for doc_key, symbol, filing, known, call, new_filing, new_known in table:
        print(f"{doc_key:72s} {filing or '-':13s} {known or '-':20s} {call or '-':10s} {new_filing or '-':13s} "
              f"{new_known or '-'}")
    unparsed = [t for t in table if not t[4]]
    print(f"\n{len(table)} transcripts, {len(unparsed)} with no call date read")
    for doc_key, _symbol, filing, known, _call, _nf, _nk in unparsed:
        print(f"  NO CALL DATE  {doc_key}  (stored {known or filing})")
    raised = [t for t in table if t[6] and t[6] != t[3]]
    print(f"{len(raised)} known_at raised to the call date")
    for doc_key, _symbol, _filing, known, call, _nf, new_known in raised:
        print(f"  RAISED  {known} -> {new_known}  (call {call})  {doc_key}")
    refiled = [t for t in table if t[5] and t[5] != t[2]]
    print(f"{len(refiled)} filing date raised to the call date")
    for doc_key, _symbol, filing, _known, call, new_filing, _nk in refiled:
        print(f"  REFILED  {filing} -> {new_filing}  (call {call})  {doc_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
