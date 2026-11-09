"""Load the fetched credit-rating rationale texts into a small read-only SQLite file (T-139 step 2).

``reality_engine.ingestion.rating_rationale_client`` writes one ``.txt`` per rationale plus ``index.csv``;
this loader splits each text into the agency's key sections and the instrument rows it prints, and writes
them to one SQLite file that ``plugins/reality-data/server/lookups_ratings.py`` (the ``pilot3_ratings`` MCP
tool and ``p3ask ratings``) serves point in time on ``known_at``.

Tables
------
``outside_doc``    exactly the DDL in ``reality_engine/v2/schema_v2.sql``: one row per rationale text,
                   ``text`` holds the whole fetched text verbatim (text is the payload; nothing else is kept).
``rating_doc``     one row per text: symbol, agency, the index ``rating_date``, ``known_at``, title, url.
``rating_action``  every instrument row the text prints (instrument, rating, outlook, action, amount_crore).
``rating_section`` the key sections verbatim: rationale, drivers, strengths, weaknesses, sensitivities,
                   liquidity, outlook.

``known_at`` is the index ``rating_date`` (CARE's is its upload stamp, kept as is) and never earlier than
the press-release date printed in the head of the text: the later of the two wins.

Section headings by agency (the loader matches the printed headings, not the agency):
    CARE    Rationale and key rating drivers / Key strengths / Key weaknesses / Rating sensitivities /
            Liquidity: Strong / Outlook: Stable
    ICRA    Rationale / Key rating drivers and their description / Credit strengths / Credit challenges /
            Rating sensitivities / Liquidity position: Strong / Outlook
    CRISIL  Detailed Rationale / Key Rating Drivers - Strengths|- Weaknesses / Rating sensitivity factors /
            Liquidity Superior / Outlook: Stable
An unrecognised heading still ends the current section, so a section body never runs into the next one.

Usage:
    python -m reality_engine.ingestion.rating_rationale_load \
        --src D:/RealityEngine/outside_doc/ratings_p20 --out .tmp/ratings.db
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from reality_engine.ingestion import rating_rationale_client as client

SECTIONS = ("rationale", "drivers", "strengths", "weaknesses", "sensitivities", "liquidity", "outlook")
SOURCE_BY_AGENCY = {"CARE": "care", "ICRA": "icra", "CRISIL": "crisil", "INDRAT": "indra", "ACUITE": "acuite"}

SCHEMA = """
-- exactly the DDL in reality_engine/v2/schema_v2.sql
CREATE TABLE IF NOT EXISTS outside_doc (
    outside_id    INTEGER PRIMARY KEY,
    source        TEXT NOT NULL,              -- 'crisil','icra','care','indra','siam','dpiit','pib','budget','rbi','sebi'
    kind          TEXT NOT NULL,              -- 'rating_rationale','industry_monthly','budget_line','circular'
    title TEXT, published_at TEXT NOT NULL, url TEXT, sha256 TEXT, text TEXT
);
-- the columns outside_doc does not carry, in side tables (T-139)
CREATE TABLE rating_doc (
    doc_id        INTEGER PRIMARY KEY REFERENCES outside_doc(outside_id),
    symbol        TEXT NOT NULL,
    agency        TEXT NOT NULL,
    rating_date   TEXT,                       -- the index date (CARE: its upload stamp)
    known_at      TEXT NOT NULL,              -- max(index date, press-release date printed in the text)
    title         TEXT,
    url           TEXT
);
CREATE INDEX rating_doc_symbol_day ON rating_doc(symbol, known_at);
CREATE TABLE rating_action (
    doc_id        INTEGER NOT NULL REFERENCES outside_doc(outside_id),
    agency        TEXT,
    instrument    TEXT,
    rating        TEXT,
    outlook       TEXT,
    action        TEXT,
    amount_crore  REAL,
    rating_date   TEXT
);
CREATE INDEX rating_action_doc ON rating_action(doc_id);
CREATE TABLE rating_section (
    doc_id        INTEGER NOT NULL REFERENCES outside_doc(outside_id),
    section       TEXT NOT NULL,
    text          TEXT NOT NULL,
    PRIMARY KEY (doc_id, section)
);
"""

# --- section headings -------------------------------------------------------------------------------
_QUALITY = ("very strong", "superior", "strong", "adequate", "excellent", "moderate", "weak",
            "not applicable", "na", "nil")
# a heading the loader recognises but does not store: it still ends the section before it
_BREAK = re.compile(
    r"^(?:analytical approach|analytical contacts|rating action|rating history|annexure|criteria details|"
    r"liquidity analysis|rating methodology|media relations|about (?:care|careedge|crisil|icra)|disclaimer)\b",
    re.I,
)
_PAGE_NOISE = re.compile(
    r"^(?:\d{1,3}|page\s*[|]\s*\d+|www\.\S+|sensitivity label\s*[:|].*|care ratings (?:ltd|limited)\.?|"
    r"press release|crisil ratings limited\.?|icra limited\.?)$",
    re.I,
)
_SENSITIVITIES = re.compile(
    r"rating sensitivit(?:y|ies)(?: factors)?(?:\s*:?\s*factors likely to lead to rating actions)?", re.I
)
_OUTLOOK = re.compile(
    r"outlook(?:\s*:?\s*(?:stable|positive|negative|developing|rating watch [a-z]+))?", re.I
)
_LIQUIDITY = re.compile(
    r"liquidity(?: position)?(?:\s*:?\s*(?:" + "|".join(_QUALITY) + r"))?", re.I
)
_EXPLICIT = {
    "rationale": "rationale", "rationale and key rating drivers": "rationale", "detailed rationale": "rationale",
    "key strengths": "strengths", "strengths": "strengths", "credit strengths": "strengths",
    "key weaknesses": "weaknesses", "weaknesses": "weaknesses", "credit challenges": "weaknesses",
}


def heading(line: str) -> tuple[str | None, str] | None:
    """``(section key, printed heading)`` for a heading line; ``(None, ...)`` when it only ends a section."""
    text = re.sub(r"\s+", " ", (line or "").strip().strip("*#_")).strip()
    if not text or len(text) > 100 or text[-1] in ".,;":
        return None
    low = text.lower().rstrip(":").strip()
    if _BREAK.match(low):
        return None, text
    if low in _EXPLICIT:
        return _EXPLICIT[low], text
    if low.startswith("key rating drivers"):
        if low.startswith(("key rating drivers and their description", "key rating drivers &")):
            return "drivers", text
        m = re.match(r"key rating drivers\s*[-&]\s*(strengths?|weaknesses?)", low)
        if m:
            return ("strengths" if m.group(1).startswith("strength") else "weaknesses"), text
        return None, text
    if _SENSITIVITIES.fullmatch(low):
        return "sensitivities", text
    if _OUTLOOK.fullmatch(low):
        return "outlook", text
    if _LIQUIDITY.fullmatch(low):
        return "liquidity", text
    return None


def split_sections(text: str) -> dict[str, str]:
    """The rationale's key sections, verbatim; when a heading repeats (a table column header), the longest wins."""
    found: dict[str, str] = {}
    key: str | None = None
    body: list[str] = []

    def flush() -> None:
        if not key or not body:
            return
        value = "\n".join(body).strip()
        if value and len(value) > len(found.get(key, "")):
            found[key] = value

    for raw in text.splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        hit = heading(line)
        if hit is not None:
            flush()
            key = hit[0]
            body = []
            continue
        if key is None:
            continue
        if not line:
            if body and body[-1]:
                body.append("")
            continue
        if _PAGE_NOISE.match(line):
            continue
        body.append(line)
    flush()
    return found


# --- printed date -----------------------------------------------------------------------------------
_MONTHS = {name: number for number, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"), 1)}
_MONTHS.update({name[:3]: number for name, number in list(_MONTHS.items())})
_DATE_PATTERNS = (
    re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9}),?\s+(\d{4})\b"),   # 1 October 2026
    re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b"),   # September 23, 2026
)
_HEAD_LINES = 30


def printed_date(text: str) -> str:
    """The press-release date printed in the head of the text (ISO), or ''.  Body dates are never read."""
    for line in [ln.strip() for ln in text.splitlines() if ln.strip()][:_HEAD_LINES]:
        for index, pattern in enumerate(_DATE_PATTERNS):
            match = pattern.search(line)
            if not match:
                continue
            if index == 0:
                day, month, year = match.group(1), match.group(2), match.group(3)
            else:
                month, day, year = match.group(1), match.group(2), match.group(3)
            number = _MONTHS.get(month.lower())
            if number and 1 <= int(day) <= 31:
                return f"{int(year):04d}-{number:02d}-{int(day):02d}"
    return ""


# --- instrument rows --------------------------------------------------------------------------------
_RATING = re.compile(
    r"(?P<rating>\[?(?:CRISIL|CARE(?:EDGE)?|IND|ICRA|ACUITE|BWR)\]?\s*"
    r"(?:AAA|AA[+-]?|A[1-4]\+?|A[+-]?|BBB[+-]?|BB[+-]?|B[+-]?|C|D)(?:\s*\((?:SO|CE)\))?)",
    re.I,
)
_AMOUNT = re.compile(r"(?:(?:Rs\.?|INR|\u20b9)\s*)?([\d,]+(?:\.\d+)?)\s*(?:crore|cr)", re.I)
_BARE = re.compile(r"^([\d,]+(?:\.\d+)?)$")
_OUTLOOK_FACT = re.compile(r"(?:/|;|\(|,)\s*(Stable|Positive|Negative|Developing|Rating Watch [A-Za-z]+)", re.I)
_REGULATORS = {"rbi", "sebi", "irdai", "pfrda", "mca"}
_HEADER_WORDS = {
    "facilities/instruments", "facility/instrument", "instrument", "instrument*", "instruments",
    "name of the regulator1", "name of the regulator", "name of instrument", "regulator of instrument",
    "amount", "amount (rs. crore)", "amount (rs.crore)", "amount (\u20b9 crore)", "rating", "rating2",
    "rating action", "rating(s)", "current ratings", "previous rated amount", "previous rated amount (rs. crore)",
    "current rated amount", "current rated amount (rs. crore)", "total", "summary of rating action",
    "rating outstanding with outlook", "date", "rating rationale", "date of allotment", "coupon rate (%)",
    "maturity date", "isin", "name of lender", "facility", "total bank loan facilities rated",
}
_SHORT_TERM = re.compile(r"A[1-4]\+?$")


def _long_term(rating: str) -> bool:
    """A long-term letter grade (AAA/AA/A/BBB ...) rather than a short-term A1+/A2+."""
    return not _SHORT_TERM.search((rating or "").strip())


def amount_crore(line: str) -> float | None:
    """The amount printed on a line, in crore (a bare number on its own line counts: CARE prints one per row)."""
    text = line.strip()
    bare = _BARE.fullmatch(text)
    if bare:
        raw = bare.group(1)
    else:
        match = _AMOUNT.search(text)
        if match is None:
            return None
        raw = match.group(1)
    try:
        return round(float(raw.replace(",", "")), 2)
    except ValueError:
        return None


def _action(window: str) -> str:
    low = window.lower()
    for word, canonical in client._ACTION_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            return canonical
    return ""


def _noise(text: str) -> bool:
    low = text.lower().strip(" .:;-|")
    return (not low or low in _REGULATORS or low in _HEADER_WORDS or low.isdigit()
            or bool(_BARE.fullmatch(text.strip())))


def _instrument_before(lines: list[str], index: int) -> str:
    """The instrument name the rating line belongs to: walk back, joining a name wrapped over two lines."""
    texts: list[str] = []
    for line in lines[max(0, index - 8): index]:
        text = re.sub(r"\s+", " ", line).strip(" .:;|")
        if _noise(text) or _RATING.search(text) or _action(text) or len(text) > 120:
            continue
        texts.append(text)
    parts: list[str] = []
    while texts:
        text = texts.pop()
        parts.insert(0, text)
        if len(parts) >= 3 or not texts or not re.search(r"[-([&/]$", texts[-1]):
            break
    return " ".join(parts)


def _amount_before(lines: list[str], index: int) -> float | None:
    for line in reversed(lines[max(0, index - 3): index + 1]):
        value = amount_crore(line)
        if value is not None:
            return value
    return None


def _actions_in(lines: list[str], rating_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for index, line in enumerate(lines):
        match = _RATING.search(line)
        if not match:
            continue
        rating = re.sub(r"\s+", " ", match.group("rating")).strip()
        if not client._looks_like_rating(rating):
            continue
        prefix = line[: match.start()].strip(" .:;-|")
        if _action(prefix):  # "Rating reaffirmed at 'Crisil AAA/Stable'": a sentence, not a table row
            continue
        instrument = prefix if not _noise(prefix) else _instrument_before(lines, index)
        window = " ".join(ln for ln in lines[index: index + 3] if ln.strip())
        outlook = _OUTLOOK_FACT.search(window)
        row = {
            "instrument": instrument,
            "rating": rating,
            "outlook": outlook.group(1).title() if outlook else "",
            "action": _action(window),
            "amount_crore": _amount_before(lines, index),
            "rating_date": rating_date,
        }
        key = (row["instrument"].lower(), rating.lower(), row["action"], row["amount_crore"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def parse_actions(text: str, rating_date: str = "") -> list[dict[str, Any]]:
    """Every instrument row the text prints; the summary table sits above the first rationale section."""
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    head_end = len(lines)
    for index, line in enumerate(lines):
        hit = heading(line)
        if hit is not None and hit[0]:
            head_end = index
            break
    head_end = min(head_end, 200)
    rows = _actions_in(lines[:head_end], rating_date)
    return rows or _actions_in(lines, rating_date)


# --- loading ----------------------------------------------------------------------------------------
def _read(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[:-1] if text.endswith("\n") else text


def _text_path(src: Path, row: dict[str, str]) -> Path | None:
    folder = src / str(row.get("symbol") or "")
    pattern = f"{row.get('agency', '')}_{row.get('rating_date', '')}_*.txt"
    candidates = sorted(folder.glob(pattern)) if folder.is_dir() else []
    if not candidates:
        return None
    digest = (row.get("sha256") or "").strip()
    if digest:
        for path in candidates:
            if hashlib.sha256(_read(path).encode("utf-8")).hexdigest() == digest:
                return path
    return candidates[0]


def load(src: Path, out: Path) -> dict[str, Any]:
    """Build ``out`` from the ``.txt`` files and ``index.csv`` under ``src``; returns the per-company summary."""
    index_path = src / "index.csv"
    if not index_path.is_file():
        raise SystemExit(f"no index.csv under {src}; run rating_rationale_client first")
    with index_path.open("r", encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if (row.get("symbol") or "").strip()]
    out.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(out) + suffix).unlink(missing_ok=True)
    con = sqlite3.connect(out)
    con.executescript(SCHEMA)
    loaded = 0
    missing: list[str] = []
    for row in rows:
        path = _text_path(src, row)
        if path is None:
            missing.append(f"{row.get('symbol')} {row.get('agency')} {row.get('rating_date')}")
            continue
        text = _read(path)
        agency = (row.get("agency") or "").upper()
        rating_date = (row.get("rating_date") or "").strip()
        known_at = max([day for day in (rating_date, printed_date(text)) if day] or [rating_date])
        title = f"{agency} rating rationale for {row['symbol']}".strip()
        cursor = con.execute(
            "INSERT INTO outside_doc (source, kind, title, published_at, url, sha256, text) VALUES (?,?,?,?,?,?,?)",
            (SOURCE_BY_AGENCY.get(agency, agency.lower()), "rating_rationale", title,
             rating_date or known_at, row.get("url") or "", row.get("sha256") or "", text),
        )
        doc_id = int(cursor.lastrowid or 0)
        con.execute(
            "INSERT INTO rating_doc (doc_id, symbol, agency, rating_date, known_at, title, url) VALUES (?,?,?,?,?,?,?)",
            (doc_id, row["symbol"].strip().upper(), agency, rating_date, known_at, title, row.get("url") or ""),
        )
        actions = parse_actions(text, rating_date)
        if not actions:  # the index row is the client's own parse of this same text
            actions = [{
                "instrument": row.get("instrument") or "", "rating": row.get("rating") or "",
                "outlook": row.get("outlook") or "", "action": row.get("action") or "",
                "amount_crore": None, "rating_date": rating_date,
            }]
        for action in actions:
            con.execute(
                "INSERT INTO rating_action (doc_id, agency, instrument, rating, outlook, action, amount_crore, "
                "rating_date) VALUES (?,?,?,?,?,?,?,?)",
                (doc_id, agency, action["instrument"], action["rating"], action["outlook"], action["action"],
                 action["amount_crore"], action["rating_date"]),
            )
        for section, body in split_sections(text).items():
            con.execute("INSERT INTO rating_section (doc_id, section, text) VALUES (?,?,?)",
                        (doc_id, section, body))
        loaded += 1
    con.commit()
    stats = summary(con)
    con.close()
    return {"src": str(src), "out": str(out), "loaded": loaded, "missing": missing, "companies": stats}


def summary(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """Per company: docs, actions, sections and the latest rating per agency (newest rating date, long-term
    grade preferred when the newest rationale rates both a short-term and a long-term instrument)."""
    companies: dict[str, dict[str, Any]] = {}
    graded: dict[tuple[str, str], list[tuple[str, str, str, str]]] = {}
    rows = con.execute(
        "SELECT d.symbol, d.agency, d.doc_id, d.rating_date, a.rating, a.outlook, a.action "
        "FROM rating_doc d LEFT JOIN rating_action a ON a.doc_id = d.doc_id ORDER BY d.symbol, d.rating_date"
    ).fetchall()
    docs = con.execute("SELECT doc_id, symbol FROM rating_doc").fetchall()
    parents = {doc_id: symbol for doc_id, symbol in docs}
    for symbol, agency, doc_id, rating_date, rating, outlook, action in rows:
        company = companies.setdefault(symbol, {"symbol": symbol, "docs": set(), "actions": 0, "sections": 0,
                                                "latest": {}})
        company["docs"].add(doc_id)
        if rating:
            company["actions"] += 1
            graded.setdefault((symbol, agency), []).append(
                (rating_date or "", rating, outlook or "", action or ""))
    for (symbol, agency), actions in graded.items():
        newest = max(item[0] for item in actions)
        chosen = next((item for item in actions if item[0] == newest and _long_term(item[1])),
                      next(item for item in actions if item[0] == newest))
        companies[symbol]["latest"][agency] = {"rating": chosen[1], "outlook": chosen[2], "action": chosen[3],
                                               "rating_date": chosen[0]}
    for doc_id, section in con.execute("SELECT doc_id, section FROM rating_section").fetchall():
        if doc_id in parents:
            companies[parents[doc_id]]["sections"] += 1
    return [{**company, "docs": len(company["docs"])} for company in companies.values()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load rating-rationale texts into a small read-only SQLite file")
    parser.add_argument("--src", required=True, help="folder with <SYMBOL>/*.txt and index.csv")
    parser.add_argument("--out", required=True, help="SQLite file to write (replaced)")
    args = parser.parse_args(argv)
    result = load(Path(args.src), Path(args.out))
    print(f"loaded {result['loaded']} rationale text(s) from {result['src']} -> {result['out']}")
    if result["missing"]:
        print(f"  {len(result['missing'])} index row(s) with no text file: {', '.join(result['missing'])}")
    per_company = result["companies"]
    print(f"  {sum(c['actions'] for c in per_company)} action(s), "
          f"{sum(c['sections'] for c in per_company)} section(s), {len(per_company)} compan(ies)")
    print(f"\n{'symbol':<12}{'docs':>5}{'actions':>9}{'sections':>10}  latest rating per agency")
    for company in per_company:
        latest = "; ".join(
            f"{agency} {item['rating']}{(' / ' + item['outlook']) if item['outlook'] else ''}"
            f"{(' ' + item['action']) if item['action'] else ''} {item['rating_date']}"
            for agency, item in sorted(company["latest"].items())
        )
        print(f"{company['symbol']:<12}{company['docs']:>5}{company['actions']:>9}{company['sections']:>10}  {latest}")
    without = [company["symbol"] for company in per_company if not company["actions"]]
    if without:
        print(f"\n  WARNING: no action row parsed for {', '.join(without)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
