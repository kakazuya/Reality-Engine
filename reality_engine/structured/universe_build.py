"""The structured universe layer (T-209, script only).

``D:/RealityEngine/structured/structured_universe.db`` holds, for every NSE company with a
filing since 2024-04-01:

``shp_category``
    shareholding by category per shareholding filing: promoter, public, fpi_total, mf,
    insurance, other DII (derived as InstitutionsDomestic less mf and insurance) and
    government, with the share count the printed percentage is on.
``shp_pledge``
    the promoter encumbrance block per filing: flags, promoter shares, pledged shares and
    the printed percentage, with the basis that percentage is printed on.
``balance_sheet``
    total equity, borrowings (non-current, current, total), cash and total assets from the
    filed results XBRL, plus capital employed derived as equity + borrowings - cash.

Every row carries ``isin``, ``symbol``, the period end, the basis, the unit, the source file
and ``known_at`` (the exchange dissemination time).  No model call anywhere.

The SHP XBRL parser is ``pilot3.stores.parse_shp_xbrl`` -- the one that already builds the
pilot3 ``shp_category`` / ``shp_pledge`` tables.  This module parses a second way: never.

    python -m reality_engine.structured.universe_build --fetch --workers 4
    python -m reality_engine.structured.universe_build --parse
    python -m reality_engine.structured.universe_build --balance
    python -m reality_engine.structured.universe_build --report

Fetch is resumable (a valid gz in the raw folder is kept) and stops when more than 5 % of a
rolling 100-request window fail twice in a row.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import os
import random
import sqlite3
import threading
import time
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from reality_engine.db.readonly import connect_ro
from reality_engine.pilot3 import stores as pilot_stores

REPO = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("REALITY_DATA_ROOT") or REPO / "reality_engine" / "data")
OUT_DIR = Path(os.environ.get("REALITY_STRUCTURED_DIR") or r"D:\RealityEngine\structured")
DB_PATH = OUT_DIR / "structured_universe.db"
COVERAGE_CSV = OUT_DIR / "coverage.csv"
SAMPLE_CSV = OUT_DIR / "sample20.csv"
RAW_DIR = Path(os.environ.get("REALITY_SHP_XBRL_RAW") or r"D:\RealityEngine\raw\nse_shp_xbrl_universe")
START = "2024-04-01"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 90
SAMPLE_SEED = 20261113

DDL = """
CREATE TABLE IF NOT EXISTS filing(
    record_id      TEXT PRIMARY KEY,
    symbol         TEXT,
    isin           TEXT,                   -- canonical ISIN (symbol_isin_history), else the filed one
    filing_isin    TEXT,                   -- the ISIN the filing/index prints
    period_end     TEXT,                   -- shp_index quarter_end (its own as-on date)
    quarter_end    TEXT,                   -- the quarter the XBRL reports
    known_at       TEXT,                   -- broadcast_at, else submission_date
    known_at_source TEXT,
    revised        TEXT,
    file           TEXT,
    url            TEXT,
    parse_status   TEXT,                   -- ok | no_facts | error | unusable
    n_categories   INTEGER,
    note           TEXT,
    fetched_at     TEXT,
    bytes          INTEGER,
    parsed_at      TEXT
);
CREATE TABLE IF NOT EXISTS shp_category(
    record_id       TEXT NOT NULL,
    symbol          TEXT,
    isin            TEXT,
    filing_isin     TEXT,
    quarter_end     TEXT,
    category        TEXT,                  -- promoter | public | fpi_total | mf | insurance | other_dii | government
    category_raw    TEXT,                  -- the XBRL member or the derivation
    shares          REAL,
    pct             REAL,
    pct_base_shares REAL,                  -- the share count the printed percentage is on
    pct_basis       TEXT,                  -- total_shares | total_excluding_dr_custody
    unit            TEXT,
    is_reported     INTEGER,               -- 0 for a derived row
    source_file     TEXT,
    known_at        TEXT,
    known_at_source TEXT,
    revised         TEXT,
    PRIMARY KEY (record_id, category)
);
CREATE TABLE IF NOT EXISTS shp_pledge(
    record_id       TEXT PRIMARY KEY,
    symbol          TEXT,
    isin            TEXT,
    filing_isin     TEXT,
    quarter_end     TEXT,
    pledge_flag     INTEGER,
    ndu_flag        INTEGER,
    other_flag      INTEGER,
    promoter_shares REAL,
    pledged_shares  REAL,
    pledged_pct     REAL,
    pct_basis       TEXT,                  -- of_promoter_holding | of_total_shares | ...
    other_shares    REAL,
    encumbered_shares REAL,
    unit            TEXT,
    source_file     TEXT,
    known_at        TEXT,
    known_at_source TEXT,
    revised         TEXT
);
CREATE TABLE IF NOT EXISTS balance_sheet(
    source_file     TEXT NOT NULL,
    isin            TEXT,
    symbol          TEXT,
    period_end      TEXT,
    basis           TEXT,                  -- consolidated | standalone
    line_item       TEXT,
    value           REAL,
    unit            TEXT,
    definition      TEXT,                  -- reported tag, or the derivation for a derived line
    xbrl_tag        TEXT,
    is_reported     INTEGER,
    known_at        TEXT,
    known_at_source TEXT,
    PRIMARY KEY (source_file, line_item)
);
CREATE TABLE IF NOT EXISTS bs_filing(
    source_file        TEXT PRIMARY KEY,
    isin               TEXT,
    symbol             TEXT,
    period_end         TEXT,
    basis              TEXT,
    known_at           TEXT,
    has_balance_sheet  INTEGER,
    n_lines            INTEGER
);
CREATE INDEX IF NOT EXISTS ix_u_sc ON shp_category(isin, quarter_end, category);
CREATE INDEX IF NOT EXISTS ix_u_bs ON balance_sheet(isin, period_end, line_item);
"""

#: category member aliases -> store category; the first reported alias wins.
CATEGORY_MEMBERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("promoter", ("ShareholdingOfPromoterAndPromoterGroup",)),
    ("public", ("PublicShareholding",)),
    ("fpi_total", ("InstitutionsForeign", "ForeignInstitutions")),
    ("mf", ("MutualFundsOrUti", "MutualFundsOrUTI")),
    ("insurance", ("InsuranceCompanies",)),
)
DII_MEMBERS = ("InstitutionsDomestic",)
GOVT_MEMBERS = ("Governments", "Goverments")          # the taxonomy's own typo appears in real files
GOVT_PARTS = ("CentralGovernmentOrPresidentOfIndia", "StateGovernmentsOrGovernors")

#: result-XBRL line -> the concepts a filing may use for it, in preference order.
BS_LINES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("borrowings_noncurrent", ("LongTermBorrowings", "BorrowingsNoncurrent")),
    ("borrowings_current", ("ShortTermBorrowings", "BorrowingsCurrent")),
    ("borrowings_total", ("Borrowings",)),
    ("cash_and_cash_equivalents", ("CashAndCashEquivalents",)),
    ("total_assets", ("Assets", "EquityAndLiabilities")),
)
BS_CONCEPTS = tuple({c for _line, tags in BS_LINES for c in tags}
                    | {"Equity", "ShareholdersFunds", "MinorityInterest"})


# ----------------------------------------------------------------------------- store
def open_store(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=120)
    con.execute("PRAGMA journal_mode=WAL")       # a per-file commit on NTFS is ~0.6 s; WAL+NORMAL
    con.execute("PRAGMA synchronous=NORMAL")     # brings a 27k-file parse to minutes
    con.executescript(DDL)
    return con


def _canon_map(con_ei: sqlite3.Connection) -> dict[str, str]:
    """symbol -> the ISIN of its latest ``symbol_isin_history`` window (pre-split ISINs follow)."""
    out: dict[str, str] = {}
    for symbol, isin in con_ei.execute(
            "SELECT upper(symbol), isin FROM symbol_isin_history "
            "WHERE exchange='NSE' ORDER BY COALESCE(last_date, '')"):
        out[symbol] = isin
    return out


def _raw_name(file: str | None, url: str | None) -> str:
    """The raw file's name: ``shp_index.file`` unless it is the literal ``-`` some rows carry."""
    name = (file or "").strip()
    if not name or name in ("-", "NA"):
        name = (url or "").rsplit("/", 1)[-1]
    return name


def seed_filings(con: sqlite3.Connection, con_ei: sqlite3.Connection) -> dict[str, int]:
    """Upsert every in-scope ``shp_index`` filing; unfetchable rows stay as coverage gaps."""
    canon = _canon_map(con_ei)
    rows = con_ei.execute(
        """SELECT record_id, symbol, upper(symbol), isin, quarter_end, broadcast_at,
                  submission_date, revised, xbrl, file
           FROM shp_index WHERE quarter_end >= ? ORDER BY quarter_end""",
        (START,)).fetchall()
    good, unusable = [], 0
    for (rid, symbol, up, isin, period_end, broadcast, submitted, revised, url, file) in rows:
        known = broadcast or submitted
        link = (url or "").strip()
        why = ""
        if not known:
            why = "no known_at"
        elif not link.startswith("http"):
            why = "no XBRL link"
        elif link.rsplit("/", 1)[-1] in ("", "-"):
            why = f"placeholder XBRL link ({link})"
        if why:
            unusable += 1
            con.execute(
                "INSERT INTO filing(record_id, symbol, isin, filing_isin, period_end,  known_at,"
                " known_at_source, revised, file, url, parse_status, note)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,'unusable',?) ON CONFLICT(record_id) DO UPDATE"
                " SET parse_status='unusable', note=excluded.note, file=excluded.file,"
                " url=excluded.url",
                (str(rid), symbol, canon.get(up) or isin, isin, period_end, known,
                 "shp_index.broadcast_at" if broadcast else "shp_index.submission_date",
                 revised, _raw_name(file, url), url, why))
            continue
        good.append((str(rid), symbol, canon.get(up) or isin, isin, period_end, known,
                     "shp_index.broadcast_at" if broadcast else "shp_index.submission_date",
                     revised, _raw_name(file, url), url))
    con.executemany(
        "INSERT INTO filing(record_id, symbol, isin, filing_isin, period_end, known_at,"
        " known_at_source, revised, file, url) VALUES (?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(record_id) DO UPDATE SET symbol=excluded.symbol, isin=excluded.isin,"
        " filing_isin=excluded.filing_isin, period_end=excluded.period_end,"
        " known_at=excluded.known_at, known_at_source=excluded.known_at_source,"
        " revised=excluded.revised, file=excluded.file, url=excluded.url", good)
    con.commit()
    return {"indexed": len(rows), "fetchable": len(good), "unusable": unusable}


# ----------------------------------------------------------------------------- fetch
def _valid(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 256:
        return False
    try:
        body = gzip.decompress(path.read_bytes())
    except (OSError, EOFError):
        return False
    return body.lstrip()[:1] == b"<" and b"</" in body[-4096:]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


_THREAD = threading.local()


def _session() -> requests.Session:
    """One pooled HTTP session per fetch thread (a fresh TLS handshake per file is the bottleneck)."""
    session = getattr(_THREAD, "session", None)
    if session is None:
        session = _THREAD.session = requests.Session()
        session.headers.update({"User-Agent": UA, "Referer": "https://www.nseindia.com/"})
    return session


def fetch(con: sqlite3.Connection, raw_dir: Path = RAW_DIR, limit: int = 0,
          workers: int = 8, pace: float = 0.1) -> dict:
    """Download the missing raw XBRL files (resumable, threaded, error-rate gated)."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    todo = [(rid, file, url) for rid, file, url in con.execute(
        "SELECT record_id, file, url FROM filing WHERE url LIKE 'http%'")
            if not _valid(raw_dir / (f"{file}.gz"))]
    todo = todo[:limit] if limit else todo
    done = failed = 0
    started = time.time()
    recent: deque[bool] = deque(maxlen=100)
    bad_windows = 0
    stopped = ""

    def one(item: tuple[str, str, str]) -> tuple[str, str, int, str | None]:
        rid, file, url = item
        time.sleep(pace)
        try:
            response = _session().get(url, timeout=TIMEOUT)
            response.raise_for_status()
            body = response.content
            if body.lstrip()[:1] != b"<":
                raise ValueError(f"not xml: {body[:40]!r}")
            (raw_dir / f"{file}.gz").write_bytes(gzip.compress(body))
            return rid, file, len(body), None
        except Exception as exc:                        # noqa: BLE001 - recorded, retried next run
            return rid, file, 0, f"fetch failed: {type(exc).__name__}: {exc}"[:300]

    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [pool.submit(one, item) for item in todo]
            for n, fut in enumerate(as_completed(futures), 1):
                rid, _file, size, error = fut.result()
                if error:
                    failed += 1
                    con.execute("UPDATE filing SET note=? WHERE record_id=?", (error, rid))
                else:
                    done += 1
                    con.execute("UPDATE filing SET bytes=?, fetched_at=?, note=NULL "
                                "WHERE record_id=?", (size, _now(), rid))
                recent.append(error is None)
                if n % 100 == 0:
                    con.commit()
                    print(f"fetched {n}/{len(todo)} ok {done} failed {failed} "
                          f"{(time.time() - started) / n:.2f} s/file", flush=True)
                if len(recent) == recent.maxlen:
                    # ponytail: rolling 100-request windows, not a 10-minute clock; a sustained
                    # failure run trips this inside a minute, which is the point.
                    rate = recent.count(False) / len(recent)
                    bad_windows = bad_windows + 1 if rate > 0.05 else 0
                    if bad_windows >= 2:
                        stopped = f"stopped: {rate:.0%} of the last 100 requests failed twice"
                        print(stopped, flush=True)
                        for f in futures:
                            f.cancel()
                        break
    finally:
        con.commit()
    elapsed = time.time() - started
    return {"todo": len(todo), "fetched": done, "failed": failed,
            "seconds": round(elapsed, 1), "stopped": stopped}


# ----------------------------------------------------------------------------- parse
def _pick(facts: dict, member: tuple[str, ...], quarter: str) -> tuple[str, dict] | None:
    for name in member:
        got = facts.get((name, quarter))
        if got is not None:
            return name, got
    return None


def _row(record: dict, category: str, raw: str, facts: dict, reported: int) -> tuple:
    shares, pct = facts.get("NumberOfShares"), facts.get(pilot_stores.PCT)
    return (record["record_id"], record["symbol"], record["isin"], record["filing_isin"],
            record["quarter_end"], category, raw, shares, pct, record["pct_base_shares"],
            record["pct_basis"], "%", reported, record["file"], record["known_at"],
            record["known_at_source"], record["revised"])


def _shp_rows(parsed: dict, record: dict) -> tuple[list[tuple], tuple | None]:
    """One parsed filing -> its ``shp_category`` rows and its ``shp_pledge`` row."""
    facts, quarter = parsed["facts"], record["quarter_end"]
    base, base_label = pilot_stores._pct_base(parsed)
    record = {**record, "pct_base_shares": base, "pct_basis": base_label}
    rows: list[tuple] = []
    for category, members in CATEGORY_MEMBERS:
        found = _pick(facts, members, quarter)
        if found is not None:
            rows.append(_row(record, category, found[0], found[1], 1))
    dii = _pick(facts, DII_MEMBERS, quarter)
    mf = _pick(facts, ("MutualFundsOrUti", "MutualFundsOrUTI"), quarter)
    insurance = _pick(facts, ("InsuranceCompanies",), quarter)
    # ponytail: other_dii = the domestic-institution summary less mf and insurance, written only
    # when both are reported; a missing row is never subtracted as zero. Upgrade: derive from the
    # remaining domestic sub-members (banks, AIF, NBFC, pension) when the summary is absent.
    if dii is not None and mf is not None and insurance is not None:
        shares = [f.get("NumberOfShares") for _n, f in (dii, mf, insurance)]
        pcts = [f.get(pilot_stores.PCT) for _n, f in (dii, mf, insurance)]
        other: dict[str, float] = {}
        if None not in shares:
            other["NumberOfShares"] = round(shares[0] - shares[1] - shares[2], 4)   # type: ignore[operator]
        if None not in pcts:
            other[pilot_stores.PCT] = round(pcts[0] - pcts[1] - pcts[2], 4)         # type: ignore[operator]
        rows.append(_row(record, "other_dii",
                         "InstitutionsDomestic less MutualFundsOrUTI + InsuranceCompanies",
                         other, 0))
    govt = _pick(facts, GOVT_MEMBERS, quarter)
    if govt is not None:
        rows.append(_row(record, "government", govt[0], govt[1], 1))
    else:
        parts = [_pick(facts, (name,), quarter) for name in GOVT_PARTS]
        if all(p is not None for p in parts):
            shares = [p[1].get("NumberOfShares") for p in parts if p is not None]
            pcts = [p[1].get(pilot_stores.PCT) for p in parts if p is not None]
            summe: dict[str, float] = {}
            if None not in shares:
                summe["NumberOfShares"] = round(sum(shares), 4)              # type: ignore[arg-type]
            if None not in pcts:
                summe[pilot_stores.PCT] = round(sum(pcts), 4)                # type: ignore[arg-type]
            rows.append(_row(record, "government",
                             "CentralGovernmentOrPresidentOfIndia + StateGovernmentsOrGovernors",
                             summe, 0))

    promoter = _pick(facts, ("ShareholdingOfPromoterAndPromoterGroup",), quarter)
    if promoter is None:
        return rows, None
    f = promoter[1]
    total = pilot_stores._pct_base(parsed)[0]
    pledged = f.get("NumberOfSharesEncumberedUnderPledged")
    if pledged is None:
        pledged = f.get("PledgedOrEncumberedNumberOfShares")
    pct = f.get("EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares")
    if pct is None:
        pct = f.get("PledgedOrEncumberedSharesHeldAsPercentageOfTotalNumberOfShares")
    promoter_shares = f.get("NumberOfShares")
    flags = parsed["pledge"]
    pledge_row = (
        record["record_id"], record["symbol"], record["isin"], record["filing_isin"],
        quarter,
        pilot_stores._flag(flags.get("WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged")),
        pilot_stores._flag(flags.get(
            "WhetherAnySharesHeldByPromotersAreEncumberedUnderNonDisposalUndertaking")),
        pilot_stores._flag(flags.get(
            "WhetherAnySharesHeldByPromotersAreEncumberedOtherThanByWayOfPledgeOrNDU")),
        promoter_shares, pledged, pct,
        _pledge_basis(pledged, pct, promoter_shares, total, base_label),
        f.get("NumberOfSharesEncumberedUnderOtherEncumbrances"),
        f.get("NumberOfSharesEncumbered") or f.get("PledgedOrEncumberedNumberOfShares"),
        "%", record["file"], record["known_at"], record["known_at_source"], record["revised"])
    return rows, pledge_row


def _pledge_basis(pledged: float | None, pct: float | None, promoter_shares: float | None,
                  total: float | None, base_label: str | None) -> str | None:
    """The base the printed pledge percentage is on, checked against the filing's own numbers.

    The concept names say "of total shares", the pilot3 corpus says of the promoter holding;
    a zero pledge fits both, so it is labelled ``zero_ambiguous`` instead of guessed.
    """
    if pledged is None or pct is None:
        return None
    if pledged == 0:
        return "zero_ambiguous"
    if promoter_shares:
        if abs(pct - pledged / promoter_shares * 100.0) <= 0.05:
            return "of_promoter_holding"
    if total:
        if abs(pct - pledged / total * 100.0) <= 0.05:
            return "of_total_shares_excluding_dr_custody" if base_label == "total_excluding_dr_custody" \
                else "of_total_shares"
    return "as_printed"


def parse(con: sqlite3.Connection, raw_dir: Path = RAW_DIR, limit: int = 0,
          canon: dict[str, str] | None = None) -> dict:
    """Parse every fetched filing into ``shp_category`` / ``shp_pledge`` (idempotent)."""
    todo = [r for r in con.execute(
        "SELECT record_id, symbol, isin, filing_isin, period_end, known_at, known_at_source,"
        " revised, file FROM filing WHERE parse_status IS NULL OR parse_status='error'")
            if _valid(raw_dir / f"{r[8]}.gz")]
    todo = todo[:limit] if limit else todo
    if canon is None:
        canon = _canon_map(connect_ro(DATA / "equity_intelligence.db"))
    counts: dict[str, int] = {}
    for n, row in enumerate(todo, 1):
        (rid, symbol, isin, filing_isin, period_end, known_at, known_src, revised, file) = row
        try:
            parsed = pilot_stores.parse_shp_xbrl(
                gzip.decompress((raw_dir / f"{file}.gz").read_bytes()))
        except Exception as exc:                        # noqa: BLE001 - recorded, not hidden
            _finish(con, rid, "error", None, None, f"{type(exc).__name__}: {exc}"[:300])
            counts["error"] = counts.get("error", 0) + 1
            continue
        head = parsed["head"]
        symbol = head.get("Symbol") or symbol
        filed = head.get("ISIN") or filing_isin
        quarter = pilot_stores._quarter(parsed)
        if not quarter:
            _finish(con, rid, "no_facts", None, None, "no period instant in the file")
            counts["no_facts"] = counts.get("no_facts", 0) + 1
            continue
        record = {"record_id": rid, "symbol": symbol,
                  "isin": canon.get((symbol or "").upper()) or isin or filed,
                  "filing_isin": filed, "period_end": period_end, "quarter_end": quarter,
                  "known_at": known_at, "known_at_source": known_src, "revised": revised,
                  "file": file}
        rows, pledge = _shp_rows(parsed, record)
        con.execute("DELETE FROM shp_category WHERE record_id=?", (rid,))
        con.execute("DELETE FROM shp_pledge WHERE record_id=?", (rid,))
        con.executemany(
            "INSERT OR REPLACE INTO shp_category VALUES (" + ",".join("?" * len(rows[0])) + ")",
            rows)
        if pledge is not None:
            con.execute("INSERT OR REPLACE INTO shp_pledge VALUES ("
                        + ",".join("?" * len(pledge)) + ")", pledge)
        _finish(con, rid, "ok" if rows else "no_facts", symbol, quarter, None,
                isin=record["isin"], filing_isin=filed, n=len(rows))
        counts["ok" if rows else "no_facts"] = counts.get("ok" if rows else "no_facts", 0) + 1
        if n % 200 == 0:
            con.commit()
            print(f"parsed {n}/{len(todo)} {counts}", flush=True)
    con.commit()
    return counts


def _finish(con, rid: str, status: str, symbol: str | None, quarter: str | None,
            note: str | None, isin: str | None = None, filing_isin: str | None = None,
            n: int | None = None) -> None:
    con.execute(
        "UPDATE filing SET parse_status=?, symbol=COALESCE(?, symbol), quarter_end=COALESCE(?, quarter_end),"
        " isin=COALESCE(?, isin), filing_isin=COALESCE(?, filing_isin), n_categories=?,"
        " parsed_at=?, note=? WHERE record_id=?",
        (status, symbol, quarter, isin, filing_isin, n, _now(), note, rid))


# ---------------------------------------------------------------------- balance sheet
def _basis(value: str | None) -> str:
    return "consolidated" if (value or "").strip().lower() == "consolidated" else "standalone"


def _pick_value(facts: dict[str, float], tags: tuple[str, ...]) -> tuple[float, str] | None:
    for tag in tags:
        if tag in facts:
            return facts[tag], tag
    return None


def _equity(facts: dict[str, float]) -> tuple[float, str, str] | None:
    """Total equity: the INDAS ``Equity`` (already total), else shareholders' funds + minority."""
    if "Equity" in facts:
        return (facts["Equity"], "Equity",
                "reported Equity (total equity attributable to owners and minority interest)")
    if "ShareholdersFunds" in facts:
        if "MinorityInterest" in facts:
            return (facts["ShareholdersFunds"] + facts["MinorityInterest"],
                    "ShareholdersFunds + MinorityInterest",
                    "reported shareholders' funds plus minority interest")
        return (facts["ShareholdersFunds"], "ShareholdersFunds",
                "reported shareholders' funds (no minority interest in the filing)")
    return None


def _bs_rows(facts: dict[str, float]) -> list[tuple]:
    """One results filing -> its ``balance_sheet`` rows.

    Each row is ``(value, line_item, xbrl_tag, definition)``; a derived line is tagged
    ``derived`` and says its formula in ``definition``.
    """
    lines: list[tuple] = []
    values: dict[str, float] = {}
    equity = _equity(facts)
    if equity is not None:
        values["total_equity"] = equity[0]
        lines.append((equity[0], "total_equity", equity[1], equity[2]))
    for line, tags in BS_LINES:
        got = _pick_value(facts, tags)
        if got is None:
            continue
        values[line] = got[0]
        definition = f"reported {got[1]}"
        if line == "total_assets" and got[1] == "EquityAndLiabilities":
            definition = "reported EquityAndLiabilities (total assets)"
        lines.append((got[0], line, got[1], definition))
    cash = values.get("cash_and_cash_equivalents")
    if "borrowings_noncurrent" in values or "borrowings_current" in values:
        borrowed = values.get("borrowings_noncurrent", 0.0) + values.get("borrowings_current", 0.0)
    else:
        borrowed = values.get("borrowings_total")
    if "total_equity" in values and cash is not None and borrowed is not None:
        lines.append((values["total_equity"] + borrowed - cash, "capital_employed", "derived",
                      "derived: total equity + borrowings (non-current + current, else total)"
                      " - cash and cash equivalents"))
    return lines


def balance_sheet(con: sqlite3.Connection, results_db: Path | None = None,
                  limit: int = 0) -> dict:
    """Read the filed results XBRL facts into ``balance_sheet`` (idempotent per source file)."""
    src = connect_ro(results_db or DATA / "results_xbrl.db")
    src.set_timeout(180)      # a 500-file facts batch can pass the 30 s default on a busy WAL
    filings = list(src.cursor().execute(
        """SELECT file, isin, symbol, period_end, consolidated,
                  broadcast_ts, dissem_ts, filing_ts
           FROM filings WHERE period_end >= ? AND status='ok' ORDER BY period_end""",
        (START,)).fetchall() or [])
    filings = filings[:limit] if limit else filings
    counts = Counter()
    batch = 500
    for start in range(0, len(filings), batch):
        chunk = filings[start:start + batch]
        files = [r[0] for r in chunk]
        period_of = {r[0]: r[3] for r in chunk}
        marks = ",".join("?" * len(files))
        concept_marks = ",".join("?" * len(BS_CONCEPTS))
        facts: dict[str, dict[str, Counter]] = {}
        fact_rows = src.cursor().execute(
            f"SELECT file, concept, value, instant FROM facts WHERE file IN ({marks}) "
            f"AND concept IN ({concept_marks}) AND unit='INR'",
            (*files, *BS_CONCEPTS)).fetchall() or []
        for file, concept, value, instant in fact_rows:
            if instant != period_of.get(file):          # a comparative instant, not this filing's
                continue
            facts.setdefault(file, {}).setdefault(concept, Counter())[value] += 1
        resolved = dict(src.cursor().execute(
            f"SELECT file, isin FROM filings_isin WHERE file IN ({marks})",
            files).fetchall() or [])
        for (file, isin, symbol, period_end, consolidated,
             broadcast, dissem, filing_ts) in chunk:
            known, source = (broadcast, "filings.broadcast_ts") if broadcast else \
                (dissem, "filings.dissem_ts") if dissem else (filing_ts, "filings.filing_ts")
            if not known:
                counts["no_known_at"] += 1
                continue
            values = {concept: counts_most_common(by_value)
                      for concept, by_value in facts.get(file, {}).items()}
            lines = _bs_rows(values)
            basis = _basis(consolidated)
            isin = resolved.get(file) or isin
            rows = [(file, isin, symbol, period_end, basis, line, value, "INR", definition, tag,
                     0 if tag == "derived" else 1, known, source)
                    for value, line, tag, definition in lines]
            con.execute("DELETE FROM balance_sheet WHERE source_file=?", (file,))
            con.executemany(
                "INSERT INTO balance_sheet(source_file, isin, symbol, period_end, basis,"
                " line_item, value, unit, definition, xbrl_tag, is_reported, known_at,"
                " known_at_source) VALUES (" + ",".join("?" * 13) + ")", rows)
            con.execute(
                "INSERT OR REPLACE INTO bs_filing(source_file, isin, symbol, period_end, basis,"
                " known_at, has_balance_sheet, n_lines) VALUES (?,?,?,?,?,?,?,?)",
                (file, isin, symbol, period_end, basis, known, int(bool(lines)), len(lines)))
            counts["filings"] += 1
            counts["with_balance_sheet"] += int(bool(lines))
            counts["rows"] += len(rows)
        con.commit()
        print(f"balance sheet {min(start + batch, len(filings))}/{len(filings)} {dict(counts)}",
              flush=True)
    return dict(counts)


def counts_most_common(counter: Counter) -> float:
    """The value a concept repeats most often (a comparative context can repeat a tag)."""
    return float(counter.most_common(1)[0][0])


# ----------------------------------------------------------------------------- report
def _coverage(con: sqlite3.Connection) -> list[tuple]:
    """``(dataset, period, companies with a row, companies with a filing)`` per period."""
    rows: list[tuple] = []
    with_row = dict(con.execute(
        "SELECT quarter_end, COUNT(DISTINCT isin) FROM shp_category "
        "WHERE quarter_end IS NOT NULL GROUP BY 1"))
    with_filing = dict(con.execute(
        "SELECT COALESCE(quarter_end, period_end), COUNT(DISTINCT isin) "
        "FROM filing GROUP BY 1"))
    for quarter in sorted(set(with_row) | set(with_filing)):
        rows.append(("shp", quarter, with_row.get(quarter, 0), with_filing.get(quarter, 0)))
    bs_row = dict(con.execute(
        "SELECT period_end, COUNT(DISTINCT isin) FROM balance_sheet GROUP BY 1"))
    bs_filing = dict(con.execute(
        "SELECT period_end, COUNT(DISTINCT isin) FROM bs_filing GROUP BY 1"))
    for period in sorted(set(bs_row) | set(bs_filing)):
        rows.append(("balance_sheet", period, bs_row.get(period, 0), bs_filing.get(period, 0)))
    return rows


def report(con: sqlite3.Connection) -> str:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    coverage = _coverage(con)
    with open(COVERAGE_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["dataset", "period_end", "companies_with_row", "companies_with_filing"])
        w.writerows(coverage)
    _sample(con, SAMPLE_CSV)
    status = dict(con.execute(
        "SELECT COALESCE(parse_status, 'pending'), COUNT(*) FROM filing GROUP BY 1"))
    out = ["# Structured universe store (T-209)", "",
           f"generated {_now()} · {DB_PATH}", "",
           f"- filings indexed: {con.execute('SELECT COUNT(*) FROM filing').fetchone()[0]} · "
           f"{status}",
           f"- shp_category rows: {con.execute('SELECT COUNT(*) FROM shp_category').fetchone()[0]} · "
           f"shp_pledge rows: {con.execute('SELECT COUNT(*) FROM shp_pledge').fetchone()[0]}",
           f"- balance_sheet rows: {con.execute('SELECT COUNT(*) FROM balance_sheet').fetchone()[0]} · "
           f"results filings seen: {con.execute('SELECT COUNT(*) FROM bs_filing').fetchone()[0]}",
           "", "## Coverage (companies with a row / companies with a filing)", ""]
    out += [f"- {dataset} {period}: {n}/{f}" for dataset, period, n, f in coverage]
    out += ["", "## Categories", ""]
    out += [f"- {category} ({reported}): {n} rows"
            for category, reported, n in con.execute(
                "SELECT category, is_reported, COUNT(*) FROM shp_category "
                "GROUP BY 1, 2 ORDER BY 1, 2")]
    out += ["", "## Pledge percentage bases", ""]
    out += [f"- {basis}: {n}" for basis, n in con.execute(
        "SELECT COALESCE(pct_basis, 'none'), COUNT(*) FROM shp_pledge GROUP BY 1 ORDER BY 2 DESC")]
    out += ["", "## Balance-sheet lines", ""]
    out += [f"- {line}: {n} rows" for line, n in con.execute(
        "SELECT line_item, COUNT(*) FROM balance_sheet GROUP BY 1 ORDER BY 1")]
    out += ["", f"- coverage: {COVERAGE_CSV}", f"- sample (seed {SAMPLE_SEED}): {SAMPLE_CSV}"]
    text = "\n".join(out) + "\n"
    (OUT_DIR / "report.md").write_text(text, encoding="utf-8")
    print(text)
    return text


def _sample(con: sqlite3.Connection, path: Path, n: int = 20) -> None:
    """A seeded random sample of data rows, each with its source file for a hand check."""
    tables = [("shp_category", "SELECT COUNT(*) FROM shp_category"),
              ("shp_pledge", "SELECT COUNT(*) FROM shp_pledge"),
              ("balance_sheet", "SELECT COUNT(*) FROM balance_sheet")]
    counts = {name: con.execute(q).fetchone()[0] for name, q in tables}
    total = sum(counts.values())
    rng = random.Random(SAMPLE_SEED)
    out: list[list] = []
    if total:
        population = [name for name, _q in tables]
        weights = [counts[name] for name in population]
        for _ in range(min(n, total)):
            table = rng.choices(population, weights)[0]
            offset = rng.randrange(counts[table])
            if table == "shp_category":
                row = con.execute(
                    "SELECT isin, symbol, quarter_end, category, pct, shares, pct_basis,"
                    " source_file, known_at FROM shp_category LIMIT 1 OFFSET ?",
                    (offset,)).fetchone()
                out.append([table, *row[:4], row[4], "%", row[7], row[8],
                            f"shares={row[5]}; pct_basis={row[6]}"])
            elif table == "shp_pledge":
                row = con.execute(
                    "SELECT isin, symbol, quarter_end, 'pledge', pledged_pct, pledged_shares,"
                    " pct_basis, source_file, known_at FROM shp_pledge LIMIT 1 OFFSET ?",
                    (offset,)).fetchone()
                out.append([table, *row[:4], row[4], "%", row[7], row[8],
                            f"pledged_shares={row[5]}; pct_basis={row[6]}"])
            else:
                row = con.execute(
                    "SELECT isin, symbol, period_end, line_item, value, unit, definition,"
                    " source_file, known_at FROM balance_sheet LIMIT 1 OFFSET ?",
                    (offset,)).fetchone()
                out.append([table, *row[:4], row[4], row[5], row[7], row[8], row[6]])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["dataset", "isin", "symbol", "period_end", "item", "value", "unit",
                    "source_file", "known_at", "detail", "seed"])
        for row in out:
            w.writerow([*row, SAMPLE_SEED])


# ------------------------------------------------------------------------------- cli
def main() -> None:
    global DB_PATH, RAW_DIR, OUT_DIR, COVERAGE_CSV, SAMPLE_CSV
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--parse", action="store_true")
    ap.add_argument("--balance", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--pace", type=float, default=0.1)
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--raw", default=str(RAW_DIR))
    args = ap.parse_args()
    OUT_DIR, DB_PATH, RAW_DIR = Path(args.db).parent, Path(args.db), Path(args.raw)
    COVERAGE_CSV, SAMPLE_CSV = OUT_DIR / "coverage.csv", OUT_DIR / "sample20.csv"
    all_steps = not (args.fetch or args.parse or args.balance or args.report)
    con = open_store(DB_PATH)
    con_ei = connect_ro(DATA / "equity_intelligence.db")
    print("seed:", seed_filings(con, con_ei))
    if args.fetch or all_steps:
        print("fetch:", fetch(con, RAW_DIR, args.limit, args.workers, args.pace))
    if args.parse or all_steps:
        print("parse:", parse(con, RAW_DIR, args.limit))
    if args.balance or all_steps:
        print("balance:", balance_sheet(con, limit=args.limit))
    if args.report or all_steps:
        report(con)


if __name__ == "__main__":
    main()
