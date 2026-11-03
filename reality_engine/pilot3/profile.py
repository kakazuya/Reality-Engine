"""Pilot build profiles (T-056): the company list and the paths a build reads, from one JSON file.

A profile names the companies (symbol, name, BSE code, ISINs, sector, lender flag), the collector's
``pages_db``, the ``raw_root`` and its ``manifest.csv``, the output database and the ``window_start`` a
build keeps (§ history window).  Every pilot3 module reads it through this module only, so the company
literals live in the JSON and not in an extractor.

Without a profile every module keeps its present defaults (``SYMBOLS``, ``PAGES_DB``, ``pilot3.db``), so
``python -m reality_engine.pilot3.build`` does exactly what it always did::

    python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part kpi
    python -m reality_engine.pilot3.docs_collect --profile <json> --symbols <SYM> --out <pages.db>

The window keeps the stores' rows dated on or after ``window_start`` (``fin_quarter_xbrl``,
``fin_annual_line``, ``shp_category``, ``price_delivery``, ``valuation_daily``); documents come from the
manifest, which is already the requested window.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from reality_engine.gap_loop.company import COMPANIES, Company
from reality_engine.pilot3 import PAGES_DB, SYMBOLS


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
    return Profile(name=str(data.get("name") or source.stem), pages_db=_path(base, data["pages_db"]),
                   raw_root=_path(base, data["raw_root"]), manifest=_path(base, data["manifest"]),
                   out=_path(base, data["out"]), window_start=str(data["window_start"]) if data.get("window_start") else None,
                   companies=tuple(companies))


_ACTIVE: Profile | None = None
_SCOPE: tuple[str, ...] | None = None


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
        return SYMBOLS
    return _SCOPE or _ACTIVE.symbols


def companies() -> dict[str, Company]:
    if _ACTIVE is not None:
        return {c.symbol: c.gap_company() for c in _ACTIVE.companies}
    return COMPANIES


def company(symbol: str) -> Company:
    if _ACTIVE is not None:
        return _ACTIVE.gap_company(symbol)
    return COMPANIES[symbol]


def isins(symbol: str) -> tuple[str, ...]:
    return _ACTIVE.company(symbol).isins if _ACTIVE is not None else tuple()


def is_lender(symbol: str) -> bool:
    """The profile's lender flag; without a profile, the present list in ``ratios.py``."""
    if _ACTIVE is not None:
        return _ACTIVE.is_lender(symbol)
    from reality_engine.pilot3.ratios import LENDERS  # late: ratios reads this module

    return symbol in LENDERS


def pages_db() -> Path:
    return _ACTIVE.pages_db if _ACTIVE is not None else PAGES_DB


def window_start() -> str | None:
    return _ACTIVE.window_start if _ACTIVE is not None else None
