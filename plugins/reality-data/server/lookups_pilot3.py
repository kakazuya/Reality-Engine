"""pilot3 lookups: the one database the reality-data server serves through the ``pilot3_*`` tools (T-049 F).

``pilot3.db`` is built by scripts (``python -m reality_engine.pilot3.build``): dated page text of every held
document, KPI series, reported and derived financial lines, ratios, shareholding, management statements.
``REALITY_PILOT3_DB`` names another build (a profile's, e.g. pilot10).  The companies the tools accept are the ones
the database's ``company`` table holds (T-090: the covered universe, never a fixed list of three); a database built
before the table existed falls back to the bundled pilot3 companies.
These tools answer from it first; the raw files are touched only when a tool says NOT IN DATA.

Read-only (``connect_ro``), small replies, and every row carries ``provenance`` = table, source (document +
page, or store table + row) and ``known_at``.  ``as_of`` drops rows whose ``known_at`` is after that day, and
rows without a ``known_at`` (a row that cannot prove it was public is never shown to a point-in-time question).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import core
from core import DataError
from reality_engine.pilot3 import preferred as p3_preferred
from reality_engine.pilot3.guidance import current_rows as _guidance_current_rows
from reality_engine.pilot3.lender import filed_lender

_MAIN = Path(r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\pilot3\pilot3.db")
MAX_LIMIT = 50
QUOTE_CHARS = 600
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_conn_path: Path | None = None

_DOC_TYPES = {
    "deck": "deck", "decks": "deck", "presentation": "deck", "investor presentation": "deck",
    "transcript": "transcript", "transcripts": "transcript", "concall": "transcript", "call": "transcript",
    "ar": "annual_report", "annual report": "annual_report", "annual_report": "annual_report",
    "announcement": "announcement", "announcements": "announcement", "filing": "announcement",
    "results": "results", "result": "results", "press release": "press_release", "press_release": "press_release",
    "audio_link": "audio_link",
}


def db_path() -> Path:
    env = os.environ.get("REALITY_PILOT3_DB")
    if env:
        return Path(env)
    here = core.DATA / "pilot3" / "pilot3.db"
    return here if here.is_file() else _MAIN


def connect() -> sqlite3.Connection:
    global _conn, _conn_path
    path = db_path()
    with _lock:
        if _conn is not None and _conn_path == path:
            return _conn
        if not path.is_file():
            raise DataError("pilot3_db_missing", f"pilot3.db not found at {path}; build it with "
                            "python -m reality_engine.pilot3.build")
        if _conn is not None:
            _conn.close()
        _conn = core.connect_ro(path, timeout_s=core.READ_TIMEOUT_S, check_same_thread=False, cache_size_kib=-65536)
        _conn.row_factory = sqlite3.Row
        _conn_path = path
        return _conn


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _q(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    try:
        return connect().execute(sql, params).fetchall()
    except core.QueryTimeout as exc:
        raise DataError("query_timeout", str(exc))
    except sqlite3.DatabaseError as exc:
        raise DataError("sql_error", f"{type(exc).__name__}: {exc}")


def _is_lender(sym: str) -> bool:
    """A bank, NBFC or insurer reports interest / premium income, so EV/EBITDA has no meaning for it."""
    return filed_lender(connect(), sym)


# --- symbols, periods, dates ------------------------------------------------------------------------
def pilot_symbols() -> tuple[str, ...]:
    """Every company the database holds: its ``company`` table (T-090).  A build that predates the table serves
    no company (the table is the only source of coverage; T-094 removed the old three-symbol fallback)."""
    try:
        return tuple(row[0] for row in _q("SELECT DISTINCT symbol FROM company WHERE symbol IS NOT NULL AND symbol<>'' "
                                          "ORDER BY symbol"))
    except DataError:
        return ()


def resolve_symbol(symbol: str) -> str:
    """A symbol / BSE code / ISIN / name of a company the database holds; anything else is a DataError."""
    text = (symbol or "").strip()
    if not text:
        raise DataError("bad_symbol", "symbol is required")
    key = text.upper()
    allowed = pilot_symbols()
    if key in allowed:
        return key
    for row in _q("SELECT symbol FROM company WHERE isin=? OR bse_code=? OR upper(name) LIKE ? LIMIT 1",
                  (key, text, f"%{key}%")):
        if row[0] in allowed:
            return row[0]
    try:  # the shared resolver knows more spellings (BAJAJ FINANCE, KEC INTERNATIONAL)
        ident = core.resolve_one(text)
        for cand in (ident.get("nse_symbol"), ident.get("bse_symbol")):
            if cand and cand.upper() in allowed:
                return cand.upper()
    except Exception:
        pass
    raise DataError("not_pilot3", f"{symbol!r} is not a company this pilot database holds: its company table lists "
                    f"{len(allowed)} companies (pilot3_sql 'SELECT symbol FROM company' to search them); use the "
                    "general tools (facts, docs, search_docs) for a company it does not hold")


def _day(value: str | None, field: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        raise DataError("bad_date", f"{field} must be YYYY-MM-DD, got {value!r}")


def _fy2(text: str) -> str:
    return text[-2:]


def norm_period(period: str | None) -> tuple[str | None, str | None]:
    """``(kind, label)``: Q2FY26 / H1FY26 / FY26 labels the tables use; ``kind`` is Q, H1, FY or None.
    Accepts Q2FY26, Q2 FY2026, FY2025-26, 2025-26, FY26, H1FY26 and a date (its fiscal quarter)."""
    if period in (None, ""):
        return None, None
    text = str(period).strip().upper().replace(" ", "")
    m = re.fullmatch(r"Q([1-4])-?FY?(\d{2}|\d{4})", text)
    if m:
        return "Q", f"Q{m[1]}FY{_fy2(m[2])}"
    m = re.fullmatch(r"H([12])-?FY?(\d{2}|\d{4})", text)
    if m:
        return "H" + m[1], f"H{m[1]}FY{_fy2(m[2])}"
    m = re.fullmatch(r"(?:FY)?(\d{4})-(\d{2}|\d{4})", text)
    if m:
        return "FY", f"FY{_fy2(m[2])}"
    m = re.fullmatch(r"(?:FY|YEAR)?-?(\d{2}|\d{4})", text)
    if m:
        return "FY", f"FY{_fy2(m[1])}"
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        year, month = int(m[1]), int(m[2])
        fy = year + 1 if month >= 4 else year
        q = {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3, 1: 4, 2: 4, 3: 4}[month]
        return "Q", f"Q{q}FY{str(fy)[-2:]}"
    return None, text


def _asof(as_of: str | None, col: str = "known_at") -> tuple[str, tuple]:
    day = _day(as_of, "as_of")
    return (f" AND {col} IS NOT NULL AND substr({col},1,10) <= ?", (day,)) if day else ("", ())


def _cap(limit: Any, default: int = 10) -> int:
    try:
        return max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        return default


def _trim(text: str | None, n: int = QUOTE_CHARS) -> str | None:
    if text is None:
        return None
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text if len(text) <= n else text[:n].rstrip() + " …"


def _prov(table: str, source: str, known_at: str | None, **extra: Any) -> dict[str, Any]:
    return {"table": table, "source": source, "known_at": known_at, **{k: v for k, v in extra.items() if v is not None}}


def _db_prov(**extra: Any) -> dict[str, Any]:
    path = db_path()
    built = time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime)) if path.exists() else None
    return {"db": "pilot3", "path": str(path), "read_only": True, "built": built, **extra}


def _reply(symbol: str, rows: list[dict], tool: str, **extra: Any) -> dict[str, Any]:
    out = {"found": bool(rows), "symbol": symbol, "tool": tool, "n": len(rows), "rows": rows, **extra,
           "provenance": _db_prov()}
    if not rows:
        out.setdefault("hint", "NOT IN DATA of pilot3 for these arguments: check the 'available' list, widen the "
                       "period or as_of, try pilot3_search; only then fall back to the raw tools.")
    return out


def _available(table: str, col: str, symbol: str, like: str | None = None, extra: str = "", n: int = 40) -> list[str]:
    sql = f"SELECT {col}, COUNT(*) c FROM {table} WHERE symbol=?{extra}"
    args: list[Any] = [symbol]
    if like:
        sql += f" AND {col} LIKE ?"
        args.append(f"%{like}%")
    sql += f" GROUP BY {col} ORDER BY c DESC LIMIT {n}"
    return [r[0] for r in _q(sql, tuple(args)) if r[0]]


def _pick(table: str, col: str, symbol: str, name: str, extra: str = "") -> tuple[list[str], list[str]]:
    """Names to match for a user's metric word: the exact one, else every name containing it (spaces as _)."""
    key = re.sub(r"[\s\-]+", "_", name.strip().lower())
    names = _available(table, col, symbol, extra=extra, n=500)
    if key in names:
        return [key], names
    near = [n for n in names if key in n]
    return near[:8], names


# --- pilot3_kpi -------------------------------------------------------------------------------------
_DOC_JOIN = ("LEFT JOIN doc d ON d.doc_key = COALESCE((SELECT a.doc_key FROM doc_alias a WHERE a.symbol=k.symbol "
             "AND a.alias_key=k.doc_key), k.doc_key)")
# The words an investor uses for a KPI the store files under a longer metric name (T-165).  "NIM" alone already
# matches nim_pct by substring; "net interest margin", "losses and provisions to assets" and "cost of borrowings"
# did not.  One-word mappings only: a metric name the store holds still wins because it is tried first elsewhere.
_KPI_WORDS = {
    "net_interest_margin": "nim", "net_interest_margins": "nim", "nims": "nim",
    "losses_and_provisions_to_assets": "credit_cost", "provisions_to_assets": "credit_cost",
    "credit_costs": "credit_cost", "cost_of_borrowings": "cost_of_funds", "cost_of_borrowing": "cost_of_funds",
    "cost_of_fund": "cost_of_funds",
}


def kpi(symbol: str, kpi: str, period: str | None = None, as_of: str | None = None,
        dimension: str | None = None, basis: str | None = None, limit: int = 10,
        include_quarantined: bool = False) -> dict[str, Any]:
    """A company-stated KPI (order book, AUM, EBITDA/tonne, NIM ...) from decks, results, releases, transcripts."""
    sym = resolve_symbol(symbol)
    metric_asked = kpi
    kpi = _KPI_WORDS.get(re.sub(r"[\s\-]+", "_", str(kpi).strip().lower()), kpi)
    # the metric NAME is not hidden by a quarantine: the row-level filter below hides the rows and the empty
    # reply says they are held but quarantined (T-165: CHOLAFIN Q2FY27 NIM 7.9 is the only row of its period)
    names, allnames = _pick("kpi_series", "metric", sym, kpi)
    if not names:
        return _reply(sym, [], "pilot3_kpi", available=allnames[:40], metric_asked=metric_asked)
    kind, label = norm_period(period)
    where, args = f"k.symbol=? AND k.metric IN ({','.join('?' * len(names))})", [sym, *names]
    if label:
        where += " AND k.fiscal_period=?"
        args.append(label)
    if dimension:
        where += " AND lower(k.dimension)=?"
        args.append(dimension.strip().lower())
    if basis:
        where += " AND k.basis=?"
        args.append(basis.strip().lower())
    join, check_sel, hide = _check_cols("kpi_series", "k.id")
    visible_where = where          # without the quarantine clause: the "held but hidden" note needs it
    if not include_quarantined:
        where += hide
    extra, eargs = _asof(as_of, "k.known_at")
    rows = _q(f"SELECT k.id, k.metric, k.dimension, k.value, k.unit, k.scale, k.fiscal_period, k.period_type, "
              f"k.as_of_date, k.basis, k.entity, k.doc_key, k.page, k.quote, k.known_at, k.conf_rank, d.doc_key AS dk, "
              f"d.title, d.doc_type{check_sel} FROM kpi_series k {_DOC_JOIN}{join} WHERE {where}{extra} "
              # best evidence first: the extractor's confidence, then a deck/results/filing before a call remark.
              # The window must reach past a measure's duplicates (one value restated in many filings): at 3x the
              # reply size, a restated measure filled it and its lower-confidence period series never arrived (T-049,
              # 4 Nov 2026: Bajaj's quarterly GNPA and KEC's order-intake trend came back as old annual rows only).
              f"ORDER BY k.conf_rank DESC, "
              f"CASE d.doc_type WHEN 'deck' THEN 0 WHEN 'results' THEN 1 WHEN 'press_release' THEN 2 "
              f"WHEN 'annual_report' THEN 3 WHEN 'transcript' THEN 4 ELSE 5 END, "
              # the group statement before standalone when both are filed (as pilot3_fin does): HINDUNILVR Q2FY27
              # Beauty & Wellbeing EBIT came back standalone 1,242 first (filed later) for consolidated 1,235 (8 Nov)
              f"(k.dimension='total') DESC, (k.basis='consolidated') DESC, k.known_at DESC, k.id LIMIT ?",
              (*args, *eargs, _cap(limit) * 30))
    out, seen = [], set()
    for r in rows:
        basis = r["basis"] if r["basis"] in _REPORTING_BASES else "not_stated"
        entity = _entity_of(r, sym)
        dimension = "total" if r["dimension"] in ("consolidated", "standalone") else r["dimension"]
        sig = (r["metric"], entity, dimension, r["fiscal_period"], r["value"], r["unit"])
        if sig in seen:      # the same figure printed again by another filing: one row, best evidence first
            continue
        seen.add(sig)
        out.append(_add_check({"metric": r["metric"], "dimension": dimension, "value": r["value"],
                               "unit": r["unit"], "period": r["fiscal_period"], "period_type": r["period_type"],
                               "as_of_date": r["as_of_date"], "basis": basis, "entity": entity,
                               "quote": _trim(r["quote"], 300),
                               "provenance": _prov("kpi_series", f"{r['dk'] or r['doc_key']} p{r['page']}",
                                                   r["known_at"], doc_type=r["doc_type"], title=r["title"],
                                                   row_id=r["id"])}, r))
    out.sort(key=lambda row: 0 if row["entity"] == sym else 1)   # the company's own rows first (T-088)
    out = out[: _cap(limit)]
    held = None
    held_hidden = None
    if not out:  # the metric exists: say which periods / dimensions hold it, so the next call can be exact
        held = [f"{r[0]} / {r[1]} ({r[2]} rows)" for r in _q(
            f"SELECT fiscal_period, dimension, COUNT(*) FROM kpi_series WHERE symbol=? AND metric IN "
            f"({','.join('?' * len(names))}){_visible('kpi_series')} "
            f"GROUP BY 1, 2 ORDER BY MAX(known_at) DESC LIMIT 40", (sym, *names))]
        # A figure the row check quarantined is still held (T-113): say so, or the caller reads a deliberate hide
        # as "not in data" (CHOLAFIN Q2FY27 NIM 7.9 is exactly this, T-165).
        if not include_quarantined and _has_table("row_check"):
            q_where = (visible_where + " AND EXISTS (SELECT 1 FROM row_check rc WHERE rc.tbl='kpi_series' "
                       "AND rc.row_id=k.id AND rc.status='quarantined')")
            held_hidden = [f"{r[0]} / {r[1]} ({r[2]} rows; the row check quarantined them: "
                           f"include_quarantined=true shows them)" for r in _q(
                f"SELECT k.fiscal_period, k.dimension, COUNT(*) FROM kpi_series k WHERE {q_where} "
                f"GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20", tuple(args))]
    return _reply(sym, out, "pilot3_kpi", metrics_matched=names, held_period_dimension=held,
                  held_quarantined=held_hidden)


# --- pilot3_fin -------------------------------------------------------------------------------------
def fin(symbol: str, measure: str, period: str | None = None, basis: str | None = None,
        definition: str | None = None, as_of: str | None = None, limit: int = 12) -> dict[str, Any]:
    """Reported / derived / company-stated financial lines: annual (FY26, H1FY26) and quarterly (Q2FY26), one
    preferred figure per measure, period and basis (the newest filing's restatement wins, alternatives listed);
    the same election the ``preferred_from`` / ``preferred_to`` columns and ``fin_quarter_current`` hold."""
    sym = resolve_symbol(symbol)
    kind, label = norm_period(period)
    use_q = kind in (None, "Q")
    use_a = kind in (None, "FY", "H1", "H2")
    out: list[dict] = []
    avail: list[str] = []
    cap = _cap(limit)
    bas = basis.strip().lower() if basis else None
    if use_a:
        names, allnames = _pick("fin_annual_line", "line_item", sym, measure)
        avail += allnames
        if names:
            where, args = f"symbol=? AND line_item IN ({','.join('?' * len(names))})", [sym, *names]
            for col, val in (("fiscal_year", label), ("basis", bas), ("definition", definition)):
                if val:
                    where += f" AND {col}=?"
                    args.append(val)
            extra, eargs = _asof(as_of)
            for r in _q(f"SELECT rowid, * FROM fin_annual_line WHERE {where}{extra} "
                        f"ORDER BY fiscal_year DESC, known_at DESC LIMIT ?", (*args, *eargs, cap * 2)):
                out.append(_fin_row(r, "fin_annual_line", r["fiscal_year"], r["definition"],
                                    _fin_source(r)))
    if use_q:
        names, allnames = _pick("fin_quarter_xbrl", "line_item", sym, measure)
        printed_names: list[str] = []
        if _has_table("fin_quarter_printed"):     # a quarter the XBRL window does not hold lives only here (T-057)
            printed_names, printed_avail = _pick("fin_quarter_printed", "line_item", sym, measure)
            allnames = sorted(set(allnames) | set(printed_avail))
        avail += allnames
        got: set = set()
        if names:
            where, args = f"symbol=? AND line_item IN ({','.join('?' * len(names))})", [sym, *names]
            for col, val in (("fiscal_period", label), ("basis", bas)):
                if val:
                    where += f" AND {col}=?"
                    args.append(val)
            extra, eargs = _asof(as_of)
            for r in _q(f"SELECT rowid, * FROM fin_quarter_xbrl WHERE {where}{extra} "
                        f"ORDER BY period_end DESC, known_at DESC LIMIT ?", (*args, *eargs, cap * 2)):
                out.append(_fin_row(r, "fin_quarter_xbrl", r["fiscal_period"], "xbrl_reported",
                                    _fin_source(r)))
                got.add((r["line_item"], r["fiscal_period"]))
        # T-057: the printed comparative columns of the results table, when a check confirmed the cell
        if printed_names:
            where, args = f"symbol=? AND line_item IN ({','.join('?' * len(printed_names))})", [sym, *printed_names]
            for col, val in (("fiscal_period", label), ("basis", bas)):
                if val:
                    where += f" AND {col}=?"
                    args.append(val)
            extra, eargs = _asof(as_of)
            printed = _q(f"SELECT rowid, * FROM fin_quarter_printed WHERE {where} "
                         f"AND basis IN ('standalone','consolidated'){extra} "
                         f"ORDER BY period_end DESC, known_at DESC LIMIT ?", (*args, *eargs, cap * 2))
            for r in printed:
                if (r["line_item"], r["fiscal_period"]) in got:
                    continue             # the XBRL row for that quarter is the evidence; no duplicate
                if not p3_preferred.displayable_printed(r["check_status"], r["raw_token"]):
                    continue
                out.append(_fin_row(r, "fin_quarter_printed", r["fiscal_period"], "printed_comparative",
                                    _fin_source(r)))
    out = _dedupe(p3_preferred.elect(out))
    # No basis asked: a group question means the consolidated statement.  T-049 (4 Nov 2026): HINDALCO's
    # diluted EPS FY26 came back standalone 45.31 where the consolidated 60.20 was wanted; standalone is one
    # explicit argument away, so a mixed reply is filtered to consolidated when it holds the same measure.
    assumed = None
    if bas is None:
        consolidated = [row for row in out if row["basis"] == "consolidated"]
        if consolidated and len(consolidated) < len(out):
            out, assumed = consolidated, "consolidated"
    out = out[:cap]
    return _reply(sym, out, "pilot3_fin", available=sorted(set(avail))[:50] if not out else None, measure_asked=measure,
                  basis_assumed=assumed)


def _fin_source(r: sqlite3.Row) -> str:
    """The filing and the store row: XBRL file name (no page), or document + page when the line came from a PDF."""
    keys = r.keys()
    doc = (r["doc_key"] if "doc_key" in keys else None) or (r["source_file"] if "source_file" in keys else None)
    page = r["page"] if "page" in keys and r["page"] else None
    where = f"{doc} p{page}" if doc and page else (doc or "")
    store = (f"[{r['source_db']}.{r['source_table']} row {r['source_rowid']}]"
             if {"source_db", "source_table", "source_rowid"} <= set(keys) else "")
    return f"{where} {store}".strip()


def _has_table(name: str) -> bool:
    """A pilot3 table may be absent from an older build (fin_quarter_printed came with T-057)."""
    return bool(_q("SELECT 1 FROM sqlite_master WHERE name=? LIMIT 1", (name,)))


# --- T-113: the independent row verdicts (row_check / row_check_fail, written by pilot3.build --part checks) -----
def _visible(tbl: str, row_id: str = "id") -> str:
    """SQL that keeps only rows the checker did not quarantine; empty when the build has no verdict table."""
    if not _has_table("row_check"):
        return ""
    return (f" AND NOT EXISTS (SELECT 1 FROM row_check rc WHERE rc.tbl='{tbl}' AND rc.row_id={row_id} "
            f"AND rc.status='quarantined')")


def _check_cols(tbl: str, row_id: str) -> tuple[str, str, str]:
    """(LEFT JOIN, selected columns, hide clause) for the row verdicts; all empty in a build without them."""
    if not _has_table("row_check"):
        return "", "", ""
    join = f" LEFT JOIN row_check rc ON rc.tbl='{tbl}' AND rc.row_id={row_id}"
    select = (f", rc.status AS check_status, (SELECT GROUP_CONCAT(f.check_name, ',') FROM row_check_fail f "
              f"WHERE f.tbl='{tbl}' AND f.row_id={row_id} AND f.hard=0) AS check_names")
    return join, select, " AND COALESCE(rc.status,'')<>'quarantined'"


def _add_check(row: dict[str, Any], r: Any) -> dict[str, Any]:
    """Every served row says verified / unverified (or null when the check part has not judged it), T-113.

    ``r`` is the fetched row: a ``sqlite3.Row`` from the queries, or a plain dict when ``guidance`` re-elects the
    current target in memory."""
    if "check_status" in r.keys():
        row["check_status"] = r["check_status"]
        if r["check_status"] == "unverified" and r["check_names"]:
            row["check_note"] = r["check_names"].replace(",", ", ")
    return row


_REPORTING_BASES = ("consolidated", "standalone", "not_stated")


def _entity_of(row: Any, symbol: str) -> str:
    """The entity a KPI row reports (T-088): its stored entity, else the subsidiary token an older build left in
    ``basis``, else the company.  A reporting-basis word in the entity column is not an entity."""
    basis = row["basis"] if row["basis"] in _REPORTING_BASES else None
    entity = row["entity"] or basis or symbol
    return symbol if entity in _REPORTING_BASES or entity == "total" else entity


def _fin_row(r: sqlite3.Row, table: str, period: str, definition: str, source: str) -> dict[str, Any]:
    unit, scale, value = r["unit"], r["scale"] or 1.0, r["value"]
    row = {"measure": r["line_item"], "period": period, "basis": r["basis"] or "not_stated", "definition": definition,
           "value": value, "unit": unit, "scale": scale,
           "provenance": _prov(table, source, r["known_at"], row_id=r["rowid"], period_end=r["period_end"])}
    if unit in ("inr", "inr_cr", "inr_mn", "inr_lakh") or (unit or "").startswith("inr") and "share" not in (unit or ""):
        row["value_inr"] = value * scale
    keys = r.keys()
    if "column_role" in keys and r["column_role"]:
        row["column_role"] = r["column_role"]
    if table in ("fin_annual_line", "fin_quarter_printed") and r["quote"]:
        row["quote"] = _trim(r["quote"], 240)
    if table != "fin_annual_line":      # a quarter: the preferred comparative election needs its filing date
        row["_table"], row["_known_at"], row["_rowid"] = table, r["known_at"], r["rowid"]
        if "check_status" in keys:
            row["_check"] = r["check_status"]
    return row


def _dedupe(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        sig = (r["measure"], r["period"], r["basis"], r["definition"], r["value"])
        if sig not in seen:
            seen.add(sig)
            out.append(r)
    return out


# --- pilot3_ratio -----------------------------------------------------------------------------------
VALUATION_FIELDS = ("pe", "pb", "ev_ebitda", "market_cap", "dividend_yield_pct", "trailing_eps", "trailing_pat",
                    "net_worth", "net_debt", "trailing_ebitda", "close", "shares_outstanding")



def _ev_all_investments(sym: str, rows: list, reply: dict) -> None:
    """MARUTI-083: next to EV/EBITDA on plain net debt, give it on net debt after ALL investments (non-current too),
    from the latest ``net_debt_all_investments`` line known on the row's date, and say so when they differ by >10%."""
    for row, r in zip(reply.get("rows", []), rows):
        v = _q("SELECT market_cap, net_debt, trailing_ebitda FROM valuation_daily WHERE rowid=?", (r["rowid"],))
        if not v or not v[0]["trailing_ebitda"] or v[0]["market_cap"] is None:
            continue
        alt = _q("SELECT value*scale AS v, period_end, known_at FROM fin_annual_line WHERE symbol=? AND basis=? "
                 "AND line_item='net_debt_all_investments' AND definition='xbrl_derived' AND substr(known_at,1,10)<=? "
                 "ORDER BY known_at DESC LIMIT 1", (sym, r["basis"], r["date"]))
        if not alt:
            continue
        ev_alt = (v[0]["market_cap"] + alt[0]["v"]) / v[0]["trailing_ebitda"]
        row["inputs"].update({"net_debt": v[0]["net_debt"], "net_debt_all_investments": alt[0]["v"],
                              "ev_ebitda_all_investments": round(ev_alt, 2)})
        if row["value"] and abs(ev_alt / row["value"] - 1) > 0.10:
            reply["note"] = ("EV/EBITDA uses net debt = borrowings - cash - bank balances - current investments; "
                             "non-current investments are large here, so give both: 'ev_ebitda_all_investments' in "
                             "inputs also subtracts them (balance sheet of " + alt[0]["period_end"] + ")")

def ratio(symbol: str, ratio: str, period: str | None = None, as_of: str | None = None,
          basis: str | None = None, limit: int = 8) -> dict[str, Any]:
    """Derived ratios (margins, ROE, growth, days ...) from ratio_panel; PE/PB/EV-EBITDA/market cap on a date
    from valuation_daily (``period`` or ``as_of`` as a YYYY-MM-DD day; latest on or before it)."""
    sym = resolve_symbol(symbol)
    key = re.sub(r"[\s\-/]+", "_", ratio.strip().lower())
    cap = _cap(limit)
    bas = (basis or "").strip().lower() or None
    day = _day(as_of, "as_of")
    if key in VALUATION_FIELDS or key in ("p_e", "p_b", "ev_to_ebitda", "dividend_yield"):
        key = {"p_e": "pe", "p_b": "pb", "ev_to_ebitda": "ev_ebitda", "dividend_yield": "dividend_yield_pct"}.get(key, key)
        when = period if period and re.fullmatch(r"\d{4}-\d{2}-\d{2}", period) else day or dt.date.today().isoformat()
        sql = (f"SELECT rowid, date, basis, {key} AS value, close, shares_outstanding, known_at, input_refs "
               f"FROM valuation_daily WHERE symbol=? AND date<=? AND {key} IS NOT NULL")
        args: list[Any] = [sym, when]
        if bas:
            sql += " AND basis=?"
            args.append(bas)
        extra, eargs = _asof(as_of)
        rows = _q(sql + extra + " ORDER BY date DESC, (basis='consolidated') DESC LIMIT ?", (*args, *eargs, cap))
        reply = _reply(sym, [{"ratio": key, "date": r["date"], "basis": r["basis"], "value": r["value"],
                              "inputs": {"close": r["close"], "shares_outstanding": r["shares_outstanding"]},
                              "provenance": _prov("valuation_daily", f"row {r['rowid']}", r["known_at"],
                                                  input_refs=_trim(r["input_refs"], 200))} for r in rows],
                       "pilot3_ratio")
        if key == "ev_ebitda" and rows:
            _ev_all_investments(sym, rows, reply)
        if key == "ev_ebitda" and not rows and _is_lender(sym):
            reply["note"] = ("EV/EBITDA is not defined for a bank, NBFC or insurer: the store keeps no such row "
                             "for a lender by design, it is not missing data")
        return reply
    names, allnames = _pick("ratio_panel", "metric", sym, ratio)
    if not names:
        return _reply(sym, [], "pilot3_ratio", available=allnames[:40] + list(VALUATION_FIELDS), metric_asked=ratio)
    kind, label = norm_period(period)
    where, args = f"p.symbol=? AND p.metric IN ({','.join('?' * len(names))})", [sym, *names]
    if label:
        where += " AND p.fiscal_period=?"
        args.append(label)
    if bas:
        where += " AND p.basis=?"
        args.append(bas)
    extra, eargs = _asof(as_of, "p.known_at")
    rows = _q(f"SELECT p.rowid, p.*, f.expression FROM ratio_panel p LEFT JOIN formula f ON f.formula_id=p.formula_id "
              f"WHERE {where}{extra} ORDER BY p.period_end DESC, (p.period_type='Q') DESC, "
              f"(p.basis='consolidated') DESC, p.known_at DESC LIMIT ?", (*args, *eargs, cap))
    derived = []
    for r in rows:
        row = {"ratio": r["metric"], "period": r["fiscal_period"], "period_type": r["period_type"],
               "basis": r["basis"], "value": r["value"], "unit": r["unit"], "definition": "derived",
               "formula": r["expression"],
               "provenance": _prov("ratio_panel", f"row {r['rowid']}", r["known_at"],
                                   formula_id=r["formula_id"], input_refs=_trim(r["input_refs"], 240),
                                   derived=bool(r["is_derived"]))}
        if r["formula_id"] in ("F_PAT_TTM", "F_PAT_BE_TTM"):   # the trailing inputs, so TTM needs no hand sum
            try:
                row["inputs"] = json.loads(r["input_refs"] or "[]")
            except ValueError:
                row["inputs"] = []
        derived.append(row)
    stated = _stated_ratios(sym, key, label, as_of, bas, cap)
    # The company's own figure answers "what is X's ROE for FY26"; the derived row is our arithmetic beside it
    # (T-107: Bajaj's FY26 ROE is its stated 18.1, not the 16.96 that LTM PAT over closing net worth derives).
    return _reply(sym, stated + derived, "pilot3_ratio", metrics_matched=names)


def _stated_ratios(sym: str, key: str, label: str | None, as_of: str | None, basis: str | None,
                   cap: int, include_quarantined: bool = False) -> list[dict]:
    """The company's own figure for a derived ratio, when kpi_series holds it (T-088): ROE, NIM, margins ... .

    ``ratio_panel`` computes a ratio; a company that prints its own number states it in kpi_series.  Both are
    returned, never merged: the stated one carries its quote and page.  The company's own rows win over a
    subsidiary's, then the consolidated basis, then the best evidence (a table row over a call remark).  A row the
    independent checker quarantined is never served (T-113)."""
    names = [key, f"{key}_pct"] if not key.endswith("_pct") else [key]
    names = [n for n in dict.fromkeys(names)
             if _q(f"SELECT 1 FROM kpi_series WHERE symbol=? AND metric=?"
                   f"{'' if include_quarantined else _visible('kpi_series')} LIMIT 1", (sym, n))]
    if not names:
        return []
    where = f"k.symbol=? AND k.metric IN ({','.join('?' * len(names))})"
    args: list[Any] = [sym, *names]
    if label:
        where += " AND k.fiscal_period=?"
        args.append(label)
    join, check_sel, hide = _check_cols("kpi_series", "k.id")
    if not include_quarantined:
        where += hide
    extra, eargs = _asof(as_of, "k.known_at")
    rows = _q(f"SELECT k.id, k.metric, k.dimension, k.value, k.unit, k.fiscal_period, k.basis, k.entity, k.doc_key, "
              f"k.page, k.quote, k.known_at, k.conf_rank, d.doc_key AS dk, d.title, d.doc_type{check_sel} "
              f"FROM kpi_series k {_DOC_JOIN}{join} WHERE {where}{extra} ORDER BY k.fiscal_period DESC, "
              f"(k.basis='consolidated') DESC, "
              f"(k.dimension='total') DESC, k.conf_rank DESC, k.known_at DESC LIMIT ?",
              (*args, *eargs, cap * 20))
    best: dict[str, dict] = {}
    for r in rows:
        row_basis = r["basis"] if r["basis"] in _REPORTING_BASES else "not_stated"
        entity = _entity_of(r, sym)
        if entity != sym:
            continue                    # a subsidiary's figure is not the company's
        if basis and row_basis != basis:
            continue
        if r["fiscal_period"] in best:
            continue                    # rows arrive best first: the first company row of the period wins
        best[r["fiscal_period"]] = _add_check({
            "ratio": key, "period": r["fiscal_period"], "period_type": "Q" if r["fiscal_period"].startswith("Q") else "FY",
            "basis": row_basis, "value": r["value"], "unit": r["unit"], "definition": "company_stated",
            "entity": entity, "quote": _trim(r["quote"], 240),
            "provenance": _prov("kpi_series", f"{r['dk'] or r['doc_key']} p{r['page']}", r["known_at"],
                                doc_type=r["doc_type"], title=r["title"], row_id=r["id"])}, r)
    return list(best.values())[:cap]


# --- pilot3_holding ---------------------------------------------------------------------------------
HOLDING_TOP = 12
_QUARTER_ENDS = ("03-31", "06-30", "09-30", "12-31")   # a calendar quarter end, the comparable trend point
# The words an investor uses for a filed category (T-165).  A stored category name that already matches wins;
# these are the fallbacks for a word that is never a column value (GoI, MF, DII ...).
_HOLDING_CATEGORY_WORDS: dict[str, tuple[str, ...]] = {
    "government": ("central_government_or_president_of_india", "governments",
                   "central_government_or_state_government_s", "state_governments_or_governors"),
    "govt": ("central_government_or_president_of_india", "governments",
             "central_government_or_state_government_s", "state_governments_or_governors"),
    "goi": ("central_government_or_president_of_india",),
    "dipam": ("central_government_or_president_of_india",),
    "president": ("central_government_or_president_of_india",),
    "fpi": ("fpi", "fpi_total", "fpi_category_1", "fpi_category_2", "institutions_foreign"),
    "fii": ("fpi", "fpi_total", "fpi_category_1", "fpi_category_2", "institutions_foreign"),
    "mf": ("mutual_funds",),
    "mutual_fund": ("mutual_funds",),
    "mutual_funds": ("mutual_funds",),
    "dii": ("institutions_domestic", "mutual_funds", "insurance", "banks", "pension_funds"),
    "retail": ("retail_up_to_2_lakh", "retail_above_2_lakh"),
}


def _holding_categories(sym: str, asked: str | None, extra: str,
                        eargs: tuple) -> tuple[list[str], list[str]]:
    """The stored shp_category names a user's category words mean, and every category the company holds.

    ``government`` / ``GoI`` / ``DIPAM`` map to ``central_government_or_president_of_india`` (Vodafone Idea's
    49%), ``FPI`` / ``FII`` to ``fpi_total`` and its component lines, ``MF`` / ``mutual fund`` to
    ``mutual_funds``.  A word that matches no stored category returns no names; the reply then lists
    ``categories_held`` (T-165)."""
    held = [r[0] for r in _q(f"SELECT DISTINCT category FROM shp_category WHERE symbol=?{extra} ORDER BY 1",
                             (sym, *eargs))]
    if not asked:
        return [], held
    picked: list[str] = []
    for word in re.split(r"[,;/&]| and ", asked):
        key = re.sub(r"[\s\-]+", "_", word.strip().lower())
        if not key:
            continue
        names = _HOLDING_CATEGORY_WORDS.get(key)
        if names is None:
            names = (key,) if key in held else tuple(c for c in held if key in c)
        picked.extend(c for c in names if c in held)
    return list(dict.fromkeys(picked)), held


def _pledge_text(r: sqlite3.Row, pct: float | None) -> str:
    """The filing's own answer to "what share of promoter holding is pledged", never a computed guess."""
    if r["pledge_flag"] is None:
        return f"the {r['quarter_end']} filing prints no promoter pledge flag"
    if not r["pledge_flag"]:
        return ("the filing states that no shares held by promoters are encumbered under pledge"
                + (" (nor under a non-disposal undertaking)" if r["ndu_flag"] == 0 else ""))
    if r["pledged_shares"] is None:
        return "the filing states promoter shares are pledged but prints no count"
    if pct is None:
        return f"{r['pledged_shares']:.0f} promoter shares are pledged (the filing prints no percentage)"
    return (f"{pct:g}% of the promoter holding is pledged ({r['pledged_shares']:.0f} of "
            f"{r['promoter_shares']:.0f} shares)" if r["promoter_shares"] else f"{r['pledged_shares']:.0f} shares pledged")


def _pledge_block(r: sqlite3.Row) -> dict[str, Any]:
    """One quarter's encumbrance block.  Nil is a fact (T-108): a filing whose pledge flag says no promoter share is
    pledged gives pledged shares 0 and 0% with ``nil`` true, so a reader never reports the quarter as 'not found'."""
    pct = r["pledged_pct"]
    shares = r["pledged_shares"]
    if pct is None and shares is not None and r["promoter_shares"]:
        pct = round(shares / r["promoter_shares"] * 100.0, 4)
    nil = r["pledge_flag"] is not None and not r["pledge_flag"]
    if nil:
        shares = 0.0 if shares is None else shares
        pct = 0.0 if pct is None else pct
    return {"quarter_end": r["quarter_end"], "nil": nil,
            "pledge_flag": None if r["pledge_flag"] is None else bool(r["pledge_flag"]),
            "non_disposal_undertaking_flag": None if r["ndu_flag"] is None else bool(r["ndu_flag"]),
            "other_encumbrance_flag": None if r["other_flag"] is None else bool(r["other_flag"]),
            "promoter_shares": r["promoter_shares"], "pledged_shares": shares,
            "pledged_pct_of_promoter_holding": pct, "other_encumbered_shares": r["other_shares"],
            "encumbered_shares": r["encumbered_shares"],
            "answer": (f"nil: {_pledge_text(r, pct)} (filing for {r['quarter_end']})" if nil else _pledge_text(r, pct)),
            "provenance": _prov("shp_pledge", r["source_file"], r["known_at"])}


def holding(symbol: str, as_of: str, quarter_end: str | None = None, all_categories: bool = False,
            all_holders: bool = False, category: str | None = None, quarters: int = 1) -> dict[str, Any]:
    """Shareholding pattern in force on ``as_of`` (the latest quarter whose filing was out by then) + shares
    outstanding.  EVERY filed category is returned, one row per category and quarter, the XBRL filing before the
    shp_index copy of promoter/public, each row with ``pct`` and the ``pct_basis`` its percentage is printed on.

    ``category`` filters by the words an investor uses: government / GoI / DIPAM ->
    ``central_government_or_president_of_india``, FPI / FII -> ``fpi_total`` and its lines, MF / mutual fund,
    promoter, public, retail, DII; a word matching no stored category returns nothing and lists
    ``categories_held``.  ``quarters`` (default 1, max 12) returns the last N quarters in force, so a "last four
    quarters" path is one call; ``quarter_end`` pins one quarter.  ``holders`` are the latest quarter's named
    holders (top 12 by shares, excluding the persons-in-concert disclosures); ``all_holders`` lists every named
    holder including them, with ``pac_name``.  ``promoter_pledge`` is the filing's own encumbrance block,
    ``pct_basis`` the share count its percentages are on, ``quarters_held``/``categories_held`` what the table
    covers.  ``all_categories`` is kept for older briefs: every filed category is returned anyway (T-165)."""
    sym = resolve_symbol(symbol)
    day = _day(as_of, "as_of")
    if not day:
        raise DataError("bad_date", "as_of (YYYY-MM-DD) is required")
    qe = _day(quarter_end, "quarter_end")
    extra, eargs = _asof(day)
    # The latest quarter with an XBRL filing, not merely any row: a build can carry the newest quarter's
    # shp_index promoter/public row (known at the reload) before its XBRL categories, and answering from that
    # lone row hid the complete previous quarter (T-165: Vodafone Idea's GoI 49% at 30-Jun-26).
    row = _q(f"SELECT MAX(quarter_end) q FROM shp_category WHERE symbol=? AND quarter_end<=?{extra}"
             + (" AND quarter_end=?" if qe else "") + " AND source_kind='xbrl'",
             (sym, day, *eargs, *((qe,) if qe else ())))
    if not (row and row[0]["q"]):
        row = _q(f"SELECT MAX(quarter_end) q FROM shp_category WHERE symbol=? AND quarter_end<=?{extra}"
                 + (" AND quarter_end=?" if qe else ""), (sym, day, *eargs, *((qe,) if qe else ())))
    quarter = row[0]["q"] if row else None
    held = _q(f"SELECT MIN(quarter_end) f, MAX(quarter_end) l, COUNT(DISTINCT quarter_end) n FROM shp_category "
              f"WHERE symbol=?{extra}", (sym, *eargs))[0]
    rows: list[dict] = []
    basis = None
    picked: list[str] = []
    qlist: list[str] = []
    if quarter:
        try:
            want = max(1, min(int(quarters or 1), 12))
        except (TypeError, ValueError):
            want = 1
        qlist = [r[0] for r in _q(f"SELECT DISTINCT quarter_end FROM shp_category WHERE symbol=? "
                                  f"AND quarter_end<=?{extra} ORDER BY quarter_end DESC",
                                  (sym, quarter, *eargs))]
        # A trend runs on quarter ends: an SHP filed at a record date inside a quarter (ANANDRATHI's 2026-06-04)
        # is not a comparable point, while one NEWER than the last quarter end (PERSISTENT's 2026-10-26) is the
        # newest filing and stays (T-165).
        ends = [q for q in qlist if q[5:10] in _QUARTER_ENDS]
        if ends:
            qlist = [q for q in qlist if q not in ends and q > ends[0]] + ends
        qlist = qlist[:want]
        picked, _held = _holding_categories(sym, category, extra, eargs)
        flt = f" AND category IN ({','.join('?' * len(picked))})" if picked else ""
        # a category was asked and no filed name matches it: no row is the answer, never every row
        cand = [] if (category and not picked) else _q(
            f"SELECT rowid, * FROM shp_category WHERE symbol=?{extra}{flt} "
            f"AND quarter_end IN ({','.join('?' * len(qlist))}) "
            "ORDER BY quarter_end DESC, category, (source_kind='xbrl') DESC, known_at DESC",
            (sym, *eargs, *picked, *qlist))
        seen = set()
        for r in cand:
            keys = r.keys()
            pct_base = r["pct_base_shares"] if "pct_base_shares" in keys else None
            pct_label = r["pct_basis"] if "pct_basis" in keys else None
            if pct_base is not None:
                basis = basis or {"shares": pct_base, "label": pct_label,
                                  "provenance": _prov("shp_category", r["source_file"], r["known_at"])}
            sig = (r["quarter_end"], r["category"])   # one value per category and quarter, XBRL first
            if sig in seen:
                continue
            seen.add(sig)
            rows.append({"category": r["category"], "pct": r["pct"], "shares": r["shares"], "holders": r["holders"],
                         "quarter_end": r["quarter_end"], "source_kind": r["source_kind"],
                         "pct_basis": pct_label, "pct_base_shares": pct_base,
                         "provenance": _prov("shp_category", f"{r['source_file'] or ''} [{r['source_db']}.{r['source_table']} "
                                             f"row {r['source_rowid']}]".strip(), r["known_at"],
                                             category_raw=r["category_raw"])})
    named: list[dict] = []
    if quarter and _has_table("shp_holder"):
        flt = "" if all_holders else " AND category NOT LIKE 'pac_%'"
        cap = MAX_LIMIT * 10 if all_holders else HOLDING_TOP
        for r in _q(f"SELECT rowid, * FROM shp_holder WHERE symbol=? AND quarter_end=?{extra}{flt} "
                    "ORDER BY shares IS NULL, shares DESC, holder_name LIMIT ?", (sym, quarter, *eargs, cap)):
            named.append({"holder": r["holder_name"], "category": r["category"], "shares": r["shares"], "pct": r["pct"],
                          "holders": r["holders"], "pac_name": r["pac_name"], "pac_pct": r["pac_pct"],
                          "pledged_shares": r["pledged_shares"],
                          "provenance": _prov("shp_holder", f"{r['source_file'] or ''} [{r['source_db']}.{r['source_table']}]",
                                              r["known_at"])})
    pledge = None
    if quarter and _has_table("shp_pledge"):
        pr = _q(f"SELECT rowid, * FROM shp_pledge WHERE symbol=? AND quarter_end=?{extra} "
                "ORDER BY known_at DESC LIMIT 1", (sym, quarter, *eargs))
        if pr:
            pledge = _pledge_block(pr[0])
            # "has it changed?": the quarter before, from its own filing (T-108)
            prev = _q(f"SELECT rowid, * FROM shp_pledge WHERE symbol=? AND quarter_end<?{extra} "
                      "ORDER BY quarter_end DESC, known_at DESC LIMIT 1", (sym, quarter, *eargs))
            if prev:
                before = _pledge_block(prev[0])
                pledge["previous_quarter"] = {k: before[k] for k in ("quarter_end", "nil", "pledged_shares",
                                                                     "pledged_pct_of_promoter_holding", "answer",
                                                                     "provenance")}
                now_pct, then_pct = pledge["pledged_pct_of_promoter_holding"], before["pledged_pct_of_promoter_holding"]
                pledge["changed"] = None if now_pct is None or then_pct is None else now_pct != then_pct
    sc = _q(f"SELECT rowid, * FROM share_capital WHERE symbol=? AND event IS NULL AND as_of_date<=?{extra} "
            "AND shares_outstanding IS NOT NULL ORDER BY as_of_date DESC, (source_table='shp_category') DESC, "
            "known_at DESC LIMIT 1", (sym, day, *eargs))
    shares = None
    if sc:
        r = sc[0]
        shares = {"shares_outstanding": r["shares_outstanding"], "paid_up_capital": r["paid_up_capital"],
                  "face_value": r["face_value"], "as_of_date": r["as_of_date"], "basis": r["basis"],
                  "provenance": _prov("share_capital", f"{r['source_db']}.{r['source_table']} row {r['source_rowid']}",
                                      r["known_at"])}
    categories = [r[0] for r in _q(f"SELECT DISTINCT category FROM shp_category WHERE symbol=?{extra} "
                                   "ORDER BY category LIMIT 60", (sym, *eargs))]
    hint = None
    if not rows:
        if category and not picked:
            hint = f"no filed category matches {category!r}: categories_held lists the names this company holds"
        elif category:
            hint = (f"{picked} has no row in the last {len(qlist) if quarter else 0} quarter(s) in force; "
                    "quarters_held lists what the table covers")
        else:
            hint = "no shareholding row filed by that day for this company"
    return _reply(sym, rows, "pilot3_holding", quarter_end=quarter, as_of=day, share_capital=shares,
                  holders=named, holders_note=None if named else "no named holder row for this quarter "
                  "(the build predates shp_holder, or the filing names none)",
                  promoter_pledge=pledge, pct_basis=basis,
                  category_filter=category, matched_categories=picked,
                  quarters_returned=sorted({r["quarter_end"] for r in rows}, reverse=True),
                  quarters_held={"first": held[0], "last": held[1], "count": held[2]},
                  categories_held=categories, hint=hint)


# --- pilot3_statements ------------------------------------------------------------------------------
def _term_hits(column: str, words: list[str]) -> tuple[str, list]:
    """SQL that scores a row by how many of ``words`` it carries (0 when no word was asked)."""
    if not words:
        return "0", []
    expr = " + ".join(f"({column} LIKE ?)" for _ in words)
    return expr, [f"%{word}%" for word in words]


def _turn_key(row: Any) -> tuple:
    """Identity of a whole answer turn: (document, answer_turn).  Answer-turn ids are per call (two calls of one
    company collide) and prepared remarks carry negative ids, so a bare id is never a turn (T-164 r8)."""
    return (row["doc_key"], row["answer_turn"]) if row["answer_turn"] else ("row", row["id"])


def statements(symbol: str, topic: str | None = None, terms: str | None = None, date_from: str | None = None,
               date_to: str | None = None, as_of: str | None = None, limit: int = 10,
               role: str | None = None, period: str | None = None,
               rank_terms: str | None = None, latest: bool = False,
                entities: str | None = None, whole_turn: bool = True) -> dict[str, Any]:
    """Management statements from concall transcripts, exact quotes: topic tag (margin, guidance, capex, order ...),
    free ``terms`` (all words must appear), call-date window, role (ceo / cfo / md / mgmt).

    ``period`` (Q4FY26 / FY26) and ``rank_terms`` (the question's own words) rank the rows: a statement of the
    period asked, carrying more of the question's words, comes first; the newest call breaks a tie.  ``latest``
    keeps only the newest call's statements."""
    sym = resolve_symbol(symbol)
    where, args = "t.symbol=?", [sym]
    if latest:
        extra_latest, latest_args = _asof(as_of, "t2.known_at")
        where += (f" AND t.call_date=(SELECT MAX(t2.call_date) FROM transcript_statement t2 "
                  f"WHERE t2.symbol=?{extra_latest})")
        args += [sym, *latest_args]
    topic_sql, topic_args = "1", []
    if topic:
        # the tag ranks first rather than filtering: the sentence that answers a "what did they say about margins"
        # question is often tagged ``nim`` (or untagged) instead of ``margin``
        topic_sql = "t.topics LIKE ?"
        topic_args = [f"%{topic.strip().lower()}%"]
    for word in re.findall(r"[\w₹%&\-\.]+", terms or ""):
        where += " AND (t.statement LIKE ? OR t.quote LIKE ?)"
        args += [f"%{word}%", f"%{word}%"]
    if entities:
        for word in re.findall(r"[\w₹%&\-\.]+", entities or ""):
            where += " AND t.entities LIKE ?"
            args += [f"%{word}%"]
    if role:
        where += " AND t.role=?"
        args.append(role.strip().lower())
    for col, val, op in (("t.call_date", _day(date_from, "date_from"), ">="), ("t.call_date", _day(date_to, "date_to"), "<=")):
        if val:
            where += f" AND {col} {op} ?"
            args.append(val)
    extra, eargs = _asof(as_of, "t.known_at")
    _kind, label = norm_period(period)
    period_sql, period_args = "1", []
    if label:
        # a year's question is answered by its quarters too ("FY26": Q1FY26 ... Q4FY26)
        labels = ([f"Q{q}FY{label[2:]}" for q in (1, 2, 3, 4)] + [label]) if label.startswith("FY") else [label]
        period_sql = "(" + " OR ".join("(t.call_period=? OR t.period_discussed LIKE ?)" for _x in labels) + ")"
        for item in labels:
            period_args += [item, f"{item}%"]
    words = [w for w in re.findall(r"[\w₹%&\-\.]+", rank_terms or "") if len(w) > 2]
    score_sql, score_args = _term_hits("t.statement", words[:8])
    cap = _cap(limit)
    # whole_turn: `limit` counts answer turns, not sentences, so fetch enough rows to find that many turns
    # (T-164 r7: limit=20 used to return 188 rows because the LIMIT bounded matched sentences before expansion)
    row_cap = cap * 50 if whole_turn else cap
    rows = _q(f"SELECT t.id, t.call_date, t.call_period, t.page, t.speaker, t.role, t.section, t.topics, "
              f"t.period_discussed, t.quote, t.is_fragment, t.entities, t.answer_turn, t.known_at, t.doc_key, d.title, "
              f"(CASE WHEN {topic_sql} THEN 0 ELSE 1 END) AS topic_rank, "
              f"(CASE WHEN {period_sql} THEN 0 ELSE 1 END) AS period_rank, ({score_sql}) AS term_score "
              f"FROM transcript_statement t "
              f"LEFT JOIN doc d ON d.doc_key=COALESCE((SELECT a.doc_key FROM doc_alias a WHERE a.symbol=t.symbol "
              f"AND a.alias_key=t.doc_key), t.doc_key) WHERE {where}{extra} "
              f"ORDER BY topic_rank, period_rank, term_score DESC, t.is_fragment, t.call_date DESC, t.seq LIMIT ?",
              # the SELECT-list placeholders bind before the WHERE ones
              (*topic_args, *period_args, *score_args, *args, *eargs, row_cap))
    if whole_turn and rows:
        kept, seen = [], set()
        for r in rows:
            key = _turn_key(r)
            if key in seen:
                continue
            seen.add(key)
            kept.append(key)
            if len(kept) >= cap:
                break
        rows = [r for r in rows if _turn_key(r) in seen]
    out = [{"id": r["id"], "call_date": r["call_date"], "call_period": r["call_period"], "speaker": r["speaker"],
            "role": r["role"], "section": r["section"], "topics": r["topics"],
            "period_discussed": r["period_discussed"], "entities": r["entities"], "answer_turn": r["answer_turn"],
            "quote": _trim(r["quote"]),
            "provenance": _prov("transcript_statement", f"{r['doc_key']} p{r['page']}", r["known_at"],
                                title=r["title"], row_id=r["id"])} for r in rows]
    # whole answer turn: expand each matched row to all sentences of its answer turn, keyed by (document, turn):
    # answer-turn ids collide across calls and prepared-remark ids are negative, so a bare id mixed two calls and
    # swept prepared remarks in (T-164 r8).  A prepared-remarks turn expands only when it was itself selected.
    extra, eargs = _asof(as_of, "t.known_at")
    if whole_turn and rows:
        keys = {_turn_key(r) for r in rows if r["answer_turn"]}
        if keys:
            turn_rows = []
            doc_keys = sorted({r["doc_key"] for r in rows})
            dk_placeholders = ",".join("?" * len(doc_keys))
            tr = _q(f"SELECT t.id, t.call_date, t.call_period, t.page, t.speaker, t.role, t.section, t.topics, "
                    f"t.period_discussed, t.quote, t.is_fragment, t.entities, t.answer_turn, t.known_at, t.doc_key, d.title "
                    f"FROM transcript_statement t LEFT JOIN doc d ON d.doc_key=COALESCE((SELECT a.doc_key FROM doc_alias a "
                    f"WHERE a.symbol=t.symbol AND a.alias_key=t.doc_key), t.doc_key) "
                    f"WHERE t.symbol=? AND t.doc_key IN ({dk_placeholders}){extra} "
                    f"ORDER BY t.call_date DESC, t.seq",
                    (sym, *doc_keys, *eargs))
            seen_ids = {r["id"] for r in rows}
            for r in tr:
                if r["id"] in seen_ids or _turn_key(r) not in keys:
                    continue
                seen_ids.add(r["id"])
                turn_rows.append(r)
            if turn_rows:
                extra_rows = [{"id": r["id"], "call_date": r["call_date"], "call_period": r["call_period"],
                               "speaker": r["speaker"], "role": r["role"], "section": r["section"],
                               "topics": r["topics"], "period_discussed": r["period_discussed"],
                               "entities": r["entities"], "answer_turn": r["answer_turn"],
                               "quote": _trim(r["quote"]),
                               "provenance": _prov("transcript_statement", f"{r['doc_key']} p{r['page']}", r["known_at"],
                                                   title=r["title"], row_id=r["id"])} for r in turn_rows]
                out = out + extra_rows
    # drop helper id from output
    for r in out:
        r.pop("id", None)
    matched = any(topic in (row["topics"] or "") for row in out) if topic else None
    fallback = None
    if topic and not matched:
        # the tagger never emitted this topic: search the calls' own page text before answering "nothing said"
        alt = _call_page_hits(sym, topic, terms, rank_terms, date_from, date_to, as_of, latest, _cap(limit))
        if alt:
            out, fallback = alt, "doc_page_bm25"
    return _reply(sym, out, "pilot3_statements", fallback=fallback,
                  topic_matched=matched, hint=None if out else "no statement in the held calls matches these arguments")


def analyst_questions(symbol: str, n_calls: int = 4, as_of: str | None = None) -> dict[str, Any]:
    sym = resolve_symbol(symbol)
    extra, eargs = _asof(as_of, "known_at")
    calls = [r[0] for r in _q("SELECT DISTINCT call_date FROM transcript_question WHERE symbol=?" + extra +
                                " ORDER BY call_date DESC LIMIT ?", (sym, *eargs, max(1, min(int(n_calls or 4), 20))))]
    if not calls:
        return _reply(sym, [], "pilot3_analyst_questions", hint="no analyst questions held")
    placeholders = ",".join("?" * len(calls))
    rows = _q("SELECT id, call_date, call_period, analyst, firm, question, topics, entities, known_at, doc_key "
              "FROM transcript_question WHERE symbol=? AND call_date IN (" + placeholders + ")" + extra +
              " ORDER BY call_date DESC, id", (sym, *calls, *eargs))
    out = [{"call_date": r["call_date"], "call_period": r["call_period"], "analyst": r["analyst"],
            "firm": r["firm"], "question": _trim(r["question"]), "topics": r["topics"],
            "entities": r["entities"],
            "provenance": _prov("transcript_question", r["doc_key"], r["known_at"], row_id=r["id"])}
           for r in rows]
    return _reply(sym, out, "pilot3_analyst_questions", n_calls=len(calls))


def _call_page_hits(sym: str, topic: str, terms: str | None, rank_terms: str | None, date_from: str | None,
                    date_to: str | None, as_of: str | None, latest: bool, cap: int) -> list[dict]:
    """bm25 over the transcript ``doc_page`` text when ``transcript_statement`` has no row carrying the topic tag:
    the page's own sentence around the match, newest call first.  Empty when the pages carry nothing either."""
    words = [w for w in re.findall(r"[\w₹%&\-\.]+", " ".join(x for x in (topic, terms, rank_terms) if x or ""))
             if len(w) > 2][:8]
    if not words:
        return []
    match = _fts_query(" ".join(words), "and") or _fts_query(" ".join(words), "or")
    if not match:
        return []
    extra, eargs = _asof(as_of, "COALESCE(p.known_at, d.known_at)")
    date_sql, date_args = "", []
    for col, val, op in (("d.filing_date", _day(date_from, "date_from"), ">="),
                         ("d.filing_date", _day(date_to, "date_to"), "<=")):
        if val:
            date_sql += f" AND {col} {op} ?"
            date_args.append(val)
    latest_sql, latest_args = "", []
    if latest:
        latest_sql = (" AND COALESCE(d.known_at, d.filing_date)=(SELECT MAX(COALESCE(d2.known_at, d2.filing_date)) "
                      "FROM doc d2 WHERE d2.symbol=? AND d2.doc_type='transcript')")
        latest_args = [sym]
    rows = _q(f"SELECT d.doc_key, d.title, d.filing_date, p.page, p.known_at, "
              f"snippet(doc_page_fts, 0, '[', ']', ' … ', 40) snip FROM doc_page_fts f "
              f"JOIN doc_page p ON p.rowid=f.rowid JOIN doc d ON d.doc_key=p.doc_key "
              f"WHERE doc_page_fts MATCH ? AND p.symbol=? AND d.doc_type='transcript'{date_sql}{latest_sql}{extra} "
              f"ORDER BY d.filing_date DESC, rank LIMIT ?",
              (match, sym, *date_args, *latest_args, *eargs, cap))
    return [{"call_date": r["filing_date"], "call_period": None, "speaker": None, "role": None,
             "section": None, "topics": None, "period_discussed": None, "quote": _trim(r["snip"], QUOTE_CHARS),
             "provenance": _prov("doc_page", f"{r['doc_key']} p{r['page']}", r["known_at"] or None,
                                 title=_trim(r["title"], 120))} for r in rows]


# --- pilot3_guidance --------------------------------------------------------------------------------
GUIDANCE_METRICS = ("revenue_growth", "ebitda_margin", "order_intake", "nim", "credit_cost", "aum_growth",
                    "capex", "cost_of_production", "interest_cost", "ebitda_per_tonne", "new_loans",
                    "new_customers", "opex_to_nti", "other")


def guidance(symbol: str, metric: str | None = None, period: str | None = None, as_of: str | None = None,
             limit: int = 12, history: bool = False, include_quarantined: bool = False) -> dict[str, Any]:
    """Rule-extracted forward guidance: the CURRENT target of each metric and target period, newest first, with
    the row it revised (``revision_of`` and the previous low/high/date, so "did the guidance change between the
    two calls" is one call).  An older row of the same metric+period that a later document replaced is dropped and
    the kept row says how many (``superseded_rows``); ``history=true`` returns every row as stored.  ``low`` and
    ``high`` are NULL on a target said in words ("high single-digit", "in the 70s, mid-70s or higher"): the
    direction and the quote carry it.  A row the independent checker quarantined is hidden unless
    ``include_quarantined=True``, and every row says ``check_status`` verified or unverified (T-113)."""
    sym = resolve_symbol(symbol)
    names, allnames = ([], list(GUIDANCE_METRICS))
    if metric:
        names, allnames = _pick("guidance", "metric", sym, metric,
                                extra="" if include_quarantined else _visible("guidance"))
        if not names:
            return _reply(sym, [], "pilot3_guidance", available=allnames[:40], metric_asked=metric)
    kind, label = norm_period(period)
    where, args = "g.symbol=?", [sym]
    if names:
        where += f" AND g.metric IN ({','.join('?' * len(names))})"
        args += names
    if kind and label:
        where += " AND g.target_period=?"
        args.append(label)
    join, check_sel, hide = _check_cols("guidance", "g.id")
    if not include_quarantined:
        where += hide
    extra, eargs = _asof(as_of, "g.known_at")
    rows = _q(f"SELECT g.id, g.metric, g.target_period, g.low, g.high, g.unit, g.direction, g.said_on, g.doc_key, "
              f"g.page, g.quote, g.speaker, g.known_at, g.revision_of, g.extractor_rule, d.title, d.doc_type, "
              f"pv.low prev_low, pv.high prev_high, pv.said_on prev_said_on, pv.direction prev_direction{check_sel} "
              f"FROM guidance g LEFT JOIN doc d ON d.doc_key=g.doc_key "
              f"LEFT JOIN guidance pv ON pv.id=g.revision_of{join} WHERE {where}{extra} "
              f"ORDER BY COALESCE(g.known_at, g.said_on) DESC, g.id DESC LIMIT 400", (*args, *eargs))
    out = []
    kept = [dict(r) for r in rows]
    if not history:
        kept = _guidance_current_rows(kept)   # the current target per metric+period, with its dropped-row count
    for r in kept[:_cap(limit)]:
        previous = None
        if r["revision_of"] is not None:
            previous = {"row_id": r["revision_of"], "low": r["prev_low"], "high": r["prev_high"],
                        "said_on": r["prev_said_on"], "direction": r["prev_direction"]}
        out.append(_add_check({"metric": r["metric"], "period": r["target_period"], "low": r["low"],
                               "high": r["high"], "unit": r["unit"], "direction": r["direction"],
                               "said_on": r["said_on"], "quote": _trim(r["quote"]), "speaker": r["speaker"],
                               "revision_of": r["revision_of"], "previous": previous,
                               "changed": bool(previous and (previous["low"], previous["high"]) != (r["low"], r["high"])),
                               "superseded_rows": 0 if history else r["superseded_rows"],
                               "provenance": _prov("guidance", f"{r['doc_key']} p{r['page']}", r["known_at"],
                                                   doc_type=r["doc_type"], title=_trim(r["title"], 120),
                                                   row_id=r["id"])}, r))
    held = None
    if not out:   # say what the table does hold, so the next call can be exact
        held = [f"{r[0]} / {r[1]} ({r[2]} rows)" for r in _q(
            f"SELECT metric, target_period, COUNT(*) FROM guidance WHERE symbol=?"
            + (f" AND metric IN ({','.join('?' * len(names))})" if names else "")
            + _visible("guidance") + " GROUP BY 1, 2 ORDER BY MAX(known_at) DESC LIMIT 40", (sym, *names))]
    return _reply(sym, out, "pilot3_guidance", metrics_matched=names or None, history=True if history else None,
                  held_options=held)


# --- pilot3_docs ------------------------------------------------------------------------------------
def docs(symbol: str, doc_type: str | None = None, date_from: str | None = None, date_to: str | None = None,
         as_of: str | None = None, limit: int = 20) -> dict[str, Any]:
    """The documents pilot3 holds for a company, newest first (known_at = filing record), with page counts."""
    sym = resolve_symbol(symbol)
    where, args = "symbol=?", [sym]
    if doc_type:
        dtype = _DOC_TYPES.get(doc_type.strip().lower(), doc_type.strip().lower())
        where += " AND doc_type=?"
        args.append(dtype)
    for val, op in ((_day(date_from, "date_from"), ">="), (_day(date_to, "date_to"), "<=")):
        if val:
            where += f" AND substr(COALESCE(known_at, filing_date),1,10) {op} ?"
            args.append(val)
    extra, eargs = _asof(as_of)
    rows = _q(f"SELECT doc_key, doc_type, title, filing_date, known_at, pages, source, source_key FROM doc "
              f"WHERE {where}{extra} ORDER BY known_at DESC LIMIT ?", (*args, *eargs, _cap(limit, 20)))
    counts = {r[0]: r[1] for r in _q(f"SELECT doc_type, COUNT(*) FROM doc WHERE {where}{extra} GROUP BY doc_type",
                                     (*args, *eargs))}
    return _reply(sym, [{"doc_key": r["doc_key"], "doc_type": r["doc_type"], "title": _trim(r["title"], 160),
                         "filing_date": r["filing_date"], "pages": r["pages"],
                         "provenance": _prov("doc", r["source_key"] or r["source"], r["known_at"])} for r in rows],
                  "pilot3_docs", counts_by_type=counts)


# --- pilot3_search ----------------------------------------------------------------------------------
def _fts_query(text: str, mode: str) -> str:
    words = [w for w in re.findall(r"[\w₹%]+", text or "") if len(w) > 1 or w.isdigit()]
    return (" AND " if mode == "and" else " OR ").join(f'"{w}"' for w in words[:12])


_FY_TEXT = re.compile(r"(Q[1-4]|H[12])?\s*FY\s*'?\s*(\d{2,4})", re.I)


def _period_labels(text: str) -> list[str]:
    """['Q1FY27', 'FY26'] for the fiscal periods printed in a query ("Q1 FY27 results")."""
    out: list[str] = []
    for match in _FY_TEXT.finditer(text or ""):
        kind = (match.group(1) or "FY").upper()
        label = f"{kind}FY{match.group(2)[-2:]}"
        if label not in out:
            out.append(label)
    return out[:3]


def _period_in(text: str, label: str) -> bool:
    """Does a page print the period ("Q1FY27": Q1 FY27, Q1FY27, Q1 FY '27, Q1 FY2027; "FY26": FY26, FY '26, FY2026)?"""
    match = re.fullmatch(r"(Q[1-4]|H[12]|FY)FY(\d{2})", label or "")
    if not match:
        return False
    kind = match.group(1)
    year = f"(?:{match.group(2)}|20{match.group(2)})"
    pattern = rf"(?:\b{kind}\s*FY\s*'?\s*{year}\b)" if kind != "FY" else rf"\bFY\s*'?\s*{year}\b"
    return bool(re.search(pattern, text or "", re.I))


def _rank_hits(rows: list[sqlite3.Row], exact: set[int], or_ids: set[int], period: str | None,
               date_from: str | None, date_to: str | None, dtype: str | None) -> list[sqlite3.Row]:
    """bm25 order with a boost for an all-word match, the period asked, the filing window and the document type.

    bm25's own scale is not comparable across queries, so it is normalised inside the OR candidate set (1 = best
    match, the only set every row's rank comes from) and the boosts are added to that: the page that prints the
    quarter and was filed in the window the question names outranks a page that only happens to repeat its words.
    """
    ranks = [row["rank"] for row in rows if row["rid"] in or_ids]
    low = min(ranks) if ranks else 0.0
    scored = []
    for index, row in enumerate(rows):
        if row["rid"] in or_ids:
            # bm25's scale is not comparable across queries: the best hit is 1.0 and the rest keep their distance
            # from it as a ratio, so a boost means the same thing whatever the query's size.
            score = row["rank"] / low if low else 1.0
        else:
            score = 1.0                                   # an all-word hit outside the OR top
        if row["rid"] in exact:
            score += 0.20                                    # every query word is on the page
        day = str(row["filing_date"] or row["pk"] or row["dk"] or "")[:10]
        if date_from and date_to and date_from <= day <= date_to:
            score += 0.35                                    # filed inside the window the question names
        if period and _period_in(row["text"], period):
            score += 0.35                                    # the page prints the period asked
        if dtype and row["doc_type"] == dtype:
            score += 0.20                                    # the document type the question names
        scored.append((score, index, row))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [row for _score, _index, row in scored]


def search(symbol: str, query: str, as_of: str | None = None, limit: int = 10,
           doc_type: str | None = None, period: str | None = None,
           date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
    """Full-text search over every held page (FTS5 bm25, ranked); exact snippet around the match, page and filing
    date.  ``period`` (Q1FY27 / FY26), ``date_from``+``date_to`` and ``doc_type`` boost the pages that print the
    period / were filed in the window / are of that document type."""
    sym = resolve_symbol(symbol)
    extra, eargs = _asof(as_of, "COALESCE(p.known_at, d.known_at)")
    dflt, dargs = "", ()
    dtype = _DOC_TYPES.get(doc_type.strip().lower(), doc_type.strip().lower()) if doc_type else None
    if dtype:
        dflt, dargs = " AND d.doc_type=?", (dtype,)
    start, end = _day(date_from, "date_from"), _day(date_to, "date_to")
    cap = _cap(limit)
    # the period the caller names is normalised to the label the pages print (FY27, Q1FY27), never prefixed twice:
    # norm_period('FY27') is ('FY', 'FY27'), so the reply can only ever echo a canonical label.
    kind, label = norm_period(period)
    labels = [label] if kind else _period_labels(query)
    period = labels[0] if labels else None
    select = (f"SELECT p.rowid rid, p.doc_key, p.page, p.text, p.known_at pk, d.known_at dk, d.doc_type, "
              f"d.title, d.filing_date, rank, snippet(doc_page_fts, 0, '[', ']', ' … ', 40) snip "
              f"FROM doc_page_fts f JOIN doc_page p ON p.rowid=f.rowid JOIN doc d ON d.doc_key=p.doc_key "
              f"WHERE doc_page_fts MATCH ? AND p.symbol=?{dflt}{extra} ORDER BY rank LIMIT ?")
    rows_or, rows_and = [], []
    for mode in ("or", "and"):
        match = _fts_query(query, mode)
        if not match:
            raise DataError("bad_query", "query needs at least one word")
        found_rows = _q(select, (match, sym, *dargs, *eargs, cap * 20))
        if mode == "or":
            rows_or = found_rows
        else:
            rows_and = found_rows
        if mode == "or" and not rows_and and _fts_query(query, "and") == match:
            rows_and = rows_or       # one word: the two queries are the same
    or_ids = {row["rid"] for row in rows_or}
    exact = {row["rid"] for row in rows_and}
    found: dict[int, sqlite3.Row] = {row["rid"]: row for row in rows_or}
    for row in rows_and:
        found.setdefault(row["rid"], row)
    rows = _rank_hits(list(found.values()), exact, or_ids, period, start, end, dtype)[:cap]
    match_mode = None if not rows else ("and" if rows[0]["rid"] in exact else "or")
    return _reply(sym, [{"doc_type": r["doc_type"], "title": _trim(r["title"], 120), "filing_date": r["filing_date"],
                         "page": r["page"], "snippet": _trim(r["snip"], 420),
                         "provenance": _prov("doc_page", f"{r['doc_key']} p{r['page']}", r["pk"] or r["dk"])}
                        for r in rows], "pilot3_search", match_mode=match_mode, period=period)


# --- pilot3_sql -------------------------------------------------------------------------------------
SQL_TEXT_CHARS = 400          # the per-cell cut the answer tools have always used
SQL_MAX_TEXT_CHARS = 8000     # hard cap: long page text must be asked for, never returned by default


def _as_of_connection(day: str) -> sqlite3.Connection:
    """A private read-only connection on which every table with a ``known_at`` column (and ``doc_page`` through
    its ``doc``) is shadowed by a TEMP view holding only rows known on or before ``day`` (T-156: answers read
    transcripts filed after the question date through sql)."""
    con = core.connect_ro(db_path(), timeout_s=core.READ_TIMEOUT_S, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=0")   # TEMP views only; the main file stays mode=ro, so nothing can be written
    tables = [r[0] for r in con.execute("SELECT name FROM main.sqlite_master WHERE type='table' "
                                         "AND name NOT LIKE '%fts%' AND name NOT LIKE 'sqlite_%'")]
    for table in tables:
        if table == "doc_page":
            con.execute(f"CREATE TEMP VIEW doc_page AS SELECT p.* FROM main.doc_page p JOIN main.doc d "
                        f"ON d.doc_key = p.doc_key WHERE substr(COALESCE(p.known_at, d.known_at), 1, 10) <= '{day}'")
            continue
        cols = {r[1] for r in con.execute(f'PRAGMA main.table_info("{table}")')}
        if "known_at" in cols:
            con.execute(f'CREATE TEMP VIEW "{table}" AS SELECT * FROM main."{table}" '
                        f"WHERE known_at IS NOT NULL AND substr(known_at, 1, 10) <= '{day}'")
    con.execute("PRAGMA query_only=1")
    return con


def sql(query: str, limit: int = 100, timeout_seconds: float = 5.0,
        max_chars: int = SQL_TEXT_CHARS, as_of: str | None = None) -> dict[str, Any]:
    """Bounded, read-only SELECT/WITH over the pilot3 database (``REALITY_PILOT3_DB`` names another build; any
    table or view; see ``schema`` rows below on a miss).

    Financial figures: ``fin_quarter_current`` gives the one preferred line per (symbol, fiscal_period, basis,
    line_item) now, and ``preferred_from`` / ``preferred_to`` on ``fin_quarter_xbrl`` and ``fin_quarter_printed``
    elect it at any past day (preferred when ``preferred_from <= day`` and (``preferred_to IS NULL`` or
    ``preferred_to > day``)); ``pilot3_fin`` returns the same figure.  The raw tables hold every filing's printing
    of the same line, so a sum over them counts a restatement and its original twice.
    Text cells are cut at ``max_chars`` (default 400, hard cap 8000): a question about wording, a whole
    paragraph or a long quote passes ``max_chars`` explicitly, otherwise the page text is truncated.
    ``as_of`` (YYYY-MM-DD): every table with a ``known_at`` column, and ``doc_page`` through its document, shows
    only rows known on or before that day (T-156); pass it for any dated question.  ``doc_page_fts`` is not
    filtered itself, so join its hits to ``doc_page``."""
    text = core._strip_sql(query or "")
    if not text:
        raise DataError("bad_query", "pilot3_sql needs a SELECT or WITH query")
    if len(core._statements(text)) != 1:
        raise DataError("not_select", "only one read-only statement is allowed")
    if not re.match(r"^(SELECT|WITH)\b", text, re.IGNORECASE):
        raise DataError("not_select", "only SELECT / WITH queries are allowed")
    if core._WRITE_WORDS.search(text):
        raise DataError("not_select", "write/DDL keywords are not allowed")
    limit = max(1, min(int(limit), 500))
    try:
        chars = max(1, min(int(max_chars), SQL_MAX_TEXT_CHARS))
    except (TypeError, ValueError):
        raise DataError("bad_max_chars", f"max_chars must be an integer 1..{SQL_MAX_TEXT_CHARS}")
    started = time.perf_counter()
    day = _day(as_of, "as_of") if as_of else None
    con = _as_of_connection(day) if day else connect()
    wrapped = f"SELECT * FROM ({text}) AS _q LIMIT {limit + 1}"
    try:
        cur = con.execute(wrapped)
        columns = [d[0] for d in cur.description]
        raw = cur.fetchall()
    except core.QueryTimeout as exc:
        raise DataError("query_timeout", str(exc))
    except sqlite3.DatabaseError as exc:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '%fts%'")]
        raise DataError("sql_error", f"{type(exc).__name__}: {exc}. Tables: {', '.join(tables)}")
    finally:
        if day:
            con.close()
    rows = [[core._jsonable(v) if not isinstance(v, str) else _trim(v, chars) for v in r] for r in raw[:limit]]
    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": len(raw) > limit, "as_of": day,
            "max_chars": chars, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "provenance": _db_prov(note="read-only SELECT/WITH, row-limited")}
