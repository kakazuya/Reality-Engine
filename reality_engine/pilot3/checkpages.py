"""Fast extractor check: fixed pages with known numbers, replayed from the pages already stored.

``make`` builds ``reality_engine/tests/fixtures/pilot3_checkpages.json`` from the graded answers
(``D:\\RealityEngine\\pilot3\\answer_run2\\<SYM>_answers.jsonl`` + ``regrades.tsv``, new grade R or P only):
every answer number whose quote maps to one to three pages of the pilot3 database, a page being a ``doc_page``
row whose normalised text (lower case, non-alphanumerics to single spaces) contains the quote's first 120
normalised characters.  A number on a document type neither extractor reads (``audio_link``, ``other``) is
dropped.  ``make`` also records the found count it measures as the fixture's ``baseline``.

``run`` re-extracts ONLY the fixture pages (plus each of their documents' first three pages, so the document's
reporting period is read as it is in a full build) with the current ``kpi`` and ``guidance`` code, from the
stored page text and -- for the table/chart rules, on that same page -- the PDF word boxes a full build reads.
No full build, no write to the live database.  It prints the per company expected numbers found / missing with
the missing list.  The database is opened read-only; the extraction runs on a throwaway copy under ``--work``.
No model call, no network.

    python -m reality_engine.pilot3.checkpages make   # rebuild the fixture (reads the live db and the answers)
    python -m reality_engine.pilot3.checkpages run    # seconds; the fix-round check
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import time
import uuid
from bisect import bisect_right
from pathlib import Path

from reality_engine.db.readonly import connect_ro
from reality_engine.pilot3 import REAL_DB, SYMBOLS, kpi

ANSWERS_DIR = Path(r"D:\RealityEngine\pilot3\answer_run2")
GRADES = ANSWERS_DIR / "regrades.tsv"
FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "pilot3_checkpages.json"
WORK = Path(".tmp")
GRADES_OK = ("R", "P")
QUOTE_CHARS = 120
SEP = "  "  # normalised text holds single spaces only, so a quote can never match across two pages


def norm(text: str) -> str:
    """Lower case, every non-alphanumeric run to one space (the gold file's page-matching rule)."""
    return re.sub(r"[^0-9a-z]+", " ", (text or "").lower()).strip()


# --- graded answers -> fixed pages ---------------------------------------------------------------
def _float(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def graded_numbers(answers_dir: Path = ANSWERS_DIR, grades_path: Path = GRADES) -> list[dict]:
    """Answer numbers of the questions whose new grade is R or P; a number needs a quote."""
    grades = {}
    for line in Path(grades_path).read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2].strip() in GRADES_OK:
            grades[parts[0].strip()] = parts[2].strip()
    numbers = []
    for symbol in SYMBOLS:
        path = Path(answers_dir) / f"{symbol}_answers.jsonl"
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event.get("event") != "answer" or event.get("qid") not in grades:
                continue
            for number in event.get("numbers") or []:
                value = _float(number.get("value"))
                quote = (number.get("quote") or "").strip()
                if not value or not quote:   # 0 is a grader marker ("0 text"), not a KPI
                    continue
                numbers.append(dict(symbol=symbol, qid=event["qid"], value=value, unit=number.get("unit"),
                                    period=number.get("period"), quote=quote))
    return numbers


def pages_blob(con: sqlite3.Connection, symbol: str):
    """One normalised string for every page of the company, plus (start, end, doc_key, page) and the starts."""
    texts, where, pos = [], [], 0
    for doc_key, page, text in con.execute(
            "SELECT doc_key, page, text FROM doc_page WHERE symbol=? ORDER BY doc_key, page", (symbol,)):
        normed = norm(text)
        texts.append(normed)
        where.append((pos, pos + len(normed), doc_key, page))
        pos += len(normed) + len(SEP)
    return SEP.join(texts), where, [w[0] for w in where]


def quote_pages(quote: str, blob: str, where, starts) -> set[tuple[str, int]]:
    """Every (doc_key, page) whose normalised text holds the quote's first 120 normalised characters."""
    needle = norm(quote)[:QUOTE_CHARS]
    if not needle:
        return set()
    hits: set[tuple[str, int]] = set()
    i = blob.find(needle)
    while i >= 0:
        j = bisect_right(starts, i) - 1
        if j >= 0:
            start, end, doc_key, page = where[j]
            if i + len(needle) <= end:
                hits.add((doc_key, page))
        i = blob.find(needle, i + 1)
    return hits


def build_pages(db: Path = REAL_DB, answers_dir: Path = ANSWERS_DIR, grades_path: Path = GRADES) -> list[dict]:
    """The fixture's page entries: one per (answer number, page) whose quote maps to one to three pages."""
    con = connect_ro(db, timeout_s=60)
    try:
        doc_types = dict(con.execute("SELECT doc_key, doc_type FROM doc"))
        blobs = {symbol: pages_blob(con, symbol) for symbol in SYMBOLS}
    finally:
        con.close()
    entries, seen = [], set()
    for number in graded_numbers(answers_dir, grades_path):
        pages = quote_pages(number["quote"], *blobs[number["symbol"]])
        if not 1 <= len(pages) <= 3:
            continue
        for doc_key, page in sorted(pages):
            doc_type = doc_types.get(doc_key)
            if doc_type not in kpi.KPI_DOC_TYPES:      # no extractor reads this document type
                continue
            key = (number["qid"], doc_key, page, number["value"])
            if key in seen:
                continue
            seen.add(key)
            entries.append(dict(symbol=number["symbol"], qid=number["qid"], doc_key=doc_key, page=page,
                                value=number["value"], unit=number["unit"], period=number["period"],
                                quote=number["quote"], doc_type=doc_type))
    return entries


# --- replaying the pages -------------------------------------------------------------------------
_CROPS = (
    ("per tonne", {"usd_per_tonne", "usd_per_t", "inr_per_t"}),
    ("/tonne", {"usd_per_tonne", "usd_per_t", "inr_per_t"}),
    ("/t", {"usd_per_tonne", "usd_per_t", "inr_per_t"}),
    ("bps", {"bps"}),
    ("basis point", {"bps"}),
    ("crore", {"inr_cr"}),
    ("billion", {"usd_bn", "inr_bn"}),
    ("million", {"usd_mn", "inr_mn", "count_mn"}),
    ("percent", {"pct"}),
    ("%", {"pct"}),
    ("day", {"days"}),
    ("kt", {"kt"}),
    ("tonne", {"tonnes", "kt"}),
    ("count", {"count", "count_cr", "count_mn"}),
    ("number", {"count", "count_cr", "count_mn"}),
)


def unit_family(expected: str | None) -> set[str] | None:
    """Units a stored row may carry for an answer's unit; None = unknown, so any unit passes."""
    unit = (expected or "").lower().strip()
    if not unit:
        return None
    if re.search(r"\bx\b", unit) or unit in ("times", "multiple"):
        return {"x"}
    for marker, family in _CROPS:
        if marker in unit:
            return family
    return None


def value_found(entry: dict, rows) -> bool:
    """True when one extracted row of the page carries the entry's value (0.1% / 0.05 tolerance)."""
    value, family = entry["value"], unit_family(entry.get("unit"))
    for low, high, unit in rows:
        if family is not None and unit not in family:
            continue
        tol = max(0.05, abs(value) * 0.001)
        if low - tol <= value <= high + tol:
            return True
    return False


def _small_db(ro: sqlite3.Connection, symbol: str, entries: list[dict], dst: Path) -> None:
    """A throwaway pilot3-shaped db holding only the checked pages and their documents' first three pages."""
    wanted: dict[str, set[int]] = {}
    for entry in entries:
        wanted.setdefault(entry["doc_key"], set()).update({entry["page"], 1, 2, 3})
    con = sqlite3.connect(dst)
    try:
        con.executescript(
            "CREATE TABLE doc(doc_key TEXT PRIMARY KEY, symbol TEXT, doc_type TEXT, isin TEXT, title TEXT,"
            " filing_date TEXT, known_at TEXT, source_path TEXT, sha256 TEXT);"
            "CREATE TABLE doc_page(doc_key TEXT, page INTEGER, text TEXT, method TEXT);")
        for doc_key, pages in wanted.items():
            row = ro.execute(
                "SELECT doc_key, symbol, doc_type, isin, title, filing_date, known_at, source_key, sha256 "
                "FROM doc WHERE doc_key=? AND symbol=?", (doc_key, symbol)).fetchone()
            if row is None:
                continue
            con.execute("INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?)", row)   # source_key -> source_path: PDF word boxes
            rows = ro.execute(
                f"SELECT doc_key, page, text, method FROM doc_page WHERE doc_key=? AND page IN "
                f"({','.join('?' * len(pages))})", (doc_key, *sorted(pages))).fetchall()
            con.executemany("INSERT INTO doc_page VALUES (?,?,?,?)", rows)
        con.commit()
    finally:
        con.close()


def _sandbox(root: Path, symbol: str) -> Path:
    """An empty sandbox loop db, so the KPI extractor never reads the real one."""
    name = kpi.COMPANIES[symbol]
    folder = root / f"{name}_loop"
    folder.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(folder / f"{name}.db")
    con.executescript("CREATE TABLE docs(doc_key TEXT, doc_type TEXT, known_at TEXT, source_key TEXT);"
                      "CREATE TABLE doc_text(doc_key TEXT, page INTEGER, text TEXT, method TEXT);"
                      "CREATE TABLE deck_figures(sha256 TEXT, known_at TEXT);")
    con.close()
    return root


def replay(db: Path, entries: list[dict], work: Path = WORK, symbols=SYMBOLS) -> dict:
    """Re-extract the fixture pages per company; {symbol: {checked, found, missing}}."""
    from reality_engine.pilot3 import guidance

    todo = [symbol for symbol in SYMBOLS if symbol in symbols and any(e["symbol"] == symbol for e in entries)]
    Path(work).mkdir(parents=True, exist_ok=True)
    root = Path(work) / f"check_{uuid.uuid4().hex[:8]}"   # not mkdtemp: its 0o700 mode is unusable in this sandbox
    root.mkdir()
    ro = connect_ro(db, timeout_s=60)
    result = {}
    try:
        for symbol in todo:
            wanted = [e for e in entries if e["symbol"] == symbol]
            small = root / f"{symbol.lower()}.db"
            _small_db(ro, symbol, wanted, small)
            sandbox = _sandbox(root / "sandbox", symbol)
            rows = list(kpi.extract_company(symbol, sandbox, {}, raw_root=kpi.RAW_ROOT, pages_db=small))
            guidance.run(str(small), [symbol])
            gcon = sqlite3.connect(small)
            try:
                grown = gcon.execute("SELECT doc_key, page, low, high, unit FROM guidance WHERE symbol=?",
                                     (symbol,)).fetchall()
            finally:
                gcon.close()
            index: dict[tuple[str, int], list] = {}
            for row in rows:
                index.setdefault((row["doc_key"], row["page"]), []).append(
                    (float(row["value"]), float(row["value"]), row["unit"]))
            for doc_key, page, low, high, unit in grown:
                low = float(low if low is not None else high)
                high = float(high if high is not None else low)
                index.setdefault((doc_key, page), []).append((low, high, unit))
            missing = [e for e in wanted if not value_found(e, index.get((e["doc_key"], e["page"]), []))]
            result[symbol] = {"checked": len(wanted), "found": len(wanted) - len(missing), "missing": missing}
    finally:
        ro.close()
        shutil.rmtree(root, ignore_errors=True)
    return result


# --- entry points ---------------------------------------------------------------------------------
def make(out: Path = FIXTURE, db: Path = REAL_DB, answers_dir: Path = ANSWERS_DIR, grades_path: Path = GRADES,
         work: Path = WORK) -> dict:
    """Write the fixture from the graded answers and record the baseline this code finds."""
    started = time.time()
    entries = build_pages(db, answers_dir, grades_path)
    result = replay(db, entries, work)
    baseline = {symbol: {"found": r["found"], "checked": r["checked"]} for symbol, r in result.items()}
    baseline["total"] = {"found": sum(r["found"] for r in result.values()),
                         "checked": sum(r["checked"] for r in result.values())}
    payload = {"source": str(answers_dir), "rule": f"quote's first {QUOTE_CHARS} normalised characters on 1-3 pages",
               "baseline": baseline, "pages": entries}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"checkpages: wrote {len(entries)} page entries to {out} in {time.time() - started:.1f} s")
    for symbol in (*SYMBOLS, "total"):
        if symbol in baseline:
            print(f"  {symbol:12} found {baseline[symbol]['found']:3} / {baseline[symbol]['checked']:3}")
    return baseline


def run(fixture: Path = FIXTURE, db: Path = REAL_DB, work: Path = WORK, symbols=SYMBOLS) -> dict:
    """Print the per-company expected numbers found / missing of the fixed pages."""
    payload = json.loads(Path(fixture).read_text(encoding="utf-8"))
    started = time.time()
    result = replay(db, payload["pages"], work, symbols)
    for symbol, r in result.items():
        print(f"{symbol:12} found {r['found']:3} / {r['checked']:3}   missing {len(r['missing'])}")
        for entry in r["missing"]:
            print(f"  missing {entry['qid']:14} {entry['value']:>12g} {entry['unit'] or '':12} "
                  f"{entry['doc_key']} p{entry['page']}")
    print(f"checkpages: {sum(r['checked'] for r in result.values())} page numbers in {time.time() - started:.1f} s")
    return result


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make", help="rebuild the fixture from the graded answers (reads the live db, no write)")
    m.add_argument("--out", default=str(FIXTURE))
    m.add_argument("--db", default=str(REAL_DB))
    m.add_argument("--answers-dir", default=str(ANSWERS_DIR))
    m.add_argument("--grades", default=str(GRADES))
    m.add_argument("--work", default=str(WORK))
    r = sub.add_parser("run", help="re-extract the fixed pages and print found / missing")
    r.add_argument("--fixture", default=str(FIXTURE))
    r.add_argument("--db", default=str(REAL_DB))
    r.add_argument("--work", default=str(WORK))
    r.add_argument("--symbols", default=",".join(SYMBOLS))
    args = ap.parse_args(argv)
    if args.cmd == "make":
        make(Path(args.out), Path(args.db), Path(args.answers_dir), Path(args.grades), Path(args.work))
    else:
        run(Path(args.fixture), Path(args.db), Path(args.work), args.symbols.split(","))


if __name__ == "__main__":
    main()
