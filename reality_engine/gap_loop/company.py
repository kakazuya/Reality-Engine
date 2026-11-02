"""The companies the T-048 gap loop can run on, and the one active company (T-048, 2 Nov 2026).

``python -m reality_engine.gap_loop --sandbox <dir> --company <SYMBOL>`` picks one entry of
``COMPANIES`` (default KEC) and calls ``activate``; every module then reads ``current()`` for its
ISINs, symbol, BSE code, database name, question bank and prompt names.  KEC keeps its original
sandbox and its ``kec.db`` unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT = "KEC"


@dataclass(frozen=True)
class Company:
    symbol: str
    name: str
    isins: tuple[str, ...]
    bse_code: str
    db_name: str
    questions: str  # relative to the sandbox
    raw_sources: tuple[str, ...] = ()  # folders under D:\RealityEngine\raw the PDFs were copied from

    @property
    def sandbox_name(self) -> str:
        return f"{self.symbol.lower()}_loop"

    @property
    def job_name(self) -> str:
        return f"{self.symbol.lower()}_gap_loop"

    @property
    def hp_sandbox(self) -> str:
        return rf"C:\RE\sandbox\{self.symbol.lower()}_loop"

    @property
    def example_qid(self) -> str:
        """The first qid of this company's bank (KEC001, BAJFINANCE001): used in prompts."""
        return f"{self.symbol}001"

    @property
    def isin_key(self) -> str:
        """``isin=<ISIN>`` (several joined by commas) for ``sources.key``."""
        return "isin=" + ",".join(self.isins)

    def isin_clause(self, column: str = "isin") -> str:
        """``isin IN (?,?)``: one placeholder per ISIN, bound with ``isin_params``."""
        return f"{column} IN ({','.join('?' * len(self.isins))})"

    @property
    def isin_params(self) -> tuple[str, ...]:
        return tuple(self.isins)


COMPANIES: dict[str, Company] = {
    "KEC": Company(
        symbol="KEC", name="KEC International Ltd", isins=("INE389H01022",), bse_code="532714",
        db_name="kec.db", questions="questions/KEC_QUESTIONS.jsonl",
        raw_sources=("pilot60_history/KEC",)),
    # The ISIN changed on 2025-06-16 at the split: rows for both ISINs are copied.
    "BAJFINANCE": Company(
        symbol="BAJFINANCE", name="Bajaj Finance Ltd", isins=("INE296A01032", "INE296A01024"),
        bse_code="500034", db_name="bajfinance.db", questions="questions/BAJFINANCE_QUESTIONS.jsonl",
        raw_sources=("pilot60_history/BAJFINANCE",)),
    "HINDALCO": Company(
        symbol="HINDALCO", name="Hindalco Industries Ltd", isins=("INE038A01020",), bse_code="500440",
        db_name="hindalco.db", questions="questions/HINDALCO_QUESTIONS.jsonl",
        raw_sources=("pilot60_history/HINDALCO",)),
}

_active: Company = COMPANIES[DEFAULT]


def lookup(symbol: str) -> Company:
    """The config for a symbol; a symbol that is not configured stops the run with a clear line."""
    key = str(symbol or "").strip().upper()
    if key not in COMPANIES:
        raise SystemExit(f"STOPPED unknown company {symbol!r}: choose one of {', '.join(COMPANIES)}")
    return COMPANIES[key]


def activate(symbol: str) -> Company:
    """Make ``symbol`` the company every gap-loop module uses from now on."""
    global _active
    _active = lookup(symbol)
    return _active


def current() -> Company:
    return _active
