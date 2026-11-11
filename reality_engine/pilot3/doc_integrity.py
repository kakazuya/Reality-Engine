"""Document-integrity report and gate (T-181): count and name a defective document before any extractor reads it.

A misdated or truncated document produces a confident wrong answer: a 2018 call stored as filed in 2026 was the
only source of a stale "24% of revenue" (held audit, 10 Nov 2026).  This module reads one pilot3 store (never
writes it) and reports nine defect classes per document, then gates a build on the counts:

    link_notice             a transcript/deck of 1-2 pages whose text is a cover letter, not the content
    duplicate_sha256        every copy after the first of the same sha256
    near_duplicate          same symbol, type, page count and first-page text under a different sha256
    misdated                a transcript whose latest printed year on pages 1-3 is more than a year before
                            ``filing_date``, or whose printed call date is more than 120 days before it
    mistyped                ``doc_identity.classify_type`` disagrees with ``doc.doc_type`` (a call transcript
                            or results text typed ``announcement``)
    truncated               an annual report below 40 pages, or ``doc.pages`` above the pages held in ``doc_page``
    no_text                 more than half of the held pages have no text layer
    known_at_after_period   ``known_at`` more than 30 days after ``filing_date``, or missing
    missing_period_call     a results filing with no transcript within 45 days after it (count only)

The rules are the existing ones, imported and not rewritten: ``doc_identity.check_type`` decides a cover letter,
``doc_identity.classify_type``/``moderator_line`` decide the content type (T-159), ``call_dates.call_date`` reads
the printed call date (T-049/T-161), ``linked_transcripts.missing_calls`` clusters results filings and finds the
call (T-157), and ``linked_transcripts.STUB_MAX_PAGES``/``TRANSCRIPT_MIN_PAGES`` set the page bounds.

    python -m reality_engine.pilot3.doc_integrity report --store <pilot3.db> --out <dir>
    python -m reality_engine.pilot3.doc_integrity gate --prev <summary.csv> --new <summary.csv>
    python -m reality_engine.pilot3.doc_integrity gate --store <pilot3.db> --max link_notice=0,misdated=0

``report`` writes ``doc_defects.csv`` (one row per document and defect) and ``summary.csv`` (defect, documents,
companies) under ``--out``.  ``gate`` exits 1 when a defect count rose against ``--prev``, or when a class
exceeds the limit named by ``--max``; it exits 0 otherwise.  Statements are bounded and per document: no
``GROUP BY`` over ``doc_page.text``.
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from reality_engine.db.readonly import connect_ro
from reality_engine.pilot3 import call_dates, doc_identity, linked_transcripts

DEFECTS = ("link_notice", "duplicate_sha256", "near_duplicate", "misdated", "mistyped", "truncated",
           "no_text", "known_at_after_period", "missing_period_call")
COLUMNS = ("doc_key", "symbol", "doc_type", "filing_date", "pages", "defect", "detail")
SUMMARY_COLUMNS = ("defect", "documents", "companies")
# doc.doc_type -> the family the first-page text must show (doc_identity's map is keyed by the record label).
EXPECTED_KIND = {"transcript": "transcript", "deck": "presentation", "results": "results",
                 "annual_report": "annual_report"}
RECORD_TYPE = {"transcript": "CONCALL_TRANSCRIPT", "deck": "INVESTOR_PRESENTATION",
               "results": "FINANCIAL_RESULT", "annual_report": "ANNUAL_REPORT"}
STALE_DAYS = 30            # known_at later than this after filing_date: reloaded, not the filing date
CALL_WINDOW_DAYS = 45      # a call transcript this long after the results still covers the quarter
MISDATE_DAYS = 120         # docs_collect.reconcile_doc's own re-date bound (T-161, section 9m)
MIN_TEXT_CHARS = 50        # a first page this thin is not evidence for a near duplicate
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


@dataclass
class Doc:
    doc_key: str
    symbol: str
    doc_type: str
    filing_date: str | None
    known_at: str | None
    pages: int | None
    sha256: str | None


def _day(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def load_docs(con: sqlite3.Connection) -> dict[str, Doc]:
    """Every ``doc`` row, in table order (the first copy of a sha256 is the earliest known one)."""
    docs: dict[str, Doc] = {}
    for doc_key, symbol, doc_type, filing_date, known_at, pages, sha256 in con.execute(
            "SELECT doc_key, symbol, doc_type, filing_date, known_at, pages, sha256 FROM doc"):
        docs[doc_key] = Doc(doc_key, symbol or "", doc_type or "", filing_date, known_at, pages, sha256)
    return docs


def page_stats(con: sqlite3.Connection) -> dict[str, tuple[int, int]]:
    """``{doc_key: (pages held, pages with no text layer)}`` in one pass, per row, no text aggregation."""
    held: dict[str, int] = defaultdict(int)
    empty: dict[str, int] = defaultdict(int)
    for doc_key, chars in con.execute("SELECT doc_key, chars FROM doc_page ORDER BY doc_key"):
        held[doc_key] += 1
        if not (chars or 0):
            empty[doc_key] += 1
    return {key: (n, empty.get(key, 0)) for key, n in held.items()}


def early_pages(con: sqlite3.Connection, max_page: int = 3) -> dict[str, dict[int, str]]:
    """``{doc_key: {page: text}}`` for pages 1..``max_page``; one bounded statement, no text GROUP BY."""
    pages: dict[str, dict[int, str]] = defaultdict(dict)
    for doc_key, page, text in con.execute(
            "SELECT doc_key, page, text FROM doc_page WHERE page<=? ORDER BY doc_key, page", (max_page,)):
        pages[doc_key][int(page)] = text or ""
    return pages


def _joined(pages: dict[int, str], upto: int) -> str:
    return "\n".join(pages.get(page, "") for page in range(1, upto + 1))


def _add(rows: list[dict], doc: Doc, defect: str, detail: str) -> None:
    rows.append({"doc_key": doc.doc_key, "symbol": doc.symbol, "doc_type": doc.doc_type,
                 "filing_date": doc.filing_date or "", "pages": doc.pages if doc.pages is not None else "",
                 "defect": defect, "detail": detail})


def _first_sort(doc: Doc) -> tuple[str, str]:
    return (doc.known_at or doc.filing_date or "", doc.doc_key)


def scan(con: sqlite3.Connection) -> list[dict]:
    """One row per (document, defect) over every ``doc`` row of ``con``; read-only."""
    docs = load_docs(con)
    stats = page_stats(con)
    early = early_pages(con)
    rows: list[dict] = []

    # link_notice: the existing cover-letter rule (doc_identity.check_type) on a 1-2 page transcript/deck.
    for doc in docs.values():
        if doc.doc_type in ("transcript", "deck") and doc.pages and doc.pages <= linked_transcripts.STUB_MAX_PAGES:
            verdict, reason = doc_identity.check_type(
                _joined(early.get(doc.doc_key, {}), doc.pages),
                doc_identity.Expected(doc.symbol, RECORD_TYPE[doc.doc_type]), doc.pages)
            if verdict == "mismatch" and reason.startswith("cover_letter"):
                _add(rows, doc, "link_notice", reason)

    # duplicate_sha256: every copy after the earliest known one.
    by_sha: dict[str, list[Doc]] = defaultdict(list)
    for doc in docs.values():
        if doc.sha256:
            by_sha[doc.sha256].append(doc)
    for group in by_sha.values():
        if len(group) < 2:
            continue
        group.sort(key=_first_sort)
        for doc in group[1:]:
            _add(rows, doc, "duplicate_sha256", f"same sha256 as {group[0].doc_key} ({len(group)} copies)")

    # near_duplicate: same symbol, type, page count and first page under a different sha256.
    by_text: dict[tuple[str, str, int | None, str], list[Doc]] = defaultdict(list)
    for doc in docs.values():
        text = (early.get(doc.doc_key, {}).get(1) or "").strip()
        if len(text) >= MIN_TEXT_CHARS:
            by_text[(doc.symbol, doc.doc_type, doc.pages, text[:2000])].append(doc)
    for group in by_text.values():
        if len(group) < 2 or len({doc.sha256 for doc in group}) < 2:
            continue
        group.sort(key=_first_sort)
        for doc in group[1:]:
            if doc.sha256 != group[0].sha256:
                _add(rows, doc, "near_duplicate",
                     f"same first page and {doc.pages} pages as {group[0].doc_key}, different sha256")

    # misdated: a transcript, pages >= 3, the 9m printed-date rule.
    for doc in docs.values():
        if doc.doc_type != "transcript" or not doc.filing_date or (doc.pages or 0) < 3:
            continue
        texts = early.get(doc.doc_key, {})
        years = [int(year) for page in texts.values() for year in _YEAR.findall(page)]
        if not years:
            continue
        latest = max(years)
        filed = _day(doc.filing_date)
        if not filed:
            continue
        call = call_dates.call_date([texts.get(page, "") for page in (1, 2, 3)])
        call_day = _day(call)
        stale_year = latest <= filed.year - 2
        stale_call = bool(call_day and (call_day - filed).days < -MISDATE_DAYS)
        if not (stale_year or stale_call):
            continue
        if call and call[:10] == doc.filing_date[:10]:
            detail = (f"latest printed year {latest} vs filed {doc.filing_date}; printed call {call} is the "
                      f"filing date (already repaired)")
        else:
            detail = f"latest printed year {latest} vs filed {doc.filing_date}"
            if call:
                detail += f"; printed call {call}"
        _add(rows, doc, "misdated", detail)

    # mistyped: a call transcript under another label, or a transcript label on another family.  The moderator
    # line is the strong marker T-159 requires; classify_type alone retypes call intimations and deck agendas
    # (section 9m), and a results announcement is a legitimate announcement, not a defect.
    for doc in docs.values():
        if (doc.pages or 0) < 3:
            continue
        pages = early.get(doc.doc_key, {})
        got = doc_identity.classify_type(pages.get(1, ""), doc.pages)
        moderator = any(doc_identity.moderator_line(pages.get(page, "")) for page in (1, 2, 3))
        if doc.doc_type != "transcript" and got == "transcript" and moderator:
            _add(rows, doc, "mistyped", f"label {doc.doc_type} but the text is a call transcript (moderator line)")
        elif doc.doc_type == "transcript" and got in EXPECTED_KIND.values() and got != "transcript":
            _add(rows, doc, "mistyped", f"label transcript but the text is a {got}")

    # truncated: an annual report below 40 pages, or fewer pages held than the record claims.
    for doc in docs.values():
        held = stats.get(doc.doc_key, (0, 0))[0]
        reasons = []
        if doc.doc_type == "annual_report" and (doc.pages or 0) < doc_identity.AR_SECTION_PAGES:
            reasons.append(f"annual report of {doc.pages or 0} pages")
        if doc.pages and held < doc.pages:
            reasons.append(f"pages says {doc.pages}, {held} held in doc_page")
        if reasons:
            _add(rows, doc, "truncated", "; ".join(reasons))

    # no_text: more than half the held pages carry no text layer.
    for doc in docs.values():
        held, empty = stats.get(doc.doc_key, (0, 0))
        if held and empty / held > 0.5:
            _add(rows, doc, "no_text", f"{empty} of {held} pages with no text layer")

    # known_at_after_period: reloaded later than the filing, or no known_at at all.
    for doc in docs.values():
        if not doc.known_at:
            _add(rows, doc, "known_at_after_period", "known_at missing")
            continue
        filed, known = _day(doc.filing_date), _day(doc.known_at)
        if filed and known and (known - filed).days > STALE_DAYS:
            _add(rows, doc, "known_at_after_period",
                 f"known_at {doc.known_at[:10]} is {(known - filed).days} days after filing {filed.isoformat()}")

    # missing_period_call: reuse the T-157 clustering, widened to the 45-day window.
    transcripts: dict[str, list[str]] = defaultdict(list)
    for doc in docs.values():
        if doc.doc_type == "transcript" and (doc.pages or 0) >= linked_transcripts.TRANSCRIPT_MIN_PAGES \
                and doc.filing_date:
            transcripts[doc.symbol].append(doc.filing_date[:10])
    for missing in linked_transcripts.missing_calls(con):
        last = _day(missing["last_filing"])
        if not last:
            continue
        end = (last + timedelta(days=CALL_WINDOW_DAYS)).isoformat()
        if any(missing["until"] < day <= end for day in transcripts.get(missing["symbol"], [])):
            continue
        doc = docs.get(missing["doc_key"]) or Doc(missing["doc_key"], missing["symbol"], "results",
                                                  missing["filing_date"], None, None, None)
        _add(rows, doc, "missing_period_call",
             f"results {missing['filing_date']} (last filing {missing['last_filing']}) has no transcript by {end}")

    return rows


def summarize(rows: list[dict]) -> list[dict]:
    """One summary row per defect class, in ``DEFECTS`` order; companies are distinct symbols."""
    companies: dict[str, set[str]] = defaultdict(set)
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["defect"]] += 1
        companies[row["defect"]].add(row["symbol"])
    return [{"defect": defect, "documents": counts.get(defect, 0), "companies": len(companies.get(defect, ()))}
            for defect in DEFECTS]


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run_report(store: Path, out: Path) -> int:
    """Write ``doc_defects.csv`` and ``summary.csv`` under ``out`` and print the summary; the store is read-only."""
    con = connect_ro(store, timeout_s=60)
    try:
        rows = scan(con)
    finally:
        con.close()
    summary = summarize(rows)
    out.mkdir(parents=True, exist_ok=True)
    _write_csv(out / "doc_defects.csv", COLUMNS, rows)
    _write_csv(out / "summary.csv", SUMMARY_COLUMNS, summary)
    print(f"{'defect':24s} {'documents':>9s} {'companies':>9s}")
    for row in summary:
        print(f"{row['defect']:24s} {row['documents']:>9d} {row['companies']:>9d}")
    print(f"{len(rows)} defect rows -> {out / 'doc_defects.csv'}")
    return 0


def read_summary(path: Path) -> dict[str, int]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["defect"]: int(row["documents"] or 0) for row in csv.DictReader(handle)}


def compare(previous: dict[str, int], current: dict[str, int]) -> list[str]:
    """Defect classes whose count rose, as ``class: before -> after`` lines."""
    return [f"{defect}: {previous.get(defect, 0)} -> {current.get(defect, 0)}"
            for defect in sorted(set(previous) | set(current))
            if current.get(defect, 0) > previous.get(defect, 0)]


def parse_limits(text: str) -> dict[str, int]:
    """``link_notice=0,misdated=0`` -> ``{class: limit}``; an unknown class is an error, never silently ignored."""
    limits: dict[str, int] = {}
    for item in text.split(","):
        name, _, value = item.partition("=")
        name = name.strip()
        if name not in DEFECTS:
            raise ValueError(f"unknown defect class {name!r}; known: {', '.join(DEFECTS)}")
        limits[name] = int(value)
    return limits


def gate_prev(previous_path: Path, current_path: Path) -> int:
    risen = compare(read_summary(previous_path), read_summary(current_path))
    for line in risen:
        print(f"ROSE {line}")
    print(f"{len(risen)} defect classes rose" if risen else "no defect class rose")
    return 1 if risen else 0


def gate_store(store: Path, limits: dict[str, int]) -> int:
    con = connect_ro(store, timeout_s=60)
    try:
        counts = {row["defect"]: row["documents"] for row in summarize(scan(con))}
    finally:
        con.close()
    over = [f"{defect}: {counts.get(defect, 0)} > {limit}"
            for defect, limit in limits.items() if counts.get(defect, 0) > limit]
    for line in over:
        print(f"OVER {line}")
    print(f"{len(over)} defect classes over limit" if over else "every defect class within its limit")
    return 1 if over else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report", help="write doc_defects.csv and summary.csv for one store")
    report.add_argument("--store", required=True, help="pilot3 store (read-only)")
    report.add_argument("--out", required=True, help="output folder for doc_defects.csv and summary.csv")
    gate = sub.add_parser("gate", help="exit 1 when a defect count rose or exceeds its limit")
    gate.add_argument("--prev", help="previous summary.csv")
    gate.add_argument("--new", help="current summary.csv")
    gate.add_argument("--store", help="store to scan for the --max form")
    gate.add_argument("--max", dest="maxima", help="link_notice=0,misdated=0")
    args = parser.parse_args(argv)
    if args.command == "report":
        return run_report(Path(args.store), Path(args.out))
    if args.store:
        if not args.maxima:
            parser.error("gate --store needs --max <class=limit,...>")
        return gate_store(Path(args.store), parse_limits(args.maxima))
    if not (args.prev and args.new):
        parser.error("gate needs --prev and --new, or --store and --max")
    return gate_prev(Path(args.prev), Path(args.new))


if __name__ == "__main__":
    sys.exit(main())
