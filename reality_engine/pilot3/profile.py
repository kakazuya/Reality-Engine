"""Pilot build profiles (T-056): the company list and the paths a build reads, from one JSON file.

A profile names the companies (symbol, name, BSE code, ISINs, sector, lender flag), the collector's
``pages_db``, the ``raw_root`` and its ``manifest.csv``, the output database and the ``window_start`` a
build keeps (§ history window).  Every pilot3 module reads it through this module only, so the company
literals live in the JSON and not in an extractor.

Without a profile every module keeps its present defaults (the companies the default database's ``company`` table
holds, ``PAGES_DB``, ``pilot3.db``), so ``python -m reality_engine.pilot3.build`` does exactly what it always did::

    python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part kpi
    python -m reality_engine.pilot3.docs_collect --profile <json> --symbols <SYM> --out <pages.db>

The default company list is data, not a literal: it is read from ``REAL_DB``'s ``company`` table (T-094).  The
default lender flag is the filed-line test (``lender.filed_lender``) on that same database.

An optional ``compute_start`` (default: ``window_start``, so nothing changes) lets a build read older rows of
already-held stores as inputs only (trailing four quarters, prior-year comparisons): they never reach an answer
table.  An optional ``extra_indices`` lists more index names for ``index_price`` besides ``Nifty 50``.

The window keeps the stores' rows dated on or after ``window_start`` (``fin_quarter_xbrl``,
``fin_annual_line``, ``shp_category``); documents come from the manifest, which is already the requested window.

``price_start`` (default ``2019-01-01``, and never earlier: ``load`` refuses it) is where every price series
begins (``price_delivery``, ``index_price``, ``valuation_daily``), independent of the document window, so a
five-year price or P/E range can be answered on a build whose documents start at ``window_start`` (T-155).  A
profile may keep prices later than 2019, never earlier.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from reality_engine.db.readonly import connect_ro
from reality_engine.gap_loop.company import Company
from reality_engine.pilot3 import PAGES_DB, REAL_DB
from reality_engine.pilot3.lender import filed_lender

# The first day any price series may start (T-155): the raw market stores begin here, and a profile may keep prices
# later than this, never earlier.
PRICE_START = "2019-01-01"


@dataclass(frozen=True)
class ProfileCompany:
    """One company of a profile; the JSON field names are the dataclass field names."""

    symbol: str
    name: str = ""
    bse_code: str = ""
    isins: tuple[str, ...] = ()
    sector: str = ""
    lender: bool = False

    def gap_company(self) -> Company:
        """The ``gap_loop`` company the store readers take (``prepare.store_copies`` filters by ISIN and
        needs no sandbox): a profile company has no sandbox database and no question bank."""
        return Company(symbol=self.symbol, name=self.name, isins=tuple(self.isins), bse_code=self.bse_code,
                       db_name="", questions="", raw_sources=())


@dataclass(frozen=True)
class Profile:
    name: str
    pages_db: Path
    raw_root: Path
    manifest: Path
    out: Path
    window_start: str | None = None
    companies: tuple[ProfileCompany, ...] = ()
    compute_start: str | None = None
    extra_indices: tuple[str, ...] = ()
    price_start: str | None = None

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(c.symbol for c in self.companies)

    def company(self, symbol: str) -> ProfileCompany:
        key = str(symbol or "").strip().upper()
        for company in self.companies:
            if company.symbol == key:
                return company
        raise KeyError(f"{symbol!r} is not in profile {self.name!r}: {', '.join(self.symbols)}")

    def gap_company(self, symbol: str) -> Company:
        return self.company(symbol).gap_company()

    def is_lender(self, symbol: str) -> bool:
        return self.company(symbol).lender


def _path(base: Path, value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (base / path).resolve()


def load(path: str | Path) -> Profile:
    """The profile at ``path``; a relative path in the JSON is read against the JSON's own directory."""
    source = Path(path).resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    base = source.parent
    companies = []
    for row in data.get("companies") or ():
        companies.append(ProfileCompany(
            symbol=str(row["symbol"]).strip().upper(), name=str(row.get("name") or ""),
            bse_code=str(row.get("bse_code") or ""), isins=tuple(str(i) for i in (row.get("isins") or ())),
            sector=str(row.get("sector") or ""), lender=bool(row.get("lender"))))
    if not companies:
        raise ValueError(f"profile {source} names no companies")
    for key in ("pages_db", "raw_root", "manifest", "out"):
        if not data.get(key):
            raise ValueError(f"profile {source} has no {key!r}")
    price_start = str(data["price_start"]) if data.get("price_start") else None
    if price_start and price_start < PRICE_START:
        raise ValueError(f"profile {source}: price_start {price_start!r} is before {PRICE_START}; price history starts "
                         f"on {PRICE_START} and a profile may only keep it later")
    return Profile(name=str(data.get("name") or source.stem), pages_db=_path(base, data["pages_db"]),
                   raw_root=_path(base, data["raw_root"]), manifest=_path(base, data["manifest"]),
                   out=_path(base, data["out"]), window_start=str(data["window_start"]) if data.get("window_start") else None,
                   companies=tuple(companies),
                   compute_start=str(data["compute_start"]) if data.get("compute_start") else None,
                   extra_indices=tuple(str(i) for i in (data.get("extra_indices") or ())),
                   price_start=price_start)


_ACTIVE: Profile | None = None
_SCOPE: tuple[str, ...] | None = None
_DEFAULT: dict[str, Company] | None = None
_LENDERS: dict[str, bool] = {}


def _default_companies() -> dict[str, Company]:
    """The companies the default database holds (its ``company`` table): the legacy three are data, not code.
    Empty when the database or its table is not there, so a build without a profile says so instead of guessing."""
    global _DEFAULT
    if _DEFAULT is not None:
        return _DEFAULT
    out: dict[str, dict] = {}
    try:
        conn = connect_ro(str(REAL_DB))
    except Exception:
        return {}
    try:
        for symbol, isin, bse_code, name in conn.execute(
                "SELECT symbol, isin, bse_code, name FROM company ORDER BY symbol"):
            entry = out.setdefault(symbol, {"name": name or "", "bse_code": bse_code or "", "isins": []})
            if isin and isin not in entry["isins"]:
                entry["isins"].append(isin)
    except sqlite3.DatabaseError:
        return {}
    finally:
        conn.close()
    _DEFAULT = {symbol: Company(symbol=symbol, name=value["name"], isins=tuple(value["isins"]),
                                bse_code=value["bse_code"], db_name="", questions="", raw_sources=())
                for symbol, value in out.items()}
    return _DEFAULT


def activate(profile: Profile | None) -> Profile | None:
    """Make ``profile`` the one every pilot3 module reads from now on (``None`` restores the defaults)."""
    global _ACTIVE, _SCOPE
    _ACTIVE = profile
    _SCOPE = None
    return _ACTIVE


def active() -> Profile | None:
    return _ACTIVE


def under_profile() -> bool:
    return _ACTIVE is not None


def set_scope(symbols: tuple[str, ...] | None) -> None:
    """Limit the companies every builder reads to a profile build's ``--symbols`` (``None``: all of them).
    Without a profile it does nothing: the pilot3 build rebuilds every company whatever ``--symbols`` says."""
    global _SCOPE
    _SCOPE = tuple(symbols) if _ACTIVE is not None and symbols else None


def symbols() -> tuple[str, ...]:
    if _ACTIVE is None:
        return tuple(_default_companies())
    return _SCOPE or _ACTIVE.symbols


def companies() -> dict[str, Company]:
    if _ACTIVE is not None:
        return {c.symbol: c.gap_company() for c in _ACTIVE.companies}
    return _default_companies()


def company(symbol: str) -> Company:
    if _ACTIVE is not None:
        return _ACTIVE.gap_company(symbol)
    try:
        return _default_companies()[symbol]
    except KeyError:
        raise KeyError(f"{symbol!r} is not in the default database's company table") from None


def isins(symbol: str) -> tuple[str, ...]:
    return _ACTIVE.company(symbol).isins if _ACTIVE is not None else tuple()


def is_lender(symbol: str) -> bool:
    """The profile's lender flag; without a profile, the filed interest / premium lines of the default database."""
    if _ACTIVE is not None:
        return _ACTIVE.is_lender(symbol)
    if symbol not in _LENDERS:
        try:
            conn = connect_ro(str(REAL_DB))
            _LENDERS[symbol] = filed_lender(conn, symbol)
            conn.close()
        except Exception:
            _LENDERS[symbol] = False
    return _LENDERS[symbol]


def pages_db() -> Path:
    return _ACTIVE.pages_db if _ACTIVE is not None else PAGES_DB


def window_start() -> str | None:
    return _ACTIVE.window_start if _ACTIVE is not None else None


def price_start() -> str:
    """The first day every price series is kept (T-155): the profile's own ``price_start`` when it sets one, else
    ``2019-01-01``.  A profile may keep prices later than 2019, never earlier (``load`` refuses that; this repeats
    the check for a ``Profile`` built directly)."""
    start = _ACTIVE.price_start if _ACTIVE is not None and _ACTIVE.price_start else PRICE_START
    if start < PRICE_START:
        raise ValueError(f"price_start {start!r} is before {PRICE_START}: price history starts on {PRICE_START}")
    return start


def compute_start() -> str | None:
    """The date from which older rows are kept as inputs only; None unless the profile sets one earlier than
    ``window_start`` (then nothing is held back)."""
    if _ACTIVE is None or not _ACTIVE.compute_start or not _ACTIVE.window_start:
        return None
    return _ACTIVE.compute_start if _ACTIVE.compute_start < _ACTIVE.window_start else None


def extra_indices() -> tuple[str, ...]:
    return _ACTIVE.extra_indices if _ACTIVE is not None else ()
