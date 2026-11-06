"""Identity verdict for one held document before anything is extracted from it (T-093). Local checks, no model.

Four checks, one column each with a reason: company, fiscal year, type, date.  A failure sets the document aside; it is
never deleted, and the build reads the verdict.  ``check`` is a pure function of the first pages and what the filing
record says, so it can run over the whole universe in parallel.

    ok         every check passed
    set_aside  a check failed: another company's file, a newspaper notice labelled annual report, a 2022 report filed
               under a 2026 date
    unknown    the text is too thin to judge (scanned or garbled); the reason says so and nothing is guessed
    not_held   no file was found for the row

Working now: the file lookup for the common cases (``resolve_file``) and the company check, using the name logic of
``scripts/ar_wrong_company_scan.py``.  The other three checks return ``not_checked``.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

from reality_engine.config import DATA_DIR, resolve_stored_path
from reality_engine.scripts.ar_wrong_company_scan import alias_tokens, page_hits

RAW_ROOT = Path(os.environ.get("REALITY_RAW_ROOT", r"D:\RealityEngine\raw"))
SHA_DIRS = ("concall_pdfs", "decks_full")      # TODO(T-093): every sha-named folder; see docs_collect.SHA_DIRS
FIRST_PAGES = 5
THIN_CHARS = 200


@dataclass
class Expected:
    """What the filing record claims about the document."""
    symbol: str
    doc_type: str
    names: tuple[str, ...] = ()
    isin_prefixes: tuple[str, ...] = ()
    bse_codes: tuple[str, ...] = ()
    bse_subcat: str | None = None
    doc_date: str | None = None
    created_at: str | None = None
    bse_dissem_ts: str | None = None
    publication_date: str | None = None
    pages: int | None = None


@dataclass
class Verdict:
    verdict: str = "unknown"
    company: str = "not_checked"           # ok | mismatch | thin
    company_reason: str = ""
    fiscal_year: str = "not_checked"       # ok | mismatch | thin
    fiscal_year_reason: str = ""
    type: str = "not_checked"              # ok | mismatch | thin
    type_reason: str = ""
    date: str = "not_checked"              # filing | crawl_date
    date_reason: str = ""
    filing_date: str | None = None         # the real filing date, from a filing record
    text_chars: int = 0
    extra: dict = field(default_factory=dict)

    def row(self) -> dict:
        out = asdict(self)
        out.pop("extra")
        return out


def check_company(text: str, expected: Expected) -> tuple[str, str]:
    """Any of the company's names, its ISIN issuer prefix or its BSE scrip code in the first pages.

    TODO(T-093): a mismatch here reads the whole file as the scan does, for its ``name_late`` and ``former_name``
    verdicts, because a rename or a late first mention is not another company's report."""
    aliases = [(name, alias_tokens(name)) for name in expected.names if alias_tokens(name)]
    hits = page_hits(aliases, text)
    if hits:
        return "ok", f"name: {hits[0]}"
    upper = text.upper()
    for prefix in expected.isin_prefixes:
        if prefix.upper() in upper:
            return "ok", f"ISIN prefix {prefix}"
    for code in expected.bse_codes:
        if code and code in text:
            return "ok", f"scrip code {code}"
    return "mismatch", f"none of {list(expected.names)[:2]}, its ISIN prefix or scrip code in the first pages"


def check(first_pages: dict[int, str], expected: Expected) -> Verdict:
    """The verdict from the first pages' text and the filing record.  TODO(T-093): fiscal year, type and date."""
    text = "\n".join(first_pages[page] for page in sorted(first_pages))
    result = Verdict(text_chars=len(text.strip()))
    if result.text_chars < THIN_CHARS:
        result.company = "thin"
        result.company_reason = f"{result.text_chars} characters in the first {len(first_pages)} pages"
        return result
    result.company, result.company_reason = check_company(text, expected)
    result.verdict = "set_aside" if result.company == "mismatch" else "ok"
    return result


def resolve_file(row) -> tuple[Path | None, str]:
    """(path, where) of a ``corporate_documents`` row: the stored path as re-rooted now, then the sha-named folders.

    TODO(T-093): a sha-to-path index built once over the raw store, and the Drive archive (``toolbelt.drive_fetch``,
    no download, an index only) so a row on Drive reads ``drive``, never ``missing``."""
    stored = row["local_file_path"]
    if stored:
        path = resolve_stored_path(stored)
        if path.exists():
            return path, "disk"
    sha = (row["sha256_hash"] or "").lower()
    if sha:
        for folder in SHA_DIRS:
            path = RAW_ROOT / folder / sha[:2] / f"{sha}.pdf"
            if path.exists():
                return path, "disk"
    return None, "missing"


def first_pages(path: Path, count: int = FIRST_PAGES) -> tuple[dict[int, str], int]:
    import pymupdf

    doc = pymupdf.open(path)
    try:
        return {i + 1: doc[i].get_text() for i in range(min(count, len(doc)))}, len(doc)
    finally:
        doc.close()


def expected_for(conn: sqlite3.Connection, row, symbol: str | None = None) -> Expected:
    """What the record claims for a document row.  ``symbol`` overrides the row's, as a swapped-pair control does."""
    symbol = symbol or row["symbol"]
    company = conn.execute("SELECT isin, bse_code, company_name FROM master_companies WHERE nse_symbol=? LIMIT 1",
                           (symbol,)).fetchone()
    names, prefixes, codes = (), (), ()
    if company:
        names = (company["company_name"],) if company["company_name"] else ()
        prefixes = (company["isin"][:7],) if company["isin"] else ()
        codes = (str(company["bse_code"]),) if company["bse_code"] else ()
    return Expected(symbol=symbol, doc_type=row["doc_type"], names=names, isin_prefixes=prefixes, bse_codes=codes,
                    bse_subcat=row["bse_subcat"], doc_date=row["doc_date"], created_at=row["created_at"],
                    bse_dissem_ts=row["bse_dissem_ts"], publication_date=row["publication_date"])


def main_store() -> Path:
    """``equity_intelligence.db``: the worker's data root when it has one (a worktree holds no data)."""
    root = os.environ.get("REALITY_DATA_ROOT")
    return Path(root) / "equity_intelligence.db" if root else DATA_DIR / "equity_intelligence.db"


def check_row(conn: sqlite3.Connection, row, symbol: str | None = None) -> Verdict:
    """One ``corporate_documents`` row from its file to its verdict."""
    path, where = resolve_file(row)
    if path is None:
        return Verdict(verdict="not_held", company_reason=f"no file: {where}", extra={"where": where})
    expected = expected_for(conn, row, symbol)
    pages, expected.pages = first_pages(path)
    result = check(pages, expected)
    result.extra = {"where": where, "path": str(path), "pages": expected.pages}
    return result
